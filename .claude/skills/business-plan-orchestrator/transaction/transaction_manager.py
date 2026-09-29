#!/usr/bin/env python3
"""transaction_manager — recoverable all-or-nothing transaction semantics.

Unico scrittore canonico: snapshot immutabile del candidate in shared/.tx/,
ri-esecuzione autonoma dei validator egress sullo snapshot (validation
binding), snapshot dello stato canonico, allocazione deterministica
P-ASS-* -> ASS-* in fase applying, sostituzione dei riferimenti, scrittura di
registri/structured-output/handoff/project-status/audit-log nella stessa
transazione recuperabile, journal shared/.tx/<tx>.json con write-set e hash
attesi, marker `committed` scritto per ultimo, recovery con verifica di
contenuto (mai per sola esistenza dei file), rollback da snapshot,
single-writer lock con process identity (PID + create time + token) e
scritture di governance journaled su project-status.md.

Path containment: ogni path letto/scritto/cancellato dal
transaction manager passa da un boundary centralizzato — journal validato
strutturalmente prima dell'uso, path relativi normalizzati, niente assoluti
né `..`, snapshot solo dentro shared/.tx/, componenti symlink/junction/
reparse-point rifiutati. Un journal alterato non produce alcun I/O fuori dal
progetto.

Audit protocol: shared/audit-log.jsonl fa parte del write-set
transazionale; l'evento di commit è scritto e hash-verificato prima del
marker `committed`, ruota indietro col rollback e non viene mai duplicato da
retry/recovery.

Exit code CLI: 0 applicato/recovered; 1 rejected (validation binding, lock,
candidate); 2 uso/configurazione; 3 stato canonico o journal corrotto.

Hook di test (solo suite): BPO_TX_TEST_CRASH = "after_writes:N" |
"before_commit" simula un crash duro con os._exit (il lock resta su disco);
BPO_TX_TEST_FAIL_WRITE = <substring> fa fallire con OSError la write del
file corrispondente; BPO_TX_TEST_MUTATE_CANONICAL = "<rel>=<contenuto>"
simula uno scrittore concorrente sul canonico nella finestra fra
`validated` e `applying` (esercita il CAS di conferma, `canonical_drift`);
BPO_TX_TEST_CORRUPT_AFTER_WRITE = "<rel>=<contenuto>" corrompe un target del
write-set dopo la write e prima di `verify_write_set` (esercita
`content_verification_failed` e il rollback da snapshot). Tutti gli hook
sono inerti se la rispettiva variabile d'ambiente non è impostata.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import stat as stat_module
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "validators"))
import _framework as fw  # noqa: E402
import validate_referential_integrity as refint  # noqa: E402

TX_REL = "shared/.tx"
LOCK_NAME = "project.lock"
AUDIT_REL = "shared/audit-log.jsonl"
STATUS_REL = "shared/project-status.md"
REGISTER_REL = "shared/assumptions-register.json"
CONDITIONS_REL = "shared/conditions-register.json"
DECISIONS_REL = "shared/decisions-register.json"
DECISION_LOG_REL = "shared/decision-log.md"

P_ASS_TEXT_RE = re.compile(r"P-ASS-[0-9]{3,}")
ASS_NUM_RE = re.compile(r"^ASS-([0-9]{3}|[1-9][0-9]{3,})$")
P_ASS_NUM_RE = re.compile(r"^P-ASS-([0-9]{3}|[1-9][0-9]{3,})$")

JOURNAL_STATES = ("preparing", "snapshot_taken", "validated", "applying",
                  "committed", "rolled_back")
FINAL_STATES = ("committed", "rolled_back")

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# stati amministrativi impostabili via governance-status; nessuno
# stato approvativo (il gate si supera solo con advance-stage)
GOVERNANCE_ALLOWED_STATES = ("in_progress", "conflict_awaiting_confirmation",
                             "needs_revision", "blocked")

_write_counter = 0


class TransactionError(Exception):
    def __init__(self, code, message, exit_code=1):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


# hash dei sorgenti EFFETTIVAMENTE caricati da questo processo, catturati
# all'import (prima di ogni lock). Il journal registra questi hash per gli
# artefatti che il transaction manager importa (framework, DSL, refint): così
# l'hash identifica i byte che il processo esegue davvero, non un re-read
# successivo che potrebbe differire dai byte caricati.
_LOADED_SOURCE_HASHES = {}
for _loaded_src in (SKILL_ROOT / "validators" / "_framework.py",
                    SKILL_ROOT / "validators" / "formula_dsl.py",
                    SKILL_ROOT / "validators" /
                    "validate_referential_integrity.py"):
    try:
        _LOADED_SOURCE_HASHES[_loaded_src.relative_to(SKILL_ROOT).as_posix()] \
            = sha256_bytes(_loaded_src.read_bytes())
    except OSError:  # pragma: no cover - sorgenti sempre presenti a runtime
        pass


def hash_candidate(candidate):
    """Hash deterministico dell'intero candidate (path relativi + contenuti)."""
    digest = hashlib.sha256()
    candidate = Path(candidate)
    for path in sorted(candidate.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(candidate).as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


# --------------------------------------------------------------------------
# Path containment boundary: ogni path del journal e ogni
# target di lettura/scrittura/cancellazione/ripristino passa da qui.
# --------------------------------------------------------------------------

def safe_rel_path(rel, label="path"):
    """Path relativo POSIX canonico: niente assoluti, `..`, `.`, backslash,
    drive letter o componenti vuoti."""
    if not isinstance(rel, str) or not rel:
        raise TransactionError(
            "path_escape", f"{label} non valido: {rel!r}", exit_code=3)
    if "\\" in rel or ":" in rel or rel.startswith("/") or rel.startswith("~"):
        raise TransactionError(
            "path_escape", f"{label} non relativo/canonico: {rel!r}",
            exit_code=3)
    for part in rel.split("/"):
        if part in ("", ".", ".."):
            raise TransactionError(
                "path_escape", f"{label} con componente vietato: {rel!r}",
                exit_code=3)
    return rel


def _is_link_or_reparse(path):
    """True per symlink (ogni OS) e per junction/symlink reparse point NTFS."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat_module.S_ISLNK(st.st_mode):
        return True
    if os.name == "nt":
        attrs = getattr(st, "st_file_attributes", 0)
        if attrs & getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            tag = getattr(st, "st_reparse_tag", 0)
            if tag in (getattr(stat_module, "IO_REPARSE_TAG_SYMLINK", 0xA000000C),
                       getattr(stat_module, "IO_REPARSE_TAG_MOUNT_POINT",
                               0xA0000003)):
                return True
    return False


def resolve_in_project(project, rel, label="path"):
    """Risolve `rel` dentro `project` verificando ogni componente esistente
    contro symlink/junction/reparse e il containment finale."""
    rel = safe_rel_path(rel, label)
    project = Path(project)
    current = project
    for part in rel.split("/"):
        current = current / part
        if _is_link_or_reparse(current):
            raise TransactionError(
                "path_escape",
                f"{label} attraversa un symlink/reparse point: {rel!r}",
                exit_code=3)
    resolved_root = project.resolve()
    try:
        inside = current.resolve().is_relative_to(resolved_root)
    except OSError:
        inside = False
    if not inside:
        raise TransactionError(
            "path_escape", f"{label} fuori dal progetto: {rel!r}", exit_code=3)
    return current


def _require(cond, message, path):
    if not cond:
        raise TransactionError(
            "journal_corrupted",
            f"journal non valido ({Path(path).name}): {message}", exit_code=3)


JOURNAL_MODES = (None, "apply", "advance", "update_assumption",
                 "resolve_condition")


def authorized_write_paths(stage, mode=None):
    """Allow-list strutturale del write-set, specifica
    per **mode** oltre che per stage. Solo i target canonici di quel mode
    sono ammessi; qualsiasi altro path — anche se legittimo per un mode
    diverso — è un journal corrotto.

    La specializzazione per mode è necessaria: con
    un'unica allow-list per stage, un journal `update_assumption` alterato
    avrebbe potuto riscrivere il conditions-register o un output di stage, e
    un journal `apply` avrebbe potuto toccare il decisions-register."""
    if mode == "update_assumption":
        return {REGISTER_REL, DECISIONS_REL, DECISION_LOG_REL, STATUS_REL,
                AUDIT_REL}
    if mode == "resolve_condition":
        return {CONDITIONS_REL, DECISIONS_REL, DECISION_LOG_REL, STATUS_REL,
                AUDIT_REL}
    if mode in ("apply", "advance"):
        allowed = {REGISTER_REL, CONDITIONS_REL, STATUS_REL, AUDIT_REL}
        if isinstance(stage, str) and stage:
            allowed.add(f"{stage}/structured-output.json")
            allowed.add(f"{stage}/handoff.md")
        return allowed
    # journal di governance-status (mode assente/None): solo status e audit
    return {STATUS_REL, AUDIT_REL}


def validate_journal(journal, path):
    """Validazione strutturale del journal PRIMA di usare qualsiasi suo path
    (path containment). Un journal alterato non guida mai letture/scritture."""
    _require(isinstance(journal, dict), "non è un oggetto", path)
    tx = journal.get("transaction_id")
    _require(isinstance(tx, str) and SAFE_ID_RE.match(tx),
             "transaction_id mancante o non valido", path)
    _require(journal.get("state") in JOURNAL_STATES,
             f"stato sconosciuto: {journal.get('state')!r}", path)
    _require(journal.get("mode") in JOURNAL_MODES,
             f"mode sconosciuto: {journal.get('mode')!r}", path)
    stage = journal.get("stage")
    _require(stage is None or isinstance(stage, str),
             "stage non valido", path)
    write_set = journal.get("write_set")
    _require(isinstance(write_set, list), "write_set mancante", path)
    allowed_paths = authorized_write_paths(stage, journal.get("mode"))
    seen_paths = set()
    for entry in write_set:
        _require(isinstance(entry, dict), "voce write_set non oggetto", path)
        try:
            safe_rel_path(entry.get("path"), "write_set.path")
        except TransactionError as exc:
            _require(False, exc.message, path)
        # il write-set non può contenere path non autorizzati
        # per il proprio mode
        _require(entry.get("path") in allowed_paths,
                 f"write_set.path non autorizzato per mode "
                 f"{journal.get('mode')!r} / stage "
                 f"{stage!r}: {entry.get('path')!r}", path)
        # un path può comparire una sola volta. Il write-set nasce da
        # un dict `contents`, quindi i duplicati sono impossibili per
        # costruzione: se ce ne sono, il journal è stato alterato e non deve
        # guidare né una recovery né una scrittura.
        _require(entry.get("path") not in seen_paths,
                 f"write_set.path duplicato: {entry.get('path')!r}", path)
        seen_paths.add(entry.get("path"))
        pre = entry.get("pre_hash", "missing")
        _require(pre is None or (isinstance(pre, str) and SHA256_RE.match(pre)),
                 "pre_hash mancante o non valido", path)
        post = entry.get("post_hash")
        _require(isinstance(post, str) and SHA256_RE.match(post),
                 "post_hash mancante o non valido", path)
    for key in ("snapshot_path", "candidate_snapshot_path"):
        value = journal.get(key)
        if value is not None:
            try:
                safe_rel_path(value, key)
            except TransactionError as exc:
                _require(False, exc.message, path)
            _require(value.startswith(TX_REL + "/"),
                     f"{key} fuori da {TX_REL}/", path)
    _require(isinstance(journal.get("pass_map"), dict),
             "pass_map mancante", path)
    _require(isinstance(journal.get("timestamps"), dict),
             "timestamps mancanti", path)
    if journal["state"] == "applying":
        _require(journal.get("snapshot_path") is not None,
                 "applying senza snapshot_path", path)
        _require(len(write_set) > 0, "applying con write_set vuoto", path)
    return journal


def _test_mutation_hook(env_key, base_dir):
    """Hook per la suite: simula una scrittura concorrente su un file
    del candidate attivo o dello snapshot. Formato: "<rel>=<contenuto>"."""
    spec = os.environ.get(env_key, "")
    if not spec:
        return
    rel, _, content = spec.partition("=")
    target = Path(base_dir) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _crash_hook(point):
    """Simulazione crash per la suite: esce senza finally (lock resta)."""
    spec = os.environ.get("BPO_TX_TEST_CRASH", "")
    if not spec:
        return
    if spec == "before_commit" and point == "before_commit":
        os._exit(70)
    if spec.startswith("after_writes:") and point == "after_write":
        if _write_counter >= int(spec.split(":", 1)[1]):
            os._exit(70)


def write_file(path, data):
    global _write_counter
    path = Path(path)
    fail_spec = os.environ.get("BPO_TX_TEST_FAIL_WRITE", "")
    if fail_spec and fail_spec in path.as_posix():
        raise OSError(f"test-induced write failure: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    _write_counter += 1
    _crash_hook("after_write")


def save_journal(path, journal):
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(journal, indent=2, ensure_ascii=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def load_journal(path):
    # il file del journal non deve essere un symlink/reparse point
    # verso un contenuto fuori dall'area transazionale.
    if _is_link_or_reparse(path):
        raise TransactionError(
            "journal_corrupted",
            f"journal è un symlink/reparse point: {Path(path).name}",
            exit_code=3)
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TransactionError(
            "journal_corrupted", f"journal illeggibile: {path.name}: {exc}",
            exit_code=3)
    return validate_journal(journal, path)


def audit_event_line(transaction_id, stage, action, result, affected_refs,
                     operation_id=None):
    event = {
        "timestamp": now_iso(),
        "transaction_id": transaction_id,
        "stage": stage,
        "action": action,
        "result": result,
        "affected_refs": affected_refs,
    }
    # gli eventi dei comandi transazionali update-assumption e
    # resolve-condition tracciano l'identità dell'operazione. Il campo è
    # additivo: gli eventi degli altri comandi restano invariati.
    if operation_id is not None:
        event["operation_id"] = operation_id
    return json.dumps(event, ensure_ascii=True) + "\n"


def append_audit(project, transaction_id, stage, action, result,
                 affected_refs):
    """Append diretto: ammesso SOLO per eventi di governance senza mutazione
    canonica (rejected/rolled_back/recovery). L'evento di commit di una
    transazione passa dal write-set (audit protocol), mai da qui."""
    path = resolve_in_project(project, AUDIT_REL, "audit")
    line = audit_event_line(transaction_id, stage, action, result,
                            affected_refs)
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        # nessuna mutazione canonica in gioco: l'esito primario non cambia
        print(f"transaction_manager: audit append fallito: {exc}",
              file=sys.stderr)


# --------------------------------------------------------------------------
# Single-writer lock con process identity
# --------------------------------------------------------------------------

def _pid_alive(pid):
    """True/False se dimostrabile, None se ignoto (trattato come vivo)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                ERROR_INVALID_PARAMETER = 87
                if ctypes.get_last_error() == ERROR_INVALID_PARAMETER or \
                        kernel32.GetLastError() == ERROR_INVALID_PARAMETER:
                    return False
                return None
            try:
                code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle,
                                                   ctypes.byref(code)):
                    return None
                STILL_ACTIVE = 259
                return code.value == STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001
            return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:  # noqa: BLE001
        return None


