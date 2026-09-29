#!/usr/bin/env python3
"""T-DATA-ROOM — i TRENTADUE contratti della Data Room (Stage 12).

Modulo di test dello Stage 12 `12_data-room`, costruito sullo stesso modello
di `tests/integration/test_funding_request.py`,
`tests/integration/test_fin_output.py` e `tests/integration/test_fin_tx.py`.
Entra nel glob di ENTRAMBI i runner (`tests/run-tests.ps1` e
`tests/run-tests.sh` globano `tests/integration/test_*.py`) senza alcuna
modifica ai runner.

PERIMETRO. Lo Stage 12 indicizza gli artefatti degli stage precedenti e i
file forniti dall'utente; lo spazio di nomi `CLM-*` dei claim appartiene
allo Stage 12; lo stage successivo, `13_document-generation`, e' l'ultimo di
`stage_order` e sta DENTRO il `release_boundary`. Famiglie di etichette:
`DR-C-01`...`-32` (contratti), `MUT-4-28`...`-59` (mutazioni), `DR-P-*`
(sonde di proprieta'), `DR-R-*` (regressioni), `T-DATA-ROOM`.

SUPERFICI LETTE IN MODO DIFENSIVO. I contratti non presuppongono che le
superfici di produzione esistano: un validator, uno schema o un workflow
assente diventa una constatazione nominata, mai un'eccezione.

RED SEMANTICO, MAI UN'ECCEZIONE. Ogni contratto valuta le PROPRIE aspettative
— dichiarazioni dello schema e della metodologia, rifiuto della propria
mutazione con il proprio codice, esito del proprio caso positivo — e le
riporta come constatazioni ATTRIBUITE quando non sono soddisfatte. Nessun
contratto dipende da un `ImportError` o da un `FileNotFoundError`: le
superfici assenti sono lette in modo difensivo e l'assenza diventa
un'aspettativa semantica non soddisfatta, nominata. `run_one` conta a parte
le constatazioni prodotte per ECCEZIONE, e l'uscita le stampa: la loro somma
DEVE essere zero, altrimenti il RED non e' evidenza.

SPECIFICITA' E NON-VACUITA'. Ogni esecuzione di mutazione e' registrata con
exit code e codici osservati. La specificita' di un contratto e' la quota
delle esecuzioni, fra TUTTE quelle del modulo, in cui il suo codice compare
appartenendo a lui o a un contratto che condivide lo stesso codice di
catalogo (`data_room_duplicate_id` per `-C-03`/`-C-26`,
`data_room_origin_ambiguous` per `-C-05`/`-C-31`). La guardia di
non-vacuita' esige, per un GREEN, almeno un'osservazione valutata e almeno
una mutazione UCCISA con il codice atteso.

I TRENTADUE CONTRATTI OSPITATI QUI
----------------------------------
    DR-C-01  T-DR-SECTIONS                 MUT-4-28
    DR-C-02  T-DR-MANIFEST-CLOSED          MUT-4-29
    DR-C-03  T-DR-DOCUMENT-ID              MUT-4-30
    DR-C-04  T-DR-ARTIFACT-TYPE            MUT-4-31
    DR-C-05  T-DR-ORIGIN                   MUT-4-32
    DR-C-06  T-DR-PATHS                    MUT-4-33
    DR-C-07  T-DR-CHECKSUM                 MUT-4-34
    DR-C-08  T-DR-VERSION                  MUT-4-35
    DR-C-09  T-DR-OWNER                    MUT-4-36
    DR-C-10  T-DR-CONFIDENTIALITY          MUT-4-37
    DR-C-11  T-DR-CLAIM-LINKS              MUT-4-38
    DR-C-12  T-DR-RELATED-SECTION          MUT-4-39
    DR-C-13  T-DR-VALIDATION-STATUS        MUT-4-40
    DR-C-14  T-DR-AVAILABILITY             MUT-4-41
    DR-C-15  T-DR-EVIDENCE-QUALITY         MUT-4-42
    DR-C-16  T-DR-IDENTITY                 MUT-4-43
    DR-C-17  T-DR-DETERMINISM              MUT-4-44
    DR-C-18  T-DR-CLAIM-NAMESPACE          MUT-4-45
    DR-C-19  T-DR-LINK-STATUS              MUT-4-46
    DR-C-20  T-DR-SOURCE-HIERARCHY         MUT-4-47
    DR-C-21  T-DR-PROVENANCE               MUT-4-48
    DR-C-22  T-DR-EVIDENCE-GAPS            MUT-4-49
    DR-C-23  T-DR-STALENESS                MUT-4-50
    DR-C-24  T-DR-CONFLICTS                MUT-4-51
    DR-C-25  T-DR-COMPLETENESS             MUT-4-52
    DR-C-26  T-DR-DUPLICATES               MUT-4-53
    DR-C-27  T-DR-ORPHAN-EVIDENCE          MUT-4-54
    DR-C-28  T-DR-UNSUPPORTED-CLAIM        MUT-4-55
    DR-C-29  T-DR-SECRET-LEAK              MUT-4-56
    DR-C-30  T-DR-SOURCE-IMMUTABLE         MUT-4-57
    DR-C-31  T-DR-DERIVED-FROM             MUT-4-58
    DR-C-32  T-DR-DEBT-EXPOSED             MUT-4-59

SONDE DI PROPRIETA' ESEGUITE DENTRO I CONTRATTI
-----------------------------------------------
    DR-P-07  ciclo di vita REALE del TM e negativi Stage 13   DR-C-12
    DR-P-08  canonico non ASCII pubblicato dal TM, egress e
               impact                                           DR-C-17
    DR-P-09  fase impact e canonico assente                   DR-C-08,
                                                                DR-C-14
    DR-P-10  byte-identita' delle fonti e degli stage 00-11   DR-C-30
    DR-P-11  determinismo, nessun orologio                    DR-C-17
    DR-P-12  ogni comando del workflow eseguito come scritto  DR-C-01
    DR-P-13  confine degli import del validator               DR-C-30

SONDE DI REGRESSIONE
--------------------
Una sonda per regressione `DR-R-01`...`-15` (`FINDINGS`), eseguita dopo i 32
contratti (`--finding <id>` per una sola, `--list-findings` per l'elenco). I
32 contratti restano INVARIATI. CONTABILITA' CAUSALE (verificata da
`DR-R-14`): ogni sonda porta CONTROLLI — forme non avversarie che anche
un'implementazione priva della protezione tratta correttamente, falliti solo
da un guasto COMUNE (validator assente, `ImportError`) — e ATTACCHI, le
riproduzioni del difetto; un RED e' CAUSALE solo con tutti i controlli
validi, altrimenti la sonda e' NON-DISCRIMINANTE. `DR-R-14` (autoverifica di
questa contabilita') e `DR-R-15` (protezioni fissate da mutazioni
in-process) sono sonde dell'HARNESS. La scansione DECODIFICATA dei registri
condivisi e la ri-verifica del bersaglio in `publish` sono fissate in
`DR-R-02`, `-03`, `-10` e `-15`.
L'uscita porta una riga per sonda e `SUMMARY-REG`; `--matrix` aggiunge le
righe `REGMATRIX`.

FIXTURE. Le fixture `G-10`...`G-14` sono DICHIARATE IN QUESTO MODULO. La
base e' REALISTICA e costruita dalle SOLE superfici di produzione: la
pipeline dello Stage 10 (motore, costruttore canonico, renderer, exporter,
attraverso l'harness `test_fin_xlsx`), il costruttore dello Stage 11 e
l'`advance-stage` REALE del Transaction Manager, che porta il progetto a
`current_stage = 12_data-room`.
Gli stage 01-09 portano uscite di stage sintetiche DICHIARATE tali. Ogni
progetto vive in una directory TEMPORANEA: nessun progetto reale e' toccato.

Exit code del modulo: 0 tutti GREEN | 1 almeno un RED | 2 errore d'uso |
3 difetto di PREPARAZIONE dell'harness (non e' evidenza RED).
"""
import argparse
import ast
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import types
import unicodedata
import zipfile
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

SKILL_REL = ".claude/skills/business-plan-orchestrator"
TESTKIT_REL = "tests/integration"
XLSX_HARNESS = "test_fin_xlsx"

DR_VALIDATOR_REL = f"{SKILL_REL}/validators/validate_data_room.py"
DR_SCHEMA_REL = f"{SKILL_REL}/schemas/data-room.schema.json"
DR_WORKFLOW_REL = f"{SKILL_REL}/workflows/13_data-room.md"
DR_METHODOLOGY_REL = f"{SKILL_REL}/methodology/data-room.md"
DR_AGENT_REL = f"{SKILL_REL}/runtime-agents/evidence-analyst.md"
FR_VALIDATOR_REL = f"{SKILL_REL}/validators/validate_funding_request.py"
ENFORCEMENT_REL = f"{SKILL_REL}/config/enforcement-config.json"
SCHEMAS_REL = f"{SKILL_REL}/schemas"
CONDITIONS_SCHEMA_REL = f"{SCHEMAS_REL}/conditions-register.schema.json"
EVIDENCE_SCHEMA_REL = f"{SCHEMAS_REL}/evidence-register.schema.json"
SOURCE_SCHEMA_REL = f"{SCHEMAS_REL}/source-register.schema.json"

STAGE10 = "10_financial-plan"
STAGE11 = "11_funding-request"
STAGE12 = "12_data-room"
STAGE13 = "13_document-generation"

CANONICAL_NAME = "structured-output.json"
HANDOFF_NAME = "handoff.md"
INDEX_NAME = "data-room-index.md"
PROPOSAL_NAME = "data-room-proposal.json"
STATUS_REL = "shared/project-status.md"
EVIDENCE_REGISTER_REL = "shared/evidence-register.json"
SOURCE_REGISTER_REL = "shared/source-register.json"
CONDITIONS_REGISTER_REL = "shared/conditions-register.json"
ASSUMPTIONS_REGISTER_REL = "shared/assumptions-register.json"
PROFILE_REL = "shared/startup-profile.json"

TX10 = "tx-s12-s10"
TX11 = "tx-s12-s11"
TX12 = "tx-s12-001"

EXIT_OK = 0
EXIT_RED = 1
EXIT_USAGE = 2
EXIT_STATE = 3

# --------------------------------------------------------------------------
# Tassonomia dei codici: i TRENTA codici `data_room_*` del catalogo della
# Data Room, piu' `path_escape` PREESISTENTE e riusato verbatim.
# --------------------------------------------------------------------------

CODE_SECTION_MISSING = "data_room_section_missing"
CODE_MANIFEST_INVALID = "data_room_manifest_invalid"
CODE_DUPLICATE_ID = "data_room_duplicate_id"
CODE_ARTIFACT_TYPE = "data_room_artifact_type_invalid"
CODE_ORIGIN = "data_room_origin_ambiguous"
CODE_BROKEN_PATH = "data_room_broken_path"
CODE_PATH_ESCAPE = "path_escape"
CODE_CHECKSUM = "data_room_checksum_mismatch"
CODE_VERSION = "data_room_version_inconsistent"
CODE_OWNER = "data_room_owner_invalid"
CODE_CONFIDENTIALITY = "data_room_confidentiality_unsupported"
CODE_CLAIM_LINK = "data_room_claim_link_invalid"
CODE_SECTION_INVALID = "data_room_section_invalid"
CODE_VALIDATION_STATUS = "data_room_validation_status_invalid"
CODE_REQUIRED_MISSING = "data_room_required_missing"
CODE_QUALITY = "data_room_quality_unavailable"
CODE_VOLATILE = "data_room_volatile_in_identity"
CODE_NONDETERMINISTIC = "data_room_nondeterministic"
CODE_CLAIM_NAMESPACE = "data_room_claim_namespace_undeclared"
CODE_CLAIM_STATUS = "data_room_claim_status_invalid"
CODE_HIERARCHY = "data_room_source_hierarchy_ignored"
CODE_PROVENANCE = "data_room_provenance_missing"
CODE_GAP = "data_room_evidence_gap_suppressed"
CODE_STALE = "data_room_stale_evidence"
CODE_CONFLICT = "data_room_conflicting_evidence"
CODE_COMPLETENESS = "data_room_completeness_misrepresented"
CODE_ORPHAN = "data_room_orphan_evidence"
CODE_UNSUPPORTED = "data_room_unsupported_claim"
CODE_SECRET = "data_room_secret_leak"
CODE_SOURCE_MUTATED = "data_room_source_mutated"
CODE_DEBT = "data_room_debt_closed_without_proof"

CATALOG_CODES = frozenset((
    CODE_SECTION_MISSING, CODE_MANIFEST_INVALID, CODE_DUPLICATE_ID,
    CODE_ARTIFACT_TYPE, CODE_ORIGIN, CODE_BROKEN_PATH, CODE_CHECKSUM,
    CODE_VERSION, CODE_OWNER, CODE_CONFIDENTIALITY, CODE_CLAIM_LINK,
    CODE_SECTION_INVALID, CODE_VALIDATION_STATUS, CODE_REQUIRED_MISSING,
    CODE_QUALITY, CODE_VOLATILE, CODE_NONDETERMINISTIC, CODE_CLAIM_NAMESPACE,
    CODE_CLAIM_STATUS, CODE_HIERARCHY, CODE_PROVENANCE, CODE_GAP, CODE_STALE,
    CODE_CONFLICT, CODE_COMPLETENESS, CODE_ORPHAN, CODE_UNSUPPORTED,
    CODE_SECRET, CODE_SOURCE_MUTATED, CODE_DEBT))
PREEXISTING_CODES = frozenset((CODE_PATH_ESCAPE,))
FRAMEWORK_CODES = frozenset(("corrupted_state",))

#: Le UNDICI sezioni, elenco CHIUSO e ordine FISSO. Sono una partizione
#: LOGICA del manifest: NESSUNA cartella fisica e' creata.
SECTIONS = (
    "01_corporate-and-governance",
    "02_market-and-customer-evidence",
    "03_product-technology-operations-ip",
    "04_commercial-and-go-to-market",
    "05_team-and-organization",
    "06_roadmap-and-milestones",
    "07_financial-model-and-plan",
    "08_funding-request-and-use-of-proceeds",
    "09_risks-assumptions-and-open-items",
    "10_source-evidence-and-provenance",
    "11_generated-artifact-metadata",
)

#: I tipi GENERATI che, uniti a `source-register.source_type`, formano l'enum
#: CHIUSO di `artifact_type` (`DR-C-04`).
GENERATED_TYPES = ("stage_canonical_output", "stage_handoff",
                   "derived_chapter", "derived_workbook",
                   "derived_funding_request", "shared_register")

EVIDENCE_CLASSES = ("verified_fact", "internal_evidence", "external_source",
                    "founder_assumption", "model_estimate",
                    "missing_information")
LINK_STATUSES = ("supporting", "contradicting", "partial", "missing")

#: Forma canonica degli id per gli spazi di nomi dei claim e dei documenti.
CLM_PATTERN = r"^CLM-(?:[0-9]{3}|[1-9][0-9]{3,})$"
DR_PATTERN = r"^DR-(?:[0-9]{3}|[1-9][0-9]{3,})$"

#: Ingressi DICHIARATI della staleness: nessun orologio e' letto.
AS_OF = "2026-09-25"
MAX_AGE_DAYS = 365

#: Testo NON ASCII di un claim (`DR-P-08`): deve superare egress e impact
#: anche nella riscrittura UTF-8 del Transaction Manager.
NON_ASCII_STATEMENT = ("Il pilota su 12 punti vendita ha ridotto di più del "
                       "30% le ore di pianificazione dei turni — dato già "
                       "verificato sul campione (≈ 4 ore/settimana, 900 €).")
NON_ASCII_MARKERS = ("più", "—", "≈", "€")

#: Una chiave privata PEM costruita a runtime: nessun segreto letterale vive
#: nel sorgente del test.
PEM_BLOCK = ("-----BEGIN " + "PRIVATE KEY-----\n"
             "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7\n"
             "-----END " + "PRIVATE KEY-----\n")
CREDENTIAL_URL = "postgres://" + "admin:s3cr3t" + "@db.example.org:5432/app"

XLSX = None
CHAPTER = None
TM = None
KIT = None
_CACHE = {}


class HarnessUsageError(Exception):
    """Errore d'uso dell'harness (exit 2)."""


class HarnessDefect(Exception):
    """Difetto di PREPARAZIONE (exit 3). Non e' evidenza RED."""


# --------------------------------------------------------------------------
# Preparazione
# --------------------------------------------------------------------------


def resolve_root(raw):
    if not raw:
        raise HarnessUsageError("--root obbligatorio")
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise HarnessUsageError(f"--root non e' una directory: {root}")
    for probe_rel in (SKILL_REL, TESTKIT_REL):
        if not (root / probe_rel).is_dir():
            raise HarnessUsageError(
                f"--root non sembra la radice del repository: {probe_rel} "
                f"assente sotto {root}")
    return root


def load_file_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_harness(root, name):
    path = root / TESTKIT_REL / f"{name}.py"
    if not path.is_file():
        raise HarnessDefect(f"harness di supporto assente: {path}")
    return load_file_module(path, name)


def build_context(root):
    ctx = XLSX.build_context(root)
    ctx["root"] = root
    ctx["config"] = json.loads(
        (root / ENFORCEMENT_REL).read_text(encoding="utf-8"))
    ctx["dr_validator"] = root / DR_VALIDATOR_REL
    ctx["fr_validator"] = root / FR_VALIDATOR_REL
    return ctx


def dr_module(ctx):
    """Il modulo DI PRODUZIONE della Data Room, importato in SOLA LETTURA per
    le sonde in-process (renderer dell'indice, regola dei path, costruttore).
    Assente prima dell'implementazione: `None`, mai un'eccezione."""
    path = ctx["dr_validator"]
    if not path.is_file():
        return None
    validators_dir = str(path.parent)
    if validators_dir not in sys.path:
        sys.path.insert(0, validators_dir)
    try:
        return load_file_module(path, "validate_data_room_under_test")
    except Exception as exc:  # superficie in costruzione: constatazione
        _CACHE["module_error"] = repr(exc)
        return None


def canonical_json(document):
    """La forma deterministica del costruttore: chiavi ordinate, indentazione
    2, `ensure_ascii`, newline finale."""
    return json.dumps(document, indent=2, ensure_ascii=True,
                      sort_keys=True) + "\n"


