#!/usr/bin/env python3
"""T-DOCGEN — i VENTI contratti dello Stage 13 (`DG-C-01`...`-20`).

Modulo di test dello Stage 13 `13_document-generation`, ultimo stage di
`stage_order`, costruito sullo stesso modello di
`tests/integration/test_data_room.py` e
`tests/integration/test_funding_request.py`. Entra nel glob di ENTRAMBI i
runner (`tests/run-tests.ps1` e `tests/run-tests.sh` globano
`tests/integration/test_*.py`) senza alcuna modifica ai runner.

PERIMETRO. Il commit di `advance-stage` dello Stage 13 porta il progetto
allo stato terminale del piano; `--publish` scrive poi il derivato
`output/business-plan.md`. Il documento e' un'istantanea datata: dopo il
completamento la fase impact segnala i valori divergenti come warning.

RED SEMANTICO, MAI UN'ECCEZIONE. Ogni contratto valuta le PROPRIE aspettative
e le riporta come constatazioni ATTRIBUITE. Le superfici di produzione assenti
sono lette in modo difensivo: il validator assente, il modulo non importabile
o lo schema mancante diventano constatazioni NOMINATE, mai un `ImportError`
nudo. `run_one` conta a parte le constatazioni prodotte per ECCEZIONE e
l'uscita le stampa (`BY_EXCEPTION`): la loro somma DEVE essere zero, altrimenti
il RED non e' evidenza.

NON-VACUITA'. Un contratto e' GREEN solo con almeno un'osservazione valutata e,
quando dichiara mutanti, con ALMENO UN mutante UCCISO dal proprio codice. Non
esiste alcun framework di mutazione dedicato: ogni contratto porta il
proprio mutante mirato.

I VENTI CONTRATTI
-----------------
    DG-C-01  T-DOCGEN-CONTRACT            DG-C-11  T-DOCGEN-UNTRACED
    DG-C-02  T-DOCGEN-CHAIN               DG-C-12  T-DOCGEN-STRUCTURE
    DG-C-03  T-DOCGEN-INPUT-STALE         DG-C-13  T-DOCGEN-SECRETS
    DG-C-04  T-DOCGEN-FINANCIAL-BASIS     DG-C-14  T-DOCGEN-CONTAINMENT
    DG-C-05  T-DOCGEN-FUNDING-BINDING     DG-C-15  T-DOCGEN-TM-TERMINAL
    DG-C-06  T-DOCGEN-FINANCIAL-VALUES    DG-C-16  T-DOCGEN-BOUNDARY-MACHINERY
    DG-C-07  T-DOCGEN-MILESTONES          DG-C-17  T-DOCGEN-PUBLISH
    DG-C-08  T-DOCGEN-CLAIMS              DG-C-18  T-DOCGEN-IMPACT
    DG-C-09  T-DOCGEN-EPISTEMIC-LABELS    DG-C-19  T-DOCGEN-WORKFLOW
    DG-C-10  T-DOCGEN-DISCLOSURES         DG-C-20  T-DOCGEN-NO-RECOMPUTE

FIXTURE `DG-FIX`. Costruita UNA volta per esecuzione e copiata per ogni
caso, dalla SOLA catena di produzione: la pipeline dello Stage 10
(`test_fin_xlsx.prepare`), il `--build` reale dello Stage 11 e dello
Stage 12 e l'`advance-stage` reale del Transaction Manager per 11 e 12.
Le uscite degli Stage 4-9 sono la catena CANONICA di
`bpo_m5_fixtures` (la stessa che supera i validator di dominio in fase
impact), con gli identificatori `ASS-*` traslati di cento per non collidere con
i driver dello Stage 10; gli Stage 1-3 portano canonici di FORMA REALE. I
registri delle evidenze e delle fonti esistono PRIMA del `--build` dello
Stage 11, come in un progetto reale, e i canonici 1-9 sono scritti PRIMA del
`--build` dello Stage 12, che li indicizza e li pinna per checksum. Ogni
progetto vive in una directory TEMPORANEA: nessun progetto reale e' toccato.

Exit code del modulo: 0 tutti GREEN | 1 almeno un RED | 2 errore d'uso |
3 difetto di PREPARAZIONE dell'harness (non e' evidenza RED).
"""
import argparse
import ast
import copy
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

SKILL_REL = ".claude/skills/business-plan-orchestrator"
TESTKIT_REL = "tests/integration"
XLSX_HARNESS = "test_fin_xlsx"

DG_VALIDATOR_REL = f"{SKILL_REL}/validators/validate_document_generation.py"
DG_SCHEMA_REL = f"{SKILL_REL}/schemas/document-generation.schema.json"
DG_WORKFLOW_REL = f"{SKILL_REL}/workflows/14_document-generation.md"
DG_METHODOLOGY_REL = f"{SKILL_REL}/methodology/document-generation.md"
DG_AGENT_REL = f"{SKILL_REL}/runtime-agents/business-plan-writer.md"
FR_VALIDATOR_REL = f"{SKILL_REL}/validators/validate_funding_request.py"
DR_VALIDATOR_REL = f"{SKILL_REL}/validators/validate_data_room.py"
ENFORCEMENT_REL = f"{SKILL_REL}/config/enforcement-config.json"
TM_REL = f"{SKILL_REL}/transaction/transaction_manager.py"

STAGE10 = "10_financial-plan"
STAGE11 = "11_funding-request"
STAGE12 = "12_data-room"
STAGE13 = "13_document-generation"
ABSENT_STAGE = "14_after-terminal"

CANONICAL_NAME = "structured-output.json"
HANDOFF_NAME = "handoff.md"
PROPOSAL_NAME = "document-proposal.json"
OUTPUT_REL = "output/business-plan.md"
STATUS_REL = "shared/project-status.md"
ASSUMPTIONS_REL = "shared/assumptions-register.json"
EVIDENCE_REL = "shared/evidence-register.json"
SOURCE_REL = "shared/source-register.json"
CONDITIONS_REL = "shared/conditions-register.json"
RISK_REL = "shared/risk-register.json"
PROFILE_REL = "shared/startup-profile.json"

PROJECT_NAME = "turnilab"
TX10 = "tx-s13-s10"
TX11 = "tx-s13-s11"
TX12 = "tx-s13-s12"
TX13 = "tx-s13-001"

EXIT_OK = 0
EXIT_RED = 1
EXIT_USAGE = 2
EXIT_STATE = 3

# --------------------------------------------------------------------------
# Catalogo CHIUSO dei codici: diciotto `docgen_*` piu' i due
# preesistenti. Nessun altro codice e' ammesso in un report dello Stage 13.
# --------------------------------------------------------------------------

CODE_CHAIN = "docgen_chain_incomplete"
CODE_INPUT_MISSING = "docgen_input_missing"
CODE_INPUT_INVALID = "docgen_input_invalid"
CODE_INPUT_STALE = "docgen_input_stale"
CODE_FIN_BASIS = "docgen_financial_basis_stale"
CODE_REFERENCE = "docgen_reference_unresolved"
CODE_BINDING = "docgen_binding_divergent"
CODE_UNTRACED = "docgen_untraced_value"
CODE_PROMOTED = "docgen_assumption_promoted"
CODE_DISCLOSURE = "docgen_disclosure_suppressed"
CODE_HIGHLIGHT = "docgen_highlight_invalid"
CODE_PROPOSAL = "docgen_proposal_invalid"
CODE_STRUCTURE = "docgen_structure_invalid"
CODE_PLACEHOLDER = "docgen_placeholder_leak"
CODE_SECRET = "docgen_secret_leak"
CODE_NONDETERMINISTIC = "docgen_nondeterministic"
CODE_OUTPUT_STALE = "docgen_output_stale"
CODE_UPSTREAM = "docgen_upstream_mutated"
CODE_PATH_ESCAPE = "path_escape"
CODE_CORRUPTED = "corrupted_state"

CATALOG_CODES = frozenset((
    CODE_CHAIN, CODE_INPUT_MISSING, CODE_INPUT_INVALID, CODE_INPUT_STALE,
    CODE_FIN_BASIS, CODE_REFERENCE, CODE_BINDING, CODE_UNTRACED,
    CODE_PROMOTED, CODE_DISCLOSURE, CODE_HIGHLIGHT, CODE_PROPOSAL,
    CODE_STRUCTURE, CODE_PLACEHOLDER, CODE_SECRET, CODE_NONDETERMINISTIC,
    CODE_OUTPUT_STALE, CODE_UPSTREAM))
ALLOWED_CODES = CATALOG_CODES | {CODE_PATH_ESCAPE, CODE_CORRUPTED}

#: I DICIASSETTE capitoli, id e titoli COSTANTI, nell'ordine fisso del
#: documento (titoli in italiano, come tutta la prosa del prodotto).
CHAPTERS = (
    ("cap-01", "Executive summary"),
    ("cap-02", "Società e progetto"),
    ("cap-03", "Problema e bisogno del cliente"),
    ("cap-04", "Segmentazione dei clienti"),
    ("cap-05", "Soluzione e proposta di valore"),
    ("cap-06", "Analisi di mercato"),
    ("cap-07", "Scenario competitivo"),
    ("cap-08", "Modello di business"),
    ("cap-09", "Go-to-market"),
    ("cap-10", "Operations e tecnologia"),
    ("cap-11", "Proprietà intellettuale e difendibilità"),
    ("cap-12", "Team e governance"),
    ("cap-13", "Roadmap e milestone"),
    ("cap-14", "Analisi dei rischi"),
    ("cap-15", "Piano finanziario"),
    ("cap-16", "Richiesta di finanziamento e impiego dei fondi"),
    ("cap-17", "Appendice e indice della data room"),
)

#: Le etichette epistemiche del documento, verbatim.
EPISTEMIC_LABELS = {
    "founder_assumption": "(ipotesi del founder)",
    "model_estimate": "(stima)",
    "missing_information": "(dato mancante)",
    "unvalidated": "(da validare)",
}
EVIDENTIAL_CLASSES = ("verified_fact", "internal_evidence", "external_source")

#: Il predicato terminale del Transaction Manager dopo l'advance dello
#: Stage 13.
TERMINAL_TASK = "plan-complete"
TERMINAL_ACTION_PREFIX = "piano completato"

#: Ogni carattere del documento appartiene a una di tre classi: nessuna cifra
#: vive in un modello costante.
DIGIT_CATEGORIES = ("Nd", "Nl", "No")

#: Import ammessi al modulo di produzione (`DG-C-20`): libreria standard e
#: `_framework`, nient'altro.
STDLIB_ALLOWED = frozenset((
    "argparse", "hashlib", "json", "os", "re", "stat", "sys", "tempfile",
    "unicodedata", "datetime", "pathlib", "_framework", "__future__",
    "collections", "itertools", "functools", "string", "textwrap", "io",
    "copy"))
#: Token VIETATI nel sorgente del modulo di produzione: nessuna aritmetica,
#: nessuna conversione numerica (`DG-C-20`).
FORBIDDEN_RECOMPUTE = ("float(", "Decimal", "round(", "sum(",
                       "import decimal", "from decimal")

#: Il segreto di caso negativo (`DG-C-13`), spezzato perche' questo modulo non
#: porti un segreto letterale scansionabile.
SECRET_TOKEN = "sk-ant-" + "api03-" + "A" * 24
NON_ASCII_PREFIX = "Validare il prezzo «"

XLSX = None
KIT = None
M5 = None
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
    ctx["dg_validator"] = root / DG_VALIDATOR_REL
    ctx["fr_validator"] = root / FR_VALIDATOR_REL
    ctx["dr_validator"] = root / DR_VALIDATOR_REL
    return ctx


def dg_module(ctx):
    """Il modulo DI PRODUZIONE dello Stage 13, importato in SOLA LETTURA per
    le sonde in-process (renderer, quality gate, modelli). Assente prima
    dell'implementazione: `None`, mai un'eccezione."""
    if "module" in _CACHE:
        return _CACHE["module"]
    path = ctx["dg_validator"]
    module = None
    if path.is_file():
        validators_dir = str(path.parent)
        if validators_dir not in sys.path:
            sys.path.insert(0, validators_dir)
        try:
            module = load_file_module(path, "validate_document_generation_t")
        except Exception as exc:  # superficie in costruzione: constatazione
            _CACHE["module_error"] = repr(exc)
            module = None
    _CACHE["module"] = module
    return module


def module_or_finding(ctx, probe, observation):
    module = dg_module(ctx)
    if module is None:
        probe.findings.append(
            f"constatazione: {observation} — il modulo di produzione "
            f"{DG_VALIDATOR_REL} e' ASSENTE o non importabile "
            f"({_CACHE.get('module_error', 'file assente')})")
    return module


# --------------------------------------------------------------------------
# Utilita' pure: forme JSON, identita', path canonici
# --------------------------------------------------------------------------


def canonical_json(document):
    return json.dumps(document, indent=2, ensure_ascii=True,
                      sort_keys=True) + "\n"


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_of(path):
    return sha256_bytes(Path(path).read_bytes())


def read_json_or_none(path):
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def read_lexical(path):
    """Un canonico letto SENZA perdita lessicale: ogni numero resta la
    stringa sorgente."""
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      parse_float=str, parse_int=str)