def _process_create_time(pid):
    """Identity di creazione del processo (anti PID-reuse); None se ignota."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class FILETIME(ctypes.Structure):
                _fields_ = [("dwLowDateTime", wintypes.DWORD),
                            ("dwHighDateTime", wintypes.DWORD)]

            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return None
            try:
                creation, exited, kern, user = (FILETIME(), FILETIME(),
                                                FILETIME(), FILETIME())
                ok = kernel32.GetProcessTimes(
                    handle, ctypes.byref(creation), ctypes.byref(exited),
                    ctypes.byref(kern), ctypes.byref(user))
                if not ok:
                    return None
                return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
            finally:
                kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001
            return None
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii",
                                                   errors="replace")
        return int(text.rsplit(")", 1)[1].split()[19])
    except Exception:  # noqa: BLE001
        return None


def _lock_owner_alive(info):
    """Liveness del proprietario del lock: PID + process create identity.

    Un PID riutilizzato (identity divergente) è un proprietario morto: il
    lock è stale, non held."""
    alive = _pid_alive(info.get("pid"))
    if alive is False:
        return False
    recorded = info.get("pid_create_time")
    if alive and recorded is not None:
        current = _process_create_time(info.get("pid"))
        if current is not None and current != recorded:
            return False
    return alive


def lock_path(project):
    # il path del lock passa dal boundary PRIMA di ogni I/O; se
    # shared o shared/.tx sono reparse point, resolve_in_project solleva
    # path_escape (exit 3) e nessun lock viene creato/letto fuori dal progetto.
    return resolve_in_project(project, f"{TX_REL}/{LOCK_NAME}", "lock")


def acquire_lock(project, transaction_id, allow_stale_takeover=False):
    """Lock esclusivo prima di allocare ASS-*, snapshot e applying.

    Gestione conservativa dei lock stale: il lock di un altro processo viene
    rimosso solo se il proprietario è dimostrabilmente morto (PID morto o
    identity divergente); in apply anche in quel caso si rifiuta (serve
    `recover`), salvo allow_stale_takeover.
    """
    path = lock_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({
        "transaction_id": transaction_id,
        "pid": os.getpid(),
        "pid_create_time": _process_create_time(os.getpid()),
        "token": uuid.uuid4().hex,
        "created_at": now_iso(),
    }, ensure_ascii=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload + "\n")
            return
        except FileExistsError:
            try:
                info = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raise TransactionError(
                    "lock_held",
                    "lock presente ma illeggibile: nessuna rimozione "
                    "automatica, richiesta ispezione manuale")
            alive = _lock_owner_alive(info)
            if alive is False:
                if not allow_stale_takeover:
                    raise TransactionError(
                        "lock_stale",
                        "lock di un processo terminato o con identity "
                        f"divergente (pid {info.get('pid')}, tx "
                        f"{info.get('transaction_id')}): eseguire 'recover' "
                        "prima di una nuova transazione")
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            raise TransactionError(
                "lock_held",
                f"transazione concorrente attiva sul progetto (tx "
                f"{info.get('transaction_id')}, pid {info.get('pid')})")
    raise TransactionError("lock_held", "impossibile acquisire il lock")


def release_lock(project, transaction_id):
    try:
        path = lock_path(project)
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TransactionError):
        # in finally: un boundary/lock non risolvibile non deve mascherare
        # l'esito primario della transazione
        return
    if info.get("transaction_id") == transaction_id:
        try:
            path.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------
# project-status.md: unica funzione di scrittura (governance-controlled)
# --------------------------------------------------------------------------

def render_project_status(front_matter, body):
    lines = ["---"]
    for key, value in front_matter.items():
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.append("---")
    return ("\n".join(lines) + "\n" + body).encode("utf-8")


def read_project_status(project):
    path = resolve_in_project(project, STATUS_REL, "project-status")
    if not path.exists():
        raise fw.CanonicalStateError("shared/project-status.md assente")
    text = path.read_text(encoding="utf-8")
    front = fw.parse_front_matter(text)
    lines = text.splitlines()
    end = next(i for i, ln in enumerate(lines[1:], start=1)
               if ln.strip() == "---")
    body = "\n".join(lines[end + 1:])
    if body and not body.endswith("\n"):
        body += "\n"
    return front, body


def build_status_update(project, updates):
    """Costruisce il nuovo project-status.md (funzione controllata)."""
    front, body = read_project_status(project)
    front.update(updates)
    return render_project_status(front, body)


# --------------------------------------------------------------------------
# Candidate lifecycle: snapshot immutabile in shared/.tx
# e rimozione della copia attiva a ogni esito terminale.
# --------------------------------------------------------------------------

def snapshot_candidate(project, candidate, tx_id):
    """Copia il candidate in shared/.tx/<tx>-candidate/ rifiutando
    symlink/reparse point. Ritorna il path relativo dello snapshot."""
    candidate = Path(candidate)
    if _is_link_or_reparse(candidate):
        raise fw.CandidateError(
            "invalid", "candidate dir è un symlink/reparse point")
    rel_root = f"{TX_REL}/{tx_id}-candidate"
    dest_root = resolve_in_project(project, rel_root, "candidate-snapshot")
    for path in sorted(candidate.rglob("*")):
        if _is_link_or_reparse(path):
            raise fw.CandidateError(
                "invalid",
                "symlink/reparse point nel candidate: "
                f"{path.relative_to(candidate).as_posix()}")
        if path.is_file():
            rel = path.relative_to(candidate)
            dest = dest_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
    dest_root.mkdir(parents=True, exist_ok=True)
    return rel_root


def cleanup_active_candidate(project, candidate_path, stage=None):
    """Rimuove il candidate dalla posizione attiva (<stage>/.working/<tx>/)
    dopo uno stato terminale. Best-effort, con containment rigido: mai
    cancellazioni fuori progetto o fuori da <stage>/.working/.

    Quando lo stage è noto, la rimozione è vincolata esattamente a
    <stage>/.working/<...>: un candidate_path alterato nel journal non può
    indurre la cancellazione della .working di un altro stage."""
    if not candidate_path or not isinstance(candidate_path, str):
        return "skipped:no-path"
    try:
        cand = Path(candidate_path)
        if not cand.is_absolute():
            cand = Path(project) / cand
        if not cand.is_dir() or _is_link_or_reparse(cand):
            return "skipped:not-a-plain-dir"
        cand_res = cand.resolve()
        proj_res = Path(project).resolve()
        if not cand_res.is_relative_to(proj_res):
            return "skipped:outside-project"
        rel_parts = cand_res.relative_to(proj_res).parts
        if ".working" not in rel_parts:
            return "skipped:not-working-area"
        if stage is not None and (len(rel_parts) < 2
                                  or rel_parts[0] != stage
                                  or rel_parts[1] != ".working"):
            return "skipped:not-stage-working-area"
        shutil.rmtree(cand_res)
        return "removed"
    except OSError as exc:
        return f"skipped:{exc.__class__.__name__}"


# --------------------------------------------------------------------------
# Schema binding al commit: candidate, canonico letto e stato
# post-transform sono validati contro gli schemi versionati. Fail-closed:
# senza `jsonschema` il percorso canonico si rifiuta di procedere (exit 2),
# nessuna degradazione shape-only.
# --------------------------------------------------------------------------

SCHEMAS_DIR = SKILL_ROOT / "schemas"
_schema_cache = {}


def _jsonschema_validator_cls():
    try:
        from jsonschema import Draft202012Validator
        return Draft202012Validator
    except ImportError:
        raise fw.ValidatorUsageError(
            "jsonschema non disponibile: l'enforcement canonico degli "
            "schemi è fail-closed; installare `jsonschema` per "
            "usare il transaction manager")


def load_schema(name):
    if name not in _schema_cache:
        path = SCHEMAS_DIR / f"{name}.schema.json"
        if not path.exists():
            raise fw.ValidatorUsageError(f"schema mancante: {path.name}")
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise fw.ValidatorUsageError(
                f"schema malformato: {path.name}: {exc}")
        _schema_cache[name] = _jsonschema_validator_cls()(doc)
    return _schema_cache[name]


def schema_errors(name, instance, label):
    validator = load_schema(name)
    return [f"{label}: {err.json_path}: {err.message}"
            for err in validator.iter_errors(instance)][:8]


def validate_canonical_state(project, config):
    """Valida i registri canonici letti (schema + coerenza semantica globale).
    Uno stato canonico schema-invalid blocca la transazione (exit 3)."""
    project = Path(project)
    problems = []
    register_path = resolve_in_project(project, REGISTER_REL, "register")
    register = fw.read_canonical_json(register_path, REGISTER_REL)
    problems += schema_errors("assumptions-register", register, REGISTER_REL)
    conditions_path = resolve_in_project(project, CONDITIONS_REL,
                                         "conditions")
    if conditions_path.exists():
        conditions = fw.read_canonical_json(conditions_path, CONDITIONS_REL)
        problems += schema_errors("conditions-register", conditions,
                                  CONDITIONS_REL)
    front, _ = read_project_status(project)
    problems += schema_errors("project-status", front, STATUS_REL)
    if problems:
        raise fw.CanonicalStateError(
            "stato canonico schema-invalid: " + "; ".join(problems))
    fw.validate_status_coherence(front, config)


def validate_candidate_docs(candidate_snap):
    """Valida i documenti del candidate contro i contratti candidate/proposed
    (schema binding). Un candidate schema-invalid è rifiutato (exit 1) prima del
    marker applying."""
    proposed = fw.load_proposed_assumptions(candidate_snap)
    problems = schema_errors("proposed-assumptions", proposed,
                             "proposed-assumptions.json")
    conditions_path = Path(candidate_snap) / "proposed-conditions.json"
    if conditions_path.exists():
        conditions = fw.read_candidate_json(conditions_path,
                                            "proposed-conditions.json")
        problems += schema_errors("conditions-register", conditions,
                                  "proposed-conditions.json")
    if problems:
        raise fw.CandidateError(
            "schema_invalid", "candidate schema-invalid: "
            + "; ".join(problems))


def canonical_derivation_cycle_problems(register, label):
    """Riesegue la cycle detection referenziale sul registro canonico
    RISULTANTE: dopo l'allocazione P-ASS-* -> ASS-* un ciclo può
    nascere da un riferimento canonico in avanti verso l'id appena allocato,
    invisibile all'overlay del candidate. Ritorna la lista dei problemi."""
    overlay = {}
    if isinstance(register, list):
        for entry in register:
            if isinstance(entry, dict):
                entry_id = entry.get("id")
                if isinstance(entry_id, str):
                    overlay[entry_id] = entry
    try:
        cycles = refint.find_derivation_cycles(overlay)
    except (RecursionError, MemoryError):
        return [f"{label}: grafo delle derivation troppo complesso"]
    return [f"{label}: derivation cicliche dopo l'allocazione: "
            + " -> ".join(cycle) for cycle in cycles]


def post_transform_errors(config, new_register, new_conditions, status_front):
    """Valida lo stato canonico risultante COMPLETO prima del marker
    applying (schema binding): registri post-transform e project-status.
    Riesegue anche la cycle detection sul registro post-allocazione."""
    problems = []
    problems += schema_errors("assumptions-register", new_register,
                              "post-transform " + REGISTER_REL)
    if new_conditions is not None:
        problems += schema_errors("conditions-register", new_conditions,
                                  "post-transform " + CONDITIONS_REL)
    problems += schema_errors("project-status", status_front,
                              "post-transform " + STATUS_REL)
    problems += canonical_derivation_cycle_problems(
        new_register, "post-transform " + REGISTER_REL)
    if not problems:
        try:
            fw.validate_status_coherence(status_front, config)
        except fw.CanonicalStateError as exc:
            problems.append(f"post-transform {STATUS_REL}: {exc}")
    return problems


# --------------------------------------------------------------------------
# decisions-register: fonte canonica strutturata delle DEC-*.
# Il decision-log Markdown è una vista umana derivata e append-only e non
# viene MAI letto per allocare.
# --------------------------------------------------------------------------

DEC_NUM_RE = re.compile(r"^DEC-([0-9]{3}|[1-9][0-9]{3,})$")
DEC_TEXT_RE = re.compile(r"DEC-([0-9]+)")


def canonical_dec_id(number):
    """Forma canonica degli id: tre cifre zero-padded fino a 999, poi numeri
    pieni (DEC-001, DEC-999, DEC-1000)."""
    return f"DEC-{number:03d}" if number <= 999 else f"DEC-{number}"


def decisions_register_problems(register, label):
    """Schema + controlli applicativi di unicità.

    `uniqueItems` di JSON Schema confronta gli elementi interi di un array e
    NON esprime l'unicità per chiave dentro un oggetto: due record con lo
    stesso `id` ma `created_at` diverso sarebbero elementi distinti e
    passerebbero lo schema. Il lookup di idempotenza assume al più un
    record per `operation_id`: con un duplicato l'esito diventerebbe non
    deterministico. Questi controlli girano a ogni lettura del registro e
    anche sul registro proposto nella validation view."""
    problems = schema_errors("decisions-register", register, label)
    if problems:
        return problems
    seen_ids = set()
    seen_ops = set()
    for rec in register.get("decisions", []):
        rec_id = rec.get("id")
        if rec_id in seen_ids:
            problems.append(f"{label}: id duplicato: {rec_id}")
        seen_ids.add(rec_id)
        operation_id = rec.get("operation_id")
        if operation_id in seen_ops:
            problems.append(
                f"{label}: operation_id duplicato: {operation_id!r}")
        seen_ops.add(operation_id)
        refs = rec.get("target_refs", [])
        if len(refs) != len(set(refs)):
            problems.append(
                f"{label}: target_refs con duplicati nel record {rec_id}")
        digest = rec.get("request_payload_hash")
        if not (isinstance(digest, str) and SHA256_RE.match(digest)):
            problems.append(
                f"{label}: request_payload_hash assente o malformato nel "
                f"record {rec_id}")
    return problems


def read_decisions_register(project):
    """Ritorna `(register, raw_bytes)`; `(None, None)` se il registro non
    esiste (progetto con registro non ancora inizializzato).

    Registro illeggibile, schema-invalid o con unicità violata = stato
    canonico corrotto (exit 3): mai un'allocazione silenziosa."""
    path = resolve_in_project(project, DECISIONS_REL, "decisions-register")
    if not path.exists():
        return None, None
    try:
        raw = path.read_bytes()
        register = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise fw.CanonicalStateError(
            f"decisions-register illeggibile: {exc}")
    problems = decisions_register_problems(register, DECISIONS_REL)
    if problems:
        raise fw.CanonicalStateError(
            "decisions-register corrotto: " + "; ".join(problems))
    return register, raw