def tm_json(document):
    """La forma con cui il Transaction Manager RISCRIVE un canonico al commit
    (`dump_json_bytes`: `ensure_ascii=False`, ordine delle chiavi conservato)."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_of(path):
    return sha256_bytes(Path(path).read_bytes())


def project_hashes(project, exclude_prefixes=(STAGE12 + "/",)):
    """Impronta per-file del progetto FUORI dalla Data Room e fuori dalle aree
    transitorie (`shared/.tx/`, `.working/`) e dal log di audit."""
    out = {}
    base = Path(project)
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(base).as_posix()
        if rel.startswith("shared/.tx/") or "/.working/" in rel:
            continue
        if rel == "shared/audit-log.jsonl":
            continue
        if any(rel.startswith(prefix) for prefix in exclude_prefixes):
            continue
        out[rel] = sha256_of(path)
    return out


def read_json_or_none(path):
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def read_text_or_none(path):
    path = Path(path)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def identity_of(document, include_volatile=False):
    """Identita' DICHIARATA del manifest (`DR-C-16`), calcolata qui per
    SPECIFICA e non per imitazione del modulo di produzione: il payload e'
    `data_room` SENZA `identity` e `generated_at`, con ogni documento SENZA
    `last_verified_at` e `generated_at`; serializzazione compatta a chiavi
    ordinate, `ensure_ascii`; `sha256`. Con `include_volatile` e' la forma
    della mutazione `MUT-4-43`, che include i timestamp."""
    room = (document or {}).get("data_room") or {}
    payload = {}
    for key, value in room.items():
        if key == "identity":
            continue
        if key == "generated_at" and not include_volatile:
            continue
        if key == "documents":
            entries = []
            for entry in value or []:
                entries.append({
                    k: v for k, v in entry.items()
                    if include_volatile or k not in ("last_verified_at",
                                                     "generated_at")})
            value = entries
        payload[key] = value
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")
    return sha256_bytes(blob)


def reseal(document):
    room = document.get("data_room") or {}
    identity = room.get("identity")
    if isinstance(identity, dict):
        identity["payload_sha256"] = identity_of(document)
    return document


def testkit():
    import bpo_testkit
    return bpo_testkit


def transaction_manager(ctx):
    kit = testkit()
    return kit.load_module(ctx["root"], kit.TRANSACTION_REL,
                           "transaction_manager")


# --------------------------------------------------------------------------
# Invocazione della produzione
# --------------------------------------------------------------------------


MISSING_VALIDATOR = (
    f"{DR_VALIDATOR_REL} ASSENTE: il modulo della Data Room e' la SEDE della "
    "validazione egress/impact e del pubblicatore --build dell'indice "
    "derivato")


def run_python(ctx, script, args, env_extra=None, cwd=None):
    command = [sys.executable, str(script)] + [str(item) for item in args]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(command, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          cwd=str(cwd or ctx["root"]), env=env)
    return proc


def verdict_of(proc):
    report = None
    if proc.stdout.strip().startswith("{"):
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            report = None
    codes = []
    messages = {}
    checks = []
    if isinstance(report, dict):
        for entry in report.get("errors") or ():
            code = entry.get("code")
            if code:
                codes.append(code)
                messages.setdefault(code, []).append(
                    f"{entry.get('ref')} {entry.get('message')}")
        checks = list(report.get("checks") or ())
    return {"available": True, "exit_code": proc.returncode,
            "report": report, "codes": sorted(set(codes)),
            "messages": messages, "checks": checks,
            "stdout": proc.stdout, "stderr": proc.stderr}


def absent_verdict():
    return {"available": False, "exit_code": None, "report": None,
            "codes": [], "messages": {}, "checks": [], "stdout": "",
            "stderr": MISSING_VALIDATOR}


def run_dr(ctx, args, env_extra=None):
    if not ctx["dr_validator"].is_file():
        return absent_verdict()
    return verdict_of(run_python(ctx, ctx["dr_validator"], args, env_extra))


def run_build(ctx, project, tx=TX12, env_extra=None):
    return run_dr(ctx, ["--build", "--project", project, "--tx", tx],
                  env_extra=env_extra)


def run_egress(ctx, project, candidate, extra=()):
    return run_dr(ctx, ["--project", project, "--candidate", candidate,
                        "--stage", STAGE12, "--phase", "egress", *extra])


def run_impact_cli(ctx, project, extra=()):
    return run_dr(ctx, ["--project", project, "--stage", STAGE12,
                        "--phase", "impact", *extra])


def run_tm(ctx, *args):
    kit = testkit()
    return kit.run_tm_cli(ctx["root"], *args)


def tm_codes(stdout):
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    return sorted({item.get("code") for item in result.get("errors") or ()})


def front_matter(ctx, project):
    text = read_text_or_none(Path(project) / STATUS_REL) or ""
    kit = testkit()
    module = kit.load_module(ctx["root"], kit.VALIDATORS_REL, "_framework")
    return module.parse_front_matter(text)


def impact_on_view(ctx, project, replacements=None, tx="tx-s12-impact"):
    """La fase impact nella forma REALE del Transaction Manager: la
    validation view di `build_validation_view` — `shared/` piu' i soli
    `NN_*/structured-output.json` — e `run_impact_validators` sullo Stage 12,
    che invoca `--project <view> --stage 12_data-room --phase impact`."""
    tm = transaction_manager(ctx)
    config = json.loads((ctx["root"] / ENFORCEMENT_REL)
                        .read_text(encoding="utf-8"))
    rel, view = tm.build_validation_view(project, tx, replacements or {},
                                         config)
    try:
        results, invoked = tm.run_impact_validators(config, view, rel,
                                                    [STAGE12])
    finally:
        tm.cleanup_validation_view(project, rel)
    return results, invoked


# --------------------------------------------------------------------------
# Fixture: base REALISTICA dalle superfici di produzione, poi G-10...G-14
# --------------------------------------------------------------------------


STARTUP_PROFILE = {"startup_type": "saas", "development_stage": "pre_seed",
                   "primary_reader": "business_angel",
                   "funding_type": "equity"}

#: Uscite SINTETICHE degli stage 01-09, DICHIARATE tali: la Data Room le
#: INDICIZZA per path e checksum e non ne interpreta il contenuto.
SYNTHETIC_STAGES = (
    ("01_problem-and-need", "Problema: pianificazione manuale dei turni."),
    ("02_customer-segmentation", "Segmento beachhead: catene retail 5-50 PV."),
    ("03_value-proposition", "Proposta: turni conformi in meno di un'ora."),
    ("04_market-and-competition", "SOM bottom-up ricalcolabile."),
    ("05_business-model", "Abbonamento per punto vendita al mese."),
    ("06_go-to-market", "Vendita diretta alle catene, funnel esplicito."),
    ("07_operations-and-ip", "Processi core e fornitore cloud."),
    ("08_team-and-governance", "Due founder, un CTO da assumere."),
    ("09_roadmap-and-milestones", "Quattro milestone datate e costate."),
)


def base_project(ctx):
    """La base REALISTICA, UNA volta per esecuzione del modulo: Stage 10 dalla
    pipeline di produzione, Stage 11 dal costruttore di produzione e
    dall'`advance-stage` REALE del Transaction Manager, che porta il progetto
    a `current_stage = 12_data-room` e `12_data-room` in stato `not_started`."""
    if "base" in _CACHE:
        return _CACHE["base"]
    holder = Path(tempfile.mkdtemp(prefix="s12_dr_base_"))
    _CACHE["holder"] = holder
    case = XLSX.prepare(ctx, holder, name="s12-base", level="full", tx=TX10)
    for key, label in (("built", "costruttore canonico"),
                       ("rendered", "renderer del capitolo"),
                       ("export", "exporter del workbook")):
        if (case.get(key) or {}).get("exit_code") != 0:
            raise HarnessDefect(
                f"la pipeline di produzione dello Stage 10 non ha prodotto "
                f"l'artefatto ({label}): "
                f"{(case.get(key) or {}).get('stdout', '')[:300]}")
    project = Path(case["project"])
    (project / STAGE10 / CANONICAL_NAME).write_bytes(
        Path(case["canonical"]).read_bytes())
    (project / PROFILE_REL).write_text(
        json.dumps(STARTUP_PROFILE, indent=2, ensure_ascii=True),
        encoding="utf-8")
    built = run_python(ctx, ctx["fr_validator"],
                       ["--build", "--project", project, "--tx", TX11])
    if built.returncode != 0:
        raise HarnessDefect(
            "il costruttore di produzione dello Stage 11 non ha prodotto la "
            f"funding request: {built.stdout[:300]} {built.stderr[:300]}")
    kit = testkit()
    order = ctx["config"]["stage_order"]
    completed = sorted((stage for stage in order
                        if int(order[stage]) < int(order[STAGE11])),
                       key=lambda stage: int(order[stage]))
    (project / STATUS_REL).write_text(
        kit.project_status_text(project.name, STAGE11, "in_progress",
                                completed), encoding="utf-8")
    exit_code, out, err = run_tm(
        ctx, "advance-stage", "--project", project, "--stage", STAGE11,
        "--candidate", project / STAGE11 / ".working" / TX11,
        "--gate-result", "approved")
    if exit_code != 0:
        raise HarnessDefect(
            "l'advance-stage REALE dello Stage 11 e' fallito: "
            f"{out.strip()[:300]} {err.strip()[:300]}")
    for stage, summary in SYNTHETIC_STAGES:
        folder = project / stage
        folder.mkdir(exist_ok=True)
        (folder / CANONICAL_NAME).write_text(
            json.dumps({"stage": stage, "synthetic_fixture": True,
                        "summary": summary}, indent=2, ensure_ascii=False)
            + "\n", encoding="utf-8")
        (folder / HANDOFF_NAME).write_text(
            f"# Handoff — {stage}\n\n{summary}\n\nnext_action: stage "
            "successivo.\n", encoding="utf-8")
    front = front_matter(ctx, project)
    if front.get("current_stage") != STAGE12 or \
            STAGE11 not in (front.get("completed_stages") or []):
        raise HarnessDefect(
            f"la base non e' a current_stage {STAGE12}: {front}")
    _CACHE["base"] = project
    return project


def assumption_ids(project):
    register = read_json_or_none(Path(project) / ASSUMPTIONS_REGISTER_REL)
    ids = sorted(entry["id"] for entry in register or ()
                 if isinstance(entry, dict) and
                 re.match(r"^ASS-(?:[0-9]{3}|[1-9][0-9]{3,})$",
                          str(entry.get("id"))))
    if len(ids) < 4:
        raise HarnessDefect(
            f"la base porta meno di quattro assunzioni canoniche: {ids}")
    return ids


def evidence_entry(ref, statement, classification, status, date, affected):
    entry = {"id": ref, "statement": statement,
             "classification": classification, "status": status,
             "evidence_type": "document", "source": "fixture data room",
             "confidence": "medium", "relevance": "high",
             "affected_assumptions": list(affected),
             "affected_sections": [], "validation_action": "verificare"}
    if date is not None:
        entry["date"] = date
    return entry


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def g10_overlay(project, variant="g10"):
    """`G-10` — progetto con `evidence-register` POPOLATO e claim mappati,
    che e' anche `G-13` (file sorgente forniti dall'utente). Le varianti
    `G-11`, `G-12` e `G-14` sono DERIVATE da questa."""
    project = Path(project)
    a1, a2, a3, a4 = assumption_ids(project)[:4]
    evidence = [
        evidence_entry("EVD-001", NON_ASCII_STATEMENT, "internal_evidence",
                       "validated", "2026-06-28", [a1]),
        evidence_entry("EVD-002", "Il mercato europeo del workforce "
                       "management vale 2,1 miliardi di euro.",
                       "external_source", "validated", "2026-05-10", [a2]),
        evidence_entry("EVD-003", "Il founder stima un CAC di 900 euro per "
                       "catena.", "founder_assumption", "open", "2026-07-01",
                       [a3]),
        evidence_entry("EVD-004", "Nessun dato di churn disponibile.",
                       "missing_information", "needs_info", "2026-07-10",
                       [a4]),
        evidence_entry("EVD-005", "Studio 2023 sul costo dei turni non "
                       "conformi.", "external_source", "validated",
                       "2024-01-15", [a2]),
        evidence_entry("EVD-006", "Nota interna non collegata ad alcun "
                       "claim.", "internal_evidence", "open", "2026-08-01",
                       []),
    ]
    sources = [
        {"id": "SRC-001", "title": "Note delle interviste ai titolari",
         "source_type": "interview", "quality_rating": "medium",
         "url_or_path": "sources/interviste-titolari.md",
         "used_for": ["EVD-001", "EVD-003"]},
        {"id": "SRC-002", "title": "Report di settore sul workforce "
         "management", "source_type": "industry_report",
         "quality_rating": "high",
         "url_or_path": "sources/report-mercato-wfm.md",
         "used_for": ["EVD-002", "EVD-005"]},
        {"id": "SRC-003", "title": "Articolo di stampa", "source_type": "news",
         "quality_rating": "low", "url_or_path": "https://example.org/a",
         "used_for": []},
    ]
    conditions = [
        {"id": "COND-001", "stage": "03_value-proposition",
         "description": "Validare il prezzo su almeno quattro catene",
         "severity": "high", "owner": "founder",
         "validation_action": "interviste di prezzo",
         "due_before_stage": "10_financial-plan",
         "resolution_status": "open", "resolved_by": None,
         "evidence_ref": None},
        {"id": "COND-002", "stage": "04_market-and-competition",
         "description": "Fonte terza sul mercato", "severity": "medium",
         "owner": "orchestrator", "validation_action": "report di settore",
         "due_before_stage": "10_financial-plan",
         "resolution_status": "resolved", "resolved_by": "DEC-001",
         "evidence_ref": "EVD-002"},
    ]
    write_json(project / EVIDENCE_REGISTER_REL, evidence)
    write_json(project / SOURCE_REGISTER_REL, sources)
    write_json(project / CONDITIONS_REGISTER_REL, conditions)
    (project / "sources").mkdir(exist_ok=True)
    (project / "sources" / "interviste-titolari.md").write_text(
        "# Interviste ai titolari\r\n\r\nQuattro titolari di catena "
        "intervistati tra giugno e luglio.\r\n", encoding="utf-8",
        newline="")
    (project / "sources" / "report-mercato-wfm.md").write_text(
        "# Report di settore\n\nDimensione del mercato europeo.\n",
        encoding="utf-8")
    (project / "sources" / "loi-cliente-alfa.md").write_text(
        "# Lettera d'intenti — cliente Alfa\n\nImpegno non vincolante a un "
        "pilota su 5 punti vendita.\n", encoding="utf-8")
    claims = [
        {"key": "problem-hours", "statement": NON_ASCII_STATEMENT,
         "related_section": "01_problem-and-need",
         "provenance": {"section": "01_problem-and-need",
                        "paragraph_anchor": "problema-misurabile"},
         "assumption_refs": [a1],
         "evidence_links": [
             {"evidence_ref": "EVD-001",
              "document_path": "sources/interviste-titolari.md",
              "status": "supporting"}]},
        {"key": "market-size", "statement": "Il mercato indirizzabile "
         "supera i 2 miliardi di euro.",
         "related_section": "04_market-and-competition",
         "provenance": {"section": "04_market-and-competition",
                        "paragraph_anchor": None},
         "assumption_refs": [a2],
         "evidence_links": [
             {"evidence_ref": "EVD-002",
              "document_path": "sources/report-mercato-wfm.md",
              "status": "supporting"},
             {"evidence_ref": "EVD-005",
              "document_path": "sources/report-mercato-wfm.md",
              "status": "partial"}]},
        {"key": "cac", "statement": "Il CAC si stabilizza a 900 euro per "
         "catena.", "related_section": "06_go-to-market",
         "provenance": {"section": None, "paragraph_anchor": None},
         "assumption_refs": [a3],
         "evidence_links": [
             {"evidence_ref": "EVD-003",
              "document_path": "sources/interviste-titolari.md",
              "status": "supporting"}]},
        {"key": "churn", "statement": "Il churn annuo resta sotto il 10%.",
         "related_section": "10_financial-plan",
         "provenance": {"section": "10_financial-plan",
                        "paragraph_anchor": "churn"},
         "assumption_refs": [a4],
         "evidence_links": [
             {"evidence_ref": "EVD-004", "document_path": None,
              "status": "missing"}]},
    ]
    proposal = {
        "as_of": AS_OF, "max_age_days": MAX_AGE_DAYS,
        "generated_at": "2026-09-25T09:00:00Z",
        "sources": [
            {"path": "sources/interviste-titolari.md",
             "title": "Note delle interviste ai titolari",
             "artifact_type": "interview",
             "section_id": "02_market-and-customer-evidence",
             "related_section": "01_problem-and-need", "owner": "founder",
             "validation_status": "validated", "source_ref": "SRC-001",
             "evidence_refs": [], "last_verified_at": "2026-09-01"},
            {"path": "sources/loi-cliente-alfa.md",
             "title": "Lettera d'intenti del cliente Alfa",
             "artifact_type": "company",
             "section_id": "04_commercial-and-go-to-market",
             "related_section": "06_go-to-market", "owner": "founder",
             "validation_status": "open", "source_ref": None,
             "evidence_refs": [], "last_verified_at": None},
        ],
        "expected": [
            {"path": "sources/contratto-fornitore-cloud.pdf",
             "title": "Contratto quadro con il fornitore cloud",
             "artifact_type": "company",
             "section_id": "03_product-technology-operations-ip",
             "related_section": "07_operations-and-ip", "owner": "external",
             "validation_status": "needs_info"},
        ],
        "claims": claims,
    }
    if variant == "g12":
        evidence.append(evidence_entry(
            "EVD-007", "Un secondo pilota non mostra alcuna riduzione delle "
            "ore di pianificazione.", "external_source", "validated",
            "2026-09-01", [a1]))
        evidence.append(evidence_entry(
            "EVD-008", "Il mercato europeo del workforce management vale 2,1 "
            "miliardi di euro.", "external_source", "validated", "2026-05-12",
            [a2]))
        write_json(project / EVIDENCE_REGISTER_REL, evidence)
        claims[0]["evidence_links"].append(
            {"evidence_ref": "EVD-007", "document_path": None,
             "status": "contradicting"})
        claims[1]["evidence_links"].append(
            {"evidence_ref": "EVD-008", "document_path": None,
             "status": "supporting"})
    if variant == "g11":
        (project / "07_operations-and-ip" / CANONICAL_NAME).unlink()
    if variant == "g14":
        handoff = project / "05_business-model" / HANDOFF_NAME
        handoff.write_text(handoff.read_text(encoding="utf-8") + "\n"
                           + PEM_BLOCK, encoding="utf-8")
    candidate = project / STAGE12 / ".working" / TX12
    candidate.mkdir(parents=True, exist_ok=True)
    write_json(candidate / PROPOSAL_NAME, proposal)
    return {"project": project, "candidate": candidate, "proposal": proposal,
            "assumptions": (a1, a2, a3, a4)}


def fresh(ctx, base_dir, name, variant="g10"):
    """Copia PROFONDA della base con l'overlay della variante: ogni
    costruzione e ogni mutazione agiscono qui, mai sulla base."""
    target = Path(base_dir) / name
    shutil.copytree(base_project(ctx), target)
    return g10_overlay(target, variant)


def stage_proposal(case, tx):
    """La STESSA proposta dell'analista nel candidate di un'altra
    transazione: ogni `--build` legge la proposta del PROPRIO candidate."""
    candidate = Path(case["project"]) / STAGE12 / ".working" / tx
    candidate.mkdir(parents=True, exist_ok=True)
    write_json(candidate / PROPOSAL_NAME, case["proposal"])
    return candidate


def built(ctx, variant="g10"):
    """Una variante COSTRUITA dal `--build` di produzione, in cache: il
    progetto, il candidate, il manifest letto e il verdetto di egress."""
    key = f"built-{variant}"
    if key in _CACHE:
        return _CACHE[key]
    holder = Path(tempfile.mkdtemp(prefix=f"s12_dr_{variant}_",
                                   dir=_CACHE.get("holder")))
    case = fresh(ctx, holder, variant, variant)
    case["build"] = run_build(ctx, case["project"])
    case["document"] = read_json_or_none(case["candidate"] / CANONICAL_NAME)
    case["index"] = read_text_or_none(
        case["project"] / STAGE12 / INDEX_NAME)
    case["egress"] = run_egress(ctx, case["project"], case["candidate"]) \
        if case["document"] is not None else absent_verdict()
    _CACHE[key] = case
    return case


def published(ctx):
    """`G-10` PUBBLICATA dal Transaction Manager REALE: `advance-stage` dello
    Stage 12 con `--gate-result approved`, in cache."""
    if "published" in _CACHE:
        return _CACHE["published"]
    holder = Path(tempfile.mkdtemp(prefix="s12_dr_pub_",
                                   dir=_CACHE.get("holder")))
    case = fresh(ctx, holder, "published")
    case["build"] = run_build(ctx, case["project"])
    exit_code, out, err = run_tm(
        ctx, "advance-stage", "--project", case["project"], "--stage",
        STAGE12, "--candidate", case["candidate"], "--gate-result",
        "approved")
    case["advance"] = (exit_code, out, err)
    case["canonical"] = case["project"] / STAGE12 / CANONICAL_NAME
    _CACHE["published"] = case
    return case


def not_built(case, findings, observation):
    """`True` quando il manifest NON e' stato prodotto, con la propria
    constatazione ATTRIBUITA: nessun contratto e' GREEN per silenzio e
    nessuno e' RED per `ImportError`."""
    build = case.get("build") or {}
    if not build.get("available", True):
        findings.append(f"constatazione: {observation} — {MISSING_VALIDATOR}")
        return True
    if case.get("document") is None:
        findings.append(
            f"constatazione: {observation} — --build non ha prodotto il "
            f"manifest (exit {build.get('exit_code')}, codici "
            f"{build.get('codes')}): {(build.get('stderr') or '')[:200]}")
        return True
    return False


def room_of(document):
    return (document or {}).get("data_room") or {}


def documents_of(document):
    return [entry for entry in room_of(document).get("documents") or ()
            if isinstance(entry, dict)]


def claims_of(document):
    return [entry for entry in room_of(document).get("claims") or ()
            if isinstance(entry, dict)]


def document_by_path(document, path):
    for entry in documents_of(document):
        if entry.get("path") == path:
            return entry
    return None


def claim_by_statement(document, statement):
    for entry in claims_of(document):
        if entry.get("statement") == statement:
            return entry
    return None


# --------------------------------------------------------------------------
# Mutazioni: output di un COSTRUTTORE MUTANTE, applicato a una copia
# --------------------------------------------------------------------------


class Probe:
    """Contabilita' di un contratto: osservazioni valutate ed esecuzioni di
    mutazione, per la specificita' e per la guardia di non-vacuita'."""

    def __init__(self, contract_id):
        self.contract_id = contract_id
        self.findings = []
        self.runs = []
        self.evaluated = 0

    def check(self, condition, message):
        self.evaluated += 1
        if not condition:
            self.findings.append(message)
        return condition

    def record(self, mutation, label, verdict, expected):
        codes = verdict.get("codes") or []
        killed = verdict.get("exit_code") == EXIT_RED and expected in codes
        self.runs.append({"contract": self.contract_id, "mutation": mutation,
                          "label": label, "exit_code":
                          verdict.get("exit_code"), "codes": codes,
                          "expected": expected, "killed": killed})
        self.evaluated += 1
        if not verdict.get("available", True):
            self.findings.append(
                f"{mutation} ({label}): atteso exit 1 con {expected}; "
                "nessun validator della Data Room la respinge — "
                f"{MISSING_VALIDATOR}")
        elif not killed:
            self.findings.append(
                f"{mutation} ({label}): atteso exit 1 con {expected}; "
                f"osservato exit {verdict.get('exit_code')} codici {codes}: "
                f"{(verdict.get('stderr') or '')[:160]}")
        return killed


def mutant_egress(ctx, case, mutate, *, reseal_identity=True,
                  rerender=True, index_edit=None, files=None):
    """Applica `mutate(document, project)` a una COPIA del progetto costruito,
    risigilla l'identita' con la SPECIFICA (`identity_of`), rigenera l'indice
    con il renderer di PRODUZIONE — l'output coerente di un costruttore
    mutante — e invoca l'egress nella forma REALE del Transaction Manager."""
    module = dr_module(ctx)
    base_dir = Path(tempfile.mkdtemp(prefix="s12_dr_mut_",
                                     dir=_CACHE.get("holder")))
    project = base_dir / "project"
    shutil.copytree(case["project"], project)
    candidate = project / STAGE12 / ".working" / TX12
    document = copy.deepcopy(case["document"])
    mutate(document, project)
    if reseal_identity:
        reseal(document)
    (candidate / CANONICAL_NAME).write_text(canonical_json(document),
                                            encoding="utf-8")
    if rerender and module is not None and hasattr(module, "render_index"):
        text = module.render_index(document)
        if index_edit is not None:
            text = index_edit(text)
        (project / STAGE12 / INDEX_NAME).write_text(text, encoding="utf-8")
    if rerender and module is not None and hasattr(module, "render_handoff"):
        # Regressione DR-R-06: l'handoff canonico e' una superficie resa
        # dal manifest come l'indice; il costruttore mutante coerente lo
        # rende con il renderer di PRODUZIONE, cosi' ogni mutazione resta
        # attribuita al proprio difetto e non a un handoff stantio.
        (candidate / HANDOFF_NAME).write_text(module.render_handoff(document),
                                              encoding="utf-8")
    if files:
        for rel, data in files.items():
            (project / rel).write_bytes(data)
    return run_egress(ctx, project, candidate)


def expect_rejected(probe, ctx, case, mutation, label, expected, mutate,
                    **kwargs):
    if case.get("document") is None:
        probe.record(mutation, label, absent_verdict()
                     if not ctx["dr_validator"].is_file()
                     else {"exit_code": None, "codes": [],
                           "stderr": "nessun manifest di base"}, expected)
        return False
    verdict = mutant_egress(ctx, case, mutate, **kwargs)
    return probe.record(mutation, label, verdict, expected)


def positive_egress(probe, case, label):
    verdict = case.get("egress") or absent_verdict()
    probe.check(verdict.get("exit_code") == EXIT_OK,
                f"{label}: l'egress del manifest COSTRUITO deve passare "
                f"(exit 0), osservato exit {verdict.get('exit_code')} codici "
                f"{verdict.get('codes')}")


def schema_doc(ctx):
    return read_json_or_none(ctx["root"] / DR_SCHEMA_REL)


def resolve_ref(schema, node):
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            return {}
        target = schema
        for part in ref[2:].split("/"):
            target = (target or {}).get(part) if isinstance(target, dict) \
                else None
        node = target
    return node if isinstance(node, dict) else {}


def schema_at(schema, *keys):
    """Il sotto-schema di `data_room.<keys...>`, seguendo `$ref` e `items`."""
    node = resolve_ref(schema, (schema or {}).get("properties", {})
                       .get("data_room", {}))
    for key in keys:
        if key == "[]":
            node = resolve_ref(schema, node.get("items", {}))
        else:
            node = resolve_ref(schema, node.get("properties", {})
                               .get(key, {}))
    return node


def enum_of(schema_node):
    if "enum" in schema_node:
        return list(schema_node["enum"])
    if "const" in schema_node:
        return [schema_node["const"]]
    return None


def register_enum(ctx, rel, field):
    schema = read_json_or_none(ctx["root"] / rel) or {}
    return ((schema.get("items") or {}).get("properties") or {}) \
        .get(field, {}).get("enum")


# --------------------------------------------------------------------------
# Contratti
# --------------------------------------------------------------------------


def c01(ctx, base):
    """`DR-C-01` — undici sezioni, elenco CHIUSO, ordine FISSO; una
    sezione vuota e' `NOT_APPLICABLE` con `reason`, mai omessa. Sonda
    `DR-P-12`: ogni comando del workflow e' eseguito COME SCRITTO."""
    probe = Probe("DR-C-01")
    schema = schema_doc(ctx)
    sections = schema_at(schema, "sections")
    probe.check(sections.get("minItems") == 11 and
                sections.get("maxItems") == 11,
                "lo schema non chiude `data_room.sections` a esattamente "
                f"11 voci: {sections.get('minItems')}/{sections.get('maxItems')}")
    section_id = resolve_ref(schema, (schema or {}).get("$defs", {})
                             .get("section_id", {}))
    probe.check(section_id.get("enum") == list(SECTIONS),
                "lo schema non dichiara `$defs.section_id` come l'elenco "
                f"CHIUSO e ORDINATO delle undici sezioni: "
                f"{section_id.get('enum')}")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings,
                     "nessun manifest a undici sezioni per G-10"):
        positive_egress(probe, case, "G-10")
        listed = room_of(case["document"]).get("sections") or []
        probe.check([item.get("section_id") for item in listed]
                    == list(SECTIONS),
                    "le sezioni emesse non sono le undici nell'ordine fisso")
        empty = [item for item in listed if not item.get("document_ids")]
        probe.check(bool(empty) and all(
            item.get("status") == "NOT_APPLICABLE" and
            isinstance(item.get("reason"), str) and item.get("reason")
            for item in empty),
            "una sezione vuota non e' emessa NOT_APPLICABLE con reason: "
            f"{[(i.get('section_id'), i.get('status')) for i in empty]}")
        partition = sorted(ref for item in listed
                           for ref in item.get("document_ids") or [])
        probe.check(partition == sorted(
            entry.get("document_id") for entry in
            documents_of(case["document"])),
            "le undici sezioni non sono una partizione del manifest")
    expect_rejected(probe, ctx, case, "MUT-4-28", "sezione omessa",
                    CODE_SECTION_MISSING,
                    lambda doc, _p: room_of(doc)["sections"].pop(0))
    expect_rejected(probe, ctx, case, "MUT-4-28", "sezione vuota senza reason",
                    CODE_SECTION_MISSING, lambda doc, _p: [
                        item.update({"status": "NOT_APPLICABLE",
                                     "reason": None})
                        for item in room_of(doc)["sections"]
                        if not item.get("document_ids")])
    run_workflow_as_written(ctx, base, probe)
    return probe


WORKFLOW_PLACEHOLDERS = ("<skill_dir>", "<project>", "<tx>")


def workflow_commands(text):
    """I comandi dei blocchi ```bash del workflow, con le continuazioni
    `\\` unite e i commenti esclusi."""
    commands = []
    for block in re.findall(r"```bash\n(.*?)```", text, flags=re.S):
        current = ""
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.endswith("\\"):
                current += stripped[:-1] + " "
                continue
            commands.append((current + stripped).strip())
            current = ""
        if current.strip():
            commands.append(current.strip())
    return commands