def read_text_or_none(path):
    path = Path(path)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def identity_of(document):
    """Identita' DICHIARATA del canonico, calcolata qui per
    SPECIFICA: il payload e' `schema_version` piu' `document_generation`
    SENZA `rendering` e SENZA `identity`; serializzazione compatta a chiavi
    ordinate, `ensure_ascii`; `sha256`."""
    body = dict((document or {}).get("document_generation") or {})
    body.pop("rendering", None)
    body.pop("identity", None)
    payload = {"schema_version": (document or {}).get("schema_version"),
               "document_generation": body}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)
    return sha256_bytes(blob.encode("utf-8"))


PATH_TOKEN_RE = re.compile(
    r'\.([A-Za-z_][A-Za-z0-9_]*)|\[([0-9]+)\]|\["((?:[^"\\]|\\.)*)"\]')


def resolve_json_path(document, path):
    """Il resolver di SPECIFICA dei `json_path` del canonico: `$`, `.chiave`,
    `[indice]`, `["chiave"]`. Solleva `KeyError` se il path non risolve."""
    if not isinstance(path, str) or not path.startswith("$"):
        raise KeyError(path)
    node = document
    position = 1
    while position < len(path):
        match = PATH_TOKEN_RE.match(path, position)
        if not match:
            raise KeyError(path)
        try:
            if match.group(1) is not None:
                node = node[match.group(1)]
            elif match.group(2) is not None:
                node = node[int(match.group(2))]
            else:
                node = node[json.loads('"' + match.group(3) + '"')]
        except (KeyError, IndexError, TypeError):
            raise KeyError(path)
        position = match.end()
    return node


def gen(document):
    return (document or {}).get("document_generation") or {}


def chapters_of(document):
    return [item for item in gen(document).get("chapters") or ()
            if isinstance(item, dict)]


def bindings_of(document):
    return [item for item in gen(document).get("bindings") or ()
            if isinstance(item, dict)]


def binding_by_key(document, key):
    for item in bindings_of(document):
        if item.get("key") == key:
            return item
    return None


def blocks_of(chapter):
    for section in chapter.get("sections") or ():
        for block in section.get("blocks") or ():
            if isinstance(block, dict):
                yield block


def chapter_by_id(document, chapter_id):
    for item in chapters_of(document):
        if item.get("chapter_id") == chapter_id:
            return item
    return None


def chapter_binding_refs(document, chapter_id):
    chapter = chapter_by_id(document, chapter_id) or {}
    return {ref for block in blocks_of(chapter)
            for ref in block.get("binding_refs") or ()}


def markdown_chapter(markdown, number):
    """Il testo del capitolo `number` nel Markdown reso: dall'H2 `N. ` al
    successivo H2."""
    lines = (markdown or "").split("\n")
    out = []
    inside = False
    for line in lines:
        if line.startswith("## "):
            inside = line.startswith(f"## {number}. ")
            continue
        if inside:
            out.append(line)
    return "\n".join(out)


def expected_qualifier(record):
    """La qualifica epistemica DOVUTA a un record `ASS-*`."""
    klass = record.get("evidence_classification")
    if klass in ("founder_assumption", "model_estimate",
                 "missing_information"):
        return klass
    if klass in EVIDENTIAL_CLASSES and \
            record.get("validation_status") == "validated":
        return "none"
    return "unvalidated"


def has_digit(text):
    return any(unicodedata.category(char) in DIGIT_CATEGORIES
               for char in str(text))


# --------------------------------------------------------------------------
# Invocazione della produzione
# --------------------------------------------------------------------------


MISSING_VALIDATOR = (
    f"{DG_VALIDATOR_REL} ASSENTE: il modulo dello Stage 13 e' la SEDE del "
    "costruttore --build, del pubblicatore --publish e della validazione "
    "egress/impact")


def run_python(ctx, script, args, env_extra=None, cwd=None):
    command = [sys.executable, str(script)] + [str(item) for item in args]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if env_extra:
        env.update(env_extra)
    return subprocess.run(command, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          cwd=str(cwd or ctx["root"]), env=env)


def verdict_of(proc):
    report = None
    if proc.stdout.strip().startswith("{"):
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            report = None
    codes, warnings, messages, checks = [], [], {}, []
    if isinstance(report, dict):
        for entry in report.get("errors") or ():
            code = entry.get("code")
            if code:
                codes.append(code)
                messages.setdefault(code, []).append(
                    f"{entry.get('ref')} {entry.get('message')}")
        for entry in report.get("warnings") or ():
            if entry.get("code"):
                warnings.append(entry.get("code"))
        checks = list(report.get("checks") or ())
    return {"available": True, "exit_code": proc.returncode,
            "report": report, "codes": sorted(set(codes)),
            "warnings": sorted(set(warnings)), "messages": messages,
            "checks": checks, "stdout": proc.stdout, "stderr": proc.stderr}


def absent_verdict():
    return {"available": False, "exit_code": None, "report": None,
            "codes": [], "warnings": [], "messages": {}, "checks": [],
            "stdout": "", "stderr": MISSING_VALIDATOR}


def run_dg(ctx, args, env_extra=None):
    if not ctx["dg_validator"].is_file():
        return absent_verdict()
    return verdict_of(run_python(ctx, ctx["dg_validator"], args, env_extra))


def run_build(ctx, project, tx=TX13):
    return run_dg(ctx, ["--build", "--project", project, "--tx", tx])


def run_egress(ctx, project, candidate):
    return run_dg(ctx, ["--project", project, "--candidate", candidate,
                        "--stage", STAGE13, "--phase", "egress"])


def run_impact_cli(ctx, project):
    return run_dg(ctx, ["--project", project, "--stage", STAGE13,
                        "--phase", "impact"])


def run_publish(ctx, project):
    return run_dg(ctx, ["--publish", "--project", project])


def run_tm(ctx, *args, env_extra=None):
    return KIT.run_tm_cli(ctx["root"], *args, env_extra=env_extra)


def tm_json(out):
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {}


def tm_codes(out):
    return sorted({item.get("code") for item in
                   tm_json(out).get("errors") or ()})


def front_matter(ctx, project):
    text = read_text_or_none(Path(project) / STATUS_REL) or ""
    module = KIT.load_module(ctx["root"], KIT.VALIDATORS_REL, "_framework")
    return module.parse_front_matter(text)


def transaction_manager(ctx):
    return KIT.load_module(ctx["root"], KIT.TRANSACTION_REL,
                           "transaction_manager")


def message_text(verdict, code):
    return " ".join(verdict.get("messages", {}).get(code) or ())


def verdict_line(verdict):
    if not verdict.get("available", True):
        return MISSING_VALIDATOR
    return (f"exit {verdict.get('exit_code')}, codici {verdict.get('codes')}, "
            f"warning {verdict.get('warnings')}: "
            f"{(verdict.get('stderr') or '')[:160]!r}")


# --------------------------------------------------------------------------
# Fixture DG-FIX
# --------------------------------------------------------------------------


STARTUP_PROFILE = {
    "startup_type": "saas", "development_stage": "pre_seed",
    "primary_reader": "business_angel", "funding_type": "equity",
    "time_horizon": "24_months", "secondary_readers": ["bank"],
    "sector_notes": "Software di pianificazione dei turni per catene retail "
                    "italiane di piccole e medie dimensioni.",
    "dominant_metrics": ["ARR", "churn", "CAC"],
    "classification_confidence": "medium"}

#: Traslazione degli id della catena canonica di `bpo_m5_fixtures`
#: (ASS-001...036 ->
#: ASS-101...136): i driver dello Stage 10 occupano ASS-001...008.
ASS_SHIFT = 100
TAM_REF = "ASS-108"
SAM_REF = "ASS-110"
SOM_REF = "ASS-111"
PRICING_REF = "ASS-112"
CAC_REF = "ASS-123"
CHURN_REF = "ASS-124"
TIME_LOST_REF = "ASS-137"
MISSING_REF = "ASS-138"
UNVALIDATED_REF = "ASS-139"
DRIVER_REF = "ASS-001"


def extra_assumptions():
    """Record `ASS-*` degli Stage 1-3, uno per ogni etichetta epistemica non
    gia' coperta dalla catena di `bpo_m5_fixtures` (verificato e validato;
    dato mancante; da
    validare)."""
    base = {"source": "fixture document generation", "owner": "founder",
            "confidence": "medium", "last_updated": "2026-07-16",
            "previous_values": []}
    return [
        dict(base, id=TIME_LOST_REF, category="problem",
             variable="time_lost_hours_week",
             statement="Ore settimanali perse dal manager nella "
                       "pianificazione manuale dei turni",
             value=3.5, display_value="3.5 ore/settimana",
             unit="ore/settimana", validation_status="validated",
             evidence_classification="internal_evidence",
             evidence_refs=["EVD-001"],
             affected_sections=["01_problem-and-need"]),
        dict(base, id=MISSING_REF, category="segmentation",
             variable="restaurant_chains_count",
             statement="Numero di catene della ristorazione nel perimetro",
             value=None, display_value=None, unit="count",
             validation_status="needs_info",
             evidence_classification="missing_information",
             affected_sections=["02_customer-segmentation"]),
        dict(base, id=UNVALIDATED_REF, category="value_proposition",
             variable="scheduling_time_saved_share",
             statement="Quota del tempo di pianificazione risparmiata",
             value=0.7, display_value="0.7 ratio", unit="ratio",
             validation_status="unvalidated",
             evidence_classification="internal_evidence",
             affected_sections=["03_value-proposition"]),
    ]


STAGE1 = {"problem_statement": {
    "type": "cost",
    "description": "La pianificazione dei turni nelle catene retail "
                   "multi-punto-vendita e' manuale: fogli di calcolo e "
                   "messaggi, con errori di copertura scoperti all'ultimo "
                   "momento e ore perse dai manager ogni settimana.",
    "affected_roles": ["store manager", "titolare della catena"],
    "frequency": "weekly", "intensity": "high",
    "perceived_vs_demonstrated": "perceived_and_demonstrated",
    "time_lost_ref": TIME_LOST_REF,
    "alternatives": [
        {"name": "Fogli di calcolo e messaggistica",
         "why_insufficient": "richiedono lavoro manuale e non segnalano i "
                             "buchi di copertura"},
        {"name": "Suite enterprise di workforce management",
         "why_insufficient": "costi e tempi di adozione fuori scala per le "
                             "catene piccole e medie"}],
    "evidence_refs": ["EVD-001"]}}

STAGE2 = {
    "customer_segments": [
        {"id": "SEG-001",
         "name": "Catene retail con 5-50 punti vendita in Italia",
         "description": "Catene con pianificazione centralizzata dal "
                        "titolare o da un responsabile operativo",
         "roles": {"user": "store manager", "buyer": "titolare",
                   "decision_maker": "titolare",
                   "influencer": "responsabile operativo",
                   "payer": "titolare",
                   "gatekeeper": "consulente del lavoro"},
         "problem_ref": "01_problem-and-need",
         "problem_fit": "sostengono direttamente il costo delle ore perse",
         "accessibility": "associazioni di categoria e consulenti del lavoro",
         "buying_process": "demo, pilota su due punti vendita, estensione",
         "size_refs": ["ASS-101"], "evidence_refs": ["EVD-001"]},
        {"id": "SEG-002",
         "name": "Catene della ristorazione organizzata",
         "description": "Catene con turni su piu' fasce orarie e forte "
                        "stagionalita'",
         "roles": {"user": "responsabile di sala",
                   "buyer": "direttore operativo",
                   "decision_maker": "amministratore",
                   "payer": "amministratore"},
         "problem_ref": "01_problem-and-need",
         "problem_fit": "picchi stagionali difficili da coprire",
         "accessibility": "fiere di settore",
         "buying_process": "confronto informale tra fornitori",
         "size_refs": [MISSING_REF], "evidence_refs": []}],
    "beachhead": {
        "segment_ref": "SEG-001",
        "selection_criteria": "intensita' del problema e accessibilita' "
                              "tramite le associazioni",
        "rationale": "abbastanza grandi da pagare, abbastanza piccole da "
                     "decidere in fretta"}}

STAGE3 = {"value_proposition": {
    "id": "VP-001", "segment_ref": "SEG-001",
    "jobs": ["coprire i turni di tutti i punti vendita senza buchi",
             "gestire assenze e picchi stagionali"],
    "pains": ["ore di pianificazione manuale ogni settimana",
              "errori di copertura scoperti all'ultimo"],
    "gains": ["turni pubblicati in pochi minuti",
              "conformita' contrattuale verificata automaticamente"],
    "mapping": [
        {"pain": "pianificazione manuale",
         "reliever": "generazione automatica dei turni"},
        {"pain": "errori di copertura",
         "reliever": "avvisi su buchi e sovrapposizioni"},
        {"gain": "conformita' contrattuale",
         "creator": "regole contrattuali precaricate"}],
    "switching_rationale": "Rispetto ai fogli di calcolo riduce tempo ed "
                           "errori; rispetto alle suite enterprise costa "
                           "meno ed e' operativo in pochi giorni.",
    "value_metrics": [
        {"metric": "ore risparmiate a settimana", "ref": TIME_LOST_REF},
        {"metric": "quota del tempo di pianificazione risparmiata",
         "ref": UNVALIDATED_REF}],
    "proof_points": [
        {"claim": "i manager dedicano ore ogni settimana alla "
                  "pianificazione manuale",
         "evidence_classification": "internal_evidence",
         "evidence_refs": ["EVD-001"]},
        {"claim": "disponibilita' a pagare un abbonamento annuale",
         "evidence_classification": "founder_assumption",
         "evidence_refs": ["EVD-003"]}]}}

