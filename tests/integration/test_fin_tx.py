#!/usr/bin/env python3
"""T-FIN-TX — i DICIOTTO contratti della QA DETERMINISTICA END-TO-END dello
Stage 10 (transazione, workflow e derivati).

Il modulo rientra nel glob di ENTRAMBI i runner (`tests/run-tests.ps1` e
`tests/run-tests.sh` globano `tests/integration/test_*.py`) senza alcuna
modifica ai runner.

I DICIOTTO CONTRATTI OSPITATI QUI
---------------------------------
    FQ-C-01  T-FIN-TX-BINDING                   MUT-4-01
    FQ-C-02  T-FIN-NO-MUTATION-FAIL             MUT-4-02
    FQ-C-03  T-FIN-RESUME                       MUT-4-03
    FQ-C-04  T-FIN-CRASH-RECOVERY               MUT-4-04
    FQ-C-05  T-FIN-IDEMPOTENCY                  MUT-4-05
    FQ-C-06  T-FIN-WRITE-SET                    MUT-4-06
    FQ-C-07  T-FIN-NO-STAGE-BEYOND-TERMINAL     MUT-4-07
    FQ-C-08  T-FIN-DERIVED-CHECKSUM             MUT-4-08
    FQ-C-09  T-FIN-DERIVED-CROSS-CONSISTENCY    MUT-4-09
    FQ-C-10  T-FIN-DERIVED-MISSING              MUT-4-10
    FQ-C-11  T-FIN-DERIVED-REGENERATION         MUT-4-11
    FQ-C-12  T-FIN-DERIVED-ROLLBACK             MUT-4-12
    FQ-C-13  T-FIN-PIPELINE-END-TO-END          MUT-4-13
    FQ-C-14  T-FIN-DERIVED-FIDELITY             MUT-4-14
    FQ-C-15  T-FIN-STDLIB-ONLY-RUNTIME          MUT-4-15
    FQ-C-16  T-FIN-REAL-PROJECT-WRITE-GUARD     MUT-4-16
    FQ-C-17  T-FIN-WAVE123-CONTRACT-INVENTORY   MUT-4-17
    FQ-C-18  T-FIN-IMPACT                       MUT-4-18

`T-FIN-IMPACT`: IL CANONICO DELLO STAGE 10 IN FASE IMPACT
---------------------------------------------------------
Lo Stage 10 e' dentro il `release_boundary` e `egress_required` contiene,
fra i QUATTRO validator finanziari, la SOLA voce `validate_financial_output`
(gli altri tre restano validator di pipeline interna). Ne segue che la fase
impact tocca lo Stage 10, invoca `validate_financial_output` sul canonico
PERSISTITO e lo ISPEZIONA realmente — senza alcuna `TypeError`, e con i casi
negativi (canonico assente/invalido/corrotto) che falliscono con exit code
definiti. `FQ-C-18` verifica ESATTAMENTE questo, sui due fronti STRUTTURALE e
COMPORTAMENTALE, ed e' un contratto `GREEN` ordinario: non porta il flag
`authorized_red`.

DUE FRONTI CONGIUNTI
--------------------
I contratti di transazione sono misurati su DUE fronti CONGIUNTI, mai su uno
solo:

  1  fronte STRUTTURALE, specifico dello Stage 10 — invocazione DIRETTA delle
     funzioni del Transaction Manager con `stage="10_financial-plan"`, le
     stesse che governano lo Stage 10: e' la verifica funzione-per-funzione
     che il meccanismo transazionale non richiede alcun delta per lo Stage 10;
  2  fronte COMPORTAMENTALE — una transazione REALE, eseguita end-to-end su uno
     stage dentro il confine, che dimostra che il meccanismo e' VIVO e non solo
     dichiarato.

Nessun fronte da solo sarebbe una prova: il primo senza il secondo misurerebbe
una funzione mai eseguita, il secondo senza il primo misurerebbe uno stage che
non e' lo Stage 10.

DISCIPLINA
----------
Ogni contratto e' INDIPENDENTE e riporta la PROPRIA constatazione di dominio.
Ogni contratto porta un caso POSITIVO e almeno un caso NEGATIVO, e NESSUNA
mutazione e' uccisa PER ECCEZIONE: ogni sotto-esecuzione verifica che il
difetto sia RILEVATO e NOMINATO.

Ogni RILEVATORE STATICO introdotto qui porta la propria sonda di
AUTO-VERIFICA: un rilevatore che non dimostra di rilevare e' un rilevatore
vacuo.

Il registro delle fixture `F-1`…`F-13` di `bpo_testkit.py` non e' esteso: le
varianti usate qui sono DERIVATE IN-MODULO, e la catena di costruzione
dell'ingresso e' quella delle suite finanziarie — `test_fin_engine.py` ->
`test_fin_output.py` -> `test_fin_chapter.py` -> `test_fin_xlsx.py` — invocata
attraverso l'harness del workbook, mai duplicata.

Nessun artefatto e' prodotto in un progetto REALE: ogni esecuzione vive in un
progetto TEMPORANEO di fixture, e `projects/**` e' misurato BYTE-IDENTICO
prima e dopo (`FQ-C-16`).

SEMANTICA DEGLI EXIT CODE
-------------------------
    0   tutti i diciotto contratti soddisfatti (GREEN), `T-FIN-IMPACT`
        incluso
    1   almeno un contratto RED
    2   errore d'uso
    3   difetto di PREPARAZIONE (non e' un esito RED)
"""
import argparse
import ast
import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

import bpo_testkit as kit
import bpo_m5_fixtures as m5

SKILL_REL = ".claude/skills/business-plan-orchestrator"
TESTKIT_REL = "tests/integration"
XLSX_HARNESS = "test_fin_xlsx"

GATE_REL = f"{SKILL_REL}/output/derived_consistency.py"
RENDERER_REL = f"{SKILL_REL}/output/render_financial_plan.py"
EXPORTER_REL = f"{SKILL_REL}/output/export_financial_model.py"
BUILDER_REL = f"{SKILL_REL}/output/build_canonical_output.py"
OUTPUT_VALIDATOR_REL = f"{SKILL_REL}/validators/validate_financial_output.py"

STAGE10 = "10_financial-plan"
STAGE11 = "11_funding-request"
STAGE12 = "12_data-room"
STAGE13 = "13_document-generation"
TX_ID = "tx-m6a-001"

CANONICAL_NAME = "structured-output.json"
CHAPTER_NAME = "financial-plan.md"
WORKBOOK_NAME = "financial-model.xlsx"

EXIT_OK = 0
EXIT_RED = 1
EXIT_USAGE = 2
EXIT_STATE = 3

CODE_INCOMPLETE = "derived_artifact_incomplete"
CODE_MISMATCH = "derived_artifact_numeric_mismatch"
CODE_STALE = "derived_artifact_stale"
CODE_REAL_PROJECT = "real_project_write_forbidden"

NOT_APPLICABLE = "NOT_APPLICABLE"

#: I TRE codici dei derivati. `WARNING` NON e' ammesso per nessuno dei tre,
#: in nessuna forma e in nessun percorso.
DERIVED_FAIL_CODES = (CODE_INCOMPLETE, CODE_MISMATCH, CODE_STALE)

#: Stage DENTRO il confine, usato per il fronte COMPORTAMENTALE dei contratti
#: di transazione: una transazione reale e leggera su uno stage iniziale.
INSIDE_STAGE = "01_problem-and-need"

#: Le PARTI OOXML senza le quali il pacchetto non e' apribile come workbook.
REQUIRED_PARTS = ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
                  "xl/_rels/workbook.xml.rels", "xl/styles.xml")

#: I QUATTRO validator finanziari dello Stage 10, con `"stages": [10]`.
#: `egress_required` contiene la SOLA `validate_financial_output`: le altre
#: TRE restano validator di PIPELINE interna e non vi entrano MAI.
FINANCIAL_VALIDATORS = ("validate_financial_binding",
                        "validate_financial_engine",
                        "validate_financial_reconciliation",
                        "validate_financial_output")

#: La condizione DICHIARATA sotto cui `T-FIN-IMPACT` e' GREEN: il canonico
#: dello Stage 10 e' validato in egress e in impact, e il confine include lo
#: Stage 10.
IMPACT_GREEN_REASON = ("validate_financial_output e' in egress_required, "
                       "SOLO validate_financial_output fra i QUATTRO "
                       "validator finanziari, e il boundary e' a Stage 13")

#: Il confine ATTESO: l'ultimo stage di `stage_order`. Un valore diverso e'
#: un difetto di configurazione.
EXPECTED_BOUNDARY = "13_document-generation"

#: L'ultima voce di `egress_required` — la TREDICESIMA, e nessuna altra. Le
#: prime DODICI restano preservate NELL'ORDINE.
EXPECTED_EGRESS_APPENDED = "validate_document_generation"
EXPECTED_EGRESS_COUNT = 13

#: Inventario ATTESO delle sette suite finanziarie. Un modulo che perde,
#: rinomina o fonde contratti e' un difetto.
ACCEPTED_INVENTORY = (
    ("test_fin_binding", 16),
    ("test_fin_engine", 30),
    ("test_fin_scenarios", 8),
    ("test_fin_recon", 11),
    ("test_fin_output", 22),
    ("test_fin_chapter", 5),
    ("test_fin_xlsx", 17),
)

#: I moduli di RUNTIME che devono girare in SOLA LIBRERIA STANDARD:
#: nessuna dipendenza di terze parti a runtime.
STDLIB_ONLY_MODULES = (EXPORTER_REL, GATE_REL, RENDERER_REL, BUILDER_REL)

#: Moduli LOCALI del repository che i moduli di runtime possono importare: non
#: sono terze parti e non violano la regola della sola libreria standard.
LOCAL_MODULES = ("render_financial_plan", "export_financial_model",
                 "derived_consistency", "build_canonical_output",
                 "_framework", "formula_dsl", "bpo_testkit",
                 "bpo_m5_fixtures", "transaction_manager")

#: Token e prefissi di uno stage OLTRE l'ultimo di `stage_order`. Sono
#: nominati QUI, in un modulo di test, per essere RESPINTI: e' la classe
#: permessa.
#:
#: Lo Stage 13 e' IMPLEMENTATO ed e' l'ULTIMO stage, quindi il token
#: `document-generation` e il segmento `13_` non sono proibiti; il rilevatore
#: di `FQ-C-07` respinge ogni segmento di stage `NN_` con `NN >= 14` —
#: nessuno Stage 14 esiste.
FORBIDDEN_STAGE_TOKENS = ()
FORBIDDEN_STAGE_PREFIXES = tuple(f"{number}_" for number in range(14, 100))
#: Forma T2: un identificatore ASSENTE da `stage_order`, bersaglio non
#: vacuo di ogni operazione oltre il terminale.
ABSENT_STAGE = "14_after-terminal"

#: L'esenzione PER PATH ESATTO della convenzione `NN_` = stage `NN-1`: il
#: workflow dello STAGE 13 e' `workflows/14_document-generation.md` e il suo
#: segmento iniziale e' `14_`. L'esenzione e' ristretta al path ESATTO: un
#: `14_` altrove resta rilevato.
NN_CONVENTION_EXEMPTIONS = ("workflows/14_document-generation.md",)

XLSX = None      # harness del workbook, popolato da `main`
CHAPTER = None   # harness del capitolo
GATE = None      # gate di produzione `derived_consistency`
TM = None        # transaction manager di produzione
_BASELINE = None


class HarnessUsageError(Exception):
    """Errore d'uso del modulo (exit 2)."""


class HarnessDefect(Exception):
    """Difetto di PREPARAZIONE (exit 3). Non e' un esito RED."""


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