def run_workflow_as_written(ctx, base, probe):
    text = read_text_or_none(ctx["root"] / DR_WORKFLOW_REL)
    if not probe.check(text is not None,
                       f"DR-P-12: {DR_WORKFLOW_REL} ASSENTE: nessun comando "
                       "documentato e' eseguibile come scritto"):
        return
    commands = workflow_commands(text)
    probe.check(len(commands) >= 3,
                f"DR-P-12: il workflow documenta {len(commands)} comandi "
                "eseguibili: attesi almeno costruzione, egress e advance")
    for command in commands:
        for token in re.findall(r"<[^<>\s]+>", command):
            probe.check(token in WORKFLOW_PLACEHOLDERS,
                        f"DR-P-12: segnaposto non dichiarato {token!r} in "
                        f"{command!r}")
        probe.check("validate_stage_gate" not in command and
                    "validate_referential_integrity" not in command,
                    "DR-P-12: il workflow invoca un validator degli stage "
                    f"1-9 sullo Stage 12: {command!r}")
    case = fresh(ctx, Path(base), "workflow")
    project = case["project"].as_posix()
    for position, command in enumerate(commands):
        concrete = command.replace(
            "<skill_dir>", (ctx["root"] / SKILL_REL).as_posix()).replace(
            "<project>", project).replace("<tx>", TX12)
        argv = shlex.split(concrete)
        if argv and argv[0] in ("python", "python3"):
            argv[0] = sys.executable
        # cwd FUORI dal repository: i comandi documentati non dipendono dalla
        # directory corrente, solo da <skill_dir> e <project>.
        proc = subprocess.run(argv, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              cwd=str(Path(base)),
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        probe.check(proc.returncode == 0,
                    f"DR-P-12: il comando {position + 1} del workflow NON "
                    f"e' eseguibile come scritto (exit {proc.returncode}): "
                    f"{command!r} — {(proc.stdout + proc.stderr)[:200]!r}")
        if proc.returncode != 0:
            return
    published_doc = read_json_or_none(case["project"] / STAGE12 /
                                      CANONICAL_NAME)
    probe.check(len(room_of(published_doc).get("sections") or []) == 11,
                "DR-P-12: il workflow eseguito come scritto non pubblica un "
                "canonico a undici sezioni")


def c02(ctx, base):
    """`DR-C-02` — manifest canonico CHIUSO a ogni livello."""
    probe = Probe("DR-C-02")
    schema = schema_doc(ctx)
    if probe.check(schema is not None,
                   f"{DR_SCHEMA_REL} ASSENTE: nessuna chiusura dichiarata"):
        open_nodes = []

        def walk(node, where):
            if isinstance(node, dict):
                if node.get("type") == "object" or "properties" in node:
                    if node.get("additionalProperties") is not False:
                        open_nodes.append(where)
                for key, value in node.items():
                    walk(value, f"{where}/{key}")
            elif isinstance(node, list):
                for position, value in enumerate(node):
                    walk(value, f"{where}[{position}]")
        walk(schema, "#")
        probe.check(not open_nodes,
                    f"oggetti NON chiusi nello schema: {open_nodes[:6]}")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessun manifest per G-10"):
        positive_egress(probe, case, "G-10")
    for label, mutate in (
            ("radice data_room", lambda d, _p: room_of(d).update(
                {"unexpected": True})),
            ("voce di documento", lambda d, _p: documents_of(d)[0].update(
                {"unexpected": True})),
            ("legame di claim", lambda d, _p: claims_of(d)[0][
                "evidence_links"][0].update({"unexpected": True})),
            ("identita'", lambda d, _p: room_of(d)["identity"].update(
                {"unexpected": True}))):
        expect_rejected(probe, ctx, case, "MUT-4-29", label,
                        CODE_MANIFEST_INVALID, mutate)
    return probe


def c03(ctx, base):
    """`DR-C-03` — `document_id` UNICO e nella forma canonica degli id:
    unicita' e canonicita' misurate SEPARATAMENTE."""
    probe = Probe("DR-C-03")
    schema = schema_doc(ctx)
    dr_id = resolve_ref(schema, (schema or {}).get("$defs", {})
                        .get("dr_id", {}))
    probe.check(dr_id.get("pattern") == DR_PATTERN,
                f"`$defs.dr_id` non dichiara {DR_PATTERN}: "
                f"{dr_id.get('pattern')}")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessun DR-* allocato per G-10"):
        ids = [entry.get("document_id") for entry in
               documents_of(case["document"])]
        probe.check(all(re.match(DR_PATTERN, str(ref)) for ref in ids) and
                    len(ids) == len(set(ids)),
                    f"id di documento non canonici o duplicati: {ids}")
    for label, value in (("alias DR-0021", "DR-0021"),
                         ("alias DR-21", "DR-21"),
                         ("forma libera DOC-001", "DOC-001")):
        expect_rejected(probe, ctx, case, "MUT-4-30", label, CODE_DUPLICATE_ID,
                        lambda d, _p, v=value: documents_of(d)[-1].update(
                            {"document_id": v}))
    expect_rejected(probe, ctx, case, "MUT-4-30", "unicita'",
                    CODE_DUPLICATE_ID,
                    lambda d, _p: documents_of(d)[-1].update(
                        {"document_id": documents_of(d)[-2]["document_id"]}))
    return probe


def c04(ctx, base):
    """`DR-C-04` — `artifact_type` in enum CHIUSO, derivato da
    `source-register.source_type` piu' i tipi generati."""
    probe = Probe("DR-C-04")
    expected = list(register_enum(ctx, SOURCE_SCHEMA_REL, "source_type")
                    or []) + list(GENERATED_TYPES)
    declared = enum_of(schema_at(schema_doc(ctx), "documents", "[]",
                                 "artifact_type"))
    probe.check(declared == expected,
                "l'enum di artifact_type non e' source_type + tipi generati: "
                f"{declared}")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessun manifest per G-10"):
        positive_egress(probe, case, "G-10")
    expect_rejected(probe, ctx, case, "MUT-4-31", "tipo fuori enum",
                    CODE_ARTIFACT_TYPE, lambda d, _p: documents_of(d)[0]
                    .update({"artifact_type": "slide_deck"}))

    def source_as_generated_type(document, _project):
        for entry in documents_of(document):
            if entry.get("origin") == "source":
                entry["artifact_type"] = "stage_canonical_output"
                return
    expect_rejected(probe, ctx, case, "MUT-4-31", "origine/tipo incoerenti",
                    CODE_ARTIFACT_TYPE, source_as_generated_type)
    return probe


def c05(ctx, base):
    """`DR-C-05` — `origin` in `source|generated`, mai implicito."""
    probe = Probe("DR-C-05")
    node = schema_at(schema_doc(ctx), "documents", "[]")
    probe.check("origin" in (node.get("required") or []) and
                enum_of(resolve_ref(schema_doc(ctx) or {},
                                    (node.get("properties") or {})
                                    .get("origin", {}))) ==
                ["source", "generated"],
                "`origin` non e' obbligatorio con enum [source, generated]")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessun manifest per G-10"):
        origins = {entry.get("origin") for entry in
                   documents_of(case["document"])}
        probe.check(origins == {"source", "generated"},
                    f"G-13: attese entrambe le origini, osservate {origins}")
    expect_rejected(probe, ctx, case, "MUT-4-32", "origin assente",
                    CODE_ORIGIN, lambda d, _p: documents_of(d)[0]
                    .pop("origin"))
    expect_rejected(probe, ctx, case, "MUT-4-32", "origin fuori enum",
                    CODE_ORIGIN, lambda d, _p: documents_of(d)[0]
                    .update({"origin": "unknown"}))
    return probe


PATH_CORPUS = ("sources/a.md", "shared/evidence-register.json",
               "../fuori.md", "a/../b.md", "./a.md", "/etc/passwd",
               "C:/Windows/x", "a\\b.md", "~/x.md", "a//b.md", "",
               "a/./b.md", "10_financial-plan/structured-output.json")


def c06(ctx, base):
    """`DR-C-06` — nessun path rotto: target ESISTENTE e path CONTENUTO,
    due condizioni con due codici distinti; `path_escape` riusa la regola di
    `safe_rel_path` e non e' coniato."""
    probe = Probe("DR-C-06")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessun path indicizzato"):
        positive_egress(probe, case, "G-13")
    module = dr_module(ctx)
    tm = transaction_manager(ctx)
    rule = getattr(module, "unsafe_path_reason", None) if module else None
    if probe.check(rule is not None,
                   "nessuna regola di contenimento dei path nel modulo della "
                   "Data Room (`unsafe_path_reason`): `path_escape` non e' "
                   "riusato da `safe_rel_path`"):
        for rel in PATH_CORPUS:
            try:
                tm.safe_rel_path(rel)
                tm_rejects = False
            except tm.TransactionError:
                tm_rejects = True
            probe.check((rule(rel) is not None) == tm_rejects,
                        f"la regola dei path diverge da safe_rel_path su "
                        f"{rel!r}: TM respinge={tm_rejects}")

    def retarget(value):
        def mutate(document, _project):
            for entry in documents_of(document):
                if entry.get("origin") == "source" and \
                        entry.get("availability") == "available":
                    entry["path"] = value
                    return
        return mutate
    expect_rejected(probe, ctx, case, "MUT-4-33", "(a) target inesistente",
                    CODE_BROKEN_PATH, retarget("sources/inesistente.md"))
    for label, value in (("(b) ../ fuori progetto", "../fuori.md"),
                         ("(b) assoluto", "/etc/passwd"),
                         ("(b) backslash", "sources\\interviste.md")):
        expect_rejected(probe, ctx, case, "MUT-4-33", label, CODE_PATH_ESCAPE,
                        retarget(value))
    return probe


def c07(ctx, base):
    """`DR-C-07` — `checksum` sha256 per ogni artefatto disponibile,
    RICALCOLATO; `null` SOLO per `expected`/`missing`."""
    probe = Probe("DR-C-07")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessun checksum emesso"):
        for entry in documents_of(case["document"]):
            target = case["project"] / str(entry.get("path"))
            if entry.get("availability") == "available":
                probe.check(target.is_file() and
                            entry.get("checksum") == sha256_of(target),
                            f"checksum non ricalcolabile per "
                            f"{entry.get('path')}")
            else:
                probe.check(entry.get("checksum") is None,
                            f"checksum non null per {entry.get('path')} "
                            f"({entry.get('availability')})")
    source = "sources/report-mercato-wfm.md"
    original = (case["project"] / source).read_bytes() \
        if (case["project"] / source).is_file() else b""
    expect_rejected(probe, ctx, case, "MUT-4-34", "contenuto alterato",
                    CODE_CHECKSUM, lambda d, _p: None,
                    files={source: original + b"\nriga aggiunta\n"})
    expect_rejected(probe, ctx, case, "MUT-4-34", "checksum null su available",
                    CODE_CHECKSUM, lambda d, _p: document_by_path(
                        d, source).update({"checksum": None}))
    return probe


def c08(ctx, base):
    """`DR-C-08` — `version` non vuota e coerente fra manifest e indice
    derivato. Sonda `DR-P-09`: in impact il confronto con l'indice, che la
    validation view non contiene, e' `NOT_APPLICABLE`, mai `FAIL`."""
    probe = Probe("DR-C-08")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessun indice derivato"):
        index = case.get("index") or ""
        for entry in documents_of(case["document"]):
            probe.check(bool(entry.get("version")) and
                        f"| {entry.get('document_id')} | "
                        f"{entry.get('version')} |" in index,
                        f"la versione di {entry.get('document_id')} non e' "
                        "resa nell'indice derivato")
        probe.check(room_of(case["document"]).get("identity", {})
                    .get("payload_sha256", "-") in index,
                    "l'indice derivato non porta l'identita' del manifest")

    def diverge(text):
        return re.sub(r"(\| DR-[0-9]+ \| )([^|]+)( \|)",
                      lambda m: m.group(1) + "v-divergente" + m.group(3),
                      text, count=1)
    expect_rejected(probe, ctx, case, "MUT-4-35", "versione divergente "
                    "nell'indice", CODE_VERSION, lambda d, _p: None,
                    index_edit=diverge)
    expect_rejected(probe, ctx, case, "MUT-4-35", "versione vuota",
                    CODE_VERSION, lambda d, _p: documents_of(d)[0].update(
                        {"version": ""}))
    pub = published(ctx)
    if probe.check(pub["advance"][0] == 0,
                   "DR-P-09: la G-10 non e' pubblicata dal TM REALE: "
                   f"{pub['advance'][1][:200]!r}"):
        results, _ = impact_on_view(ctx, pub["project"])
        mine = [item for item in results
                if item.get("validator") == "validate_data_room"]
        probe.check(bool(mine) and mine[0]["exit_code"] == 0,
                    "DR-P-09: la fase impact sulla view REALE non passa: "
                    f"{[(m['exit_code'], m.get('report', {}).get('errors')) for m in mine]}")
        checks = (mine[0].get("report") or {}).get("checks") or [] \
            if mine else []
        probe.check(any(item.get("status") == "NOT_APPLICABLE" and
                        "index" in str(item.get("check_id"))
                        for item in checks),
                    "DR-P-09: in impact il confronto con l'indice derivato "
                    "non e' dichiarato NOT_APPLICABLE")
    return probe


def c09(ctx, base):
    """`DR-C-09` — `owner` nell'enum RIUSATO di `conditions-register`."""
    probe = Probe("DR-C-09")
    expected = register_enum(ctx, CONDITIONS_SCHEMA_REL, "owner")
    declared = enum_of(schema_at(schema_doc(ctx), "documents", "[]",
                                 "owner"))
    probe.check(declared is not None and declared == expected,
                "l'enum di owner non e' quello di conditions-register "
                f"({expected}): {declared}")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessun owner emesso"):
        positive_egress(probe, case, "G-10")
    expect_rejected(probe, ctx, case, "MUT-4-36", "owner in prosa libera",
                    CODE_OWNER, lambda d, _p: documents_of(d)[0].update(
                        {"owner": "Mario Rossi (CFO)"}))
    return probe


def c10(ctx, base):
    """`DR-C-10` — riservatezza solo dove supportata: nessun portatore
    esiste, quindi la costante dichiarata `NOT_SUPPORTED`."""
    probe = Probe("DR-C-10")
    declared = enum_of(schema_at(schema_doc(ctx), "documents", "[]",
                                 "confidentiality"))
    probe.check(declared == ["NOT_SUPPORTED"],
                f"confidentiality non e' la costante NOT_SUPPORTED: {declared}")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessuna riservatezza emessa"):
        probe.check(all(entry.get("confidentiality") == "NOT_SUPPORTED"
                        for entry in documents_of(case["document"])),
                    "un documento dichiara una riservatezza inventata")
    expect_rejected(probe, ctx, case, "MUT-4-37", "livelli inventati",
                    CODE_CONFIDENTIALITY, lambda d, _p: documents_of(d)[0]
                    .update({"confidentiality": "confidential"}))
    return probe


def c11(ctx, base):
    """`DR-C-11` — ogni legame RISOLVE contro il registro dei claim e i
    registri condivisi: risoluzione, non presenza sintattica."""
    probe = Probe("DR-C-11")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessun legame emesso"):
        registry = {claim.get("claim_id") for claim in
                    claims_of(case["document"])}
        linked = [ref for entry in documents_of(case["document"])
                  for ref in entry.get("related_claims") or []]
        probe.check(bool(linked) and set(linked) <= registry,
                    f"related_claims vuoti o non risolti: {linked}")
    expect_rejected(probe, ctx, case, "MUT-4-38", "CLM-999 inesistente",
                    CODE_CLAIM_LINK, lambda d, _p: documents_of(d)[0].update(
                        {"related_claims": ["CLM-999"]}))
    expect_rejected(probe, ctx, case, "MUT-4-38", "EVD-999 inesistente",
                    CODE_CLAIM_LINK, lambda d, _p: claims_of(d)[0][
                        "evidence_links"][0].update(
                            {"evidence_ref": "EVD-999"}))
    expect_rejected(probe, ctx, case, "MUT-4-38", "DR-999 inesistente",
                    CODE_CLAIM_LINK, lambda d, _p: claims_of(d)[0][
                        "evidence_links"][0].update({"document_id": "DR-999"}))
    return probe


def c12(ctx, base):
    """`DR-C-12` — `related_section` nell'enum di `stage_order` letto da
    `enforcement-config.json`, MAI oltre `release_boundary`. Sonda
    `DR-P-07`: ciclo di vita REALE del Transaction Manager, con lo Stage 13
    DENTRO il confine: il candidate non conforme e' respinto dall'egress del
    validator reale."""
    probe = Probe("DR-C-12")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessuna related_section emessa"):
        config = ctx["config"]
        boundary = int(config["stage_order"].get(
            config.get("release_boundary"), -1))
        sections = [entry.get("related_section") for entry in
                    documents_of(case["document"])]
        probe.check(all(section in config["stage_order"] and
                        int(config["stage_order"][section]) <= boundary
                        for section in sections),
                    f"related_section fuori stage_order o oltre il confine: "
                    f"{sorted(set(sections))}")
    # Con il confine sull'ULTIMO stage di stage_order il sotto-caso «oltre il
    # confine» bersaglia un identificatore ASSENTE da stage_order (forma T2);
    # il numero delle mutazioni del contratto non cambia.
    for label, value in (("sezione inventata", "99_invented"),
                         ("oltre il confine", "14_after-terminal")):
        expect_rejected(probe, ctx, case, "MUT-4-39", label,
                        CODE_SECTION_INVALID,
                        lambda d, _p, v=value: documents_of(d)[0].update(
                            {"related_section": v}))
    lifecycle(ctx, base, probe)
    return probe


def lifecycle(ctx, base, probe):
    """`DR-P-07` sul Transaction Manager NON modificato."""
    case = fresh(ctx, Path(base), "lifecycle")
    project = case["project"]
    candidate = stage_proposal(case, "tx-apply")
    run_build(ctx, project, tx="tx-apply")
    exit_code, out, err = run_tm(ctx, "apply", "--project", project,
                                 "--stage", STAGE12, "--candidate",
                                 candidate)
    if not probe.check(exit_code == 0,
                       "DR-P-07: `apply` dello Stage 12 non riesce (exit "
                       f"{exit_code}, codici {tm_codes(out)}): "
                       f"{(out + err).strip()[:200]!r}"):
        return
    candidate = stage_proposal(case, "tx-advance")
    run_build(ctx, project, tx="tx-advance")
    exit_code, out, err = run_tm(
        ctx, "advance-stage", "--project", project, "--stage", STAGE12,
        "--candidate", candidate, "--gate-result", "approved")
    if not probe.check(exit_code == 0,
                       "DR-P-07: `advance-stage 12_data-room --gate-result "
                       f"approved` non riesce (exit {exit_code}, codici "
                       f"{tm_codes(out)}): {(out + err).strip()[:200]!r}"):
        return
    front = front_matter(ctx, project)
    probe.check(STAGE12 in (front.get("completed_stages") or []),
                f"DR-P-07: {STAGE12} non e' in completed_stages: {front}")
    probe.check(front.get("current_stage") == STAGE13,
                f"DR-P-07: current_stage non e' {STAGE13}: "
                f"{front.get('current_stage')}")
    probe.check(front.get("status") == "not_started",
                f"DR-P-07: status non e' not_started: {front.get('status')}")
    next_action = str(front.get("next_action"))
    # Lo Stage 13 e' DENTRO il confine, quindi il next_action dopo l'advance
    # dello Stage 12 lo avvia, senza messaggio di confine; il candidate non
    # conforme dello Stage 13 e' respinto dall'egress del validator REALE
    # (validation_failed, exit 1). `governance-status` non e' sondato qui:
    # lo stato attivo sullo Stage 13 e' legittimo (Passo 1 del workflow dello
    # Stage 13, contratto DG-C-19).
    probe.check(next_action == f"avviare {STAGE13}",
                f"DR-P-07: next_action dopo lo Stage 12 incoerente: "
                f"{next_action!r}")
    kit = testkit()
    before = kit.snapshot_canonical(project)
    for command in ("apply", "advance-stage"):
        # Il rifiuto dopo lo snapshot RIPULISCE il candidate attivo: ciascun
        # comando riceve il PROPRIO candidate non conforme.
        stage13 = kit.make_candidate(project, STAGE13,
                                     tx_id=f"tx-s13-{command}",
                                     structured={"document_generation": {}})
        exit_code, out, _ = run_tm(ctx, command, "--project", project,
                                   "--stage", STAGE13, "--candidate", stage13)
        probe.check(exit_code == 1 and "validation_failed" in tm_codes(out),
                    f"DR-P-07: {command} su {STAGE13} con un candidate non "
                    f"conforme non da' exit 1 validation_failed: exit "
                    f"{exit_code} {tm_codes(out)}")
    probe.check(kit.snapshot_canonical(project) == before,
                "DR-P-07: un'operazione fallita sullo Stage 13 ha MUTATO il "
                "progetto")


def c13(ctx, base):
    """`DR-C-13` — `validation_status` nell'enum RIUSATO dello `status`
    del registro delle evidenze."""
    probe = Probe("DR-C-13")
    expected = register_enum(ctx, EVIDENCE_SCHEMA_REL, "status")
    declared = enum_of(schema_at(schema_doc(ctx), "documents", "[]",
                                 "validation_status"))
    probe.check(declared is not None and declared == expected,
                f"validation_status non riusa l'enum {expected}: {declared}")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessun validation_status"):
        positive_egress(probe, case, "G-10")
    expect_rejected(probe, ctx, case, "MUT-4-40", "stato coniato",
                    CODE_VALIDATION_STATUS, lambda d, _p: documents_of(d)[0]
                    .update({"validation_status": "approved"}))
    return probe


def c14(ctx, base):
    """`DR-C-14` — tri-stato ESPLICITO `available|expected|missing`:
    l'assenza e' VISIBILE, mai assorbita. Sonde `DR-P-09`: file fuori dalla
    view `NOT_APPLICABLE` in impact, canonico assente dichiarato."""
    probe = Probe("DR-C-14")
    case = built(ctx, "g11")
    missing_rel = f"07_operations-and-ip/{CANONICAL_NAME}"
    if not not_built(case, probe.findings,
                     "nessun manifest per G-11 (artefatto obbligatorio "
                     "assente)"):
        positive_egress(probe, case, "G-11")
        entry = document_by_path(case["document"], missing_rel)
        probe.check(entry is not None and entry.get("availability") ==
                    "missing" and entry.get("checksum") is None,
                    f"G-11: {missing_rel} non e' dichiarato missing: {entry}")
        states = {item.get("availability") for item in
                  documents_of(case["document"])}
        probe.check(states == {"available", "expected", "missing"},
                    f"i tre stati non sono tutti rappresentati: {states}")
    expect_rejected(probe, ctx, case, "MUT-4-41", "assente dato available",
                    CODE_REQUIRED_MISSING,
                    lambda d, _p: document_by_path(d, missing_rel).update(
                        {"availability": "available", "checksum": "0" * 64}))
    expect_rejected(probe, ctx, case, "MUT-4-41", "obbligatorio omesso",
                    CODE_REQUIRED_MISSING, lambda d, _p: room_of(d).update(
                        {"documents": [item for item in documents_of(d)
                                       if item.get("path") != missing_rel]}))
    # DR-P-09 — canonico ASSENTE in impact.
    unbuilt = fresh(ctx, Path(base), "impact-absent")
    verdict = run_impact_cli(ctx, unbuilt["project"])
    probe.check(verdict.get("exit_code") == 0 and any(
        item.get("status") == "NOT_APPLICABLE" for item in verdict["checks"]),
        "DR-P-09: con lo Stage 12 NON completato e canonico assente, "
        "l'impact deve dichiarare NOT_APPLICABLE ed uscire 0: exit "
        f"{verdict.get('exit_code')} {verdict.get('codes')}")
    pub = published(ctx)
    if pub["advance"][0] == 0:
        results, _ = impact_on_view(ctx, pub["project"])
        mine = [item for item in results
                if item.get("validator") == "validate_data_room"]
        checks = (mine[0].get("report") or {}).get("checks") or [] \
            if mine else []
        probe.check(any(item.get("status") == "NOT_APPLICABLE" and
                        "view" in str(item.get("message", ""))
                        for item in checks),
                    "DR-P-09: in impact i file fuori dalla validation view "
                    "non sono dichiarati NOT_APPLICABLE con motivo")
        holder = Path(tempfile.mkdtemp(prefix="s12_dr_absent_",
                                       dir=_CACHE.get("holder")))
        broken = holder / "project"
        shutil.copytree(pub["project"], broken)
        (broken / STAGE12 / CANONICAL_NAME).unlink()
        verdict = run_impact_cli(ctx, broken)
        probe.check(verdict.get("exit_code") == EXIT_STATE,
                    "DR-P-09: con lo Stage 12 COMPLETATO e canonico assente "
                    "l'impact deve uscire 3 (stato corrotto), osservato "
                    f"{verdict.get('exit_code')}")
    else:
        probe.check(False, "DR-P-09: G-10 non pubblicata dal TM REALE")
    return probe


def c15(ctx, base):
    """`DR-C-15` — `evidence_quality` DERIVATA da
    `source-register.quality_rating`; `null` se la fonte non e' registrata.
    Alias `SRC-` respinti con codice attribuito."""
    probe = Probe("DR-C-15")
    case = built(ctx, "g11")
    if not not_built(case, probe.findings, "nessuna qualita' derivata"):
        for path, quality in (("sources/interviste-titolari.md", "medium"),
                              ("sources/report-mercato-wfm.md", "high"),
                              ("sources/loi-cliente-alfa.md", None)):
            entry = document_by_path(case["document"], path) or {}
            probe.check(entry.get("evidence_quality") == quality,
                        f"evidence_quality di {path}: attesa {quality}, "
                        f"osservata {entry.get('evidence_quality')}")
    loi = "sources/loi-cliente-alfa.md"
    report = "sources/report-mercato-wfm.md"
    expect_rejected(probe, ctx, case, "MUT-4-42", "qualita' inventata per "
                    "fonte non registrata", CODE_QUALITY,
                    lambda d, _p: document_by_path(d, loi).update(
                        {"evidence_quality": "high"}))
    expect_rejected(probe, ctx, case, "MUT-4-42", "qualita' divergente dal "
                    "registro", CODE_QUALITY,
                    lambda d, _p: document_by_path(d, report).update(
                        {"evidence_quality": "low"}))
    expect_rejected(probe, ctx, case, "MUT-4-42", "source_ref non registrata",
                    CODE_QUALITY, lambda d, _p: document_by_path(
                        d, loi).update({"source_ref": "SRC-999"}))
    return probe


def c16(ctx, base):
    """`DR-C-16` — `last_verified_at` e `generated_at` ESCLUSI per
    costruzione dal payload di identita'."""
    probe = Probe("DR-C-16")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessuna identita' dichiarata"):
        document = case["document"]
        declared = room_of(document).get("identity", {}).get("payload_sha256")
        probe.check(declared == identity_of(document),
                    "l'identita' dichiarata non e' l'impronta del payload di "
                    "identita' SPECIFICATO")
        shifted = copy.deepcopy(document)
        room_of(shifted)["generated_at"] = "2030-01-01T00:00:00Z"
        for entry in documents_of(shifted):
            entry["last_verified_at"] = "2030-01-01"
            entry["generated_at"] = "2030-01-01T00:00:00Z"
        probe.check(identity_of(shifted) == declared,
                    "l'identita' non e' invariante ai due campi temporali")

    def retime(document, _project):
        room_of(document)["generated_at"] = "2030-01-01T00:00:00Z"
        documents_of(document)[0]["last_verified_at"] = "2030-01-01"
    expect_not = case.get("document") is not None
    if expect_not:
        verdict = mutant_egress(ctx, case, retime)
        probe.check(verdict.get("exit_code") == EXIT_OK,
                    "cambiare i soli timestamp non deve cambiare l'identita' "
                    f"ne' respingere il manifest: exit "
                    f"{verdict.get('exit_code')} {verdict.get('codes')}")

    def timestamp_in_hash(document, _project):
        retime(document, _project)
        room_of(document)["identity"]["payload_sha256"] = identity_of(
            document, include_volatile=True)
    expect_rejected(probe, ctx, case, "MUT-4-43", "timestamp nell'hash",
                    CODE_VOLATILE, timestamp_in_hash, reseal_identity=False)
    return probe


CLOCK_CALLS = ("now", "today", "utcnow", "time", "time_ns", "perf_counter",
               "monotonic", "localtime", "gmtime")


def clock_reads(source):
    reads = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func,
                                                     ast.Attribute):
            if node.func.attr in CLOCK_CALLS:
                owner = node.func.value
                name = getattr(owner, "id", getattr(owner, "attr", ""))
                if name in ("datetime", "date", "time"):
                    reads.append(f"{name}.{node.func.attr}")
    return reads


def renumber(document, mapping):
    """Rinumera i `DR-*` in modo COERENTE in ogni sede del manifest: un
    manifest ancora valido, con id che attraversano la soglia delle quattro
    cifre."""
    def swap(ref):
        return mapping.get(ref, ref)
    for entry in documents_of(document):
        entry["document_id"] = swap(entry.get("document_id"))
        entry["derived_from"] = [swap(ref) for ref in
                                 entry.get("derived_from") or []]
    for section in room_of(document).get("sections") or []:
        section["document_ids"] = [swap(ref) for ref in
                                   section.get("document_ids") or []]
    for claim in claims_of(document):
        for link in claim.get("evidence_links") or []:
            if link.get("document_id"):
                link["document_id"] = swap(link["document_id"])
    for item in room_of(document).get("evidence_index") or []:
        item["linked_documents"] = [swap(ref) for ref in
                                    item.get("linked_documents") or []]
    return document


def dr_number(ref):
    match = re.match(r"^DR-([0-9]+)$", str(ref))
    return int(match.group(1)) if match else -1


def ordinal_sort(document, stage_order):
    room_of(document)["documents"] = sorted(
        documents_of(document),
        key=lambda e: (int(stage_order.get(e.get("related_section"), 99)),
                       dr_number(e.get("document_id"))))
    for section in room_of(document).get("sections") or []:
        order = [entry.get("document_id") for entry in documents_of(document)]
        section["document_ids"] = sorted(section.get("document_ids") or [],
                                         key=order.index)
    return document


def c17(ctx, base):
    """`DR-C-17` — ordinamento stabile `(related_section_ordinal,
    document_id)` a ordinali ESPLICITI, due esecuzioni => byte identici,
    nessun orologio. Sonda `DR-P-08`: il canonico NON ASCII pubblicato dal
    TM REALE (`ensure_ascii=False`) supera egress e impact."""
    probe = Probe("DR-C-17")
    source = read_text_or_none(ctx["dr_validator"])
    if probe.check(source is not None,
                   "DR-P-11: nessun modulo da ispezionare per letture "
                   "dell'orologio"):
        reads = clock_reads(source)
        probe.check(not reads, f"DR-P-11: letture dell'orologio: {reads}")
    outputs = []
    for position, seed in enumerate(("0", "4242")):
        case = fresh(ctx, Path(base), f"det-{position}")
        verdict = run_build(ctx, case["project"],
                            env_extra={"PYTHONHASHSEED": seed})
        files = [case["candidate"] / CANONICAL_NAME,
                 case["candidate"] / HANDOFF_NAME,
                 case["project"] / STAGE12 / INDEX_NAME]
        if not probe.check(verdict.get("exit_code") == 0 and
                           all(path.is_file() for path in files),
                           f"DR-P-11: la generazione {position + 1} non "
                           f"produce i tre artefatti (exit "
                           f"{verdict.get('exit_code')})"):
            break
        outputs.append([sha256_of(path) for path in files])
        texts = [path.read_text(encoding="utf-8") for path in files]
        probe.check(not any(str(case["project"]) in text or
                            case["project"].as_posix() in text
                            for text in texts),
                    "DR-P-11: un path assoluto trapela negli artefatti "
                    "generati")
    if len(outputs) == 2:
        probe.check(outputs[0] == outputs[1],
                    "DR-P-11: due generazioni sullo stesso ingresso NON sono "
                    f"byte-identiche: {outputs}")
    case = built(ctx, "g10")
    stage_order = ctx["config"]["stage_order"]

    def lexicographic(document, _project):
        groups = {}
        for entry in documents_of(document):
            groups.setdefault(entry.get("related_section"), []).append(entry)
        group = next(items for items in groups.values() if len(items) >= 2)
        mapping = {group[-2]["document_id"]: "DR-999",
                   group[-1]["document_id"]: "DR-1000"}
        renumber(document, mapping)
        ordinal_sort(document, stage_order)
        room_of(document)["documents"] = sorted(
            documents_of(document),
            key=lambda e: (str(e.get("related_section")),
                           str(e.get("document_id"))))
        order = [entry.get("document_id") for entry in documents_of(document)]
        for section in room_of(document).get("sections") or []:
            section["document_ids"] = sorted(section.get("document_ids") or [],
                                             key=order.index)
    if case.get("document") is not None:
        valid = copy.deepcopy(case["document"])
        groups = {}
        for entry in documents_of(valid):
            groups.setdefault(entry.get("related_section"), []).append(entry)
        group = next(items for items in groups.values() if len(items) >= 2)
        renumber(valid, {group[-2]["document_id"]: "DR-999",
                         group[-1]["document_id"]: "DR-1000"})
        ordinal_sort(valid, stage_order)
        verdict = mutant_egress(ctx, case, lambda d, _p: d.update(
            copy.deepcopy(valid)))
        probe.check(verdict.get("exit_code") == EXIT_OK,
                    "controllo positivo: il manifest RINUMERATO in ordine "
                    "ordinale (DR-999 < DR-1000) deve passare, osservato exit "
                    f"{verdict.get('exit_code')} {verdict.get('codes')}")
    expect_rejected(probe, ctx, case, "MUT-4-44", "ordinamento "
                    "lessicografico", CODE_NONDETERMINISTIC, lexicographic)
    expect_rejected(probe, ctx, case, "MUT-4-44", "entrate scambiate",
                    CODE_NONDETERMINISTIC, lambda d, _p: room_of(d).update(
                        {"documents": list(reversed(documents_of(d)))}))
    pub = published(ctx)
    probe.check(pub["advance"][0] == 0,
                "DR-P-08: il TM REALE non pubblica il canonico non ASCII: "
                f"{pub['advance'][1][:200]!r}")
    if pub["advance"][0] == 0:
        text = pub["canonical"].read_text(encoding="utf-8")
        probe.check(all(marker in text for marker in NON_ASCII_MARKERS),
                    "DR-P-08: il canonico pubblicato non porta il testo non "
                    "ASCII in chiaro (la riscrittura del TM non e' esercitata)")
        results, _ = impact_on_view(ctx, pub["project"])
        mine = [item for item in results
                if item.get("validator") == "validate_data_room"]
        probe.check(bool(mine) and mine[0]["exit_code"] == 0,
                    "DR-P-08: il canonico non ASCII pubblicato dal TM non "
                    "supera l'impact: "
                    f"{[(m['exit_code'], (m.get('report') or {}).get('errors')) for m in mine]}")
    return probe