RISKS = [
    {"id": "RISK-001", "risk": "Interruzione del fornitore cloud unico",
     "category": "operational", "probability": "medium", "impact": "high",
     "severity": "high",
     "mitigation": "architettura multi-region e piano di uscita documentato",
     "contingency": "migrazione verso il secondo fornitore",
     "early_warning_indicator": "incidenti di disponibilita' ripetuti",
     "owner": "founder", "status": "open"},
    {"id": "RISK-002",
     "risk": "Adozione lenta nelle catene della ristorazione",
     "category": "market", "probability": "medium", "impact": "medium",
     "severity": "medium", "mitigation": "pilota gratuito su due locali",
     "owner": "founder", "status": "open"},
]


def evidence_entry(ref, statement, classification, status, date, affected):
    return {"id": ref, "statement": statement,
            "classification": classification, "status": status,
            "evidence_type": "document", "source": "fixture document generation",
            "date": date, "confidence": "medium", "relevance": "high",
            "affected_assumptions": list(affected),
            "affected_sections": [], "validation_action": "verificare"}


def evidence_register():
    return [
        evidence_entry("EVD-001", "Quattro titolari intervistati dichiarano "
                       "oltre tre ore settimanali di pianificazione.",
                       "internal_evidence", "validated", "2026-06-28",
                       [TIME_LOST_REF]),
        evidence_entry("EVD-002", "Il report di settore stima il mercato "
                       "italiano del workforce management per le PMI.",
                       "external_source", "validated", "2026-05-10",
                       [TAM_REF]),
        evidence_entry("EVD-003", "Il founder stima il costo di "
                       "acquisizione dai primi contatti commerciali.",
                       "founder_assumption", "open", "2026-07-01",
                       [CAC_REF]),
        evidence_entry("EVD-004", "Nessun dato di abbandono disponibile.",
                       "missing_information", "needs_info", "2026-07-10",
                       [CHURN_REF]),
        evidence_entry("EVD-005", "Studio precedente sul costo dei turni "
                       "non conformi.", "external_source", "validated",
                       "2024-01-15", [TAM_REF]),
        evidence_entry("EVD-006", "Nota interna non collegata ad alcun "
                       "claim.", "internal_evidence", "open", "2026-08-01",
                       []),
        evidence_entry("EVD-007", "Un secondo pilota non mostra alcuna "
                       "riduzione delle ore di pianificazione.",
                       "external_source", "validated", "2026-09-01",
                       [TIME_LOST_REF]),
    ]


def source_register():
    return [
        {"id": "SRC-001", "title": "Note delle interviste ai titolari",
         "source_type": "interview", "quality_rating": "medium",
         "url_or_path": "sources/interviste-titolari.md",
         "used_for": ["EVD-001", "EVD-003"]},
        {"id": "SRC-002", "title": "Report di settore sul workforce "
         "management", "publisher": "Osservatorio di settore",
         "publication_date": "2026-05-10", "source_type": "industry_report",
         "quality_rating": "high", "url_or_path": "sources/report-mercato.md",
         "used_for": ["EVD-002", "EVD-005"]},
        {"id": "SRC-003", "title": "Articolo di stampa", "source_type": "news",
         "quality_rating": "low", "url_or_path": "https://example.org/a",
         "used_for": []},
    ]


def conditions_register():
    return [
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


def data_room_proposal():
    return {
        "as_of": "2026-09-25", "max_age_days": 365,
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
             "evidence_refs": [], "last_verified_at": None}],
        "expected": [
            {"path": "sources/contratto-fornitore-cloud.pdf",
             "title": "Contratto quadro con il fornitore cloud",
             "artifact_type": "company",
             "section_id": "03_product-technology-operations-ip",
             "related_section": "07_operations-and-ip", "owner": "external",
             "validation_status": "needs_info"}],
        "claims": [
            {"key": "problem-hours",
             "statement": "I manager dedicano oltre tre ore a settimana alla "
                          "pianificazione manuale dei turni.",
             "related_section": "01_problem-and-need",
             "provenance": {"section": "01_problem-and-need",
                            "paragraph_anchor": None},
             "assumption_refs": [TIME_LOST_REF],
             "evidence_links": [
                 {"evidence_ref": "EVD-001",
                  "document_path": "sources/interviste-titolari.md",
                  "status": "supporting"},
                 {"evidence_ref": "EVD-007", "document_path": None,
                  "status": "contradicting"}]},
            {"key": "market-size",
             "statement": "Il mercato indirizzabile in Italia vale circa "
                          "dieci milioni di euro all'anno.",
             "related_section": "04_market-and-competition",
             "provenance": {"section": "04_market-and-competition",
                            "paragraph_anchor": None},
             "assumption_refs": [TAM_REF],
             "evidence_links": [
                 {"evidence_ref": "EVD-002",
                  "document_path": "sources/report-mercato.md",
                  "status": "supporting"},
                 {"evidence_ref": "EVD-005",
                  "document_path": "sources/report-mercato.md",
                  "status": "partial"}]},
            {"key": "cac",
             "statement": "Il costo di acquisizione si stabilizza sotto i "
                          "duecento euro per cliente.",
             "related_section": "06_go-to-market",
             "provenance": {"section": None, "paragraph_anchor": None},
             "assumption_refs": [CAC_REF],
             "evidence_links": [
                 {"evidence_ref": "EVD-003",
                  "document_path": "sources/interviste-titolari.md",
                  "status": "supporting"}]},
            {"key": "churn",
             "statement": "Il tasso di abbandono annuo resta sotto il "
                          "quindici per cento.",
             "related_section": "10_financial-plan",
             "provenance": {"section": "10_financial-plan",
                            "paragraph_anchor": None},
             "assumption_refs": [CHURN_REF],
             "evidence_links": [
                 {"evidence_ref": "EVD-004", "document_path": None,
                  "status": "missing"}]},
        ],
    }


#: Allocazione dei `CLM-*` della Data Room: (ordinale della related_section,
#: chiave). `CLM-001` contestato da due evidenze opposte (conflitto
#: `ISSUE-DR-001`), `CLM-002` supportato, `CLM-003`/`-004` non supportati.
CONTESTED_CLAIMS = ("CLM-001",)
SUPPORTED_CLAIMS = ("CLM-002",)
UNSUPPORTED_CLAIMS = ("CLM-003", "CLM-004")
CONFLICT_ISSUE = "ISSUE-DR-001"


def default_proposal():
    return {"as_of": "2026-09-29", "version_label": "versione per investitori",
            "highlights": {"milestone_refs": ["MIL-001", "MIL-003"],
                           "claim_refs": list(SUPPORTED_CLAIMS)}}


def shift_ids(node):
    pattern = re.compile(r"^ASS-([0-9]{3})$")
    if isinstance(node, dict):
        return {key: shift_ids(value) for key, value in node.items()}
    if isinstance(node, list):
        return [shift_ids(value) for value in node]
    if isinstance(node, str):
        match = pattern.match(node)
        if match:
            return f"ASS-{int(match.group(1)) + ASS_SHIFT:03d}"
    return node


def base_fixture(ctx):
    """`DG-FIX`, UNA volta per esecuzione del modulo."""
    if "base" in _CACHE:
        return _CACHE["base"]
    holder = Path(tempfile.mkdtemp(prefix="s13_dg_"))
    _CACHE["holder"] = holder
    case = XLSX.prepare(ctx, holder, name=PROJECT_NAME, level="full", tx=TX10)
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
    register = json.loads((project / ASSUMPTIONS_REL).read_text(
        encoding="utf-8"))
    chain = (M5.market_assumptions() + M5.business_assumptions()
             + M5.gtm_assumptions() + M5.ops_assumptions()
             + M5.team_assumptions() + M5.milestone_assumptions())
    register = register + shift_ids(chain) + extra_assumptions()
    (project / ASSUMPTIONS_REL).write_text(
        json.dumps(register, indent=2, ensure_ascii=True, sort_keys=True),
        encoding="utf-8")
    stages = (("01_problem-and-need", STAGE1),
              ("02_customer-segmentation", STAGE2),
              ("03_value-proposition", STAGE3),
              ("04_market-and-competition", shift_ids(M5.market_structured())),
              ("05_business-model", shift_ids(M5.business_structured())),
              ("06_go-to-market", shift_ids(M5.gtm_structured())),
              ("07_operations-and-ip",
               shift_ids(M5.canonical_operations_structured())),
              ("08_team-and-governance",
               shift_ids(M5.canonical_team_structured())),
              ("09_roadmap-and-milestones",
               shift_ids(M5.canonical_milestone_structured())))
    for stage, document in stages:
        write_json(project / stage / CANONICAL_NAME, document)
        (project / stage / HANDOFF_NAME).write_text(
            f"# Handoff — {stage}\n\nStage approvato: canonico pubblicato.\n"
            "\nnext_action: stage successivo.\n", encoding="utf-8")
    write_json(project / RISK_REL, RISKS)
    write_json(project / PROFILE_REL, STARTUP_PROFILE)
    write_json(project / EVIDENCE_REL, evidence_register())
    write_json(project / SOURCE_REL, source_register())
    write_json(project / CONDITIONS_REL, conditions_register())
    sources = project / "sources"
    sources.mkdir(exist_ok=True)
    (sources / "interviste-titolari.md").write_text(
        "# Interviste ai titolari\n\nQuattro titolari di catena intervistati "
        "tra giugno e luglio.\n", encoding="utf-8")
    (sources / "report-mercato.md").write_text(
        "# Report di settore\n\nDimensione del mercato italiano.\n",
        encoding="utf-8")
    (sources / "loi-cliente-alfa.md").write_text(
        "# Lettera d'intenti — cliente Alfa\n\nPilota non vincolante.\n",
        encoding="utf-8")
    (project / "output").mkdir(exist_ok=True)
    built = run_python(ctx, ctx["fr_validator"],
                       ["--build", "--project", project, "--tx", TX11])
    if built.returncode != 0:
        raise HarnessDefect(
            "il costruttore di produzione dello Stage 11 non ha prodotto la "
            f"funding request: {built.stdout[:300]} {built.stderr[:300]}")
    order = ctx["config"]["stage_order"]
    completed = sorted((stage for stage in order
                        if int(order[stage]) < int(order[STAGE11])),
                       key=lambda stage: int(order[stage]))
    (project / STATUS_REL).write_text(
        KIT.project_status_text(PROJECT_NAME, STAGE11, "in_progress",
                                completed), encoding="utf-8")
    exit_code, out, err = run_tm(
        ctx, "advance-stage", "--project", project, "--stage", STAGE11,
        "--candidate", project / STAGE11 / ".working" / TX11,
        "--gate-result", "approved")
    if exit_code != 0:
        raise HarnessDefect(
            "l'advance-stage REALE dello Stage 11 e' fallito: "
            f"{out.strip()[:300]} {err.strip()[:300]}")
    candidate = project / STAGE12 / ".working" / TX12
    write_json(candidate / "data-room-proposal.json", data_room_proposal())
    built = run_python(ctx, ctx["dr_validator"],
                       ["--build", "--project", project, "--tx", TX12])
    if built.returncode != 0:
        raise HarnessDefect(
            "il costruttore di produzione dello Stage 12 non ha prodotto la Data "
            f"Room: {built.stdout[:600]} {built.stderr[:300]}")
    exit_code, out, err = run_tm(
        ctx, "advance-stage", "--project", project, "--stage", STAGE12,
        "--candidate", candidate, "--gate-result", "approved")
    if exit_code != 0:
        raise HarnessDefect(
            "l'advance-stage REALE dello Stage 12 e' fallito: "
            f"{out.strip()[:300]} {err.strip()[:300]}")
    front = front_matter(ctx, project)
    if front.get("current_stage") != STAGE13 or \
            STAGE12 not in (front.get("completed_stages") or []):
        raise HarnessDefect(f"DG-FIX non e' a current_stage {STAGE13}: {front}")
    room = read_json_or_none(project / STAGE12 / CANONICAL_NAME) or {}
    claims = {claim.get("claim_id"): claim.get("support_status")
              for claim in (room.get("data_room") or {}).get("claims") or ()}
    expected = {ref: "supported" for ref in SUPPORTED_CLAIMS}
    expected.update({ref: "unsupported" for ref in UNSUPPORTED_CLAIMS})
    expected.update({ref: "contested" for ref in CONTESTED_CLAIMS})
    if claims != expected:
        raise HarnessDefect(f"DG-FIX: claim della Data Room inattesi: {claims}")
    _CACHE["base"] = project
    return project


def fresh(ctx, name):
    """Copia PROFONDA di DG-FIX: ogni caso e ogni mutazione agiscono qui."""
    target = Path(tempfile.mkdtemp(prefix=f"{name[:10]}_",
                                   dir=_CACHE.get("holder")))
    project = target / PROJECT_NAME
    shutil.copytree(base_fixture(ctx), project)
    return project


def stage_proposal(project, tx=TX13, proposal=None):
    candidate = Path(project) / STAGE13 / ".working" / tx
    candidate.mkdir(parents=True, exist_ok=True)
    write_json(candidate / PROPOSAL_NAME,
               default_proposal() if proposal is None else proposal)
    return candidate