def next_decision_id(register):
    """Prossimo `DEC-*` = max(floor, max id di definizione) + 1, calcolato
    ESCLUSIVAMENTE dall'array JSON schema-enforced."""
    highest = 0
    attestation = register.get("initialized_from")
    if isinstance(attestation, dict):
        try:
            highest = int(attestation.get("derived_floor", 0))
        except (TypeError, ValueError):
            highest = 0
    for rec in register.get("decisions", []):
        match = DEC_NUM_RE.match(str(rec.get("id", "")))
        if match:
            highest = max(highest, int(match.group(1)))
    return canonical_dec_id(highest + 1)


def find_decision_by_operation_id(register, operation_id):
    """Lookup di idempotenza: al più un record per operation_id —
    garantito dai controlli applicativi di `decisions_register_problems`."""
    for rec in register.get("decisions", []):
        if rec.get("operation_id") == operation_id:
            return rec
    return None


def derive_decision_floor(project):
    """Floor conservativo per l'init lazy: massimo su TUTTE le
    occorrenze `DEC-[0-9]+` del decision-log, incluse quelle di semplice
    riferimento in prosa. L'over-counting è deliberato: per un floor può solo
    saltare numeri, mai produrre collisioni. Decision-log illeggibile =
    stato canonico corrotto (exit 3), nessun registro creato."""
    path = resolve_in_project(project, DECISION_LOG_REL, "decision-log")
    if not path.exists():
        return 0
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise fw.CanonicalStateError(f"decision-log illeggibile: {exc}")
    numbers = [int(n) for n in DEC_TEXT_RE.findall(text)]
    return max(numbers) if numbers else 0


def init_decisions_register(project, operation_id):
    """Inizializzazione lazy e additiva su un progetto che non ha ancora il
    registro: registro vuoto con attestazione `initialized_from`. Nessun record
    viene importato dalla prosa del decision-log — i record del registro
    nascono strutturati; gli eventuali `DEC-*` storici restano solo nel
    Markdown e il floor li rende non collidibili."""
    floor = derive_decision_floor(project)
    path = resolve_in_project(project, DECISION_LOG_REL, "decision-log")
    source_sha = sha256_bytes(path.read_bytes() if path.exists() else b"")
    return {
        "schema_version": "1.0",
        "initialized_from": {
            "source": DECISION_LOG_REL,
            "source_sha256": source_sha,
            "derived_floor": floor,
            "initialized_at": now_iso(),
            "operation_id": operation_id,
        },
        "decisions": [],
    }


# --------------------------------------------------------------------------
# Sostituzione P-ASS-* -> ASS-*
# --------------------------------------------------------------------------

def substitute_text(text, pass_map):
    return P_ASS_TEXT_RE.sub(lambda m: pass_map.get(m.group(0), m.group(0)),
                             text)


def substitute_json(node, pass_map):
    if isinstance(node, dict):
        return {k: substitute_json(v, pass_map) for k, v in node.items()}
    if isinstance(node, list):
        return [substitute_json(v, pass_map) for v in node]
    if isinstance(node, str):
        return substitute_text(node, pass_map)
    return node


def dump_json_bytes(data):
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8")


# --------------------------------------------------------------------------
# Canonicalizzazione e hash — algoritmi pinnati
#
# (A) `dump_json_bytes` sopra: byte CANONICI DEI FILE (indent=2,
#     ensure_ascii=False, newline finale, nessun sort_keys). Restano la base
#     degli hash *dei registri* (register_hash, pre/post_hash del write-set),
#     cioè CAS byte-level su disco. NON va modificata:
#     aggiungervi sort_keys riscriverebbe l'ordine delle chiavi di ogni
#     registro esistente al primo commit — breaking mascherato da refactor.
#
# (B) `canonical_hash_bytes` qui sotto: hash di IDENTITÀ LOGICA, invariante
#     rispetto a whitespace e ordine delle chiavi dell'input. Serve a
#     `request_payload_hash` e `expected_record_hash`, dove un retry
#     legittimo ri-serializzato in modo diverso deve produrre lo stesso hash.
# --------------------------------------------------------------------------

def canonical_hash_bytes(obj):
    """Serializzazione di identità logica (B). Sempre applicata all'oggetto
    JSON **parsato**, mai ai byte originali di un file."""
    return json.dumps(
        obj,
        sort_keys=True,              # ordine delle chiavi irrilevante
        separators=(",", ":"),       # separatori compatti e deterministici
        ensure_ascii=True,           # stabile su ogni piattaforma
    ).encode("utf-8")                # nessuna newline finale: non è un file


def canonical_sha256(obj):
    return sha256_bytes(canonical_hash_bytes(obj))


def strip_reason(node):
    """Rimuove `reason` a ogni livello: è testo umano e non partecipa
    all'identità dell'operazione. Basare l'idempotenza sul reason
    significherebbe non riconoscere un retry legittimo con testo variato."""
    if isinstance(node, dict):
        return {k: strip_reason(v) for k, v in node.items() if k != "reason"}
    if isinstance(node, list):
        return [strip_reason(v) for v in node]
    return node


def update_request_payload_hash(payload):
    """`request_payload_hash` di `update-assumption`: sha256 di
    canonical_hash_bytes del payload privato di `reason`."""
    return canonical_sha256(strip_reason(payload))


def resolve_request_payload_hash(condition, resolution, evidence_ref,
                                 decision, operation_id):
    """`request_payload_hash` di `resolve-condition`: oggetto
    normalizzato, con `evidence_ref` a `null` nel ramo `waived` (dove è
    assente per regola) così che la chiave di idempotenza sia totalmente
    definita in entrambi i rami; `reason` escluso."""
    return canonical_sha256(strip_reason({
        "condition": condition,
        "resolution": resolution,
        "evidence_ref": evidence_ref if resolution == "resolved" else None,
        "decision": decision,
        "operation_id": operation_id,
    }))


def record_fingerprint(record):
    """`expected_record_hash` del CAS: sha256 di
    canonical_hash_bytes dell'INTERO record ASS-* (id, value, derivation,
    unit, last_updated e ogni altro campo), mai del solo `value`. Usando (B)
    e non (A), il CAS non fallisce per differenze cosmetiche di ordine
    chiavi o whitespace."""
    return canonical_sha256(record)


# --------------------------------------------------------------------------
# Verifica di contenuto (apply e recovery: mai "completa" per sola esistenza)
# --------------------------------------------------------------------------

def verify_write_set(project, journal):
    """Ritorna la lista dei problemi (vuota = transazione verificabile)."""
    project = Path(project)
    problems = []
    for entry in journal.get("write_set", []):
        try:
            target = resolve_in_project(project, entry["path"],
                                        "write_set.path")
        except TransactionError as exc:
            problems.append(exc.message)
            continue
        if not target.exists():
            problems.append(f"file atteso assente: {entry['path']}")
            continue
        actual = sha256_file(target)
        if actual != entry["post_hash"]:
            problems.append(
                f"hash divergente per {entry['path']}: atteso "
                f"{entry['post_hash'][:12]}…, trovato {actual[:12]}…")
        if entry["path"] != AUDIT_REL and "P-ASS-" in target.read_text(
                encoding="utf-8", errors="replace"):
            problems.append(f"P-ASS residuo nel canonico: {entry['path']}")
    if problems:
        return problems
    # verifica semantica: registro, allocazioni, project-status
    try:
        register_path = resolve_in_project(project, REGISTER_REL, "register")
        register = json.loads(register_path.read_text(encoding="utf-8"))
        ids = [e.get("id") for e in register]
        if len(ids) != len(set(ids)):
            problems.append("id duplicati nel registro applicato")
        for allocated in journal.get("pass_map", {}).values():
            if allocated not in ids:
                problems.append(f"ASS allocato mancante: {allocated}")
        # cycle detection anche sui byte post-write del registro
        problems += canonical_derivation_cycle_problems(
            register, "post-write " + REGISTER_REL)
    except (OSError, json.JSONDecodeError, AttributeError,
            TransactionError) as exc:
        problems.append(f"registro applicato illeggibile: {exc}")
    try:
        front, _ = read_project_status(project)
        if not front.get("current_stage"):
            problems.append("project-status senza current_stage")
    except (fw.CanonicalStateError, TransactionError) as exc:
        problems.append(f"project-status incoerente: {exc}")
    if problems:
        return problems
    # rilettura dei byte effettivamente scritti e rivalidazione a schema
    # dello stato canonico risultante (schema binding, prima del marker
    # committed)
    try:
        validate_canonical_state(project, fw.load_config())
    except fw.CanonicalStateError as exc:
        problems.append(f"stato canonico post-write schema-invalid: {exc}")
    return problems


def restore_snapshot(project, journal):
    project = Path(project)
    snapshot_rel = journal.get("snapshot_path")
    if not isinstance(snapshot_rel, str) or \
            not snapshot_rel.startswith(TX_REL + "/"):
        raise TransactionError(
            "journal_corrupted",
            f"snapshot_path non ammesso: {snapshot_rel!r}", exit_code=3)
    resolve_in_project(project, snapshot_rel, "snapshot_path")
    for entry in journal.get("write_set", []):
        rel = entry["path"]
        target = resolve_in_project(project, rel, "write_set.path")
        source = resolve_in_project(project, f"{snapshot_rel}/{rel}",
                                    "snapshot source")
        if entry["pre_hash"] is None:
            if target.exists():
                target.unlink()
            continue
        if not source.exists():
            raise TransactionError(
                "snapshot_missing",
                f"snapshot incompleto per {rel}: rollback "
                "impossibile senza intervento manuale", exit_code=3)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if sha256_file(target) != entry["pre_hash"]:
            raise TransactionError(
                "snapshot_mismatch",
                f"ripristino divergente per {rel}", exit_code=3)


# --------------------------------------------------------------------------
# Validation binding (riesecuzione autonoma dei validator egress)
# --------------------------------------------------------------------------

def enforcement_artifact_hashes(config, loaded=False):
    """Hash degli artefatti di enforcement effettivamente usati:
    config, framework, DSL, validator egress e schemi. Registrati nel journal
    e ri-verificati prima del marker committed.

    Con `loaded=True` (registrazione nel journal), per i sorgenti che questo
    processo importa (framework, DSL, refint) si usa l'hash catturato
    all'import (`_LOADED_SOURCE_HASHES`): l'hash identifica i byte davvero
    eseguiti, non un re-read successivo che potrebbe divergere. La verifica
    (loaded=False) rilegge i byte su disco: se differiscono dai byte caricati
    e hashati, è drift -> rollback."""
    files = [SKILL_ROOT / "config" / "enforcement-config.json",
             SKILL_ROOT / "validators" / "_framework.py",
             SKILL_ROOT / "validators" / "formula_dsl.py"]
    for name in config.get("egress_required", []):
        files.append(SKILL_ROOT / "validators" / f"{name}.py")
    files += sorted((SKILL_ROOT / "schemas").glob("*.schema.json"))
    hashes = {}
    for path in files:
        rel = path.relative_to(SKILL_ROOT).as_posix()
        if loaded and rel in _LOADED_SOURCE_HASHES:
            hashes[rel] = _LOADED_SOURCE_HASHES[rel]
        elif path.exists():
            hashes[rel] = sha256_file(path)
    return hashes


def recovery_binding_problems(project, journal, config):
    """Prima di completare un recovery marker-only, rivalida che lo
    snapshot del candidate e gli artefatti di enforcement non siano derivati
    rispetto a quanto registrato nel journal. Un drift -> rollback, mai un
    commit marker-only che benedirebbe byte non più identici a quelli
    validati."""
    problems = []
    snap_rel = journal.get("candidate_snapshot_path")
    recorded_candidate = journal.get("candidate_hash")
    if snap_rel and recorded_candidate:
        try:
            snap_dir = resolve_in_project(project, snap_rel,
                                          "candidate-snapshot")
        except TransactionError as exc:
            return [exc.message]
        if not snap_dir.is_dir() or \
                hash_candidate(snap_dir) != recorded_candidate:
            problems.append(
                "snapshot del candidate derivato rispetto all'hash registrato")
    recorded_enf = journal.get("enforcement_hashes")
    if isinstance(recorded_enf, dict) and recorded_enf:
        if enforcement_artifact_hashes(config) != recorded_enf:
            problems.append(
                "artefatti di enforcement (config/validator/schemi) derivati "
                "rispetto al journal")
    return problems