def c18(ctx, base):
    """`DR-C-18` — spazio di nomi `CLM-*` INTRODOTTO e dichiarato dallo
    Stage 12: `$defs` tipizzato riusato per `$ref`, alias respinti."""
    probe = Probe("DR-C-18")
    schema = schema_doc(ctx) or {}
    clm = (schema.get("$defs") or {}).get("clm_id") or {}
    probe.check(clm.get("pattern") == CLM_PATTERN,
                f"`$defs.clm_id` non dichiara {CLM_PATTERN}: "
                f"{clm.get('pattern')}")
    claim_node = schema_at(schema, "claims", "[]")
    probe.check(((claim_node.get("properties") or {}).get("claim_id") or {})
                .get("$ref") == "#/$defs/clm_id",
                "claims[].claim_id non usa $ref a #/$defs/clm_id")
    related = schema_at(schema, "documents", "[]", "related_claims")
    probe.check((related.get("items") or {}).get("$ref") == "#/$defs/clm_id",
                "related_claims[] non usa $ref a #/$defs/clm_id")
    methodology = read_text_or_none(ctx["root"] / DR_METHODOLOGY_REL) or ""
    probe.check("Lo spazio di nomi **`CLM-*`** è introdotto dallo Stage 12"
                in methodology,
                "la metodologia non dichiara lo spazio di nomi CLM-* "
                "come proprio dello Stage 12")
    others = [path.name for path in (ctx["root"] / SCHEMAS_REL).glob(
        "*.schema.json") if path.name != "data-room.schema.json" and
        "CLM-" in path.read_text(encoding="utf-8")]
    probe.check(not others,
                f"CLM-* e' definito anche fuori dallo Stage 12: {others}")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessun claim registrato"):
        ids = [claim.get("claim_id") for claim in claims_of(case["document"])]
        probe.check(bool(ids) and all(re.match(CLM_PATTERN, str(ref))
                                      for ref in ids),
                    f"claim_id non canonici: {ids}")
    for label, value in (("id senza spazio di nomi", "claim-1"),
                         ("alias CLM-0001", "CLM-0001")):
        expect_rejected(probe, ctx, case, "MUT-4-45", label,
                        CODE_CLAIM_NAMESPACE,
                        lambda d, _p, v=value: claims_of(d)[0].update(
                            {"claim_id": v}))
    return probe


def c19(ctx, base):
    """`DR-C-19` — stato del legame in `supporting|contradicting|
    partial|missing`; `contradicting` VISIBILE, mai attenuato."""
    probe = Probe("DR-C-19")
    link = schema_at(schema_doc(ctx), "claims", "[]", "evidence_links", "[]",
                     "status")
    probe.check(enum_of(link) == list(LINK_STATUSES),
                f"l'enum dello stato del legame non e' {LINK_STATUSES}: "
                f"{enum_of(link)}")
    case = built(ctx, "g12")
    if not not_built(case, probe.findings, "nessun legame contraddittorio "
                     "per G-12"):
        positive_egress(probe, case, "G-12")
        statuses = {link.get("status") for claim in
                    claims_of(case["document"])
                    for link in claim.get("evidence_links") or []}
        probe.check(set(LINK_STATUSES) <= statuses,
                    f"G-12: i quattro stati non sono tutti rappresentati: "
                    f"{statuses}")

    def degrade(document, _project):
        for claim in claims_of(document):
            for item in claim.get("evidence_links") or []:
                if item.get("status") == "contradicting":
                    item["status"] = "partial"
                    return
    expect_rejected(probe, ctx, case, "MUT-4-46", "contradicting degradato a "
                    "partial", CODE_CLAIM_STATUS, degrade)
    expect_rejected(probe, ctx, case, "MUT-4-46", "stato coniato",
                    CODE_CLAIM_STATUS, lambda d, _p: claims_of(d)[0][
                        "evidence_links"][0].update({"status": "neutral"}))
    return probe


def c20(ctx, base):
    """`DR-C-20` — le SEI classi di evidenza esatte, confrontate
    sull'enum e sul registro, mai su sinonimi."""
    probe = Probe("DR-C-20")
    expected = register_enum(ctx, EVIDENCE_SCHEMA_REL, "classification")
    declared = enum_of(schema_at(schema_doc(ctx), "claims", "[]",
                                 "evidence_links", "[]", "evidence_class"))
    probe.check(declared == expected == list(EVIDENCE_CLASSES),
                f"evidence_class non e' l'enum delle sei classi: {declared}")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessuna classe applicata"):
        positive_egress(probe, case, "G-10")
    expect_rejected(probe, ctx, case, "MUT-4-47", "classe parafrasata",
                    CODE_HIERARCHY, lambda d, _p: claims_of(d)[0][
                        "evidence_links"][0].update(
                            {"evidence_class": "fatto verificato"}))

    def promote(document, _project):
        for claim in claims_of(document):
            for item in claim.get("evidence_links") or []:
                if item.get("evidence_class") == "founder_assumption":
                    item["evidence_class"] = "verified_fact"
                    return
    expect_rejected(probe, ctx, case, "MUT-4-47", "promozione silenziosa",
                    CODE_HIERARCHY, promote)
    return probe


def c21(ctx, base):
    """`DR-C-21` — provenienza di sezione e paragrafo dove disponibile,
    `null` ESPLICITO altrimenti: assente non e' non disponibile."""
    probe = Probe("DR-C-21")
    node = schema_at(schema_doc(ctx), "claims", "[]", "provenance")
    probe.check(sorted(node.get("required") or []) ==
                ["paragraph_anchor", "section"],
                "provenance non obbliga section e paragraph_anchor: "
                f"{node.get('required')}")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessuna provenienza emessa"):
        provenances = [claim.get("provenance") for claim in
                       claims_of(case["document"])]
        probe.check(all(isinstance(item, dict) and
                        {"section", "paragraph_anchor"} <= set(item)
                        for item in provenances) and
                    any(item.get("paragraph_anchor") is None
                        for item in provenances),
                    f"provenienze incomplete o senza null esplicito: "
                    f"{provenances}")
    expect_rejected(probe, ctx, case, "MUT-4-48", "paragrafo omesso senza "
                    "null", CODE_PROVENANCE, lambda d, _p: claims_of(d)[0][
                        "provenance"].pop("paragraph_anchor"))
    expect_rejected(probe, ctx, case, "MUT-4-48", "provenienza omessa",
                    CODE_PROVENANCE, lambda d, _p: claims_of(d)[0].pop(
                        "provenance"))
    return probe


def c22(ctx, base):
    """`DR-C-22` — lacune irrisolte ESPOSTE in `unresolved_evidence_gaps`:
    sul caso reale (evidence_refs vuoti) la lista NON e' vuota."""
    probe = Probe("DR-C-22")
    case = built(ctx, "g11")
    if not not_built(case, probe.findings, "nessuna lacuna esposta per G-11"):
        gaps = room_of(case["document"]).get("unresolved_evidence_gaps") or []
        kinds = {item.get("kind") for item in gaps}
        probe.check(len(gaps) > 0 and {"claim_unsupported",
                                       "assumption_without_evidence_refs",
                                       "missing_information"} <= kinds,
                    f"G-11: lacune non esposte: {sorted(kinds)}")
    expect_rejected(probe, ctx, case, "MUT-4-49", "lacuna soppressa",
                    CODE_GAP, lambda d, _p: room_of(d)[
                        "unresolved_evidence_gaps"].pop(0))
    return probe


def c23(ctx, base):
    """`DR-C-23` — evidenza stantia o non verificata RILEVATA e MARCATA,
    con criterio DICHIARATO, deterministico, da soli ingressi dichiarati."""
    probe = Probe("DR-C-23")
    policy = schema_at(schema_doc(ctx), "staleness_policy")
    probe.check(sorted(policy.get("required") or []) ==
                ["criterion", "max_age_days", "reference_date"],
                "lo schema non dichiara il criterio di staleness: "
                f"{policy.get('required')}")
    methodology = read_text_or_none(ctx["root"] / DR_METHODOLOGY_REL) or ""
    probe.check("max_age_days" in methodology and
                "reference_date" in methodology,
                "la metodologia non dichiara il criterio di staleness")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessuna staleness marcata"):
        index = {item.get("evidence_ref"): item for item in
                 room_of(case["document"]).get("evidence_index") or []}
        probe.check(index.get("EVD-005", {}).get("freshness") == "stale" and
                    index.get("EVD-002", {}).get("freshness") == "current",
                    "EVD-005 (2024-01-15) non e' stale o EVD-002 non current")
        probe.check(index.get("EVD-003", {}).get("verification") ==
                    "unverified",
                    "EVD-003 (status open) non e' marcata non verificata")
        probe.check("EVD-005" in (room_of(case["document"])
                                  .get("stale_evidence") or []),
                    "EVD-005 non compare in stale_evidence")
        earlier = fresh(ctx, Path(base), "staleness-2024")
        proposal_path = earlier["candidate"] / PROPOSAL_NAME
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        proposal["as_of"] = "2024-06-01"
        write_json(proposal_path, proposal)
        verdict = run_build(ctx, earlier["project"])
        rebuilt = read_json_or_none(earlier["candidate"] / CANONICAL_NAME)
        index = {item.get("evidence_ref"): item for item in
                 room_of(rebuilt).get("evidence_index") or []}
        probe.check(verdict.get("exit_code") == 0 and
                    index.get("EVD-005", {}).get("freshness") == "current",
                    "la staleness non e' funzione del SOLO reference_date "
                    "dichiarato")
        undeclared = fresh(ctx, Path(base), "staleness-undeclared")
        proposal_path = undeclared["candidate"] / PROPOSAL_NAME
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        proposal.pop("as_of")
        write_json(proposal_path, proposal)
        verdict = run_build(ctx, undeclared["project"])
        probe.check(verdict.get("exit_code") == 1 and
                    CODE_STALE in verdict.get("codes"),
                    "un criterio NON dichiarato (as_of assente) deve essere "
                    f"respinto con {CODE_STALE}: exit "
                    f"{verdict.get('exit_code')} {verdict.get('codes')}")

    def as_current(document, _project):
        for item in room_of(document).get("evidence_index") or []:
            if item.get("freshness") == "stale":
                item["freshness"] = "current"
        room_of(document)["stale_evidence"] = []
    expect_rejected(probe, ctx, case, "MUT-4-50", "obsoleta data per "
                    "corrente", CODE_STALE, as_current)

    def as_verified(document, _project):
        for item in room_of(document).get("evidence_index") or []:
            if item.get("verification") == "unverified":
                item["verification"] = "verified"
                return
    expect_rejected(probe, ctx, case, "MUT-4-50", "non verificata data per "
                    "verificata", CODE_STALE, as_verified)
    return probe


def c24(ctx, base):
    """`DR-C-24` — evidenze duplicate o contraddittorie => `INCOERENZA
    RILEVATA`, mai fusione, mai la piu' recente."""
    probe = Probe("DR-C-24")
    case = built(ctx, "g12")
    if not not_built(case, probe.findings, "nessun conflitto per G-12"):
        positive_egress(probe, case, "G-12")
        conflicts = room_of(case["document"]).get("conflicts") or []
        pairs = {(item.get("kind"), item.get("evidence_a"),
                  item.get("evidence_b")) for item in conflicts}
        probe.check(("contradiction", "EVD-001", "EVD-007") in pairs and
                    ("duplicate", "EVD-002", "EVD-008") in pairs,
                    f"G-12: conflitti non esposti: {sorted(pairs)}")
        handoff = read_text_or_none(case["candidate"] / HANDOFF_NAME) or ""
        probe.check("INCOERENZA RILEVATA" in handoff and
                    "INCOERENZA RILEVATA" in (case.get("index") or ""),
                    "il blocco INCOERENZA RILEVATA non e' reso nell'handoff "
                    "e nell'indice")

    def fuse(document, _project):
        for claim in claims_of(document):
            links = claim.get("evidence_links") or []
            if any(item.get("status") == "contradicting" for item in links):
                claim["evidence_links"] = [
                    dict(item, status="supporting") for item in links
                    if item.get("evidence_ref") == "EVD-007"]
                claim["support_status"] = "supported"
        room_of(document)["conflicts"] = [
            item for item in room_of(document).get("conflicts") or []
            if item.get("kind") != "contradiction"]
    expect_rejected(probe, ctx, case, "MUT-4-51", "fusione nella piu' "
                    "recente", CODE_CONFLICT, fuse)
    expect_rejected(probe, ctx, case, "MUT-4-51", "duplicato soppresso",
                    CODE_CONFLICT, lambda d, _p: room_of(d).update(
                        {"conflicts": [item for item in room_of(d).get(
                            "conflicts") or [] if item.get("kind") !=
                            "duplicate"]}))
    fused = fresh(ctx, Path(base), "fused-proposal", "g12")
    proposal_path = fused["candidate"] / PROPOSAL_NAME
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    proposal["claims"][0]["evidence_links"] = [
        link for link in proposal["claims"][0]["evidence_links"]
        if link["evidence_ref"] == "EVD-007"]
    write_json(proposal_path, proposal)
    verdict = run_build(ctx, fused["project"])
    probe.record("MUT-4-51", "costruttore: proposta fusa", verdict,
                 CODE_CONFLICT)
    return probe


def c25(ctx, base):
    """`DR-C-25` — le metriche di completezza non travisano la qualita':
    ogni percentuale e' accompagnata dal denominatore e dalla distribuzione
    per classe."""
    probe = Probe("DR-C-25")
    case = built(ctx, "g11")
    if not not_built(case, probe.findings, "nessuna metrica di completezza"):
        document = case["document"]
        completeness = room_of(document).get("completeness") or {}
        claims = claims_of(document)
        supported = sum(1 for claim in claims
                        if claim.get("support_status") == "supported")
        distribution = {name: 0 for name in EVIDENCE_CLASSES}
        for claim in claims:
            for link in claim.get("evidence_links") or []:
                distribution[link.get("evidence_class")] = distribution.get(
                    link.get("evidence_class"), 0) + 1
        percent = str((Decimal(supported) * 100 / Decimal(len(claims)))
                      .quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)) \
            if claims else None
        probe.check(completeness.get("claims_total") == len(claims) and
                    completeness.get("claims_supported") == supported and
                    completeness.get("coverage_percent") == percent and
                    completeness.get("class_distribution") == distribution,
                    f"completezza non ricalcolabile: {completeness} contro "
                    f"{len(claims)}/{supported}/{percent}/{distribution}")

    def full_coverage(document, _project):
        completeness = room_of(document)["completeness"]
        completeness["claims_supported"] = completeness["claims_total"]
        completeness["coverage_percent"] = "100.00"
        completeness["class_distribution"] = {
            name: (sum(completeness["class_distribution"].values())
                   if name == "verified_fact" else 0)
            for name in EVIDENCE_CLASSES}
    expect_rejected(probe, ctx, case, "MUT-4-52", "100% coperto",
                    CODE_COMPLETENESS, full_coverage)
    return probe


def c26(ctx, base):
    """`DR-C-26` — identificatori duplicati RESPINTI, con normalizzazione
    dei path prima del confronto; alias dei registri respinti."""
    probe = Probe("DR-C-26")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessun DR-* da confrontare"):
        positive_egress(probe, case, "G-10")
    expect_rejected(probe, ctx, case, "MUT-4-53", "stesso DR-* su due voci",
                    CODE_DUPLICATE_ID, lambda d, _p: documents_of(d)[1]
                    .update({"document_id": documents_of(d)[0][
                        "document_id"]}))

    def same_path(document, _project):
        entries = documents_of(document)
        clone_entry = copy.deepcopy(next(item for item in entries
                                         if item.get("origin") == "source"))
        clone_entry["document_id"] = "DR-900"
        clone_entry["path"] = clone_entry["path"].upper()
        clone_entry["evidence_refs"] = []
        clone_entry["related_claims"] = []
        entries.append(clone_entry)
        for section in room_of(document).get("sections") or []:
            if section.get("section_id") == clone_entry.get("section_id"):
                section["document_ids"] = list(section.get("document_ids")
                                               or []) + ["DR-900"]
        room_of(document)["documents"] = entries
        ordinal_sort(document, ctx["config"]["stage_order"])
    expect_rejected(probe, ctx, case, "MUT-4-53", "stesso path normalizzato",
                    CODE_DUPLICATE_ID, same_path)
    alias = fresh(ctx, Path(base), "register-alias")
    register = json.loads((alias["project"] / EVIDENCE_REGISTER_REL)
                          .read_text(encoding="utf-8"))
    register.append(evidence_entry("EVD-0021", "Alias non canonico.",
                                   "internal_evidence", "open", "2026-08-01",
                                   []))
    write_json(alias["project"] / EVIDENCE_REGISTER_REL, register)
    probe.record("MUT-4-53", "alias EVD-0021 nel registro (costruttore)",
                 run_build(ctx, alias["project"]), CODE_DUPLICATE_ID)
    return probe


def c27(ctx, base):
    """`DR-C-27` — evidenza orfana RILEVATA: scartare non e' rilevare."""
    probe = Probe("DR-C-27")
    case = built(ctx, "g11")
    if not not_built(case, probe.findings, "nessuna orfana rilevata"):
        index = {item.get("evidence_ref"): item for item in
                 room_of(case["document"]).get("evidence_index") or []}
        probe.check(index.get("EVD-006", {}).get("orphan") is True and
                    "EVD-006" in (room_of(case["document"])
                                  .get("orphan_evidence") or []),
                    "EVD-006, non collegata, non e' rilevata orfana")
        probe.check(len(index) == 6,
                    f"l'indice delle evidenze non copre il registro: "
                    f"{sorted(index)}")

    def discard(document, _project):
        room = room_of(document)
        room["evidence_index"] = [item for item in room.get(
            "evidence_index") or [] if item.get("evidence_ref") != "EVD-006"]
        room["orphan_evidence"] = []
    expect_rejected(probe, ctx, case, "MUT-4-54", "orfana scartata in "
                    "silenzio", CODE_ORPHAN, discard)
    expect_rejected(probe, ctx, case, "MUT-4-54", "orfana marcata collegata",
                    CODE_ORPHAN, lambda d, _p: [
                        item.update({"orphan": False}) for item in
                        room_of(d).get("evidence_index") or []
                        if item.get("evidence_ref") == "EVD-006"])
    return probe


def c28(ctx, base):
    """`DR-C-28` — claim materiale non supportato RILEVATO; OGNI claim
    registrato e' materiale, nessuna materialita' a runtime."""
    probe = Probe("DR-C-28")
    node = schema_at(schema_doc(ctx), "claims", "[]", "materiality")
    probe.check(enum_of(node) == ["material"],
                f"materiality non e' la costante material: {enum_of(node)}")
    case = built(ctx, "g11")
    if not not_built(case, probe.findings, "nessun claim valutato"):
        unsupported = room_of(case["document"]).get("unsupported_claims") or []
        statuses = {claim.get("claim_id"): claim.get("support_status")
                    for claim in claims_of(case["document"])}
        probe.check(len(unsupported) == 2 and all(
            statuses.get(ref) == "unsupported" for ref in unsupported),
            f"claim non supportati non rilevati: {unsupported} {statuses}")

    def claim_supported(document, _project):
        for claim in claims_of(document):
            if claim.get("support_status") == "unsupported":
                claim["support_status"] = "supported"
                claim["evidence_links"] = []
                room_of(document)["unsupported_claims"] = [
                    ref for ref in room_of(document)["unsupported_claims"]
                    if ref != claim.get("claim_id")]
                return
    expect_rejected(probe, ctx, case, "MUT-4-55", "supportato con evidenze "
                    "vuote", CODE_UNSUPPORTED, claim_supported)
    expect_rejected(probe, ctx, case, "MUT-4-55", "materialita' a runtime",
                    CODE_UNSUPPORTED, lambda d, _p: claims_of(d)[0].update(
                        {"materiality": "immaterial"}))
    return probe


def c29(ctx, base):
    """`DR-C-29` — nessuna fuga di segreti negli artefatti GENERATI; i
    file sorgente NON sono ispezionati (perimetro)."""
    probe = Probe("DR-C-29")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessuna scansione dei generati"):
        positive_egress(probe, case, "G-10")
    perimeter = fresh(ctx, Path(base), "secret-in-source")
    source = perimeter["project"] / "sources" / "loi-cliente-alfa.md"
    source.write_text(source.read_text(encoding="utf-8") + PEM_BLOCK,
                      encoding="utf-8")
    verdict = run_build(ctx, perimeter["project"])
    probe.check(verdict.get("exit_code") == 0,
                "perimetro: un segreto in un file SORGENTE non deve essere "
                f"ispezionato (exit {verdict.get('exit_code')} "
                f"{verdict.get('codes')})")
    leaked = fresh(ctx, Path(base), "secret-in-generated", "g14")
    probe.record("MUT-4-56", "costruttore: PEM in un riassunto generato",
                 run_build(ctx, leaked["project"]), CODE_SECRET)
    target = "05_business-model/" + HANDOFF_NAME

    def leak(document, project):
        path = Path(project) / target
        data = path.read_bytes() + PEM_BLOCK.encode("utf-8")
        path.write_bytes(data)
        entry = document_by_path(document, target)
        entry["checksum"] = sha256_bytes(data)
        entry["version"] = "sha256:" + entry["checksum"][:12]
    expect_rejected(probe, ctx, case, "MUT-4-56", "PEM in un riassunto "
                    "generato", CODE_SECRET, leak)
    expect_rejected(probe, ctx, case, "MUT-4-56", "credenziale nel canonico",
                    CODE_SECRET, lambda d, _p: claims_of(d)[0].update(
                        {"statement": f"Database: {CREDENTIAL_URL}"}))
    return probe