def build_case(ctx, name, proposal=None, prepare=None):
    """Una copia di DG-FIX con la proposta del writer e il `--build` di
    produzione: progetto, candidate, canonico, handoff ed egress."""
    project = fresh(ctx, name)
    if prepare is not None:
        prepare(project)
    candidate = stage_proposal(project, proposal=proposal)
    case = {"project": project, "candidate": candidate}
    case["build"] = run_build(ctx, project)
    case["raw"] = read_text_or_none(candidate / CANONICAL_NAME)
    case["document"] = read_json_or_none(candidate / CANONICAL_NAME)
    case["handoff"] = read_text_or_none(candidate / HANDOFF_NAME)
    return case


def built(ctx, key="default"):
    cache_key = f"built-{key}"
    if cache_key not in _CACHE:
        case = build_case(ctx, key)
        case["egress"] = run_egress(ctx, case["project"], case["candidate"]) \
            if case["document"] is not None else absent_verdict()
        _CACHE[cache_key] = case
    return _CACHE[cache_key]


def completed(ctx):
    """DG-FIX COMPLETATA: `--build`, `advance-stage` terminale del TM reale e
    `--publish`, in cache."""
    if "completed" in _CACHE:
        return _CACHE["completed"]
    case = build_case(ctx, "completed")
    project = case["project"]
    case["before_advance"] = project_fingerprint(project)
    case["advance"] = run_tm(
        ctx, "advance-stage", "--project", project, "--stage", STAGE13,
        "--candidate", case["candidate"], "--gate-result", "approved")
    case["after_advance"] = project_fingerprint(project)
    case["publish"] = run_publish(ctx, project)
    case["after_publish"] = project_fingerprint(project)
    case["canonical"] = project / STAGE13 / CANONICAL_NAME
    case["output"] = project / OUTPUT_REL
    _CACHE["completed"] = case
    return case


def not_built(case, findings, observation):
    build = case.get("build") or {}
    if not build.get("available", True):
        findings.append(f"constatazione: {observation} — {MISSING_VALIDATOR}")
        return True
    if case.get("document") is None:
        findings.append(
            f"constatazione: {observation} — --build non ha prodotto il "
            f"canonico ({verdict_line(build)})")
        return True
    return False


#: Aree PROPRIE dello Stage 13 e del Transaction Manager: tutto il resto del
#: progetto deve restare byte-identico (`DG-P-09`).
OWN_AREAS = (f"{STAGE13}/", OUTPUT_REL, "shared/.tx/", STATUS_REL,
             "shared/audit-log.jsonl")


def is_link(path):
    path = Path(path)
    try:
        return path.is_symlink() or path.is_junction()
    except OSError:
        return False


def project_fingerprint(project, own=OWN_AREAS):
    out = {}
    root = Path(project)
    stack = [root]
    while stack:
        current = stack.pop()
        for item in sorted(current.iterdir()):
            if is_link(item):
                continue
            rel = item.relative_to(root).as_posix()
            if item.is_dir():
                if not any((rel + "/").startswith(area) for area in own
                           if area.endswith("/")):
                    stack.append(item)
            elif item.is_file():
                if any(rel == area or rel.startswith(area) for area in own):
                    continue
                out[rel] = sha256_of(item)
    return out


def make_link(link, target):
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(str(target), str(link), target_is_directory=True)


def drop_link(link):
    try:
        if os.name == "nt":
            os.rmdir(link)
        else:
            os.unlink(link)
    except OSError:
        pass


# --------------------------------------------------------------------------
# Contabilita' dei contratti
# --------------------------------------------------------------------------


class Probe:
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
        self.runs.append({"mutation": mutation, "label": label,
                          "expected": expected, "codes": codes,
                          "exit_code": verdict.get("exit_code"),
                          "killed": killed})
        unknown = sorted(set(codes) - ALLOWED_CODES)
        self.check(not unknown,
                   f"{label}: codici FUORI dal catalogo chiuso: {unknown}")
        self.check(killed, f"{mutation} {label}: atteso exit 1 con "
                           f"{expected}, ottenuto {verdict_line(verdict)}")
        return killed


def reseal(ctx, document):
    """Il candidate MUTATO resta formalmente coerente: identita' e impronta
    della resa ricalcolate, cosi' che il rifiuto sia attribuibile alla
    mutazione e non a un sigillo rotto."""
    body = gen(document)
    identity = body.get("identity")
    if isinstance(identity, dict):
        identity["payload_sha256"] = identity_of(document)
    module = dg_module(ctx)
    rendering = body.get("rendering")
    if module is not None and isinstance(rendering, dict):
        try:
            rendering["markdown_sha256"] = sha256_bytes(
                module.render_markdown(document).encode("utf-8"))
        except Exception:  # la resa di un mutante puo' fallire: e' un esito
            pass
    return document


def mutant_egress(ctx, case, mutate, label):
    """Egress REALE su una COPIA del candidate con il canonico MUTATO."""
    if case.get("document") is None:
        return absent_verdict() if not ctx["dg_validator"].is_file() else \
            {"available": True, "exit_code": None, "codes": [],
             "warnings": [], "messages": {}, "checks": [],
             "stderr": "canonico di partenza assente", "stdout": ""}
    target = Path(tempfile.mkdtemp(prefix="mut_", dir=_CACHE.get("holder")))
    project = target / PROJECT_NAME
    shutil.copytree(case["project"], project)
    candidate = project / STAGE13 / ".working" / TX13
    document = copy.deepcopy(case["document"])
    mutate(document)
    reseal(ctx, document)
    (candidate / CANONICAL_NAME).write_text(canonical_json(document),
                                            encoding="utf-8")
    module = dg_module(ctx)
    if module is not None:
        try:
            (candidate / HANDOFF_NAME).write_text(
                module.render_handoff(document), encoding="utf-8")
        except Exception:
            pass
    return run_egress(ctx, project, candidate)


def expect_rejected(probe, ctx, case, mutation, label, expected, mutate):
    verdict = mutant_egress(ctx, case, mutate, label)
    probe.record(mutation, label, verdict, expected)
    return verdict


def rewrite_json(path, mutate, ensure_ascii=False):
    path = Path(path)
    document = json.loads(path.read_text(encoding="utf-8"))
    mutate(document)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=ensure_ascii)
                    + "\n", encoding="utf-8")


def record_of(project, ref):
    register = json.loads((Path(project) / ASSUMPTIONS_REL).read_text(
        encoding="utf-8"))
    for index, entry in enumerate(register):
        if entry.get("id") == ref:
            return index, entry
    raise HarnessDefect(f"record {ref} assente dal registro di DG-FIX")


def template_block(document, chapter_id=None):
    for chapter in chapters_of(document):
        if chapter_id and chapter.get("chapter_id") != chapter_id:
            continue
        for block in blocks_of(chapter):
            if block.get("origin") == "template" and \
                    block.get("kind") == "paragraph":
                return block
    return None


def canonical_paragraph(document):
    for chapter in chapters_of(document):
        for block in blocks_of(chapter):
            if block.get("origin") == "canonical" and \
                    block.get("kind") == "paragraph":
                return block
    return None


def block_with_binding(document, binding_id, chapter_id=None):
    for chapter in chapters_of(document):
        if chapter_id and chapter.get("chapter_id") != chapter_id:
            continue
        for block in blocks_of(chapter):
            if binding_id in (block.get("binding_refs") or ()):
                return block
    return None


def rendered_markdown(ctx, document):
    module = dg_module(ctx)
    if module is None or document is None:
        return None
    try:
        return module.render_markdown(document)
    except Exception as exc:
        _CACHE["render_error"] = repr(exc)
        return None


# --------------------------------------------------------------------------
# DG-C-01 — T-DOCGEN-CONTRACT
# --------------------------------------------------------------------------


def c01(ctx):
    """Output richiesti, 17 capitoli ordinati, schema, identita' e
    determinismo (`DG-P-01`, `-02`, `-17`)."""
    probe = Probe("DG-C-01")
    probe.check((ctx["root"] / DG_SCHEMA_REL).is_file(),
                f"{DG_SCHEMA_REL} ASSENTE: lo schema del canonico e della "
                "proposta e' un artefatto obbligatorio")
    case = built(ctx)
    if not_built(case, probe.findings, "nessun documento finale costruito"):
        return probe
    probe.check(case["build"]["exit_code"] == EXIT_OK,
                f"--build su DG-FIX non riesce: {verdict_line(case['build'])}")
    probe.check(case["egress"]["exit_code"] == EXIT_OK,
                f"egress del candidate costruito non riesce: "
                f"{verdict_line(case['egress'])}")
    document = case["document"]
    probe.check(document.get("schema_version") == "1.0.0",
                f"schema_version {document.get('schema_version')!r}")
    probe.check(case["raw"] == canonical_json(document),
                "il canonico non e' nella forma deterministica del costruttore")
    probe.check(case["handoff"] is not None,
                "l'handoff canonico e' ASSENTE dal candidate")
    chapters = chapters_of(document)
    observed = [(item.get("chapter_id"), item.get("title"),
                 item.get("ordinal")) for item in chapters]
    expected = [(ref, title, position) for position, (ref, title) in
                enumerate(CHAPTERS, start=1)]
    probe.check(observed == expected,
                f"i capitoli non sono i DICIASSETTE capitoli nell'ordine "
                f"fisso: {observed}")
    identity = gen(document).get("identity") or {}
    probe.check(identity.get("payload_sha256") == identity_of(document),
                "l'identita' dichiarata non e' l'impronta di specifica del "
                "payload (schema_version + document_generation senza "
                "rendering e identity)")
    probe.check(identity.get("excluded_fields") == ["rendering"],
                f"excluded_fields {identity.get('excluded_fields')}")
    markdown = rendered_markdown(ctx, document)
    if probe.check(markdown is not None,
                   "la resa Markdown in memoria non e' producibile"):
        probe.check(sha256_bytes(markdown.encode("utf-8")) ==
                    (gen(document).get("rendering") or {})
                    .get("markdown_sha256"),
                    "rendering.markdown_sha256 non e' l'impronta della resa")
        probe.check(markdown.count("\n# ") + markdown.startswith("# ") == 1,
                    "la resa non ha esattamente UN titolo H1")
        headings = re.findall(r"^## ([0-9]+)\. (.+)$", markdown, re.M)
        probe.check([(int(n), t) for n, t in headings] ==
                    [(position, title) for position, (_ref, title) in
                     enumerate(CHAPTERS, start=1)],
                    f"gli H2 della resa non sono i diciassette capitoli: "
                    f"{headings}")
        probe.check(not re.search(r"^#### ", markdown, re.M),
                    "la resa contiene un titolo H4")
    # DG-P-17 — due esecuzioni COMPLETE producono byte identici.
    twin = built(ctx, "determinism")
    if not not_built(twin, probe.findings, "seconda costruzione assente"):
        probe.check(twin["raw"] == case["raw"],
                    "due costruzioni dagli stessi ingressi NON producono byte "
                    "identici del canonico")
        probe.check(twin["handoff"] == case["handoff"],
                    "due costruzioni NON producono byte identici dell'handoff")
        probe.check(rendered_markdown(ctx, twin["document"]) == markdown,
                    "due costruzioni NON producono byte identici della resa")
    # DG-P-01 — il derivato finale esiste dopo il ciclo di vita completo.
    done = completed(ctx)
    probe.check(done["output"].is_file(),
                f"{OUTPUT_REL} ASSENTE dopo --build, advance-stage e "
                f"--publish: {verdict_line(done['publish'])}")
    probe.check(done["canonical"].is_file() and
                (done["project"] / STAGE13 / HANDOFF_NAME).is_file(),
                "canonico o handoff dello Stage 13 non pubblicati dal TM")
    expect_rejected(
        probe, ctx, case, "MUT-01", "capitolo rimosso", CODE_STRUCTURE,
        lambda d: gen(d)["chapters"].pop(6))
    return probe


# --------------------------------------------------------------------------
# DG-C-02 — T-DOCGEN-CHAIN
# --------------------------------------------------------------------------


def status_prepare(current, completed_through):
    def prepare(project):
        order = sorted(KIT_ORDER(), key=lambda item: item[1])
        done = [stage for stage, ordinal in order
                if ordinal <= completed_through]
        (Path(project) / STATUS_REL).write_text(
            KIT.project_status_text(PROJECT_NAME, current, "in_progress",
                                    done), encoding="utf-8")
    return prepare


def KIT_ORDER():
    return [(stage, int(ordinal)) for stage, ordinal in
            _CACHE["config"]["stage_order"].items()]


def c02(ctx):
    """Precondizioni `XS-01` e ingressi obbligatori."""
    probe = Probe("DG-C-02")
    case = build_case(ctx, "c02-current", prepare=status_prepare(STAGE12, 11))
    probe.record("MUT-02", "current_stage diverso da 13", case["build"],
                 CODE_CHAIN)

    def gap(project):
        front_done = [stage for stage, ordinal in sorted(
            KIT_ORDER(), key=lambda item: item[1]) if ordinal <= 12 and
            stage != STAGE12]
        (Path(project) / STATUS_REL).write_text(
            KIT.project_status_text(PROJECT_NAME, STAGE13, "in_progress",
                                    front_done), encoding="utf-8")
    case = build_case(ctx, "c02-gap", prepare=gap)
    probe.record("MUT-02", "stage 12 mancante da completed_stages",
                 case["build"], CODE_CHAIN)

    def no_derived(project):
        (Path(project) / STAGE10 / "financial-plan.md").unlink()
    case = build_case(ctx, "c02-derived", prepare=no_derived)
    probe.record("MUT-02", "derivato financial-plan.md assente",
                 case["build"], CODE_INPUT_MISSING)
    probe.check(case["document"] is None,
                "un --build respinto ha PUBBLICATO il canonico nel candidate")
    positive = built(ctx)
    probe.check(positive["build"].get("exit_code") == EXIT_OK,
                f"controllo positivo: {verdict_line(positive['build'])}")
    return probe


