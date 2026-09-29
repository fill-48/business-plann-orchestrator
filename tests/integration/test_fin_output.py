#!/usr/bin/env python3
"""T-FIN-OUTPUT — ventidue contratti dell'OUTPUT CANONICO dello Stage 10.

Verifica il costruttore canonico `output/build_canonical_output.py` e il
validator `validators/validate_financial_output.py`: dal payload intermedio
del motore finanziario al documento `structured-output.json` scritto nel
candidate `.working/<tx>/`. Entra nel glob di ENTRAMBI i runner
(`tests/run-tests.ps1` e `tests/run-tests.sh` globano
`tests/integration/test_*.py`).

VENTIDUE CONTRATTI OSPITATI QUI
-------------------------------
    FO-C-01  T-FIN-CANONICAL-IDEMPOTENT
    FO-C-02  T-FIN-CANONICAL-JSON            (a) schema  (b) profilo attivo
    FO-C-03  T-FIN-CANONICAL-MODULES
    FO-C-04  T-FIN-GOVERNANCE-CANONICAL
    FO-C-05  T-FIN-GOVERNANCE-SCENARIOS
    FO-C-06  T-FIN-GOVERNANCE-MINIMUM
    FO-C-07  T-FIN-GOVERNANCE-NO-NUMBERS
    FO-C-08  T-FIN-FORMULA-PROVENANCE          (stringhe di formula fedeli)
    FO-C-09  T-FIN-TIMING-SHIFT                (clipping ancorato allo start)
    FO-C-10  T-FIN-TIMING-OUT-OF-HORIZON       (finestra vuota mai silenziosa)
    FO-C-11  T-FIN-INVESTOR-READINESS          (prontezza distinta)
    FO-C-12  T-FIN-MATERIALITY-CARRIER         (nessuna soglia inventata)
    FO-C-13  T-FIN-SOURCE-TYPE-CARRIER         (enum riusato)
    FO-C-14  T-FIN-USE-OF-PROCEEDS-CANDIDATES  (categorie, mai allocazioni)
    FO-C-15  T-FIN-NO-SILENT-ASSUMPTION
    FO-C-16  T-FIN-CANONICAL-NO-RECOMPUTE     (a) scansione (b) auto-sonda
    FO-C-17  T-FIN-CANONICAL-ATOMIC-WRITE
    FO-C-18  T-FIN-CANONICAL-STALE-GUARD
    FO-C-19  T-FIN-ENGINE-CANONICAL-BOUNDARY
    FO-C-20  T-FIN-WORKFLOW-CONTRACT
    FO-C-21  T-FIN-NO-STAGE-11-ARTIFACTS      (token degli stage successivi)
    FO-C-22  T-FIN-M5A-NO-DERIVED             (a) derivati  (b) run bloccata

DISCIPLINA
----------
Ogni contratto e' INDIPENDENTE: un contratto RED riporta la PROPRIA
constatazione e il PROPRIO codice atteso. Nessun contratto fallisce per un
errore globale non pertinente.

Il registro delle fixture `F-1`...`F-13` di `bpo_testkit.py` non e' esteso da
questo modulo: le varianti usate qui sono DERIVATE IN-MODULO, come
`tests/integration/test_fin_scenarios.py` gia' costruisce in-modulo il proprio driver
`timing_like`.

SEMANTICA DEGLI EXIT CODE
-------------------------
    0   tutti i contratti soddisfatti
    1   almeno un contratto RED
    2   errore d'uso
    3   stato del repository inutilizzabile (difetto di harness)
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_REL = ".claude/skills/business-plan-orchestrator"
TESTKIT_REL = "tests/integration"
ENGINE_HARNESS = "test_fin_engine"

BUILDER_REL = f"{SKILL_REL}/output/build_canonical_output.py"
OUTPUT_VALIDATOR_REL = f"{SKILL_REL}/validators/validate_financial_output.py"
ENGINE_VALIDATOR_REL = f"{SKILL_REL}/validators/validate_financial_engine.py"
SCHEMA_REL = f"{SKILL_REL}/schemas/financial-plan.schema.json"
SOURCE_REGISTER_REL = f"{SKILL_REL}/schemas/source-register.schema.json"
ENFORCEMENT_REL = f"{SKILL_REL}/config/enforcement-config.json"
WORKFLOW_REL = f"{SKILL_REL}/workflows/11_financial-plan.md"
METHODOLOGY_REL = f"{SKILL_REL}/methodology/financial-plan.md"
RUNTIME_AGENT_REL = f"{SKILL_REL}/runtime-agents/financial-modeller.md"

#: Suite della guardia dei token di stage, eseguita su copie isolate.
WORKFLOW_TEST_REL = "tests/integration/test_stage_workflows.py"

STAGE10 = "10_financial-plan"
PROFILE_ID = "subscription_saas"
SCHEMA_VERSION = "1.1.0"

EXIT_OK = 0
EXIT_RED = 1
EXIT_USAGE = 2
EXIT_STATE = 3

#: I QUINDICI `module_id` che `results.modules` dichiara gia' `required`.
#: E' lo STESSO insieme, VERIFICATO contro lo schema, non un elenco parallelo.
MODULE_IDS = (
    "balance_sheet", "break_even", "cash_buffer", "cash_flow", "cogs",
    "funding_gap", "gross_margin", "headcount", "kpi", "milestone_coverage",
    "opex", "payroll", "pnl", "revenue", "runway",
)

#: I TRE scenari di `results.scenarios` che sono `$ref` a `scenario_result`.
#: `coverage` NON e' uno scenario: e' il blocco di MISURA della
#: copertura, con `ratio` e `threshold` NUMERICI, e non entra in `governance`.
SCENARIO_IDS = ("base", "downside", "upside")

#: Enumerazione CHIUSA di `driver_status`, dal meno al piu' confermato.
STATUS_ORDER = ("unresolved", "placeholder", "inferred", "confirmed")

#: Grammatica CHIUSA dei tre token di `affected_refs[]` per
#: `timing_window_empty`: un token DRV-*, uno module:<id>, uno scenario:<id>.
TOKEN_DRIVER_RE = re.compile(r"^DRV-(?:[0-9]{3}|[1-9][0-9]{3,})$")
TOKEN_MODULE_RE = re.compile(
    r"^module:(?:balance_sheet|break_even|cash_buffer|cash_flow|cogs|"
    r"funding_gap|gross_margin|headcount|kpi|milestone_coverage|opex|payroll|"
    r"pnl|revenue|runway)$")
TOKEN_SCENARIO_RE = re.compile(r"^scenario:(?:base|downside|upside)$")

CODE_TIMING_WINDOW_EMPTY = "timing_window_empty"
CODE_STALE = "derived_artifact_stale"

#: Le SETTE chiavi che lo Stage 11 possiede e che lo Stage 10 non produce.
STAGE11_FORBIDDEN_KEYS = ("funding_ask", "instrument", "valuation",
                          "round_size", "ownership", "dilution", "terms")

#: Le TRE omissioni DICHIARATE della mappatura payload -> canonico.
DECLARED_OMISSIONS = ("superseded", "sensitivity", "tolerance_ledger")

ENG = None  # popolato da `main` (evita import circolari a tempo di modulo)


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
    for probe in (SKILL_REL, TESTKIT_REL):
        if not (root / probe).is_dir():
            raise HarnessUsageError(
                f"--root non sembra la radice del repository: {probe} assente "
                f"sotto {root}")
    return root


def load_engine_harness(root):
    """Riusa i costruttori DICHIARATIVI di `test_fin_engine.py`.

    Nessuna duplicazione dell'ingresso del motore: questo modulo consuma il
    payload che il motore finanziario produce, e lo costruisce con il SOLO
    costruttore gia' esistente.
    """
    path = root / TESTKIT_REL / f"{ENGINE_HARNESS}.py"
    if not path.is_file():
        raise HarnessDefect(f"harness del motore assente: {path}")
    spec = importlib.util.spec_from_file_location(ENGINE_HARNESS, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[ENGINE_HARNESS] = module
    spec.loader.exec_module(module)
    return module


def read_json(root, rel):
    path = root / rel
    if not path.is_file():
        raise HarnessDefect(f"artefatto assente: {rel}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HarnessDefect(f"artefatto corrotto: {rel}: {exc}")


def build_context(root):
    eng = ENG.build_context(root)
    return {
        "root": root,
        "eng": eng,
        "schema": eng["schema"],
        "profile": eng["profile"],
        "jsonschema": eng["jsonschema"],
        "enforcement": eng["enforcement"],
        "source_register": read_json(root, SOURCE_REGISTER_REL),
        "builder": root / BUILDER_REL,
        "validator": root / OUTPUT_VALIDATOR_REL,
    }


# --------------------------------------------------------------------------
# Invocazione delle superfici di produzione
# --------------------------------------------------------------------------


MISSING_BUILDER = (
    "output/build_canonical_output.py ASSENTE: il costruttore canonico e' "
    "obbligatorio e nessun contratto dell'output canonico e' misurabile "
    "senza di esso")
MISSING_VALIDATOR = (
    "validators/validate_financial_output.py ASSENTE: il validator canonico e' "
    "obbligatorio ed e' la SEDE della validazione "
    "comportamentale del documento canonico")


def engine_run(ctx, base, rows, records, config=None, name="m5a"):
    """Esegue il motore finanziario e restituisce `(project, run)`."""
    project, _ = ENG.make_project(ctx["eng"], base, name=name)
    payload_in = ENG.engine_input(ctx["eng"], rows, records, config=config)
    run = ENG.run_engine(ctx["eng"], project, payload_in)
    if not run["available"]:
        raise HarnessDefect(f"motore non invocabile: {run['reason']}")
    if run["result"] is None:
        raise HarnessDefect(
            f"il motore non ha prodotto alcun payload (exit {run['exit_code']}): "
            f"{run['stderr'][:400]}")
    return project, run


def nominal_payload(ctx, base, name="m5a-nominal", **over):
    """Payload NOMINALE a copertura di scenario PIENA (forma della `F-1`)."""
    records = ENG.triplet_records(ctx["eng"], **over)
    rows = ENG.base_rows(ctx["eng"], records)
    _, run = engine_run(ctx, base, rows, records, name=name)
    return run["result"]


def write_payload(base, payload, name="engine-payload.json"):
    path = Path(base) / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True,
                               sort_keys=True) + "\n", encoding="utf-8")
    return path


def run_builder(ctx, payload_path, project, tx="tx-fo-001", extra=()):
    """Invoca il COSTRUTTORE canonico DICHIARATO e restituisce l'esito."""
    builder = ctx["builder"]
    if not builder.is_file():
        return {"available": False, "reason": MISSING_BUILDER,
                "exit_code": None, "report": None, "stdout": "", "stderr": ""}
    command = [sys.executable, str(builder),
               "--engine-payload", str(payload_path),
               "--project", str(project), "--tx", tx]
    command.extend(extra)
    proc = subprocess.run(command, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          cwd=str(ctx["root"]),
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    report = None
    if proc.stdout.strip().startswith("{"):
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            report = None
    return {"available": True, "reason": "", "exit_code": proc.returncode,
            "report": report, "stdout": proc.stdout, "stderr": proc.stderr,
            "command": " ".join(command)}


def candidate_dir(project, tx="tx-fo-001"):
    return Path(project) / STAGE10 / ".working" / tx


def canonical_path(project, tx="tx-fo-001"):
    return candidate_dir(project, tx) / "structured-output.json"


def run_output_validator(ctx, project, canonical, tx="tx-fo-001",
                         payload_path=None, phase="egress"):
    """Invoca il VALIDATOR CANONICO DI PRODUZIONE, mai una copia."""
    validator = ctx["validator"]
    if not validator.is_file():
        return {"available": False, "reason": MISSING_VALIDATOR,
                "exit_code": None, "report": None, "codes": set(),
                "stdout": "", "stderr": ""}
    command = [sys.executable, str(validator),
               "--project", str(project), "--stage", STAGE10,
               "--phase", phase,
               "--candidate", str(candidate_dir(project, tx)),
               "--canonical", str(canonical)]
    if payload_path is not None:
        command.extend(["--engine-payload", str(payload_path)])
    proc = subprocess.run(command, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          cwd=str(ctx["root"]),
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    report = None
    if proc.stdout.strip().startswith("{"):
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            report = None
    codes = set()
    refs_by_code = {}
    if report:
        for entry in report.get("errors") or ():
            codes.add(entry.get("code"))
            refs_by_code.setdefault(entry.get("code"), []).append(
                entry.get("ref"))
    return {"available": True, "reason": "", "exit_code": proc.returncode,
            "report": report, "codes": {c for c in codes if c},
            "refs_by_code": refs_by_code,
            "stdout": proc.stdout, "stderr": proc.stderr,
            "command": " ".join(command)}


def fixture_project(ctx, base, name):
    """Progetto TEMPORANEO di fixture, mai un progetto REALE.

    Il progetto porta `shared/` completo, che e' cio' che `fw.ProjectState`
    esige: un albero nudo non e' un progetto e il validator lo respingerebbe
    per una ragione NON PERTINENTE al contratto.
    """
    slug = name
    index = 0
    while (Path(base) / slug).exists():
        index += 1
        slug = f"{name}-{index}"
    project, _ = ctx["eng"]["testkit"].make_stage10_fixture_project(
        Path(base), "F-12", name=slug)
    return project


def build_and_validate(ctx, base, payload, name="proj", tx="tx-fo-001",
                       validate=True):
    """Costruisce il canonico e, se richiesto, lo valida. Ritorna un contesto."""
    project = fixture_project(ctx, base, name)
    payload_path = write_payload(base, payload, name=f"{name}-payload.json")
    built = run_builder(ctx, payload_path, project, tx=tx)
    document = None
    target = canonical_path(project, tx)
    if target.is_file():
        try:
            document = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HarnessDefect(f"canonico non e' JSON: {exc}")
    validated = None
    if validate:
        validated = run_output_validator(ctx, project, target, tx=tx,
                                         payload_path=payload_path)
    return {"project": project, "payload_path": payload_path, "built": built,
            "document": document, "target": target, "validated": validated}


def unavailable(ctx_run, findings):
    """Registra la constatazione di superficie ASSENTE e ritorna True."""
    if not ctx_run.get("available", True):
        findings.append(ctx_run["reason"])
        return True
    return False


def not_built(case, findings):
    """`True` quando il canonico NON e' stato prodotto, con la PROPRIA
    constatazione registrata: nessun contratto e' GREEN per silenzio."""
    if unavailable(case["built"], findings):
        return True
    if case["document"] is None:
        findings.append(
            f"nessun documento canonico prodotto (exit "
            f"{case['built'].get('exit_code')}): "
            f"{(case['built'].get('stderr') or '')[:300]}")
        return True
    return False


def plan_of(document):
    return (document or {}).get("financial_plan") or {}


def modules_of(document):
    return ((plan_of(document).get("results") or {}).get("modules")) or {}


def governance_of(document):
    return plan_of(document).get("governance") or {}


def validation_of(document):
    return plan_of(document).get("validation") or {}


def drivers_of(document):
    return ((plan_of(document).get("driver_registry") or {}).get("drivers")
            or [])


def validate_document(ctx, document, findings, label="canonico"):
    """Valida il documento contro lo schema INTERO (radice compresa)."""
    validator = ctx["jsonschema"].Draft202012Validator(ctx["schema"])
    for error in sorted(validator.iter_errors(document),
                        key=lambda err: list(map(str, err.absolute_path))):
        path = "/".join(map(str, error.absolute_path)) or "(radice)"
        findings.append(f"{label}: {path}: {error.message}")


def schema_rejects(ctx, document):
    """`True` se lo schema INTERO respinge il documento."""
    validator = ctx["jsonschema"].Draft202012Validator(ctx["schema"])
    return bool(list(validator.iter_errors(document)))


def deep_numbers(node, path="governance"):
    """Ogni valore NUMERICO raggiungibile, col PROPRIO path."""
    found = []
    if isinstance(node, bool):
        return found
    if isinstance(node, (int, float)):
        found.append((path, node))
    elif isinstance(node, dict):
        for key in sorted(node):
            found.extend(deep_numbers(node[key], f"{path}.{key}"))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(deep_numbers(item, f"{path}[{index}]"))
    return found


def deep_keys(node, path="", acc=None):
    acc = [] if acc is None else acc
    if isinstance(node, dict):
        for key in sorted(node):
            acc.append((f"{path}.{key}" if path else key, key))
            deep_keys(node[key], f"{path}.{key}" if path else key, acc)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            deep_keys(item, f"{path}[{index}]", acc)
    return acc


def sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_digest(root, skip=(".git", "__pycache__")):
    """Impronta dell'albero: usata per PROVARE il ripristino byte per byte."""
    entries = []
    for path in sorted(Path(root).rglob("*")):
        if any(part in skip for part in path.parts):
            continue
        if path.is_file():
            entries.append(f"{path.relative_to(root).as_posix()}:"
                           f"{hashlib.sha256(path.read_bytes()).hexdigest()}")
    return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()


def repo_mirror(root, dest):
    """Copia ISOLATA del repository, FUORI dal repository stesso."""
    shutil.copytree(root, dest, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", "*.pyc", "generated"))
    return Path(dest)


def run_module(root, rel, *args):
    proc = subprocess.run(
        [sys.executable, str(Path(root) / rel), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(root), env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return proc


def load_production_module(ctx, rel, name):
    path = ctx["root"] / rel
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - superficie in costruzione
        raise HarnessDefect(f"modulo di produzione non importabile: {rel}: "
                            f"{exc}")
    return module


# --------------------------------------------------------------------------
# Varianti DERIVATE IN-MODULO — il registro F-1...F-13 resta CHIUSO
# --------------------------------------------------------------------------


def timing_rows(ctx, records, horizon=12, start=2, end=3, triplet=("0", "2",
                                                                   "9")):
    """`F-1` con un driver `timing_like` DERIVATO IN-MODULO.

    Nessuna fixture del registro porta un driver `timing_like`: la variante e'
    costruita QUI, esattamente come `tests/integration/test_fin_scenarios.py` costruisce
    in-modulo il proprio.
    """
    low, mid, high = triplet
    # La terna e' DICHIARATA sul record PRIMA che la riga ne calcoli il
    # `source_record_hash`: dichiararla dopo produrrebbe `driver_source_stale`
    # e il contratto fallirebbe per una ragione NON PERTINENTE.
    ENG.with_triplet(records, "ASS-007", low, mid, high)
    rows = ENG.base_rows(ctx["eng"], records, horizon=horizon)
    for entry in rows:
        if entry["role"] == "opex":
            entry["scenario_polarity"] = "timing_like"
            entry["start_period"] = start
            entry["end_period"] = end
    return rows


def placeholder_optional_rows(ctx, records, horizon=12):
    """`F-1` piu' un input OPZIONALE CONSUMATO in stato `placeholder`.

    Serve a `FO-C-06`: il minimo di piano si prende su TUTTI gli input
    consumati, richiesti E opzionali. Il ruolo `cash_buffer` e' OPZIONALE nel
    profilo `subscription_saas`.
    """
    rows = ENG.base_rows(ctx["eng"], records, horizon=horizon)
    rows.append(ENG.row(
        ctx["eng"], "DRV-009", "cash_buffer", "ASS-009", "EUR", "stock",
        "monthly", "carry_level", "constant", records, start_period=0,
        end_period=horizon - 1, status="placeholder",
        scenario_polarity="neutral"))
    return rows


def with_cash_buffer_record(ctx, records, value="20000"):
    entry = ENG.record(ctx["eng"]["testkit"], 9, float(value), "EUR",
                       category="finance")
    records[entry["id"]] = entry
    return records


def blocked_payload(ctx, base, name="m5a-blocked"):
    """Payload di RUN BLOCCATA: politica di conversione NON ammessa.

    E' la variante INVALIDA di `F-11`, DERIVATA IN-MODULO: il motore fallisce
    CHIUSO, `results.modules` resta vuoto e il `driver_registry` porta il valore
    VERBATIM, non valido per lo schema. Il costruttore deve RIFIUTARLO.
    """
    records = ENG.triplet_records(ctx["eng"])
    rows = ENG.base_rows(ctx["eng"], records)
    for entry in rows:
        if entry["role"] == "opex":
            entry["conversion_policy"] = "totally_invented_policy"
    _, run = engine_run(ctx, base, rows, records, name=name)
    return run["result"]


def no_coverage_payload(ctx, base, name="m5a-none"):
    """Copertura di scenario NULLA (forma della `F-3`): Downside e Upside sono
    `NOT_APPLICABLE` DICHIARATI, mai omessi e mai etichettati."""
    records = ENG.base_records(ctx["eng"])
    rows = ENG.base_rows(ctx["eng"], records)
    _, run = engine_run(ctx, base, rows, records, name=name)
    return run["result"]


# --------------------------------------------------------------------------
# I ventidue contratti
# --------------------------------------------------------------------------


def c01(ctx, base):
    """`FO-C-01` `T-FIN-CANONICAL-IDEMPOTENT` — stesso payload, BYTE
    IDENTICI; la riesecuzione non produce alcun effetto collaterale."""
    findings = []
    payload = nominal_payload(ctx, base, name="c01")
    first = build_and_validate(ctx, base, payload, name="c01", validate=False)
    if unavailable(first["built"], findings):
        return findings
    if first["built"]["exit_code"] != 0:
        findings.append(
            f"prima costruzione fallita (exit {first['built']['exit_code']}): "
            f"{first['built']['stderr'][:300]}")
        return findings
    digest_one = sha256_of(first["target"])
    second = run_builder(ctx, first["payload_path"], first["project"])
    if second["exit_code"] != 0:
        findings.append(
            f"riesecuzione fallita (exit {second['exit_code']}): non e' "
            "idempotente")
        return findings
    digest_two = sha256_of(first["target"])
    if digest_one != digest_two:
        findings.append(
            f"due costruzioni dallo stesso payload NON sono byte-identiche: "
            f"{digest_one} != {digest_two}")
    # Nessun campo non deterministico: ne' orologio, ne' path assoluto, ne'
    # identificatore casuale.
    text = first["target"].read_text(encoding="utf-8")
    for marker, label in ((str(first["project"]).replace("\\", "\\\\"),
                           "path assoluto del progetto"),
                          ("generated_at", "timestamp di generazione"),
                          ("built_at", "timestamp di costruzione")):
        if marker and marker in text:
            findings.append(
                f"il documento porta un campo NON DETERMINISTICO ({label}): "
                "due esecuzioni in contesti diversi divergerebbero")
    # `drivers[]` ORDINATO per `driver_id`.
    ids = [entry.get("driver_id") for entry in drivers_of(first["document"])]
    if ids != sorted(ids):
        findings.append(
            f"drivers[] non e' ordinato per driver_id: {ids} — l'ordine "
            "dipende dall'iterazione e non dal contratto")
    return findings


def c02(ctx, base):
    """`FO-C-02` `T-FIN-CANONICAL-JSON` — (a) validita' di SCHEMA;
    (b) validita' rispetto al PROFILO ATTIVO."""
    findings = []
    payload = nominal_payload(ctx, base, name="c02")
    case = build_and_validate(ctx, base, payload, name="c02")
    if unavailable(case["built"], findings):
        return findings
    if case["document"] is None:
        findings.append("nessun documento canonico prodotto")
        return findings
    # (a) — radice, cinque sezioni piu' `governance`.
    validate_document(ctx, case["document"], findings)
    if case["document"].get("schema_version") != SCHEMA_VERSION:
        findings.append(
            f"schema_version {case['document'].get('schema_version')!r} "
            f"invece di {SCHEMA_VERSION!r} (versione di schema attesa)")
    for section in ("driver_registry", "results", "reconciliations",
                    "validation", "calculation_metadata", "governance"):
        if section not in plan_of(case["document"]):
            findings.append(f"(a) sezione canonica assente: {section}")
    # (a) RED — chiave extra alla radice, e `governance` assente.
    extra = copy.deepcopy(case["document"])
    extra["unexpected_root_key"] = True
    if not schema_rejects(ctx, extra):
        findings.append(
            "(a) una chiave EXTRA alla radice non e' respinta dallo schema: "
            "la radice non e' chiusa")
    without = copy.deepcopy(case["document"])
    without["financial_plan"].pop("governance", None)
    if not schema_rejects(ctx, without):
        findings.append(
            "(a) `governance` ASSENTE non e' respinta: financial_plan.required "
            "non ha acquisito \"governance\" (D4)")
    # (b) — profilo attivo.
    if unavailable(case["validated"], findings):
        return findings
    if case["validated"]["exit_code"] != 0:
        findings.append(
            f"(b) il canonico NOMINALE e' respinto dal validator di "
            f"produzione (exit {case['validated']['exit_code']}, codici "
            f"{sorted(case['validated']['codes'])})")
    profile = ctx["profile"]
    for module_id in profile.get("not_applicable_modules") or ():
        entry = modules_of(case["document"]).get(module_id) or {}
        if entry.get("status") != "NOT_APPLICABLE":
            findings.append(
                f"(b) {module_id} e' dichiarato in not_applicable_modules del "
                f"profilo {profile.get('profile_id')} ma il canonico lo "
                f"pubblica con status {entry.get('status')!r}")
        if not (entry.get("reason") or entry.get("not_applicable_reason")):
            findings.append(
                f"(b) {module_id}: NOT_APPLICABLE senza motivazione NOMINATA")
    # (b) RED — un modulo di `not_applicable_modules` pubblicato `PASS`.
    mutated = copy.deepcopy(case["document"])
    target = (profile.get("not_applicable_modules") or ["balance_sheet"])[0]
    mutated["financial_plan"]["results"]["modules"][target] = {
        "module_id": target, "status": "PASS"}
    probe = probe_document(ctx, base, mutated, name="c02b")
    if probe["exit_code"] == 0:
        findings.append(
            f"(b) un modulo di not_applicable_modules ({target}) pubblicato "
            "con status PASS e' ACCETTATO dal validator di produzione")
    elif not any(target in str(ref) for refs in probe["refs_by_code"].values()
                 for ref in refs):
        findings.append(
            f"(b) il rifiuto non NOMINA il module_id non conforme al profilo "
            f"({target}): {probe['refs_by_code']}")
    # (b) RED — un ruolo richiesto NON risolto e ASSENTE da
    # `unbound_required_roles[]`.
    unbound = copy.deepcopy(case["document"])
    registry = unbound["financial_plan"]["driver_registry"]
    victim = None
    for entry in registry["drivers"]:
        if entry.get("role") in (profile.get("required_driver_roles") or ()):
            victim = entry
            break
    if victim is None:
        findings.append("(b) nessun driver di ruolo RICHIESTO nel canonico")
    else:
        registry["drivers"] = [e for e in registry["drivers"]
                               if e is not victim]
        registry["unbound_required_roles"] = []
        probe2 = probe_document(ctx, base, unbound, name="c02c")
        if probe2["exit_code"] == 0:
            findings.append(
                f"(b) il ruolo richiesto {victim['role']!r} non risolto e "
                "ASSENTE da unbound_required_roles[] e' accettato in silenzio")
        elif not any(victim["role"] in str(ref)
                     for refs in probe2["refs_by_code"].values()
                     for ref in refs):
            findings.append(
                f"(b) il rifiuto non NOMINA il ruolo non conforme al profilo "
                f"({victim['role']}): {probe2['refs_by_code']}")
    return findings


def probe_document(ctx, base, document, name="probe", tx="tx-fo-001"):
    """Sonda NEGATIVA DIRETTA sul VALIDATOR DI PRODUZIONE.

    Il documento MUTATO e' scritto in un progetto TEMPORANEO, mai in un
    progetto reale, e il validator invocato e' quello di produzione, mai una
    copia.
    """
    project = fixture_project(ctx, base, f"probe-{name}")
    target = canonical_path(project, tx)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2, ensure_ascii=True,
                                 sort_keys=True) + "\n", encoding="utf-8")
    return run_output_validator(ctx, project, target, tx=tx)


def c03(ctx, base):
    """`FO-C-03` `T-FIN-CANONICAL-MODULES` — ogni modulo prodotto e ogni
    scenario prodotto compaiono UNA VOLTA SOLA."""
    findings = []
    payload = nominal_payload(ctx, base, name="c03")
    case = build_and_validate(ctx, base, payload, name="c03")
    if unavailable(case["built"], findings):
        return findings
    if case["document"] is None:
        findings.append("nessun documento canonico prodotto")
        return findings
    modules = modules_of(case["document"])
    missing = sorted(set(MODULE_IDS) - set(modules))
    if missing:
        findings.append(f"moduli assenti dal canonico: {missing}")
    unknown = sorted(set(modules) - set(MODULE_IDS))
    if unknown:
        findings.append(f"moduli SCONOSCIUTI nel canonico: {unknown}")
    engine_modules = ((payload.get("financial_payload") or {})
                      .get("results") or {}).get("modules") or {}
    for module_id, entry in sorted(engine_modules.items()):
        if module_id == "calendar":
            continue
        if module_id not in modules:
            findings.append(
                f"il modulo PRODOTTO dal motore {module_id} non compare nel "
                "canonico")
            continue
        if modules[module_id].get("status") != entry.get("status"):
            findings.append(
                f"{module_id}: status {modules[module_id].get('status')!r} nel "
                f"canonico contro {entry.get('status')!r} nel payload")
    scenarios = ((plan_of(case["document"]).get("results") or {})
                 .get("scenarios")) or {}
    for scenario_id in SCENARIO_IDS:
        if scenario_id not in scenarios:
            findings.append(f"scenario assente dal canonico: {scenario_id}")
    if "coverage" not in scenarios:
        findings.append("results.scenarios.coverage assente dal canonico")
    # RED — un modulo OMESSO e' respinto dal validator di produzione.
    mutated = copy.deepcopy(case["document"])
    mutated["financial_plan"]["results"]["modules"].pop("revenue", None)
    probe = probe_document(ctx, base, mutated, name="c03")
    if probe["exit_code"] == 0:
        findings.append(
            "un modulo OMESSO dal canonico e' accettato: il validator non "
            "misura la completezza")
    elif not any("revenue" in str(ref)
                 for refs in probe["refs_by_code"].values() for ref in refs):
        findings.append(
            f"il rifiuto non NOMINA il module_id omesso: {probe['refs_by_code']}")
    return findings


def c04(ctx, base):
    """`FO-C-04` `T-FIN-GOVERNANCE-CANONICAL` — `governance.modules` nella
    CODIFICA ESATTA dello schema: mappa FINITA e CHIUSA."""
    findings = []
    schema = ctx["schema"]
    node = ((schema.get("properties") or {}).get("financial_plan") or {})
    governance = ((node.get("properties") or {}).get("governance"))
    if not isinstance(governance, dict):
        findings.append(
            "financial_plan.governance ASSENTE dallo schema: D4 non e' "
            "applicata")
        return findings
    if governance.get("additionalProperties") is not False:
        findings.append("governance: additionalProperties non e' false")
    if sorted(governance.get("required") or ()) != ["modules", "plan",
                                                    "scenarios"]:
        findings.append(
            f"governance.required {governance.get('required')} invece di "
            "[plan, modules, scenarios]")
    if "governance" not in (node.get("required") or ()):
        findings.append(
            "financial_plan.required non ha acquisito \"governance\"")
    modules_node = (governance.get("properties") or {}).get("modules") or {}
    declared = sorted((modules_node.get("properties") or {}))
    if declared != sorted(MODULE_IDS):
        findings.append(
            f"governance.modules dichiara {len(declared)} properties "
            f"({declared}) invece delle QUINDICI di results.modules")
    if sorted(modules_node.get("required") or ()) != sorted(MODULE_IDS):
        findings.append(
            "governance.modules.required non elenca tutte e quindici le chiavi")
    if modules_node.get("additionalProperties") is not False:
        findings.append("governance.modules: additionalProperties non e' false")
    refs = {json.dumps(value, sort_keys=True)
            for value in (modules_node.get("properties") or {}).values()}
    if refs != {json.dumps({"$ref": "#/$defs/governance_module_entry"},
                           sort_keys=True)}:
        findings.append(
            "governance.modules non usa UNA SOLA definizione condivisa "
            "#/$defs/governance_module_entry: sono quindici copie")
    # `check_schema` verde sullo schema INTERO.
    try:
        ctx["jsonschema"].Draft202012Validator.check_schema(schema)
    except Exception as exc:  # pragma: no cover - difetto di schema
        findings.append(f"check_schema RIFIUTA lo schema aggiornato: {exc}")
    payload = nominal_payload(ctx, base, name="c04")
    case = build_and_validate(ctx, base, payload, name="c04")
    if not_built(case, findings):
        return findings
    entries = (governance_of(case["document"]).get("modules")) or {}
    if sorted(entries) != sorted(MODULE_IDS):
        findings.append(
            f"governance.modules del canonico porta {sorted(entries)} invece "
            "delle quindici voci")
    for module_id, entry in sorted(entries.items()):
        if entry.get("status") == "NOT_APPLICABLE" and not \
                entry.get("not_applicable_reason"):
            findings.append(
                f"governance.modules.{module_id}: NOT_APPLICABLE senza "
                "not_applicable_reason NOMINATA")
    # RED — voce OMESSA e chiave SCONOSCIUTA.
    omitted = copy.deepcopy(case["document"])
    omitted["financial_plan"]["governance"]["modules"].pop("payroll", None)
    if not schema_rejects(ctx, omitted):
        findings.append(
            "governance.modules PRIVA di payroll non e' respinta: la mappa non "
            "e' `required` su tutte e quindici le chiavi")
    unknown = copy.deepcopy(case["document"])
    unknown["financial_plan"]["governance"]["modules"]["not_a_module"] = {
        "propagated_status": "confirmed", "status": "PASS"}
    if not schema_rejects(ctx, unknown):
        findings.append(
            "una chiave di modulo SCONOSCIUTA e' accettata: "
            "additionalProperties non chiude la mappa")
    return findings


def c05(ctx, base):
    """`FO-C-05` `T-FIN-GOVERNANCE-SCENARIOS` — uno stato SEPARATO per ogni
    scenario, calcolato sul PROPRIO set risolto."""
    findings = []
    payload = nominal_payload(ctx, base, name="c05")
    case = build_and_validate(ctx, base, payload, name="c05")
    if not_built(case, findings):
        return findings
    scenarios = governance_of(case["document"]).get("scenarios") or {}
    if sorted(scenarios) != sorted(SCENARIO_IDS):
        findings.append(
            f"governance.scenarios porta {sorted(scenarios)} invece di "
            f"{sorted(SCENARIO_IDS)}")
    # `coverage` NON e' uno scenario e non entra in governance.
    if "coverage" in scenarios:
        findings.append(
            "governance.scenarios porta la chiave `coverage`: `coverage` NON "
            "e' uno scenario e i suoi `ratio`/`threshold` sono NUMERICI")
    projection = (payload.get("governance_projection") or {}).get("scenarios") \
        or {}
    for scenario_id in SCENARIO_IDS:
        entry = scenarios.get(scenario_id) or {}
        own = projection.get(scenario_id) or {}
        if own and entry.get("driver_refs") != sorted(own.get("driver_refs")
                                                      or []):
            findings.append(
                f"governance.scenarios.{scenario_id}: driver_refs "
                f"{entry.get('driver_refs')} diversi dal set risolto PROPRIO "
                f"{sorted(own.get('driver_refs') or [])}")
        if own and entry.get("propagated_status") != \
                own.get("propagated_status"):
            findings.append(
                f"governance.scenarios.{scenario_id}: propagated_status "
                f"{entry.get('propagated_status')!r} diverso da quello "
                f"calcolato sul PROPRIO set {own.get('propagated_status')!r}")
    # Copertura NULLA — Downside e Upside NOT_APPLICABLE DICHIARATI. E' la
    # fixture `F-3` che il contratto NOMINA accanto a `F-1`, ed e' la SOLA su
    # cui gli stati dei tre scenari sono DAVVERO DIVERSI: su `F-1` i tre
    # scenari consumano lo stesso insieme di driver e una copia sarebbe
    # indistinguibile dall'originale ANCHE per un controllo corretto. La sonda
    # negativa vive quindi qui, dove e' DISCRIMINANTE.
    none_payload = no_coverage_payload(ctx, base, name="c05-none")
    none_case = build_and_validate(ctx, base, none_payload, name="c05none",
                                   validate=False)
    if none_case["document"] is None:
        findings.append(
            "nessun canonico prodotto a copertura NULLA: il caso di frontiera "
            "non e' misurabile")
        return findings
    none_scen = governance_of(none_case["document"]).get("scenarios") or {}
    for scenario_id in ("downside", "upside"):
        entry = none_scen.get(scenario_id) or {}
        if entry.get("status") != "NOT_APPLICABLE":
            findings.append(
                f"con copertura NULLA governance.scenarios.{scenario_id} "
                f"porta status {entry.get('status')!r} invece di "
                "NOT_APPLICABLE DICHIARATO")
        elif not entry.get("not_applicable_reason"):
            findings.append(
                f"governance.scenarios.{scenario_id}: NOT_APPLICABLE "
                "senza motivazione NOMINATA")
    # RED — lo stato di `downside` COPIATO da `base`.
    mutated = copy.deepcopy(none_case["document"])
    block = mutated["financial_plan"]["governance"]["scenarios"]
    block["downside"] = copy.deepcopy(block["base"])
    probe = probe_document(ctx, base, mutated, name="c05")
    if probe["exit_code"] == 0:
        findings.append(
            "lo stato di downside COPIATO da base e' accettato: nessun "
            "controllo misura che ogni scenario porti il PROPRIO stato")
    elif not any("downside" in str(ref)
                 for refs in probe["refs_by_code"].values() for ref in refs):
        findings.append(
            f"il rifiuto non NOMINA lo scenario col valore preso in prestito: "
            f"{probe['refs_by_code']}")
    return findings


def c06(ctx, base):
    """`FO-C-06` `T-FIN-GOVERNANCE-MINIMUM` — il minimo di piano si prende
    su TUTTI gli input consumati, RICHIESTI E OPZIONALI."""
    findings = []
    records = ENG.triplet_records(ctx["eng"])
    with_cash_buffer_record(ctx, records)
    rows = placeholder_optional_rows(ctx, records)
    _, run = engine_run(ctx, base, rows, records, name="c06")
    payload = run["result"]
    case = build_and_validate(ctx, base, payload, name="c06")
    if not_built(case, findings):
        return findings
    plan = governance_of(case["document"]).get("plan") or {}
    validation = validation_of(case["document"])
    if plan.get("propagated_status") != validation.get("propagated_status"):
        findings.append(
            f"governance.plan.propagated_status "
            f"{plan.get('propagated_status')!r} NON coincide con "
            f"validation.propagated_status "
            f"{validation.get('propagated_status')!r}: i due stati devono coincidere")
    statuses = {entry["driver_id"]: entry.get("status")
                for entry in drivers_of(case["document"])}
    optional = [drv for drv, status in sorted(statuses.items())
                if status == "placeholder"]
    if not optional:
        findings.append(
            "la variante DERIVATA IN-MODULO non porta alcun input opzionale "
            "consumato in stato placeholder: il contratto sarebbe vacuo")
    elif plan.get("propagated_status") != "placeholder":
        findings.append(
            f"il minimo di piano e' {plan.get('propagated_status')!r} mentre "
            f"gli input OPZIONALI consumati {optional} sono placeholder: il "
            "minimo e' preso sui soli RICHIESTI")
    # RED — il minimo che ESCLUDE l'opzionale consumato e' respinto.
    mutated = copy.deepcopy(case["document"])
    mutated["financial_plan"]["governance"]["plan"]["propagated_status"] = \
        "inferred"
    probe = probe_document(ctx, base, mutated, name="c06")
    if probe["exit_code"] == 0:
        findings.append(
            "un minimo di piano che ESCLUDE gli input opzionali consumati e' "
            "accettato in silenzio")
    elif not any(any(drv in str(ref) for drv in optional)
                 for refs in probe["refs_by_code"].values() for ref in refs):
        findings.append(
            f"il rifiuto non NOMINA il DRV-* opzionale escluso: "
            f"{probe['refs_by_code']}")
    return findings


def c07(ctx, base):
    """`FO-C-07` `T-FIN-GOVERNANCE-NO-NUMBERS` — nessun valore finanziario
    nella sezione di governance (`D-04`)."""
    findings = []
    payload = nominal_payload(ctx, base, name="c07")
    case = build_and_validate(ctx, base, payload, name="c07")
    if not_built(case, findings):
        return findings
    numbers = deep_numbers(governance_of(case["document"]))
    if numbers:
        findings.append(
            f"la sezione di governance del canonico porta valori NUMERICI: "
            f"{numbers}")
    # Fronte STRUTTURALE — nessun tipo numerico raggiungibile dallo schema.
    governance_schema = ((((ctx["schema"].get("properties") or {})
                           .get("financial_plan") or {}).get("properties")
                          or {}).get("governance"))
    forbidden = []
    for path, key in deep_keys(governance_schema or {}):
        if key == "type" and str(path).endswith(".type"):
            continue
    for text in json.dumps(governance_schema or {}).split(","):
        for token in ("\"number\"", "\"integer\"", "$defs/amount",
                      "$defs/period_series", "$defs/period_index",
                      "$defs/sha256"):
            if token in text:
                forbidden.append(token)
    if forbidden:
        findings.append(
            f"lo schema di governance dichiara tipi NUMERICI: "
            f"{sorted(set(forbidden))}")
    # Fronte COMPORTAMENTALE — DUE payload di sonda con un numero iniettato
    # in governance, uno alla volta, sul VALIDATOR DI PRODUZIONE.
    probes = (
        ("governance.modules.revenue.revenue_total",
         lambda doc: doc["financial_plan"]["governance"]["modules"]["revenue"]
         .__setitem__("revenue_total", "123456.78")),
        ("governance.plan.cash_balance",
         lambda doc: doc["financial_plan"]["governance"]["plan"]
         .__setitem__("cash_balance", 999999)),
    )
    for index, (path, inject) in enumerate(probes):
        mutated = copy.deepcopy(case["document"])
        inject(mutated)
        probe = probe_document(ctx, base, mutated, name=f"c07-{index}")
        if probe["exit_code"] == 0:
            findings.append(
                f"il validator DI PRODUZIONE accetta in silenzio il numero "
                f"iniettato in {path}: il presidio e' solo dichiarativo")
        elif not any(path.split(".")[-1] in str(ref)
                     for refs in probe["refs_by_code"].values()
                     for ref in refs):
            findings.append(
                f"il rifiuto non NOMINA il path iniettato {path}: "
                f"{probe['refs_by_code']}")
    return findings


def c08(ctx, base):
    """`FO-C-08` `T-FIN-FORMULA-PROVENANCE` — nessuna stringa di formula
    FUORVIANTE fra le tre classi pubblicate."""
    findings = []
    payload = nominal_payload(ctx, base, name="c08")
    recon = ((payload.get("financial_payload") or {})
             .get("reconciliations")) or {}
    rec03 = recon.get("REC-03") or {}
    formula = rec03.get("formula") or ""
    if not formula:
        findings.append("REC-03 senza stringa di formula")
    if formula.strip() == "Sigma (FTE x costo unitario) = payroll":
        findings.append(
            "REC-03: la stringa di formula e' l'IDENTITA' VERA PER "
            "COSTRUZIONE `Sigma (FTE x costo unitario) = payroll`, non cio' "
            "che il residuo misura (il payroll NON CATEGORIZZATO)")
    if "non categorizzat" not in formula.lower():
        findings.append(
            f"REC-03: la formula {formula!r} non descrive il payroll NON "
            "CATEGORIZZATO che il residuo misura")
    if not (rec03.get("residual_breakdown") or {}):
        findings.append("REC-03: il residuo non e' ripartito PER RUOLO")
    rec05 = recon.get("REC-05") or {}
    if rec05.get("expected") is None or rec05.get("actual") is None:
        findings.append("REC-05: expected/actual assenti")
    if "opening" not in (rec05.get("formula") or ""):
        findings.append(
            f"REC-05: la formula {rec05.get('formula')!r} non nomina le due "
            "grandezze confrontate")
    # Il criterio «expected != actual in REC-05». La disuguaglianza
    # NUMERICA e' osservabile SOLO dove l'identita' non chiude: quando il
    # roll-forward chiude ESATTAMENTE — che e' il caso della fixture nominale —
    # le DUE grandezze davvero confrontate SONO uguali, e l'uguaglianza e'
    # l'osservazione CORRETTA, non il difetto. Il criterio e' quindi misurato
    # nella sola forma in cui e' vero, su DUE fronti:
    #
    #   (i)  COMPORTAMENTALE — l'uguaglianza e' AMMESSA solo se GIUSTIFICATA da
    #        un residuo NULLO; con residuo non nullo le due grandezze DEVONO
    #        divergere. Sotto il codice difettoso, che poneva ENTRAMBI i campi
    #        a `sum(ending)`, coincidevano SEMPRE — anche con residuo non nullo;
    #   (ii) STRUTTURALE — nel sorgente del motore i due argomenti sono
    #        ESPRESSIONI DIVERSE, e `expected` NON e' piu' derivato da `ending`.
    #        E' la stessa disciplina, con FILE e RIGA, del contratto
    #        `FE-C-31`, e la mutazione `MUT-3-08` la uccide.
    #
    # Il criterio e' quindi verificato nella sua sola forma vera, non nella
    # formulazione letterale «expected != actual».
    coincide = str(rec05.get("expected")) == str(rec05.get("actual"))
    if coincide and rec05.get("status") != "PASS":
        findings.append(
            f"REC-05: expected e actual coincidono ({rec05.get('expected')!r}) "
            f"mentre lo stato e' {rec05.get('status')!r}, cioe' il residuo "
            f"{rec05.get('residual')!r} eccede la tolleranza "
            f"{rec05.get('tolerance')!r}: sono la STESSA grandezza e non "
            "portano informazione"
        )
    source = (ctx["root"] / ENGINE_VALIDATOR_REL).read_text(encoding="utf-8")
    body = source.split("def cash_reconciliation(")
    if len(body) < 2:
        findings.append(
            "cash_reconciliation assente da validate_financial_engine.py")
    else:
        block = body[1].split("\ndef ")[0]
        offset = source.split("def cash_reconciliation(")[0].count("\n")
        if "expected=amount(sum(ending, ZERO))" in block:
            findings.append(
                f"{ENGINE_VALIDATOR_REL}:{offset}: REC-05 deriva `expected` "
                "da `sum(ending)`, cioe' dalla STESSA grandezza di `actual`: "
                "i due campi non portano informazione")
        if "expected=amount(bridge_total)" not in block:
            findings.append(
                f"{ENGINE_VALIDATOR_REL}:{offset}: REC-05 non deriva "
                "`expected` dal ponte `opening + cash_in - cash_out`")
    # Le tre classi di stringa pubblicate dal CANONICO.
    case = build_and_validate(ctx, base, payload, name="c08", validate=False)
    if not_built(case, findings):
        return findings
    canonical_recon = plan_of(case["document"]).get("reconciliations") or {}
    if (canonical_recon.get("REC-03") or {}).get("formula") != formula:
        findings.append(
            "il canonico non pubblica la stringa di formula del MOTORE: la "
            "provenienza e' rotta")
    for entry in ((plan_of(case["document"]).get("calculation_metadata") or {})
                  .get("modules") or ()):
        if not entry.get("formula_semantics"):
            findings.append(
                f"calculation_metadata.modules[{entry.get('module_id')}] senza "
                "formula_semantics")
    return findings


def c09(ctx, base):
    """`FO-C-09` `T-FIN-TIMING-SHIFT` — politica di CLIPPING ANCORATO ALLO
    START, DICHIARATA e applicata."""
    findings = []
    records = ENG.triplet_records(ctx["eng"])
    rows = timing_rows(ctx, records, start=2, end=11, triplet=("0", "2", "4"))
    _, run = engine_run(ctx, base, rows, records, name="c09")
    payload = run["result"]
    scenarios = ((payload.get("financial_payload") or {}).get("results")
                 or {}).get("scenarios") or {}
    totals = {}
    for scenario_id in SCENARIO_IDS:
        entry = scenarios.get(scenario_id) or {}
        summary = entry.get("summary") or {}
        totals[scenario_id] = str(summary.get("pnl_total"))
    if len(set(totals.values())) != len(SCENARIO_IDS):
        findings.append(
            f"i tre scenari NON sono distinti sotto la politica dichiarata: "
            f"{totals} — sotto la TRASLAZIONE a durata conservata i tre "
            "valori coinciderebbero")
    # L'`end_period` DICHIARATO non e' mosso: e' lo START a muoversi. La
    # verifica e' sul CLONE che `resolve_scenario_rows` produce, che e' la
    # sede reale della politica.
    engine = load_production_module(ctx, ENGINE_VALIDATOR_REL,
                                    "validate_financial_engine_probe")
    if engine is None:
        findings.append("validate_financial_engine.py assente")
        return findings
    binding = None
    for entry in rows:
        if entry["role"] == "opex":
            # La riga di binding porta il RECORD CANONICO che dichiara la
            # terna: senza di esso `scenario_endpoints` restituisce None, il
            # clone resta invariato e la sonda sarebbe VACUA. Il record e' lo
            # STESSO che il motore lega a runtime, non un valore inventato.
            binding = dict(entry, _record=records[entry["source_ref"]])
            break
    if binding is None:
        findings.append("nessun driver `timing_like` nella variante derivata")
        return findings
    horizon = 12
    for scenario_id in SCENARIO_IDS:
        clone = engine.resolve_scenario_rows([binding], scenario_id,
                                             horizon)[0]
        if clone.get("start_period") == binding.get("start_period") and \
                scenario_id != "base":
            findings.append(
                f"{binding['driver_id']} scenario {scenario_id}: lo start NON "
                "si e' mosso — la sonda sulla politica di timing sarebbe VACUA")
        if clone.get("end_period") != binding.get("end_period"):
            findings.append(
                f"{binding['driver_id']} scenario {scenario_id}: end_period "
                f"{clone.get('end_period')} diverso da quello DICHIARATO "
                f"{binding.get('end_period')}: la finestra TRASLA invece di "
                "essere ANCORATA allo start (clipping ancorato allo start)")
    # La politica e' PUBBLICATA nel workflow e nella metodologia.
    for rel in (WORKFLOW_REL, METHODOLOGY_REL):
        path = ctx["root"] / rel
        if not path.is_file():
            findings.append(f"{rel} assente: la politica non e' PUBBLICATA")
            continue
        text = path.read_text(encoding="utf-8").lower()
        for marker in ("clipping", "start", "finestra"):
            if marker not in text:
                findings.append(
                    f"{rel}: la politica di timing dichiarata non nomina "
                    f"{marker!r}")
    return findings


def c10(ctx, base):
    """`FO-C-10` `T-FIN-TIMING-OUT-OF-HORIZON` — finestra vuota e fuori
    orizzonte MAI silenziose, con attribuzione PER CAMPO TIPIZZATO."""
    findings = []
    records = ENG.triplet_records(ctx["eng"])
    rows = timing_rows(ctx, records, start=2, end=3, triplet=("0", "2", "9"))
    _, run = engine_run(ctx, base, rows, records, name="c10")
    payload = run["result"]
    warnings = ((payload.get("financial_payload") or {}).get("validation")
                or {}).get("warnings") or []
    timing = [w for w in warnings
              if w.get("code") == CODE_TIMING_WINDOW_EMPTY]
    if not timing:
        findings.append(
            f"finestra vuota (start 9 > end 3, entrambi in orizzonte) senza "
            f"alcun {CODE_TIMING_WINDOW_EMPTY} in validation.warnings[]: "
            "l'output canonico pubblicherebbe in SILENZIO una finestra "
            "svuotata")
        return findings
    for entry in timing:
        refs = entry.get("affected_refs") or []
        drivers = [r for r in refs if TOKEN_DRIVER_RE.match(str(r))]
        modules = [r for r in refs if TOKEN_MODULE_RE.match(str(r))]
        scenarios = [r for r in refs if TOKEN_SCENARIO_RE.match(str(r))]
        outside = [r for r in refs
                   if not (TOKEN_DRIVER_RE.match(str(r))
                           or TOKEN_MODULE_RE.match(str(r))
                           or TOKEN_SCENARIO_RE.match(str(r)))]
        if len(drivers) != 1 or len(modules) != 1 or len(scenarios) != 1:
            findings.append(
                f"{CODE_TIMING_WINDOW_EMPTY}: affected_refs {refs} non porta "
                "ESATTAMENTE un token DRV-*, uno module:<id> e uno "
                "scenario:<id>")
        if outside:
            findings.append(
                f"{CODE_TIMING_WINDOW_EMPTY}: token FUORI dalle tre "
                f"grammatiche dichiarate: {outside}")
        if "severity" in entry:
            findings.append(
                "il warning porta un campo `severity`: la severita' e' portata "
                "dall'APPARTENENZA all'array dei warning, e nessun campo e' "
                "aggiunto")
        message = (entry.get("message") or "")
        for token in ("scenario:", "module:"):
            if token in message:
                findings.append(
                    f"l'attribuzione e' messa in PROSA nel campo `message` "
                    f"({message!r}) invece che nel token tipizzato: e' la "
                    "prosa da re-interpretare, vietata: l'attribuzione vive "
                    "SOLO nei token tipizzati")
        if re.search(r"DRV-[0-9]{3}", message):
            findings.append(
                f"il campo `message` NOMINA il driver ({message!r}): "
                "l'attribuzione vive SOLO nel token tipizzato")
    # Un estremo FUORI ORIZZONTE non conta come coperto ed e' NOMINATO.
    out_records = ENG.triplet_records(ctx["eng"])
    out_rows = timing_rows(ctx, out_records, start=2, end=11,
                           triplet=("0", "2", "99"))
    _, out_run = engine_run(ctx, base, out_rows, out_records, name="c10out")
    coverage = (((out_run["result"].get("financial_payload") or {})
                 .get("results") or {}).get("scenarios") or {}).get("coverage") \
        or {}
    uncovered = coverage.get("uncovered_driver_refs") or []
    victim = None
    for entry in out_rows:
        if entry["role"] == "opex":
            victim = entry["driver_id"]
    if victim not in uncovered:
        findings.append(
            f"il driver {victim} con estremo FUORI ORIZZONTE non compare in "
            f"uncovered_driver_refs {uncovered}: e' contato come coperto")
    # `validation.result` non e' MAI `PASS` senza il warning.
    validation = ((payload.get("financial_payload") or {}).get("validation")
                  or {})
    if validation.get("result") == "PASS" and not timing:
        findings.append(
            "validation.result e' PASS senza il warning attribuito")
    # Il canonico PUBBLICA il warning attribuito, e il validator ne verifica la
    # grammatica in modo COMPORTAMENTALE.
    case = build_and_validate(ctx, base, payload, name="c10")
    if not_built(case, findings):
        return findings
    published = [w for w in (validation_of(case["document"]).get("warnings")
                             or [])
                 if w.get("code") == CODE_TIMING_WINDOW_EMPTY]
    if not published:
        findings.append(
            "il canonico NON pubblica il warning di finestra vuota: "
            "l'attribuzione si perde alla canonicalizzazione")
    if unavailable(case["validated"], findings):
        return findings
    # RED — attribuzione in PROSA e token fuori grammatica: entrambi RESPINTI.
    for label, mutate in (
            ("prosa nel message",
             lambda doc: doc["financial_plan"]["validation"]["warnings"][0]
             .update({"affected_refs": ["DRV-007", "module:opex"],
                      "message": "finestra vuota nello scenario downside"})),
            ("token fuori grammatica",
             lambda doc: doc["financial_plan"]["validation"]["warnings"][0]
             .update({"affected_refs": ["DRV-007", "module:opex",
                                        "scenario:downside", "opex-window"]}))):
        mutated = copy.deepcopy(case["document"])
        published_index = None
        for index, entry in enumerate(
                mutated["financial_plan"]["validation"]["warnings"]):
            if entry.get("code") == CODE_TIMING_WINDOW_EMPTY:
                published_index = index
                break
        if published_index is None:
            continue
        mutated["financial_plan"]["validation"]["warnings"] = [
            mutated["financial_plan"]["validation"]["warnings"][published_index]
        ] + [e for i, e in enumerate(
            mutated["financial_plan"]["validation"]["warnings"])
            if i != published_index]
        mutate(mutated)
        probe = probe_document(ctx, base, mutated, name=f"c10-{label[:5]}")
        if probe["exit_code"] == 0:
            findings.append(
                f"il validator di produzione ACCETTA il warning con {label}: "
                "la validazione della grammatica non e' comportamentale")
    return findings


def c11(ctx, base):
    """`FO-C-11` `T-FIN-INVESTOR-READINESS` — la prontezza e' DISTINTA da
    `result` e da `propagated_status`."""
    findings = []
    validation_schema = (((((ctx["schema"].get("properties") or {})
                            .get("financial_plan") or {}).get("properties")
                           or {}).get("validation") or {}).get("properties")
                         or {})
    readiness_schema = validation_schema.get("investor_readiness")
    if not isinstance(readiness_schema, dict):
        findings.append(
            "validation.investor_readiness ASSENTE dallo schema: la "
            "prontezza distinta non e' applicata")
        return findings
    if readiness_schema.get("additionalProperties") is not False:
        findings.append("investor_readiness non e' un oggetto CHIUSO")
    status_enum = ((readiness_schema.get("properties") or {}).get("status")
                   or {}).get("enum")
    if sorted(status_enum or ()) != ["not_ready", "ready"]:
        findings.append(
            f"investor_readiness.status enum {status_enum} invece di "
            "[ready, not_ready]")
    payload = nominal_payload(ctx, base, name="c11")
    case = build_and_validate(ctx, base, payload, name="c11")
    if not_built(case, findings):
        return findings
    validation = validation_of(case["document"])
    readiness = validation.get("investor_readiness") or {}
    if not readiness:
        findings.append("il canonico non porta validation.investor_readiness")
        return findings
    for key in ("result", "propagated_status"):
        if key not in validation:
            findings.append(f"validation.{key} assente: le TRE prontezze non "
                            "sono tre campi distinti")
    if readiness.get("status") == "ready" and \
            validation.get("propagated_status") != "confirmed":
        findings.append(
            f"investor_readiness `ready` con propagated_status "
            f"{validation.get('propagated_status')!r}: la regola conservativa di prontezza "
            "e' violata")
    for reason in readiness.get("blocking_reasons") or ():
        if not reason.get("code"):
            findings.append("blocking_reason senza `code`: e' PROSA")
        if not (reason.get("affected_refs") or []):
            findings.append(
                f"blocking_reason {reason.get('code')!r} senza affected_refs: "
                "e' TIPIZZATA ma non ATTRIBUITA")
    # Copertura NULLA -> `not_ready` con ragioni TIPIZZATE e ATTRIBUITE.
    none_payload = no_coverage_payload(ctx, base, name="c11-none")
    none_case = build_and_validate(ctx, base, none_payload, name="c11none",
                                   validate=False)
    if none_case["document"] is not None:
        none_readiness = validation_of(none_case["document"]).get(
            "investor_readiness") or {}
        if none_readiness.get("status") != "not_ready":
            findings.append(
                f"con copertura di scenario NULLA la prontezza e' "
                f"{none_readiness.get('status')!r} invece di not_ready: la "
                "regola conservativa di prontezza non e' applicata")
        if not (none_readiness.get("blocking_reasons") or []):
            findings.append(
                "not_ready senza blocking_reasons: le ragioni di blocco sono "
                "l'informazione utile")
    # RED — prontezza DERIVATA da `validation.result`.
    mutated = copy.deepcopy(case["document"])
    mutated["financial_plan"]["validation"]["investor_readiness"] = {
        "status": "ready", "blocking_reasons": []}
    mutated["financial_plan"]["validation"]["propagated_status"] = "inferred"
    probe = probe_document(ctx, base, mutated, name="c11")
    if probe["exit_code"] == 0:
        findings.append(
            "`ready` con propagated_status != confirmed e' accettato: la "
            "prontezza e' derivata dall'aritmetica (MUT-3-11)")
    elif not any("propagated_status" in str(ref) or "investor_readiness" in
                 str(ref) for refs in probe["refs_by_code"].values()
                 for ref in refs):
        findings.append(
            f"il rifiuto non NOMINA il predicato violato: "
            f"{probe['refs_by_code']}")
    return findings


def c12(ctx, base):
    """`FO-C-12` `T-FIN-MATERIALITY-CARRIER` — portatore presente, NESSUNA
    SOGLIA INVENTATA."""
    findings = []
    driver_schema = ((ctx["schema"].get("$defs") or {}).get("driver_entry")
                     or {})
    properties = driver_schema.get("properties") or {}
    materiality = properties.get("materiality")
    if not isinstance(materiality, dict):
        findings.append(
            "$defs.driver_entry.properties.materiality ASSENTE: il "
            "portatore di materialita' non e' applicato")
        return findings
    if sorted(materiality.get("enum") or ()) != ["high", "low", "medium"]:
        findings.append(
            f"materiality enum {materiality.get('enum')} invece di "
            "[low, medium, high]")
    if "materiality_basis" not in properties:
        findings.append(
            "materiality_basis ASSENTE: la base del giudizio non e' dichiarata")
    if "materiality" in (driver_schema.get("required") or ()):
        findings.append("materiality e' `required`: deve essere OPZIONALE")
    blob = json.dumps(materiality)
    for token in ("minimum", "maximum", "threshold"):
        if token in blob:
            findings.append(
                f"materiality dichiara una SOGLIA NUMERICA ({token}): "
                "la materialita' e' un giudizio, mai una soglia")
    payload = nominal_payload(ctx, base, name="c12")
    case = build_and_validate(ctx, base, payload, name="c12", validate=False)
    if not_built(case, findings):
        return findings
    # ASSENTE nel payload ⇒ ASSENTE nel canonico: mai «bassa», mai dedotta.
    for entry in drivers_of(case["document"]):
        if "materiality" in entry:
            findings.append(
                f"{entry['driver_id']}: il canonico porta materiality "
                f"{entry['materiality']!r} mentre il payload non la dichiara: "
                "l'assenza e' stata DEDOTTA")
    # PRESENTE nel payload ⇒ COPIATA alla lettera.
    declared = copy.deepcopy(payload)
    drivers = declared["financial_payload"]["driver_registry"]["drivers"]
    drivers[0]["materiality"] = "high"
    drivers[0]["materiality_basis"] = (
        "giudicata sul peso del ruolo nel conto economico, DICHIARATA")
    declared_case = build_and_validate(ctx, base, declared, name="c12d",
                                       validate=False)
    if declared_case["document"] is not None:
        first = drivers_of(declared_case["document"])
        match = [e for e in first if e["driver_id"] == drivers[0]["driver_id"]]
        if not match or match[0].get("materiality") != "high":
            findings.append(
                "materiality DICHIARATA nel payload non e' portata nel "
                "canonico: il portatore non trasporta")
    # RED — valore FUORI ENUM respinto dallo schema.
    out = copy.deepcopy(case["document"])
    out["financial_plan"]["driver_registry"]["drivers"][0]["materiality"] = \
        "critical"
    if not schema_rejects(ctx, out):
        findings.append(
            "materiality `critical` (fuori enum) non e' respinta dallo schema")
    # Nessun percorso usa `materiality` per decidere la prontezza.
    high = copy.deepcopy(payload)
    for entry in high["financial_payload"]["driver_registry"]["drivers"]:
        entry["materiality"] = "high"
    high_case = build_and_validate(ctx, base, high, name="c12h",
                                   validate=False)
    if high_case["document"] is not None and case["document"] is not None:
        before = validation_of(case["document"]).get("investor_readiness")
        after = validation_of(high_case["document"]).get("investor_readiness")
        if json.dumps(before, sort_keys=True) != json.dumps(after,
                                                            sort_keys=True):
            findings.append(
                "la prontezza CAMBIA al variare della sola materialita': un "
                "percorso la usa per decidere investor_readiness, mentre "
                "la materialita' non entra nella regola di prontezza")
    return findings


def c13(ctx, base):
    """`FO-C-13` `T-FIN-SOURCE-TYPE-CARRIER` — enum RIUSATO, non CONIATO
    """
    findings = []
    properties = (((ctx["schema"].get("$defs") or {}).get("driver_entry")
                   or {}).get("properties") or {})
    source_type = properties.get("source_type")
    if not isinstance(source_type, dict):
        findings.append(
            "$defs.driver_entry.properties.source_type ASSENTE: il "
            "portatore del tipo di fonte non e' applicato")
        return findings
    accepted = (((ctx["source_register"].get("items") or {}).get("properties")
                 or {}).get("source_type") or {}).get("enum")
    if list(source_type.get("enum") or ()) != list(accepted or ()):
        findings.append(
            f"l'enum di source_type {source_type.get('enum')} DIVERGE da "
            f"quello di source-register.schema.json {accepted}: "
            "e' stato CONIATO invece che RIUSATO")
    payload = nominal_payload(ctx, base, name="c13")
    declared = copy.deepcopy(payload)
    drivers = declared["financial_payload"]["driver_registry"]["drivers"]
    drivers[0]["source_type"] = (accepted or ["internal"])[0]
    case = build_and_validate(ctx, base, declared, name="c13", validate=False)
    if not_built(case, findings):
        return findings
    match = [e for e in drivers_of(case["document"])
             if e["driver_id"] == drivers[0]["driver_id"]]
    if not match or match[0].get("source_type") != drivers[0]["source_type"]:
        findings.append(
            "source_type DICHIARATO nel payload non e' portato nel canonico")
    out = copy.deepcopy(case["document"])
    out["financial_plan"]["driver_registry"]["drivers"][0]["source_type"] = \
        "not_a_source_type"
    if not schema_rejects(ctx, out):
        findings.append(
            "un source_type FUORI ENUM non e' respinto dallo schema")
    return findings


def c14(ctx, base):
    """`FO-C-14` `T-FIN-USE-OF-PROCEEDS-CANDIDATES` — CATEGORIE candidate,
    mai un'allocazione, nella forma ESATTA di un oggetto chiuso inline."""
    findings = []
    schema = ctx["schema"]
    slot = ((((((schema.get("properties") or {}).get("financial_plan") or {})
               .get("properties") or {}).get("results") or {})
             .get("properties") or {}).get("modules") or {})
    funding = (slot.get("properties") or {}).get("funding_gap")
    if not isinstance(funding, dict):
        findings.append("results.modules.funding_gap assente dallo schema")
        return findings
    if "allOf" in funding:
        findings.append(
            "results.modules.funding_gap e' ancora un `allOf`: lo schema "
            "deve dichiararlo come OGGETTO CHIUSO INLINE")
    module_result = (schema.get("$defs") or {}).get("module_result") or {}
    # GUARDIA DI EQUIVALENZA STRUTTURALE — insieme di ECCEZIONI DICHIARATO.
    if funding.get("type") != module_result.get("type"):
        findings.append("guardia: `type` divergente da $defs.module_result")
    if funding.get("additionalProperties") != \
            module_result.get("additionalProperties"):
        findings.append(
            "guardia: `additionalProperties` divergente da $defs.module_result")
    if list(funding.get("required") or ()) != list(
            module_result.get("required") or ()):
        findings.append(
            f"guardia: `required` {funding.get('required')} non e' la STESSA "
            f"LISTA nello STESSO ORDINE di {module_result.get('required')}")
    base_props = set(module_result.get("properties") or ())
    inline_props = set(funding.get("properties") or ())
    if inline_props != base_props | {"use_of_proceeds_candidates"}:
        findings.append(
            f"guardia: l'INSIEME dei nomi di proprieta' {sorted(inline_props)} "
            f"non e' {sorted(base_props)} piu' la SOLA "
            "use_of_proceeds_candidates")
    for name in sorted(base_props & inline_props):
        left = json.dumps((module_result.get("properties") or {})[name],
                          sort_keys=True)
        right = json.dumps((funding.get("properties") or {})[name],
                           sort_keys=True)
        if name == "module_id":
            expected = dict((module_result.get("properties") or {})[name])
            expected["const"] = "funding_gap"
            if json.dumps(expected, sort_keys=True) != right:
                findings.append(
                    "guardia: properties.module_id non acquisisce ESATTAMENTE "
                    f"la chiave `const` con valore \"funding_gap\": {right}")
            continue
        if left != right:
            findings.append(
                f"guardia: il sottoschema della proprieta' condivisa {name} "
                f"diverge per JSON canonico")
    # I QUATTORDICI slot FRATELLI restano INVARIATI nelle FORME REALI.
    allof_slots = ("revenue", "cogs", "gross_margin", "headcount", "payroll",
                   "opex", "pnl", "cash_flow", "balance_sheet", "runway",
                   "cash_buffer")
    inline_slots = ("break_even", "milestone_coverage", "kpi")
    for name in allof_slots:
        entry = (slot.get("properties") or {}).get(name) or {}
        if "allOf" not in entry:
            findings.append(
                f"lo slot fratello {name} non e' piu' in forma `allOf`")
    for name in inline_slots:
        entry = (slot.get("properties") or {}).get(name) or {}
        if "allOf" in entry or entry.get("additionalProperties") is not False:
            findings.append(
                f"lo slot fratello {name} non e' piu' un OGGETTO CHIUSO "
                "INLINE")
    candidates = (funding.get("properties") or {}).get(
        "use_of_proceeds_candidates") or {}
    blob = json.dumps(candidates)
    for token in ("\"number\"", "\"integer\"", "amount", "period_series"):
        if token in blob:
            findings.append(
                f"use_of_proceeds_candidates dichiara un tipo NUMERICO "
                f"({token}): un'allocazione diventerebbe possibile")
    payload = nominal_payload(ctx, base, name="c14")
    case = build_and_validate(ctx, base, payload, name="c14")
    if not_built(case, findings):
        return findings
    module = modules_of(case["document"]).get("funding_gap") or {}
    listed = module.get("use_of_proceeds_candidates")
    if module.get("status") == "PASS" and not listed:
        findings.append(
            "funding_gap e' PASS ma use_of_proceeds_candidates e' ASSENTE: il "
            "portatore canonico non e' popolato")
    for entry in listed or ():
        for key in ("category_id", "label", "eligibility_basis"):
            if not entry.get(key):
                findings.append(
                    f"use_of_proceeds_candidates: voce senza {key}")
        for key in sorted(entry):
            if key not in ("category_id", "label", "eligibility_basis",
                           "driver_refs"):
                findings.append(
                    f"use_of_proceeds_candidates: campo non dichiarato "
                    f"{key!r} sulla categoria {entry.get('category_id')!r}")
    # RED — un campo di IMPORTO su una categoria e' respinto dallo schema.
    mutated = copy.deepcopy(case["document"])
    block = mutated["financial_plan"]["results"]["modules"]["funding_gap"]
    block.setdefault("use_of_proceeds_candidates", [{
        "category_id": "operating_cost", "label": "costi operativi",
        "eligibility_basis": "tassonomia dei costi"}])
    block["use_of_proceeds_candidates"][0]["allocated_amount"] = "120000.00"
    if not schema_rejects(ctx, mutated):
        findings.append(
            "un campo di IMPORTO su una categoria di uso dei proventi non e' "
            "respinto: l'allocazione non e' strutturalmente impossibile")
    # RED — `module_id` diverso da `funding_gap`.
    wrong = copy.deepcopy(case["document"])
    wrong["financial_plan"]["results"]["modules"]["funding_gap"]["module_id"] \
        = "funding_request"
    if not schema_rejects(ctx, wrong):
        findings.append(
            "un module_id diverso da `funding_gap` non e' respinto dal `const`")
    # RED — l'OMISSIONE di un `required` di `module_result`.
    dropped = copy.deepcopy(case["document"])
    dropped["financial_plan"]["results"]["modules"]["funding_gap"].pop(
        "status", None)
    if not schema_rejects(ctx, dropped):
        findings.append(
            "l'omissione del `required` `status` non e' respinta")
    return findings


def c15(ctx, base):
    """`FO-C-15` `T-FIN-NO-SILENT-ASSUMPTION` — nessun caveat riassorbito
    in un `PASS`; `unbound_required_roles[]` NOMINATIVO."""
    findings = []
    records = ENG.triplet_records(ctx["eng"])
    with_cash_buffer_record(ctx, records)
    rows = placeholder_optional_rows(ctx, records)
    _, run = engine_run(ctx, base, rows, records, name="c15")
    payload = run["result"]
    case = build_and_validate(ctx, base, payload, name="c15")
    if not_built(case, findings):
        return findings
    validation = validation_of(case["document"])
    statuses = [entry.get("status") for entry in drivers_of(case["document"])]
    if "placeholder" in statuses and \
            validation.get("propagated_status") == "confirmed":
        findings.append(
            "un input `placeholder` CONSUMATO e' riassorbito in uno stato "
            "propagato `confirmed`: il caveat e' scomparso")
    registry = plan_of(case["document"]).get("driver_registry") or {}
    if "unbound_required_roles" not in registry:
        findings.append(
            "driver_registry.unbound_required_roles assente dal canonico")
    # Un ruolo RICHIESTO non legato e' NOMINATO, mai stimato.
    short_records = ENG.triplet_records(ctx["eng"])
    short_rows = [r for r in ENG.base_rows(ctx["eng"], short_records)
                  if r["role"] != "opex"]
    _, short_run = engine_run(ctx, base, short_rows, short_records,
                              name="c15u")
    unbound = (((short_run["result"].get("financial_payload") or {})
                .get("driver_registry") or {}).get("unbound_required_roles")
               or [])
    if "opex" not in unbound:
        findings.append(
            f"il ruolo RICHIESTO `opex` non legato non e' NOMINATO in "
            f"unbound_required_roles {unbound}")
    # RED — lo stato PROMOSSO e' respinto dal validator di produzione.
    mutated = copy.deepcopy(case["document"])
    mutated["financial_plan"]["validation"]["propagated_status"] = "confirmed"
    mutated["financial_plan"]["governance"]["plan"]["propagated_status"] = \
        "confirmed"
    probe = probe_document(ctx, base, mutated, name="c15")
    if probe["exit_code"] == 0:
        findings.append(
            "uno stato propagato PROMOSSO sopra il minimo dei propri input e' "
            "accettato in silenzio")
    return findings


def c16(ctx, base):
    """`FO-C-16` `T-FIN-CANONICAL-NO-RECOMPUTE` — (a) scansione PULITA;
    (b) AUTO-SONDA: il rilevatore AST NON e' vacuo."""
    findings = []
    module = load_production_module(ctx, OUTPUT_VALIDATOR_REL,
                                    "validate_financial_output_probe")
    if module is None:
        findings.append(MISSING_VALIDATOR)
        return findings
    scan = getattr(module, "scan_forbidden_recomputation", None)
    probe_source = getattr(module, "AST_SELF_PROBE_SOURCE", None)
    if not callable(scan) or not probe_source:
        findings.append(
            "validate_financial_output non espone "
            "`scan_forbidden_recomputation` e `AST_SELF_PROBE_SOURCE`: il "
            "rilevatore AST e la sua auto-sonda sono obbligatori")
        return findings
    builder = ctx["root"] / BUILDER_REL
    if not builder.is_file():
        findings.append(MISSING_BUILDER)
        return findings
    # (a) — scansione PULITA del costruttore di produzione.
    dirty = scan(builder.read_text(encoding="utf-8"), label=BUILDER_REL)
    if dirty:
        findings.append(
            f"(a) il costruttore canonico contiene operazioni VIETATE: {dirty}")
    # (b) — AUTO-SONDA: il rilevatore DEVE rilevare la violazione sintetica.
    detected = scan(probe_source, label="<auto-sonda>")
    if not detected:
        findings.append(
            "(b) l'AUTO-SONDA non ha rilevato la violazione iniettata nel "
            "sorgente sintetico: il rilevatore AST e' VACUO e la scansione (a) "
            "non prova nulla (MUT-3-16(b))")
    else:
        kinds = {entry.split(":")[-1].strip().split(" ")[0]
                 for entry in detected}
        del kinds
    return findings


def c17(ctx, base):
    """`FO-C-17` `T-FIN-CANONICAL-ATOMIC-WRITE` — scrittura ATOMICA, con
    FALLIMENTO INIETTATO."""
    findings = []
    builder = load_production_module(ctx, BUILDER_REL,
                                     "build_canonical_output_probe")
    if builder is None:
        findings.append(MISSING_BUILDER)
        return findings
    atomic = getattr(builder, "atomic_write", None)
    if not callable(atomic):
        findings.append(
            "build_canonical_output non espone `atomic_write`: la politica "
            "atomica di par. I.2 non e' isolabile ne' iniettabile")
        return findings
    work = Path(base) / "c17"
    work.mkdir(parents=True, exist_ok=True)
    target = work / "structured-output.json"
    previous = "{\n  \"generation\": \"N\"\n}\n"
    target.write_text(previous, encoding="utf-8")
    before = sha256_of(target)
    original = builder.os.replace

    def exploding(src, dst):
        raise OSError("fallimento INIETTATO dopo la scrittura parziale")

    builder.os.replace = exploding
    try:
        atomic(target, "{\n  \"generation\": \"N+1\"\n}\n")
    except OSError:
        pass
    except Exception as exc:  # pragma: no cover - forma inattesa
        findings.append(f"atomic_write ha sollevato {exc!r} invece di OSError")
    finally:
        builder.os.replace = original
    if sha256_of(target) != before:
        findings.append(
            "il documento PRECEDENTE non e' rimasto INTATTO dopo il "
            "fallimento iniettato")
    residue = sorted(p.name for p in work.iterdir()
                     if p.name != "structured-output.json")
    if residue:
        findings.append(
            f"file PARZIALI superstiti dopo il fallimento iniettato: {residue}")
    if target.read_text(encoding="utf-8") != previous:
        findings.append(
            "il contenuto del documento precedente e' cambiato: la verifica e' "
            "per CONTENUTO, non per sola esistenza")
    # Caso POSITIVO — la scrittura riuscita sostituisce per intero.
    atomic(target, "{\n  \"generation\": \"N+1\"\n}\n")
    if "N+1" not in target.read_text(encoding="utf-8"):
        findings.append("la scrittura atomica riuscita non sostituisce il file")
    residue = sorted(p.name for p in work.iterdir()
                     if p.name != "structured-output.json")
    if residue:
        findings.append(f"file temporanei ORFANI dopo il successo: {residue}")
    return findings


def c18(ctx, base):
    """`FO-C-18` `T-FIN-CANONICAL-STALE-GUARD` — lo stantio e' RIGENERATO,
    mai letto; classificarlo `WARNING` e' un FALLIMENTO del contratto."""
    findings = []
    payload = nominal_payload(ctx, base, name="c18")
    case = build_and_validate(ctx, base, payload, name="c18", validate=False)
    if not_built(case, findings):
        return findings
    fresh = sha256_of(case["target"])
    stale = copy.deepcopy(case["document"])
    stale["financial_plan"]["calculation_metadata"]["output_checksums"][
        "base"] = "b" * 64
    case["target"].write_text(json.dumps(stale, indent=2, ensure_ascii=True,
                                         sort_keys=True) + "\n",
                              encoding="utf-8")
    again = run_builder(ctx, case["payload_path"], case["project"])
    if again["exit_code"] != 0:
        findings.append(
            f"il costruttore non RIGENERA un documento stantio (exit "
            f"{again['exit_code']})")
    elif sha256_of(case["target"]) != fresh:
        findings.append(
            "il documento stantio non e' stato RIGENERATO byte per byte dal "
            "payload corrente")
    report = again.get("report") or {}
    if not report.get("regenerated"):
        findings.append(
            "il costruttore non DICHIARA la rigenerazione: la divergenza dei "
            "due checksum resta muta")
    # Il VALIDATOR classifica lo stantio FAIL, mai WARNING.
    project = fixture_project(ctx, base, "c18-stale")
    target = canonical_path(project)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(stale, indent=2, ensure_ascii=True,
                                 sort_keys=True) + "\n", encoding="utf-8")
    probe = run_output_validator(ctx, project, target,
                                 payload_path=case["payload_path"])
    if unavailable(probe, findings):
        return findings
    if probe["exit_code"] == 0:
        findings.append(
            f"un canonico con `canonical_source_checksum` STANTIO e' accettato "
            f"(exit 0): {CODE_STALE} non e' un gate")
    if CODE_STALE not in probe["codes"]:
        findings.append(
            f"lo stantio non e' classificato {CODE_STALE}: codici osservati "
            f"{sorted(probe['codes'])}")
    for warning in (probe["report"] or {}).get("warnings") or ():
        if warning.get("code") == CODE_STALE:
            findings.append(
                f"{CODE_STALE} e' classificato WARNING: uno stantio e' un "
                "FAIL e classificarlo WARNING e' un FALLIMENTO del contratto")
    body = json.dumps(probe["report"] or {})
    if "b" * 64 not in body:
        findings.append(
            "il rifiuto non NOMINA i DUE checksum a confronto")
    return findings


def c19(ctx, base):
    """`FO-C-19` `T-FIN-ENGINE-CANONICAL-BOUNDARY` — mappatura TOTALE
    payload -> canonico, con le TRE omissioni DICHIARATE."""
    findings = []
    payload = nominal_payload(ctx, base, name="c19")
    case = build_and_validate(ctx, base, payload, name="c19", validate=False)
    if not_built(case, findings):
        return findings
    body = json.dumps(case["document"])
    if "sensitivity" in body:
        findings.append(
            "il canonico porta `sensitivity`: e' un'OMISSIONE DICHIARATA "
            "(in questa versione la sensitivity non fa parte del documento "
            "canonico) e canonicalizzarla di nascosto e' MUT-3-19")
    if "tolerance_ledger" in body:
        findings.append("il canonico porta `tolerance_ledger`")
    registry = plan_of(case["document"]).get("driver_registry") or {}
    if "superseded" in registry:
        findings.append("il canonico porta `driver_registry.superseded`")
    handoff = candidate_dir(case["project"]) / "handoff.md"
    if not handoff.is_file():
        findings.append(
            "handoff.md assente: le TRE omissioni non sono NOMINATE "
            "nell'handoff dello stage")
    else:
        text = handoff.read_text(encoding="utf-8")
        for omission in DECLARED_OMISSIONS:
            if omission not in text:
                findings.append(
                    f"handoff.md non NOMINA l'omissione dichiarata "
                    f"{omission!r}")
    # RED — un blocco di PRIMO LIVELLO NUOVO nel payload e' un FAIL.
    mutated = copy.deepcopy(payload)
    mutated["financial_payload"]["unmapped_new_block"] = {"whatever": 1}
    probe_path = write_payload(base, mutated, name="c19-unmapped.json")
    project = fixture_project(ctx, base, "c19-unmapped")
    built = run_builder(ctx, probe_path, project)
    if built["exit_code"] == 0:
        findings.append(
            "un blocco di primo livello NUOVO nel payload e' accettato in "
            "silenzio: la mappatura non e' TOTALE")
    elif "unmapped_new_block" not in json.dumps(built.get("report") or {}):
        findings.append(
            "il rifiuto non NOMINA il blocco non mappato: "
            f"{built.get('report')}")
    if canonical_path(project).exists():
        findings.append(
            "un payload con un blocco non mappato ha comunque prodotto un "
            "documento")
    return findings


def c20(ctx, base):
    """`FO-C-20` `T-FIN-WORKFLOW-CONTRACT` — workflow, metodologia e
    runtime-agent portano il CONTRATTO OPERATIVO."""
    findings = []
    required = {
        WORKFLOW_REL: (
            "validate_financial_binding", "validate_financial_engine",
            "build_canonical_output.py", "validate_financial_output",
            "transaction_manager.py", ".working/",
            "structured-output.json", "handoff.md",
            "gate 1", "gate 2", "gate 3",
            "release boundary", "stage_not_implemented",
            "clipping", "copertura di scenario",
            "nessuna scrittura canonica diretta",
        ),
        METHODOLOGY_REL: (
            "D-01", "D-02", "D-03", "D-04", "D-05", "D-06", "D-07", "D-08",
            "D-09", "driver_registry", "propagated_status",
            "investor_readiness", "verified_fact", "founder_assumption",
            "placeholder",
        ),
        RUNTIME_AGENT_REL: (
            "role:", "objective:", "scope:", "required_inputs:",
            "optional_inputs:", "methodology_files:", "allowed_tools:",
            "forbidden_actions:", "expected_output:", "output_schema:",
            "quality_checks:", "escalation_conditions:",
            "10_financial-plan", "handoff.md",
        ),
    }
    for rel, markers in required.items():
        path = ctx["root"] / rel
        if not path.is_file():
            findings.append(f"{rel}: ASSENTE — file obbligatorio")
            continue
        text = path.read_text(encoding="utf-8")
        if len(text.strip()) < 1200:
            findings.append(
                f"{rel}: contenuto insufficiente per un contratto operativo "
                f"({len(text.strip())} caratteri)")
        missing = [m for m in markers if m not in text]
        if missing:
            findings.append(f"{rel}: voci di contratto assenti: {missing}")
    agent = ctx["root"] / RUNTIME_AGENT_REL
    if agent.is_file():
        text = agent.read_text(encoding="utf-8").lower()
        for prohibition in ("nessun ricalcolo", "nessuna ricerca",
                            "nessuna scrittura canonica"):
            if prohibition not in text:
                findings.append(
                    f"{RUNTIME_AGENT_REL}: divieto esplicito assente: "
                    f"{prohibition!r}")
    return findings


def c21(ctx, base):
    """`FO-C-21` `T-FIN-NO-STAGE-11-ARTIFACTS` — i token degli stage
    successivi (`funding-request`, `data-room`, `document-generation`) sono
    ammessi SOLO per l'invariante parametrico sul release_boundary, e la
    guardia di `T-STAGE-WORKFLOWS` non e' indebolita."""
    findings = []
    # Guardia dei token di stage, misurata su COPIE ISOLATE del repository.
    #
    # CRITERIO: ogni token di stage successivo e' PARAMETRICO, misurato sui
    # suoi artefatti REALI e ammesso solo se lo stage e' al piu' uno oltre il
    # release_boundary:
    #
    #   (a-FR) `funding-request`  INVARIATO: RESPINTO e nominato al boundary
    #       forzato 09; AMMESSO dal solo invariante parametrico da 10 in su.
    #   (a-DR) `data-room`  diventa PARAMETRICO come i token che lo precedono,
    #       misurato sui suoi artefatti REALI: RESPINTO e nominato ai boundary
    #       forzati 09 e 10 (12 > boundary + 1); AMMESSO a 11 e al boundary
    #       reale 12, SOLO per l'invariante
    #           stage_order["12_data-room"] <= stage_order[boundary] + 1
    #   (a-DG) `document-generation`  diventa PARAMETRICO come i token che
    #       lo precedono, misurato sui suoi artefatti REALI: RESPINTO e
    #       nominato ai
    #       boundary forzati 09, 10 e 11 (13 > boundary + 1); AMMESSO a 12 e
    #       al boundary reale 13, SOLO per l'invariante
    #           stage_order["13_document-generation"] <= stage_order[boundary]
    #           + 1
    #       Nessuna clausola ASSOLUTA lo respinge a ogni boundary: lo
    #       Stage 13 e' implementato.
    #
    # DISCRIMINANZA: prima di ogni sonda di
    # rifiuto sono rimossi, dal SOLO mirror, gli artefatti REALI dei token non
    # ammessi a quel boundary, e il controllo PULITO deve essere VERDE; le
    # sonde `data-room` e `document-generation` RIPRISTINANO poi ciascuna i
    # propri artefatti reali, cosi' che il rifiuto sia attribuibile a lei
    # sola.
    #
    # Restano obbligatori: che il rifiuto NOMINI il token e che la copia
    # PULITA sia VERDE.
    def token_files(tree, token):
        return sorted(path for folder in ("workflows", "methodology",
                                          "runtime-agents")
                      for path in (tree / SKILL_REL / folder).glob(
                          f"*{token}*"))

    with tempfile.TemporaryDirectory(prefix="fin_output_c21_") as work:
        clean = repo_mirror(ctx["root"], Path(work) / "clean")
        proc = run_module(clean, WORKFLOW_TEST_REL)
        if proc.returncode != 0:
            findings.append(
                f"(a) T-STAGE-WORKFLOWS e' RED sulla copia PULITA, al "
                f"boundary REALE, con gli artefatti `financial-plan`, "
                f"`funding-request`, `data-room` e `document-generation` "
                f"presenti: {proc.stdout.strip()[:400]}")
        real_boundary = json.loads(
            (ctx["root"] / ENFORCEMENT_REL).read_text(encoding="utf-8")
        )["release_boundary"]
        cases = (("09_roadmap-and-milestones", False, False, False),
                 ("10_financial-plan", True, False, False),
                 ("11_funding-request", True, True, False),
                 ("12_data-room", True, True, True),
                 (real_boundary, True, True, True))
        for index, (boundary, fr_admitted, dr_admitted,
                    dg_admitted) in enumerate(cases):
            mirror = repo_mirror(ctx["root"], Path(work) / f"neg-{index}")
            config_path = mirror / ENFORCEMENT_REL
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["release_boundary"] = boundary
            config_path.write_text(json.dumps(config, indent=2,
                                              ensure_ascii=False) + "\n",
                                   encoding="utf-8")
            stage_order = config["stage_order"]
            # DISCRIMINANZA: a un boundary dove `document-generation`
            # non e' ammesso i suoi artefatti REALI sono rimossi dal SOLO
            # mirror PRIMA delle sonde che non lo riguardano — il rifiuto
            # nomina il release_boundary, e a boundary 11 la stringa
            # `11_funding-request` renderebbe il rifiuto di un ALTRO token
            # indistinguibile da quello di `funding-request`. La sonda a-DG li
            # RIPRISTINA da se'.
            if not dg_admitted:
                for path in token_files(mirror, "document-generation"):
                    path.unlink()
            # (a-FR) — gli artefatti REALI dello Stage 11 sono gia' nel
            # mirror: la guardia misura LORO, non un file fittizio.
            proc = run_module(mirror, WORKFLOW_TEST_REL)
            if fr_admitted:
                if proc.returncode != 0 and "funding-request" in proc.stdout:
                    findings.append(
                        f"(a) al boundary {boundary} il token "
                        "`funding-request` e' RESPINTO benche' l'invariante "
                        "PARAMETRICO lo ammetta: il criterio successore non e' "
                        f"applicato: {proc.stdout.strip()[:300]}")
                if not (stage_order["11_funding-request"]
                        <= stage_order[boundary] + 1):
                    findings.append(
                        f"(a) al boundary {boundary} l'ammissione di "
                        "`funding-request` NON discende dall'invariante "
                        "parametrico: sarebbe un'eccezione nominale")
            else:
                if proc.returncode == 0:
                    findings.append(
                        f"(a) al boundary {boundary} il token "
                        "`funding-request` e' AMMESSO: il criterio successore "
                        "ha indebolito la guardia")
                elif "funding-request" not in proc.stdout:
                    findings.append(
                        f"(a) al boundary {boundary} il rifiuto non NOMINA il "
                        f"token: {proc.stdout.strip()[:300]}")
            # DISCRIMINANZA — rimossi dal SOLO mirror gli artefatti REALI dei
            # token non ammessi a questo boundary: il controllo PULITO deve
            # essere VERDE.
            for token, admitted in (("funding-request", fr_admitted),
                                    ("data-room", dr_admitted),
                                    ("document-generation", dg_admitted)):
                if not admitted:
                    for path in token_files(mirror, token):
                        path.unlink()
            proc = run_module(mirror, WORKFLOW_TEST_REL)
            if proc.returncode != 0:
                findings.append(
                    f"(a) al boundary {boundary}, senza gli artefatti dei "
                    "token non ammessi, T-STAGE-WORKFLOWS e' RED prima delle "
                    "sonde: le sonde non sarebbero discriminanti: "
                    f"{proc.stdout.strip()[:300]}")
            # (a-DR) — PARAMETRICO, sui propri artefatti REALI.
            if dr_admitted:
                if not (stage_order["12_data-room"]
                        <= stage_order[boundary] + 1):
                    findings.append(
                        f"(a) al boundary {boundary} l'ammissione di "
                        "`data-room` NON discende dall'invariante parametrico: "
                        "sarebbe un'eccezione nominale")
            else:
                real = token_files(ctx["root"], "data-room")
                if not real:
                    findings.append(
                        "(a) nessun artefatto REALE `data-room` da misurare: "
                        "la sonda parametrica sarebbe vacua")
                for path in real:
                    target = mirror / path.relative_to(ctx["root"])
                    target.write_bytes(path.read_bytes())
                proc = run_module(mirror, WORKFLOW_TEST_REL)
                if proc.returncode == 0:
                    findings.append(
                        f"(a) al boundary {boundary} il token `data-room` e' "
                        "AMMESSO benche' 12 > boundary + 1: il criterio "
                        "successore ha indebolito la guardia")
                elif "data-room" not in proc.stdout:
                    findings.append(
                        f"(a) al boundary {boundary} il rifiuto di `data-room` "
                        f"non NOMINA il token: {proc.stdout.strip()[:300]}")
                for path in token_files(mirror, "data-room"):
                    path.unlink()
            # (a-DG) — PARAMETRICO, sui propri artefatti REALI.
            if dg_admitted:
                if not (stage_order["13_document-generation"]
                        <= stage_order[boundary] + 1):
                    findings.append(
                        f"(a) al boundary {boundary} l'ammissione di "
                        "`document-generation` NON discende dall'invariante "
                        "parametrico: sarebbe un'eccezione nominale")
            else:
                real = token_files(ctx["root"], "document-generation")
                if not real:
                    findings.append(
                        "(a) nessun artefatto REALE `document-generation` da "
                        "misurare: la sonda parametrica sarebbe vacua")
                for path in real:
                    target = mirror / path.relative_to(ctx["root"])
                    target.write_bytes(path.read_bytes())
                proc = run_module(mirror, WORKFLOW_TEST_REL)
                if proc.returncode == 0:
                    findings.append(
                        f"(a) al boundary {boundary} il token "
                        "`document-generation` e' AMMESSO benche' 13 > "
                        "boundary + 1: il criterio successore ha indebolito "
                        "la guardia")
                elif "document-generation" not in proc.stdout:
                    findings.append(
                        f"(a) al boundary {boundary} il rifiuto di "
                        "`document-generation` non NOMINA il token: "
                        f"{proc.stdout.strip()[:300]}")
                for path in token_files(mirror, "document-generation"):
                    path.unlink()
    return findings


def c22(ctx, base):
    """`FO-C-22` `T-FIN-M5A-NO-DERIVED` — (a) al termine NESSUN derivato
    esiste; (b) una RUN BLOCCATA non produce ALCUN file."""
    findings = []
    # (a) — nessun artefatto derivato nell'albero, zero import OOXML.
    for pattern in (f"**/{STAGE10}/financial-plan.md",
                    f"**/{STAGE10}/financial-model.xlsx",
                    "**/*.xlsx"):
        for path in ctx["root"].glob(pattern):
            if ".git" in path.parts:
                continue
            findings.append(
                f"(a) artefatto DERIVATO presente nell'albero del repository: "
                f"{path.relative_to(ctx['root']).as_posix()}")
    for rel in (BUILDER_REL, OUTPUT_VALIDATOR_REL):
        path = ctx["root"] / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for library in ("openpyxl", "xlsxwriter", "zipfile", "xml.etree"):
            if re.search(rf"^\s*(import|from)\s+{re.escape(library)}",
                         text, re.MULTILINE):
                findings.append(
                    f"(a) {rel} importa {library}: la produzione del workbook "
                    "appartiene all'esportatore del workbook, non al "
                    "costruttore canonico ne' al suo validator")
    # (b) — run BLOCCATA: exit != 0, ZERO file scritti, codice ATTRIBUITO.
    payload = blocked_payload(ctx, base)
    validation = ((payload.get("financial_payload") or {}).get("validation")
                  or {})
    modules = ((payload.get("financial_payload") or {}).get("results")
               or {}).get("modules") or {}
    if validation.get("result") != "FAIL" and modules:
        findings.append(
            "(b) la variante DERIVATA IN-MODULO non produce una run BLOCCATA: "
            f"result={validation.get('result')!r}, moduli={sorted(modules)}")
    project = fixture_project(ctx, base, "c22-blocked")
    payload_path = write_payload(base, payload, name="c22-blocked.json")
    before = json.dumps(payload, sort_keys=True)
    built = run_builder(ctx, payload_path, project)
    if unavailable(built, findings):
        return findings
    if built["exit_code"] == 0:
        findings.append(
            "(b) il costruttore ACCETTA un payload di run bloccata (exit 0): "
            "un driver_registry non valido per schema raggiungerebbe il "
            "canonico")
    stage_dir = Path(project) / STAGE10
    written = [p.relative_to(project).as_posix()
               for p in stage_dir.rglob("*") if p.is_file()] \
        if stage_dir.exists() else []
    if written:
        findings.append(
            f"(b) la run bloccata ha comunque scritto: {written} — nemmeno "
            "parziale, nemmeno nel candidate")
    report = built.get("report") or {}
    codes = {entry.get("code") for entry in report.get("errors") or ()}
    if not codes:
        findings.append(
            "(b) il rifiuto non porta alcun CODICE ATTRIBUITO: «fallisce» non "
            "e' evidenza")
    if json.dumps(json.loads(payload_path.read_text(encoding="utf-8")),
                  sort_keys=True) != before:
        findings.append(
            "(b) il costruttore ha «RIPULITO» il payload invece di "
            "RIFIUTARLO: nasconderebbe la violazione")
    return findings


# --------------------------------------------------------------------------
# Registro dei contratti
# --------------------------------------------------------------------------


CONTRACTS = [
    {"id": "FO-C-01", "name": "T-FIN-CANONICAL-IDEMPOTENT", "fn": c01,
     "fixture": "F-12 (payload nominale a copertura piena)",
     "expected_code": "(strutturale) campo non deterministico NOMINATO",
     "mutation": "MUT-3-01"},
    {"id": "FO-C-02", "name": "T-FIN-CANONICAL-JSON", "fn": c02,
     "fixture": "F-12",
     "expected_code": "(a) path JSON rifiutato · (b) module_id/ruolo non "
                      "conforme al profilo, NOMINATO",
     "mutation": "MUT-3-02"},
    {"id": "FO-C-03", "name": "T-FIN-CANONICAL-MODULES", "fn": c03,
     "fixture": "F-12", "expected_code": "module_id omesso o duplicato",
     "mutation": "MUT-3-03"},
    {"id": "FO-C-04", "name": "T-FIN-GOVERNANCE-CANONICAL", "fn": c04,
     "fixture": "F-12",
     "expected_code": "module_id omesso o sconosciuto, NOMINATO",
     "mutation": "MUT-3-04"},
    {"id": "FO-C-05", "name": "T-FIN-GOVERNANCE-SCENARIOS", "fn": c05,
     "fixture": "F-1, F-3",
     "expected_code": "scenario col valore preso in prestito",
     "mutation": "MUT-3-05"},
    {"id": "FO-C-06", "name": "T-FIN-GOVERNANCE-MINIMUM", "fn": c06,
     "fixture": "F-1 con `placeholder` opzionale consumato",
     "expected_code": "DRV-* opzionale escluso", "mutation": "MUT-3-06"},
    {"id": "FO-C-07", "name": "T-FIN-GOVERNANCE-NO-NUMBERS", "fn": c07,
     "fixture": "F-12", "expected_code": "path e valore iniettati",
     "mutation": "MUT-3-07"},
    {"id": "FO-C-08", "name": "T-FIN-FORMULA-PROVENANCE", "fn": c08,
     "fixture": "demo + F-12", "expected_code": "rec_id e campo fuorviante",
     "mutation": "MUT-3-08"},
    {"id": "FO-C-09", "name": "T-FIN-TIMING-SHIFT", "fn": c09,
     "fixture": "F-1 con driver `timing_like` derivato in-modulo",
     "expected_code": "DRV-* e finestra risultante", "mutation": "MUT-3-09"},
    {"id": "FO-C-10", "name": "T-FIN-TIMING-OUT-OF-HORIZON", "fn": c10,
     "fixture": "F-1 derivata, finestra [2,3] terna 0/2/9",
     "expected_code": CODE_TIMING_WINDOW_EMPTY,
     "mutation": "MUT-3-10"},
    {"id": "FO-C-11", "name": "T-FIN-INVESTOR-READINESS", "fn": c11,
     "fixture": "F-12, F-3", "expected_code": "predicato violato, NOMINATO",
     "mutation": "MUT-3-11"},
    {"id": "FO-C-12", "name": "T-FIN-MATERIALITY-CARRIER", "fn": c12,
     "fixture": "F-12", "expected_code": "DRV-* e valore sostituito",
     "mutation": "MUT-3-12"},
    {"id": "FO-C-13", "name": "T-FIN-SOURCE-TYPE-CARRIER", "fn": c13,
     "fixture": "F-12",
     "expected_code": "enum divergente da source-register",
     "mutation": "MUT-3-13"},
    {"id": "FO-C-14", "name": "T-FIN-USE-OF-PROCEEDS-CANDIDATES",
     "fn": c14, "fixture": "F-12",
     "expected_code": "categoria e campo vietato; path rifiutato dallo schema",
     "mutation": "MUT-3-14"},
    {"id": "FO-C-15", "name": "T-FIN-NO-SILENT-ASSUMPTION", "fn": c15,
     "fixture": "F-3, F-9", "expected_code": "DRV-* e caveat riassorbito",
     "mutation": "MUT-3-15"},
    {"id": "FO-C-16", "name": "T-FIN-CANONICAL-NO-RECOMPUTE", "fn": c16,
     "fixture": "sorgente + sorgente sintetico di auto-sonda",
     "expected_code": "(a) file e riga · (b) auto-sonda che NON rileva",
     "mutation": "MUT-3-16"},
    {"id": "FO-C-17", "name": "T-FIN-CANONICAL-ATOMIC-WRITE", "fn": c17,
     "fixture": "F-12", "expected_code": "path parziale trovato",
     "mutation": "MUT-3-17"},
    {"id": "FO-C-18", "name": "T-FIN-CANONICAL-STALE-GUARD", "fn": c18,
     "fixture": "F-13(d)", "expected_code": CODE_STALE,
     "mutation": "MUT-3-18"},
    {"id": "FO-C-19", "name": "T-FIN-ENGINE-CANONICAL-BOUNDARY", "fn": c19,
     "fixture": "F-12", "expected_code": "blocco non mappato, NOMINATO",
     "mutation": "MUT-3-19"},
    {"id": "FO-C-20", "name": "T-FIN-WORKFLOW-CONTRACT", "fn": c20,
     "fixture": "file", "expected_code": "file e voce mancante",
     "mutation": "MUT-3-20"},
    {"id": "FO-C-21", "name": "T-FIN-NO-STAGE-11-ARTIFACTS", "fn": c21,
     "fixture": "copie isolate del repository a release_boundary forzato",
     "expected_code": "token respinto e boundary, NOMINATI",
     "mutation": "MUT-3-21"},
    {"id": "FO-C-22", "name": "T-FIN-M5A-NO-DERIVED", "fn": c22,
     "fixture": "(a) albero · (b) F-11 variante invalida derivata in-modulo",
     "expected_code": "(a) path trovato · (b) path scritto e codice attribuito",
     "mutation": "MUT-3-22"},
]

CONTRACT_IDS = tuple(entry["id"] for entry in CONTRACTS)


# --------------------------------------------------------------------------
# Esecuzione
# --------------------------------------------------------------------------


def run_one(ctx, contract):
    with tempfile.TemporaryDirectory(prefix="fin_output_") as base:
        try:
            findings = contract["fn"](ctx, Path(base))
        except HarnessDefect:
            raise
        except (AssertionError, AttributeError, IndexError, KeyError,
                OSError, TypeError, ValueError) as exc:
            findings = [f"errore di valutazione del contratto: {exc!r}"]
    return {"contract": contract, "red": bool(findings), "findings": findings}


def format_line(result):
    contract = result["contract"]
    return ("{state:<5} {cid:<12} {name:<36} fixture={fixture} | EXPECTED: "
            "{exp} | mutazione={mut} | reason={reason}".format(
                state="RED" if result["red"] else "GREEN",
                cid=contract["id"], name=contract["name"],
                fixture=contract["fixture"], exp=contract["expected_code"],
                mut=contract["mutation"],
                reason="; ".join(result["findings"]) or "-"))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(
        prog="test_fin_output.py", add_help=True,
        description="Contratti dell'output canonico dello Stage 10.")
    parser.add_argument("--root", required=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--contract", help="esegue un solo contratto")
    mode.add_argument("--all", action="store_true",
                      help="esegue tutti i contratti (default)")
    parser.add_argument("--list", action="store_true",
                        help="elenca gli id dei contratti ospitati qui")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE

    if args.list:
        for contract_id in CONTRACT_IDS:
            print(contract_id)
        return EXIT_OK

    try:
        root = resolve_root(args.root)
    except HarnessUsageError as exc:
        print(f"USAGE ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.contract and args.contract not in CONTRACT_IDS:
        print(f"USAGE ERROR: contratto inesistente: {args.contract}; ammessi: "
              f"{', '.join(CONTRACT_IDS)}", file=sys.stderr)
        return EXIT_USAGE

    global ENG
    try:
        ENG = load_engine_harness(root)
        ctx = build_context(root)
        selected = [entry for entry in CONTRACTS
                    if not args.contract or entry["id"] == args.contract]
        results = [run_one(ctx, entry) for entry in selected]
    except HarnessDefect as exc:
        print(f"HARNESS DEFECT: {exc}", file=sys.stderr)
        return EXIT_STATE
    except HarnessUsageError as exc:
        print(f"USAGE ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE

    for result in results:
        print(format_line(result))
    red = [result for result in results if result["red"]]
    print("SUMMARY: {total} contratti, {red} RED, {green} GREEN "
          "(costruttore {b}: {bs}; validator {v}: {vs})".format(
              total=len(results), red=len(red), green=len(results) - len(red),
              b=BUILDER_REL,
              bs="presente" if ctx["builder"].is_file() else "ASSENTE",
              v=OUTPUT_VALIDATOR_REL,
              vs="presente" if ctx["validator"].is_file() else "ASSENTE"))
    if red:
        return EXIT_RED
    print("PASS: T-FIN-OUTPUT {n} contratti dell'output canonico dello "
          "Stage 10".format(n=len(results)))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