def c30(ctx, base):
    """`DR-C-30` — i file forniti dall'utente e gli artefatti degli stage
    00-11 restano BYTE-IDENTICI (`DR-P-10`); il pubblicatore e' atomico; il
    validator importa SOLO la libreria standard e `_framework`
    (`DR-P-13`)."""
    probe = Probe("DR-C-30")
    source = read_text_or_none(ctx["dr_validator"])
    if probe.check(source is not None,
                   "DR-P-13: nessun modulo di cui ispezionare gli import"):
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0]
                                for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        foreign = sorted(name for name in imported
                         if name not in sys.stdlib_module_names and
                         name != "_framework")
        probe.check(not foreign,
                    f"DR-P-13: import fuori dal confine ammesso: "
                    f"{foreign}")
    case = fresh(ctx, Path(base), "immutability")
    before = project_hashes(case["project"])
    verdict = run_build(ctx, case["project"])
    probe.check(verdict.get("exit_code") == 0,
                f"la generazione non riesce (exit {verdict.get('exit_code')})")
    probe.check(project_hashes(case["project"]) == before,
                "DR-P-10: una fonte o un artefatto degli stage 00-11 NON e' "
                "byte-identico dopo la generazione")
    written = sorted(path.relative_to(case["project"]).as_posix()
                     for path in (case["project"] / STAGE12).rglob("*")
                     if path.is_file())
    probe.check(f"{STAGE12}/{INDEX_NAME}" in written,
                f"la generazione non pubblica {STAGE12}/{INDEX_NAME}: "
                f"{written}")
    probe.check(all(rel.startswith(f"{STAGE12}/") for rel in written),
                f"scritture della generazione fuori da {STAGE12}/: {written}")
    module = dr_module(ctx)
    if not probe.check(module is not None and
                       hasattr(module, "render_index"),
                       "MUT-4-57: nessun costruttore in-process su cui "
                       "iniettare la normalizzazione di fine riga"):
        probe.record("MUT-4-57", "normalizzazione EOL su un sorgente",
                     absent_verdict(), CODE_SOURCE_MUTATED)
        return probe
    mutated = fresh(ctx, Path(base), "eol")
    target = mutated["project"] / "sources" / "interviste-titolari.md"
    original_render = module.render_index

    def normalizing_render(document):
        target.write_bytes(target.read_bytes().replace(b"\r\n", b"\n"))
        return original_render(document)
    module.render_index = normalizing_render
    stdout = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout):
            exit_code = module.main(["--build", "--project",
                                     str(mutated["project"]), "--tx", TX12])
    finally:
        module.render_index = original_render
    report = json.loads(stdout.getvalue() or "{}")
    probe.record("MUT-4-57", "normalizzazione EOL su un sorgente",
                 {"exit_code": exit_code, "codes": sorted({
                     item.get("code") for item in report.get("errors") or ()})},
                 CODE_SOURCE_MUTATED)
    probe.check(not (mutated["project"] / STAGE12 / INDEX_NAME).exists(),
                "MUT-4-57: il rifiuto ha comunque PUBBLICATO l'indice")
    atomic = fresh(ctx, Path(base), "atomic")
    targets = [atomic["candidate"] / CANONICAL_NAME,
               atomic["candidate"] / HANDOFF_NAME,
               atomic["project"] / STAGE12 / INDEX_NAME]
    for path in targets:
        path.write_text("stato precedente\n", encoding="utf-8")
    prior = {str(path): sha256_of(path) for path in targets}
    real_replace = os.replace
    calls = []

    def failing_replace(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise OSError("fallimento INIETTATO dopo il primo file pubblicato")
        return real_replace(src, dst)
    os.replace = failing_replace
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                module.main(["--build", "--project", str(atomic["project"]),
                             "--tx", TX12])
            except OSError:
                pass
    finally:
        os.replace = real_replace
    probe.check({str(path): sha256_of(path) for path in targets} == prior,
                "pubblicazione NON atomica: dopo un fallimento iniettato lo "
                "stato precedente non e' ripristinato byte per byte")
    leftovers = [path.name for path in (atomic["project"] / STAGE12)
                 .rglob("*.part")]
    probe.check(not leftovers, f"temporanei orfani: {leftovers}")
    return probe


def c31(ctx, base):
    """`DR-C-31` — riassunto generato DISTINTO dall'evidenza originale,
    con `derived_from` che nomina il `DR-*` dell'originale."""
    probe = Probe("DR-C-31")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessun derived_from emesso"):
        document = case["document"]
        by_path = {entry.get("path"): entry for entry in
                   documents_of(document)}
        for stage in ("05_business-model", STAGE11):
            summary = by_path.get(f"{stage}/{HANDOFF_NAME}") or {}
            original = by_path.get(f"{stage}/{CANONICAL_NAME}") or {}
            probe.check(summary.get("origin") == "generated" and
                        summary.get("derived_from") ==
                        [original.get("document_id")],
                        f"{stage}/{HANDOFF_NAME}: derived_from non nomina il "
                        f"DR-* dell'originale: {summary.get('derived_from')}")
        request = by_path.get(f"{STAGE11}/funding-request.md") or {}
        probe.check(request.get("derived_from") ==
                    [by_path.get(f"{STAGE11}/{CANONICAL_NAME}", {})
                     .get("document_id")],
                    "funding-request.md non deriva dal canonico dello Stage 11")
        probe.check(all(entry.get("derived_from") == [] for entry in
                        documents_of(document)
                        if entry.get("origin") == "source"),
                    "una fonte originale porta un derived_from")
    handoff = f"05_business-model/{HANDOFF_NAME}"
    expect_rejected(probe, ctx, case, "MUT-4-58", "riassunto marcato "
                    "origin: source", CODE_ORIGIN, lambda d, _p: document_by_path(
                        d, handoff).update({"origin": "source",
                                            "derived_from": []}))
    expect_rejected(probe, ctx, case, "MUT-4-58", "derived_from rimosso",
                    CODE_ORIGIN, lambda d, _p: document_by_path(
                        d, handoff).update({"derived_from": []}))
    return probe


def c32(ctx, base):
    """`DR-C-32` — il debito differito e' ESPOSTO, mai chiuso
    dall'esistenza della data room: le voci aperte (`open_items`) sono
    verificate contro il registro delle condizioni, e una voce CHIUSA porta
    la prova che la chiude."""
    probe = Probe("DR-C-32")
    case = built(ctx, "g10")
    if not not_built(case, probe.findings, "nessun debito esposto"):
        items = {item.get("item_ref"): item for item in
                 room_of(case["document"]).get("open_items") or []}
        probe.check(items.get("COND-001", {}).get("status") == "APERTO" and
                    items.get("COND-001", {}).get("proof_ref") is None,
                    f"COND-001 aperta non esposta APERTO: {items}")
        probe.check(items.get("COND-002", {}).get("status") == "CHIUSO" and
                    items.get("COND-002", {}).get("proof_ref") == "DEC-001",
                    f"COND-002 risolta non chiusa CON prova DEC-001: {items}")
    expect_rejected(probe, ctx, case, "MUT-4-59", "debito chiuso perche' "
                    "indicizzato", CODE_DEBT, lambda d, _p: [
                        item.update({"status": "CHIUSO"}) for item in
                        room_of(d).get("open_items") or []
                        if item.get("item_ref") == "COND-001"])
    expect_rejected(probe, ctx, case, "MUT-4-59", "debito omesso", CODE_DEBT,
                    lambda d, _p: room_of(d).update({"open_items": [
                        item for item in room_of(d).get("open_items") or []
                        if item.get("item_ref") != "COND-001"]}))
    expect_rejected(probe, ctx, case, "MUT-4-59", "prova non corrispondente",
                    CODE_DEBT, lambda d, _p: [
                        item.update({"proof_ref": "DEC-999"}) for item in
                        room_of(d).get("open_items") or []
                        if item.get("item_ref") == "COND-002"])
    return probe


# --------------------------------------------------------------------------
# Registro dei contratti
# --------------------------------------------------------------------------


def entry(cid, name, fn, fixture, code, mutation, observation):
    return {"id": cid, "name": name, "fn": fn, "fixture": fixture,
            "expected_code": code, "mutation": mutation,
            "observation": observation}


CONTRACTS = [
    entry("DR-C-01", "T-DR-SECTIONS", c01, "G-10", CODE_SECTION_MISSING,
          "MUT-4-28", "nessuna struttura di undici sezioni esiste"),
    entry("DR-C-02", "T-DR-MANIFEST-CLOSED", c02, "G-10",
          CODE_MANIFEST_INVALID, "MUT-4-29", "nessuno schema di manifest"),
    entry("DR-C-03", "T-DR-DOCUMENT-ID", c03, "G-10", CODE_DUPLICATE_ID,
          "MUT-4-30", "nessuno spazio di nomi DR-*"),
    entry("DR-C-04", "T-DR-ARTIFACT-TYPE", c04, "G-10",
          CODE_ARTIFACT_TYPE, "MUT-4-31", "nessun enum di tipo"),
    entry("DR-C-05", "T-DR-ORIGIN", c05, "G-13", CODE_ORIGIN, "MUT-4-32",
          "origin non esiste"),
    entry("DR-C-06", "T-DR-PATHS", c06, "G-13", CODE_BROKEN_PATH,
          "MUT-4-33", "ne' risoluzione ne' contenimento sono controllati"),
    entry("DR-C-07", "T-DR-CHECKSUM", c07, "G-13", CODE_CHECKSUM,
          "MUT-4-34", "nessun checksum"),
    entry("DR-C-08", "T-DR-VERSION", c08, "G-10", CODE_VERSION,
          "MUT-4-35", "nessun campo versione"),
    entry("DR-C-09", "T-DR-OWNER", c09, "G-10", CODE_OWNER, "MUT-4-36",
          "nessun campo owner"),
    entry("DR-C-10", "T-DR-CONFIDENTIALITY", c10, "G-10",
          CODE_CONFIDENTIALITY, "MUT-4-37", "nessun campo di riservatezza"),
    entry("DR-C-11", "T-DR-CLAIM-LINKS", c11, "G-10", CODE_CLAIM_LINK,
          "MUT-4-38", "nessun related_claims[]"),
    entry("DR-C-12", "T-DR-RELATED-SECTION", c12, "G-10",
          CODE_SECTION_INVALID, "MUT-4-39", "nessun enum di sezione"),
    entry("DR-C-13", "T-DR-VALIDATION-STATUS", c13, "G-10",
          CODE_VALIDATION_STATUS, "MUT-4-40", "nessun validation_status"),
    entry("DR-C-14", "T-DR-AVAILABILITY", c14, "G-11",
          CODE_REQUIRED_MISSING, "MUT-4-41",
          "nessun tri-stato di disponibilita'"),
    entry("DR-C-15", "T-DR-EVIDENCE-QUALITY", c15, "G-11", CODE_QUALITY,
          "MUT-4-42", "nessuna derivazione da quality_rating"),
    entry("DR-C-16", "T-DR-IDENTITY", c16, "G-10", CODE_VOLATILE,
          "MUT-4-43", "nessun payload di identita'"),
    entry("DR-C-17", "T-DR-DETERMINISM", c17, "G-10",
          CODE_NONDETERMINISTIC, "MUT-4-44", "nessun ordinamento definito"),
    entry("DR-C-18", "T-DR-CLAIM-NAMESPACE", c18, "G-10",
          CODE_CLAIM_NAMESPACE, "MUT-4-45",
          "nessuna identita' di claim esiste nel repository"),
    entry("DR-C-19", "T-DR-LINK-STATUS", c19, "G-12", CODE_CLAIM_STATUS,
          "MUT-4-46", "nessun enum di stato del legame"),
    entry("DR-C-20", "T-DR-SOURCE-HIERARCHY", c20, "G-10",
          CODE_HIERARCHY, "MUT-4-47", "nessuna gerarchia applicata"),
    entry("DR-C-21", "T-DR-PROVENANCE", c21, "G-10", CODE_PROVENANCE,
          "MUT-4-48", "nessun campo di provenienza"),
    entry("DR-C-22", "T-DR-EVIDENCE-GAPS", c22, "G-11", CODE_GAP,
          "MUT-4-49", "nessun unresolved_evidence_gaps[]"),
    entry("DR-C-23", "T-DR-STALENESS", c23, "G-10", CODE_STALE,
          "MUT-4-50", "nessun criterio di staleness"),
    entry("DR-C-24", "T-DR-CONFLICTS", c24, "G-12", CODE_CONFLICT,
          "MUT-4-51", "nessuna rilevazione di conflitto"),
    entry("DR-C-25", "T-DR-COMPLETENESS", c25, "G-11",
          CODE_COMPLETENESS, "MUT-4-52", "nessuna metrica di completezza"),
    entry("DR-C-26", "T-DR-DUPLICATES", c26, "G-10", CODE_DUPLICATE_ID,
          "MUT-4-53", "nessun controllo di unicita'"),
    entry("DR-C-27", "T-DR-ORPHAN-EVIDENCE", c27, "G-11", CODE_ORPHAN,
          "MUT-4-54", "nessuna rilevazione di orfane"),
    entry("DR-C-28", "T-DR-UNSUPPORTED-CLAIM", c28, "G-11",
          CODE_UNSUPPORTED, "MUT-4-55", "nessuna nozione di claim materiale"),
    entry("DR-C-29", "T-DR-SECRET-LEAK", c29, "G-14", CODE_SECRET,
          "MUT-4-56", "nessuna scansione di segreti"),
    entry("DR-C-30", "T-DR-SOURCE-IMMUTABLE", c30, "G-13",
          CODE_SOURCE_MUTATED, "MUT-4-57", "nessuna verifica di immutabilita'"),
    entry("DR-C-31", "T-DR-DERIVED-FROM", c31, "G-13", CODE_ORIGIN,
          "MUT-4-58", "nessun derived_from"),
    entry("DR-C-32", "T-DR-DEBT-EXPOSED", c32, "G-10", CODE_DEBT,
          "MUT-4-59", "nessun elenco di debiti"),
]

CONTRACT_IDS = tuple(item["id"] for item in CONTRACTS)


# --------------------------------------------------------------------------
# SONDE DI REGRESSIONE `DR-R-01`...`-15`
# --------------------------------------------------------------------------
#
# Ogni regressione HIGH e MEDIUM della Data Room ha qui una SONDA propria,
# attribuita al proprio id.
#
# CONTABILITA' CAUSALE (verificata da `DR-R-14`). Ogni sonda porta:
#   - CONTROLLI: forme NON avversarie che anche un'implementazione priva
#     della protezione tratta correttamente (per esempio il solo record
#     CHIUSO senza duplicato). Falliscono SOLO per un guasto GENERICO —
#     validator assente, `ImportError`, base non costruita — e la sonda e'
#     allora NON-DISCRIMINANTE, mai un RED;
#   - ATTACCHI: le riproduzioni del difetto. Un RED e' CAUSALE solo se ogni
#     controllo vale e almeno un attacco non e' respinto come atteso.
# I 32 contratti qui sopra restano INVARIATI: queste sonde si aggiungono,
# non li sostituiscono.

#: Etichette neutre della suite (non stampate nel sommario).
REVIEW_COMMIT = "data-room"
REJECTED_CANDIDATE = "regressioni"

#: La chiave AWS DI ESEMPIO della documentazione del provider, costruita a
#: runtime: nessun segreto letterale vive nel sorgente del test.
AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
PEM_HEADER = "-----BEGIN " + "PRIVATE KEY-----"
TX_LINK = "tx-ir-link"
HANDOFF_LABEL = f"{STAGE12}/{HANDOFF_NAME}"
INDEX_LABEL = f"{STAGE12}/{INDEX_NAME}"
WORKBOOK_REL = f"{STAGE10}/financial-model.xlsx"
GAP_ORDER = ("claim_unsupported", "missing_link",
             "assumption_without_evidence_refs", "missing_information")

#: Segreti in un REGISTRO CONDIVISO che vede SOLO la scansione DECODIFICATA
#: (`file_text` -> `semantic_text`): nel testo GREZZO del JSON la sequenza di
#: escape (`\n`, `\t`, `\u00ab`) si fonde con il segreto e `\b` non trova il
#: confine (`DR-R-15`). Voce:
#: (etichetta, registro, campo del primo record, testo, `ensure_ascii`).
REGISTER_ESCAPED_SECRETS = (
    ("a capo nella descrizione di COND-001 (forma UTF-8 del TM)",
     CONDITIONS_REGISTER_REL, "description",
     f"Validare il prezzo:\n{AWS_KEY}", False),
    ("tab nel rationale della prima assunzione (forma UTF-8 del TM)",
     ASSUMPTIONS_REGISTER_REL, "rationale",
     f"Benchmark di settore.\t{AWS_KEY}", False),
    ("« nella descrizione di COND-001 in un registro ensure_ascii (\\u00ab)",
     CONDITIONS_REGISTER_REL, "description",
     f"Validare «{AWS_KEY}» con il fornitore", True),
)
#: Il CONTROLLO: lo stesso segreto dopo uno spazio ASCII, che anche il testo
#: grezzo rileva (respinto al `--build` anche senza scansione decodificata).
REGISTER_PLAIN_SECRET = (
    "spazio ASCII nella descrizione di COND-001", CONDITIONS_REGISTER_REL,
    "description", f"Validare il prezzo {AWS_KEY} con il fornitore", False)
#: Il registro delle decisioni che `update-assumption` e `resolve-condition`
#: creano DOPO la pubblicazione: PRESENTE nella view di impact e NON
#: indicizzato dal manifest, quindi scandito dal SECONDO ciclo di
#: `check_secrets`, che condivide `file_text` con il primo.
DECISIONS_REGISTER_REL = "shared/decisions-register.json"
DECISION_RECORD = {"id": "DEC-002", "decision": "Adottare il fornitore cloud "
                   "europeo", "rationale": "Costi e conformita'."}
UNINDEXED_NEWLINE_SECRET = f"Chiave di rotazione:\n{AWS_KEY}"


class FindingProbe:
    """Contabilita' CAUSALE di una sonda di regressione `DR-R-*` (vedi
    sopra)."""

    def __init__(self, finding_id):
        self.finding_id = finding_id
        self.controls = []
        self.attacks = []
        self.declared = []
        self.error = None

    def control(self, label, ok, detail=""):
        self.controls.append((label, bool(ok), detail))
        return bool(ok)

    def attack(self, label, ok, detail=""):
        self.attacks.append((label, bool(ok), detail))
        return bool(ok)

    def declare(self, text):
        """Un sotto-caso NON APPLICABILE su questa piattaforma o volume,
        dichiarato e mai contato come attacco respinto."""
        self.declared.append(text)

    def discriminant(self):
        """Falso appena un controllo fallisce: gli attacchi non sono piu'
        attribuibili e la sonda si ferma (e' NON-DISCRIMINANTE)."""
        return all(ok for _, ok, _ in self.controls)

    def state(self):
        if any(not ok for _, ok, _ in self.controls):
            return "NON-DISCRIMINANTE"
        if not self.controls or not self.attacks:
            return "VACUO"
        if any(not ok for _, ok, _ in self.attacks):
            return "RED-CAUSALE"
        return "GREEN"


def ref_number(ref):
    match = re.search(r"-([0-9]+)$", str(ref or ""))
    return int(match.group(1)) if match else -1


def error_refs(verdict, code):
    report = verdict.get("report") or {}
    return [str(item.get("ref")) for item in report.get("errors") or ()
            if item.get("code") == code]


def rejected_with(verdict, *codes, ref=None):
    ok = verdict.get("exit_code") == EXIT_RED and all(
        code in (verdict.get("codes") or []) for code in codes)
    if ok and ref is not None:
        ok = ref in error_refs(verdict, codes[0])
    return ok


def observed(verdict):
    return (f"osservato exit {verdict.get('exit_code')} codici "
            f"{verdict.get('codes')}")


def expect(record, label, verdict, *codes, ref=None):
    """`codes` vuoto: atteso exit 0. Altrimenti exit 1 con TUTTI i codici e,
    con `ref`, il primo codice attribuito a quel riferimento."""
    if not codes:
        return record(label, verdict.get("exit_code") == EXIT_OK,
                      f"atteso exit 0; {observed(verdict)}")
    wanted = ", ".join(codes) + (f" su {ref}" if ref else "")
    return record(label, rejected_with(verdict, *codes, ref=ref),
                  f"atteso exit 1 con {wanted}; {observed(verdict)}")


def production(ctx):
    """Il modulo di PRODUZIONE usato per RISIGILLARE e RENDERE un canonico
    esterno: identita', indice e handoff con le funzioni di
    produzione, cosi' l'unica incoerenza e' quella dell'attacco."""
    key = f"ir-production-{ctx['dr_validator']}"
    if key not in _CACHE:
        _CACHE[key] = dr_module(ctx)
    return _CACHE[key]


def tm_form(document):
    """La riscrittura UTF-8 del Transaction Manager di un canonico a chiavi
    ordinate (`ensure_ascii=False`)."""
    return json.dumps(document, indent=2, ensure_ascii=False,
                      sort_keys=True) + "\n"


def tm_bytes(data):
    """`dump_json_bytes` del Transaction Manager, per i registri."""
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8")


def external(ctx, case, mutate=None, *, form="builder", pre=None,
             handoff_edit=None, index_edit=None, files=None):
    """Canonico ESTERNO: copia del progetto costruito,
    `mutate(document, project)`, identita' risigillata e superfici rese con
    la produzione, serializzazione del costruttore o del TM. Un
    `handoff_edit` che restituisce `None` CANCELLA l'handoff."""
    module = production(ctx)
    holder = Path(tempfile.mkdtemp(prefix="s12_reg_", dir=_CACHE.get("holder")))
    project = holder / "p"
    shutil.copytree(case["project"], project)
    candidate = project / STAGE12 / ".working" / TX12
    if pre is not None:
        pre(project)
    document = copy.deepcopy(case["document"])
    if mutate is not None:
        mutate(document, project)
    identity = room_of(document).get("identity")
    if module is not None and isinstance(identity, dict):
        identity["payload_sha256"] = module.identity_of(document)
    raw = canonical_json(document) if form == "builder" else tm_form(document)
    (candidate / CANONICAL_NAME).write_text(raw, encoding="utf-8",
                                            newline="\n")
    handoff = module.render_handoff(document) if module is not None else ""
    if handoff_edit is not None:
        handoff = handoff_edit(handoff)
    if handoff is None:
        (candidate / HANDOFF_NAME).unlink(missing_ok=True)
    else:
        (candidate / HANDOFF_NAME).write_text(handoff, encoding="utf-8",
                                              newline="\n")
    index = module.render_index(document) if module is not None else ""
    if index_edit is not None:
        index = index_edit(index)
    (project / STAGE12 / INDEX_NAME).write_text(index, encoding="utf-8",
                                                newline="\n")
    for rel, data in (files or {}).items():
        (project / rel).write_bytes(data)
    return {"project": project, "candidate": candidate, "document": document}


def external_egress(ctx, case, mutate=None, **kwargs):
    prepared = external(ctx, case, mutate, **kwargs)
    return run_egress(ctx, prepared["project"], prepared["candidate"])


def tm_outcome(ctx, prepared):
    exit_code, out, err = run_tm(
        ctx, "advance-stage", "--project", prepared["project"], "--stage",
        STAGE12, "--candidate", prepared["candidate"], "--gate-result",
        "approved")
    front = front_matter(ctx, prepared["project"])
    return {"exit_code": exit_code, "codes": tm_codes(out),
            "committed": (prepared["project"] / STAGE12 /
                          CANONICAL_NAME).is_file(),
            "completed": STAGE12 in (front.get("completed_stages") or [])}


def tm_control(ctx, finding, case, variant):
    """Il TM REALE applica il canonico esterno NON alterato: un suo rifiuto
    in un attacco e' quindi attribuibile all'attacco, non al percorso."""
    key = f"ir-tm-control-{variant}-{ctx['dr_validator']}"
    if key not in _CACHE:
        _CACHE[key] = tm_outcome(ctx, external(ctx, case))
    outcome = _CACHE[key]
    finding.control(
        f"controllo: il TM reale applica il canonico esterno NON alterato "
        f"({variant})", outcome["exit_code"] == 0 and outcome["committed"]
        and outcome["completed"],
        f"exit {outcome['exit_code']} codici {outcome['codes']}")


def tm_refuses(ctx, finding, case, label, mutate=None, **kwargs):
    outcome = tm_outcome(ctx, external(ctx, case, mutate, **kwargs))
    finding.attack(
        f"TM reale: {label}", outcome["exit_code"] != 0 and not
        outcome["committed"] and not outcome["completed"],
        f"atteso nessun commit ({STAGE12} non completato); osservato exit "
        f"{outcome['exit_code']} codici {outcome['codes']} canonico "
        f"pubblicato={outcome['committed']}")


def proposal_case(ctx, base, name, edit=None, *, variant="g10",
                  registers=None, pre=None):
    """Una variante FRESCA con la proposta dell'analista modificata da
    `edit(proposal)` e i registri da `registers[rel](entries)`."""
    case = fresh(ctx, Path(base), name, variant)
    if pre is not None:
        pre(case["project"])
    for rel, change in (registers or {}).items():
        path = case["project"] / rel
        entries = json.loads(path.read_text(encoding="utf-8"))
        change(entries)
        write_json(path, entries)
    proposal = copy.deepcopy(case["proposal"])
    if edit is not None:
        edit(proposal)
    write_json(case["candidate"] / PROPOSAL_NAME, proposal)
    case["proposal"] = proposal
    return case


def view_verdict(ctx, project, replacements=None):
    """La fase impact nella forma REALE del TM (`impact_on_view`), come
    verdetto."""
    results, _ = impact_on_view(ctx, project, replacements)
    mine = [item for item in results
            if item.get("validator") == "validate_data_room"]
    if not mine:
        return {"exit_code": None, "codes": [], "report": None}
    report = mine[0].get("report") or {}
    return {"exit_code": mine[0].get("exit_code"), "report": report,
            "codes": sorted({item.get("code") for item in
                             report.get("errors") or ()})}


def register_bytes(project, rel, field, text, ensure_ascii=False):
    """Il registro `rel` di `project` con `field` del PRIMO record uguale a
    `text`, nella forma UTF-8 del TM (`dump_json_bytes`) o `ensure_ascii`."""
    entries = json.loads((Path(project) / rel).read_text(encoding="utf-8"))
    entries[0][field] = text
    return (json.dumps(entries, indent=2, ensure_ascii=ensure_ascii)
            + "\n").encode("utf-8")


def register_secret_case(ctx, base, name, variant):
    """Una G-10 FRESCA il cui registro condiviso porta il segreto di
    `variant` (`REGISTER_ESCAPED_SECRETS`, `REGISTER_PLAIN_SECRET`)."""
    _label, rel, field, text, ensure_ascii = variant
    case = fresh(ctx, Path(base), name)
    (case["project"] / rel).write_bytes(register_bytes(
        case["project"], rel, field, text, ensure_ascii))
    return case


def make_link(link, target):
    """Una junction NTFS (nessun privilegio) o, fuori da Windows, un
    symlink di directory."""
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(str(target), str(link), target_is_directory=True)


def drop_link(link):
    """Rimuove il SOLO collegamento, mai il bersaglio."""
    try:
        if os.name == "nt":
            os.rmdir(link)
        else:
            os.unlink(link)
    except OSError:
        pass


def tree_hashes(root):
    """`sha256` di ogni file regolare sotto `root`, SENZA attraversare
    symlink o junction."""
    out = {}
    root = Path(root)
    stack = [root]
    while stack:
        current = stack.pop()
        for item in sorted(current.iterdir()):
            if item.is_symlink() or item.is_junction():
                continue
            if item.is_dir():
                stack.append(item)
            elif item.is_file():
                out[item.relative_to(root).as_posix()] = sha256_of(item)
    return out


def is_link(path):
    path = Path(path)
    return path.is_symlink() or path.is_junction()


def publish_swap(ctx, base, module, tag):
    """TOCTOU DETERMINISTICO sulla ri-verifica di `publish` (`DR-R-15`).
    `publish` del modulo e' avvolto
    in-process: al suo INGRESSO — dopo il pre-controllo, la lettura della
    proposta, la validazione e l'impronta del progetto, immediatamente prima
    della prima scrittura — il candidate `.working/<tx>` e' spostato e
    sostituito da una junction verso `11_funding-request/`. Nessuna
    concorrenza: lo scambio avviene sempre nello stesso punto del flusso. La
    junction e' rimossa e il candidate ripristinato in ogni caso. Atteso:
    `path_escape` e Stage 11 byte-identico."""
    case = fresh(ctx, Path(base), f"pin-swap-{tag}")
    candidate = case["candidate"]
    moved = candidate.with_name(f"{candidate.name}-spostato")
    stage11 = case["project"] / STAGE11
    before = tree_hashes(stage11)
    original = module.publish
    planted = []

    def swap_then_publish(*args, **kwargs):
        if not planted:
            candidate.rename(moved)
            make_link(candidate, stage11)
            planted.append(is_link(candidate))
        return original(*args, **kwargs)

    module.publish = swap_then_publish
    try:
        verdict = inprocess(module, ["--build", "--project", case["project"],
                                     "--tx", TX12])
    finally:
        module.publish = original
        if is_link(candidate):
            drop_link(candidate)
        elif moved.is_dir() and candidate.is_dir() and \
                not any(candidate.iterdir()):
            # `CreateJunction` interrotta dopo la creazione della cartella.
            candidate.rmdir()
        if moved.is_dir() and not os.path.lexists(candidate):
            moved.rename(candidate)
    if is_link(candidate) or not candidate.is_dir():
        raise HarnessDefect(f"junction della sonda non rimossa: {candidate}")
    after = tree_hashes(stage11)
    written = sorted(rel for rel in set(before) | set(after)
                     if before.get(rel) != after.get(rel))
    swapped = planted == [True]
    ok = swapped and rejected_with(verdict, CODE_PATH_ESCAPE) and not written
    return ok, (f"junction piantata all'ingresso di publish={swapped}; "
                f"{observed(verdict)}; scritti nello Stage 11 {written[:4]}")


def proposal_outside(ctx, base, module, tag):
    """Contenimento in LETTURA del candidate: `.working/<tx>` e' una junction
    verso una cartella FUORI dal progetto con una proposta ILLEGGIBILE. Il
    pre-controllo dei bersagli la respinge `path_escape` PRIMA di leggerla;
    `data_room_manifest_invalid` proverebbe che l'ingresso fuori area e'
    stato letto."""
    case = fresh(ctx, Path(base), f"pin-proposal-{tag}")
    outside = Path(base) / f"pin-proposal-{tag}-fuori"
    outside.mkdir()
    (outside / PROPOSAL_NAME).write_text("{ proposta fuori area, mai letta",
                                         encoding="utf-8")
    link = case["project"] / STAGE12 / ".working" / TX_LINK
    make_link(link, outside)
    try:
        verdict = inprocess(module, ["--build", "--project", case["project"],
                                     "--tx", TX_LINK])
    finally:
        drop_link(link)
    if is_link(link):
        raise HarnessDefect(f"junction della sonda non rimossa: {link}")
    return (rejected_with(verdict, CODE_PATH_ESCAPE) and
            CODE_MANIFEST_INVALID not in verdict.get("codes", []),
            observed(verdict))


def short_component(path):
    """Il nome 8.3 dell'ULTIMO componente di `path`, se il volume lo
    genera; `None` altrimenti (sotto-caso dichiarato non applicabile)."""
    if os.name != "nt":
        return None
    import ctypes
    buffer = ctypes.create_unicode_buffer(1024)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, 1024):
        return None
    name = Path(buffer.value).name
    return name if name.casefold() != Path(path).name.casefold() else None


def extra_source(path, title, **fields):
    """Una voce `sources[]` della proposta, conforme a `$defs.proposal`."""
    entry = {"path": path, "title": title, "artifact_type": "other",
             "section_id": "10_source-evidence-and-provenance",
             "related_section": "00_idea-discovery", "owner": "founder",
             "validation_status": "open", "source_ref": None,
             "evidence_refs": [], "last_verified_at": None}
    entry.update(fields)
    return entry


def resync_related_claims(document):
    """`related_claims` di ogni documento ricalcolati dai legami, come fa il
    costruttore: un canonico esterno resta coerente dopo un attacco."""
    for entry in documents_of(document):
        entry["related_claims"] = sorted({
            claim.get("claim_id") for claim in claims_of(document)
            for link in claim.get("evidence_links") or []
            if link.get("document_id") == entry.get("document_id")},
            key=ref_number)


def sort_gaps(gaps):
    gaps.sort(key=lambda item: (
        GAP_ORDER.index(item["kind"]) if item.get("kind") in GAP_ORDER
        else 9, ref_number(item.get("ref"))))


# -- DR-R-01 · HIGH -------------------------------------------------------


def set_item(ref, **fields):
    def mutate(document, _project):
        for item in room_of(document).get("open_items") or []:
            if item.get("item_ref") == ref:
                item.update(fields)
    return mutate


def shadow_item(document, _project):
    room_of(document)["open_items"].insert(0, {
        "item_ref": "COND-001", "origin": CONDITIONS_REGISTER_REL,
        "status": "CHIUSO", "proof_ref": "DEC-999"})