# --------------------------------------------------------------------------
# DG-C-03 — T-DOCGEN-INPUT-STALE
# --------------------------------------------------------------------------


def c03(ctx):
    """Pin di byte sulla Data Room (`XS-02`) e drift dei registri (`XS-03`,
    `DG-P-07`)."""
    probe = Probe("DG-C-03")

    def stale(project):
        rewrite_json(Path(project) / "05_business-model" / CANONICAL_NAME,
                     lambda d: d["business_model"].update(
                         {"recurrence": "monthly"}))
    case = build_case(ctx, "c03-stale", prepare=stale)
    probe.record("MUT-03", "un byte di 05_business-model dopo la Data Room",
                 case["build"], CODE_INPUT_STALE)
    probe.check("INCOERENZA RILEVATA" in message_text(case["build"],
                                                      CODE_INPUT_STALE),
                "il rifiuto di pin non porta il blocco INCOERENZA RILEVATA")

    def drift(project):
        rewrite_json(Path(project) / EVIDENCE_REL,
                     lambda d: d[5].update({"statement": "Nota interna "
                                            "aggiornata dopo la Data Room."}))
    case = build_case(ctx, "c03-drift", prepare=drift)
    if not not_built(case, probe.findings, "drift di registro"):
        probe.check(case["build"]["exit_code"] == EXIT_OK,
                    f"il drift di un registro deve dare WARNING, non un "
                    f"blocco: {verdict_line(case['build'])}")
        probe.check(CODE_INPUT_STALE in case["build"]["warnings"],
                    "il drift del registro non e' un WARNING attribuito")
        body = gen(case["document"])
        probe.check(EVIDENCE_REL in (body.get("disclosures") or {}).get(
            "register_drift_since_data_room", []),
                    "il drift non e' divulgato in "
                    "disclosures.register_drift_since_data_room")
        entry = next((item for item in body.get("inputs") or ()
                      if item.get("path") == EVIDENCE_REL), {})
        probe.check(entry.get("data_room_match") == "register_drift",
                    f"inputs[] non marca il drift: {entry}")
        markdown = rendered_markdown(ctx, case["document"]) or ""
        probe.check(EVIDENCE_REL in markdown_chapter(markdown, 17),
                    "l'appendice 17.7 non nomina il registro modificato")
    base = built(ctx)
    if not not_built(base, probe.findings, "controllo dei pin"):
        body = gen(base["document"])
        room = read_json_or_none(base["project"] / STAGE12 / CANONICAL_NAME)
        indexed = {item.get("path"): item.get("checksum") for item in
                   (room.get("data_room") or {}).get("documents") or ()}
        pinned = [item for item in body.get("inputs") or ()
                  if item.get("path") in indexed]
        probe.check(bool(pinned) and all(
            item.get("sha256") == indexed[item.get("path")] or
            item.get("role") == "shared_register" for item in pinned),
                    "inputs[] non coincide con i checksum della Data Room")
        for rel in [f"{stage}/{CANONICAL_NAME}" for stage in
                    ("01_problem-and-need", "05_business-model", STAGE10,
                     STAGE11)] + [f"{STAGE10}/financial-model.xlsx",
                                  f"{STAGE11}/funding-request.md"]:
            entry = next((item for item in body.get("inputs") or ()
                          if item.get("path") == rel), None)
            probe.check(entry is not None and
                        entry.get("data_room_match") == "match" and
                        entry.get("sha256") == sha256_of(base["project"] /
                                                         rel),
                        f"ingresso immutabile {rel} non pinnato: {entry}")
    return probe


# --------------------------------------------------------------------------
# DG-C-04 — T-DOCGEN-FINANCIAL-BASIS
# --------------------------------------------------------------------------


def c04(ctx):
    """`XS-04`: il record `ASS-*` di un driver dello Stage 10 modificato dopo
    la Data Room blocca la costruzione (`DG-P-06`)."""
    probe = Probe("DG-C-04")

    def driver(project):
        def mutate(register):
            for entry in register:
                if entry.get("id") == DRIVER_REF:
                    entry["value"] = 120.0
        rewrite_json(Path(project) / ASSUMPTIONS_REL, mutate)
    case = build_case(ctx, "c04-basis", prepare=driver)
    probe.record("MUT-04", f"record {DRIVER_REF} di un driver modificato",
                 case["build"], CODE_FIN_BASIS)
    text = message_text(case["build"], CODE_FIN_BASIS)
    probe.check("INCOERENZA RILEVATA" in text and DRIVER_REF in text,
                "il blocco della base finanziaria non porta INCOERENZA "
                f"RILEVATA con il record nominato: {text[:300]!r}")
    probe.check(case["document"] is None,
                "una base finanziaria stantia ha prodotto un canonico")
    return probe


# --------------------------------------------------------------------------
# DG-C-05 — T-DOCGEN-FUNDING-BINDING
# --------------------------------------------------------------------------


def c05(ctx):
    """Importo, impieghi e runway = Stage 11 ovunque (`DG-P-04`, `-05`)."""
    probe = Probe("DG-C-05")
    case = built(ctx)
    if not_built(case, probe.findings, "nessun binding della funding request"):
        return probe
    request = read_lexical(case["project"] / STAGE11 / CANONICAL_NAME)[
        "funding_request"]
    document = case["document"]
    capital = binding_by_key(document, "funding.requested_capital.amount")
    if probe.check(capital is not None,
                   "nessun binding con chiave funding.requested_capital."
                   "amount"):
        probe.check(capital.get("value") ==
                    request["requested_capital"]["amount"] and
                    capital.get("currency") ==
                    request["requested_capital"]["currency"],
                    f"il capitale richiesto legato {capital} non e' quello "
                    "dello Stage 11")
        probe.check(capital["binding_id"] in chapter_binding_refs(
            document, "cap-01") and capital["binding_id"] in
            chapter_binding_refs(document, "cap-16"),
                    "executive summary e capitolo 16 NON usano lo STESSO "
                    "binding del capitale richiesto (XS-05)")
        markdown = rendered_markdown(ctx, document) or ""
        for number in (1, 16):
            probe.check(capital.get("rendered", "\0") in
                        markdown_chapter(markdown, number),
                        f"il letterale del capitale richiesto non compare "
                        f"nel capitolo {number}")
    for position, item in enumerate(request["use_of_proceeds"]):
        for field in ("amount", "percentage"):
            bound = binding_by_key(
                document, f"funding.use_of_proceeds.{position}.{field}")
            probe.check(bound is not None and
                        bound.get("value") == item[field],
                        f"impiego {position} {field}: binding {bound} "
                        f"diverso dallo Stage 11 {item[field]!r}")
    runway = binding_by_key(document,
                            "funding.runway.before_financing.runway_to_zero")
    probe.check(runway is not None and runway.get("value") ==
                request["runway"]["before_financing"]["runway_to_zero"],
                f"runway prima del finanziamento non legato: {runway}")
    if capital is not None:
        def mutate(d):
            for item in gen(d)["bindings"]:
                if item["key"] == "funding.requested_capital.amount":
                    item["value"] = "99999"
                    item["rendered"] = "99999 EUR"
        expect_rejected(probe, ctx, case, "MUT-05",
                        "capitale richiesto alterato nel candidate",
                        CODE_BINDING, mutate)
    return probe


# --------------------------------------------------------------------------
# DG-C-06 — T-DOCGEN-FINANCIAL-VALUES
# --------------------------------------------------------------------------

#: Radici AMMESSE del catalogo chiuso dello Stage 10.
FIN_CATALOG_RE = re.compile(
    r"^\$\.financial_plan\.(?:"
    r"results\.calendar\.(?:anchor_date|frequency|horizon_periods)"
    r"|results\.modules\.[a-z_]+\.(?:metrics\.[a-z_]+[a-z_0-9]*|status"
    r"|not_applicable_reason)"
    r"|results\.scenarios\.coverage\.(?:level|ratio|uncovered_driver_refs"
    r"(?:\[[0-9]+\])?)"
    r"|results\.scenarios\.(?:base|downside|upside)\.(?:status"
    r"|not_applicable_reason|summary\.[a-z_]+)"
    r"|validation\.(?:result|propagated_status|investor_readiness\.status"
    r"|investor_readiness\.blocking_reasons\[[0-9]+\]\.message"
    r"|warnings\[[0-9]+\]\.code))$")


def c06(ctx):
    """Catalogo chiuso dello Stage 10 reso VERBATIM (`DG-P-06`)."""
    probe = Probe("DG-C-06")
    case = built(ctx)
    if not_built(case, probe.findings, "nessun valore finanziario legato"):
        return probe
    plan = read_lexical(case["project"] / STAGE10 / CANONICAL_NAME)
    periods = {str(item.get("index")) for item in
               plan["financial_plan"]["results"]["calendar"]["periods"]}
    financial = [item for item in bindings_of(case["document"])
                 if (item.get("source") or {}).get("file") ==
                 f"{STAGE10}/{CANONICAL_NAME}"]
    probe.check(len(financial) >= 5,
                f"troppo pochi binding dello Stage 10: {len(financial)}")
    for item in financial:
        path = item["source"].get("json_path")
        try:
            leaf = resolve_json_path(plan, path)
        except KeyError:
            probe.check(False, f"{item.get('binding_id')}: json_path {path!r} "
                               "non risolve nel canonico dello Stage 10")
            continue
        probe.check(item.get("value") == leaf,
                    f"{item.get('binding_id')}: valore {item.get('value')!r} "
                    f"diverso dalla foglia {leaf!r}")
        probe.check(bool(FIN_CATALOG_RE.match(path or "")),
                    f"{item.get('binding_id')}: {path!r} FUORI dal catalogo "
                    "chiuso dello Stage 10")
        tail = str(path).rsplit(".", 1)[-1]
        suffix = tail.rsplit("_", 1)[-1] if "_" in tail else None
        probe.check(".metrics." not in str(path) or suffix not in periods,
                    f"{path!r} e' una chiave PER PERIODO: nessuna serie entra "
                    "nel documento")
    gap = binding_by_key(case["document"],
                         "financial.funding_gap.funding_gap_to_zero")
    probe.check(gap is not None and gap["binding_id"] in
                chapter_binding_refs(case["document"], "cap-01") and
                gap["binding_id"] in chapter_binding_refs(case["document"],
                                                          "cap-15"),
                "il fabbisogno non e' lo STESSO binding in executive summary "
                "e capitolo 15")
    if financial:
        target = financial[0]["binding_id"]

        def mutate(d):
            for item in gen(d)["bindings"]:
                if item["binding_id"] == target:
                    item["value"] = "123456.78"
                    item["rendered"] = "123456.78"
        expect_rejected(probe, ctx, case, "MUT-06",
                        "foglia dello Stage 10 alterata", CODE_BINDING,
                        mutate)
    return probe


# --------------------------------------------------------------------------
# DG-C-07 — T-DOCGEN-MILESTONES
# --------------------------------------------------------------------------


def c07(ctx):
    """Join 9 <-> 11 e highlight delle milestone (`XS-07`, `XS-12`)."""
    probe = Probe("DG-C-07")
    case = built(ctx)
    if not not_built(case, probe.findings, "nessuna milestone resa"):
        plan = read_json_or_none(case["project"] /
                                 "09_roadmap-and-milestones" / CANONICAL_NAME)
        markdown = rendered_markdown(ctx, case["document"]) or ""
        roadmap = markdown_chapter(markdown, 13)
        for milestone in plan["milestone_plan"]["milestones"]:
            probe.check(milestone["title"] in roadmap,
                        f"la milestone {milestone['id']} non e' resa nel "
                        "capitolo 13")
        selection = gen(case["document"]).get("selection") or {}
        probe.check(selection.get("milestone_refs") == ["MIL-001", "MIL-003"]
                    and selection.get("origin") == "proposal",
                    f"selezione delle milestone {selection}")
        probe.check("non coperta dalla richiesta" in roadmap,
                    "una milestone non finanziata non e' dichiarata «non "
                    "coperta dalla richiesta»")
    proposal = default_proposal()
    proposal["highlights"]["milestone_refs"] = ["MIL-999"]
    case = build_case(ctx, "c07-unknown", proposal=proposal)
    probe.record("MUT-07", "MIL-999 inesistente in proposta", case["build"],
                 CODE_HIGHLIGHT)
    proposal = default_proposal()
    proposal["highlights"]["milestone_refs"] = [
        "MIL-001", "MIL-002", "MIL-003", "MIL-004", "MIL-001", "MIL-002"]
    case = build_case(ctx, "c07-limit", proposal=proposal)
    probe.record("MUT-07", "sei milestone oltre il limite di cinque",
                 case["build"], CODE_HIGHLIGHT)
    return probe