def load_module(path, name):
    path = Path(path)
    if not path.is_file():
        raise HarnessDefect(f"modulo assente: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_xlsx_harness(root):
    """Riusa la catena di costruzione delle suite finanziarie.

    `test_fin_xlsx` carica `test_fin_chapter`, che carica `test_fin_output`,
    che carica `test_fin_engine`. Una sola catena di costruzione dell'ingresso,
    nessuna duplicazione della fixture e nessun costruttore nuovo: e' lo stesso
    riuso con cui i derivati consumano il canonico dello Stage 10.
    """
    module = load_module(root / TESTKIT_REL / f"{XLSX_HARNESS}.py",
                         XLSX_HARNESS)
    module.CHAPTER = module.load_chapter_harness(root)
    module.GATE = module.load_gate(root)
    if module.GATE is None:
        raise HarnessDefect(
            f"{GATE_REL} ASSENTE: il gate di coerenza triangolare e' la sede "
            "UNICA del lettore OOXML e delle XREC-*, e nessun contratto "
            "cross-artefatto dello Stage 10 e' misurabile senza di esso")
    return module


def build_context(root):
    ctx = XLSX.build_context(root)
    ctx["config_path"] = root / kit.CONFIG_REL
    ctx["config"] = kit.read_json(ctx["config_path"])
    ctx["output_validator"] = root / OUTPUT_VALIDATOR_REL
    ctx["tokens"] = CHAPTER.build_context(root)["style_tokens"]
    if ctx["tokens"] is None:
        raise HarnessDefect(CHAPTER.MISSING_TOKENS)
    return ctx


def baseline(ctx):
    """La pipeline deterministica COMPLETA, eseguita UNA VOLTA per esecuzione.

    Il progetto e' TEMPORANEO, mai un progetto REALE, e porta i QUATTRO output
    della pipeline. Ogni contratto che deve MUTARE lavora su una COPIA
    PROFONDA: il caso di riferimento non e' mai toccato.
    """
    global _BASELINE
    if _BASELINE is None:
        holder = Path(tempfile.mkdtemp(prefix="fq_baseline_"))
        case = XLSX.prepare(ctx, holder, name="m6a", level="full", tx=TX_ID)
        if (case.get("built") or {}).get("exit_code") != 0:
            raise HarnessDefect(
                "il costruttore canonico non ha prodotto il "
                f"canonico: {(case.get('built') or {}).get('stdout', '')[:300]}")
        if (case.get("rendered") or {}).get("exit_code") != 0:
            raise HarnessDefect(
                "il renderer del capitolo non ha prodotto il capitolo: "
                f"{(case.get('rendered') or {}).get('stdout', '')[:300]}")
        if (case.get("export") or {}).get("exit_code") != 0:
            raise HarnessDefect(
                "l'exporter del workbook non ha prodotto il workbook: "
                f"{(case.get('export') or {}).get('stdout', '')[:300]}")
        _BASELINE = {"holder": holder, "case": case}
    return _BASELINE["case"]


def drop_baseline():
    global _BASELINE
    if _BASELINE is not None:
        shutil.rmtree(_BASELINE["holder"], ignore_errors=True)
        _BASELINE = None


def clone(ctx, base, name="clone"):
    """Copia PROFONDA del progetto pubblicato: ogni mutazione agisce qui, e il
    caso di riferimento resta INTATTO."""
    case = baseline(ctx)
    target = Path(base) / name
    shutil.copytree(case["project"], target)
    paths = GATE.artifact_paths(target, TX_ID)
    return {"project": target, "canonical": paths["canonical"],
            "chapter": paths["chapter"], "workbook": paths["workbook"],
            "document": json.loads(
                paths["canonical"].read_text(encoding="utf-8")),
            "text": paths["chapter"].read_text(encoding="utf-8"),
            "package": GATE.read_package(paths["workbook"])}


def run_generator(ctx, script_rel, canonical, project):
    """Invoca il GENERATORE DI PRODUZIONE, mai una copia."""
    command = [sys.executable, str(ctx["root"] / script_rel), "--canonical",
               str(canonical), "--project", str(project)]
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
    return {"exit_code": proc.returncode, "report": report,
            "stdout": proc.stdout, "stderr": proc.stderr,
            "command": " ".join(command)}


def run_output_validator(ctx, project, candidate):
    """Il VALIDATOR CANONICO DI PRODUZIONE — gate 1 della pipeline."""
    command = [sys.executable, str(ctx["output_validator"]),
               "--project", str(project), "--stage", STAGE10,
               "--phase", "egress", "--candidate", str(candidate)]
    proc = subprocess.run(command, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    report = None
    if proc.stdout.strip().startswith("{"):
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            report = None
    return {"exit_code": proc.returncode, "report": report,
            "stdout": proc.stdout}


def codes_of(findings):
    return sorted({item.get("code") for item in findings or []})


def names_metric(finding, metric_id):
    return metric_id in str(finding.get("where", "")) or \
        metric_id in str(finding.get("message", ""))


def warning_leakage(verdict):
    """`WARNING` NON e' ammesso per i TRE codici dei derivati, in nessuna
    forma e in nessun percorso."""
    leaked = []
    for finding in verdict.get("findings") or []:
        severity = str(finding.get("severity", "")).upper()
        if severity == "WARNING":
            leaked.append(
                f"il gate classifica WARNING un difetto di deliverable: "
                f"{finding.get('code')} — la regola dei derivati lo VIETA")
    if verdict.get("passed") and verdict.get("findings"):
        leaked.append(
            "il gate dichiara `passed` con findings presenti: un difetto di "
            "deliverable e' declassato a caveat")
    return leaked


# --------------------------------------------------------------------------
# Costruttori del fronte COMPORTAMENTALE — transazione REALE dentro il confine
# --------------------------------------------------------------------------


def tm_project(base, name, stage=INSIDE_STAGE, status="in_progress",
               completed=None):
    return kit.make_project(base, name=name, current_stage=stage,
                            status=status,
                            completed=completed or ["00_idea-discovery"],
                            assumptions=[kit.base_assumption(1),
                                         kit.base_assumption(2)])


def tm_candidate(project, tx="tx-a", revenue_ref="P-ASS-001", declare=True,
                 extra_files=()):
    """Candidate COERENTE dello stage dentro il confine.

    Con `declare=False` il riferimento resta NON DICHIARATO e i validator
    egress FALLISCONO: e' la costruzione del caso negativo di
    `T-FIN-NO-MUTATION-FAIL`.
    """
    proposed = [{"id": "P-ASS-001", "category": "market",
                 "statement": "Driver ricavo", "kind": "primary",
                 "unit": "EUR", "value": 2000,
                 "validation_status": "unvalidated"}] if declare else []
    candidate = kit.make_candidate(
        project, INSIDE_STAGE, tx_id=tx,
        structured={"problem_statement": {"id": "SEG-001",
                                          "problem_ref": "ASS-001",
                                          "revenue_ref": revenue_ref}},
        proposed=proposed, handoff="# Handoff\n\nDriver: P-ASS-001.\n")
    for name in extra_files:
        (candidate / name).write_text(
            "artefatto NON previsto dal write-set\n", encoding="utf-8")
    return candidate


def terminal_project(base, name, stage=STAGE10):
    """Progetto fermo all'inizio di `stage`: `current_stage = stage`, gli
    stage precedenti completati. E' la stessa costruzione che
    `test_release_boundary.py` usa per il progetto al confine."""
    order = ORDER_CACHE["order"]
    index = order.index(stage)
    project = kit.make_project(base, name=name, current_stage=stage,
                               status="not_started", completed=order[:index],
                               assumptions=m5.market_assumptions())
    for folder in order[:index + 1]:
        (project / folder).mkdir(exist_ok=True)
    return project


ORDER_CACHE = {"order": []}


def journals_by_state(project):
    states = {}
    for path in kit.find_journals(project):
        try:
            journal = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        states.setdefault(journal.get("state"), []).append(journal)
    return states


# --------------------------------------------------------------------------
# FQ-C-01 — T-FIN-TX-BINDING
# --------------------------------------------------------------------------


def c01(ctx, base):
    """`T-FIN-TX-BINDING` — i validator girano sullo SNAPSHOT, non sui file
    vivi; i BYTE VALIDATI sono i BYTE COMMITTATI.

    Fronte STRUTTURALE (Stage 10): `build_validation_view` copia OGNI
    `NN_*/structured-output.json`, quindi il canonico dello Stage 10 — e con
    esso il `driver_registry` — e' GIA' visibile ai validator in fase impact.
    E' la conclusione «nessun delta per lo Stage 10», ESEGUITA invece che
    asserita.

    Fronte COMPORTAMENTALE: una transazione REALE dimostra che il legame e'
    vivo, e DUE casi negativi dimostrano che rompendolo la transazione e'
    RESPINTA.
    """
    findings = []

    # ---- fronte STRUTTURALE, Stage 10 ------------------------------------
    project = tm_project(base, "c01-view")
    (project / "shared" / ".tx").mkdir(parents=True, exist_ok=True)
    stage_dir = project / STAGE10
    stage_dir.mkdir(exist_ok=True)
    canonical = baseline(ctx)["canonical"]
    (stage_dir / CANONICAL_NAME).write_bytes(canonical.read_bytes())
    # I DERIVATI esistono accanto al canonico e NON devono entrare nella view:
    # non sono input di alcun validator.
    (stage_dir / CHAPTER_NAME).write_bytes(baseline(ctx)["chapter"].read_bytes())
    rel, view = TM.build_validation_view(project, "tx-view", {}, ctx["config"])
    copied = view / STAGE10 / CANONICAL_NAME
    if not copied.is_file():
        findings.append(
            f"build_validation_view NON copia {STAGE10}/{CANONICAL_NAME} nella "
            "validation view: il driver_registry dello Stage 10 sarebbe "
            "INVISIBILE ai validator in fase impact e driver_ref_orphaned non "
            "potrebbe funzionare")
    elif copied.read_bytes() != canonical.read_bytes():
        findings.append(
            f"il canonico dello Stage 10 copiato nella view DIVERGE dal "
            "canonico di origine: i byte validati non sarebbero i byte "
            "committati")
    if (view / STAGE10 / CHAPTER_NAME).exists():
        findings.append(
            f"la validation view contiene {CHAPTER_NAME}: un DERIVATO non e' "
            "mai input canonico di alcun componente")
    if not str(rel).startswith("shared/.tx/"):
        findings.append(
            f"la validation view non vive sotto la transazione: {rel!r}")

    # ---- fronte COMPORTAMENTALE: mutazione del candidate ATTIVO ----------
    tamper = 'structured-output.json={"tampered": "unvalidated-content"}'
    live = tm_project(base, "c01-live")
    candidate = tm_candidate(live)
    exit_code, out, err = kit.run_tm_cli(
        ctx["root"], "apply", "--project", live, "--stage", INSIDE_STAGE,
        "--candidate", candidate,
        env_extra={"BPO_TX_TEST_MUTATE_ACTIVE": tamper})
    if exit_code != 0:
        findings.append(
            "una mutazione CONCORRENTE del candidate ATTIVO dopo lo snapshot "
            f"ha impedito il commit (exit {exit_code}): {out.strip()[:200]!r} "
            f"{err.strip()[:200]!r}")
    else:
        committed = kit.read_json(live / INSIDE_STAGE / CANONICAL_NAME)
        if "tampered" in json.dumps(committed):
            findings.append(
                "contenuto NON VALIDATO, scritto sul candidate attivo dopo lo "
                "snapshot, e' entrato nello stato canonico: i byte committati "
                "non sono i byte validati")

    # ---- caso negativo 1: mutazione dello SNAPSHOT dopo la validazione ---
    tampered = tm_project(base, "c01-snap")
    candidate = tm_candidate(tampered)
    before = kit.snapshot_canonical(tampered)
    exit_code, out, _ = kit.run_tm_cli(
        ctx["root"], "apply", "--project", tampered, "--stage", INSIDE_STAGE,
        "--candidate", candidate,
        env_extra={"BPO_TX_TEST_MUTATE_SNAPSHOT": tamper})
    if exit_code == 0:
        findings.append(
            "uno snapshot MUTATO dopo la validazione ha comunque committato: "
            "il legame fra byte validati e byte committati e' VACUO")
    else:
        codes = {item["code"] for item in kit.tm_result(out, "c01")["errors"]}
        if "candidate_changed" not in codes:
            findings.append(
                f"snapshot mutato: atteso `candidate_changed`, ottenuti "
                f"{sorted(codes)}")
    if kit.snapshot_canonical(tampered) != before:
        findings.append(
            "lo snapshot mutato e respinto ha comunque MUTATO il canonico")

    # ---- caso negativo 2: report riferito a un candidate DIVERSO ---------
    reported = tm_project(base, "c01-report")
    candidate = tm_candidate(reported)
    before = kit.snapshot_canonical(reported)
    report_path = Path(base) / "foreign-report.json"
    report_path.write_text(json.dumps({"candidate_hash": "0" * 64}),
                           encoding="utf-8")
    exit_code, out, _ = kit.run_tm_cli(
        ctx["root"], "apply", "--project", reported, "--stage", INSIDE_STAGE,
        "--candidate", candidate, "--report", report_path)
    if exit_code != 1:
        findings.append(
            "un validation report riferito a un candidate hash DIVERSO non e' "
            f"stato respinto con exit 1 (exit {exit_code})")
    else:
        codes = {item["code"] for item in kit.tm_result(out, "c01")["errors"]}
        if "report_hash_mismatch" not in codes:
            findings.append(
                f"report estraneo: atteso `report_hash_mismatch`, ottenuti "
                f"{sorted(codes)}")
    if kit.snapshot_canonical(reported) != before:
        findings.append("il report estraneo respinto ha MUTATO il canonico")
    return findings


# --------------------------------------------------------------------------
# FQ-C-02 — T-FIN-NO-MUTATION-FAIL
# --------------------------------------------------------------------------


def c02(ctx, base):
    """`T-FIN-NO-MUTATION-FAIL` — un FAIL in fase egress lascia il canonico
    BYTE-IDENTICO e NON scrive alcun marker `committed`.

    Fronte STRUTTURALE (Stage 10): il validator canonico di produzione dello
    Stage 10 respinge un canonico degenere SENZA scrivere nulla — un validator
    non e' mai una superficie di scrittura.
    """
    findings = []

    # ---- fronte COMPORTAMENTALE: egress FAIL su transazione reale --------
    project = tm_project(base, "c02-fail")
    candidate = tm_candidate(project, revenue_ref="P-ASS-999", declare=False)
    before = kit.snapshot_canonical(project)
    exit_code, out, _ = kit.run_tm_cli(
        ctx["root"], "apply", "--project", project, "--stage", INSIDE_STAGE,
        "--candidate", candidate)
    if exit_code == 0:
        findings.append(
            "un candidate che NON supera i validator egress ha comunque "
            "committato: il gate 1 della pipeline e' VACUO")
    else:
        codes = {item["code"] for item in kit.tm_result(out, "c02")["errors"]}
        if "validation_failed" not in codes:
            findings.append(
                f"egress FAIL: atteso `validation_failed`, ottenuti "
                f"{sorted(codes)}")
    after = kit.snapshot_canonical(project)
    if after != before:
        changed = sorted(set(after) ^ set(before)) or sorted(
            rel for rel in before if before[rel] != after.get(rel))
        findings.append(
            f"un egress FAIL ha MUTATO il canonico: {changed}; la "
            "transazione esige prima = dopo")
    states = journals_by_state(project)
    if "committed" in states:
        findings.append(
            "un egress FAIL ha comunque lasciato un journal in stato "
            "`committed`: il marker di commit non e' subordinato ai validator")
    if "rolled_back" not in states:
        findings.append(
            f"un egress FAIL non ha prodotto alcun journal `rolled_back`: "
            f"stati osservati {sorted(states)}")

    # ---- fronte STRUTTURALE, Stage 10: il validator NON scrive ------------
    case = clone(ctx, base, "c02-s10")
    document = copy.deepcopy(case["document"])
    registry = (document.get("financial_plan") or {}).get("driver_registry")
    if not isinstance(registry, dict) or not registry.get("drivers"):
        findings.append(
            "il canonico di riferimento non porta un driver_registry "
            "popolato: il caso negativo di Stage 10 non sarebbe discriminante")
        return findings
    registry["drivers"] = []
    degenerate = case["canonical"].parent / CANONICAL_NAME
    tree_before = kit.snapshot_tree(case["project"])
    degenerate.write_text(json.dumps(document, indent=2, ensure_ascii=True,
                                     sort_keys=True) + "\n", encoding="utf-8")
    tree_after_write = kit.snapshot_tree(case["project"])
    verdict = run_output_validator(ctx, case["project"],
                                   case["canonical"].parent)
    if verdict["exit_code"] == 0:
        findings.append(
            "il validator canonico dello Stage 10 ACCETTA un canonico con "
            "driver_registry VUOTO: il gate 1 non discrimina")
    if kit.snapshot_tree(case["project"]) != tree_after_write:
        findings.append(
            "il validator canonico dello Stage 10 ha SCRITTO nel progetto: un "
            "validator non e' mai una superficie di scrittura")
    if tree_before == tree_after_write:
        findings.append(
            "la mutazione del canonico non ha cambiato l'albero: il caso "
            "negativo non e' stato costruito")
    return findings


# --------------------------------------------------------------------------
# FQ-C-03 — T-FIN-RESUME
# --------------------------------------------------------------------------


def c03(ctx, base):
    """`T-FIN-RESUME` — la ripresa a meta' Stage 10 NON riapre alcuno stage
    approvato.

    Lo stato di ripresa e' l'inizio dello Stage 10:
    `current_stage = 10_financial-plan`, `status = not_started`,
    `next_action` boundary-aware. Lo Stage 10 e' DENTRO il release
    boundary: `next_action` invita ad avviarlo.
    """
    findings = []
    project = terminal_project(base, "c03-terminal")
    before = kit.snapshot_canonical(project)
    front_before = kit.load_module(ctx["root"], kit.VALIDATORS_REL,
                                   "_framework").parse_front_matter(
        (project / "shared/project-status.md").read_text(encoding="utf-8"))

    exit_code, out, err = kit.run_tm_cli(ctx["root"], "recover", "--project",
                                         project)
    if exit_code != 0:
        findings.append(
            f"il resume di un progetto allo stato terminale fallisce (exit "
            f"{exit_code}): {out.strip()[:200]!r} {err.strip()[:200]!r}")
    if kit.snapshot_canonical(project) != before:
        findings.append(
            "il resume ha MUTATO il canonico di un progetto senza transazioni "
            "pendenti")
    front_after = kit.load_module(ctx["root"], kit.VALIDATORS_REL,
                                  "_framework").parse_front_matter(
        (project / "shared/project-status.md").read_text(encoding="utf-8"))
    if front_after.get("completed_stages") != front_before.get(
            "completed_stages"):
        findings.append(
            f"il resume ha cambiato completed_stages: "
            f"{front_before.get('completed_stages')} -> "
            f"{front_after.get('completed_stages')}")
    if (project / STAGE10 / CANONICAL_NAME).exists():
        findings.append(
            f"il resume ha creato {STAGE10}/{CANONICAL_NAME}: `recover` non "
            "scrive mai un output canonico senza una transazione pendente")
    # Il `next_action` boundary-aware e' misurato dove viene PRODOTTO — la
    # funzione che l'advance calcola NELLA STESSA transazione — e non sul
    # campo della fixture, che nessun advance ha scritto: misurare la fixture
    # sarebbe misurare il costruttore del test.
    terminal_action = TM.boundary_next_action(STAGE10, ctx["config"])
    if "release boundary" in terminal_action.lower():
        findings.append(
            f"il next_action calcolato per {STAGE10} porta ancora il "
            f"messaggio di confine — lo Stage 10 e' DENTRO il release "
            f"boundary: {terminal_action!r}")
    if f"avviare {STAGE10}" not in terminal_action:
        findings.append(
            f"il next_action calcolato per {STAGE10} deve invitare ad "
            f"avviarlo: {terminal_action!r}")
    inside_action = TM.boundary_next_action(INSIDE_STAGE, ctx["config"])
    if "release boundary" in inside_action.lower():
        findings.append(
            f"il next_action di uno stage DENTRO il confine ({INSIDE_STAGE}) "
            f"porta il messaggio di confine: {inside_action!r} — la regola "
            "sarebbe incondizionata e non discriminante")
    # SOLO la sonda oltre il confine dipende dalla posizione del confine.
    # Con il confine
    # sull'ULTIMO stage la sonda e' in forma T1 — variante in-process con il
    # confine a 12_data-room, dove lo Stage 13 porta il messaggio di confine —
    # piu' l'asserzione REALE che lo Stage 13 si avvia. Ogni altra asserzione
    # di questo contratto — uscita e zero mutazione di `recover`,
    # `completed_stages`, nessuna creazione di output canonico, discriminante
    # dello stage DENTRO il confine, negativi `stage_already_completed`,
    # semantica di resume e idempotenza — resta INVARIATA.
    variant = json.loads(json.dumps(ctx["config"]))
    variant["release_boundary"] = STAGE12
    beyond_action = TM.boundary_next_action(STAGE13, variant)
    if "release boundary" not in beyond_action.lower():
        findings.append(
            f"il next_action calcolato per {STAGE13} a confine 12 (forma T1) "
            f"non e' boundary-aware: {beyond_action!r}")
    real_action = TM.boundary_next_action(STAGE13, ctx["config"])
    if real_action != f"avviare {STAGE13}":
        findings.append(
            f"il next_action REALE di {STAGE13}, dentro il confine, deve "
            f"invitare ad avviarlo: {real_action!r}")

    # ---- caso negativo: il resume RILANCIA uno stage COMPLETATO ----------
    completed = front_before.get("completed_stages") or []
    if not completed:
        findings.append(
            "la fixture terminale non porta alcuno stage completato: il caso "
            "negativo del resume non sarebbe discriminante")
        return findings
    reopened = completed[-1]
    for command in ("apply", "advance-stage"):
        # Il rifiuto RIPULISCE il candidate attivo: ciascun comando riceve
        # quindi il PROPRIO candidate, altrimenti il secondo misurerebbe un
        # errore d'uso invece del rifiuto di dominio.
        candidate = kit.make_candidate(
            project, reopened, tx_id=f"tx-reopen-{command}",
            structured={"reopened": True})
        snapshot = kit.snapshot_canonical(project)
        exit_code, out, _ = kit.run_tm_cli(
            ctx["root"], command, "--project", project, "--stage", reopened,
            "--candidate", candidate)
        if exit_code == 0:
            findings.append(
                f"{command} su {reopened}, gia' in completed_stages, e' stato "
                "ACCETTATO: il resume puo' riaprire uno stage approvato")
            continue
        codes = {item["code"] for item in kit.tm_result(out, "c03")["errors"]}
        if "stage_already_completed" not in codes:
            findings.append(
                f"{command} su uno stage completato: atteso "
                f"`stage_already_completed`, ottenuti {sorted(codes)}")
        if kit.snapshot_canonical(project) != snapshot:
            findings.append(
                f"{command} su uno stage completato, pur respinto, ha MUTATO "
                "il canonico")
    return findings


# --------------------------------------------------------------------------
# FQ-C-04 — T-FIN-CRASH-RECOVERY
# --------------------------------------------------------------------------


def crash_apply(ctx, project, candidate, spec):
    return kit.run_tm_cli(
        ctx["root"], "apply", "--project", project, "--stage", INSIDE_STAGE,
        "--candidate", candidate, env_extra={"BPO_TX_TEST_CRASH": spec})


def temporary_survivors(project):
    return sorted(path.relative_to(project).as_posix()
                  for path in Path(project).rglob("*")
                  if path.is_file() and (path.suffix in (".tmp", ".bak")
                                         or ".tmp-" in path.name))


def c04(ctx, base):
    """`T-FIN-CRASH-RECOVERY` — un crash a QUALUNQUE punto del journal produce
    una recovery CORRETTA, e nessun output PARZIALE sopravvive.

    «Corretta» NON significa «sempre rollback», e la distinzione e' la sostanza
    del contratto:

      - write-set INCOMPLETO  -> ROLLBACK dallo snapshot, stato byte-identico
        al precedente;
      - write-set COMPLETO e marker mancante -> COMPLETAMENTO marker-only, e lo
        stato risultante e' ESATTAMENTE quello VALIDATO, verificato per
        CONTENUTO e mai per sola esistenza;
      - DRIFT durante la finestra di crash -> nessun commit, e ripristino.

    Un contratto che pretendesse il rollback anche nel secondo caso misurerebbe
    una regola che il Transaction Manager non ha, e sarebbe verde solo per caso.
    """
    findings = []

    # ---- 1  write-set INCOMPLETO: ROLLBACK dallo snapshot ----------------
    project = tm_project(base, "c04-partial")
    candidate = tm_candidate(project)
    before = kit.snapshot_canonical(project)
    exit_code, _, _ = crash_apply(ctx, project, candidate, "after_writes:2")
    if exit_code == 0:
        findings.append(
            "crash dopo due scritture: l'hook non ha interrotto la "
            "transazione, il caso non e' stato costruito")
    else:
        exit_code, out, err = kit.run_tm_cli(ctx["root"], "recover",
                                             "--project", project)
        if exit_code != 0:
            findings.append(
                f"crash dopo due scritture: il recover fallisce (exit "
                f"{exit_code}): {out.strip()[:200]!r} {err.strip()[:200]!r}")
        after = kit.snapshot_canonical(project)
        if after != before:
            differing = sorted(set(after) ^ set(before)) or sorted(
                rel for rel in before if before[rel] != after.get(rel))
            findings.append(
                f"crash dopo due scritture: il recover NON ha ripristinato lo "
                f"stato canonico: {differing}")
        if f"{INSIDE_STAGE}/{CANONICAL_NAME}" not in before and \
                (project / INSIDE_STAGE / CANONICAL_NAME).exists():
            findings.append(
                "crash dopo due scritture: un output canonico che PRIMA non "
                "esisteva e' sopravvissuto al recover")
        survivors = temporary_survivors(project)
        if survivors:
            findings.append(
                f"crash dopo due scritture: file temporanei sopravvissuti al "
                f"recover: {survivors}")
        # lo snapshot che guida il rollback e' COMPLETO
        for journal in journals_by_state(project).get("rolled_back", []):
            snapshot_rel = journal.get("snapshot_path")
            if not snapshot_rel:
                continue
            for entry in journal.get("write_set", []):
                if entry.get("pre_hash") is None:
                    continue
                if not (project / snapshot_rel / entry["path"]).is_file():
                    findings.append(
                        f"crash dopo due scritture: snapshot INCOMPLETO — "
                        f"{entry['path']} manca dallo snapshot che dovrebbe "
                        "guidare il rollback")

    # ---- 2  write-set COMPLETO: completamento marker-only ----------------
    complete = tm_project(base, "c04-marker")
    candidate = tm_candidate(complete)
    exit_code, _, _ = crash_apply(ctx, complete, candidate, "before_commit")
    if exit_code == 0:
        findings.append(
            "crash prima del commit: l'hook non ha interrotto la transazione, "
            "il caso non e' stato costruito")
    else:
        journals = kit.find_journals(complete)
        pending = [kit.read_json(path) for path in journals]
        if not any(item.get("state") == "applying" for item in pending):
            findings.append(
                f"crash prima del commit: nessun journal in stato `applying`: "
                f"{[item.get('state') for item in pending]}")
        exit_code, out, err = kit.run_tm_cli(ctx["root"], "recover",
                                             "--project", complete)
        if exit_code != 0:
            findings.append(
                f"crash prima del commit: il recover fallisce (exit "
                f"{exit_code}): {out.strip()[:200]!r} {err.strip()[:200]!r}")
        recovered = [kit.read_json(path) for path in kit.find_journals(complete)]
        committed = [item for item in recovered
                     if item.get("state") == "committed"]
        if not committed:
            findings.append(
                "crash prima del commit con write-set COMPLETO: il recover non "
                f"ha completato la transazione: "
                f"{[item.get('state') for item in recovered]}")
        # lo stato risultante e' ESATTAMENTE quello VALIDATO: verifica di
        # CONTENUTO, mai per sola esistenza
        for journal in committed:
            problems = TM.verify_write_set(complete, journal)
            if problems:
                findings.append(
                    f"crash prima del commit: lo stato completato dal recover "
                    f"NON coincide con i byte validati: {problems}")
        survivors = temporary_survivors(complete)
        if survivors:
            findings.append(
                f"crash prima del commit: file temporanei sopravvissuti al "
                f"recover: {survivors}")

    # ---- caso negativo: DRIFT nella finestra di crash -> nessun commit ---
    drifted = tm_project(base, "c04-drift")
    candidate = tm_candidate(drifted)
    before = kit.snapshot_canonical(drifted)
    exit_code, _, _ = crash_apply(ctx, drifted, candidate, "before_commit")
    if exit_code == 0:
        findings.append(
            "caso negativo di drift: l'hook non ha interrotto la transazione")
        return findings
    journal_path = kit.find_journals(drifted)[0]
    journal = kit.read_json(journal_path)
    snapshot_dir = drifted / journal["candidate_snapshot_path"]
    target = next((path for path in sorted(snapshot_dir.rglob("*"))
                   if path.is_file()), None)
    if target is None:
        findings.append(
            "lo snapshot del candidate e' vuoto: il caso di drift non e' "
            "costruibile")
        return findings
    target.write_text("contenuto DERIVATO durante la finestra di crash\n",
                      encoding="utf-8")
    kit.run_tm_cli(ctx["root"], "recover", "--project", drifted)
    if kit.read_json(journal_path).get("state") == "committed":
        findings.append(
            "il recover ha COMMITTATO uno snapshot del candidate DERIVATO "
            "durante la finestra di crash: un drift verrebbe sanato dalla "
            "recovery")
    if kit.snapshot_canonical(drifted) != before:
        findings.append(
            "il recover di uno snapshot derivato non ha RIPRISTINATO lo stato")
    return findings


# --------------------------------------------------------------------------
# FQ-C-05 — T-FIN-IDEMPOTENCY
# --------------------------------------------------------------------------


def c05(ctx, base):
    """`T-FIN-IDEMPOTENCY` — lo STESSO `operation_id` produce lo STESSO
    risultato, e NESSUN doppio evento di audit."""
    findings = []
    project = tm_project(base, "c05")
    register = kit.read_json(project / "shared/assumptions-register.json")
    entry = next(item for item in register if item["id"] == "ASS-001")
    payload = {
        "operation_id": "op-m6a-idempotency",
        "reason": "revisione su nuova evidenza",
        "decision": {"decision_type": "assumption_update",
                     "options_considered": "mantenere vs aggiornare",
                     "motivation": "evidenza aggiornata",
                     "impact": "nessun derivato coinvolto",
                     "approver": "founder"},
        "changes": [{"assumption_id": "ASS-001",
                     "expected_record_hash": TM.record_fingerprint(entry),
                     "updates": {"value": 42.0}}],
    }
    changes = Path(base) / "c05-changes.json"
    changes.write_text(json.dumps(payload, indent=2, ensure_ascii=True),
                       encoding="utf-8")

    exit_code, out, err = kit.run_tm_cli(
        ctx["root"], "update-assumption", "--project", project,
        "--changes", changes)
    if exit_code != 0:
        findings.append(
            f"il primo update-assumption fallisce (exit {exit_code}): "
            f"{out.strip()[:250]!r} {err.strip()[:250]!r}")
        return findings
    first = kit.tm_result(out, "c05-first")
    after_first = kit.snapshot_canonical(project)
    audit_first = (project / "shared/audit-log.jsonl").read_text(
        encoding="utf-8").splitlines() if (
            project / "shared/audit-log.jsonl").exists() else []
    decisions_first = kit.read_json(project / "shared/decisions-register.json")

    exit_code, out, err = kit.run_tm_cli(
        ctx["root"], "update-assumption", "--project", project,
        "--changes", changes)
    if exit_code != 0:
        findings.append(
            f"la RIESECUZIONE con lo stesso operation_id fallisce (exit "
            f"{exit_code}): {out.strip()[:250]!r}")
        return findings
    second = kit.tm_result(out, "c05-second")
    if second.get("result") != "already_applied":
        findings.append(
            f"la riesecuzione con lo stesso operation_id ha prodotto "
            f"{second.get('result')!r} invece di `already_applied`: "
            "l'operazione non e' idempotente")
    if second.get("decision_id") != first.get("decision_id"):
        findings.append(
            f"la riesecuzione ha allocato una decisione DIVERSA: "
            f"{first.get('decision_id')!r} -> {second.get('decision_id')!r}")
    if kit.snapshot_canonical(project) != after_first:
        findings.append(
            "la riesecuzione con lo stesso operation_id ha MUTATO di nuovo lo "
            "stato canonico")
    audit_second = (project / "shared/audit-log.jsonl").read_text(
        encoding="utf-8").splitlines()
    applied_first = [line for line in audit_first if '"applied"' in line]
    applied_second = [line for line in audit_second if '"applied"' in line]
    if len(applied_second) != len(applied_first):
        findings.append(
            f"la riesecuzione ha aggiunto un DOPPIO evento di audit applicato: "
            f"{len(applied_first)} -> {len(applied_second)}")
    decisions_second = kit.read_json(project / "shared/decisions-register.json")
    if len(decisions_second) != len(decisions_first):
        findings.append(
            f"la riesecuzione ha aggiunto una SECONDA decisione: "
            f"{len(decisions_first)} -> {len(decisions_second)}")

    # ---- caso negativo: stesso operation_id, payload DIVERSO -------------
    conflicting = copy.deepcopy(payload)
    conflicting["changes"][0]["updates"]["value"] = 99.0
    register_now = kit.read_json(project / "shared/assumptions-register.json")
    entry_now = next(item for item in register_now if item["id"] == "ASS-001")
    conflicting["changes"][0]["expected_record_hash"] = \
        TM.record_fingerprint(entry_now)
    conflict_path = Path(base) / "c05-conflict.json"
    conflict_path.write_text(json.dumps(conflicting, indent=2,
                                        ensure_ascii=True), encoding="utf-8")
    snapshot = kit.snapshot_canonical(project)
    exit_code, out, _ = kit.run_tm_cli(
        ctx["root"], "update-assumption", "--project", project,
        "--changes", conflict_path)
    if exit_code == 0:
        findings.append(
            "uno STESSO operation_id con un payload DIVERSO e' stato "
            "accettato: l'idempotenza e' una riscrittura silenziosa")
    else:
        codes = {item["code"]
                 for item in kit.tm_result(out, "c05-conflict")["errors"]}
        if "operation_id_conflict" not in codes:
            findings.append(
                f"payload divergente con lo stesso operation_id: atteso "
                f"`operation_id_conflict`, ottenuti {sorted(codes)}")
    if kit.snapshot_canonical(project) != snapshot:
        findings.append(
            "il conflitto di operation_id, pur respinto, ha MUTATO lo stato")
    return findings


# --------------------------------------------------------------------------
# FQ-C-06 — T-FIN-WRITE-SET
# --------------------------------------------------------------------------


def c06(ctx, base):
    """`T-FIN-WRITE-SET` — l'allow-list NON ESTESA continua a difendere per
    mode, e un artefatto non previsto NON entra nel write-set.

    E' la verifica ESEGUITA della regola «zero nuovi path canonici»: i DUE
    derivati obbligatori dello Stage 10 NON sono nel write-set, e non devono
    esserlo.
    """
    findings = []

    # ---- fronte STRUTTURALE, Stage 10: l'allow-list per mode -------------
    # L'insieme e' confrontato per UGUAGLIANZA ESATTA, mode per mode. Misurare
    # la sola ASSENZA del canonico non basterebbe: un mode che collassasse
    # sull'insieme di default supererebbe un controllo di sola assenza, e la
    # specializzazione per mode — che e' cio' che il contratto misura —
    # sarebbe morta senza che nulla lo dicesse.
    expected = {
        "apply": {"shared/assumptions-register.json",
                  "shared/conditions-register.json",
                  "shared/project-status.md", "shared/audit-log.jsonl",
                  f"{STAGE10}/{CANONICAL_NAME}", f"{STAGE10}/handoff.md"},
        "advance": {"shared/assumptions-register.json",
                    "shared/conditions-register.json",
                    "shared/project-status.md", "shared/audit-log.jsonl",
                    f"{STAGE10}/{CANONICAL_NAME}", f"{STAGE10}/handoff.md"},
        "update_assumption": {"shared/assumptions-register.json",
                              "shared/decisions-register.json",
                              "shared/decision-log.md",
                              "shared/project-status.md",
                              "shared/audit-log.jsonl"},
        "resolve_condition": {"shared/conditions-register.json",
                              "shared/decisions-register.json",
                              "shared/decision-log.md",
                              "shared/project-status.md",
                              "shared/audit-log.jsonl"},
        None: {"shared/project-status.md", "shared/audit-log.jsonl"},
    }
    for mode, allowed_paths in expected.items():
        observed = TM.authorized_write_paths(STAGE10, mode)
        if observed != allowed_paths:
            findings.append(
                f"authorized_write_paths({STAGE10!r}, {mode!r}) = "
                f"{sorted(observed)}; atteso ESATTAMENTE "
                f"{sorted(allowed_paths)}")
        if mode in ("apply", "advance"):
            for derived in (f"{STAGE10}/{CHAPTER_NAME}",
                            f"{STAGE10}/{WORKBOOK_NAME}"):
                if derived in observed:
                    findings.append(
                        f"il DERIVATO {derived} e' entrato nel write-set del "
                        f"mode {mode!r}: la regola esige ZERO nuovi path "
                        "canonici, e un .xlsx e' un BINARIO dentro un "
                        "meccanismo che legge ogni file del write-set COME "
                        "TESTO")
        elif f"{STAGE10}/{CANONICAL_NAME}" in observed:
            findings.append(
                f"il mode {mode!r} puo' scrivere {STAGE10}/{CANONICAL_NAME}: "
                "un journal alterato riscriverebbe un output di stage")

    # ---- caso negativo 1: journal `update_assumption` ALTERATO -----------
    doctored = {
        "transaction_id": "tx-doctored-001",
        "project": "irrilevante",
        "stage": STAGE10,
        "mode": "update_assumption",
        "state": "applying",
        "snapshot_path": "shared/.tx/tx-doctored-001-snapshot",
        "write_set": [{"path": f"{STAGE10}/{CANONICAL_NAME}",
                       "pre_hash": None, "post_hash": "0" * 64}],
        "pass_map": {},
        "timestamps": {"preparing": "2026-08-05T00:00:00Z"},
    }
    rejected = False
    try:
        TM.validate_journal(copy.deepcopy(doctored), "tx-doctored-001.json")
    except TM.TransactionError as exc:
        rejected = True
        if exc.code != "journal_corrupted":
            findings.append(
                f"journal `update_assumption` alterato: atteso "
                f"`journal_corrupted`, ottenuto {exc.code!r}")
    if not rejected:
        findings.append(
            f"un journal con mode `update_assumption` e write_set "
            f"{STAGE10}/{CANONICAL_NAME} e' stato ACCETTATO: l'allow-list per "
            "mode e' VACUA")
    # lo stesso path e' invece LEGITTIMO per il mode `apply`: il caso negativo
    # discrimina il MODE, non il path.
    legitimate = dict(doctored, mode="apply",
                      transaction_id="tx-legitimate-001")
    try:
        TM.validate_journal(copy.deepcopy(legitimate), "tx-legitimate-001.json")
    except TM.TransactionError as exc:
        findings.append(
            f"lo stesso path e' respinto anche per il mode `apply` "
            f"({exc.code}): il caso negativo misura il PATH e non il MODE, e "
            "non sarebbe discriminante")

    # ---- caso negativo 2: un journal che guida una RECOVERY reale --------
    project = tm_project(base, "c06-recover")
    tx_dir = project / "shared" / ".tx"
    tx_dir.mkdir(parents=True, exist_ok=True)
    (tx_dir / "tx-doctored-001.json").write_text(
        json.dumps(dict(doctored, project=str(project)), indent=2,
                   ensure_ascii=True), encoding="utf-8")
    before = kit.snapshot_canonical(project)
    exit_code, out, _ = kit.run_tm_cli(ctx["root"], "recover", "--project",
                                       project)
    if exit_code == 0:
        findings.append(
            "una recovery guidata da un journal ALTERATO e' riuscita: il "
            "journal corrotto ha guidato una scrittura")
    elif out.strip().startswith("{"):
        codes = {item.get("code")
                 for item in json.loads(out).get("errors", [])}
        if "journal_corrupted" not in codes:
            findings.append(
                f"recovery su journal alterato: atteso `journal_corrupted`, "
                f"ottenuti {sorted(codes)}")
    if kit.snapshot_canonical(project) != before:
        findings.append(
            "la recovery guidata da un journal alterato ha MUTATO il canonico")

    # ---- caso negativo 3: artefatto NON PREVISTO nel candidate -----------
    extra = tm_project(base, "c06-extra")
    candidate = tm_candidate(extra, extra_files=(WORKBOOK_NAME,
                                                 "unexpected-artifact.md"))
    exit_code, out, err = kit.run_tm_cli(
        ctx["root"], "apply", "--project", extra, "--stage", INSIDE_STAGE,
        "--candidate", candidate)
    if exit_code != 0:
        findings.append(
            f"un candidate con artefatti EXTRA ha impedito il commit (exit "
            f"{exit_code}): {out.strip()[:200]!r} {err.strip()[:200]!r}")
    else:
        committed = journals_by_state(extra).get("committed") or []
        if not committed:
            findings.append(
                "nessun journal `committed` dopo un apply riuscito")
        for journal in committed:
            paths = {item["path"] for item in journal.get("write_set", [])}
            leaked = sorted(path for path in paths
                            if path.endswith((WORKBOOK_NAME,
                                              "unexpected-artifact.md")))
            if leaked:
                findings.append(
                    f"un artefatto NON PREVISTO del candidate e' entrato nel "
                    f"write-set: {leaked}; il write-set nasce da nomi NOTI, "
                    "mai da una scoperta dinamica del candidate")
        for name in (WORKBOOK_NAME, "unexpected-artifact.md"):
            if (extra / INSIDE_STAGE / name).exists():
                findings.append(
                    f"l'artefatto non previsto {name} e' stato SCRITTO nello "
                    "stato canonico")
    return findings


# --------------------------------------------------------------------------
# FQ-C-07 — T-FIN-NO-STAGE-BEYOND-TERMINAL (oltre l'ultimo stage)
# --------------------------------------------------------------------------


def beyond_terminal_paths(tree):
    """RILEVATORE STATICO — path di uno stage OLTRE l'ultimo sotto un albero.

    La guardia scatta su un segmento di stage `NN_` con `NN >= 14`. NON
    scatta sul path ESATTO `workflows/14_document-generation.md`, che per la
    convenzione del repository — workflow `NN_` = stage `NN-1` — e' il
    workflow dello STAGE 13 e non un artefatto di uno Stage 14: e' la STESSA
    convenzione `NN_` = stage `NN-1`, ristretta al path esatto.
    """
    hits = []
    root = Path(tree)
    if not root.exists():
        return hits
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        segments = rel.split("/")
        if any(token in rel for token in FORBIDDEN_STAGE_TOKENS):
            hits.append(rel)
            continue
        if rel in NN_CONVENTION_EXEMPTIONS:
            continue
        for segment in segments:
            if segment.startswith(FORBIDDEN_STAGE_PREFIXES):
                hits.append(rel)
                break
    return hits


def c07(ctx, base):
    """`T-FIN-NO-STAGE-BEYOND-TERMINAL` — oltre l'ULTIMO stage di
    `stage_order` non esiste alcuno stage: `apply` e `advance-stage` su un
    identificatore ASSENTE da `stage_order` e `governance-status` su un piano
    COMPLETATO sono respinti come errori d'uso, exit 2, ZERO scritture; e la
    pipeline dello Stage 10 non crea alcun path di uno stage oltre il
    terminale.

    FORMA TERMINALE: con il confine sull'ultimo stage non esiste un
    bersaglio reale «oltre», e la SOSTANZA e' verificata in forma T2. `F1` — i TRE comandi restano tre, respinti
    ciascuno con un rifiuto attribuito. `F2` — zero scrittura: il rifiuto
    PRECEDE lock, journal e qualunque I/O. `F3` — il rilevatore respinge i
    segmenti `NN_` con `NN >= 14`, con l'esenzione `NN_` per path ESATTO del
    workflow dello Stage 13. `F4` — l'auto-verifica trasla col bersaglio.
    """
    findings = []
    project = terminal_project(base, "c07-s13", stage=STAGE13)
    before = kit.snapshot_canonical(project)
    candidate = kit.make_candidate(project, ABSENT_STAGE, tx_id="tx-absent",
                                   structured={"document_generation": {}})
    for command in ("apply", "advance-stage"):
        exit_code, out, err = kit.run_tm_cli(
            ctx["root"], command, "--project", project, "--stage",
            ABSENT_STAGE, "--candidate", candidate)
        if exit_code != 2:
            findings.append(
                f"{command} su {ABSENT_STAGE}, assente da stage_order: atteso "
                f"exit 2, ottenuto {exit_code} ({out.strip()[:150]!r} "
                f"{err.strip()[:150]!r})")
    completed_project = kit.make_project(
        base, name="c07-complete", current_stage=STAGE13, status="approved",
        completed=list(ORDER_CACHE["order"]),
        assumptions=m5.market_assumptions())
    completed_before = kit.snapshot_canonical(completed_project)
    exit_code, out, err = kit.run_tm_cli(
        ctx["root"], "governance-status", "--project", completed_project,
        "--updates", json.dumps({"status": "in_progress"}),
        "--reason", "riapertura del piano completato")
    if exit_code != 2:
        findings.append(
            f"governance-status su un piano COMPLETATO: atteso exit 2, "
            f"ottenuto {exit_code} ({out.strip()[:150]!r} "
            f"{err.strip()[:150]!r})")
    if kit.snapshot_canonical(completed_project) != completed_before:
        findings.append(
            "governance-status su un piano completato ha MUTATO il canonico")
    after = kit.snapshot_canonical(project)
    if after != before:
        findings.append(
            "un tentativo operativo oltre l'ultimo stage ha MUTATO il "
            "canonico: il rifiuto deve precedere lock, journal e qualunque "
            "I/O")

    # ---- la pipeline dello Stage 10 non crea alcun path oltre il terminale
    case = clone(ctx, base, "c07-pipeline")
    leaked = beyond_terminal_paths(case["project"])
    if leaked:
        findings.append(
            f"la pipeline dello Stage 10 ha creato path di uno stage oltre il "
            f"terminale: {leaked}")
    for artifact, text in (("canonico", json.dumps(case["document"])),
                           ("capitolo", case["text"])):
        named = sorted(token for token in FORBIDDEN_STAGE_TOKENS
                       if token in text)
        if named:
            findings.append(
                f"il {artifact} dello Stage 10 NOMINA token di Stage 13: "
                f"{named}")

    # ---- AUTO-VERIFICA del rilevatore statico ---------------------------
    probe = Path(base) / "c07-probe"
    (probe / "14_x").mkdir(parents=True)
    (probe / "14_x" / CANONICAL_NAME).write_text("{}", encoding="utf-8")
    (probe / "workflows").mkdir()
    (probe / "workflows" / "14_document-generation.md").write_text(
        "# workflow dello Stage 13\n", encoding="utf-8")
    (probe / "methodology").mkdir()
    (probe / "methodology" / "14_document-generation.md").write_text(
        "# segmento 14_ FUORI dal path esentato\n", encoding="utf-8")
    detected = beyond_terminal_paths(probe)
    if not any("14_x" in hit for hit in detected):
        findings.append(
            "AUTO-VERIFICA FALLITA: il rilevatore statico non rileva un path "
            "14_x iniettato — il rilevatore e' VACUO")
    if "workflows/14_document-generation.md" in detected:
        findings.append(
            "AUTO-VERIFICA FALLITA: il rilevatore statico respinge "
            "workflows/14_document-generation.md, che per la convenzione "
            "workflow NN_ = stage NN-1 e' il workflow dello STAGE 13 e non un "
            "artefatto di uno Stage 14")
    if "methodology/14_document-generation.md" not in detected:
        findings.append(
            "AUTO-VERIFICA FALLITA: l'esenzione NN_ non e' per path ESATTO: "
            "un segmento 14_ fuori da workflows/14_document-generation.md non "
            "e' rilevato")
    return findings


# --------------------------------------------------------------------------
# FQ-C-08 — T-FIN-DERIVED-CHECKSUM
# --------------------------------------------------------------------------


def c08(ctx, base):
    """`T-FIN-DERIVED-CHECKSUM` — ENTRAMBI i derivati obbligatori portano il
    `canonical_source_checksum` CORRENTE. Uno stantio e' `derived_artifact_stale`
    e FAIL, MAI `WARNING`."""
    findings = []
    case = clone(ctx, base, "c08")
    canonical_checksum = GATE.canonical_checksum(case["document"])
    if not canonical_checksum:
        findings.append(
            "il canonico non dichiara `calculation_metadata.output_checksums."
            "base`: non esiste alcun checksum corrente da propagare")
        return findings
    checksum_findings, checksums = GATE.triangular_checksums(
        case["document"], case["text"], case["package"])
    if checksum_findings:
        findings.append(
            f"i TRE checksum non coincidono sul caso nominale: "
            f"{[item['message'] for item in checksum_findings]}")
    for key in ("canonical", "chapter", "workbook"):
        if checksums.get(key) != canonical_checksum:
            findings.append(
                f"il checksum di {key} e' {checksums.get(key)!r} invece del "
                f"canonico corrente {canonical_checksum!r}")

    # ---- caso negativo A: CAPITOLO stantio, sul disco --------------------
    stale = "b" * 64
    stale_case = clone(ctx, base, "c08-stale-chapter")
    stale_case["chapter"].write_text(
        stale_case["text"].replace(canonical_checksum, stale),
        encoding="utf-8")
    verdict = GATE.check(stale_case["project"], stale_case["canonical"], TX_ID)
    if verdict["passed"]:
        findings.append(
            "un CAPITOLO con checksum di una generazione PRECEDENTE supera il "
            "gate di completamento: un derivato stantio e' consegnato come "
            "fresco")
    elif CODE_STALE not in codes_of(verdict["findings"]):
        findings.append(
            f"capitolo stantio: atteso {CODE_STALE}, ottenuti "
            f"{codes_of(verdict['findings'])}")
    findings.extend(warning_leakage(verdict))

    # ---- caso negativo B: WORKBOOK stantio, in memoria -------------------
    mutated = copy.deepcopy(case["package"])
    reference = mutated["defined_names"].get("meta_canonical_checksum")
    if not reference:
        findings.append(
            "il workbook non dichiara il named range "
            "`meta_canonical_checksum`: la freschezza del workbook non e' "
            "verificabile")
    else:
        sheet, cell_ref = GATE.split_ref(reference)
        mutated["sheets"][sheet][cell_ref]["value"] = stale
        stale_findings, _ = GATE.triangular_checksums(
            case["document"], case["text"], mutated)
        workbook_stale = [item for item in stale_findings
                          if item["code"] == CODE_STALE and
                          "workbook" in item["where"]]
        if not workbook_stale:
            findings.append(
                "un WORKBOOK con checksum di una generazione PRECEDENTE non e' "
                f"rilevato: atteso {CODE_STALE} attribuito al workbook, "
                f"ottenuti {[item['message'] for item in stale_findings]}")

    # ---- caso negativo C: capitolo con DUE generazioni contemporanee -----
    mixed = clone(ctx, base, "c08-mixed")
    captions = GATE.parse_chapter(mixed["text"])["tables"]
    if len(captions) < 2:
        findings.append(
            f"il capitolo porta {len(captions)} didascalie di tabella: il caso "
            "della generazione MISTA richiede almeno DUE checksum dichiarati")
    else:
        # La generazione mista si costruisce sulla DIDASCALIA, che e' la sola
        # sede in cui il capitolo DICHIARA il proprio checksum: mutare la prima
        # occorrenza testuale toccherebbe un'intestazione che nessun contratto
        # legge, e il caso non sarebbe discriminante.
        lines = mixed["text"].split("\n")
        index = captions[0]["line"] - 1
        lines[index] = lines[index].replace(canonical_checksum, stale)
        mixed["chapter"].write_text("\n".join(lines), encoding="utf-8")
        reparsed = GATE.parse_chapter("\n".join(lines))
        if len({table["checksum"] for table in reparsed["tables"]}) < 2:
            findings.append(
                "la mutazione non ha prodotto DUE checksum distinti nelle "
                "didascalie: il caso della generazione mista non e' stato "
                "costruito")
        verdict = GATE.check(mixed["project"], mixed["canonical"], TX_ID)
        if verdict["passed"]:
            findings.append(
                "un capitolo che porta DUE checksum distinti supera il gate: "
                "una sola generazione deve essere ammessa")
        elif CODE_STALE not in codes_of(verdict["findings"]):
            findings.append(
                f"capitolo a due generazioni: atteso {CODE_STALE}, ottenuti "
                f"{codes_of(verdict['findings'])}")
        findings.extend(warning_leakage(verdict))
    return findings


# --------------------------------------------------------------------------
# FQ-C-09 — T-FIN-DERIVED-CROSS-CONSISTENCY
# --------------------------------------------------------------------------


def perturb(value, delta):
    try:
        return str(Decimal(str(value).strip()) + delta)
    except (InvalidOperation, ValueError):
        return None


def c09(ctx, base):
    """`T-FIN-DERIVED-CROSS-CONSISTENCY` — le NOVE metriche di testata
    coincidono fra JSON, Markdown ed Excel, con confronto TRIANGOLARE.

    UN CASO NEGATIVO PER CIASCUNA DELLE NOVE: nove sonde distinte,
    ciascuna attribuita alla propria
    metrica. Le metriche che il canonico non produce sono dichiarate
    `NOT_APPLICABLE` nel workbook — e' un CAVEAT PROPAGATO, non un difetto — e
    la loro sonda misura che la DICHIARAZIONE non puo' essere sostituita da un
    numero divergente.
    """
    findings = []
    tokens = ctx["tokens"]
    declared = [entry["id"] for entry in tokens.get("headline_metrics") or []]
    expected_nine = ["revenue", "gross_margin", "ebitda", "ending_cash",
                     "burn", "runway", "break_even", "funding_gap",
                     "milestone_coverage"]
    if declared != expected_nine:
        findings.append(
            f"le metriche di testata dichiarate sono {declared}; il "
            f"contratto ne enumera NOVE, alla lettera: {expected_nine}")
        return findings

    case = clone(ctx, base, "c09")
    nominal = GATE.xrec_04(case["document"], case["package"], case["text"],
                           tokens)
    if nominal:
        findings.append(
            f"il confronto triangolare nominale NON e' pulito: "
            f"{[item['message'] for item in nominal]}")
    metrics = GATE.headline_from_workbook(case["package"], tokens)
    missing = [name for name in expected_nine if name not in metrics]
    if missing:
        findings.append(
            f"metriche di testata ASSENTI dal Dashboard: {missing}")
        return findings

    chapter_by_path = {}
    for entry in GATE.chapter_value_rows(GATE.parse_chapter(case["text"])):
        chapter_by_path.setdefault(entry["path"], entry)

    for metric_id in expected_nine:
        found = metrics[metric_id]
        sheet, cell_ref = GATE.split_ref(f"Dashboard!{found['ref']}")
        entry = chapter_by_path.get(found["path"])
        unit = entry["unit"] if entry else GATE.UNDECLARED
        tolerance = GATE.tolerance_for(unit)

        # ---- sonda NEGATIVA, una per metrica -----------------------------
        mutated = copy.deepcopy(case["package"])
        if str(found["value"]) == NOT_APPLICABLE:
            # La metrica e' un CAVEAT DICHIARATO: la sonda sostituisce la
            # dichiarazione con un numero, che e' esattamente la mutazione da
            # uccidere — un caveat trasformato in valore.
            mutated["sheets"][sheet][cell_ref]["value"] = "123456.78"
            label = "caveat NOT_APPLICABLE sostituito da un numero"
        else:
            outside = perturb(found["value"], tolerance * 2 + Decimal("0.01"))
            if outside is None:
                findings.append(
                    f"metrica {metric_id}: valore non numerico "
                    f"{found['value']!r}, la sonda non e' costruibile")
                continue
            mutated["sheets"][sheet][cell_ref]["value"] = outside
            label = f"scarto oltre la tolleranza {tolerance} {unit}"
        detected = GATE.xrec_04(case["document"], mutated, case["text"], tokens)
        attributed = [item for item in detected
                      if names_metric(item, metric_id)]
        if not attributed:
            findings.append(
                f"metrica {metric_id}: {label} NON e' rilevato — il confronto "
                "triangolare e' VACUO su questa metrica")
        elif CODE_MISMATCH not in {item["code"] for item in attributed} and \
                CODE_INCOMPLETE not in {item["code"] for item in attributed}:
            findings.append(
                f"metrica {metric_id}: rilevata con codice "
                f"{sorted({item['code'] for item in attributed})}, atteso "
                f"{CODE_MISMATCH} o {CODE_INCOMPLETE}")

        # ---- discriminazione della TOLLERANZA ----------------------------
        if str(found["value"]) != NOT_APPLICABLE and tolerance > 0:
            inside_pkg = copy.deepcopy(case["package"])
            inside = perturb(found["value"], tolerance / 2)
            inside_pkg["sheets"][sheet][cell_ref]["value"] = inside
            noise = [item for item in
                     GATE.xrec_04(case["document"], inside_pkg, case["text"],
                                  tokens)
                     if names_metric(item, metric_id)]
            if noise:
                findings.append(
                    f"metrica {metric_id}: uno scarto DENTRO la tolleranza "
                    f"{tolerance} {unit} e' segnalato come difetto — la "
                    "tolleranza di repository non e' rispettata")

        # ---- la metrica ASSENTE dal Dashboard e' `derived_artifact_incomplete`
        dropped = copy.deepcopy(case["package"])
        row = GATE.row_of(found["ref"])
        dropped["sheets"]["Dashboard"].pop(f"A{row}", None)
        detected = GATE.xrec_04(case["document"], dropped, case["text"], tokens)
        attributed = [item for item in detected
                      if names_metric(item, metric_id)]
        if not attributed:
            findings.append(
                f"metrica {metric_id}: la sua RIMOZIONE dal Dashboard non e' "
                f"rilevata — atteso {CODE_INCOMPLETE}")
        elif CODE_INCOMPLETE not in {item["code"] for item in attributed}:
            findings.append(
                f"metrica {metric_id}: rimozione rilevata con "
                f"{sorted({item['code'] for item in attributed})}, atteso "
                f"{CODE_INCOMPLETE}")
    return findings


# --------------------------------------------------------------------------
# FQ-C-10 — T-FIN-DERIVED-MISSING
# --------------------------------------------------------------------------


def c10(ctx, base):
    """`T-FIN-DERIVED-MISSING` — l'assenza di un deliverable obbligatorio
    BLOCCA il gate di completamento MENTRE la transazione canonica resta
    VALIDA.

    E' la sonda che distingue i TRE gate della pipeline. Confonderli e' un
    difetto, e la confusione ha DUE versi opposti:
    un derivato mancante che fa fallire una transazione canonica valida, e un
    derivato mancante che non fa fallire NULLA. Entrambi sono misurati.
    """
    findings = []
    variants = (("capitolo assente", ("chapter",)),
                ("workbook assente", ("workbook",)),
                ("ENTRAMBI assenti, con canonico VALIDO", ("chapter",
                                                           "workbook")))
    for label, absent in variants:
        case = clone(ctx, base, f"c10-{len(absent)}-{absent[0]}")
        canonical_before = case["canonical"].read_bytes()
        for key in absent:
            case[key].unlink()
        verdict = GATE.check(case["project"], case["canonical"], TX_ID)
        if verdict["passed"]:
            findings.append(
                f"{label}: il gate di completamento e' SUPERATO — lo Stage 10 "
                "sarebbe dichiarato completo con il solo structured-output.json")
        elif CODE_INCOMPLETE not in codes_of(verdict["findings"]):
            findings.append(
                f"{label}: atteso {CODE_INCOMPLETE}, ottenuti "
                f"{codes_of(verdict['findings'])}")
        findings.extend(warning_leakage(verdict))
        # il CANONICO resta VALIDO e INTATTO: gate 1 non e' toccato da gate 2
        if case["canonical"].read_bytes() != canonical_before:
            findings.append(
                f"{label}: il canonico e' stato MODIFICATO dal fallimento del "
                "gate dei derivati")
        gate_one = run_output_validator(ctx, case["project"],
                                        case["canonical"].parent)
        if gate_one["exit_code"] != 0:
            findings.append(
                f"{label}: la TRANSAZIONE CANONICA e' fallita (exit "
                f"{gate_one['exit_code']}) per l'assenza di un DERIVATO — "
                "un difetto di presentazione ha corrotto lo stato")
    return findings


# --------------------------------------------------------------------------
# FQ-C-11 — T-FIN-DERIVED-REGENERATION
# --------------------------------------------------------------------------


def workbook_signature(package):
    """La firma di CONTENUTO del workbook: valori ufficiali, named range e
    ordine dei fogli. Esclude i soli metadati volatili permessi, che non sono
    ne' valori ufficiali ne' riferimenti."""
    return {
        "values": sorted(
            (row["sheet"], row["ref"], str(row["value"]), row["path"],
             row["unit"]) for row in GATE.workbook_value_rows(package)),
        "defined_names": sorted(package["defined_names"].items()),
        "order": list(package["order"]),
    }


def c11(ctx, base):
    """`T-FIN-DERIVED-REGENERATION` — i derivati sono RIGENERATI
    DETERMINISTICAMENTE dal SOLO canonico, e da nient'altro."""
    findings = []
    case = clone(ctx, base, "c11")
    chapter_before = case["chapter"].read_bytes()
    signature_before = workbook_signature(case["package"])

    # ---- rigenerazione dal SOLO canonico, senza alcun derivato preesistente
    case["chapter"].unlink()
    case["workbook"].unlink()
    rendered = run_generator(ctx, RENDERER_REL, case["canonical"],
                             case["project"])
    exported = run_generator(ctx, EXPORTER_REL, case["canonical"],
                             case["project"])
    if rendered["exit_code"] != 0 or exported["exit_code"] != 0:
        findings.append(
            f"la rigenerazione dal SOLO canonico e' fallita (renderer exit "
            f"{rendered['exit_code']}, exporter exit {exported['exit_code']}): "
            f"{(rendered['stdout'] or exported['stdout'])[:300]}")
        return findings
    if not case["chapter"].is_file() or not case["workbook"].is_file():
        findings.append(
            "la rigenerazione non ha ricostruito entrambi i derivati: il "
            "rollback di un derivato E' la sua rigenerazione, e deve essere "
            "sempre disponibile")
        return findings
    if case["chapter"].read_bytes() != chapter_before:
        findings.append(
            "il capitolo rigenerato dal SOLO canonico DIFFERISCE, byte per "
            "byte, da quello consegnato: la resa non e' una funzione pura del "
            "canonico")
    signature_after = workbook_signature(GATE.read_package(case["workbook"]))
    if signature_after != signature_before:
        findings.append(
            "il workbook rigenerato dal SOLO canonico non e' EQUIVALENTE per "
            "contenuto a quello consegnato: valori ufficiali, named range o "
            "ordine dei fogli sono cambiati")
    verdict = GATE.check(case["project"], case["canonical"], TX_ID)
    if not verdict["passed"]:
        findings.append(
            f"l'insieme rigenerato NON supera il gate di completamento: "
            f"{codes_of(verdict['findings'])}")

    # ---- caso negativo: canonico INCOERENTE -> nessun derivato prodotto --
    broken = clone(ctx, base, "c11-broken")
    document = json.loads(broken["canonical"].read_text(encoding="utf-8"))
    series = ((((document.get("financial_plan") or {}).get("results") or {})
               .get("modules") or {}).get("revenue") or {}).get("series")
    if not isinstance(series, dict) or not series:
        findings.append(
            "il canonico non porta `results.modules.revenue.series` come "
            "oggetto popolato: il caso negativo non e' costruibile")
        return findings
    key = sorted(series)[0]
    series[key] = perturb(series[key], Decimal("1000"))
    broken["canonical"].write_text(
        json.dumps(document, indent=2, ensure_ascii=True, sort_keys=True)
        + "\n", encoding="utf-8")
    chapter_bytes = broken["chapter"].read_bytes()
    refused = run_generator(ctx, RENDERER_REL, broken["canonical"],
                            broken["project"])
    if refused["exit_code"] == 0:
        findings.append(
            "il renderer ha prodotto un capitolo da un canonico INCOERENTE: "
            "la derivazione non e' vincolata al canonico")
    else:
        codes = {item.get("code")
                 for item in (refused["report"] or {}).get("errors", [])}
        if not codes & set(DERIVED_FAIL_CODES):
            findings.append(
                f"canonico incoerente: atteso uno fra {DERIVED_FAIL_CODES}, "
                f"ottenuti {sorted(codes)}")
    if broken["chapter"].read_bytes() != chapter_bytes:
        findings.append(
            "il renderer RIFIUTATO ha comunque SCRITTO il capitolo: un "
            "rifiuto non puo' lasciare un derivato parziale")
    return findings


# --------------------------------------------------------------------------
# FQ-C-12 — T-FIN-DERIVED-ROLLBACK
# --------------------------------------------------------------------------


def c12(ctx, base):
    """`T-FIN-DERIVED-ROLLBACK` — la pubblicazione e' COORDINATA: al ritorno
    dell'operazione NESSUNA GENERAZIONE MISTA sopravvive."""
    findings = []
    case = clone(ctx, base, "c12")
    report = GATE.publish(case["project"], case["canonical"], TX_ID)
    if report.get("staging_survivors"):
        findings.append(
            f"la pubblicazione RIUSCITA ha lasciato file di staging o di "
            f"backup: {report['staging_survivors']}")
    if not report.get("single_generation"):
        findings.append(
            f"la pubblicazione RIUSCITA lascia PIU' DI UNA generazione: "
            f"{report.get('generations')}")
    if not report["published"]:
        findings.append(
            f"la pubblicazione COORDINATA nominale e' fallita: "
            f"{report.get('failure')!r} {report.get('findings')}")
    elif not (report.get("check") or {}).get("passed"):
        findings.append(
            "la pubblicazione riuscita non supera il gate POST-pubblicazione: "
            f"{codes_of((report.get('check') or {}).get('findings'))}")
    if report.get("publish_order") != ["canonical", "chapter", "workbook"]:
        findings.append(
            f"l'ordine di pubblicazione non e' DETERMINISTICO: "
            f"{report.get('publish_order')}")

    for injection, description in (
            ("before-chapter", "fra la PRIMA e la SECONDA pubblicazione"),
            ("before-workbook", "fra la SECONDA e la TERZA pubblicazione")):
        rollback_case = clone(ctx, base, f"c12-{injection}")
        snapshot = {key: GATE.sha256_of(rollback_case[key])
                    for key in ("canonical", "chapter", "workbook")}
        report = GATE.publish(rollback_case["project"],
                              rollback_case["canonical"], TX_ID,
                              inject_failure=injection)
        if report["published"]:
            findings.append(
                f"fallimento iniettato {description}: la pubblicazione e' "
                "stata comunque dichiarata RIUSCITA")
        if not report["rolled_back"]:
            findings.append(
                f"fallimento iniettato {description}: nessun ROLLBACK e' stato "
                "eseguito")
        if not report.get("single_generation"):
            findings.append(
                f"fallimento iniettato {description}: l'insieme porta PIU' DI "
                f"UNA generazione dopo il ritorno: {report.get('generations')}")
        if not report.get("byte_identical_to_previous"):
            findings.append(
                f"fallimento iniettato {description}: gli artefatti NON sono "
                f"byte-identici ai precedenti: {report.get('sha256_after')} "
                f"contro {snapshot}")
        if report.get("staging_survivors"):
            findings.append(
                f"fallimento iniettato {description}: file di staging o di "
                f"backup SOPRAVVISSUTI: {report['staging_survivors']}")
        if not report.get("staging_removed"):
            findings.append(
                f"fallimento iniettato {description}: l'area di staging non e' "
                "stata rimossa")
        after = {key: GATE.sha256_of(rollback_case[key])
                 for key in ("canonical", "chapter", "workbook")}
        if after != snapshot:
            findings.append(
                f"fallimento iniettato {description}: lo stato sul disco "
                f"DIVERGE da quello precedente: {sorted(after.items())}")
    return findings


# --------------------------------------------------------------------------
# FQ-C-13 — T-FIN-PIPELINE-END-TO-END
# --------------------------------------------------------------------------


def c13(ctx, base):
    """`T-FIN-PIPELINE-END-TO-END` — la pipeline deterministica COMPLETA
    produce i QUATTRO output della pipeline su un progetto TEMPORANEO, e
    ciascuno e' valido nella propria classe: canonico schema-valido, capitolo
    COMPLETO e TRACCIABILE, workbook STRUTTURALMENTE valido."""
    findings = []
    case = clone(ctx, base, "c13")

    # ---- 1  canonico: JSON valido e schema-valido ------------------------
    try:
        json.loads(case["canonical"].read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        findings.append(f"il canonico non e' JSON valido: {exc}")
        return findings
    gate_one = run_output_validator(ctx, case["project"],
                                    case["canonical"].parent)
    if gate_one["exit_code"] != 0:
        errors = [item.get("code")
                  for item in (gate_one["report"] or {}).get("errors", [])]
        findings.append(
            f"il canonico NON supera il validator canonico di produzione "
            f"(exit {gate_one['exit_code']}): {errors}")

    # ---- 2  capitolo: sezioni, tabelle e TRACCIABILITA' ------------------
    parsed = GATE.parse_chapter(case["text"])
    chapter_tokens = ctx["tokens"].get("chapter") or {}
    declared_sections = [entry["title"]
                         for entry in chapter_tokens.get("sections") or []]
    declared_tables = [entry["title"]
                       for entry in chapter_tokens.get("tables") or []]
    present_sections = {entry["title"] for entry in parsed["sections"]}
    present_tables = {entry["title"] for entry in parsed["tables"]}
    if len(declared_sections) != 15 or len(declared_tables) != 12:
        findings.append(
            f"i token dichiarano {len(declared_sections)} sezioni e "
            f"{len(declared_tables)} tabelle: il capitolo ne esige QUINDICI e "
            "DODICI")
    for title in declared_sections:
        if title not in present_sections:
            findings.append(
                f"sezione obbligatoria ASSENTE dal capitolo: {title!r} "
                f"[{CODE_INCOMPLETE}]")
    for title in declared_tables:
        if title not in present_tables:
            findings.append(
                f"tabella obbligatoria ASSENTE dal capitolo: {title!r} "
                f"[{CODE_INCOMPLETE}]")
    untraced = []
    for entry in GATE.chapter_value_rows(parsed):
        for element in ("path", "scenario", "period", "unit", "checksum"):
            if not str(entry.get(element) or "").strip():
                untraced.append((entry["line"], element))
    if untraced:
        findings.append(
            f"valori economici del capitolo SENZA traccia canonica completa: "
            f"{untraced[:5]} (totale {len(untraced)})")

    # ---- 3  workbook: pacchetto OOXML STRUTTURALMENTE valido -------------
    package = case["package"]
    if not package.get("valid_zip"):
        findings.append(
            f"il workbook non si apre come pacchetto OOXML valido: "
            f"l'estensione {WORKBOOK_NAME!r} non basta [{CODE_INCOMPLETE}]")
    else:
        for part in REQUIRED_PARTS:
            if part not in package["parts"]:
                findings.append(
                    f"parte OOXML obbligatoria ASSENTE: {part!r} "
                    f"[{CODE_INCOMPLETE}]")
        declared_sheets = [entry["name"] for entry in
                           (ctx["tokens"].get("workbook") or {}).get("sheets")
                           or []]
        for name in declared_sheets:
            if name not in package["sheets"]:
                findings.append(
                    f"foglio obbligatorio ASSENTE dal workbook: {name!r} "
                    f"[{CODE_INCOMPLETE}]")

    # ---- 4  il gate di completamento e' SUPERATO -------------------------
    verdict = GATE.check(case["project"], case["canonical"], TX_ID)
    if not verdict["passed"]:
        findings.append(
            f"il gate di completamento NON e' superato sulla pipeline "
            f"nominale: {[item['message'] for item in verdict['findings']][:3]}")

    # ---- casi NEGATIVI: una sezione, una tabella e una parte OOXML -------
    # La COMPLETEZZA del capitolo NON e' misurata da `derived_consistency`, che
    # verifica la coerenza NUMERICA e di CHECKSUM: e' il rilevatore dichiarato
    # QUI a doverla misurare, ed e' quindi QUI che va dimostrato che rileva.
    if parsed["sections"] and declared_sections:
        title = declared_sections[-1]
        reduced = GATE.parse_chapter(
            CHAPTER.drop_section(case["text"], title))
        remaining = {entry["title"] for entry in reduced["sections"]}
        if title in remaining:
            findings.append(
                f"la sezione «{title}» non e' stata rimossa: il caso negativo "
                "non e' stato costruito")
        elif not [name for name in declared_sections if name not in remaining]:
            findings.append(
                f"AUTO-VERIFICA FALLITA: la rimozione della sezione «{title}» "
                "non e' rilevata — il rilevatore di completezza del capitolo "
                "e' VACUO e una sezione scomoda potrebbe essere omessa in "
                "silenzio")
    if parsed["tables"] and declared_tables:
        title = declared_tables[0]
        reduced = GATE.parse_chapter(CHAPTER.drop_table(case["text"], title))
        remaining = {entry["title"] for entry in reduced["tables"]}
        if title in remaining:
            findings.append(
                f"la tabella «{title}» non e' stata rimossa: il caso negativo "
                "non e' stato costruito")
        elif not [name for name in declared_tables if name not in remaining]:
            findings.append(
                f"AUTO-VERIFICA FALLITA: la rimozione della tabella «{title}» "
                "non e' rilevata dal rilevatore di completezza del capitolo")
    broken = clone(ctx, base, "c13-broken-ooxml")
    mutated_path = XLSX.drop_part(broken["workbook"], "xl/workbook.xml")
    shutil.copyfile(mutated_path, broken["workbook"])
    try:
        broken_package = GATE.read_package(broken["workbook"])
    except GATE.GateDefect:
        broken_package = None
    if broken_package is not None and broken_package.get("sheets"):
        findings.append(
            "un pacchetto OOXML privo di `xl/workbook.xml` e' comunque letto "
            "come workbook: la validita' strutturale non e' misurata")

    # ---- AUTO-VERIFICA del rilevatore di tracciabilita' ------------------
    probe = copy.deepcopy(parsed)
    if not probe["tables"] or not probe["tables"][0]["rows"]:
        findings.append(
            "il capitolo non porta alcuna riga di valore: l'AUTO-VERIFICA del "
            "rilevatore di tracciabilita' non e' costruibile")
    else:
        probe["tables"][0]["rows"][0]["unit"] = ""
        detected = [entry for entry in GATE.chapter_value_rows(probe)
                    if not str(entry.get("unit") or "").strip()]
        if not detected:
            findings.append(
                "AUTO-VERIFICA FALLITA: una riga di valore PRIVA di unita' non "
                "e' rilevata — il rilevatore di tracciabilita' e' VACUO")
    return findings


# --------------------------------------------------------------------------
# FQ-C-14 — T-FIN-DERIVED-FIDELITY
# --------------------------------------------------------------------------


REC_ID_RE = re.compile(r"REC-\d+")


def reconciliation_gaps(document, package):
    """RILEVATORE — ogni `REC-*` canonico compare nel foglio `Reconciliation`
    del workbook.

    L'id e' ESTRATTO dal contenuto della cella e non confrontato per uguaglianza
    di stringa: il foglio decora l'id con la propria etichetta
    (`REC-01 · residuo`), e un confronto per uguaglianza misurerebbe la
    decorazione invece dell'identita' della riconciliazione.
    """
    declared = sorted((document.get("financial_plan") or {}).get(
        "reconciliations") or {})
    shown = set()
    for columns in GATE.rows_of_sheet(package, "Reconciliation").values():
        for entry in columns.values():
            shown.update(REC_ID_RE.findall(str(entry.get("value") or "")))
    return sorted(set(declared) - shown)


def scenario_gaps(document, package):
    """RILEVATORE — ogni scenario canonico PRODOTTO compare nel foglio
    `Scenarios`. `coverage` e' il blocco di MISURA della copertura, non uno
    scenario, ed e' escluso alla fonte."""
    declared = sorted(
        name for name in (((document.get("financial_plan") or {}).get("results")
                           or {}).get("scenarios") or {})
        if name != "coverage")
    shown = set()
    for columns in GATE.rows_of_sheet(package, "Scenarios").values():
        for entry in columns.values():
            value = str(entry.get("value") or "").strip().lower()
            if value in declared:
                shown.add(value)
    return sorted(set(declared) - shown)


def c14(ctx, base):
    """`T-FIN-DERIVED-FIDELITY` — tracciabilita' dell'assumption register,
    semantica delle celle ARANCIONI, e fedelta' di SCENARIO, di
    RICONCILIAZIONE e di INVESTOR READINESS fra canonico e derivati."""
    findings = []
    case = clone(ctx, base, "c14")
    tokens = ctx["tokens"]

    nominal = GATE.xrec_05(case["document"], case["package"], tokens)
    if nominal:
        findings.append(
            f"la corrispondenza BIUNIVOCA cella <-> riga <-> DRV-* non e' "
            f"pulita: {[item['message'] for item in nominal][:3]}")
    governed = GATE.xrec_06(case["project"], case["document"])
    if governed:
        findings.append(
            f"gli attributi di input GOVERNATI non sono verificati per "
            f"impronta: {[item['message'] for item in governed][:3]}")
    gaps = reconciliation_gaps(case["document"], case["package"])
    if gaps:
        findings.append(
            f"riconciliazioni canoniche ASSENTI dal workbook: {gaps}")
    gaps = scenario_gaps(case["document"], case["package"])
    if gaps:
        findings.append(f"scenari canonici ASSENTI dal workbook: {gaps}")
    promotion = CHAPTER.promotion_findings(tokens, case["document"],
                                           case["text"], label="capitolo")
    if promotion:
        findings.append(
            f"il capitolo PROMUOVE uno stato che il canonico non dichiara: "
            f"{promotion[:3]}")

    # ---- caso negativo 1: una riga di Assumption Register RIMOSSA --------
    mutated = copy.deepcopy(case["package"])
    register_rows = GATE.rows_of_sheet(mutated, "Assumption Register")
    target_row = None
    for row_index in sorted(register_rows):
        value = str((register_rows[row_index].get("A") or {}).get("value") or "")
        if value.startswith("DRV-"):
            target_row = row_index
            break
    if target_row is None:
        findings.append(
            "l'Assumption Register non porta alcuna riga `DRV-*`: i casi "
            "negativi di tracciabilita' non sono costruibili")
    else:
        mutated["sheets"]["Assumption Register"].pop(f"A{target_row}", None)
        detected = GATE.xrec_05(case["document"], mutated, tokens)
        if not detected:
            findings.append(
                "la RIMOZIONE di una riga di Assumption Register non e' "
                "rilevata: la cardinalita' esatta contro il registro canonico "
                "e' VACUA")
        elif CODE_INCOMPLETE not in {item["code"] for item in detected}:
            findings.append(
                f"riga di Register rimossa: atteso {CODE_INCOMPLETE}, ottenuti "
                f"{codes_of(detected)}")

    # ---- caso negativo 2: una cella di OUTPUT colorata di ARANCIONE ------
    orange = sorted(GATE.assumption_argb(tokens))
    if not orange:
        findings.append(
            "i token di stile non dichiarano alcun ARGB di cella di "
            "assunzione: la semantica delle celle arancioni non e' misurabile")
    else:
        mutated = copy.deepcopy(case["package"])
        style_index = next(
            (index for index, argb in mutated["fills"].items()
             if argb in set(orange)), None)
        assumptions = mutated["sheets"].get("Assumptions") or {}
        named_refs = set()
        for reference in mutated["defined_names"].values():
            sheet, cell_ref = GATE.split_ref(reference)
            if sheet == "Assumptions":
                named_refs.add(cell_ref)
        victim = next((ref for ref in sorted(assumptions)
                       if ref not in named_refs), None)
        if style_index is None or victim is None:
            findings.append(
                "non e' costruibile una cella di OUTPUT arancione: lo stile "
                f"di assunzione {orange} o una cella non nominata mancano")
        else:
            assumptions[victim]["style"] = style_index
            detected = GATE.xrec_05(case["document"], mutated, tokens)
            if not any("NAMED RANGE" in item["message"] for item in detected):
                findings.append(
                    f"una cella NON di assunzione colorata con l'ARGB "
                    f"arancione ({victim}) non e' rilevata: la semantica delle "
                    "celle arancioni e' decorativa e non contrattuale")

    # ---- caso negativo 3: una riconciliazione RIMOSSA dal workbook -------
    mutated = copy.deepcopy(case["package"])
    declared_recs = sorted((case["document"].get("financial_plan") or {}).get(
        "reconciliations") or {})
    removed = declared_recs[0] if declared_recs else None
    if removed is not None:
        sheet = mutated["sheets"].get("Reconciliation") or {}
        # OGNI cella che nomina l'id e' rimossa: eliminarne una sola non
        # produrrebbe un varco se l'id compare piu' volte nel foglio.
        for ref in [key for key, entry in sheet.items()
                    if removed in REC_ID_RE.findall(
                        str(entry.get("value") or ""))]:
            sheet.pop(ref, None)
    if removed is None:
        findings.append(
            "il foglio Reconciliation non porta alcun `REC-*`: il caso "
            "negativo di fedelta' di riconciliazione non e' costruibile")
    elif removed not in reconciliation_gaps(case["document"], mutated):
        findings.append(
            f"AUTO-VERIFICA FALLITA: la rimozione di {removed} dal workbook "
            "non e' rilevata dal rilevatore di fedelta' di riconciliazione")

    # ---- caso negativo 4: uno scenario RIMOSSO dal workbook --------------
    mutated = copy.deepcopy(case["package"])
    declared = sorted(
        name for name in (((case["document"].get("financial_plan") or {})
                           .get("results") or {}).get("scenarios") or {})
        if name != "coverage")
    if not declared:
        findings.append(
            "il canonico non dichiara alcuno scenario prodotto: il caso "
            "negativo di fedelta' di scenario non e' costruibile")
    else:
        victim = declared[0]
        sheet = mutated["sheets"].get("Scenarios") or {}
        for ref in [key for key, entry in sheet.items()
                    if str(entry.get("value") or "").strip().lower() == victim]:
            sheet.pop(ref, None)
        if victim not in scenario_gaps(case["document"], mutated):
            findings.append(
                f"AUTO-VERIFICA FALLITA: la rimozione dello scenario "
                f"«{victim}» dal workbook non e' rilevata dal rilevatore di "
                "fedelta' di scenario")

    # ---- caso negativo 5: PROMOZIONE della prontezza nel capitolo --------
    sections = GATE.parse_chapter(case["text"])["sections"]
    if not sections:
        findings.append(
            "il capitolo non porta alcuna sezione: il caso negativo di "
            "promozione non e' costruibile")
    else:
        last = sections[-1]
        heading = f"{last['number']}. {last['title']}"
        injected = CHAPTER.inject_after_heading(
            case["text"], heading,
            "Il piano e' investor-ready e puo' essere portato in banca.")
        detected = CHAPTER.promotion_findings(tokens, case["document"],
                                              injected, label="iniettato")
        if not any("investor-ready" in item for item in detected):
            findings.append(
                "una PROMOZIONE della prontezza iniettata nel capitolo non e' "
                "rilevata: la fedelta' di investor readiness e' VACUA")
    return findings


# --------------------------------------------------------------------------
# FQ-C-15 — T-FIN-STDLIB-ONLY-RUNTIME
# --------------------------------------------------------------------------


def third_party_imports(source, label):
    """RILEVATORE STATICO AST — ogni import di un modulo di runtime risolve
    alla LIBRERIA STANDARD o a un modulo LOCALE del repository.

    L'analisi e' sull'AST e non sul testo: un `import` dentro una funzione, in
    un `try` o dentro una condizione e' visitato come ogni altro.
    """
    hits = []
    try:
        tree = ast.parse(source, filename=label)
    except SyntaxError as exc:
        return [f"{label}: sorgente non analizzabile ({exc})"]
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:          # import relativo: mai una terza parte
                continue
            names = [node.module or ""]
        for name in names:
            top = str(name).split(".")[0]
            if not top or top in stdlib or top in LOCAL_MODULES:
                continue
            hits.append(
                f"{label}:{getattr(node, 'lineno', '?')}: import di terze "
                f"parti {top!r} — il runtime deve essere di SOLA libreria "
                "standard")
    return hits


def c15(ctx, base):
    """`T-FIN-STDLIB-ONLY-RUNTIME` — il runtime OOXML e' di SOLA LIBRERIA
    STANDARD: nessuna dipendenza di terze parti."""
    findings = []
    for rel in STDLIB_ONLY_MODULES:
        path = ctx["root"] / rel
        if not path.is_file():
            findings.append(f"modulo di runtime ASSENTE: {rel}")
            continue
        findings.extend(third_party_imports(
            path.read_text(encoding="utf-8"), rel))

    # il workbook e' prodotto e riletto SENZA alcuna terza parte: e' uno ZIP
    # di XML, e il lettore del gate ne e' la sede UNICA.
    case = clone(ctx, base, "c15")
    if not zipfile.is_zipfile(case["workbook"]):
        findings.append(
            "il workbook non e' uno ZIP: il runtime OOXML di sola libreria "
            "standard non l'ha prodotto")

    # ---- AUTO-VERIFICA del rilevatore statico ---------------------------
    injected = "import openpyxl\n\n\ndef build():\n    return openpyxl\n"
    if not third_party_imports(injected, "<sonda>"):
        findings.append(
            "AUTO-VERIFICA FALLITA: il rilevatore AST non rileva un "
            "`import openpyxl` iniettato — il rilevatore e' VACUO")
    nested = ("def build():\n    try:\n        from openpyxl import Workbook\n"
              "    except ImportError:\n        Workbook = None\n"
              "    return Workbook\n")
    if not third_party_imports(nested, "<sonda-annidata>"):
        findings.append(
            "AUTO-VERIFICA FALLITA: il rilevatore AST non rileva un import di "
            "terze parti ANNIDATO in una funzione e in un `try` — la scansione "
            "e' limitata al livello di modulo")
    if third_party_imports("import json\nimport zipfile\n", "<sonda-stdlib>"):
        findings.append(
            "AUTO-VERIFICA FALLITA: il rilevatore AST segnala import di SOLA "
            "libreria standard — produce falsi positivi")
    return findings


# --------------------------------------------------------------------------
# FQ-C-16 — T-FIN-REAL-PROJECT-WRITE-GUARD
# --------------------------------------------------------------------------


def c16(ctx, base):
    """`T-FIN-REAL-PROJECT-WRITE-GUARD` — i generatori respingono, prima di
    qualunque I/O, un progetto che si trova DENTRO la directory della skill,
    che resta BYTE-IDENTICA; un progetto in qualunque altra posizione (anche
    sotto una cartella `projects/` accanto a `.claude/`) NON e' respinto: la
    guardia non dipende da dove la skill e' installata.

    La skill e' un MIRROR TEMPORANEO del pacchetto, cosi' il contratto non
    scrive mai nel checkout in cui gira la suite.
    """
    findings = []
    mirror = Path(base) / "c16-mirror"
    skill = mirror / SKILL_REL
    shutil.copytree(ctx["root"] / SKILL_REL, skill,
                    ignore=shutil.ignore_patterns("__pycache__"))
    inside = skill / "project-inside-skill"
    shutil.copytree(ctx["root"] / "examples" / "fictional-startup", inside)
    mirror_ctx = dict(ctx, root=mirror)
    before = kit.snapshot_tree(skill)

    case = clone(ctx, base, "c16")
    for rel in (RENDERER_REL, EXPORTER_REL):
        outcome = run_generator(mirror_ctx, rel, case["canonical"], inside)
        if outcome["exit_code"] == 0:
            findings.append(
                f"{rel} ha ACCETTATO un progetto dentro la skill: la guardia "
                f"{CODE_REAL_PROJECT} e' VACUA")
            continue
        # I DUE generatori dichiarano il rifiuto in DUE forme diverse — il
        # renderer in `errors[]`, l'exporter in `refusal` — ed entrambe sono
        # lette.
        report = outcome["report"] or {}
        codes = {item.get("code") for item in report.get("errors") or []}
        refusal = report.get("refusal")
        if isinstance(refusal, dict):
            codes.add(refusal.get("code"))
        if CODE_REAL_PROJECT not in codes:
            findings.append(
                f"{rel} su progetto dentro la skill: atteso "
                f"{CODE_REAL_PROJECT}, ottenuti "
                f"{sorted(code for code in codes if code)}")
        written = report.get("written")
        if written:
            findings.append(
                f"{rel} ha SCRITTO dentro la skill nonostante il rifiuto: "
                f"{written}")
    after = kit.snapshot_tree(skill)
    if after != before:
        changed = sorted(set(after) ^ set(before)) or sorted(
            rel for rel in before if before[rel] != after.get(rel))
        findings.append(
            f"la directory della skill NON e' byte-identica: {changed}")

    # Nessuna falsa positiva legata al layout: un progetto sotto `projects/`
    # accanto a `.claude/` e' un progetto utente come un altro.
    outside = clone(ctx, mirror / "projects", "c16-user-project")
    outcome = run_generator(mirror_ctx, RENDERER_REL, outside["canonical"],
                            outside["project"])
    if outcome["exit_code"] != 0:
        findings.append(
            f"{RENDERER_REL} ha RESPINTO un progetto utente sotto projects/ "
            f"(exit {outcome['exit_code']}): la guardia dipende dal layout "
            f"— {(outcome['stdout'] + outcome['stderr'])[:200]!r}")

    # il progetto di fixture e' TEMPORANEO e vive fuori dal repository
    try:
        case["project"].relative_to(ctx["root"])
    except ValueError:
        pass
    else:
        findings.append(
            f"il progetto di fixture vive DENTRO il repository: "
            f"{case['project']}")
    return findings


# --------------------------------------------------------------------------
# FQ-C-17 — T-FIN-WAVE123-CONTRACT-INVENTORY
# --------------------------------------------------------------------------


def c17(ctx, _base):
    """`T-FIN-WAVE123-CONTRACT-INVENTORY` — l'inventario dei contratti
    delle sette suite finanziarie e' INVARIATO e DISGIUNTO da quello di
    questo modulo.

    Non duplica l'esecuzione delle sette suite: il runner le esegue tutte, e
    rieseguirle qui raddoppierebbe il costo senza aggiungere prova. Cio' che
    questo contratto misura e' l'INVARIANTE DI INVENTARIO — che nessun modulo
    finanziario abbia perso, rinominato o fuso un contratto, il che
    potrebbe passare inosservato in un conteggio aggregato.
    """
    findings = []
    seen = {}
    for name, expected in ACCEPTED_INVENTORY:
        path = ctx["root"] / TESTKIT_REL / f"{name}.py"
        if not path.is_file():
            findings.append(f"suite finanziaria assente: {name}")
            continue
        proc = subprocess.run(
            [sys.executable, str(path), "--list"], capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            cwd=str(ctx["root"]),
            env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        if proc.returncode != 0:
            findings.append(
                f"{name} --list e' fallito (exit {proc.returncode}): "
                f"{proc.stderr.strip()[:200]!r}")
            continue
        ids = [line.strip() for line in proc.stdout.splitlines()
               if line.strip()]
        if len(ids) != expected:
            findings.append(
                f"{name} dichiara {len(ids)} contratti invece dei {expected} "
                "attesi dall'inventario")
        if len(set(ids)) != len(ids):
            findings.append(f"{name} dichiara id DUPLICATI: {sorted(ids)}")
        for contract_id in ids:
            if contract_id in seen:
                findings.append(
                    f"id di contratto CONDIVISO fra {seen[contract_id]} e "
                    f"{name}: {contract_id} — un id, un contratto")
            seen[contract_id] = name
    for entry in CONTRACTS:
        if entry["id"] in seen:
            findings.append(
                f"test_fin_tx RIUSA un id gia' assegnato a {seen[entry['id']]}: "
                f"{entry['id']}")
        if entry["name"] in seen:
            findings.append(
                f"test_fin_tx RIUSA un nome di contratto gia' assegnato: "
                f"{entry['name']}")
    if len({entry["id"] for entry in CONTRACTS}) != len(CONTRACTS):
        findings.append("test_fin_tx dichiara id DUPLICATI al proprio interno")
    if len({entry["name"] for entry in CONTRACTS}) != len(CONTRACTS):
        findings.append("test_fin_tx dichiara nomi DUPLICATI al proprio interno")
    return findings


# --------------------------------------------------------------------------
# FQ-C-18 — T-FIN-IMPACT
# --------------------------------------------------------------------------


def c18_stage10_project(base, name):
    """Progetto TM dentro lo Stage 10, col canonico REALE della baseline
    (percorso di produzione) copiato alla sede PERSISTITA che
    `validate_financial_output.py` risolve in fase impact — lo stesso idioma
    gia' usato da `c01` per lo Stage 10 dentro la validation view."""
    project = tm_project(base, name, stage=STAGE10)
    stage_dir = project / STAGE10
    stage_dir.mkdir(exist_ok=True)
    return project, stage_dir


def c18(ctx, base):
    """`T-FIN-IMPACT` — verifica il fronte STRUTTURALE di confine ed
    egress, cioe' la ragione dichiarata

        «validate_financial_output e' in egress_required, SOLO
          validate_financial_output fra i QUATTRO validator finanziari, e il
          boundary e' a Stage 13»

    e ne prova la CONSEGUENZA per esecuzione: il canonico Stage 10 PERSISTITO e' realmente
    invocato e ISPEZIONATO in fase impact, senza alcuna `TypeError`, con lo
    stesso esito verde gia' provato in fase egress, e i casi negativi
    (canonico assente/invalido/corrotto) falliscono con exit code definiti.
    """
    findings = []
    config = ctx["config"]

    # ---- fronte STRUTTURALE: confine e matrice ----------------------------
    boundary = config.get("release_boundary")
    if boundary != EXPECTED_BOUNDARY:
        findings.append(
            f"release_boundary e' {boundary!r} invece di "
            f"{EXPECTED_BOUNDARY!r}: il confine deve essere l'ultimo stage, "
            "lo Stage 13")
    egress = list(config.get("egress_required") or [])
    if "validate_financial_output" not in egress:
        findings.append(
            "validate_financial_output non e' in egress_required: il "
            "canonico dello Stage 10 non e' validato in egress")
    intruders = [name for name in FINANCIAL_VALIDATORS
                if name != "validate_financial_output" and name in egress]
    if intruders:
        findings.append(
            f"validator di PIPELINE in egress_required: {intruders}; solo "
            "validate_financial_output vi entra")
    if len(egress) != EXPECTED_EGRESS_COUNT:
        findings.append(
            f"egress_required porta {len(egress)} voci invece delle TREDICI "
            f"attese: {egress}")
    if egress[-1:] != [EXPECTED_EGRESS_APPENDED]:
        findings.append(
            f"l'ultima voce di egress_required deve essere "
            f"{EXPECTED_EGRESS_APPENDED!r}: {egress[-1:]}")
    for name in FINANCIAL_VALIDATORS:
        spec = (config.get("validators") or {}).get(name) or {}
        if not spec:
            findings.append(
                f"{name} non e' dichiarato nella matrice di enforcement")
            continue
        if [int(item) for item in spec.get("stages") or []] != [10]:
            findings.append(
                f"{name} non dichiara piu' `stages: [10]`: "
                f"{spec.get('stages')}")

    # ---- fronte STRUTTURALE: la finestra impact include gli Stage 10-13 --
    window = TM.impact_window(config, EXPECTED_BOUNDARY)
    for stage in (STAGE10, STAGE11, STAGE12, STAGE13):
        if stage not in window:
            findings.append(
                f"la finestra impact al confine corrente NON contiene "
                f"{stage}: {window}; gli Stage 10-13 restano DENTRO la "
                "finestra dopo il movimento del confine a Stage 13")

    # ---- fronte COMPORTAMENTALE: canonico VALIDO -> invocato e GREEN -----
    valid_project, valid_stage_dir = c18_stage10_project(base, "c18-valid")
    canonical_bytes = baseline(ctx)["canonical"].read_bytes()
    (valid_stage_dir / CANONICAL_NAME).write_bytes(canonical_bytes)
    results, invoked = TM.run_impact_validators(config, valid_project,
                                                "shared", [STAGE10])
    output_invocations = [entry for entry in invoked
                          if entry["validator"] == "validate_financial_output"]
    if not output_invocations:
        findings.append(
            "validate_financial_output NON e' stato invocato in fase impact "
            "allo Stage 10")
    output_results = [entry for entry in results
                      if entry["validator"] == "validate_financial_output"]
    for entry in output_results:
        report = entry.get("report") or {}
        if entry["exit_code"] != 0:
            findings.append(
                f"validate_financial_output su canonico Stage 10 VALIDO in "
                f"fase impact: atteso exit 0, ottenuto {entry['exit_code']}; "
                f"report={report}")
        if not report.get("checks"):
            findings.append(
                "il canonico Stage 10 valido non produce alcun `checks[]` in "
                "fase impact: il canonico persistito non risulta realmente "
                "ISPEZIONATO")
        if "TypeError" in json.dumps(report):
            findings.append(
                "TypeError presente nel report di impact su canonico Stage "
                "10 valido")

    # ---- fronte COMPORTAMENTALE: canonico ASSENTE -> exit 2, no TypeError -
    missing_project, _ = c18_stage10_project(base, "c18-missing")
    exit_code, out, err = kit.run_validator_cli(
        ctx["root"], "validate_financial_output", project=missing_project,
        stage=STAGE10, phase="impact")
    if exit_code != 2:
        findings.append(
            f"canonico Stage 10 ASSENTE in fase impact: atteso exit 2, "
            f"ottenuto {exit_code} (out {out.strip()[:200]!r} "
            f"err {err.strip()[:200]!r})")
    if "TypeError" in err:
        findings.append(
            f"canonico Stage 10 ASSENTE in fase impact: TypeError in "
            f"stderr: {err.strip()[:300]!r}")

    # ---- fronte COMPORTAMENTALE: canonico CORROTTO -> exit 3, no TypeError
    corrupt_project, corrupt_stage_dir = c18_stage10_project(base,
                                                             "c18-corrupt")
    (corrupt_stage_dir / CANONICAL_NAME).write_text("{not json",
                                                     encoding="utf-8")
    exit_code, out, err = kit.run_validator_cli(
        ctx["root"], "validate_financial_output", project=corrupt_project,
        stage=STAGE10, phase="impact")
    if exit_code != 3:
        findings.append(
            f"canonico Stage 10 CORROTTO in fase impact: atteso exit 3, "
            f"ottenuto {exit_code} (out {out.strip()[:200]!r} "
            f"err {err.strip()[:200]!r})")
    if "TypeError" in err:
        findings.append(
            f"canonico Stage 10 CORROTTO in fase impact: TypeError in "
            f"stderr: {err.strip()[:300]!r}")

    # ---- fronte COMPORTAMENTALE: canonico INVALIDO -> exit 1, no TypeError
    invalid_project, invalid_stage_dir = c18_stage10_project(base,
                                                             "c18-invalid")
    document = json.loads(canonical_bytes.decode("utf-8"))
    document["schema_version"] = "0.0.0-invalid"
    (invalid_stage_dir / CANONICAL_NAME).write_text(
        json.dumps(document, indent=2, ensure_ascii=True, sort_keys=True) +
        "\n", encoding="utf-8")
    exit_code, out, err = kit.run_validator_cli(
        ctx["root"], "validate_financial_output", project=invalid_project,
        stage=STAGE10, phase="impact")
    if exit_code != 1:
        findings.append(
            f"canonico Stage 10 INVALIDO in fase impact: atteso exit 1, "
            f"ottenuto {exit_code} (out {out.strip()[:200]!r} "
            f"err {err.strip()[:200]!r})")
    if "TypeError" in err:
        findings.append(
            f"canonico Stage 10 INVALIDO in fase impact: TypeError in "
            f"stderr: {err.strip()[:300]!r}")

    # ---- fronte COMPORTAMENTALE: egress resta INVOCATO e GREEN -----------
    verdict = run_output_validator(ctx, valid_project, valid_stage_dir)
    if verdict["exit_code"] != 0:
        findings.append(
            f"validate_financial_output in fase egress: atteso exit 0, "
            f"ottenuto {verdict['exit_code']}: {verdict['stdout'][:300]!r}")
    return findings


# --------------------------------------------------------------------------
# Registro dei contratti
# --------------------------------------------------------------------------


CONTRACTS = [
    {"id": "FQ-C-01", "name": "T-FIN-TX-BINDING", "fn": c01,
     "fixture": "F-12 + progetto TM dentro il confine",
     "expected_code": "candidate_changed · report_hash_mismatch",
     "mutation": "MUT-4-01"},
    {"id": "FQ-C-02", "name": "T-FIN-NO-MUTATION-FAIL", "fn": c02,
     "fixture": "candidate con riferimento NON dichiarato + F-12 degenere",
     "expected_code": "validation_failed · canonico byte-identico",
     "mutation": "MUT-4-02"},
    {"id": "FQ-C-03", "name": "T-FIN-RESUME", "fn": c03,
     "fixture": "progetto all'inizio dello Stage 10",
     "expected_code": "stage_already_completed", "mutation": "MUT-4-03"},
    {"id": "FQ-C-04", "name": "T-FIN-CRASH-RECOVERY", "fn": c04,
     "fixture": "crash after_writes:2 e before_commit",
     "expected_code": "rollback da snapshot COMPLETO", "mutation": "MUT-4-04"},
    {"id": "FQ-C-05", "name": "T-FIN-IDEMPOTENCY", "fn": c05,
     "fixture": "update-assumption con operation_id ripetuto",
     "expected_code": "already_applied · operation_id_conflict",
     "mutation": "MUT-4-05"},
    {"id": "FQ-C-06", "name": "T-FIN-WRITE-SET", "fn": c06,
     "fixture": "journal update_assumption ALTERATO + candidate con extra",
     "expected_code": "journal_corrupted", "mutation": "MUT-4-06"},
    {"id": "FQ-C-07", "name": "T-FIN-NO-STAGE-BEYOND-TERMINAL",
     "fn": c07,
     "fixture": "progetto a 13_document-generation, piano completato + "
                "pipeline F-12",
     "expected_code": "exit 2 oltre l'ultimo stage", "mutation": "MUT-4-07"},
    {"id": "FQ-C-08", "name": "T-FIN-DERIVED-CHECKSUM", "fn": c08,
     "fixture": "F-13(d) derivata in-modulo", "expected_code": CODE_STALE,
     "mutation": "MUT-4-08"},
    {"id": "FQ-C-09", "name": "T-FIN-DERIVED-CROSS-CONSISTENCY", "fn": c09,
     "fixture": "F-13(c) derivata in-modulo, NOVE sonde",
     "expected_code": f"{CODE_MISMATCH} · {CODE_INCOMPLETE}",
     "mutation": "MUT-4-09"},
    {"id": "FQ-C-10", "name": "T-FIN-DERIVED-MISSING", "fn": c10,
     "fixture": "F-13(a)/(b) + variante CRITICA con canonico valido",
     "expected_code": CODE_INCOMPLETE, "mutation": "MUT-4-10"},
    {"id": "FQ-C-11", "name": "T-FIN-DERIVED-REGENERATION", "fn": c11,
     "fixture": "F-12 rigenerata dal solo canonico",
     "expected_code": CODE_MISMATCH, "mutation": "MUT-4-11"},
    {"id": "FQ-C-12", "name": "T-FIN-DERIVED-ROLLBACK", "fn": c12,
     "fixture": "F-12 con fallimento INIETTATO",
     "expected_code": "rollback coordinato, UNA sola generazione",
     "mutation": "MUT-4-12"},
    {"id": "FQ-C-13", "name": "T-FIN-PIPELINE-END-TO-END", "fn": c13,
     "fixture": "F-12, pipeline COMPLETA", "expected_code": CODE_INCOMPLETE,
     "mutation": "MUT-4-13"},
    {"id": "FQ-C-14", "name": "T-FIN-DERIVED-FIDELITY", "fn": c14,
     "fixture": "F-12, CINQUE sonde di fedelta'",
     "expected_code": CODE_INCOMPLETE, "mutation": "MUT-4-14"},
    {"id": "FQ-C-15", "name": "T-FIN-STDLIB-ONLY-RUNTIME", "fn": c15,
     "fixture": "AST dei QUATTRO moduli di runtime",
     "expected_code": "import di terze parti", "mutation": "MUT-4-15"},
    {"id": "FQ-C-16", "name": "T-FIN-REAL-PROJECT-WRITE-GUARD", "fn": c16,
     "fixture": "mirror temporaneo della skill",
     "expected_code": CODE_REAL_PROJECT, "mutation": "MUT-4-16"},
    {"id": "FQ-C-17", "name": "T-FIN-WAVE123-CONTRACT-INVENTORY",
     "fn": c17, "fixture": "le SETTE suite finanziarie",
     "expected_code": "inventario 16/30/8/11/22/5/17 invariato",
     "mutation": "MUT-4-17"},
    {"id": "FQ-C-18", "name": "T-FIN-IMPACT", "fn": c18,
     "fixture": "enforcement-config.json + canonico Stage 10 valido/"
                "assente/invalido/corrotto",
     "expected_code": IMPACT_GREEN_REASON, "mutation": "MUT-4-18"},
]

CONTRACT_IDS = tuple(entry["id"] for entry in CONTRACTS)


# --------------------------------------------------------------------------
# Esecuzione
# --------------------------------------------------------------------------


def run_one(ctx, contract):
    with tempfile.TemporaryDirectory(prefix="fq_tx_") as base:
        try:
            findings = contract["fn"](ctx, Path(base))
        except HarnessDefect:
            raise
        except (AssertionError, AttributeError, IndexError, KeyError,
                OSError, StopIteration, TypeError, ValueError) as exc:
            findings = [f"errore di valutazione del contratto: {exc!r}"]
    return {"contract": contract, "red": bool(findings), "findings": findings}


def format_line(result):
    contract = result["contract"]
    if contract.get("authorized_red"):
        state = "RED*" if not result["red"] else "RED"
    else:
        state = "RED" if result["red"] else "GREEN"
    return ("{state:<5} {cid:<12} {name:<34} fixture={fixture} | EXPECTED: "
            "{exp} | mutazione={mut} | reason={reason}".format(
                state=state, cid=contract["id"], name=contract["name"],
                fixture=contract["fixture"], exp=contract["expected_code"],
                mut=contract["mutation"],
                reason="; ".join(result["findings"]) or "-"))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(
        prog="test_fin_tx.py", add_help=True,
        description="Contratti della QA deterministica end-to-end dello "
                    "Stage 10 (transazione, workflow e derivati).")
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

    global XLSX, CHAPTER, GATE, TM
    try:
        XLSX = load_xlsx_harness(root)
        CHAPTER = XLSX.CHAPTER
        GATE = XLSX.GATE
        TM = kit.load_module(root, kit.TRANSACTION_REL, "transaction_manager")
        ctx = build_context(root)
        ORDER_CACHE["order"] = sorted(
            ctx["config"]["stage_order"],
            key=lambda stage: int(ctx["config"]["stage_order"][stage]))
        selected = [entry for entry in CONTRACTS
                    if not args.contract or entry["id"] == args.contract]
        results = [run_one(ctx, entry) for entry in selected]
    except HarnessDefect as exc:
        drop_baseline()
        print(f"HARNESS DEFECT: {exc}", file=sys.stderr)
        return EXIT_STATE
    except HarnessUsageError as exc:
        drop_baseline()
        print(f"USAGE ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE
    finally:
        drop_baseline()

    for result in results:
        print(format_line(result))
    red = [result for result in results if result["red"]]
    authorized = [result for result in results
                  if result["contract"].get("authorized_red")
                  and not result["red"]]
    print("SUMMARY: {total} contratti, {red} RED, {green} GREEN, "
          "{auth} RED ATTESO (gate {gate}: {gs}; transaction manager "
          "{tm}: presente)".format(
              total=len(results), red=len(red),
              green=len(results) - len(red) - len(authorized),
              auth=len(authorized), gate=GATE_REL,
              gs="presente" if (root / GATE_REL).is_file() else "ASSENTE",
              tm=f"{kit.TRANSACTION_REL}/transaction_manager.py"))
    if authorized:
        print("RED ATTESO: {names} — RAGIONE DICHIARATA: «{reasons}»."
              .format(
                  names=", ".join(result["contract"]["name"]
                                  for result in authorized),
                  reasons="; ".join(result["contract"]["expected_code"]
                                    for result in authorized)))
    if red:
        return EXIT_RED
    print("PASS: T-FIN-TX {n} contratti della QA deterministica end-to-end "
          "dello Stage 10".format(n=len(results)))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