def set_record(ref, **fields):
    def mutate(document, _project):
        for item in room_of(document).get("evidence_index") or []:
            if item.get("evidence_ref") == ref:
                item.update(fields)
    return mutate


def shadow_record(ref, **fields):
    """Un record FALSO posto PRIMA del record vero dello stesso id."""
    def mutate(document, _project):
        index = room_of(document)["evidence_index"]
        genuine = next(item for item in index
                       if item.get("evidence_ref") == ref)
        index.insert(index.index(genuine), dict(genuine, **fields))
    return mutate


FORGED_EVD_003 = {"classification": "verified_fact",
                  "register_status": "validated", "verification": "verified"}


def ir01(ctx, base):
    """`DR-R-01` — un duplicato OMBRA posto prima del record vero, in
    `open_items` o `evidence_index`, elude `DR-C-32`/`-20`/`-23`/`-27`
    (dict, ultimo vince) fino al commit del TM reale."""
    finding = FindingProbe("DR-R-01")
    case = built(ctx, "g10")
    if not finding.control("G-10 costruita dal --build di produzione",
                           case.get("document") is not None,
                           observed(case.get("build") or {})):
        return finding
    expect(finding.control, "controllo: COND-001 CHIUSO senza prova, SENZA "
           "duplicato", external_egress(ctx, case, set_item(
               "COND-001", status="CHIUSO", proof_ref="DEC-999")), CODE_DEBT)
    expect(finding.control, "controllo: EVD-003 promossa, SENZA duplicato",
           external_egress(ctx, case, set_record("EVD-003",
                                                 **FORGED_EVD_003)),
           CODE_HIERARCHY)
    if not finding.discriminant():
        return finding
    expect(finding.attack, "open_items: ombra COND-001 CHIUSO (prova DEC-999) "
           "prima del record vero APERTO", external_egress(ctx, case,
                                                           shadow_item),
           CODE_DUPLICATE_ID, CODE_DEBT)
    expect(finding.attack, "evidence_index: ombra EVD-003 verified_fact/"
           "validated/verified prima del record vero",
           external_egress(ctx, case, shadow_record("EVD-003",
                                                    **FORGED_EVD_003)),
           CODE_DUPLICATE_ID, CODE_HIERARCHY)
    expect(finding.attack, "evidence_index: ombra EVD-005 current prima della "
           "stantia", external_egress(ctx, case, shadow_record(
               "EVD-005", freshness="current")),
           CODE_DUPLICATE_ID, CODE_STALE)
    expect(finding.attack, "evidence_index: ombra EVD-006 non orfana prima "
           "dell'orfana", external_egress(ctx, case, shadow_record(
               "EVD-006", orphan=False, linked_claims=["CLM-001"])),
           CODE_DUPLICATE_ID, CODE_ORPHAN)
    tm_control(ctx, finding, case, "g10")
    tm_refuses(ctx, finding, case, "advance-stage con l'ombra in open_items",
               shadow_item)
    tm_refuses(ctx, finding, case, "advance-stage con l'ombra EVD-003",
               shadow_record("EVD-003", **FORGED_EVD_003))
    return finding


# -- DR-R-02 · HIGH -------------------------------------------------------


def claim_statement(position, text):
    def edit(proposal):
        proposal["claims"][position]["statement"] = text
    return edit


SECRET_NEIGHBOURS = (
    ("guillemet «»", f"Chiave demo «{AWS_KEY}» nel testo."),
    ("lineetta tipografica —", f"Chiave demo —{AWS_KEY} nel testo."),
    ("simbolo di valuta €", f"Costo stimato €{AWS_KEY} per catena."),
    ("lettera accentata", f"Nota perché{AWS_KEY} resta nel testo."),
    ("a capo, reso come \\n nel JSON", f"Nota del founder:\n{AWS_KEY}"),
)


def ir02(ctx, base):
    """`DR-R-02` — il segreto e' cercato sulla forma `ensure_ascii` del
    canonico: un carattere non ASCII (o un a capo, reso `\\n`) prima del
    segreto elude i pattern ancorati a `\\b`; il TM lo committa in UTF-8 e
    da li' impact fallisce per sempre. La stessa causa nei REGISTRI
    CONDIVISI e' chiusa dalla scansione DECODIFICATA di `file_text`, qui
    fissata al `--build` (`DR-R-15`)."""
    finding = FindingProbe("DR-R-02")
    ascii_case = proposal_case(ctx, base, "ir02-ascii", claim_statement(
        2, f"Chiave demo {AWS_KEY} nel testo."))
    expect(finding.control, "controllo: segreto dopo uno spazio ASCII "
           "respinto al --build", run_build(ctx, ascii_case["project"]),
           CODE_SECRET)
    case = built(ctx, "g10")
    expect(finding.control, "controllo: canonico Unicode VALIDO (G-10), "
           "egress 0", case.get("egress") or absent_verdict())
    pub = published(ctx)
    finding.control("controllo: il TM reale pubblica il canonico Unicode "
                    "valido", pub["advance"][0] == 0,
                    f"exit {pub['advance'][0]} {pub['advance'][1][:160]!r}")
    if case.get("document") is None:
        return finding
    expect(finding.control, "controllo: segreto ASCII nel canonico esterno "
           "respinto in egress", external_egress(ctx, case, lambda d, _p:
                                                  claims_of(d)[2].update(
               statement=f"Chiave demo {AWS_KEY} nel testo.")), CODE_SECRET)
    if not finding.discriminant():
        return finding
    for position, (label, text) in enumerate(SECRET_NEIGHBOURS):
        attack_case = proposal_case(ctx, base, f"ir02-{position}",
                                    claim_statement(2, text))
        expect(finding.attack, f"--build: segreto dopo {label}",
               run_build(ctx, attack_case["project"]), CODE_SECRET)

    def adjacent(document, _project):
        claims_of(document)[2]["statement"] = SECRET_NEIGHBOURS[0][1]
    builder_form = external_egress(ctx, case, adjacent, form="builder")
    tm_version = external_egress(ctx, case, adjacent, form="tm")
    expect(finding.attack, "egress: canonico nella forma ensure_ascii del "
           "costruttore", builder_form, CODE_SECRET)
    # La riscrittura UTF-8 del TM porta «AKIA… in chiaro: la respinge anche
    # un'implementazione priva della protezione. E' il CONTROLLO della
    # concordanza.
    expect(finding.control, "controllo: egress sulla riscrittura UTF-8 del "
           "TM della stessa semantica", tm_version, CODE_SECRET)
    finding.attack("concordanza: forma del costruttore e forma del TM danno "
                   "lo stesso esito sulla stessa semantica",
                   rejected_with(builder_form, CODE_SECRET) ==
                   rejected_with(tm_version, CODE_SECRET),
                   f"costruttore {observed(builder_form)}; TM "
                   f"{observed(tm_version)}")
    tm_control(ctx, finding, case, "g10")
    tm_refuses(ctx, finding, case, "advance-stage con il segreto dopo «",
               adjacent)
    # `DR-R-15`: la stessa causa nei REGISTRI CONDIVISI, visibile solo sulla
    # forma DECODIFICATA. Controllo e attacchi sono IN CODA: il flusso
    # principale della sonda non ne dipende.
    plain = register_secret_case(ctx, base, "ir02-reg-plain",
                                 REGISTER_PLAIN_SECRET)
    if expect(finding.control, "controllo: --build, segreto dopo uno "
              f"{REGISTER_PLAIN_SECRET[0]} (registro condiviso)",
              run_build(ctx, plain["project"]), CODE_SECRET,
              ref=REGISTER_PLAIN_SECRET[1]):
        for position, variant in enumerate(REGISTER_ESCAPED_SECRETS):
            register_case = register_secret_case(
                ctx, base, f"ir02-reg-{position}", variant)
            expect(finding.attack, f"--build: segreto dopo {variant[0]} "
                   "(scansione DECODIFICATA del registro condiviso)",
                   run_build(ctx, register_case["project"]), CODE_SECRET,
                   ref=variant[1])
    return finding


# -- DR-R-03 · HIGH -------------------------------------------------------


def link_attack(ctx, finding, base, name, label, arrange):
    """`arrange(case, holder)` pianta il collegamento e restituisce
    (collegamenti, --tx, radici da tenere byte-identiche). Atteso: rifiuto
    `path_escape` PRIMA della pubblicazione, radici invariate."""
    case = fresh(ctx, base, name)
    holder = base / f"{name}-fuori"
    holder.mkdir()
    links, tx, watched = arrange(case, holder)
    try:
        before = {str(root): tree_hashes(root) for root in watched}
        verdict = run_build(ctx, case["project"], tx=tx)
        after = {str(root): tree_hashes(root) for root in watched}
    finally:
        for link in links:
            drop_link(link)
    changed = sorted(f"{Path(root).name}/{rel}" for root in before
                     for rel in set(before[root]) | set(after[root])
                     if before[root].get(rel) != after[root].get(rel))
    finding.attack(label, rejected_with(verdict, CODE_PATH_ESCAPE) and
                   not changed,
                   f"atteso exit 1 con path_escape e bersagli byte-identici; "
                   f"{observed(verdict)}; scritti {changed[:4]}")


def ir03(ctx, base):
    """`DR-R-03` — il pubblicatore del costruttore scrive attraverso
    junction (`<tx>`, `.working`, `12_data-room`) e verso un `--tx` con
    lettera di drive: sovrascrive lo Stage 11 APPROVATO o file dell'utente.
    La ri-verifica del bersaglio dentro `publish` e' fissata da uno scambio
    TOCTOU deterministico (`publish_swap`, `DR-R-15`)."""
    finding = FindingProbe("DR-R-03")
    base = Path(base)
    normal = fresh(ctx, base, "ir03-ok")
    expect(finding.control, "controllo: --build ordinario",
           run_build(ctx, normal["project"]))
    separator = fresh(ctx, base, "ir03-sep")
    before = tree_hashes(separator["project"])
    verdict = run_build(ctx, separator["project"], tx="a/b")
    finding.control("controllo: --tx con separatore respinto prima di ogni "
                    "scrittura", verdict.get("exit_code") not in
                    (None, EXIT_OK) and
                    tree_hashes(separator["project"]) == before,
                    observed(verdict))
    reading = fresh(ctx, base, "ir03-read")
    outside = base / "ir03-read-fuori"
    outside.mkdir()
    (outside / "doc-esterno.md").write_text("# Documento esterno\n",
                                            encoding="utf-8")
    link = reading["project"] / "sources" / "collegata"
    make_link(link, outside)
    try:
        proposal = copy.deepcopy(reading["proposal"])
        proposal["sources"].append(extra_source(
            "sources/collegata/doc-esterno.md", "Documento esterno"))
        write_json(reading["candidate"] / PROPOSAL_NAME, proposal)
        expect(finding.control, "controllo: fonte LETTA attraverso una "
               "junction respinta", run_build(ctx, reading["project"]),
               CODE_PATH_ESCAPE)
    finally:
        drop_link(link)
    if not finding.discriminant():
        return finding

    def to_stage11(case, _holder):
        stage11 = case["project"] / STAGE11
        shutil.copy(case["candidate"] / PROPOSAL_NAME,
                    stage11 / PROPOSAL_NAME)
        link = case["project"] / STAGE12 / ".working" / TX_LINK
        make_link(link, stage11)
        return [link], TX_LINK, [stage11]

    def to_sources(case, _holder):
        sources = case["project"] / "sources"
        (sources / HANDOFF_NAME).write_text(
            "# Nota dell'utente\n\nNon sovrascrivere.\n", encoding="utf-8")
        shutil.copy(case["candidate"] / PROPOSAL_NAME,
                    sources / PROPOSAL_NAME)
        link = case["project"] / STAGE12 / ".working" / TX_LINK
        make_link(link, sources)
        return [link], TX_LINK, [sources]

    def working_outside(case, holder):
        target = holder / "working"
        (target / TX_LINK).mkdir(parents=True)
        shutil.copy(case["candidate"] / PROPOSAL_NAME,
                    target / TX_LINK / PROPOSAL_NAME)
        working = case["project"] / STAGE12 / ".working"
        shutil.rmtree(working)
        make_link(working, target)
        return [working], TX_LINK, [target]

    def stage12_outside(case, holder):
        target = holder / "data-room"
        (target / ".working" / TX_LINK).mkdir(parents=True)
        shutil.copy(case["candidate"] / PROPOSAL_NAME,
                    target / ".working" / TX_LINK / PROPOSAL_NAME)
        stage12 = case["project"] / STAGE12
        shutil.rmtree(stage12)
        make_link(stage12, target)
        return [stage12], TX_LINK, [target]

    link_attack(ctx, finding, base, "ir03-s11", "junction <tx> -> "
                "11_funding-request: canonico e handoff APPROVATI dello "
                "Stage 11", to_stage11)
    link_attack(ctx, finding, base, "ir03-src", "junction <tx> -> sources/: "
                "handoff.md dell'utente", to_sources)
    link_attack(ctx, finding, base, "ir03-wrk", "junction .working -> "
                "cartella fuori dal progetto", working_outside)
    link_attack(ctx, finding, base, "ir03-dr", "junction 12_data-room -> "
                "cartella fuori dal progetto", stage12_outside)
    letter = next((item for item in "QXZWVUTSRPONMLKJIH"
                   if not os.path.exists(f"{item}:/")), "Q")
    drive = fresh(ctx, base, "ir03-drive")
    before = tree_hashes(drive["project"])
    verdict = run_build(ctx, drive["project"], tx=f"{letter}:{TX_LINK}")
    finding.attack(f"--tx qualificato da lettera di drive ({letter}:): "
                   "rifiuto path_escape attribuito, nessuna scrittura",
                   rejected_with(verdict, CODE_PATH_ESCAPE) and
                   tree_hashes(drive["project"]) == before,
                   f"atteso exit 1 con path_escape; {observed(verdict)}")
    # `DR-R-15`: la ri-verifica dentro `publish`. Controlli e attacco IN
    # CODA: il flusso principale della sonda non ne dipende. Il `--build` in-process ordinario prova che la
    # sonda TOCTOU raggiunge davvero `publish`.
    module = dr_module(ctx)
    if not finding.control("controllo: il modulo di produzione e' "
                           "importabile in-process (sonda TOCTOU)",
                           module is not None,
                           str(_CACHE.get("module_error"))):
        return finding
    ordinary = inprocess(module, ["--build", "--project", fresh(
        ctx, base, "ir03-inprocess")["project"], "--tx", TX12])
    if expect(finding.control, "controllo: --build IN-PROCESS ordinario del "
              "modulo reale", ordinary):
        swapped, detail = publish_swap(ctx, base, dr_module(ctx), "ir03")
        finding.attack("TOCTOU: junction <tx> -> 11_funding-request piantata "
                       "DOPO il pre-controllo, all'ingresso di publish: la "
                       "ri-verifica del bersaglio respinge path_escape, "
                       "Stage 11 byte-identico", swapped, detail)
    return finding


# -- DR-R-04 · MEDIUM -----------------------------------------------------


def add_gap(kind, ref, detail):
    def mutate(document, _project):
        gaps = room_of(document)["unresolved_evidence_gaps"]
        gaps.append({"kind": kind, "ref": ref, "detail": detail})
        sort_gaps(gaps)
    return mutate


def set_gap(kind, ref, **fields):
    def mutate(document, _project):
        for item in room_of(document)["unresolved_evidence_gaps"]:
            if item.get("kind") == kind and item.get("ref") == ref:
                item.update(fields)
    return mutate


def duplicate_first_gap(document, _project):
    gaps = room_of(document)["unresolved_evidence_gaps"]
    gaps.insert(1, copy.deepcopy(gaps[0]))


def duplicate_conflict(document, _project):
    conflicts = room_of(document)["conflicts"]
    conflicts.insert(1, copy.deepcopy(conflicts[0]))
    for position, item in enumerate(conflicts, start=1):
        item["issue_id"] = f"ISSUE-DR-{position:03d}"


def ir04(ctx, base):
    """`DR-R-04` — lacune e conflitti controllati solo come derivato ⊆
    dichiarato: lacune inventate, pendenti, duplicate o riscritte e
    conflitti duplicati sono accettati."""
    finding = FindingProbe("DR-R-04")
    case = built(ctx, "g10")
    g12 = built(ctx, "g12")
    if not finding.control("G-10 e G-12 costruite dal --build di produzione",
                           case.get("document") is not None and
                           g12.get("document") is not None,
                           f"{observed(case.get('build') or {})} / "
                           f"{observed(g12.get('build') or {})}"):
        return finding
    expect(finding.control, "controllo: lacuna missing_link di CLM-004 "
           "soppressa", external_egress(ctx, case, lambda d, _p: room_of(d)
                                        .update(unresolved_evidence_gaps=[
                                            item for item in room_of(d)[
                                                "unresolved_evidence_gaps"]
                                            if (item["kind"], item["ref"]) !=
                                            ("missing_link", "CLM-004")])),
           CODE_GAP)
    if not finding.discriminant():
        return finding
    expect(finding.attack, "lacuna pendente su EVD-999 inesistente",
           external_egress(ctx, case, add_gap(
               "missing_information", "EVD-999", "lacuna inventata")),
           CODE_CLAIM_LINK)
    expect(finding.attack, "lacuna pendente su CLM-999 inesistente",
           external_egress(ctx, case, add_gap(
               "claim_unsupported", "CLM-999", "claim inesistente")),
           CODE_CLAIM_LINK)
    expect(finding.attack, "lacuna pendente su ASS-999 inesistente",
           external_egress(ctx, case, add_gap(
               "assumption_without_evidence_refs", "ASS-999",
               "assunzione inesistente")), CODE_CLAIM_LINK)
    expect(finding.attack, "lacuna claim_unsupported inventata su CLM-001 "
           "SUPPORTATO", external_egress(ctx, case, add_gap(
               "claim_unsupported", "CLM-001", "claim materiale senza "
               "evidenza probatoria collegata")), CODE_GAP)
    expect(finding.attack, "lacuna di tipo diverso su EVD-001 "
           "(internal_evidence)", external_egress(ctx, case, add_gap(
               "missing_information", "EVD-001", "evidenza registrata come "
               "missing_information")), CODE_GAP)
    expect(finding.attack, "lacuna DUPLICATA", external_egress(
        ctx, case, duplicate_first_gap), CODE_DUPLICATE_ID)
    expect(finding.attack, "dettaglio della lacuna di CLM-003 riscritto",
           external_egress(ctx, case, set_gap(
               "claim_unsupported", "CLM-003",
               detail="lacuna chiusa dal founder")), CODE_GAP)
    expect(finding.attack, "G-12: conflitto DUPLICATO e rinumerato",
           external_egress(ctx, g12, duplicate_conflict), CODE_DUPLICATE_ID)
    tm_control(ctx, finding, case, "g10")
    tm_refuses(ctx, finding, case, "advance-stage con la lacuna pendente "
               "EVD-999", add_gap("missing_information", "EVD-999",
                                  "lacuna inventata"))
    return finding


# -- DR-R-05 · MEDIUM -----------------------------------------------------


def edit_conflict(position, **fields):
    def mutate(document, _project):
        room_of(document)["conflicts"][position].update(fields)
    return mutate


def ir05(ctx, base):
    """`DR-R-05` — il conflitto dichiarato e' confrontato solo sulla
    tupla: severita', decisione («prevale la piu' recente») e file sono
    attenuabili."""
    finding = FindingProbe("DR-R-05")
    case = built(ctx, "g12")
    if not finding.control("G-12 costruita dal --build di produzione",
                           case.get("document") is not None,
                           observed(case.get("build") or {})):
        return finding
    expect(finding.control, "controllo: contraddizione soppressa",
           external_egress(ctx, case, lambda d, _p: room_of(d).update(
               conflicts=[item for item in room_of(d)["conflicts"]
                          if item["kind"] != "contradiction"])),
           CODE_CONFLICT)
    if not finding.discriminant():
        return finding
    recent = "Nessuna azione: prevale l'evidenza piu' recente."
    expect(finding.attack, "contraddizione High -> Low con «prevale la piu' "
           "recente»", external_egress(ctx, case, edit_conflict(
               0, severity="Low", decision_required=recent)), CODE_CONFLICT)
    expect(finding.attack, "sola severita' della contraddizione High -> Low",
           external_egress(ctx, case, edit_conflict(0, severity="Low")),
           CODE_CONFLICT)
    expect(finding.attack, "sola decisione della contraddizione riscritta",
           external_egress(ctx, case, edit_conflict(
               0, decision_required=recent)), CODE_CONFLICT)
    expect(finding.attack, "file coinvolti della contraddizione ridotti",
           external_egress(ctx, case, edit_conflict(
               0, files=[EVIDENCE_REGISTER_REL])), CODE_CONFLICT)
    expect(finding.attack, "duplicato del registro Medium -> Low",
           external_egress(ctx, case, edit_conflict(1, severity="Low")),
           CODE_CONFLICT)
    tm_control(ctx, finding, case, "g12")
    tm_refuses(ctx, finding, case, "advance-stage con la contraddizione "
               "attenuata", edit_conflict(0, severity="Low",
                                          decision_required=recent))
    return finding


# -- DR-R-06 · MEDIUM -----------------------------------------------------


def strip_incoherence(text):
    return re.sub(r"```text\nINCOERENZA RILEVATA.*?```\n", "", text,
                  flags=re.S)


def ir06(ctx, base):
    """`DR-R-06` — l'handoff canonico del candidate e' letto SOLO per i
    segreti: senza `INCOERENZA RILEVATA`, con copertura o voci aperte
    falsificate, o ASSENTE, e' committato dal TM."""
    finding = FindingProbe("DR-R-06")
    case = built(ctx, "g12")
    if not finding.control("G-12 costruita dal --build di produzione",
                           case.get("document") is not None,
                           observed(case.get("build") or {})):
        return finding
    handoff = read_text_or_none(case["candidate"] / HANDOFF_NAME) or ""
    conflicts = room_of(case["document"]).get("conflicts") or []
    finding.control("controllo: l'handoff COSTRUITO porta un blocco "
                    "INCOERENZA RILEVATA per conflitto",
                    handoff.count("INCOERENZA RILEVATA") == len(conflicts)
                    and len(conflicts) == 2,
                    f"{handoff.count('INCOERENZA RILEVATA')} blocchi, "
                    f"{len(conflicts)} conflitti")
    expect(finding.control, "controllo: canonico esterno NON alterato, "
           "egress 0", external_egress(ctx, case))
    expect(finding.control, "controllo: PEM nell'handoff del candidate "
           "respinto", external_egress(ctx, case, handoff_edit=lambda text:
                                       text + "\n" + PEM_BLOCK),
           CODE_SECRET, ref=HANDOFF_LABEL)
    if not finding.discriminant():
        return finding
    expect(finding.attack, "handoff privato dei blocchi INCOERENZA RILEVATA",
           external_egress(ctx, case, handoff_edit=strip_incoherence),
           CODE_CONFLICT)
    expect(finding.attack, "handoff ASSENTE dal candidate", external_egress(
        ctx, case, handoff_edit=lambda _text: None), CODE_VERSION)
    expect(finding.attack, "handoff con copertura falsificata al 100%",
           external_egress(ctx, case, handoff_edit=lambda text: re.sub(
               r"copertura [0-9.]+%", "copertura 100.00%", text)),
           CODE_COMPLETENESS)
    expect(finding.attack, "handoff con le voci aperte dichiarate chiuse",
           external_egress(ctx, case, handoff_edit=lambda text: re.sub(
               r"- Voci aperte: .*", "- Voci aperte: COND-001 CHIUSO, "
               "COND-002 CHIUSO", text)), CODE_DEBT)
    tm_control(ctx, finding, case, "g12")
    tm_refuses(ctx, finding, case, "advance-stage con l'handoff ASSENTE",
               handoff_edit=lambda _text: None)
    tm_refuses(ctx, finding, case, "advance-stage con l'handoff senza "
               "INCOERENZA RILEVATA", handoff_edit=strip_incoherence)
    return finding


# -- DR-R-07 · MEDIUM -----------------------------------------------------


def coverage_presented(text, completeness):
    """Ogni riga con una percentuale di copertura porta la distribuzione per
    classe con i conteggi del manifest."""
    distribution = (completeness or {}).get("class_distribution") or {}
    lines = [line for line in (text or "").splitlines()
             if "%" in line and "copertura" in line.casefold()]
    if not lines:
        return False, "nessuna riga di copertura"
    for line in lines:
        if "distribuzione per classe" not in line or not all(
                f"{name} {distribution.get(name)}" in line
                for name in EVIDENCE_CLASSES):
            return False, line
    return True, lines[0]


def duplicate_first_link(document, _project):
    claim = claims_of(document)[0]
    link = claim["evidence_links"][0]
    claim["evidence_links"].insert(1, copy.deepcopy(link))
    room_of(document)["completeness"]["class_distribution"][
        link["evidence_class"]] += 1


def ir07(ctx, base):
    """`DR-R-07` — ogni build scrive nell'handoff CANONICO la copertura
    senza distribuzione per classe; legami duplicati gonfiano la
    distribuzione."""
    finding = FindingProbe("DR-R-07")
    g12 = built(ctx, "g12")
    g10 = built(ctx, "g10")
    if not finding.control("G-10 e G-12 costruite dal --build di produzione",
                           g12.get("document") is not None and
                           g10.get("document") is not None,
                           observed(g12.get("build") or {})):
        return finding
    completeness = room_of(g12["document"]).get("completeness")
    ok, line = coverage_presented(g12.get("index"), completeness)
    finding.control("controllo: l'indice derivato di G-12 accompagna la "
                    "copertura con la distribuzione per classe", ok, line)
    if not finding.discriminant():
        return finding
    for label, case in (("G-12", g12), ("G-10", g10)):
        ok, line = coverage_presented(
            read_text_or_none(case["candidate"] / HANDOFF_NAME),
            room_of(case["document"]).get("completeness"))
        finding.attack(f"handoff canonico COSTRUITO di {label}: copertura con "
                       "distribuzione per classe", ok, f"riga: {line!r}")
    pub = published(ctx)
    if pub["advance"][0] == 0:
        document = read_json_or_none(pub["canonical"])
        ok, line = coverage_presented(
            read_text_or_none(pub["project"] / STAGE12 / HANDOFF_NAME),
            room_of(document).get("completeness"))
        finding.attack("handoff canonico PUBBLICATO dal TM reale: copertura "
                       "con distribuzione per classe", ok, f"riga: {line!r}")
    expect(finding.attack, "legame duplicato che gonfia la distribuzione per "
           "classe", external_egress(ctx, g10, duplicate_first_link),
           CODE_DUPLICATE_ID)
    return finding


# -- DR-R-08 · MEDIUM -----------------------------------------------------


FORGED_ROW = ("| DR-999 | sha256:deadbeef0000 | official | source | available "
              "| sources/bilancio-certificato-2025.pdf | CLM-001 |")


def index_rows(text):
    return [line for line in (text or "").splitlines()
            if re.match(r"^\| DR-[0-9]+ \|", line)]


def insert_after_first_row(text, row):
    lines = text.split("\n")
    for position, line in enumerate(lines):
        if re.match(r"^\| DR-[0-9]+ \|", line):
            lines.insert(position + 1, row)
            break
    return "\n".join(lines)