# --------------------------------------------------------------------------
# DG-C-08 — T-DOCGEN-CLAIMS
# --------------------------------------------------------------------------


def claims_table(document):
    for chapter in chapters_of(document):
        if chapter.get("chapter_id") != "cap-17":
            continue
        for block in blocks_of(chapter):
            table = block.get("table") or {}
            if block.get("kind") == "table" and \
                    "Supporto" in (table.get("columns") or ()):
                return block
    return None


def c08(ctx):
    """Stato dei claim verbatim, highlight solo `supported`
    (`XS-09`, `DG-P-07`, `-08`)."""
    probe = Probe("DG-C-08")
    case = built(ctx)
    if not not_built(case, probe.findings, "nessun claim reso"):
        room = read_json_or_none(case["project"] / STAGE12 / CANONICAL_NAME)
        statuses = {claim["claim_id"]: claim["support_status"]
                    for claim in room["data_room"]["claims"]}
        block = claims_table(case["document"])
        if probe.check(block is not None,
                       "l'appendice 17.2 non porta la tabella dei claim con "
                       "la colonna «Supporto»"):
            columns = block["table"]["columns"]
            index = columns.index("Supporto")
            rows = {row[0]: row[index] for row in block["table"]["rows"]}
            probe.check(rows == statuses,
                        f"lo stato dei claim NON e' verbatim: {rows} contro "
                        f"{statuses}")
        body = gen(case["document"])
        probe.check((body.get("selection") or {}).get("claim_refs") ==
                    list(SUPPORTED_CLAIMS),
                    f"highlight {body.get('selection')}")
        probe.check((body.get("disclosures") or {}).get(
            "unsupported_claims") == list(UNSUPPORTED_CLAIMS),
                    "i claim non supportati non sono divulgati per nome")

        def promote(d):
            target = claims_table(d)
            position = target["table"]["columns"].index("Supporto")
            for row in target["table"]["rows"]:
                if row[0] == UNSUPPORTED_CLAIMS[0]:
                    row[position] = "supported"
        if block is not None:
            expect_rejected(probe, ctx, case, "MUT-08",
                            "stato del claim alterato nel candidate",
                            CODE_PROMOTED, promote)
    for label, refs in (("claim non supportato in highlight",
                         [UNSUPPORTED_CLAIMS[0]]),
                        ("claim contestato in highlight",
                         [CONTESTED_CLAIMS[0]]),
                        ("CLM-999 inventato", ["CLM-999"])):
        proposal = default_proposal()
        proposal["highlights"]["claim_refs"] = refs
        verdict = build_case(ctx, "c08-" + refs[0].lower(),
                             proposal=proposal)["build"]
        probe.record("MUT-08", label, verdict, CODE_HIGHLIGHT)
    return probe


# --------------------------------------------------------------------------
# DG-C-09 — T-DOCGEN-EPISTEMIC-LABELS
# --------------------------------------------------------------------------


def c09(ctx):
    """Nessuna assunzione promossa a fatto (`XS-10`, `DG-P-08`)."""
    probe = Probe("DG-C-09")
    case = built(ctx)
    if not_built(case, probe.findings, "nessuna etichetta epistemica resa"):
        return probe
    register = {entry["id"]: entry for entry in json.loads(
        (case["project"] / ASSUMPTIONS_REL).read_text(encoding="utf-8"))}
    markdown = rendered_markdown(ctx, case["document"]) or ""
    seen = set()
    for item in bindings_of(case["document"]):
        record_id = (item.get("source") or {}).get("record_id")
        if not record_id:
            continue
        record = register.get(record_id)
        if not probe.check(record is not None,
                           f"{item.get('binding_id')}: record {record_id} "
                           "non registrato"):
            continue
        qualifier = expected_qualifier(record)
        seen.add(qualifier)
        probe.check(item.get("qualifier") == qualifier,
                    f"{record_id}: qualifica {item.get('qualifier')!r} invece "
                    f"di {qualifier!r}")
        label = EPISTEMIC_LABELS.get(qualifier)
        if label:
            probe.check(str(item.get("rendered")).endswith(label),
                        f"{record_id}: letterale {item.get('rendered')!r} "
                        f"senza l'etichetta {label!r}")
        probe.check(str(item.get("rendered")) in markdown,
                    f"{record_id}: il letterale etichettato non compare nella "
                    "resa")
    probe.check({"none", "founder_assumption", "model_estimate",
                 "missing_information", "unvalidated"} <= seen,
                f"DG-FIX non esercita tutte le qualifiche: {sorted(seen)}")
    tam = binding_by_key(case["document"], f"register.{TAM_REF}")
    if probe.check(tam is not None, f"nessun binding del TAM {TAM_REF}"):
        def strip(d):
            for item in gen(d)["bindings"]:
                if item["key"] == f"register.{TAM_REF}":
                    item["qualifier"] = "none"
                    item["rendered"] = item["rendered"].replace(
                        " " + EPISTEMIC_LABELS["model_estimate"], "")
        expect_rejected(probe, ctx, case, "MUT-09", "etichetta del TAM rimossa",
                        CODE_PROMOTED, strip)
    return probe


# --------------------------------------------------------------------------
# DG-C-10 — T-DOCGEN-DISCLOSURES
# --------------------------------------------------------------------------


def c10(ctx):
    """Completezza delle disclosure (`XS-11`)."""
    probe = Probe("DG-C-10")
    case = built(ctx)
    if not_built(case, probe.findings, "nessuna disclosure resa"):
        return probe
    body = gen(case["document"])
    disclosures = body.get("disclosures") or {}
    probe.check("COND-001" in [item.get("condition_id") if
                               isinstance(item, dict) else item for item in
                               disclosures.get("open_conditions") or ()],
                f"COND-001 aperta non divulgata: "
                f"{disclosures.get('open_conditions')}")
    probe.check(disclosures.get("final_review") == "not_performed",
                "la review finale non e' dichiarata non eseguita")
    readiness = disclosures.get("financial_readiness") or {}
    probe.check(readiness.get("investor_readiness_status") == "not_ready",
                f"prontezza dello Stage 10 non divulgata: {readiness}")
    markdown = rendered_markdown(ctx, case["document"]) or ""
    summary = markdown_chapter(markdown, 1)
    for name in ("COND-001",) + UNSUPPORTED_CLAIMS + CONTESTED_CLAIMS:
        probe.check(name in summary,
                    f"{name} non e' NOMINATO nell'executive summary (ES-11)")
    appendix = markdown_chapter(markdown, 17)
    probe.check("INCOERENZA RILEVATA" in appendix and
                CONFLICT_ISSUE in appendix,
                f"il conflitto {CONFLICT_ISSUE} della Data Room non e' reso "
                "come blocco INCOERENZA RILEVATA in appendice")
    probe.check(disclosures.get("contested_claims") ==
                list(CONTESTED_CLAIMS) and
                disclosures.get("data_room_conflicts") == [CONFLICT_ISSUE],
                "claim contestati o conflitti non divulgati per nome")
    probe.check("COND-002" not in summary,
                "una condizione CHIUSA e' presentata fra le aperte")

    def suppress(d):
        """COND-001 cancellata dalle disclosure e dall'executive summary:
        le voci di elenco che la nominano spariscono, e un blocco rimasto
        senza voci e' rimosso."""
        body = gen(d)
        body["disclosures"]["open_conditions"] = [
            item for item in body["disclosures"]["open_conditions"]
            if (item.get("condition_id") if isinstance(item, dict)
                else item) != "COND-001"]
        chapter = next(item for item in body["chapters"]
                       if item["chapter_id"] == "cap-01")
        for section in chapter["sections"]:
            kept = []
            for block in section["blocks"]:
                if "COND-001" in str(block.get("text")):
                    continue
                items = block.get("items") or []
                if items:
                    block["items"] = [item for item in items
                                      if "COND-001" not in item]
                    if not block["items"]:
                        continue
                kept.append(block)
            section["blocks"] = kept
    expect_rejected(probe, ctx, case, "MUT-10",
                    "COND aperta rimossa dalla resa", CODE_DISCLOSURE,
                    suppress)
    return probe


# --------------------------------------------------------------------------
# DG-C-11 — T-DOCGEN-UNTRACED
# --------------------------------------------------------------------------


def c11(ctx):
    """La regola delle tre classi (`DG-P-03`, `RSK-S13-01`)."""
    probe = Probe("DG-C-11")
    module = module_or_finding(ctx, probe, "modelli costanti non ispezionabili")
    if module is not None:
        templates = getattr(module, "TEMPLATES", None)
        if probe.check(isinstance(templates, dict) and templates,
                       "il modulo non espone la tabella chiusa TEMPLATES"):
            with_digits = sorted(key for key, text in templates.items()
                                 if has_digit(text))
            probe.check(not with_digits,
                        f"modelli costanti CON cifre: {with_digits}")
    proposal = default_proposal()
    proposal["version_label"] = "versione 2 per investitori"
    probe.record("MUT-11", "cifra in version_label",
                 build_case(ctx, "c11-version", proposal=proposal)["build"],
                 CODE_UNTRACED)
    case = built(ctx)
    if not not_built(case, probe.findings, "nessun blocco di modello"):
        target = template_block(case["document"])
        if probe.check(target is not None,
                       "nessun blocco di modello nel canonico"):
            block_id = target["block_id"]

            def inject(d):
                for chapter in gen(d)["chapters"]:
                    for block in blocks_of(chapter):
                        if block["block_id"] == block_id:
                            block["text"] = block["text"] + " Crescita del 42."
            expect_rejected(probe, ctx, case, "MUT-11",
                            "cifra in un blocco di modello", CODE_UNTRACED,
                            inject)
        verbatim = canonical_paragraph(case["document"])
        if probe.check(verbatim is not None,
                       "nessun blocco verbatim nel canonico"):
            block_id = verbatim["block_id"]

            def rewrite(d):
                for chapter in gen(d)["chapters"]:
                    for block in blocks_of(chapter):
                        if block["block_id"] == block_id:
                            block["text"] = "Testo riscritto dal writer."
            expect_rejected(probe, ctx, case, "MUT-11",
                            "blocco verbatim riscritto", CODE_UNTRACED,
                            rewrite)
    return probe


# --------------------------------------------------------------------------
# DG-C-12 — T-DOCGEN-STRUCTURE
# --------------------------------------------------------------------------


def gate_codes(module, markdown, document):
    try:
        problems = module.markdown_problems(markdown, document)
    except Exception as exc:
        return {"exception": repr(exc)}
    return {code for code, _ref, _message in problems}


def c12(ctx):
    """Quality gate `QG-01`...`QG-10` sulla resa (`DG-P-02`)."""
    probe = Probe("DG-C-12")
    module = module_or_finding(ctx, probe, "quality gate non ispezionabili")
    case = built(ctx)
    if module is None or not_built(case, probe.findings,
                                   "nessuna resa da ispezionare"):
        return probe
    document = case["document"]
    markdown = rendered_markdown(ctx, document)
    if not probe.check(markdown is not None,
                       f"resa non producibile: {_CACHE.get('render_error')}"):
        return probe
    probe.check(gate_codes(module, markdown, document) == set(),
                "la resa reale non supera i quality gate: "
                f"{gate_codes(module, markdown, document)}")
    table_line = next((line for line in markdown.split("\n")
                       if line.startswith("| ") and "---" not in line), None)
    heading = next(line for line in markdown.split("\n")
                   if line.startswith("## 7. "))
    mutants = (
        ("capitolo duplicato", markdown.replace(
            heading, heading + "\n\n" + heading, 1), CODE_STRUCTURE),
        ("titolo H4", markdown.replace(heading, heading + "\n\n#### Extra\n",
                                       1), CODE_STRUCTURE),
        ("link d'indice rotto", markdown.replace("(#cap-05)",
                                                 "(#cap-99)", 1),
         CODE_STRUCTURE),
        ("tabella sbilanciata", markdown.replace(
            table_line, table_line + " extra |", 1) if table_line else
         markdown + "\n| a | b |\n|---|---|\n| c |\n", CODE_STRUCTURE),
        ("segnaposto {{", markdown.replace(heading, heading +
                                           "\n\nValore {{price}}.\n", 1),
         CODE_PLACEHOLDER),
        ("TODO", markdown.replace(heading, heading + "\n\nTODO completare.\n",
                                  1), CODE_PLACEHOLDER),
        ("path .working/", markdown.replace(
            heading, heading + f"\n\nVedi {STAGE13}/.working/tx/x.json\n", 1),
         CODE_PLACEHOLDER),
        ("None serializzato", markdown.replace(
            heading, heading + "\n\nValore: None\n", 1), CODE_PLACEHOLDER),
    )
    for label, mutated, expected in mutants:
        codes = gate_codes(module, mutated, document)
        killed = expected in codes if isinstance(codes, set) else False
        probe.runs.append({"mutation": "MUT-12", "label": label,
                           "expected": expected, "codes": sorted(codes) if
                           isinstance(codes, set) else [str(codes)],
                           "exit_code": EXIT_RED if killed else None,
                           "killed": killed})
        probe.check(killed, f"quality gate: {label} NON respinto con "
                            f"{expected}: {codes}")
    verbatim = canonical_paragraph(document)
    if verbatim is not None:
        block_id = verbatim["block_id"]

        def leak(d):
            for chapter in gen(d)["chapters"]:
                for block in blocks_of(chapter):
                    if block["block_id"] == block_id:
                        block["text"] = block["text"] + " TODO"
        expect_rejected(probe, ctx, case, "MUT-12",
                        "TODO nel testo del candidate", CODE_PLACEHOLDER, leak)
    return probe