def run_egress_validators(config, project, candidate, stage):
    results = []
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    stage_ord = fw.stage_ordinal(stage, config)
    for name in config.get("egress_required", []):
        # Matrice di applicabilità: i validator di dominio girano
        # solo per gli stage dichiarati nella propria voce di config; per
        # gli altri stage l'invocazione sarebbe un errore d'uso (exit 2),
        # non un esito del candidate.
        spec = config.get("validators", {}).get(name, {})
        stages = spec.get("stages")
        if stages is not None and stage_ord not in [int(s) for s in stages]:
            continue
        script = SKILL_ROOT / "validators" / f"{name}.py"
        if not script.exists():
            raise fw.ValidatorUsageError(f"validator richiesto assente: {name}")
        import subprocess
        proc = subprocess.run(
            [sys.executable, str(script), "--project", str(project),
             "--candidate", str(candidate), "--stage", stage,
             "--phase", "egress"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env)
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            report = {"raw_stdout": proc.stdout, "stderr": proc.stderr}
        results.append({"validator": name, "exit_code": proc.returncode,
                        "report": report})
    return results


# --------------------------------------------------------------------------
# apply / advance-stage (avanzamento di stage nella stessa
# transazione recuperabile di output, registri, handoff, status e audit)
# --------------------------------------------------------------------------

def cmd_apply(args):
    return _apply_transaction(args, advance=False)


def cmd_advance_stage(args):
    return _apply_transaction(args, advance=True)


#: `next_action` dello STATO TERMINALE del piano,
#: generico — il transaction manager non conosce alcuno stage per nome.
TERMINAL_NEXT_ACTION = ("piano completato: tutti gli stage di stage_order "
                        "sono in completed_stages; nessuno stage successivo")


def _is_terminal_stage(stage, config):
    """Predicato STRUTTURALE dello stage terminale — ultimo
    ordinale di stage_order E release_boundary. Il suo advance completa il
    piano invece di cercare uno stage successivo che non esiste."""
    order = config["stage_order"]
    return (int(order[stage]) == max(int(value) for value in order.values())
            and stage == config.get("release_boundary"))


def _next_stage(stage, config):
    """Transizione derivata da current stage + stage order: l'unico
    avanzamento ammesso è allo stage con ordinale successivo."""
    ordinal = fw.stage_ordinal(stage, config)
    for folder, value in config["stage_order"].items():
        if int(value) == ordinal + 1:
            return folder
    raise fw.ValidatorUsageError(
        f"nessuno stage successivo definito dopo {stage}")


def _apply_transaction(args, advance):
    config = fw.load_config()
    project = Path(args.project)
    candidate = Path(args.candidate)
    if not project.is_dir():
        raise fw.ValidatorUsageError(f"project dir inesistente: {project}")
    if not candidate.is_dir():
        raise fw.ValidatorUsageError(f"candidate dir inesistente: {candidate}")
    fw.stage_ordinal(args.stage, config)
    # tentativo operativo oltre il release boundary. È un risultato di
    # DOMINIO (exit 1), non un errore d'uso: nessun nuovo stato di governance
    # e nessuna mutazione. Il rifiuto precede lock, journal e ogni I/O.
    if beyond_release_boundary(args.stage, config):
        raise TransactionError(
            "stage_not_implemented",
            f"{args.stage} è oltre il release_boundary configurato "
            f"({config.get('release_boundary')}): nessuna "
            "transazione possibile oltre il confine",
            exit_code=1)
    action = "tx_advance_stage" if advance else "tx_apply"
    gate_result = None
    next_stage = None
    terminal = False
    if advance:
        gate_result = getattr(args, "gate_result", None) or "approved"
        if gate_result not in config["approved_states"]:
            raise fw.ValidatorUsageError(
                f"--gate-result non ammesso: {gate_result!r} "
                f"(ammessi: {config['approved_states']})")
        terminal = _is_terminal_stage(args.stage, config)
        next_stage = None if terminal else _next_stage(args.stage, config)

    tx_id = (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
             + "-" + uuid.uuid4().hex[:10])
    # la transaction directory e il journal passano dal boundary
    # PRIMA di qualunque mkdir/open (se shared o shared/.tx sono reparse point
    # -> path_escape, exit 3).
    tx_dir = resolve_in_project(project, TX_REL, "transaction-dir")
    tx_dir.mkdir(parents=True, exist_ok=True)
    journal_path = resolve_in_project(project, f"{TX_REL}/{tx_id}.json",
                                      "journal")

    # il lock precede il caricamento degli artefatti di enforcement e
    # dei registri canonici. Sotto lock, la cache degli schemi è azzerata e
    # gli hash sono catturati PRIMA del caricamento: i byte hashati coincidono
    # con i byte caricati/validati (nessuna finestra fra hash e load, nessuna
    # cache che separi byte caricati e byte hashati).
    acquire_lock(project, tx_id)
    try:
        _schema_cache.clear()
        enforcement_hashes = enforcement_artifact_hashes(config, loaded=True)
        # i registri canonici letti devono essere schema-validi e
        # semanticamente coerenti PRIMA di iniziare la transazione (exit 3)
        validate_canonical_state(project, config)
        journal = {
            "transaction_id": tx_id,
            "project": str(project),
            "stage": args.stage,
            "mode": "advance" if advance else "apply",
            "gate_result": gate_result,
            "next_stage": next_stage,
            "candidate_path": str(candidate),
            "candidate_snapshot_path": None,
            "candidate_hash": None,
            "enforcement_hashes": enforcement_hashes,
            "state": "preparing",
            "snapshot_path": f"{TX_REL}/{tx_id}-snapshot",
            "write_set": [],
            "pass_map": {},
            "validation": [],
            "timestamps": {"preparing": now_iso()},
            "error": None,
            "recovery_action": None,
        }
        save_journal(journal_path, journal)

        def reject(code, message, extra_errors=None):
            journal["state"] = "rolled_back"
            journal["error"] = {"code": code, "message": message}
            journal["timestamps"]["finalized"] = now_iso()
            journal["candidate_cleanup"] = cleanup_active_candidate(
                project, str(candidate), stage=args.stage)
            save_journal(journal_path, journal)
            append_audit(project, tx_id, args.stage, action, "rejected",
                         [])
            errors = [{"code": code, "message": message}]
            if extra_errors:
                errors += extra_errors
            print(json.dumps({"result": "rejected", "transaction_id": tx_id,
                              "errors": errors}, ensure_ascii=True, indent=2))
            return 1

        # apply/advance su uno stage già presente in completed_stages
        # è sempre rifiutato: nessuna riscrittura del deliverable approvato
        # (la riapertura via protocollo ISSUE non è implementata dal
        # transaction manager). Difesa diretta oltre al validator egress.
        front_pre, _ = read_project_status(project)
        completed_pre = front_pre.get("completed_stages", [])
        if isinstance(completed_pre, list) and args.stage in completed_pre:
            return reject(
                "stage_already_completed",
                f"stage {args.stage} già in completed_stages: nessuna "
                "riscrittura canonica di uno stage approvato (riapertura "
                "non supportata)")

        # snapshot immutabile del candidate: da qui in poi ogni
        # lettura/validazione usa esclusivamente lo snapshot in shared/.tx/
        snap_rel = snapshot_candidate(project, candidate, tx_id)
        journal["candidate_snapshot_path"] = snap_rel
        candidate_snap = project / snap_rel
        candidate_hash = hash_candidate(candidate_snap)
        journal["candidate_hash"] = candidate_hash
        save_journal(journal_path, journal)
        # hook di test: mutazione concorrente del candidate ATTIVO dopo
        # lo snapshot; non deve avere alcun effetto sul commit
        _test_mutation_hook("BPO_TX_TEST_MUTATE_ACTIVE", candidate)

        # contratto candidate (proposed assumptions/conditions) validato
        # a schema prima di qualunque marker; schema-invalid -> rejected
        validate_candidate_docs(candidate_snap)

        if advance and gate_result == "approved_with_conditions":
            cond_path = candidate_snap / "proposed-conditions.json"
            cond_entries = fw.read_candidate_json(
                cond_path, "proposed-conditions.json") \
                if cond_path.exists() else []
            if not cond_entries:
                return reject(
                    "conditions_required",
                    "approved_with_conditions richiede COND tracciate nel "
                    "candidate (proposed-conditions.json)")

        # Un report esterno è accettato solo se riferito allo stesso hash;
        # in ogni caso i validator vengono rieseguiti qui sotto.
        if args.report:
            try:
                report_doc = json.loads(
                    Path(args.report).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return reject("report_invalid",
                              f"validation report illeggibile: {exc}")
            if report_doc.get("candidate_hash") != candidate_hash:
                return reject(
                    "report_hash_mismatch",
                    "il validation report riferisce un candidate hash "
                    "diverso: candidate modificato dopo la validazione")

        # snapshot dello stato canonico toccato
        structured_path = candidate_snap / "structured-output.json"
        handoff_path = candidate_snap / "handoff.md"
        proposed_conditions_path = candidate_snap / "proposed-conditions.json"
        targets = [REGISTER_REL]
        if proposed_conditions_path.exists():
            targets.append(CONDITIONS_REL)
        if structured_path.exists():
            targets.append(f"{args.stage}/structured-output.json")
        if handoff_path.exists():
            targets.append(f"{args.stage}/handoff.md")
        targets.append(STATUS_REL)
        targets.append(AUDIT_REL)

        snapshot_dir = resolve_in_project(project, journal["snapshot_path"],
                                          "snapshot_path")
        pre_hashes = {}
        for rel in targets:
            source = resolve_in_project(project, rel, "snapshot target")
            if source.exists():
                pre_hashes[rel] = sha256_file(source)
                dest = snapshot_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
            else:
                pre_hashes[rel] = None
        journal["state"] = "snapshot_taken"
        journal["timestamps"]["snapshot_taken"] = now_iso()
        save_journal(journal_path, journal)

        # validation binding: riesecuzione autonoma dei validator egress
        # ESCLUSIVAMENTE sullo snapshot immutabile del candidate
        validation = run_egress_validators(config, project, candidate_snap,
                                           args.stage)
        journal["validation"] = validation
        save_journal(journal_path, journal)
        failed = [v for v in validation if v["exit_code"] != 0]
        if failed:
            details = [{"code": "validator_failed",
                        "message": f"{v['validator']} exit {v['exit_code']}"}
                       for v in failed]
            return reject("validation_failed",
                          "validator egress non superati: nessuna "
                          "applicazione canonica", details)

        # hook di test: mutazione dello snapshot dopo la validazione;
        # deve essere rilevata dal rehash e produrre rejection
        _test_mutation_hook("BPO_TX_TEST_MUTATE_SNAPSHOT", candidate_snap)
        rehash = hash_candidate(candidate_snap)
        if rehash != candidate_hash:
            return reject(
                "candidate_changed",
                "candidate snapshot modificato durante la validazione: "
                "hash divergente")

        journal["state"] = "validated"
        journal["timestamps"]["validated"] = now_iso()
        save_journal(journal_path, journal)

        # costruzione dei contenuti canonici (allocazione ASS-* SOLO qui)
        state = fw.ProjectState(project, config)
        register = state.assumptions
        max_id = 0
        for entry in register:
            match = ASS_NUM_RE.match(str(entry.get("id", "")))
            if match:
                max_id = max(max_id, int(match.group(1)))
        proposed = fw.load_proposed_assumptions(candidate_snap)

        def p_num(entry):
            match = P_ASS_NUM_RE.match(str(entry.get("id", "")))
            if not match:
                raise fw.CandidateError(
                    "invalid", f"id proposto non P-ASS-*: {entry.get('id')!r}")
            return int(match.group(1))

        pass_map = {}
        for entry in sorted(proposed, key=p_num):
            max_id += 1
            pass_map[entry["id"]] = f"ASS-{max_id:03d}"
        journal["pass_map"] = pass_map

        new_register = [dict(e) for e in register]
        for entry in sorted(proposed, key=p_num):
            new_register.append(substitute_json(entry, pass_map))

        contents = {REGISTER_REL: dump_json_bytes(new_register)}
        new_conditions = None
        if proposed_conditions_path.exists():
            conditions = state.conditions + fw.read_candidate_json(
                proposed_conditions_path, "proposed-conditions.json")
            new_conditions = substitute_json(conditions, pass_map)
            contents[CONDITIONS_REL] = dump_json_bytes(new_conditions)
        if structured_path.exists():
            structured = fw.read_candidate_json(structured_path,
                                                "structured-output.json")
            contents[f"{args.stage}/structured-output.json"] = \
                dump_json_bytes(substitute_json(structured, pass_map))
        if handoff_path.exists():
            contents[f"{args.stage}/handoff.md"] = substitute_text(
                handoff_path.read_text(encoding="utf-8"), pass_map).encode(
                "utf-8")
        if advance:
            front_now, _ = read_project_status(project)
            completed_now = front_now.get("completed_stages", [])
            if not isinstance(completed_now, list):
                raise fw.CanonicalStateError(
                    "completed_stages non è una lista")
            if terminal:
                # stato terminale ESPLICITO del piano; resta immutabile
                # per le protezioni sugli stage già completati.
                status_updates = {
                    "current_stage": args.stage,
                    "status": gate_result,
                    "current_task": "plan-complete",
                    "next_action": TERMINAL_NEXT_ACTION,
                    "last_updated": now_iso()[:10],
                    "completed_stages": completed_now + [args.stage],
                }
            else:
                status_updates = {
                    "current_stage": next_stage,
                    "status": "not_started",
                    "current_task": "stage-advanced",
                    "next_action": boundary_next_action(next_stage, config),
                    "last_updated": now_iso()[:10],
                    "completed_stages": completed_now + [args.stage],
                }
        else:
            status_updates = {
                "current_task": "stage-output-applied",
                "last_updated": now_iso()[:10],
            }
        contents[STATUS_REL] = build_status_update(project, status_updates)

        for rel, data in contents.items():
            if "P-ASS-" in data.decode("utf-8", errors="replace"):
                return reject(
                    "pass_unresolved_in_output",
                    f"P-ASS non risolto nei contenuti canonici ({rel})")

        # lo stato canonico risultante COMPLETO è validato a schema e
        # coerenza prima del marker applying; schema-invalid -> rejected
        status_front = fw.parse_front_matter(
            contents[STATUS_REL].decode("utf-8"))
        problems = post_transform_errors(config, new_register,
                                         new_conditions, status_front)
        if problems:
            return reject("schema_validation_failed",
                          "stato post-transform schema-invalid: "
                          + "; ".join(problems))

        # evento audit di commit: parte del write-set, hash-verificato
        # e scritto prima del marker `committed`
        audit_target = resolve_in_project(project, AUDIT_REL, "audit")
        audit_existing = audit_target.read_bytes() \
            if audit_target.exists() else b""
        contents[AUDIT_REL] = audit_existing + audit_event_line(
            tx_id, args.stage, action, "applied",
            sorted(pass_map.values())).encode("utf-8")

        journal["write_set"] = [
            {"path": rel, "pre_hash": pre_hashes.get(rel),
             "post_hash": sha256_bytes(data)}
            for rel, data in contents.items()
        ]
        journal["state"] = "applying"
        journal["timestamps"]["applying"] = now_iso()
        save_journal(journal_path, journal)

        try:
            for rel, data in contents.items():
                write_file(resolve_in_project(project, rel, "write target"),
                           data)
        except OSError as exc:
            restore_snapshot(project, journal)
            journal["state"] = "rolled_back"
            journal["error"] = {"code": "write_failed", "message": str(exc)}
            journal["timestamps"]["finalized"] = now_iso()
            journal["candidate_cleanup"] = cleanup_active_candidate(
                project, str(candidate), stage=args.stage)
            save_journal(journal_path, journal)
            append_audit(project, tx_id, args.stage, action,
                         "rolled_back", [])
            raise TransactionError(
                "write_failed",
                f"write canonica fallita, rollback eseguito: {exc}",
                exit_code=3)

        problems = verify_write_set(project, journal)
        # verifica dell'identità prima del commit — snapshot del
        # candidate e artefatti di enforcement (config/validator/schemi)
        # devono corrispondere a quanto registrato nel journal
        if not problems:
            if hash_candidate(candidate_snap) != candidate_hash:
                problems = ["candidate snapshot modificato dopo la "
                            "validazione: hash divergente"]
            elif enforcement_artifact_hashes(config) != \
                    journal["enforcement_hashes"]:
                problems = ["artefatti di enforcement (config/validator/"
                            "schemi) modificati durante la transazione"]
        if problems:
            restore_snapshot(project, journal)
            journal["state"] = "rolled_back"
            journal["error"] = {"code": "content_verification_failed",
                                "message": "; ".join(problems)}
            journal["timestamps"]["finalized"] = now_iso()
            journal["candidate_cleanup"] = cleanup_active_candidate(
                project, str(candidate), stage=args.stage)
            save_journal(journal_path, journal)
            append_audit(project, tx_id, args.stage, action,
                         "rolled_back", [])
            raise TransactionError(
                "content_verification_failed",
                "verifica post-applicazione fallita: rollback eseguito",
                exit_code=3)

        _crash_hook("before_commit")
        journal["state"] = "committed"
        journal["timestamps"]["committed"] = now_iso()
        journal["timestamps"]["finalized"] = now_iso()
        save_journal(journal_path, journal)
        journal["candidate_cleanup"] = cleanup_active_candidate(
            project, str(candidate), stage=args.stage)
        save_journal(journal_path, journal)
        output = {"result": "applied", "transaction_id": tx_id,
                  "pass_map": pass_map,
                  "journal": f"{TX_REL}/{tx_id}.json"}
        if advance:
            output["advanced_to"] = next_stage
            output["gate_result"] = gate_result
            if terminal:
                output["completed"] = True
        print(json.dumps(output, ensure_ascii=True, indent=2))
        return 0
    except fw.CandidateError as exc:
        journal["state"] = "rolled_back"
        journal["error"] = {"code": exc.code, "message": exc.message}
        journal["timestamps"]["finalized"] = now_iso()
        journal["candidate_cleanup"] = cleanup_active_candidate(
            project, str(candidate), stage=args.stage)
        save_journal(journal_path, journal)
        append_audit(project, tx_id, args.stage, action, "rejected", [])
        print(json.dumps({"result": "rejected", "transaction_id": tx_id,
                          "errors": [{"code": exc.code,
                                      "message": exc.message}]},
                         ensure_ascii=True, indent=2))
        return 1
    finally:
        release_lock(project, tx_id)


# --------------------------------------------------------------------------
# resolve-condition: la risoluzione delle COND-* passa dal transaction
# manager, mai da una scrittura diretta dell'orchestratore.
# --------------------------------------------------------------------------

def cmd_resolve_condition(args):
    config = fw.load_config()
    project = Path(args.project)
    if not project.is_dir():
        raise fw.ValidatorUsageError(f"project dir inesistente: {project}")
    operation_id = args.operation_id
    resolution = args.resolution
    reason = args.reason or ""
    action = "tx_resolve_condition"

    decision = None
    if args.decision:
        try:
            decision = json.loads(args.decision)
        except json.JSONDecodeError:
            decision = None
    request_hash = resolve_request_payload_hash(
        args.condition, resolution, args.evidence_ref, decision, operation_id)

    tx_id = (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
             + "-" + uuid.uuid4().hex[:10])
    tx_dir = resolve_in_project(project, TX_REL, "transaction-dir")
    tx_dir.mkdir(parents=True, exist_ok=True)
    journal_path = resolve_in_project(project, f"{TX_REL}/{tx_id}.json",
                                      "journal")

    acquire_lock(project, tx_id)
    journal = None
    try:
        _schema_cache.clear()
        enforcement_hashes = enforcement_artifact_hashes(config, loaded=True)
        validate_canonical_state(project, config)

        decisions, decisions_raw = read_decisions_register(project)
        if decisions is None:
            decisions = init_decisions_register(project, operation_id)
        existing = find_decision_by_operation_id(decisions, operation_id)
        if existing is not None:
            if existing.get("request_payload_hash") == request_hash:
                print(json.dumps(
                    {"result": "already_applied", "operation_id": operation_id,
                     "decision_id": existing.get("id")},
                    ensure_ascii=True, indent=2))
                return 0
            print(json.dumps(
                {"result": "rejected",
                 "errors": [{"code": "operation_id_conflict",
                             "message": f"operation_id {operation_id!r} già "
                                        f"usato con un payload diverso "
                                        f"({existing.get('id')})"}]},
                ensure_ascii=True, indent=2))
            return 1

        conditions_path = resolve_in_project(project, CONDITIONS_REL,
                                             "conditions")
        conditions_bytes = conditions_path.read_bytes() \
            if conditions_path.exists() else None
        conditions = json.loads(conditions_bytes.decode("utf-8")) \
            if conditions_bytes is not None else []

        journal = {
            "transaction_id": tx_id,
            "project": str(project),
            "stage": None,
            "mode": "resolve_condition",
            "operation_id": operation_id,
            "request_payload_hash": request_hash,
            "target_refs": [args.condition],
            "candidate_path": None,
            "candidate_snapshot_path": None,
            "candidate_hash": None,
            "enforcement_hashes": enforcement_hashes,
            "reserved_decision_id": None,
            "conditions_hash": (sha256_bytes(conditions_bytes)
                                if conditions_bytes is not None else None),
            "decisions_register_hash": (sha256_bytes(decisions_raw)
                                        if decisions_raw is not None else None),
            "validation_view_path": None,
            "validators_invoked": [],
            "state": "preparing",
            "snapshot_path": f"{TX_REL}/{tx_id}-snapshot",
            "write_set": [],
            "pass_map": {},
            "validation": [],
            "timestamps": {"preparing": now_iso()},
            "error": None,
            "recovery_action": None,
        }
        save_journal(journal_path, journal)

        def reject(code, message):
            journal["state"] = "rolled_back"
            journal["error"] = {"code": code, "message": message}
            journal["timestamps"]["finalized"] = now_iso()
            save_journal(journal_path, journal)
            append_audit(project, tx_id, None, action, "rejected", [])
            print(json.dumps(
                {"result": "rejected", "transaction_id": tx_id,
                 "errors": [{"code": code, "message": message}]},
                ensure_ascii=True, indent=2))
            return 1

        # precondizione — regola unica, senza rami alternativi
        problem = decision_payload_problem(decision, "condition_resolution")
        if problem:
            return reject("decision_required", problem)
        if resolution == "resolved" and not args.evidence_ref:
            return reject(
                "evidence_required",
                "--resolution resolved significa verified_fact e richiede "
                "un --evidence-ref risolvibile")
        if resolution == "waived" and args.evidence_ref:
            return reject(
                "evidence_not_allowed_for_waiver",
                "una risoluzione waived è per definizione una rinuncia "
                "all'evidenza: "
                "--evidence-ref è una contraddizione semantica")

        target = None
        for entry in conditions:
            if isinstance(entry, dict) and entry.get("id") == args.condition:
                target = entry
                break
        if target is None or target.get("resolution_status") != "open":
            return reject(
                "condition_not_open",
                f"{args.condition}: inesistente oppure resolution_status "
                f"diverso da open")

        # esistenza dell'EVD-*: lettura diretta del registro evidenze, non un
        # refint (che risolverebbe gli EVD-* solo dal candidate structured
        # output, inesistente qui)
        if resolution == "resolved":
            evidence_ids = refint.load_evidence_ids(
                fw.ProjectState(project, config))
            if args.evidence_ref not in evidence_ids:
                return reject(
                    "evidence_not_found",
                    f"evidence_ref inesistente in "
                    f"shared/evidence-register.json: {args.evidence_ref}")

        reserved_decision_id = next_decision_id(decisions)
        journal["reserved_decision_id"] = reserved_decision_id
        save_journal(journal_path, journal)

        new_conditions = []
        for entry in conditions:
            if isinstance(entry, dict) and entry.get("id") == args.condition:
                updated = dict(entry)
                updated["resolution_status"] = resolution
                updated["resolved_by"] = reserved_decision_id
                updated["evidence_ref"] = args.evidence_ref \
                    if resolution == "resolved" else None
                updated["last_updated"] = now_iso()[:10]
                new_conditions.append(updated)
            else:
                new_conditions.append(entry)

        decision_record = build_decision_record(
            reserved_decision_id, operation_id, request_hash, decision,
            [args.condition])
        new_decisions = json.loads(json.dumps(decisions))
        new_decisions["decisions"] = list(new_decisions["decisions"]) + \
            [decision_record]

        conditions_bytes_new = dump_json_bytes(new_conditions)
        decisions_bytes_new = dump_json_bytes(new_decisions)
        # la view è materializzata per UNIFORMITÀ DI CICLO DI VITA con
        # update-assumption — stesso campo di journal, stesso cleanup nel
        # `finally`, stesso ramo di recovery — e NON come input di validazione:
        # `view_path` non viene letto da alcun controllo qui sotto. La
        # risoluzione di una COND non muta dati quantitativi, quindi non esiste
        # matrice impact da eseguire su una copia del progetto.
        view_rel, _view_path = build_validation_view(
            project, tx_id, {CONDITIONS_REL: conditions_bytes_new,
                             DECISIONS_REL: decisions_bytes_new}, config)
        journal["validation_view_path"] = view_rel
        save_journal(journal_path, journal)

        # pre-commit validation: controlli TM-interni sugli OGGETTI PROPOSTI in
        # memoria (`new_conditions`, `new_decisions`), che sono esattamente gli
        # stessi byte materializzati nella view e poi committati
        problems = schema_errors("conditions-register", new_conditions,
                                 "proposed " + CONDITIONS_REL)
        problems += decisions_register_problems(new_decisions,
                                                "proposed " + DECISIONS_REL)
        if problems:
            return reject("schema_invalid",
                          "stato proposto schema-invalid: "
                          + "; ".join(problems))

        contents = {
            CONDITIONS_REL: conditions_bytes_new,
            DECISIONS_REL: decisions_bytes_new,
            DECISION_LOG_REL: append_decision_log(
                project,
                decision_log_row(
                    decision_record,
                    f"{args.condition} {resolution}",
                    "`shared/conditions-register.json`")),
        }
        status_updates = _status_updates_for_decision(
            project, "condition-resolved",
            f"{args.condition} chiusa: riprendere il gate")
        front, _ = read_project_status(project)
        blocking = front.get("blocking_issues")
        if isinstance(blocking, list) and args.condition in blocking:
            status_updates["blocking_issues"] = [
                item for item in blocking if item != args.condition]
        contents[STATUS_REL] = build_status_update(project, status_updates)

        snapshot_dir = resolve_in_project(project, journal["snapshot_path"],
                                          "snapshot_path")
        pre_hashes = {}
        for rel in (CONDITIONS_REL, DECISIONS_REL, DECISION_LOG_REL,
                    STATUS_REL, AUDIT_REL):
            source = resolve_in_project(project, rel, "snapshot target")
            if source.exists():
                pre_hashes[rel] = sha256_file(source)
                dest = snapshot_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
            else:
                pre_hashes[rel] = None
        journal["state"] = "snapshot_taken"
        journal["timestamps"]["snapshot_taken"] = now_iso()
        save_journal(journal_path, journal)

        journal["state"] = "validated"
        journal["timestamps"]["validated"] = now_iso()
        save_journal(journal_path, journal)

        # hook della suite: scrittore concorrente sul canonico nella finestra
        # fra validazione e applicazione (esercita il CAS di conferma)
        _test_mutation_hook("BPO_TX_TEST_MUTATE_CANONICAL", project)

        # CAS di conferma (TOCTOU): i byte canonici devono ancora
        # hashare ai valori registrati nel journal
        drift = []
        current_conditions_hash = sha256_file(conditions_path) \
            if conditions_path.exists() else None
        if current_conditions_hash != journal["conditions_hash"]:
            drift.append(CONDITIONS_REL)
        decisions_path = resolve_in_project(project, DECISIONS_REL,
                                            "decisions-register")
        current_decisions_hash = sha256_file(decisions_path) \
            if decisions_path.exists() else None
        if current_decisions_hash != journal["decisions_register_hash"]:
            drift.append(DECISIONS_REL)
        if drift:
            journal["state"] = "rolled_back"
            journal["error"] = {"code": "canonical_drift",
                                "message": "byte canonici divergenti: "
                                           + ", ".join(drift)}
            journal["timestamps"]["finalized"] = now_iso()
            save_journal(journal_path, journal)
            append_audit(project, tx_id, None, action, "rolled_back", [])
            print(json.dumps(
                {"result": "rejected", "transaction_id": tx_id,
                 "errors": [{"code": "canonical_drift",
                             "message": journal["error"]["message"]}]},
                ensure_ascii=True, indent=2))
            return 1

        audit_target = resolve_in_project(project, AUDIT_REL, "audit")
        audit_existing = audit_target.read_bytes() \
            if audit_target.exists() else b""
        contents[AUDIT_REL] = audit_existing + audit_event_line(
            tx_id, None, action, "applied", [args.condition],
            operation_id=operation_id).encode("utf-8")

        journal["write_set"] = [
            {"path": rel, "pre_hash": pre_hashes.get(rel),
             "post_hash": sha256_bytes(data)}
            for rel, data in contents.items()
        ]
        journal["state"] = "applying"
        journal["timestamps"]["applying"] = now_iso()
        save_journal(journal_path, journal)

        try:
            for rel, data in contents.items():
                write_file(resolve_in_project(project, rel, "write target"),
                           data)
        except OSError as exc:
            restore_snapshot(project, journal)
            journal["state"] = "rolled_back"
            journal["error"] = {"code": "write_failed", "message": str(exc)}
            journal["timestamps"]["finalized"] = now_iso()
            save_journal(journal_path, journal)
            append_audit(project, tx_id, None, action, "rolled_back", [])
            raise TransactionError(
                "write_failed",
                f"write canonica fallita, rollback eseguito: {exc}",
                exit_code=3)

        # hook della suite: corruzione di un target del write-set dopo la
        # write e prima della verifica (esercita il rollback da snapshot)
        _test_mutation_hook("BPO_TX_TEST_CORRUPT_AFTER_WRITE", project)

        problems = verify_write_set(project, journal)
        if problems:
            restore_snapshot(project, journal)
            journal["state"] = "rolled_back"
            journal["error"] = {"code": "content_verification_failed",
                                "message": "; ".join(problems)}
            journal["timestamps"]["finalized"] = now_iso()
            save_journal(journal_path, journal)
            append_audit(project, tx_id, None, action, "rolled_back", [])
            raise TransactionError(
                "content_verification_failed",
                "verifica post-applicazione fallita: rollback eseguito",
                exit_code=3)

        _crash_hook("before_commit")
        journal["state"] = "committed"
        journal["timestamps"]["committed"] = now_iso()
        journal["timestamps"]["finalized"] = now_iso()
        save_journal(journal_path, journal)
        print(json.dumps({"result": "applied", "transaction_id": tx_id,
                          "operation_id": operation_id,
                          "condition": args.condition,
                          "resolution": resolution,
                          "decision_id": reserved_decision_id,
                          "journal": f"{TX_REL}/{tx_id}.json"},
                         ensure_ascii=True, indent=2))
        return 0
    finally:
        if journal is not None:
            cleanup_validation_view(project,
                                    journal.get("validation_view_path"))
        release_lock(project, tx_id)


# --------------------------------------------------------------------------
# show-assumption: read-only, nessun lock, nessuna mutazione possibile.
# Espone il record canonico e il suo `record_hash`, che è l'input del CAS
# (`expected_record_hash`) di update-assumption.
# --------------------------------------------------------------------------

def cmd_show_assumption(args):
    project = Path(args.project)
    if not project.is_dir():
        raise fw.ValidatorUsageError(f"project dir inesistente: {project}")
    register_path = resolve_in_project(project, REGISTER_REL, "register")
    register = fw.read_canonical_json(register_path, REGISTER_REL)
    if not isinstance(register, list):
        raise fw.CanonicalStateError(
            "assumptions-register.json non è una lista")
    for entry in register:
        if isinstance(entry, dict) and entry.get("id") == args.assumption:
            print(json.dumps({"result": "found",
                              "assumption": entry,
                              "record_hash": record_fingerprint(entry)},
                             ensure_ascii=True, indent=2))
            return 0
    print(json.dumps(
        {"result": "rejected",
         "errors": [{"code": "assumption_not_found",
                     "message": f"assunzione inesistente nel registro "
                                f"canonico: {args.assumption}"}]},
        ensure_ascii=True, indent=2))
    return 1


# --------------------------------------------------------------------------
# update-assumption: l'update
# confermato di un ASS-* canonico diventa una transazione journal-protetta.
# --------------------------------------------------------------------------

# Whitelist dei campi aggiornabili. `derivation.formula` è
# deliberatamente ASSENTE: una formula non è mai modificata da questo comando
# (la si cambia ricreando l'assunzione, con il proprio ciclo di validazione).
UPDATE_FIELD_WHITELIST = frozenset({
    "value", "display_value", "rationale", "confidence", "validation_status",
    "evidence_refs", "derivation.variables", "last_updated",
})

DECISION_TYPES = {"update_assumption": "assumption_update",
                  "resolve_condition": "condition_resolution"}


def load_changes_payload(path):
    """Legge e valida strutturalmente il payload `--changes`. I
    difetti strutturali della CLI sono errori d'uso (exit 2); i difetti di
    dominio (decisione, whitelist, CAS) sono rejected (exit 1)."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise fw.ValidatorUsageError(f"--changes illeggibile: {exc}")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise fw.ValidatorUsageError(f"--changes non è JSON valido: {exc}")
    if not isinstance(payload, dict):
        raise fw.ValidatorUsageError("--changes deve essere un oggetto JSON")
    operation_id = payload.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id:
        raise fw.ValidatorUsageError(
            "--changes senza operation_id: l'identità dell'operazione è "
            "obbligatoria")
    changes = payload.get("changes")
    if not isinstance(changes, list) or not changes:
        raise fw.ValidatorUsageError(
            "--changes senza un array `changes` non vuoto")
    for change in changes:
        if not isinstance(change, dict):
            raise fw.ValidatorUsageError("ogni change deve essere un oggetto")
        if not isinstance(change.get("assumption_id"), str):
            raise fw.ValidatorUsageError("change senza assumption_id")
        if not isinstance(change.get("updates"), dict):
            raise fw.ValidatorUsageError(
                f"change {change.get('assumption_id')!r} senza `updates`")
    return payload


def decision_payload_problem(decision, expected_type):
    """`decision` è il CONTENUTO del record DEC-* e la giustificazione di
    governance: è obbligatorio sempre (resolve-condition e
    update-assumption). Ritorna il messaggio del
    problema, oppure None se conforme."""
    if not isinstance(decision, dict):
        return "payload `decision` assente o non è un oggetto"
    if decision.get("decision_type") != expected_type:
        return (f"decision_type atteso {expected_type!r}, ottenuto "
                f"{decision.get('decision_type')!r}")
    for key in ("motivation", "approver"):
        value = decision.get(key)
        if not isinstance(value, str) or not value.strip():
            return f"campo `{key}` della decisione assente o vuoto"
    return None


def build_decision_record(decision_id, operation_id, request_payload_hash,
                          decision, target_refs):
    record = {
        "id": decision_id,
        "operation_id": operation_id,
        "request_payload_hash": request_payload_hash,
        "decision_type": decision["decision_type"],
        "target_refs": list(target_refs),
        "motivation": decision["motivation"],
        "approver": decision["approver"],
        "created_at": now_iso(),
    }
    for optional in ("options_considered", "impact"):
        value = decision.get(optional)
        if isinstance(value, str) and value:
            record[optional] = value
    return record


def decision_log_row(record, summary, files):
    """Riga della vista umana derivata: generata DAL record JSON, mai
    letta per allocare. Formato tabella del decision-log."""
    def cell(text):
        return str(text if text is not None else "").replace(
            "|", "\\|").replace("\n", " ").strip()

    return ("| {date} | {id} — {summary} | {options} | {motivation} | "
            "{impact} | {files} | {approver} |\n").format(
        date=cell(record["created_at"][:10]),
        id=cell(record["id"]),
        summary=cell(summary),
        options=cell(record.get("options_considered", "—")),
        motivation=cell(record["motivation"]),
        impact=cell(record.get("impact", "—")),
        files=cell(files),
        approver=cell(record["approver"]))


def append_decision_log(project, row):
    path = resolve_in_project(project, DECISION_LOG_REL, "decision-log")
    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
    except (OSError, UnicodeDecodeError) as exc:
        raise fw.CanonicalStateError(f"decision-log illeggibile: {exc}")
    if existing and not existing.endswith("\n"):
        existing += "\n"
    return (existing + row).encode("utf-8")


def apply_record_updates(record, updates, reason, decision_id):
    """Applica gli `updates` whitelisted e appende `previous_values`. Lo
    storico non viene mai riscritto: solo appeso."""
    new = json.loads(json.dumps(record))
    for key, value in updates.items():
        if key == "derivation.variables":
            derivation = new.get("derivation")
            if not isinstance(derivation, dict):
                derivation = {}
                new["derivation"] = derivation
            derivation["variables"] = value
        else:
            new[key] = value
    history = list(new.get("previous_values") or [])
    history.append({
        "value": record.get("value"),
        "display_value": record.get("display_value"),
        "superseded_at": now_iso(),
        "reason": reason,
        "decision_id": decision_id,
    })
    new["previous_values"] = history
    if "last_updated" not in updates:
        new["last_updated"] = now_iso()[:10]
    return new


def derivation_keys(record):
    derivation = record.get("derivation")
    if not isinstance(derivation, dict):
        return frozenset()
    variables = derivation.get("variables")
    return frozenset(variables) if isinstance(variables, dict) else frozenset()


def derivation_refs(record):
    derivation = record.get("derivation")
    if not isinstance(derivation, dict):
        return []
    refs = []
    variables = derivation.get("variables")
    if isinstance(variables, dict):
        refs += [v for v in variables.values() if isinstance(v, str)]
    selected = derivation.get("selected_ref")
    if isinstance(selected, str):
        refs.append(selected)
    return refs


def internal_reference_problems(view_project, config, new_register,
                                new_decisions, touched_ids, changed_evidence):
    """Canale referenziale pre-commit TM-interno.

    `validate_referential_integrity` NON è invocato come CLI: le sue fasi
    sono candidate/egress e richiedono un `--candidate` che in un update non
    esiste; con `--phase impact` produrrebbe exit 2. Si importano invece le
    sole funzioni PURE del modulo (`find_derivation_cycles`,
    `load_evidence_ids`), come già fa
    `canonical_derivation_cycle_problems()`. La direzione della dipendenza
    resta unidirezionale transaction → validators.

    Ritorna la lista di `(codice, messaggio)`; vuota = nessun problema."""
    problems = []
    # (1) schema del nuovo assumptions-register e del nuovo decisions-register
    for error in schema_errors("assumptions-register", new_register,
                               "proposed " + REGISTER_REL):
        problems.append(("schema_invalid", error))
    for error in decisions_register_problems(new_decisions,
                                             "proposed " + DECISIONS_REL):
        problems.append(("schema_invalid", error))
    if problems:
        return problems

    by_id = {e.get("id"): e for e in new_register if isinstance(e, dict)}

    # (3) ogni ASS-* citato da derivation.variables/selected_ref esiste nel
    #     registro AGGIORNATO (il controllo 2 sulle chiavi gira prima, nel
    #     contratto del payload: se il set delle chiavi è già cambiato, la
    #     risoluzione dei nuovi valori è irrilevante)
    for entry_id in touched_ids:
        for ref in derivation_refs(by_id.get(entry_id, {})):
            if ref not in by_id:
                problems.append((
                    "derivation_variable_unresolved",
                    f"{entry_id}: derivation punta a {ref}, assente dal "
                    "registro aggiornato"))

    # (4) nessun ciclo di derivation sull'INTERO registro risultante: più
    #     forte del refint di candidate, che girava sull'overlay
    problems += [("circular_derivation", message)
                 for message in canonical_derivation_cycle_problems(
                     new_register, "proposed " + REGISTER_REL)]

    # (5) ogni EVD-* introdotto dal payload esiste nel registro evidenze
    if changed_evidence:
        evidence_ids = refint.load_evidence_ids(
            fw.ProjectState(view_project, config))
        for entry_id, ref in sorted(changed_evidence):
            if ref not in evidence_ids:
                problems.append((
                    "evidence_ref_not_found",
                    f"{entry_id}: evidence_ref inesistente: {ref}"))

    # (6) nessun P-ASS-* nel canonico proposto
    for label, document in (("assumptions-register", new_register),
                            ("decisions-register", new_decisions)):
        if P_ASS_TEXT_RE.search(json.dumps(document, ensure_ascii=True)):
            problems.append(("pass_in_canonical",
                             f"P-ASS-* nel canonico proposto ({label})"))
    return problems


def _copy_tree_excluding_tx(src, dest):
    """Copia ricorsiva byte-a-byte con UNA sola esclusione: `.tx/`.

    L'esclusione è obbligatoria e ricorsiva: senza di essa la view
    conterrebbe una copia di `shared/.tx/` e quindi, ricorsivamente, di sé
    stessa. Nessun symlink/junction viene seguito o ricreato (coerente con
    il path containment)."""
    dest.mkdir(parents=True, exist_ok=True)
    for item in sorted(Path(src).iterdir()):
        if item.name == ".tx" or _is_link_or_reparse(item):
            continue
        if item.is_dir():
            _copy_tree_excluding_tx(item, dest / item.name)
        elif item.is_file():
            shutil.copyfile(item, dest / item.name)


def build_validation_view(project, tx_id, replacements, config):
    """Materializza la validation view project-shaped.

    Due passi deterministici: (1) copia byte-identica dell'INTERA `shared/`
    canonica, esclusa ricorsivamente `.tx/`; (2) sostituzione dei soli file
    modificati dalla transazione con le versioni proposte, serializzate
    esattamente come verranno scritte in `applying` (byte validati = byte
    committati). Più, fuori da `shared/`, ogni
    `NN_*/structured-output.json` canonico: sono l'input dei validator di
    dominio in fase impact.

    La copia COMPLETA (mai un elenco chiuso) rende la view
    indistinguibile da un progetto reale per qualunque lettore presente o
    futuro: un registro non enumerato produrrebbe un FAIL o un exit 3 spurio
    su un update legittimo."""
    rel_root = f"{TX_REL}/{tx_id}-validation-view"
    view = resolve_in_project(project, rel_root, "validation-view")
    if view.exists():
        shutil.rmtree(view)
    _copy_tree_excluding_tx(
        resolve_in_project(project, "shared", "shared"), view / "shared")
    for stage in config["stage_order"]:
        source = Path(project) / stage / "structured-output.json"
        if source.is_file() and not _is_link_or_reparse(source):
            dest = view / stage / "structured-output.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
    for rel, data in replacements.items():
        target = view / safe_rel_path(rel, "validation-view target")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return rel_root, view


def cleanup_validation_view(project, rel):
    """La view vive sotto la transazione: rimossa best-effort a ogni stato
    terminale e dal `recover` per i journal terminali. Non fa parte del
    write-set canonico e non partecipa a snapshot/restore; una view residua
    dopo un crash è inerte (nessun comando la legge se non esplicitamente
    puntato)."""
    if not rel:
        return "skipped:no-path"
    try:
        path = resolve_in_project(project, rel, "validation-view")
    except TransactionError:
        return "skipped:path-escape"
    if not path.is_dir() or _is_link_or_reparse(path):
        return "skipped:absent"
    try:
        shutil.rmtree(path)
        return "removed"
    except OSError as exc:
        return f"skipped:{exc.__class__.__name__}"


def beyond_release_boundary(stage, config):
    """True se `stage` supera `release_boundary`, l'ultimo stage implementato.
    Senza `release_boundary` in config nessuno stage è oltre il confine. Con
    la configurazione distribuita il confine è `13_document-generation`,
    ultimo stage di `stage_order`: nessuno stage reale lo supera."""
    boundary = config.get("release_boundary")
    if not boundary or not stage:
        return False
    try:
        return fw.stage_ordinal(stage, config) > \
            fw.stage_ordinal(boundary, config)
    except fw.ValidatorUsageError:
        return False


def boundary_next_action(next_stage, config):
    """`next_action` boundary-aware, calcolato NELLA STESSA transazione
    dell'advance: non esiste alcuna finestra in cui il project-status inviti
    ad avviare uno stage non implementato. Il ramo «oltre il confine» vale
    solo se `release_boundary` precede l'ultimo stage di `stage_order`;
    l'advance dello stage terminale non passa da qui ma porta il progetto
    allo stato terminale del piano (`plan-complete`)."""
    if beyond_release_boundary(next_stage, config):
        return (f"release boundary {config.get('release_boundary')}: "
                f"{next_stage} è oltre il release_boundary configurato; "
                "nessuno stage avviabile oltre il confine")
    return f"avviare {next_stage}"


def impact_window(config, current_stage):
    """Finestra della matrice impact.

    È una funzione PURA di `(4, current_stage)`: limite inferiore sempre
    Stage 4, limite superiore sempre il `current_stage` del progetto, mai
    oltre il `release_boundary`. `affected_sections` — o qualunque euristica
    sul contenuto del change-set — non restringe mai la finestra: una
    rottura visibile solo su uno stage fuori da una finestra «ristretta»
    resterebbe altrimenti invisibile."""
    upper = fw.stage_ordinal(current_stage, config)
    boundary = config.get("release_boundary")
    if boundary:
        upper = min(upper, fw.stage_ordinal(boundary, config))
    window = [(int(ordinal), folder)
              for folder, ordinal in config["stage_order"].items()
              if 4 <= int(ordinal) <= upper]
    return [folder for _, folder in sorted(window)]


def run_impact_validators(config, view_project, view_rel, stages):
    """Runner della finestra impact: itera gli
    stage della finestra e invoca, per ciascuno, i validator applicabili
    secondo la matrice, con `--project <view> --phase impact` e MAI
    `--candidate` (che resta riservato alla semantica P-ASS-only di
    candidate/egress).

    Si iterano i soli validator di `egress_required` — la lista contrattuale
    dei validator davvero implementati — intersecata con quelli che
    dichiarano la fase `impact`: un validator di dominio entra nella
    finestra automaticamente quando è aggiunto a `egress_required`.
    `validate_referential_integrity` non compare mai qui: le sue fasi sono
    candidate/egress e `--phase impact` sarebbe un errore d'uso (exit 2)."""
    import subprocess
    results = []
    invoked = []
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    for stage in stages:
        stage_ord = fw.stage_ordinal(stage, config)
        for name in config.get("egress_required", []):
            spec = config.get("validators", {}).get(name, {})
            if "impact" not in spec.get("phases", []):
                continue
            stages_cfg = spec.get("stages")
            if stages_cfg is not None and \
                    stage_ord not in [int(s) for s in stages_cfg]:
                continue
            script = SKILL_ROOT / "validators" / f"{name}.py"
            if not script.exists():
                raise fw.ValidatorUsageError(
                    f"validator richiesto assente: {name}")
            proc = subprocess.run(
                [sys.executable, str(script), "--project", str(view_project),
                 "--stage", stage, "--phase", "impact"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", env=env)
            try:
                report = json.loads(proc.stdout)
            except json.JSONDecodeError:
                report = {"raw_stdout": proc.stdout, "stderr": proc.stderr}
            results.append({"validator": name, "stage": stage,
                            "phase": "impact", "project": view_rel,
                            "exit_code": proc.returncode, "report": report})
            invoked.append({"validator": name, "stage": stage})
    return results, invoked


def _status_updates_for_decision(project, current_task, next_action):
    """project-status nella stessa transazione: se il progetto era in
    `conflict_awaiting_confirmation`, la decisione lo risolve."""
    front, _ = read_project_status(project)
    updates = {"current_task": current_task,
               "last_updated": now_iso()[:10]}
    if front.get("status") == "conflict_awaiting_confirmation":
        updates["status"] = "in_progress"
        updates["next_action"] = next_action
    return updates


def cmd_update_assumption(args):
    config = fw.load_config()
    project = Path(args.project)
    if not project.is_dir():
        raise fw.ValidatorUsageError(f"project dir inesistente: {project}")
    payload = load_changes_payload(args.changes)
    operation_id = payload["operation_id"]
    request_hash = update_request_payload_hash(payload)
    reason = payload.get("reason") or ""
    action = "tx_update_assumption"

    tx_id = (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
             + "-" + uuid.uuid4().hex[:10])
    tx_dir = resolve_in_project(project, TX_REL, "transaction-dir")
    tx_dir.mkdir(parents=True, exist_ok=True)
    journal_path = resolve_in_project(project, f"{TX_REL}/{tx_id}.json",
                                      "journal")

    acquire_lock(project, tx_id)
    journal = None
    try:
        _schema_cache.clear()
        enforcement_hashes = enforcement_artifact_hashes(config, loaded=True)
        validate_canonical_state(project, config)

        # idempotenza PRIMA di ogni marker: l'identità è
        # operation_id + request_payload_hash, mai il reason testuale
        decisions, decisions_raw = read_decisions_register(project)
        if decisions is None:
            decisions = init_decisions_register(project, operation_id)
        existing = find_decision_by_operation_id(decisions, operation_id)
        if existing is not None:
            if existing.get("request_payload_hash") == request_hash:
                print(json.dumps(
                    {"result": "already_applied", "operation_id": operation_id,
                     "decision_id": existing.get("id")},
                    ensure_ascii=True, indent=2))
                return 0
            print(json.dumps(
                {"result": "rejected",
                 "errors": [{"code": "operation_id_conflict",
                             "message": f"operation_id {operation_id!r} già "
                                        f"usato con un payload diverso "
                                        f"({existing.get('id')})"}]},
                ensure_ascii=True, indent=2))
            return 1

        register_path = resolve_in_project(project, REGISTER_REL, "register")
        register_bytes = register_path.read_bytes()
        register = json.loads(register_bytes.decode("utf-8"))
        target_refs = [c["assumption_id"] for c in payload["changes"]]

        journal = {
            "transaction_id": tx_id,
            "project": str(project),
            "stage": None,
            "mode": "update_assumption",
            "operation_id": operation_id,
            "request_payload_hash": request_hash,
            "target_refs": target_refs,
            "candidate_path": None,
            "candidate_snapshot_path": None,
            "candidate_hash": None,
            "enforcement_hashes": enforcement_hashes,
            "reserved_decision_id": None,
            "register_hash": sha256_bytes(register_bytes),
            "decisions_register_hash": (sha256_bytes(decisions_raw)
                                        if decisions_raw is not None else None),
            "validation_view_path": None,
            "validators_invoked": [],
            "state": "preparing",
            "snapshot_path": f"{TX_REL}/{tx_id}-snapshot",
            "write_set": [],
            "pass_map": {},
            "validation": [],
            "timestamps": {"preparing": now_iso()},
            "error": None,
            "recovery_action": None,
        }
        save_journal(journal_path, journal)

        def reject(code, message, extra_errors=None):
            journal["state"] = "rolled_back"
            journal["error"] = {"code": code, "message": message}
            journal["timestamps"]["finalized"] = now_iso()
            save_journal(journal_path, journal)
            append_audit(project, tx_id, None, action, "rejected", [])
            errors = [{"code": code, "message": message}]
            if extra_errors:
                errors += extra_errors
            print(json.dumps({"result": "rejected", "transaction_id": tx_id,
                              "errors": errors}, ensure_ascii=True, indent=2))
            return 1

        # contratto del payload
        problem = decision_payload_problem(payload.get("decision"),
                                           "assumption_update")
        if problem:
            return reject("decision_required", problem)
        if len(set(target_refs)) != len(target_refs):
            return reject(
                "duplicate_assumption_change",
                "un record, un change: assumption_id duplicato nel payload")

        by_id = {e.get("id"): e for e in register if isinstance(e, dict)}
        for change in payload["changes"]:
            assumption_id = change["assumption_id"]
            current = by_id.get(assumption_id)
            if current is None:
                return reject(
                    "assumption_not_found",
                    f"assunzione inesistente nel registro canonico: "
                    f"{assumption_id}")
            outside = sorted(set(change["updates"]) - UPDATE_FIELD_WHITELIST)
            if outside:
                return reject(
                    "update_field_not_allowed",
                    f"{assumption_id}: campi fuori whitelist: {outside}")
            # CAS su fingerprint strutturato del record intero
            if change.get("expected_record_hash") != \
                    record_fingerprint(current):
                return reject(
                    "stale_record_hash",
                    f"{assumption_id}: expected_record_hash non corrisponde "
                    "al record canonico corrente (record modificato dopo la "
                    "lettura di show-assumption)")

        # (2) il set delle chiavi di derivation.variables deve restare
        # IDENTICO: solo i valori possono cambiare. Gira PRIMA della
        # risoluzione dei ref: altrimenti `derivation.formula`, che referenzia
        # le chiavi per nome, resterebbe disallineata dai variables effettivi.
        for change in payload["changes"]:
            updates = change["updates"]
            if "derivation.variables" not in updates:
                continue
            current = by_id[change["assumption_id"]]
            proposed = updates["derivation.variables"]
            if not isinstance(proposed, dict):
                return reject(
                    "derivation_keys_changed",
                    f"{change['assumption_id']}: derivation.variables deve "
                    "essere un oggetto")
            if frozenset(proposed) != derivation_keys(current):
                return reject(
                    "derivation_keys_changed",
                    f"{change['assumption_id']}: il set delle chiavi di "
                    "derivation.variables non è modificabile "
                    f"(atteso {sorted(derivation_keys(current))}, proposto "
                    f"{sorted(proposed)})")

        # derivate: il value di una entry `derived` cambia solo se
        # l'operazione rende coerente il ricalcolo
        touched = set(target_refs)
        for change in payload["changes"]:
            current = by_id[change["assumption_id"]]
            updates = change["updates"]
            if current.get("kind") != "derived" or "value" not in updates:
                continue
            if "derivation.variables" in updates:
                continue
            drivers = set(derivation_refs(current))
            if not drivers & (touched - {change["assumption_id"]}):
                return reject(
                    "derived_update_incoherent",
                    f"{change['assumption_id']} è derivata: il suo value non "
                    "può cambiare senza che l'operazione aggiorni i driver o "
                    "ri-referenzi la derivation")

        # riserva DEC: id DEFINITIVO già qui, mai un placeholder;
        # nessuna scrittura canonica prima di applying, quindi un rollback non
        # consuma l'id
        reserved_decision_id = next_decision_id(decisions)
        journal["reserved_decision_id"] = reserved_decision_id
        save_journal(journal_path, journal)

        # contenuti proposti
        new_register = []
        updates_by_id = {c["assumption_id"]: c["updates"]
                         for c in payload["changes"]}
        changed_evidence = set()
        for entry in register:
            entry_id = entry.get("id") if isinstance(entry, dict) else None
            if entry_id in updates_by_id:
                updates = updates_by_id[entry_id]
                new_register.append(apply_record_updates(
                    entry, updates, reason, reserved_decision_id))
                for ref in updates.get("evidence_refs", []) or []:
                    changed_evidence.add((entry_id, ref))
            else:
                new_register.append(entry)

        decision_record = build_decision_record(
            reserved_decision_id, operation_id, request_hash,
            payload["decision"], sorted(set(target_refs)))
        new_decisions = json.loads(json.dumps(decisions))
        new_decisions["decisions"] = list(new_decisions["decisions"]) + \
            [decision_record]

        # validation view project-shaped: i byte materializzati qui
        # sono ESATTAMENTE quelli che verranno scritti in applying
        register_bytes_new = dump_json_bytes(new_register)
        decisions_bytes_new = dump_json_bytes(new_decisions)
        view_rel, view_path = build_validation_view(
            project, tx_id, {REGISTER_REL: register_bytes_new,
                             DECISIONS_REL: decisions_bytes_new}, config)
        journal["validation_view_path"] = view_rel
        save_journal(journal_path, journal)

        # pre-commit validation, canale (a): controlli TM-interni puri,
        # tutti sulla view, mai sul canonico
        problems = internal_reference_problems(
            view_path, config, new_register, new_decisions, touched,
            changed_evidence)
        if problems:
            return reject(
                problems[0][0], problems[0][1],
                [{"code": code, "message": message}
                 for code, message in problems[1:]])

        # pre-commit validation, canale (b): matrice impact dei validator di
        # dominio sulla finestra fissa 4..current_stage
        front_now, _ = read_project_status(project)
        window = impact_window(config, front_now.get("current_stage"))
        validation, invoked = run_impact_validators(
            config, view_path, view_rel, window)
        journal["validation"] = validation
        journal["validators_invoked"] = invoked
        save_journal(journal_path, journal)
        failed = [v for v in validation if v["exit_code"] != 0]
        if failed:
            return reject(
                "impact_validation_failed",
                "matrice impact non superata sulla validation view: nessuna "
                "applicazione canonica",
                [{"code": "validator_failed",
                  "message": f"{v['validator']} ({v['stage']}) exit "
                             f"{v['exit_code']}"} for v in failed])

        # snapshot dello stato canonico toccato
        contents = {
            REGISTER_REL: register_bytes_new,
            DECISIONS_REL: decisions_bytes_new,
            DECISION_LOG_REL: append_decision_log(
                project,
                decision_log_row(
                    decision_record,
                    "aggiornamento assunzioni "
                    + ", ".join(sorted(set(target_refs))),
                    "`shared/assumptions-register.json`")),
        }
        contents[STATUS_REL] = build_status_update(
            project,
            _status_updates_for_decision(
                project, "assumption-updated",
                "riprendere lo stage con i valori canonici aggiornati"))

        snapshot_dir = resolve_in_project(project, journal["snapshot_path"],
                                          "snapshot_path")
        pre_hashes = {}
        for rel in (REGISTER_REL, DECISIONS_REL, DECISION_LOG_REL, STATUS_REL,
                    AUDIT_REL):
            source = resolve_in_project(project, rel, "snapshot target")
            if source.exists():
                pre_hashes[rel] = sha256_file(source)
                dest = snapshot_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
            else:
                pre_hashes[rel] = None
        journal["state"] = "snapshot_taken"
        journal["timestamps"]["snapshot_taken"] = now_iso()
        save_journal(journal_path, journal)

        journal["state"] = "validated"
        journal["timestamps"]["validated"] = now_iso()
        save_journal(journal_path, journal)

        # hook della suite: scrittore concorrente sul canonico nella finestra
        # fra validazione e applicazione (esercita il CAS di conferma)
        _test_mutation_hook("BPO_TX_TEST_MUTATE_CANONICAL", project)

        # CAS di conferma (TOCTOU): i byte canonici devono ancora
        # hashare ai valori registrati nel journal
        drift = []
        if sha256_file(register_path) != journal["register_hash"]:
            drift.append(REGISTER_REL)
        decisions_path = resolve_in_project(project, DECISIONS_REL,
                                            "decisions-register")
        current_decisions_hash = sha256_file(decisions_path) \
            if decisions_path.exists() else None
        if current_decisions_hash != journal["decisions_register_hash"]:
            drift.append(DECISIONS_REL)
        if drift:
            journal["state"] = "rolled_back"
            journal["error"] = {"code": "canonical_drift",
                                "message": "byte canonici divergenti: "
                                           + ", ".join(drift)}
            journal["timestamps"]["finalized"] = now_iso()
            save_journal(journal_path, journal)
            append_audit(project, tx_id, None, action, "rolled_back", [])
            print(json.dumps(
                {"result": "rejected", "transaction_id": tx_id,
                 "errors": [{"code": "canonical_drift",
                             "message": journal["error"]["message"]}]},
                ensure_ascii=True, indent=2))
            return 1

        audit_target = resolve_in_project(project, AUDIT_REL, "audit")
        audit_existing = audit_target.read_bytes() \
            if audit_target.exists() else b""
        contents[AUDIT_REL] = audit_existing + audit_event_line(
            tx_id, None, action, "applied", sorted(set(target_refs)),
            operation_id=operation_id).encode("utf-8")

        journal["write_set"] = [
            {"path": rel, "pre_hash": pre_hashes.get(rel),
             "post_hash": sha256_bytes(data)}
            for rel, data in contents.items()
        ]
        journal["state"] = "applying"
        journal["timestamps"]["applying"] = now_iso()
        save_journal(journal_path, journal)

        try:
            for rel, data in contents.items():
                write_file(resolve_in_project(project, rel, "write target"),
                           data)
        except OSError as exc:
            restore_snapshot(project, journal)
            journal["state"] = "rolled_back"
            journal["error"] = {"code": "write_failed", "message": str(exc)}
            journal["timestamps"]["finalized"] = now_iso()
            save_journal(journal_path, journal)
            append_audit(project, tx_id, None, action, "rolled_back", [])
            raise TransactionError(
                "write_failed",
                f"write canonica fallita, rollback eseguito: {exc}",
                exit_code=3)

        # hook della suite: corruzione di un target del write-set dopo la
        # write e prima della verifica (esercita il rollback da snapshot)
        _test_mutation_hook("BPO_TX_TEST_CORRUPT_AFTER_WRITE", project)

        problems = verify_write_set(project, journal)
        if problems:
            restore_snapshot(project, journal)
            journal["state"] = "rolled_back"
            journal["error"] = {"code": "content_verification_failed",
                                "message": "; ".join(problems)}
            journal["timestamps"]["finalized"] = now_iso()
            save_journal(journal_path, journal)
            append_audit(project, tx_id, None, action, "rolled_back", [])
            raise TransactionError(
                "content_verification_failed",
                "verifica post-applicazione fallita: rollback eseguito",
                exit_code=3)

        _crash_hook("before_commit")
        journal["state"] = "committed"
        journal["timestamps"]["committed"] = now_iso()
        journal["timestamps"]["finalized"] = now_iso()
        save_journal(journal_path, journal)
        print(json.dumps({"result": "applied", "transaction_id": tx_id,
                          "operation_id": operation_id,
                          "decision_id": reserved_decision_id,
                          "updated_refs": sorted(set(target_refs)),
                          "journal": f"{TX_REL}/{tx_id}.json"},
                         ensure_ascii=True, indent=2))
        return 0
    finally:
        if journal is not None:
            cleanup_validation_view(project,
                                    journal.get("validation_view_path"))
        release_lock(project, tx_id)


# --------------------------------------------------------------------------
# recover
# --------------------------------------------------------------------------

def cmd_recover(args):
    config = fw.load_config()
    project = Path(args.project)
    if not project.is_dir():
        raise fw.ValidatorUsageError(f"project dir inesistente: {project}")
    # la transaction directory passa dal boundary PRIMA di glob/lock;
    # se shared/.tx è un reparse point -> path_escape (exit 3), nessuna I/O.
    tx_dir = resolve_in_project(project, TX_REL, "transaction-dir")
    recovery_id = "recovery-" + uuid.uuid4().hex[:10]

    lock = lock_path(project)
    if lock.exists():
        try:
            info = json.loads(lock.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise TransactionError(
                "lock_held", "lock illeggibile: ispezione manuale richiesta")
        alive = _lock_owner_alive(info)
        if alive is not False:
            raise TransactionError(
                "lock_held",
                f"transazione attiva (pid {info.get('pid')}): recovery "
                "rifiutato")
    acquire_lock(project, recovery_id, allow_stale_takeover=True)
    actions = []
    pending_audit = []
    try:
        if tx_dir.is_dir():
            for journal_path in sorted(tx_dir.glob("*.json")):
                journal = load_journal(journal_path)
                state = journal.get("state")
                tx_id = journal.get("transaction_id", journal_path.stem)
                if state in FINAL_STATES:
                    # un candidate rimasto attivo dopo uno stato
                    # terminale non deve poter essere riapplicato
                    cleanup_active_candidate(project,
                                             journal.get("candidate_path"),
                                             stage=journal.get("stage"))
                    # stessa regola per la validation view residua
                    cleanup_validation_view(
                        project, journal.get("validation_view_path"))
                    continue
                if state != "applying":
                    journal["state"] = "rolled_back"
                    journal["recovery_action"] = "discarded_before_applying"
                    journal["timestamps"]["finalized"] = now_iso()
                    journal["candidate_cleanup"] = cleanup_active_candidate(
                        project, journal.get("candidate_path"),
                        stage=journal.get("stage"))
                    # la view di un journal appena finalizzato è
                    # residua e va rimossa come il candidate snapshot
                    journal["validation_view_cleanup"] = \
                        cleanup_validation_view(
                            project, journal.get("validation_view_path"))
                    save_journal(journal_path, journal)
                    pending_audit.append((tx_id, journal.get("stage"),
                                          "tx_recover", "rolled_back", []))
                    actions.append({"transaction_id": tx_id,
                                    "action": "rolled_back",
                                    "reason": f"state was {state}"})
                    continue
                problems = verify_write_set(project, journal)
                if not problems:
                    # il recovery marker-only rivalida lo snapshot del
                    # candidate e gli enforcement artifacts prima del marker;
                    # un drift chiude la finestra verifica->marker con un
                    # rollback, non con un commit.
                    problems = recovery_binding_problems(project, journal,
                                                         config)
                if not problems:
                    journal["state"] = "committed"
                    journal["recovery_action"] = "completed_marker_only"
                    journal["timestamps"]["committed"] = now_iso()
                    journal["timestamps"]["finalized"] = now_iso()
                    journal["candidate_cleanup"] = cleanup_active_candidate(
                        project, journal.get("candidate_path"),
                        stage=journal.get("stage"))
                    # la view di un journal appena finalizzato è
                    # residua e va rimossa come il candidate snapshot
                    journal["validation_view_cleanup"] = \
                        cleanup_validation_view(
                            project, journal.get("validation_view_path"))
                    save_journal(journal_path, journal)
                    # l'evento `applied` è già dentro il write-set verificato
                    # (audit protocol): il recovery non lo duplica
                    actions.append({"transaction_id": tx_id,
                                    "action": "committed",
                                    "reason": "write-set completo e "
                                              "verificato nel contenuto"})
                else:
                    restore_snapshot(project, journal)
                    journal["state"] = "rolled_back"
                    journal["recovery_action"] = "restored_snapshot"
                    journal["error"] = {"code": "incomplete_applying",
                                        "message": "; ".join(problems)}
                    journal["timestamps"]["finalized"] = now_iso()
                    journal["candidate_cleanup"] = cleanup_active_candidate(
                        project, journal.get("candidate_path"),
                        stage=journal.get("stage"))
                    # la view di un journal appena finalizzato è
                    # residua e va rimossa come il candidate snapshot
                    journal["validation_view_cleanup"] = \
                        cleanup_validation_view(
                            project, journal.get("validation_view_path"))
                    save_journal(journal_path, journal)
                    pending_audit.append((tx_id, journal.get("stage"),
                                          "tx_recover",
                                          "recovered_rolled_back", []))
                    actions.append({"transaction_id": tx_id,
                                    "action": "rolled_back",
                                    "reason": "; ".join(problems)})
        # gli append di audit del recovery avvengono DOPO ogni verifica di
        # hash, per non invalidare i write-set ancora da verificare
        for event in pending_audit:
            append_audit(project, *event)
        print(json.dumps({"result": "recovered", "actions": actions},
                         ensure_ascii=True, indent=2))
        return 0
    finally:
        release_lock(project, recovery_id)


# --------------------------------------------------------------------------
# governance-status (scrittura journaled di project-status.md e audit)
# --------------------------------------------------------------------------

def cmd_governance_status(args):
    config = fw.load_config()
    project = Path(args.project)
    if not project.is_dir():
        raise fw.ValidatorUsageError(f"project dir inesistente: {project}")
    try:
        updates = json.loads(args.updates)
    except json.JSONDecodeError as exc:
        raise fw.ValidatorUsageError(f"--updates non è JSON valido: {exc}")
    if not isinstance(updates, dict) or not updates:
        raise fw.ValidatorUsageError("--updates deve essere un oggetto JSON")
    allowed = {"status", "current_task", "next_action", "last_updated",
               "blocking_issues", "open_questions"}
    unknown = set(updates) - allowed
    if unknown:
        raise fw.ValidatorUsageError(
            f"campi non governabili da questo entry point: {sorted(unknown)}")
    if "status" in updates:
        # governance-status è limitato agli stati amministrativi non
        # approvativi. Qualsiasi stato che equivale a superamento del gate
        # (approved, approved_with_conditions) passa ESCLUSIVAMENTE dal
        # percorso transazionale advance-stage (validator + snapshot +
        # journal + audit + recovery).
        if updates["status"] not in GOVERNANCE_ALLOWED_STATES:
            raise fw.ValidatorUsageError(
                f"status non impostabile via governance-status: "
                f"{updates['status']!r} (ammessi solo "
                f"{sorted(GOVERNANCE_ALLOWED_STATES)}; le approvazioni "
                "passano da advance-stage)")
    # lo stato canonico letto deve essere valido prima della scrittura
    validate_canonical_state(project, config)
    if "status" in updates:
        # portare a uno stato ATTIVO un current_stage oltre il release
        # boundary equivale ad avviare uno stage non implementato
        front_boundary, _ = read_project_status(project)
        if beyond_release_boundary(front_boundary.get("current_stage"),
                                   config):
            raise TransactionError(
                "stage_not_implemented",
                f"current_stage {front_boundary.get('current_stage')!r} è "
                f"oltre il release boundary "
                f"{config.get('release_boundary')!r}: nessuno stato attivo "
                "impostabile su uno stage non implementato",
                exit_code=1)
    if "status" in updates:
        # governance-status non può riaprire uno stage già completed
        # portandolo a uno stato attivo (in_progress/needs_revision/blocked/
        # conflict). Un deliverable in completed_stages resta approved*: la
        # riapertura via protocollo ISSUE non è implementata qui.
        front_now, _ = read_project_status(project)
        completed_now = front_now.get("completed_stages", [])
        current_now = front_now.get("current_stage")
        approved_states = set(config.get("approved_states", []))
        if isinstance(completed_now, list) and current_now in completed_now \
                and updates["status"] not in approved_states:
            raise fw.ValidatorUsageError(
                f"status {updates['status']!r} non impostabile: lo stage "
                f"{current_now} è già in completed_stages e non è riapribile "
                "(riapertura di uno stage approvato non supportata)")
    gov_id = (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
              + "-gov-" + uuid.uuid4().hex[:10])
    # transaction directory e journal dal boundary prima di ogni I/O
    tx_dir = resolve_in_project(project, TX_REL, "transaction-dir")
    tx_dir.mkdir(parents=True, exist_ok=True)
    journal_path = resolve_in_project(project, f"{TX_REL}/{gov_id}.json",
                                      "journal")
    acquire_lock(project, gov_id)
    try:
        journal = {
            "transaction_id": gov_id,
            "project": str(project),
            "stage": None,
            "candidate_path": None,
            "candidate_snapshot_path": None,
            "candidate_hash": None,
            "state": "preparing",
            "snapshot_path": f"{TX_REL}/{gov_id}-snapshot",
            "write_set": [],
            "pass_map": {},
            "validation": [],
            "timestamps": {"preparing": now_iso()},
            "error": None,
            "recovery_action": None,
        }
        save_journal(journal_path, journal)

        snapshot_dir = resolve_in_project(project, journal["snapshot_path"],
                                          "snapshot_path")
        pre_hashes = {}
        for rel in (STATUS_REL, AUDIT_REL):
            source = resolve_in_project(project, rel, "snapshot target")
            if source.exists():
                pre_hashes[rel] = sha256_file(source)
                dest = snapshot_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
            else:
                pre_hashes[rel] = None
        journal["state"] = "snapshot_taken"
        journal["timestamps"]["snapshot_taken"] = now_iso()
        save_journal(journal_path, journal)

        audit_target = resolve_in_project(project, AUDIT_REL, "audit")
        audit_existing = audit_target.read_bytes() \
            if audit_target.exists() else b""
        contents = {
            STATUS_REL: build_status_update(project, updates),
            AUDIT_REL: audit_existing + audit_event_line(
                args.transaction_id or gov_id, None,
                "governance_status_update", "applied",
                sorted(updates.keys())).encode("utf-8"),
        }
        journal["write_set"] = [
            {"path": rel, "pre_hash": pre_hashes.get(rel),
             "post_hash": sha256_bytes(data)}
            for rel, data in contents.items()
        ]
        journal["state"] = "applying"
        journal["timestamps"]["applying"] = now_iso()
        save_journal(journal_path, journal)

        try:
            for rel, data in contents.items():
                write_file(resolve_in_project(project, rel, "write target"),
                           data)
        except OSError as exc:
            restore_snapshot(project, journal)
            journal["state"] = "rolled_back"
            journal["error"] = {"code": "write_failed", "message": str(exc)}
            journal["timestamps"]["finalized"] = now_iso()
            save_journal(journal_path, journal)
            raise TransactionError(
                "write_failed",
                f"write governance fallita, rollback eseguito: {exc}",
                exit_code=3)

        problems = verify_write_set(project, journal)
        if problems:
            restore_snapshot(project, journal)
            journal["state"] = "rolled_back"
            journal["error"] = {"code": "content_verification_failed",
                                "message": "; ".join(problems)}
            journal["timestamps"]["finalized"] = now_iso()
            save_journal(journal_path, journal)
            raise TransactionError(
                "content_verification_failed",
                "verifica post-applicazione fallita: rollback eseguito",
                exit_code=3)

        _crash_hook("before_commit")
        journal["state"] = "committed"
        journal["timestamps"]["committed"] = now_iso()
        journal["timestamps"]["finalized"] = now_iso()
        save_journal(journal_path, journal)
        print(json.dumps({"result": "applied", "updates": updates,
                          "reason": args.reason}, ensure_ascii=True,
                         indent=2))
        return 0
    finally:
        release_lock(project, gov_id)


def main():
    parser = argparse.ArgumentParser(prog="transaction_manager")
    sub = parser.add_subparsers(dest="command")
    p_apply = sub.add_parser("apply")
    p_apply.add_argument("--project", required=True)
    p_apply.add_argument("--stage", required=True)
    p_apply.add_argument("--candidate", required=True)
    p_apply.add_argument("--report")
    p_advance = sub.add_parser("advance-stage")
    p_advance.add_argument("--project", required=True)
    p_advance.add_argument("--stage", required=True)
    p_advance.add_argument("--candidate", required=True)
    p_advance.add_argument("--report")
    p_advance.add_argument("--gate-result", dest="gate_result",
                           default="approved")
    p_update = sub.add_parser("update-assumption")
    p_update.add_argument("--project", required=True)
    p_update.add_argument("--changes", required=True)
    p_resolve = sub.add_parser("resolve-condition")
    p_resolve.add_argument("--project", required=True)
    p_resolve.add_argument("--condition", required=True)
    p_resolve.add_argument("--resolution", required=True,
                           choices=["resolved", "waived"])
    p_resolve.add_argument("--operation-id", dest="operation_id",
                           required=True)
    # --decision è obbligatorio nel dominio ma non in argparse: la sua
    # assenza deve produrre il codice `decision_required` (exit 1), non un
    # errore d'uso indistinguibile da una CLI sbagliata.
    p_resolve.add_argument("--decision")
    p_resolve.add_argument("--evidence-ref", dest="evidence_ref")
    p_resolve.add_argument("--reason", required=True)
    p_show = sub.add_parser("show-assumption")
    p_show.add_argument("--project", required=True)
    p_show.add_argument("--assumption", required=True)
    p_recover = sub.add_parser("recover")
    p_recover.add_argument("--project", required=True)
    p_gov = sub.add_parser("governance-status")
    p_gov.add_argument("--project", required=True)
    p_gov.add_argument("--updates", required=True)
    p_gov.add_argument("--reason", required=True)
    p_gov.add_argument("--transaction-id")
    try:
        args = parser.parse_args()
    except SystemExit:
        sys.exit(2)
    try:
        if args.command == "apply":
            sys.exit(cmd_apply(args))
        elif args.command == "advance-stage":
            sys.exit(cmd_advance_stage(args))
        elif args.command == "update-assumption":
            sys.exit(cmd_update_assumption(args))
        elif args.command == "resolve-condition":
            sys.exit(cmd_resolve_condition(args))
        elif args.command == "show-assumption":
            sys.exit(cmd_show_assumption(args))
        elif args.command == "recover":
            sys.exit(cmd_recover(args))
        elif args.command == "governance-status":
            sys.exit(cmd_governance_status(args))
        else:
            print("comando mancante: apply | advance-stage | "
                  "show-assumption | recover | governance-status",
                  file=sys.stderr)
            sys.exit(2)
    except fw.ValidatorUsageError as exc:
        print(f"transaction_manager: {exc}", file=sys.stderr)
        sys.exit(2)
    except fw.CanonicalStateError as exc:
        print(json.dumps({"result": "error",
                          "errors": [{"code": "corrupted_state",
                                      "message": str(exc)}]},
                         ensure_ascii=True))
        sys.exit(3)
    except TransactionError as exc:
        print(json.dumps({"result": "rejected" if exc.exit_code == 1
                          else "error",
                          "errors": [{"code": exc.code,
                                      "message": exc.message}]},
                         ensure_ascii=True))
        sys.exit(exc.exit_code)


if __name__ == "__main__":
    main()