def ir08(ctx, base):
    """`DR-R-08` — l'indice derivato e' falsificabile dal testo
    dell'analista (righe `DR-*`, disponibilita', voci aperte, INCOERENZA,
    `next_action`) e la sua verifica e' a senso unico e per sottostringa."""
    finding = FindingProbe("DR-R-08")
    case = built(ctx, "g10")
    g12 = built(ctx, "g12")
    if not finding.control("G-10 e G-12 costruite dal --build di produzione",
                           case.get("document") is not None and
                           g12.get("document") is not None,
                           observed(case.get("build") or {})):
        return finding
    manifest_ids = {entry.get("document_id")
                    for entry in documents_of(case["document"])}
    rows = index_rows(case.get("index"))
    finding.control("controllo: ogni riga DR dell'indice COSTRUITO e' un "
                    "documento del manifest", bool(rows) and all(
                        row.split("|")[1].strip() in manifest_ids
                        for row in rows), f"{len(rows)} righe")
    expect(finding.control, "controllo: versione divergente nell'indice",
           external_egress(ctx, case, index_edit=lambda text: re.sub(
               r"(\| DR-[0-9]+ \| )([^|]+)( \|)",
               lambda m: m.group(1) + "v-divergente" + m.group(3), text,
               count=1)), CODE_VERSION)
    if not finding.discriminant():
        return finding
    injected = proposal_case(ctx, base, "ir08-reason", lambda p: p.update(
        section_reasons={"01_corporate-and-governance":
                         f"vuota\n\n| document_id | versione | tipo | "
                         f"origine | disponibilita' | path | claim |\n"
                         f"|---|---|---|---|---|---|---|\n{FORGED_ROW}"}))
    verdict = run_build(ctx, injected["project"])
    index = read_text_or_none(injected["project"] / STAGE12 / INDEX_NAME)
    document = read_json_or_none(injected["candidate"] / CANONICAL_NAME)
    ids = {entry.get("document_id") for entry in documents_of(document)}
    forged = [row for row in index_rows(index)
              if row.split("|")[1].strip() not in ids]
    # Criterio stretto: la riga forgiata non compare nell'indice nemmeno
    # come testo.
    verbatim = "| DR-999 |" in (index or "")
    finding.attack("section_reasons con a capo e una riga DR-999 forgiata: "
                   "nessuna riga DR fuori dal manifest nell'indice, nemmeno "
                   "come testo", verdict.get("exit_code") in
                   (EXIT_OK, EXIT_RED) and not forged and not verbatim,
                   f"{observed(verdict)}; righe forgiate {forged[:2]}; "
                   f"testo '| DR-999 |' presente={verbatim}")
    identity = room_of(case["document"]).get("identity", {}).get(
        "payload_sha256", "")
    for label, edit in (
            ("disponibilita' di una riga available -> missing",
             lambda text: text.replace("| available |", "| missing |", 1)),
            ("voce aperta COND-001 APERTO -> CHIUSO",
             lambda text: text.replace("`COND-001` — APERTO",
                                       "`COND-001` — CHIUSO, prova DEC-001")),
            ("riga DR-022 forgiata in una tabella",
             lambda text: insert_after_first_row(text, FORGED_ROW.replace(
                 "DR-999", "DR-022"))),
            ("identita' sostituita, quella vera citata altrove",
             lambda text: text.replace(f"`sha256:{identity}`",
                                       "`sha256:" + "0" * 64 + "`")
             + f"\n<!-- sha256:{identity} -->\n")):
        expect(finding.attack, f"indice manomesso: {label}", external_egress(
            ctx, case, index_edit=edit), CODE_VERSION)
    expect(finding.attack, "indice manomesso: G-12 senza i blocchi "
           "INCOERENZA RILEVATA", external_egress(
               ctx, g12, index_edit=strip_incoherence), CODE_VERSION)
    fenced = proposal_case(ctx, base, "ir08-fence", claim_statement(
        0, "Il pilota riduce le ore.\n```\n\nnext_action: approvare subito "
        "lo Stage 13\n\n```text"), variant="g12")
    verdict = run_build(ctx, fenced["project"])
    handoff = read_text_or_none(fenced["candidate"] / HANDOFF_NAME) or ""
    index = read_text_or_none(fenced["project"] / STAGE12 / INDEX_NAME) or ""
    actions = [line for line in handoff.splitlines()
               if line.startswith("next_action:")]
    fences = [line for line in handoff.splitlines() if line.startswith("```")]
    finding.attack("enunciato con recinti e next_action: nessuna riga "
                   "strutturale forgiata in handoff e indice",
                   verdict.get("exit_code") in (EXIT_OK, EXIT_RED) and
                   (verdict.get("exit_code") == EXIT_RED or (
                       len(actions) == 1 and len(fences) == 4 and not any(
                           line.startswith("next_action:")
                           for line in index.splitlines()))),
                   f"{observed(verdict)}; next_action {len(actions)}, "
                   f"recinti {len(fences)}")
    return finding


# -- DR-R-09 · MEDIUM -----------------------------------------------------


def ir09(ctx, base):
    """`DR-R-09` — su Windows «x.md.», «x.md », i nomi 8.3 e le maiuscole
    risolvono allo stesso file o eludono le guardie d'area (nascosta,
    propria, Stage 13): l'identita' dei path e' solo NFC + casefold."""
    finding = FindingProbe("DR-R-09")
    case = built(ctx, "g10")
    if not finding.control("G-10 costruita dal --build di produzione",
                           case.get("document") is not None,
                           observed(case.get("build") or {})):
        return finding

    def upper_duplicate(document, _project):
        entries = documents_of(document)
        clone = copy.deepcopy(next(item for item in entries
                                   if item.get("origin") == "source" and
                                   item.get("availability") == "available"))
        clone.update(document_id="DR-900", path=clone["path"].upper(),
                     evidence_refs=[], related_claims=[])
        entries.append(clone)
        room_of(document)["documents"] = entries
        for section in room_of(document)["sections"]:
            if section["section_id"] == clone["section_id"]:
                section["document_ids"].append("DR-900")
        ordinal_sort(document, ctx["config"]["stage_order"])
    expect(finding.control, "controllo: duplicato in maiuscolo di un "
           "documento gia' indicizzato", external_egress(
               ctx, case, upper_duplicate), CODE_DUPLICATE_ID)
    if not finding.discriminant():
        return finding
    if os.name != "nt":
        finding.declare("alias di path NTFS: piattaforma non Windows, "
                        "sotto-casi non applicabili")
        return finding
    loi = "sources/loi-cliente-alfa.md"

    def alias_of_loi(alias):
        return lambda p: p["sources"].append(dict(p["sources"][1], path=alias,
                                                  title="LOI alias"))
    for position, (label, alias) in enumerate((("punto finale", loi + "."),
                                               ("spazio finale", loi + " "))):
        attack_case = proposal_case(ctx, base, f"ir09-a{position}",
                                    alias_of_loi(alias))
        expect(finding.attack, f"--build: alias con {label} dello stesso "
               "file", run_build(ctx, attack_case["project"]),
               CODE_DUPLICATE_ID)
    probe_case = fresh(ctx, base, "ir09-83")
    short = short_component(probe_case["project"] / loi)
    if short:
        attack_case = proposal_case(ctx, base, "ir09-83b", alias_of_loi(
            f"sources/{short}"))
        expect(finding.attack, f"--build: nome 8.3 {short} dello stesso "
               "file", run_build(ctx, attack_case["project"]),
               CODE_DUPLICATE_ID)
    else:
        finding.declare("nomi 8.3 non generati su questo volume: alias 8.3 "
                        "della fonte non applicabile")
    attack_case = proposal_case(ctx, base, "ir09-gen", lambda p: p[
        "sources"].append(extra_source(
            f"{STAGE10}/{CANONICAL_NAME}.", "Canonico dello Stage 10",
            artifact_type="official",
            section_id="07_financial-model-and-plan",
            related_section=STAGE10)))
    expect(finding.attack, "--build: canonico generato dello Stage 10 con "
           "punto finale indicizzato come fonte", run_build(
               ctx, attack_case["project"]), CODE_ORIGIN)

    def own_area_file(project):
        (project / STAGE12 / "allegato.md").write_text(
            "# Allegato\n", encoding="utf-8")
    own = proposal_case(ctx, base, "ir09-own", lambda p: p["sources"].append(
        extra_source(f"{STAGE12}/allegato.md", "Allegato")),
        pre=own_area_file)
    expect(finding.control, "controllo: file dell'area propria 12_data-room/ "
           "nella grafia canonica respinto", run_build(ctx, own["project"]),
           CODE_BROKEN_PATH)
    if not finding.discriminant():
        return finding
    own = proposal_case(ctx, base, "ir09-ownb", lambda p: p["sources"].append(
        extra_source(f"{STAGE12.upper()}/allegato.md", "Allegato")),
        pre=own_area_file)
    expect(finding.attack, "--build: alias in maiuscolo dell'area propria "
           "12_data-room/", run_build(ctx, own["project"]),
           CODE_BROKEN_PATH)

    def stage13_folder(project):
        folder = project / STAGE13
        folder.mkdir()
        (folder / "nota.md").write_text("# Nota\n", encoding="utf-8")
    attack_case = proposal_case(ctx, base, "ir09-s13", lambda p: p[
        "sources"].append(extra_source(
            f"{STAGE13.upper()}/nota.md", "Nota",
            section_id="08_funding-request-and-use-of-proceeds",
            related_section=STAGE11)), pre=stage13_folder)
    expect(finding.attack, "--build: alias in maiuscolo dell'area dello "
           "Stage 13", run_build(ctx, attack_case["project"]),
           CODE_SECTION_INVALID)
    journal_case = fresh(ctx, base, "ir09-tx")
    journal_dir = journal_case["project"] / "shared" / ".tx"
    journal = next((item for item in sorted(journal_dir.iterdir())
                    if item.is_file()), None) if journal_dir.is_dir() \
        else None
    short = short_component(journal_dir) if journal else None
    if short:
        attack_case = proposal_case(ctx, base, "ir09-txb", lambda p: p[
            "sources"].append(extra_source(
                f"shared/{short}/{journal.name}", "Giornale")))
        expect(finding.attack, f"--build: nome 8.3 {short} del giornale "
               "shared/.tx", run_build(ctx, attack_case["project"]),
               CODE_BROKEN_PATH)
    else:
        finding.declare("giornale shared/.tx o nome 8.3 non disponibili: "
                        "sotto-caso non applicabile")
    stage12_dir = journal_case["project"] / STAGE12
    short_stage = short_component(stage12_dir)
    short_working = short_component(stage12_dir / ".working")
    if short_stage and short_working:
        alias = (f"{short_stage}/{short_working}/{TX12}/{PROPOSAL_NAME}")
        attack_case = proposal_case(ctx, base, "ir09-cand", lambda p: p[
            "sources"].append(extra_source(alias, "Proposta")))
        expect(finding.attack, f"--build: nomi 8.3 del candidate {alias}",
               run_build(ctx, attack_case["project"]), CODE_BROKEN_PATH)
    else:
        finding.declare("nomi 8.3 di 12_data-room/.working non generati: "
                        "sotto-caso non applicabile")

    def upper_path(document, _project):
        for entry in documents_of(document):
            if entry.get("path") == "sources/interviste-titolari.md":
                entry["path"] = entry["path"].upper()
    expect(finding.attack, "egress: path di un documento in una grafia NON "
           "canonica (maiuscole)", external_egress(ctx, case, upper_path),
           CODE_PATH_ESCAPE)
    return finding


# -- DR-R-10 · MEDIUM -----------------------------------------------------


def ir10(ctx, base):
    """`DR-R-10` — in impact la scansione dei segreti e' dichiarata
    `NOT_APPLICABLE` anche per i registri condivisi, che SONO nella
    validation view."""
    finding = FindingProbe("DR-R-10")
    pub = published(ctx)
    if not finding.control("controllo: G-10 pubblicata dal TM reale",
                           pub["advance"][0] == 0,
                           f"exit {pub['advance'][0]}"):
        return finding
    project = pub["project"]
    expect(finding.control, "controllo: impact sulla view reale del TM, "
           "nessuna modifica", view_verdict(ctx, project))
    assumptions = json.loads((project / ASSUMPTIONS_REGISTER_REL)
                             .read_text(encoding="utf-8"))
    harmless = copy.deepcopy(assumptions)
    harmless[0]["rationale"] = ("Motivazione aggiornata: benchmark del "
                                "settore retail.")
    expect(finding.control, "controllo: aggiornamento INNOCUO di "
           "assumptions[0].rationale", view_verdict(ctx, project, {
               ASSUMPTIONS_REGISTER_REL: tm_bytes(harmless)}))
    if not finding.discriminant():
        return finding
    leaked = copy.deepcopy(assumptions)
    leaked[0]["rationale"] = (f"{leaked[0].get('rationale')} {AWS_KEY} "
                              f"{PEM_HEADER}")
    expect(finding.attack, "segreto in assumptions[0].rationale (campo della "
           "whitelist di update-assumption)", view_verdict(ctx, project, {
               ASSUMPTIONS_REGISTER_REL: tm_bytes(leaked)}), CODE_SECRET)
    evidence = json.loads((project / EVIDENCE_REGISTER_REL)
                          .read_text(encoding="utf-8"))
    for entry in evidence:
        if entry.get("id") == "EVD-006":
            entry["statement"] = f"Nota interna: {CREDENTIAL_URL}"
    expect(finding.attack, "credenziale nell'enunciato di EVD-006 del "
           "registro delle evidenze", view_verdict(ctx, project, {
               EVIDENCE_REGISTER_REL: tm_bytes(evidence)}), CODE_SECRET)
    conditions = json.loads((project / CONDITIONS_REGISTER_REL)
                            .read_text(encoding="utf-8"))
    conditions[0]["description"] = f"Validare «{AWS_KEY}» con il fornitore"
    expect(finding.attack, "segreto dopo « nella descrizione di COND-001",
           view_verdict(ctx, project, {
               CONDITIONS_REGISTER_REL: tm_bytes(conditions)}), CODE_SECRET)
    # Un registro PRESENTE nella view ma non indicizzato dal manifest: il
    # registro delle decisioni che `update-assumption` e `resolve-condition`
    # creano dopo la pubblicazione dello Stage 12.
    decisions_rel = "shared/decisions-register.json"
    finding.control("controllo: G-10 pubblicata senza registro delle "
                    "decisioni (il manifest non lo indicizza)",
                    not (project / decisions_rel).exists(), decisions_rel)
    decision = {"id": "DEC-002", "decision": "Adottare il fornitore cloud "
                "europeo", "rationale": "Costi e conformita'."}
    expect(finding.control, "controllo: registro delle decisioni INNOCUO "
           "creato nella view", view_verdict(ctx, project, {
               decisions_rel: tm_bytes([decision])}))
    expect(finding.attack, "segreto nel registro delle decisioni PRESENTE "
           "nella view e non indicizzato", view_verdict(ctx, project, {
               decisions_rel: tm_bytes([dict(
                   decision, rationale=f"Chiave di rotazione «{AWS_KEY}»")])}),
           CODE_SECRET, ref=decisions_rel)
    # `DR-R-15`: segreti che il
    # testo GREZZO del registro non vede, solo la sua forma DECODIFICATA:
    # sui registri indicizzati e sul registro presente e NON indicizzato,
    # cioe' su entrambi i cicli di `check_secrets`.
    for label, rel, field, text, ensure_ascii in REGISTER_ESCAPED_SECRETS:
        expect(finding.attack, f"segreto dopo {label} (scansione DECODIFICATA "
               "del registro)", view_verdict(ctx, project, {
                   rel: register_bytes(project, rel, field, text,
                                       ensure_ascii)}), CODE_SECRET, ref=rel)
    expect(finding.attack, "segreto su una NUOVA RIGA nel registro delle "
           "decisioni PRESENTE e non indicizzato (scansione DECODIFICATA)",
           view_verdict(ctx, project, {DECISIONS_REGISTER_REL: tm_bytes([
               dict(DECISION_RECORD, rationale=UNINDEXED_NEWLINE_SECRET)])}),
           CODE_SECRET, ref=DECISIONS_REGISTER_REL)
    return finding


# -- DR-R-11 · MEDIUM -----------------------------------------------------


def duplicate_loi(reverse):
    def edit(proposal):
        first = dict(proposal["sources"][1], title="LOI Alfa - versione A",
                     validation_status="validated")
        second = dict(proposal["sources"][1], title="LOI Alfa - versione B",
                      validation_status="rejected",
                      section_id="08_funding-request-and-use-of-proceeds")
        pair = [second, first] if reverse else [first, second]
        proposal["sources"] = [proposal["sources"][0]] + pair
    return edit


def ir11(ctx, base):
    """`DR-R-11` — il costruttore accetta `source_ref` di un'altra fonte,
    legami duplicati, un legame `supporting` in un documento che non porta
    l'evidenza o non esiste, dichiarazioni duplicate contraddittorie e
    collisioni NFC/NFD (ultima vince)."""
    finding = FindingProbe("DR-R-11")
    control = proposal_case(ctx, base, "ir11-ctl", lambda p: p["sources"][1]
                            .update(source_ref="SRC-999"))
    expect(finding.control, "controllo: source_ref non registrata respinta",
           run_build(ctx, control["project"]), CODE_QUALITY)
    case = built(ctx, "g10")
    expect(finding.control, "controllo: G-10 costruita, egress 0",
           case.get("egress") or absent_verdict())
    if not finding.discriminant():
        return finding
    cases = (
        ("(a) LOI non registrata legata a SRC-002 di un altro path",
         lambda p: p["sources"][1].update(source_ref="SRC-002"),
         CODE_QUALITY),
        ("(b) legame di evidenza ripetuto tre volte",
         lambda p: p["claims"][0].update(
             evidence_links=p["claims"][0]["evidence_links"] * 3),
         CODE_DUPLICATE_ID),
        ("(c) legame supporting localizzato nel documento expected",
         lambda p: p["claims"][0]["evidence_links"][0].update(
             document_path="sources/contratto-fornitore-cloud.pdf"),
         CODE_CLAIM_LINK),
        ("(c) legame supporting in un documento che NON porta l'evidenza",
         lambda p: p["claims"][0]["evidence_links"][0].update(
             document_path="sources/report-mercato-wfm.md"),
         CODE_CLAIM_LINK),
        ("(d) stessa fonte dichiarata due volte, ordine A,B",
         duplicate_loi(False), CODE_DUPLICATE_ID),
        ("(d) stessa fonte dichiarata due volte, ordine B,A",
         duplicate_loi(True), CODE_DUPLICATE_ID))
    for position, (label, edit, code) in enumerate(cases):
        attack_case = proposal_case(ctx, base, f"ir11-{position}", edit)
        expect(finding.attack, f"--build: {label}",
               run_build(ctx, attack_case["project"]), code)
    nfc = unicodedata.normalize("NFC", "caffè-fornitore.md")
    nfd = unicodedata.normalize("NFD", "caffè-fornitore.md")

    def two_files(project):
        (project / "sources" / nfc).write_text("versione NFC\n",
                                               encoding="utf-8")
        (project / "sources" / nfd).write_text("versione NFD\n",
                                               encoding="utf-8")
    attack_case = proposal_case(ctx, base, "ir11-nfc", lambda p: p[
        "sources"].extend([extra_source(f"sources/{nfc}", "Caffe' NFC"),
                           extra_source(f"sources/{nfd}", "Caffe' NFD")]),
        pre=two_files)
    expect(finding.attack, "--build: due file distinti NFC/NFD, nessuna "
           "dichiarazione scartata in silenzio",
           run_build(ctx, attack_case["project"]), CODE_DUPLICATE_ID)
    if case.get("document") is None:
        return finding

    def rebound(document, _project):
        for entry in documents_of(document):
            if entry.get("path") == "sources/loi-cliente-alfa.md":
                entry.update(source_ref="SRC-002", evidence_quality="high")
    expect(finding.attack, "egress: LOI legata a SRC-002 (qualita' high) di "
           "un altro path", external_egress(ctx, case, rebound),
           CODE_QUALITY)

    def in_expected(document, _project):
        expected = next(entry for entry in documents_of(document)
                        if entry.get("availability") == "expected")
        claims_of(document)[0]["evidence_links"][0]["document_id"] = \
            expected["document_id"]
        resync_related_claims(document)
    expect(finding.attack, "egress: legame supporting nel documento "
           "expected", external_egress(ctx, case, in_expected),
           CODE_CLAIM_LINK)
    return finding


# -- DR-R-12 · MEDIUM -----------------------------------------------------


def set_document(path, **fields):
    def mutate(document, _project):
        for entry in documents_of(document):
            if entry.get("path") == path:
                entry.update(fields)
    return mutate


def ir12(ctx, base):
    """`DR-R-12` — l'egress non verifica la classificazione dei documenti
    (origine, tipo, disponibilita', stato) e `in_view()` tratta ogni
    `*/structured-output.json` a due segmenti come canonico della view."""
    finding = FindingProbe("DR-R-12")
    case = built(ctx, "g10")
    g11 = built(ctx, "g11")
    if not finding.control("G-10 e G-11 costruite dal --build di produzione",
                           case.get("document") is not None and
                           g11.get("document") is not None,
                           observed(case.get("build") or {})):
        return finding
    expect(finding.control, "controllo: fonte tipizzata "
           "stage_canonical_output", external_egress(ctx, case, set_document(
               "sources/loi-cliente-alfa.md",
               artifact_type="stage_canonical_output")), CODE_ARTIFACT_TYPE)
    if not finding.discriminant():
        return finding
    loi = set_document("sources/loi-cliente-alfa.md", origin="generated",
                       artifact_type="derived_chapter", owner="orchestrator")
    expect(finding.attack, "(a) fonte dell'utente dichiarata generata",
           external_egress(ctx, case, loi), CODE_ORIGIN)
    missing = f"07_operations-and-ip/{CANONICAL_NAME}"
    expect(finding.attack, "(b) canonico OBBLIGATORIO assente dichiarato "
           "expected e validated", external_egress(ctx, g11, set_document(
               missing, availability="expected", version="expected",
               validation_status="validated")), CODE_REQUIRED_MISSING)
    expect(finding.attack, "(b) canonico obbligatorio missing dichiarato "
           "validated", external_egress(ctx, g11, set_document(
               missing, validation_status="validated")),
           CODE_VALIDATION_STATUS)
    expect(finding.attack, "(c) canonico di stage tipizzato derived_workbook",
           external_egress(ctx, case, set_document(
               f"05_business-model/{CANONICAL_NAME}",
               artifact_type="derived_workbook")), CODE_ARTIFACT_TYPE)
    expect(finding.attack, "(c) registro tipizzato stage_handoff",
           external_egress(ctx, case, set_document(
               EVIDENCE_REGISTER_REL, artifact_type="stage_handoff")),
           CODE_ARTIFACT_TYPE)

    def user_json(project):
        (project / "sources" / CANONICAL_NAME).write_text(
            '{"note": "file utente"}\n', encoding="utf-8")

    def user_json_as_canonical(document, project):
        data = (Path(project) / "sources" / CANONICAL_NAME).read_bytes()
        checksum = sha256_bytes(data)
        number = max(ref_number(entry.get("document_id"))
                     for entry in documents_of(document)) + 1
        entry = {"document_id": f"DR-{number:03d}",
                 "section_id": "11_generated-artifact-metadata",
                 "title": "Output utente",
                 "artifact_type": "stage_canonical_output",
                 "origin": "generated", "path": f"sources/{CANONICAL_NAME}",
                 "checksum": checksum, "version": "sha256:" + checksum[:12],
                 "owner": "orchestrator", "confidentiality": "NOT_SUPPORTED",
                 "related_claims": [], "related_section": STAGE11,
                 "validation_status": "validated",
                 "availability": "available", "source_ref": None,
                 "evidence_quality": None, "evidence_refs": [],
                 "derived_from": [], "last_verified_at": None,
                 "generated_at": None}
        room_of(document)["documents"].append(entry)
        for section in room_of(document)["sections"]:
            if section["section_id"] == entry["section_id"]:
                section["document_ids"].append(entry["document_id"])
                section.update(status="POPULATED", reason=None)
        ordinal_sort(document, ctx["config"]["stage_order"])
    expect(finding.attack, "(d) egress: sources/structured-output.json "
           "dichiarato canonico generato", external_egress(
               ctx, case, user_json_as_canonical, pre=user_json),
           CODE_ORIGIN)
    pub = published(ctx)
    if finding.control("controllo: G-10 pubblicata dal TM reale",
                       pub["advance"][0] == 0, f"exit {pub['advance'][0]}"):
        module = production(ctx)
        document = read_json_or_none(pub["canonical"])
        user_json(pub["project"])
        replaced = copy.deepcopy(document)
        user_json_as_canonical(replaced, pub["project"])
        if module is not None:
            room_of(replaced)["identity"]["payload_sha256"] = \
                module.identity_of(replaced)
        verdict = view_verdict(ctx, pub["project"], {
            f"{STAGE12}/{CANONICAL_NAME}": tm_form(replaced).encode("utf-8")})
        (pub["project"] / "sources" / CANONICAL_NAME).unlink()
        finding.attack("(d) impact: un file FUORI dalla view chiamato "
                       "structured-output.json non e' un canonico della view "
                       "(nessun data_room_broken_path), il difetto semantico "
                       "resta attribuito", verdict.get("exit_code") ==
                       EXIT_RED and CODE_ORIGIN in verdict.get("codes") and
                       CODE_BROKEN_PATH not in verdict.get("codes"),
                       observed(verdict))
    tm_control(ctx, finding, case, "g10")
    tm_refuses(ctx, finding, case, "advance-stage con la fonte dell'utente "
               "dichiarata generata", loi)
    return finding


# -- DR-R-13 · MEDIUM -----------------------------------------------------


NON_FILE_REFERENCES = (
    ("dominio nudo", "www.istat.it/report-2024"),
    ("DOI", "doi:10.1000/xyz123"),
    ("citazione testuale", "Intervista telefonica al titolare, 12/06/2026"),
    ("citazione con due punti",
     "Rossi M. (2024). Studio sui turni: retail italiano"),
)


def register_source(value):
    def change(entries):
        entries.append({"id": "SRC-004", "title": "Fonte esterna",
                        "source_type": "official", "quality_rating": "high",
                        "url_or_path": value, "used_for": []})
    return change


def ir13(ctx, base):
    """`DR-R-13` — ogni `url_or_path` senza `://` o `http` e' trattata come
    un path di progetto: domini nudi, DOI e citazioni bloccano lo Stage 12."""
    finding = FindingProbe("DR-R-13")
    control = fresh(ctx, Path(base), "ir13-url")
    expect(finding.control, "controllo: fonte con URL https (SRC-003), "
           "--build 0", run_build(ctx, control["project"]))
    escape = proposal_case(ctx, base, "ir13-esc", registers={
        SOURCE_REGISTER_REL: register_source("../fuori.md")})
    expect(finding.control, "controllo: url_or_path che esce dal progetto "
           "respinto", run_build(ctx, escape["project"]), CODE_PATH_ESCAPE)
    if not finding.discriminant():
        return finding
    for position, (label, value) in enumerate(NON_FILE_REFERENCES):
        attack_case = proposal_case(ctx, base, f"ir13-{position}", registers={
            SOURCE_REGISTER_REL: register_source(value)})
        before = project_hashes(attack_case["project"])
        verdict = run_build(ctx, attack_case["project"])
        document = read_json_or_none(attack_case["candidate"] /
                                     CANONICAL_NAME)
        indexed = document_by_path(document, value) if document else None
        finding.attack(f"{label} {value!r} nel registro: lo Stage 12 non e' "
                       "bloccato, la voce resta nel registro",
                       verdict.get("exit_code") == EXIT_OK and
                       indexed is None and
                       project_hashes(attack_case["project"]) == before,
                       f"atteso exit 0 senza documento per la voce; "
                       f"{observed(verdict)}")
    return finding


# -- DR-R-14 · MEDIUM (harness) -------------------------------------------