# --------------------------------------------------------------------------
# DG-C-13 — T-DOCGEN-SECRETS
# --------------------------------------------------------------------------


def c13(ctx):
    """Segreto in un campo di registro dopo la Data Room, adiacente a un
    carattere non ASCII (lezione `DR-R-02`)."""
    probe = Probe("DG-C-13")

    def secret(project):
        rewrite_json(Path(project) / CONDITIONS_REL,
                     lambda d: d[0].update({"description": NON_ASCII_PREFIX +
                                            SECRET_TOKEN + "» su due catene"}))
    case = build_case(ctx, "c13-secret", prepare=secret)
    probe.record("MUT-13", "segreto dopo «", case["build"], CODE_SECRET)
    probe.check(case["document"] is None,
                "un --build con un segreto ha PUBBLICATO il canonico")
    probe.check(SECRET_TOKEN not in (case["build"].get("stdout") or ""),
                "il report ristampa il segreto rilevato")

    def control(project):
        rewrite_json(Path(project) / CONDITIONS_REL,
                     lambda d: d[0].update({"description": NON_ASCII_PREFIX +
                                            "senza credenziali» su due "
                                            "catene"}))
    case = build_case(ctx, "c13-control", prepare=control)
    probe.check(case["build"].get("exit_code") == EXIT_OK,
                "controllo: lo stesso campo SENZA segreto deve costruire: "
                f"{verdict_line(case['build'])}")
    return probe


# --------------------------------------------------------------------------
# DG-C-14 — T-DOCGEN-CONTAINMENT
# --------------------------------------------------------------------------


def c14(ctx):
    """Letture, scritture e immutabilita' (`DG-P-09`, `-10`)."""
    probe = Probe("DG-C-14")
    project = fresh(ctx, "c14-tx")
    stage_proposal(project)
    before = project_fingerprint(project, own=("shared/.tx/",))
    for tx in ("../evil", "a/b", "C:x", "x."):
        verdict = run_build(ctx, project, tx=tx)
        probe.record("MUT-14", f"--tx non sicuro {tx!r}", verdict,
                     CODE_PATH_ESCAPE)
    probe.check(project_fingerprint(project, own=("shared/.tx/",)) == before,
                "un --tx non sicuro ha scritto nel progetto")
    # junction nel percorso del candidate
    project = fresh(ctx, "c14-junc")
    outside = project.parent / "outside"
    outside.mkdir()
    write_json(outside / "tx-s13-001" / PROPOSAL_NAME, default_proposal())
    outside_before = project_fingerprint(outside, own=())
    stage_dir = project / STAGE13
    stage_dir.mkdir(exist_ok=True)
    link = stage_dir / ".working"
    make_link(link, outside)
    try:
        verdict = run_build(ctx, project)
    finally:
        drop_link(link)
    probe.record("MUT-14", "junction .working -> fuori dal progetto", verdict,
                 CODE_PATH_ESCAPE)
    probe.check(project_fingerprint(outside, own=()) == outside_before,
                "il costruttore ha SCRITTO attraverso una junction")
    # junction su output/ al --publish
    done = completed(ctx)
    if done["canonical"].is_file():
        project = done["project"].parent / "c14-publish"
        shutil.copytree(done["project"], project)
        (project / OUTPUT_REL).unlink(missing_ok=True)
        output = project / "output"
        if output.exists():
            shutil.rmtree(output)
        target = project.parent / "c14-outside-output"
        target.mkdir()
        make_link(output, target)
        try:
            verdict = run_publish(ctx, project)
        finally:
            drop_link(output)
        probe.record("MUT-14", "junction output/ -> fuori dal progetto",
                     verdict, CODE_PATH_ESCAPE)
        probe.check(not any(target.iterdir()),
                    "il pubblicatore ha scritto (anche un temporaneo) "
                    "attraverso la junction di output/")
    else:
        probe.check(False, "il ciclo di vita completo non ha pubblicato il "
                           "canonico: la junction di output/ non e' "
                           "misurabile")
    # DG-P-09 — byte-identita' del progetto fuori dalle aree proprie.
    probe.check(done["before_advance"] == done["after_advance"] ==
                done["after_publish"],
                "un file fuori dalle aree proprie e' cambiato durante "
                "advance-stage o --publish")
    probe.check(project_fingerprint(base_fixture(ctx)) ==
                done["before_advance"],
                "--build ha mutato un file fuori dalle aree proprie")
    return probe


# --------------------------------------------------------------------------
# DG-C-15 — T-DOCGEN-TM-TERMINAL
# --------------------------------------------------------------------------


def c15(ctx):
    """Predicato terminale sul Transaction Manager reale (`DG-P-11`,
    `-13`)."""
    probe = Probe("DG-C-15")
    done = completed(ctx)
    exit_code, out, err = done["advance"]
    if not probe.check(exit_code == EXIT_OK,
                       f"advance-stage {STAGE13} non riesce: exit {exit_code} "
                       f"{tm_codes(out)} {(out + err).strip()[:300]!r}"):
        return probe
    result = tm_json(out)
    probe.check("advanced_to" in result and result["advanced_to"] is None,
                f"advanced_to deve essere null: {result.get('advanced_to')!r}")
    probe.check(result.get("completed") is True,
                f"l'uscita non dichiara completed: {result}")
    project = done["project"]
    front = front_matter(ctx, project)
    order = [stage for stage, _ in sorted(KIT_ORDER(), key=lambda i: i[1])]
    probe.check(front.get("completed_stages") == order,
                f"completed_stages {front.get('completed_stages')}")
    probe.check(front.get("current_stage") == STAGE13,
                f"current_stage {front.get('current_stage')}")
    probe.check(front.get("status") == "approved",
                f"status {front.get('status')}")
    probe.check(front.get("current_task") == TERMINAL_TASK,
                f"current_task {front.get('current_task')}")
    action = str(front.get("next_action"))
    probe.check(action.startswith(TERMINAL_ACTION_PREFIX) and
                "avviare" not in action and "release boundary" not in action,
                f"next_action non terminale: {action!r}")
    snapshot = KIT.snapshot_canonical(project)
    for command in ("apply", "advance-stage"):
        candidate = project / STAGE13 / ".working" / f"tx-again-{command}"
        candidate.mkdir(parents=True)
        shutil.copyfile(done["canonical"], candidate / CANONICAL_NAME)
        shutil.copyfile(project / STAGE13 / HANDOFF_NAME,
                        candidate / HANDOFF_NAME)
        code, out, _ = run_tm(ctx, command, "--project", project, "--stage",
                              STAGE13, "--candidate", candidate)
        probe.check(code == EXIT_RED and "stage_already_completed" in
                    tm_codes(out),
                    f"{command} dopo il completamento: exit {code} "
                    f"{tm_codes(out)}")
    code, out, err = run_tm(ctx, "governance-status", "--project", project,
                            "--updates", json.dumps({"status": "in_progress"}),
                            "--reason", "riapertura del piano completato")
    probe.check(code == EXIT_USAGE,
                f"governance-status su un piano completato deve essere "
                f"rifiutato (exit 2): exit {code} {err.strip()[:200]!r}")
    beyond = project / ABSENT_STAGE / ".working" / "tx-beyond"
    beyond.mkdir(parents=True)
    code, _out, _err = run_tm(ctx, "advance-stage", "--project", project,
                              "--stage", ABSENT_STAGE, "--candidate", beyond)
    probe.check(code == EXIT_USAGE,
                f"nessuno stage oltre il terminale: exit {code}")
    shutil.rmtree(project / ABSENT_STAGE)
    probe.check(KIT.snapshot_canonical(project) == snapshot,
                "un tentativo oltre il terminale ha MUTATO il progetto")
    # crash prima del marker committed, poi recover
    case = build_case(ctx, "c15-crash")
    if case["document"] is not None:
        code, _out, _err = run_tm(
            ctx, "advance-stage", "--project", case["project"], "--stage",
            STAGE13, "--candidate", case["candidate"], "--gate-result",
            "approved", env_extra={"BPO_TX_TEST_CRASH": "before_commit"})
        probe.check(code != EXIT_OK, "il crash simulato non ha interrotto")
        code, out, err = run_tm(ctx, "recover", "--project", case["project"])
        probe.check(code == EXIT_OK, f"recover fallito: {err.strip()[:200]}")
        front = front_matter(ctx, case["project"])
        probe.check(STAGE13 in (front.get("completed_stages") or []) and
                    front.get("status") == "approved" and
                    front.get("current_stage") == STAGE13,
                    f"stato dopo il recover incoerente: {front}")
    else:
        probe.check(False, f"crash non misurabile: "
                           f"{verdict_line(case['build'])}")
    return probe


# --------------------------------------------------------------------------
# DG-C-16 — T-DOCGEN-BOUNDARY-MACHINERY
# --------------------------------------------------------------------------


def c16(ctx):
    """Forma T3: la catena CLI `stage_not_implemented` resta viva su uno
    specchio della skill con il confine forzato a `12_data-room`, mentre il
    Transaction Manager REALE ammette lo Stage 13."""
    probe = Probe("DG-C-16")
    holder = Path(tempfile.mkdtemp(prefix="mirror_", dir=_CACHE.get("holder")))
    mirror = holder / SKILL_REL
    shutil.copytree(ctx["root"] / SKILL_REL, mirror)
    config_path = mirror / "config" / "enforcement-config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["release_boundary"] = STAGE12
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False)
                           + "\n", encoding="utf-8")
    mirror_tm = mirror / "transaction" / "transaction_manager.py"
    project = fresh(ctx, "c16-mirror")
    snapshot = KIT.snapshot_canonical(project)

    def tm(*args):
        proc = run_python(ctx, mirror_tm, list(args))
        return proc.returncode, proc.stdout, proc.stderr
    candidate = KIT.make_candidate(project, STAGE13, tx_id="tx-mirror",
                                   structured={"document_generation": {}})
    for command in ("apply", "advance-stage"):
        code, out, _ = tm(command, "--project", project, "--stage", STAGE13,
                          "--candidate", candidate)
        probe.check(code == EXIT_RED and "stage_not_implemented" in
                    tm_codes(out),
                    f"specchio a confine 12: {command} su {STAGE13} exit "
                    f"{code} {tm_codes(out)}")
    code, out, _ = tm("governance-status", "--project", project, "--updates",
                      json.dumps({"status": "in_progress"}), "--reason",
                      "avvio dello Stage 13")
    probe.check(code == EXIT_RED and "stage_not_implemented" in tm_codes(out),
                f"specchio a confine 12: governance-status exit {code} "
                f"{tm_codes(out)}")
    beyond = KIT.make_candidate(project, ABSENT_STAGE, tx_id="tx-absent")
    code, _out, _err = tm("apply", "--project", project, "--stage",
                          ABSENT_STAGE, "--candidate", beyond)
    probe.check(code == EXIT_USAGE,
                f"identificatore assente da stage_order: exit {code}")
    shutil.rmtree(project / ABSENT_STAGE)
    probe.check(KIT.snapshot_canonical(project) == snapshot,
                "un'operazione respinta dallo specchio ha MUTATO il progetto")
    # Il TM REALE, a confine 13, non respinge piu' lo Stage 13: senza questo
    # contrasto la sonda T3 sarebbe indistinguibile da un confine fermo a 12.
    code, out, _ = run_tm(ctx, "governance-status", "--project", project,
                          "--updates", json.dumps({"status": "in_progress"}),
                          "--reason", "avvio dello Stage 13")
    probe.check(code == EXIT_OK,
                f"il TM reale deve ammettere lo stato attivo sullo Stage 13 "
                f"(confine reale {STAGE13}): exit {code} {tm_codes(out)}")
    probe.check(ctx["config"].get("release_boundary") == STAGE13,
                f"release_boundary reale {ctx['config'].get('release_boundary')}")
    return probe


# --------------------------------------------------------------------------
# DG-C-17 — T-DOCGEN-PUBLISH
# --------------------------------------------------------------------------


def c17(ctx):
    """Il derivato `output/business-plan.md`."""
    probe = Probe("DG-C-17")
    early = fresh(ctx, "c17-early")
    verdict = run_publish(ctx, early)
    probe.record("MUT-17", "--publish prima del completamento", verdict,
                 CODE_CHAIN)
    probe.check(not (early / OUTPUT_REL).exists(),
                "--publish prima del completamento ha scritto il derivato")
    done = completed(ctx)
    if not probe.check(done["publish"].get("exit_code") == EXIT_OK,
                       f"--publish dopo il completamento: "
                       f"{verdict_line(done['publish'])}"):
        return probe
    document = read_json_or_none(done["canonical"])
    output = done["output"]
    if not probe.check(output.is_file(), f"{OUTPUT_REL} assente"):
        return probe
    data = output.read_bytes()
    probe.check(sha256_bytes(data) ==
                (gen(document).get("rendering") or {}).get("markdown_sha256"),
                "sha256 del derivato diverso da rendering.markdown_sha256")
    markdown = rendered_markdown(ctx, document)
    probe.check(markdown is not None and data == markdown.encode("utf-8"),
                "il derivato non e' la resa del canonico COMMITTATO")
    probe.check(not data.startswith(b"\xef\xbb\xbf") and b"\r" not in data,
                "il derivato ha BOM o CR")
    verdict = run_publish(ctx, done["project"])
    probe.check(verdict.get("exit_code") == EXIT_OK and
                output.read_bytes() == data,
                f"--publish non e' idempotente: {verdict_line(verdict)}")
    tampered = done["project"].parent / "c17-tampered"
    shutil.copytree(done["project"], tampered)
    target = tampered / OUTPUT_REL
    target.write_bytes(data + b"\nRiga aggiunta a mano.\n")
    changed = target.read_bytes()
    verdict = run_publish(ctx, tampered)
    probe.record("MUT-17", "derivato modificato a mano", verdict,
                 CODE_OUTPUT_STALE)
    probe.check(target.read_bytes() == changed,
                "--publish ha sovrascritto un derivato divergente")
    return probe


# --------------------------------------------------------------------------
# DG-C-18 — T-DOCGEN-IMPACT
# --------------------------------------------------------------------------


def c18(ctx):
    """Fase impact e semantica post-completamento."""
    probe = Probe("DG-C-18")
    project = fresh(ctx, "c18-absent")
    verdict = run_impact_cli(ctx, project)
    probe.check(verdict.get("exit_code") == EXIT_OK and any(
        check.get("status") == "NOT_APPLICABLE" for check in
        verdict.get("checks") or ()),
                f"canonico assente: atteso NOT_APPLICABLE exit 0, "
                f"{verdict_line(verdict)}")
    done = completed(ctx)
    if not done["canonical"].is_file():
        probe.check(False, "ciclo di vita non completato: impact "
                           "post-completamento non misurabile")
        return probe
    project = done["project"].parent / "c18-update"
    shutil.copytree(done["project"], project)
    tm = transaction_manager(ctx)
    index, entry = record_of(project, CHURN_REF)
    del index
    payload = {
        "operation_id": "op-s13-churn", "reason": "nuova evidenza",
        "decision": {"decision_type": "assumption_update",
                     "options_considered": "mantenere vs aggiornare",
                     "motivation": "evidenza aggiornata",
                     "impact": "valore reso nel documento finale",
                     "approver": "founder"},
        "changes": [{"assumption_id": CHURN_REF,
                     "expected_record_hash": tm.record_fingerprint(entry),
                     "updates": {"value": 0.12}}]}
    changes = project.parent / "c18-changes.json"
    changes.write_text(json.dumps(payload), encoding="utf-8")
    code, out, err = run_tm(ctx, "update-assumption", "--project", project,
                            "--changes", changes)
    probe.check(code == EXIT_OK,
                f"update-assumption post-completamento su un valore non "
                f"legato a un driver deve riuscire: exit {code} "
                f"{tm_codes(out)} {(out + err).strip()[:300]!r}")
    journal = Path(project) / "shared" / ".tx" / (
        str(tm_json(out).get("transaction_id")) + ".json")
    reports = [item for item in (read_json_or_none(journal) or {}).get(
        "validation") or () if item.get("validator") ==
        "validate_document_generation"]
    probe.check(bool(reports) and all(item.get("exit_code") == EXIT_OK
                                      for item in reports),
                f"validate_document_generation non eseguito o non verde in "
                f"impact: {[item.get('exit_code') for item in reports]}")
    probe.check(any(CODE_INPUT_STALE in [warning.get("code") for warning in
                                         (item.get("report") or {})
                                         .get("warnings") or ()]
                    for item in reports),
                "il drift del valore reso non e' un WARNING nel report di "
                "impact")
    config = json.loads((ctx["root"] / ENFORCEMENT_REL).read_text(
        encoding="utf-8"))
    rel, view = tm.build_validation_view(
        done["project"], "tx-s13-corrupt",
        {f"{STAGE13}/{CANONICAL_NAME}": b"{"}, config)
    try:
        results, _invoked = tm.run_impact_validators(config, view, rel,
                                                     [STAGE13])
    finally:
        tm.cleanup_validation_view(done["project"], rel)
    exits = [item.get("exit_code") for item in results
             if item.get("validator") == "validate_document_generation"]
    probe.check(bool(exits) and all(code != EXIT_OK for code in exits),
                f"canonico corrotto nella view: exit {exits}")
    return probe


# --------------------------------------------------------------------------
# DG-C-19 — T-DOCGEN-WORKFLOW
# --------------------------------------------------------------------------

WORKFLOW_PLACEHOLDERS = ("<skill_dir>", "<project>", "<tx>")


def workflow_commands(text):
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


def c19(ctx):
    """Ogni comando del workflow eseguibile come scritto (precedente
    `DR-P-12`); nessun validator degli Stage 1-9 invocato."""
    probe = Probe("DG-C-19")
    for rel in (DG_WORKFLOW_REL, DG_METHODOLOGY_REL, DG_AGENT_REL):
        probe.check((ctx["root"] / rel).is_file(), f"{rel} ASSENTE")
    text = read_text_or_none(ctx["root"] / DG_WORKFLOW_REL)
    if text is None:
        return probe
    commands = workflow_commands(text)
    probe.check(len(commands) >= 6,
                f"il workflow documenta {len(commands)} comandi: attesi "
                "apertura, costruzione, egress, advance, publish e impact")
    for command in commands:
        for token in re.findall(r"<[^<>\s]+>", command):
            probe.check(token in WORKFLOW_PLACEHOLDERS,
                        f"segnaposto non dichiarato {token!r} in {command!r}")
        probe.check("validate_stage_gate" not in command and
                    "validate_referential_integrity" not in command,
                    f"validator degli Stage 1-9 invocato: {command!r}")
    project = fresh(ctx, "c19-workflow")
    stage_proposal(project)
    for position, command in enumerate(commands):
        concrete = command.replace(
            "<skill_dir>", (ctx["root"] / SKILL_REL).as_posix()) \
            .replace("<project>", project.as_posix()).replace("<tx>", TX13)
        argv = shlex.split(concrete)
        if argv and argv[0] in ("python", "python3"):
            argv[0] = sys.executable
        # cwd FUORI dal repository: i comandi documentati non dipendono dalla
        # directory corrente, solo da <skill_dir> e <project>.
        proc = subprocess.run(argv, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              cwd=str(project.parent),
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        if not probe.check(proc.returncode == 0,
                           f"comando {position + 1} del workflow NON "
                           f"eseguibile come scritto (exit {proc.returncode}): "
                           f"{command!r} — "
                           f"{(proc.stdout + proc.stderr)[:240]!r}"):
            return probe
    front = front_matter(ctx, project)
    probe.check(STAGE13 in (front.get("completed_stages") or []),
                "il workflow eseguito come scritto non completa lo Stage 13")
    probe.check((project / OUTPUT_REL).is_file(),
                "il workflow eseguito come scritto non pubblica il derivato")
    return probe


# --------------------------------------------------------------------------
# DG-C-20 — T-DOCGEN-NO-RECOMPUTE
# --------------------------------------------------------------------------


def recompute_findings(source):
    """Il RILEVATORE statico: import fuori dall'elenco ammesso e token di
    aritmetica o conversione numerica."""
    findings = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"sorgente non analizzabile: {exc}"]
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module.split(".")[0]]
        for name in names:
            if name not in STDLIB_ALLOWED:
                findings.append(f"import non ammesso: {name}")
    for token in FORBIDDEN_RECOMPUTE:
        if token in source:
            findings.append(f"token vietato: {token!r}")
    return findings


def c20(ctx):
    """Nessun ricalcolo: import stdlib + `_framework`, nessuna aritmetica
    (`DG-P-06`)."""
    probe = Probe("DG-C-20")
    probe_source = ("import decimal\nimport numpy\n"
                    "total = sum(values)\nx = float(value)\n")
    detected = recompute_findings(probe_source)
    probe.check(len(detected) >= 4,
                f"AUTO-SONDA: il rilevatore e' VACUO: {detected}")
    source = read_text_or_none(ctx["dg_validator"])
    if not probe.check(source is not None, MISSING_VALIDATOR):
        return probe
    findings = recompute_findings(source)
    probe.check(not findings, f"il modulo di produzione ricalcola o importa "
                              f"fuori dal confine: {findings}")
    return probe


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

CONTRACTS = (
    ("DG-C-01", "T-DOCGEN-CONTRACT", c01),
    ("DG-C-02", "T-DOCGEN-CHAIN", c02),
    ("DG-C-03", "T-DOCGEN-INPUT-STALE", c03),
    ("DG-C-04", "T-DOCGEN-FINANCIAL-BASIS", c04),
    ("DG-C-05", "T-DOCGEN-FUNDING-BINDING", c05),
    ("DG-C-06", "T-DOCGEN-FINANCIAL-VALUES", c06),
    ("DG-C-07", "T-DOCGEN-MILESTONES", c07),
    ("DG-C-08", "T-DOCGEN-CLAIMS", c08),
    ("DG-C-09", "T-DOCGEN-EPISTEMIC-LABELS", c09),
    ("DG-C-10", "T-DOCGEN-DISCLOSURES", c10),
    ("DG-C-11", "T-DOCGEN-UNTRACED", c11),
    ("DG-C-12", "T-DOCGEN-STRUCTURE", c12),
    ("DG-C-13", "T-DOCGEN-SECRETS", c13),
    ("DG-C-14", "T-DOCGEN-CONTAINMENT", c14),
    ("DG-C-15", "T-DOCGEN-TM-TERMINAL", c15),
    ("DG-C-16", "T-DOCGEN-BOUNDARY-MACHINERY", c16),
    ("DG-C-17", "T-DOCGEN-PUBLISH", c17),
    ("DG-C-18", "T-DOCGEN-IMPACT", c18),
    ("DG-C-19", "T-DOCGEN-WORKFLOW", c19),
    ("DG-C-20", "T-DOCGEN-NO-RECOMPUTE", c20),
)
CONTRACT_IDS = tuple(item[0] for item in CONTRACTS)


def run_one(ctx, contract_id, name, function):
    try:
        probe = function(ctx)
        by_exception = False
    except HarnessDefect:
        raise
    except Exception as exc:  # un'eccezione non e' evidenza RED
        probe = Probe(contract_id)
        probe.findings.append(f"ECCEZIONE {type(exc).__name__}: {exc}")
        by_exception = True
    killed = sum(1 for run in probe.runs if run["killed"])
    red = bool(probe.findings) or probe.evaluated == 0 or \
        (probe.runs and killed == 0)
    return {"id": contract_id, "name": name, "probe": probe, "red": red,
            "by_exception": by_exception, "killed": killed}


def format_line(result):
    probe = result["probe"]
    state = "RED" if result["red"] else "GREEN"
    line = (f"{result['id']} {result['name']:<30} {state:<5} "
            f"evaluated={probe.evaluated} runs={len(probe.runs)} "
            f"killed={result['killed']}")
    if result["red"]:
        reasons = "; ".join(probe.findings[:4]) or "nessuna osservazione"
        line += f" :: {reasons[:900]}"
    return line


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(
        prog="test_document_generation.py",
        description="I venti contratti dello Stage 13.")
    parser.add_argument("--root", required=False)
    parser.add_argument("--contract", help="esegue un solo contratto")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--matrix", action="store_true",
                        help="stampa le esecuzioni di mutazione")
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
        print(f"USAGE ERROR: contratto inesistente: {args.contract}",
              file=sys.stderr)
        return EXIT_USAGE
    global XLSX, KIT, M5
    testkit_dir = str(root / TESTKIT_REL)
    if testkit_dir not in sys.path:
        sys.path.insert(0, testkit_dir)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    try:
        import bpo_testkit
        import bpo_m5_fixtures
        KIT = bpo_testkit
        M5 = bpo_m5_fixtures
        XLSX = load_harness(root, XLSX_HARNESS)
        XLSX.CHAPTER = XLSX.load_chapter_harness(root)
        XLSX.GATE = XLSX.load_gate(root)
        ctx = build_context(root)
        _CACHE["config"] = ctx["config"]
        base_fixture(ctx)
        results = [run_one(ctx, *item) for item in CONTRACTS
                   if not args.contract or item[0] == args.contract]
    except HarnessDefect as exc:
        print(f"HARNESS DEFECT: {exc}", file=sys.stderr)
        return EXIT_STATE
    finally:
        holder = _CACHE.get("holder")
        if holder is not None:
            shutil.rmtree(holder, ignore_errors=True)
    for result in results:
        print(format_line(result))
        if args.matrix:
            for run in result["probe"].runs:
                print(f"MATRIX {result['id']} {run['mutation']} "
                      f"{run['label']!r} exit={run['exit_code']} "
                      f"atteso={run['expected']} ucciso={run['killed']} "
                      f"codici={run['codes']}")
    red = [result for result in results if result["red"]]
    by_exception = sum(1 for result in results if result["by_exception"])
    runs = [run for result in results for run in result["probe"].runs]
    print(f"SUMMARY contratti={len(results)} GREEN={len(results) - len(red)} "
          f"RED={len(red)} BY_EXCEPTION={by_exception} "
          f"mutanti={len(runs)} uccisi={sum(1 for run in runs if run['killed'])}")
    return EXIT_RED if red else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