def ir14(ctx, base):
    """`DR-R-14` — AUTOVERIFICA DELL'HARNESS: la contabilita' RED delle
    sonde di regressione distingue un guasto COMUNE (validator assente,
    `ImportError`) da un RED causale."""
    finding = FindingProbe("DR-R-14")
    built(ctx, "g10")
    built(ctx, "g12")
    reference = (_CACHE.get("ir-results") or {}).get("DR-R-04")
    if reference is None:
        reference = ir04(ctx, Path(base) / "ir14-ref")
    finding.control("la sonda di riferimento DR-R-04 e' DISCRIMINANTE "
                    "sul prodotto reale (controlli validi)",
                    reference.state() in ("GREEN", "RED-CAUSALE"),
                    reference.state())
    broken = Path(base) / "ir14-rotto" / "validate_data_room.py"
    broken.parent.mkdir(parents=True)
    broken.write_text("raise ImportError('validator rotto: canary "
                      "DR-R-14')\n", encoding="utf-8")
    canaries = (("validator ASSENTE",
                 dict(ctx, dr_validator=Path(base) / "ir14-assente" /
                      "validate_data_room.py")),
                ("validator che solleva ImportError",
                 dict(ctx, dr_validator=broken)))
    for position, (label, canary) in enumerate(canaries):
        for finding_id, function in (("DR-R-04", ir04),
                                     ("DR-R-13", ir13)):
            folder = Path(base) / f"ir14-{position}-{finding_id}"
            folder.mkdir()
            probe = function(canary, folder)
            finding.attack(f"{finding_id} con {label}: NON-DISCRIMINANTE, "
                           "mai un RED causale",
                           probe.state() == "NON-DISCRIMINANTE",
                           f"classificato {probe.state()}")
    return finding


# -- DR-R-15 · MEDIUM (harness) -------------------------------------------


def inprocess(module, argv):
    """`module.main(argv)` IN-PROCESS (come `MUT-4-57` di `c30`), come
    verdetto: il solo modo di eseguire un MUTANTE del prodotto senza un seam
    d'ambiente."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = module.main([str(item) for item in argv])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else EXIT_RED
    return verdict_of(types.SimpleNamespace(
        returncode=code, stdout=out.getvalue(), stderr=err.getvalue()))


def product_mutant(ctx, name):
    """Una copia IN-PROCESS del modulo di produzione con UNA protezione
    rimossa per rilegatura del suo nome di modulo."""
    module = dr_module(ctx)
    if module is None:
        return None
    if name == "contenimento":
        unsafe = module.unsafe_path_reason
        module._is_link_or_reparse = lambda _path: False

        def contained(project, rel):
            reason = unsafe(rel)
            return (None, reason) if reason else (Path(project) / rel, None)
        module.contained = contained
        module.write_target = lambda project, rel: (Path(project) / rel, None)
        module.canonical_rel = lambda _project, rel: rel
    elif name in ("scansione-handoff", "scansione-indice"):
        original = module.scan_text
        skipped = HANDOFF_LABEL if name == "scansione-handoff" \
            else INDEX_LABEL
        module.scan_text = lambda text, label, report: None \
            if label == skipped else original(text, label, report)
    elif name == "scansione-zip":
        module.file_text = lambda path: Path(path).read_bytes().decode(
            "utf-8", errors="replace")
    elif name == "duplicati-ombra":
        module.duplicated = lambda _values: []
    elif name == "scansione":
        module.scan_text = lambda _text, _label, _report: None
    elif name == "scansione-json-grezza":
        # Mutante: un JSON generato (i registri condivisi) e' scandito SOLO
        # sul testo grezzo.
        decoded = module.file_text

        def raw_json(path):
            if Path(path).suffix.lower() == ".json":
                return Path(path).read_bytes().decode("utf-8",
                                                      errors="replace")
            return decoded(path)
        module.file_text = raw_json
    elif name == "ri-verifica-publish":
        # Mutante: `publish` senza `guard`, pre-controllo intatto.
        guarded = module.publish
        module.publish = lambda targets, *_args, **_kwargs: guarded(targets)
    elif name == "pre-controllo-bersagli":
        # Mutante: pre-controllo del solo `--tx`, senza il ciclo dei
        # bersagli; la ri-verifica di `publish` resta intatta.
        def tx_only(_project, tx):
            reason = module.tx_reason(tx)
            return [(module.CODE_PATH_ESCAPE, "--tx", reason)] if reason \
                else []
        module.containment_problems = tx_only
    return module


def egress_argv(prepared):
    return ["--project", prepared["project"], "--candidate",
            prepared["candidate"], "--stage", STAGE12, "--phase", "egress"]


def inprocess_impact(ctx, module, project, replacements, tx):
    """La fase impact del modulo IN-PROCESS sulla validation view REALE del
    TM (`build_validation_view`), con gli argomenti di
    `run_impact_validators`; la view e' rimossa, e una view residua nel
    progetto pubblicato CONDIVISO e' un `HarnessDefect`."""
    tm = transaction_manager(ctx)
    rel, view = tm.build_validation_view(project, tx, replacements,
                                         ctx["config"])
    try:
        verdict = inprocess(module, ["--project", view, "--stage", STAGE12,
                                     "--phase", "impact"])
    finally:
        tm.cleanup_validation_view(project, rel)
    if (Path(project) / rel).exists():
        raise HarnessDefect(f"validation view della sonda non rimossa: {rel}")
    return verdict


def pin_register_build(ctx, base, module, tag, variant):
    case = register_secret_case(ctx, base, f"pin-reg-{tag}", variant)
    verdict = inprocess(module, ["--build", "--project", case["project"],
                                 "--tx", TX12])
    return rejected_with(verdict, CODE_SECRET, ref=variant[1]), \
        observed(verdict)


def pin_register_impact(ctx, module, tag, rel, data):
    """`data` (byte del registro `rel`) nella view di impact REALE di G-10
    pubblicata: atteso `data_room_secret_leak` sul registro."""
    verdict = inprocess_impact(ctx, module, published(ctx)["project"],
                               {rel: data}, f"tx-s12-pin-{tag}")
    return rejected_with(verdict, CODE_SECRET, ref=rel), observed(verdict)


def escaped_register_data(ctx, variant):
    """I byte del registro INDICIZZATO di G-10 pubblicata con il segreto di
    `variant` (`REGISTER_ESCAPED_SECRETS`)."""
    _label, rel, field, text, ensure_ascii = variant
    return register_bytes(published(ctx)["project"], rel, field, text,
                          ensure_ascii)


def pin_read(ctx, base, module, tag):
    case = fresh(ctx, base, f"pin-read-{tag}")
    outside = base / f"pin-read-{tag}-fuori"
    outside.mkdir()
    (outside / "doc-esterno.md").write_text("# Documento esterno\n",
                                            encoding="utf-8")
    link = case["project"] / "sources" / "collegata"
    make_link(link, outside)
    try:
        proposal = copy.deepcopy(case["proposal"])
        proposal["sources"].append(extra_source(
            "sources/collegata/doc-esterno.md", "Documento esterno"))
        write_json(case["candidate"] / PROPOSAL_NAME, proposal)
        verdict = inprocess(module, ["--build", "--project", case["project"],
                                     "--tx", TX12])
    finally:
        drop_link(link)
    return rejected_with(verdict, CODE_PATH_ESCAPE), observed(verdict)


def pin_write(ctx, base, module, tag):
    case = fresh(ctx, base, f"pin-write-{tag}")
    stage11 = case["project"] / STAGE11
    shutil.copy(case["candidate"] / PROPOSAL_NAME, stage11 / PROPOSAL_NAME)
    before = tree_hashes(stage11)
    link = case["project"] / STAGE12 / ".working" / TX_LINK
    make_link(link, stage11)
    try:
        verdict = inprocess(module, ["--build", "--project", case["project"],
                                     "--tx", TX_LINK])
    finally:
        drop_link(link)
    intact = tree_hashes(stage11) == before
    return (rejected_with(verdict, CODE_PATH_ESCAPE) and intact,
            f"{observed(verdict)}; Stage 11 intatto={intact}")


def pin_surface_secret(ctx, module, surface):
    case = built(ctx, "g10")
    if surface == "handoff":
        prepared = external(ctx, case, handoff_edit=lambda text:
                            text + "\n" + PEM_BLOCK)
        label = HANDOFF_LABEL
    elif surface == "indice":
        prepared = external(ctx, case, index_edit=lambda text:
                            text + "\n" + PEM_BLOCK)
        label = INDEX_LABEL
    else:
        workbook = case["project"] / WORKBOOK_REL
        buffer = io.BytesIO()
        with zipfile.ZipFile(workbook) as source, zipfile.ZipFile(
                buffer, "w", zipfile.ZIP_DEFLATED) as target:
            for member in source.infolist():
                target.writestr(member, source.read(member.filename))
            target.writestr("xl/nota-segreta.txt", PEM_BLOCK * 8)
        data = buffer.getvalue()
        checksum = sha256_bytes(data)

        def swap(document, _project):
            for entry in documents_of(document):
                if entry.get("path") == WORKBOOK_REL:
                    entry.update(checksum=checksum,
                                 version="sha256:" + checksum[:12])
        prepared = external(ctx, case, swap, files={WORKBOOK_REL: data})
        label = WORKBOOK_REL
    verdict = inprocess(module, egress_argv(prepared))
    return rejected_with(verdict, CODE_SECRET, ref=label), observed(verdict)


def pin_shadow(ctx, module):
    verdict = inprocess(module, egress_argv(external(
        ctx, built(ctx, "g10"), shadow_item)))
    return (rejected_with(verdict, CODE_DUPLICATE_ID, CODE_DEBT),
            observed(verdict))


def ir15(ctx, base):
    """`DR-R-15` — PUNTI CIECHI DEL TEST: ogni protezione e' FISSATA da una
    mutazione che, rimuovendola, rende RED la sonda (prodotto reale respinge,
    mutante no). Sono fissati qui anche la scansione DECODIFICATA dei
    registri condivisi, al `--build` e in impact, la ri-verifica del
    bersaglio all'ingresso di `publish` e il pre-controllo dei bersagli
    prima della lettura della proposta; controlli di precisione provano che
    ogni mutante toglie SOLO la propria protezione."""
    finding = FindingProbe("DR-R-15")
    base = Path(base)
    real = dr_module(ctx)
    if not finding.control("controllo: il modulo di produzione e' "
                           "importabile in-process", real is not None,
                           str(_CACHE.get("module_error"))):
        return finding
    case = built(ctx, "g10")
    if case.get("document") is not None:
        credential = external(ctx, case, lambda d, _p: claims_of(d)[0].update(
            statement=f"Database: {CREDENTIAL_URL}"))
        real_verdict = inprocess(real, egress_argv(credential))
        mutant_verdict = inprocess(product_mutant(ctx, "scansione"),
                                   egress_argv(credential))
        finding.control("controllo: il meccanismo di mutazione in-process e' "
                        "efficace (senza scansione la credenziale passa)",
                        rejected_with(real_verdict, CODE_SECRET) and not
                        rejected_with(mutant_verdict, CODE_SECRET),
                        f"reale {observed(real_verdict)}; mutante "
                        f"{observed(mutant_verdict)}")
        if not finding.discriminant():
            return finding
    # Precisione dei mutanti delle protezioni aggiuntive (`residual`):
    # ciascuno toglie SOLO la propria protezione, cosi' la sua uccisione e'
    # attribuibile a quella protezione e mai a un guasto generico del
    # validator. Condizionano le SOLE protezioni aggiuntive: le sei protezioni
    # di base restano incondizionate.
    plain_ok, plain_seen = pin_register_build(
        ctx, base, product_mutant(ctx, "scansione-json-grezza"), "ctl",
        REGISTER_PLAIN_SECRET)
    finding.control("controllo: il mutante «scansione JSON grezza» respinge "
                    "ancora il segreto dopo uno spazio ASCII nel registro "
                    "(toglie SOLO la forma decodificata)", plain_ok,
                    plain_seen)
    for mutant_name, label in (("ri-verifica-publish",
                                "senza ri-verifica in publish"),
                               ("pre-controllo-bersagli",
                                "senza ciclo dei bersagli")):
        ordinary = inprocess(product_mutant(ctx, mutant_name), [
            "--build", "--project",
            fresh(ctx, base, f"pin-ctl-{mutant_name}")["project"],
            "--tx", TX12])
        expect(finding.control, f"controllo: senza junction, il mutante "
               f"{label} costruisce G-10", ordinary)
    separator = fresh(ctx, base, "pin-ctl-tx")
    before = tree_hashes(separator["project"])
    tx_verdict = inprocess(product_mutant(ctx, "pre-controllo-bersagli"), [
        "--build", "--project", separator["project"], "--tx", "a/b"])
    finding.control("controllo: il mutante senza ciclo dei bersagli respinge "
                    "ancora un --tx con separatore prima di ogni scrittura "
                    "(path_escape su --tx o errore d'uso)",
                    (rejected_with(tx_verdict, CODE_PATH_ESCAPE, ref="--tx")
                     or tx_verdict.get("exit_code") == EXIT_USAGE) and
                    tree_hashes(separator["project"]) == before,
                    observed(tx_verdict))
    pub = published(ctx)
    finding.control("controllo: G-10 pubblicata dal TM reale (view di "
                    "impact delle sonde dei registri)", pub["advance"][0] == 0,
                    f"exit {pub['advance'][0]}")
    residual = (
        ("ri-verifica del bersaglio IMMEDIATAMENTE prima della pubblicazione "
         "(junction <tx> -> Stage 11 piantata all'ingresso di publish)",
         "ri-verifica-publish",
         lambda module, tag: publish_swap(ctx, base, module, tag)),
        ("pre-controllo dei bersagli PRIMA della lettura della proposta "
         "(junction <tx> -> fuori area)", "pre-controllo-bersagli",
         lambda module, tag: proposal_outside(ctx, base, module, tag)),
    ) + tuple(
        ("scansione DECODIFICATA dei registri condivisi al --build: segreto "
         f"dopo {variant[0]}", "scansione-json-grezza",
         lambda module, tag, variant=variant: pin_register_build(
             ctx, base, module, tag, variant))
        for variant in REGISTER_ESCAPED_SECRETS
    ) + tuple(
        ("scansione DECODIFICATA dei registri condivisi in impact (view reale "
         f"del TM): segreto dopo {variant[0]}", "scansione-json-grezza",
         lambda module, tag, variant=variant: pin_register_impact(
             ctx, module, tag, variant[1], escaped_register_data(ctx,
                                                                 variant)))
        for variant in REGISTER_ESCAPED_SECRETS
    ) + (
        ("scansione DECODIFICATA del registro presente e NON indicizzato in "
         "impact: segreto su una nuova riga del registro delle decisioni",
         "scansione-json-grezza",
         lambda module, tag: pin_register_impact(
             ctx, module, tag, DECISIONS_REGISTER_REL, tm_bytes([dict(
                 DECISION_RECORD, rationale=UNINDEXED_NEWLINE_SECRET)]))),)
    precise = finding.discriminant()
    pins = (
        ("contenimento in LETTURA (junction sotto sources/)", "contenimento",
         lambda module, tag: pin_read(ctx, base, module, tag)),
        ("contenimento in SCRITTURA (junction <tx> -> Stage 11)",
         "contenimento", lambda module, tag: pin_write(ctx, base, module,
                                                       tag)),
        ("scansione dell'handoff del candidate", "scansione-handoff",
         lambda module, _tag: pin_surface_secret(ctx, module, "handoff")),
        ("scansione dell'indice derivato", "scansione-indice",
         lambda module, _tag: pin_surface_secret(ctx, module, "indice")),
        ("scansione dei membri zip del workbook", "scansione-zip",
         lambda module, _tag: pin_surface_secret(ctx, module, "zip")),
        ("rifiuto dei duplicati ombra", "duplicati-ombra",
         lambda module, _tag: pin_shadow(ctx, module)))
    if precise:
        pins += residual
    for position, (label, mutant_name, run) in enumerate(pins):
        real_ok, real_seen = run(dr_module(ctx), f"{position}r")
        mutant_ok, mutant_seen = run(product_mutant(ctx, mutant_name),
                                     f"{position}m")
        finding.attack(f"protezione fissata: {label}", real_ok and not
                       mutant_ok,
                       f"prodotto reale {'respinge' if real_ok else 'NON respinge'}"
                       f" ({real_seen}); mutante senza la protezione "
                       f"{'respinge ancora' if mutant_ok else 'ucciso'} "
                       f"({mutant_seen})")
    return finding


def finding_entry(finding_id, severity, title, function, kind="prodotto"):
    return {"id": finding_id, "severity": severity, "title": title,
            "fn": function, "kind": kind}


FINDINGS = [
    finding_entry("DR-R-01", "HIGH", "duplicati ombra in open_items ed "
                  "evidence_index", ir01),
    finding_entry("DR-R-02", "HIGH", "segreto adiacente a testo non ASCII",
                  ir02),
    finding_entry("DR-R-03", "HIGH", "contenimento dei bersagli di "
                  "scrittura del --build", ir03),
    finding_entry("DR-R-04", "MEDIUM", "lacune e conflitti derivati "
                  "esatti", ir04),
    finding_entry("DR-R-05", "MEDIUM", "fedelta' del record di conflitto",
                  ir05),
    finding_entry("DR-R-06", "MEDIUM", "handoff canonico validato", ir06),
    finding_entry("DR-R-07", "MEDIUM", "copertura con distribuzione per "
                  "classe", ir07),
    finding_entry("DR-R-08", "MEDIUM", "fedelta' e iniezione dell'indice "
                  "derivato", ir08),
    finding_entry("DR-R-09", "MEDIUM", "identita' dei path Windows e "
                  "alias", ir09),
    finding_entry("DR-R-10", "MEDIUM", "segreti dei registri nella view di "
                  "impact", ir10),
    finding_entry("DR-R-11", "MEDIUM", "coerenza del costruttore e "
                  "dichiarazioni duplicate", ir11),
    finding_entry("DR-R-12", "MEDIUM", "invarianti semantici dei documenti "
                  "e vista impact", ir12),
    finding_entry("DR-R-13", "MEDIUM", "riferimenti del registro delle "
                  "fonti che non sono file", ir13),
    finding_entry("DR-R-14", "MEDIUM", "RED distinguibile da un guasto "
                  "comune", ir14, kind="harness"),
    finding_entry("DR-R-15", "MEDIUM", "protezioni fissate da mutazioni",
                  ir15, kind="harness"),
]

FINDING_IDS = tuple(item["id"] for item in FINDINGS)


# --------------------------------------------------------------------------
# Esecuzione
# --------------------------------------------------------------------------


def run_one(ctx, contract):
    """Nessuna uccisione PER ECCEZIONE: una constatazione
    prodotta da un'eccezione e' contata a parte e il RED che ne derivasse non
    e' evidenza."""
    with tempfile.TemporaryDirectory(prefix="s12_dr_") as base:
        by_exception = False
        try:
            probe = contract["fn"](ctx, Path(base))
        except HarnessDefect:
            raise
        except Exception as exc:  # contata, mai nascosta
            probe = Probe(contract["id"])
            probe.findings.append(
                f"constatazione PER ECCEZIONE: {contract['observation']} — "
                f"{exc!r}")
            by_exception = True
    killed = [run for run in probe.runs if run["killed"]]
    if not probe.findings and (probe.evaluated == 0 or not killed):
        probe.findings.append(
            "GREEN VACUO: nessuna osservazione valutata o nessuna mutazione "
            "uccisa con il codice atteso")
    return {"contract": contract, "probe": probe, "red": bool(probe.findings),
            "by_exception": by_exception}


def specificity(results):
    runs = [run for result in results for run in result["probe"].runs]
    table = {}
    for result in results:
        contract = result["contract"]
        code = contract["expected_code"]
        siblings = {item["contract"]["id"] for item in results
                    if item["contract"]["expected_code"] == code}
        firing = [run for run in runs if code in run["codes"]]
        own = [run for run in firing if run["contract"] in siblings]
        table[contract["id"]] = (len(own), len(firing))
    return table


def format_line(result, spec):
    contract = result["contract"]
    probe = result["probe"]
    own, firing = spec.get(contract["id"], (0, 0))
    runs = probe.runs
    killed = sum(1 for run in runs if run["killed"])
    extra = ""
    return ("{state:<5} {cid:<12} {name:<24} fixture={fixture} | EXPECTED: "
            "{exp} | mutazione={mut} | valutate={ev} mutazioni={k}/{n} "
            "specificita'={own}/{firing}{extra} | reason={reason}".format(
                state="RED" if result["red"] else "GREEN",
                cid=contract["id"], name=contract["name"],
                fixture=contract["fixture"], exp=contract["expected_code"],
                mut=contract["mutation"], ev=probe.evaluated, k=killed,
                n=len(runs), own=own, firing=firing, extra=extra,
                reason="; ".join(probe.findings) or "-"))


def run_finding(ctx, entry):
    """Una sonda di regressione `DR-R-*`: un'eccezione e' contata a parte (`PER
    ECCEZIONE`), mai come RED causale."""
    with tempfile.TemporaryDirectory(prefix="s12_reg_") as base:
        try:
            finding = entry["fn"](ctx, Path(base))
            state = finding.state()
        except HarnessDefect:
            raise
        except Exception as exc:  # contata, mai nascosta
            finding = FindingProbe(entry["id"])
            finding.error = repr(exc)
            state = "PER-ECCEZIONE"
    _CACHE.setdefault("ir-results", {})[entry["id"]] = finding
    return {"entry": entry, "finding": finding, "state": state}


def format_finding(result):
    entry = result["entry"]
    finding = result["finding"]
    failed = [f"CONTROLLO {label}: {detail}"
              for label, ok, detail in finding.controls if not ok]
    failed += [f"ATTACCO {label}: {detail}"
               for label, ok, detail in finding.attacks if not ok]
    if finding.error:
        failed.append(f"ECCEZIONE {finding.error}")
    declared = (" | dichiarati non applicabili: " +
                "; ".join(finding.declared)) if finding.declared else ""
    return ("{head:<5} {fid} {severity:<6} [{kind}] {title} | stato={state} | "
            "controlli {cok}/{cn} | attacchi respinti {aok}/{an}{declared} | "
            "reason={reason}".format(
                head="GREEN" if result["state"] == "GREEN" else "RED",
                fid=entry["id"], severity=entry["severity"],
                kind=entry["kind"], title=entry["title"],
                state=result["state"],
                cok=sum(1 for _, ok, _ in finding.controls if ok),
                cn=len(finding.controls),
                aok=sum(1 for _, ok, _ in finding.attacks if ok),
                an=len(finding.attacks), declared=declared,
                reason="; ".join(failed) or "-"))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(
        prog="test_data_room.py", add_help=True,
        description="I 32 contratti della Data Room e le sonde di "
                    "regressione DR-R-01...15.")
    parser.add_argument("--root", required=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--contract", help="esegue un solo contratto")
    mode.add_argument("--finding", help="esegue una sola sonda DR-R-*")
    mode.add_argument("--all", action="store_true",
                      help="esegue contratti e sonde di regressione "
                           "(default)")
    parser.add_argument("--list", action="store_true",
                        help="elenca gli id dei contratti ospitati qui")
    parser.add_argument("--list-findings", action="store_true",
                        help="elenca gli id delle sonde di regressione")
    parser.add_argument("--matrix", action="store_true",
                        help="stampa la matrice di mutazione per riga e "
                             "la matrice delle regressioni")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE
    if args.list:
        for contract_id in CONTRACT_IDS:
            print(contract_id)
        return EXIT_OK
    if args.list_findings:
        for finding_id in FINDING_IDS:
            print(finding_id)
        return EXIT_OK
    try:
        root = resolve_root(args.root)
    except HarnessUsageError as exc:
        print(f"USAGE ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.contract and args.contract not in CONTRACT_IDS:
        print(f"USAGE ERROR: contratto inesistente: {args.contract}",
              file=sys.stderr)
        return EXIT_USAGE
    if args.finding and args.finding not in FINDING_IDS:
        print(f"USAGE ERROR: sonda inesistente: {args.finding}",
              file=sys.stderr)
        return EXIT_USAGE
    global XLSX, CHAPTER
    testkit_dir = str(root / TESTKIT_REL)
    if testkit_dir not in sys.path:
        sys.path.insert(0, testkit_dir)
    try:
        XLSX = load_harness(root, XLSX_HARNESS)
        XLSX.CHAPTER = XLSX.load_chapter_harness(root)
        XLSX.GATE = XLSX.load_gate(root)
        CHAPTER = XLSX.CHAPTER
        ctx = build_context(root)
        selected = [item for item in CONTRACTS
                    if not args.finding and
                    (not args.contract or item["id"] == args.contract)]
        results = [run_one(ctx, item) for item in selected]
        chosen = [item for item in FINDINGS
                  if not args.contract and
                  (not args.finding or item["id"] == args.finding)]
        findings = [run_finding(ctx, item) for item in chosen]
    except HarnessDefect as exc:
        print(f"HARNESS DEFECT: {exc}", file=sys.stderr)
        return EXIT_STATE
    finally:
        holder = _CACHE.get("holder")
        if holder is not None:
            shutil.rmtree(holder, ignore_errors=True)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    red = [result for result in results if result["red"]]
    if results:
        spec = specificity(results)
        for result in results:
            print(format_line(result, spec))
        if args.matrix:
            for result in results:
                for run in result["probe"].runs:
                    print("MATRIX {contract} {mutation:<8} {label:<46} "
                          "exit={exit} atteso={expected} ucciso={killed} "
                          "codici={codes}"
                          .format(contract=run["contract"],
                                  mutation=run["mutation"],
                                  label=run["label"],
                                  exit=run["exit_code"],
                                  expected=run["expected"],
                                  killed=run["killed"], codes=run["codes"]))
        by_exception = sum(1 for result in results if result["by_exception"])
        reasons = {"; ".join(result["probe"].findings) for result in red}
        runs = [run for result in results for run in result["probe"].runs]
        print("SUMMARY: {total} contratti, {red} RED, {green} GREEN "
              "(constatazioni DISTINTE: {distinct}/{red}; PER ECCEZIONE: "
              "{exc}; mutazioni uccise: {killed}/{nruns}; modulo {v}: {vs})"
              .format(total=len(results), red=len(red),
                      green=len(results) - len(red), distinct=len(reasons),
                      exc=by_exception,
                      killed=sum(1 for run in runs if run["killed"]),
                      nruns=len(runs), v=DR_VALIDATOR_REL,
                      vs="presente" if ctx["dr_validator"].is_file()
                      else "ASSENTE"))
    open_findings = [item for item in findings if item["state"] != "GREEN"]
    if findings:
        for result in findings:
            print(format_finding(result))
        if args.matrix:
            for result in findings:
                finding = result["finding"]
                for kind, rows in (("controllo", finding.controls),
                                   ("attacco", finding.attacks)):
                    for label, ok, detail in rows:
                        print(f"REGMATRIX {finding.finding_id} {kind:<9} "
                              f"ok={ok} | {label} | {detail}")
        states = [item["state"] for item in findings]
        controls = [ok for item in findings
                    for _, ok, _ in item["finding"].controls]
        attacks = [ok for item in findings
                   for _, ok, _ in item["finding"].attacks]
        print("SUMMARY-REG: {n} regressioni della data room "
              "| GREEN {green} | RED CAUSALI {causal} | NON "
              "DISCRIMINANTI {nd} | VACUI {vac} | PER ECCEZIONE {exc} | "
              "controlli validi {cok}/{cn} | attacchi respinti {aok}/{an}"
              .format(n=len(findings), review=REVIEW_COMMIT[:7],
                      cand=REJECTED_CANDIDATE[:7],
                      green=states.count("GREEN"),
                      causal=states.count("RED-CAUSALE"),
                      nd=states.count("NON-DISCRIMINANTE"),
                      vac=states.count("VACUO"),
                      exc=states.count("PER-ECCEZIONE"),
                      cok=sum(controls), cn=len(controls),
                      aok=sum(attacks), an=len(attacks)))
    if red or open_findings:
        return EXIT_RED
    parts = []
    if results:
        parts.append(f"{len(results)} contratti della Data Room")
    if findings:
        parts.append(f"{len(findings)} regressioni "
                     "della data room")
    print("PASS: T-DATA-ROOM " + " e ".join(parts))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
