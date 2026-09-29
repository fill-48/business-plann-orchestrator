#!/usr/bin/env python3
"""Harness dei contratti del MOTORE FINANZIARIO dello Stage 10.

Ogni contratto invoca `validators/validate_financial_engine.py` su un
progetto temporaneo con un ingresso DICHIARATO riga per riga e verifica il
payload intermedio prodotto: moduli, metriche, riconciliazioni, proiezione di
governance NON canonica e codici di errore attesi.

CONTRATTI OSPITATI QUI  --  TRENTA
----------------------------------
    FE-C-01 ... FE-C-12      motore, calendario e moduli core
    FE-C-20                  nessun letterale economico nel motore
    FE-C-22 ... FE-C-31      tolleranza, demo, purezza, governance
    FS-C-08 ... FS-C-10      break-even, KPI, fabbisogno
    FS-C-15, FS-C-17, FS-C-18  tolleranza, confine con lo Stage 11, checksum
    FS-C-20                  proiezione del registro delle assunzioni

Le SETTE riconciliazioni dei moduli core -- `FE-C-13` ... `FE-C-19` -- e le
QUATTRO di break-even, scenari e categorie -- `FS-C-11` ... `FS-C-14` --
vivono in `tests/integration/test_fin_recon.py`. Gli OTTO contratti di
scenario -- `FS-C-01` ... `FS-C-07` e `FS-C-19` -- vivono in
`tests/integration/test_fin_scenarios.py`.

SEMANTICA DEGLI EXIT CODE
-------------------------
    0   tutti i contratti soddisfatti
    1   almeno un contratto RED
    2   errore d'uso
    3   stato del repository inutilizzabile (difetto di harness)

Un fallimento di PREPARAZIONE non e' evidenza RED: e' exit 3.

CHE COSA QUESTO HARNESS NON CONTIENE
------------------------------------
Nessuna aritmetica finanziaria di produzione: ogni valore atteso e' ricalcolato
QUI in `Decimal` a partire dai record DICHIARATI dal contratto, mai copiato
dall'output del motore. I letterali economici di questo modulo sono DATI DI
CASO DI TEST: il divieto di letterali economici vale sul SORGENTE DEL MOTORE
ed e' verificato da `FE-C-20`.
"""
import argparse
import ast
import copy
import decimal
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

# --------------------------------------------------------------------------
# Costanti strutturali
# --------------------------------------------------------------------------

SKILL_REL = ".claude/skills/business-plan-orchestrator"
VALIDATORS_REL = f"{SKILL_REL}/validators"
TRANSACTION_REL = f"{SKILL_REL}/transaction"
PROFILES_REL = f"{SKILL_REL}/profiles"
SCHEMAS_REL = f"{SKILL_REL}/schemas"
CONFIG_REL = f"{SKILL_REL}/config/enforcement-config.json"
TESTKIT_REL = "tests/integration"

ENTRY_POINT_REL = f"{VALIDATORS_REL}/validate_financial_engine.py"
ENTRY_POINT_NAME = "validate_financial_engine"
MISSING_CAPABILITY_REASON = f"MISSING_CAPABILITY: {ENTRY_POINT_NAME}"

DEMO_PROJECT_REL = "examples/fictional-startup"
PROJECT_CONFIG_REL = "shared/project-config.json"

STAGE10 = "10_financial-plan"
PROFILE_ID = "subscription_saas"
CURRENCY = "EUR"

EXIT_OK = 0
EXIT_RED = 1
EXIT_USAGE = 2
EXIT_STATE = 3

#: Precisione di riferimento del ricalcolo indipendente dell'harness. E' la
#: STESSA che il motore dichiara: un confronto a precisioni diverse misurerebbe
#: la precisione, non il calcolo.
HARNESS_PRECISION = 28

#: I QUATTRO codici di errore dei moduli core emessi dal motore. Nessuno e'
#: inventato qui.
AMB_W2_01 = "opening_balance_as_source"
AMB_W2_02 = "rate_conversion_not_compounded"
AMB_W2_03 = "engine_determinism_violated"
AMB_W2_04 = "cash_metrics_collapsed"

#: I DUE codici di errore degli scenari emessi dal motore. Nessuno e'
#: inventato qui.
AMB_W2_05 = "sensitivity_multi_driver"
AMB_W2_06 = "scenario_series_identical"

#: I due codici di scenario: NON compaiono nei contratti dei moduli core e la
#: loro assenza vi resta verificata.
M4_ONLY_CODES = (AMB_W2_05, AMB_W2_06)

#: Codice emesso dal motore quando `funding_gap` compare fra le SOURCES: il
#: fabbisogno e' un residuo, mai una fonte. Non e' coniato qui.
CODE_GAP_AS_SOURCE = "funding_gap_as_source"

#: Le SETTE chiavi che lo Stage 11 possiede e che lo Stage 10 non produce
#: (`FS-C-17`). L'elenco e' CHIUSO.
STAGE11_FORBIDDEN_KEYS = ("funding_ask", "instrument", "valuation",
                          "round_size", "ownership", "dilution", "terms")

#: Chiavi composte soltanto dal costruttore canonico: il payload del motore
#: NON deve portarle, e qui se ne verifica l'assenza, non la correttezza.
M5A_ONLY_KEYS = ("use_of_proceeds_candidates", "milestone_coverage")

#: Le OTTO voci del set minimo di KPI. Lo schema del piano finanziario le
#: dichiara TUTTE `required` sotto `results.modules.kpi.indicators` ed e'
#: `additionalProperties: false`: non ne esiste una nona e non ne manca una.
KPI_IDS = ("gross_margin_pct", "monthly_burn", "runway", "cac", "ltv",
           "ltv_cac_ratio", "break_even_period", "milestone_coverage")

#: I TRE scenari. L'enumerazione e' CHIUSA dallo schema del piano finanziario.
SCENARIO_IDS = ("base", "downside", "upside")

#: Codici di errore gia' esistenti che il motore riusa.
CODE_CONFIG_MISSING = "financial_config_missing"
CODE_CONFIG_INVALID = "financial_config_invalid"
CODE_ROLE_UNBOUND = "driver_role_unbound"
CODE_UNRESOLVED_REQUIRED = "unresolved_required_input"
CODE_PLACEHOLDER_OPTIONAL = "placeholder_optional_input"
CODE_SOURCE_STALE = "driver_source_stale"
CODE_SOURCE_CONFLICT = "source_conflict_unresolved"
CODE_INFORMATIONAL = "driver_informational_consumed"
CODE_FINANCING_IN_PNL = "financing_in_pnl"
CODE_PERIOD_UNDECLARED = "driver_period_undeclared"
CODE_SOURCE_PATH = "driver_source_path_unverifiable"
#: Codice gia' emesso dal validator di binding: una politica di conversione
#: non ammessa per la propria natura di misura e' lo stesso difetto, rilevato
#: al confine del motore. Non e' coniato qui.
CODE_CONVERSION_POLICY = "driver_conversion_policy_undeclared"

#: `check_id` strutturali emessi dal motore (non sono codici di errore: la
#: regola vieta di coniare CODICI, non `check_id`, come il validator di
#: binding gia' fa con `driver_status_mapping`).
CHECK_DERIVED = "driver_derived_not_assumable"
CHECK_PRESENTATION = "engine_presentation_dependency"
CHECK_ECONOMIC_LITERAL = "engine_economic_literal"
CHECK_TOLERANCE = "tolerance_representation"

#: Le UNDICI voci dei moduli core del motore. `break_even`, `kpi` e
#: `funding_gap` sono i tre moduli aggiuntivi elencati sotto.
M3_MODULES = (
    "calendar", "revenue", "cogs", "gross_margin", "headcount", "payroll",
    "opex", "pnl", "cash_flow", "runway", "cash_buffer",
)

#: I tre moduli aggiuntivi (break-even, KPI, fabbisogno) e le loro quattro
#: riconciliazioni.
M4_MODULES = ("break_even", "kpi", "funding_gap")
M4_REC_IDS = ("REC-06", "REC-11", "REC-13", "REC-15")

#: Le QUATTORDICI voci di modulo che il motore produce: le undici core piu'
#: le tre aggiuntive. Non ne esiste una quindicesima -- `capex`,
#: `depreciation`, `working_capital`, `tax`, `financing` e `balance_sheet` non
#: sono calcolati dal motore e `milestone_coverage` non e' prodotto dal
#: motore.
M4_ALL_MODULES = M3_MODULES + M4_MODULES
M3_REC_IDS = ("REC-01", "REC-02", "REC-03", "REC-04", "REC-05",
              "REC-12", "REC-14")

#: Enumerazione CHIUSA di `driver_status`, dal piu' basso al piu' alto.
STATUS_ORDER = ("unresolved", "placeholder", "inferred", "confirmed")


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
    for probe in (SKILL_REL, TESTKIT_REL, DEMO_PROJECT_REL):
        if not (root / probe).is_dir():
            raise HarnessUsageError(
                f"--root non sembra la radice del repository: {probe} assente "
                f"sotto {root}")
    return root


def load_module(root, rel, name):
    path = root / rel
    if not path.is_file():
        raise HarnessDefect(f"modulo assente: {rel}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - difetto di harness
        raise HarnessDefect(f"modulo non importabile: {rel}: {exc}")
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
    testkit = load_module(root, f"{TESTKIT_REL}/bpo_testkit.py", "bpo_testkit")
    transaction = testkit.load_module(root, TRANSACTION_REL,
                                      "transaction_manager")
    fingerprint = getattr(transaction, "record_fingerprint", None)
    if not callable(fingerprint):
        raise HarnessDefect(
            "transaction_manager senza record_fingerprint: il CAS esistente "
            "non e' riusabile")
    profile = read_json(root, f"{PROFILES_REL}/{PROFILE_ID}.json")
    schema = read_json(root, f"{SCHEMAS_REL}/financial-plan.schema.json")
    enforcement = read_json(root, CONFIG_REL)
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - ambiente
        raise HarnessDefect(f"jsonschema non importabile: {exc}")
    return {
        "root": root,
        "testkit": testkit,
        "fingerprint": fingerprint,
        "profile": profile,
        "schema": schema,
        "enforcement": enforcement,
        "jsonschema": jsonschema,
        "entry_point": root / ENTRY_POINT_REL,
    }


# --------------------------------------------------------------------------
# Costruttori DICHIARATIVI dell'ingresso del motore
# --------------------------------------------------------------------------
#
# L'ingresso del motore e' il payload di binding gia' risolto da
# `validate_financial_binding` piu' `financial_config` validato. I record
# canonici sono DICHIARATI
# dal contratto e sovrapposti al canonico del progetto temporaneo, esattamente
# come `validate_financial_binding.build_overlay` gia' consente e come
# `test_fin_binding.py` gia' fa. Nessun valore e' cercato o dedotto.


def record(testkit, idx, value, unit, **over):
    entry = testkit.base_assumption(
        idx, id=f"ASS-{idx:03d}", value=value, unit=unit,
        display_value=f"{value} {unit}", confidence="medium")
    entry["evidence_classification"] = "founder_assumption"
    entry["validation_status"] = "unvalidated"
    entry["rationale"] = f"assunzione dichiarata dal contratto per {unit}"
    entry.update(over)
    return entry


def row(ctx, driver_id, role, source_ref, unit, measure_kind, frequency,
        conversion_policy, timing_rule, records, start_period=None,
        end_period=None, status="inferred", source_priority=10,
        cardinality="one", scenario_polarity=None, input_kind="operational",
        **over):
    """Una riga di binding COMPLETA, DICHIARATA dal contratto."""
    profile = ctx["profile"]
    source = records.get(source_ref)
    if source is None:
        raise HarnessDefect(
            f"{driver_id}: record dichiarato assente per {source_ref}")
    entry = {
        "driver_id": driver_id,
        "semantic_name": role,
        "role": role,
        "driver_class": (profile.get("role_driver_class") or {}).get(role),
        "producer_stage": "09_roadmap-and-milestones",
        "source_ref": source_ref,
        "source_path": f"milestone_plan.financial_plan_inputs.{role}_ref",
        "source_record_hash": ctx["fingerprint"](source),
        "cardinality": cardinality,
        "unit": unit,
        "currency": CURRENCY if unit.upper().startswith(CURRENCY) else None,
        "measure_kind": measure_kind,
        "frequency": frequency,
        "conversion_policy": conversion_policy,
        "timing_rule": timing_rule,
        "start_period": start_period,
        "end_period": end_period,
        "scenario_polarity": scenario_polarity or (
            "cost_like" if role in ("churn_rate", "variable_cost", "headcount",
                                    "payroll_unit_cost", "opex")
            else "revenue_like"),
        "status": status,
        "confidence": source.get("confidence", "medium"),
        "source_priority": source_priority,
        "binding_method": "fpi_declared",
        "double_count_risk": "none",
        "input_kind": input_kind,
        "rationale": source.get("rationale", "dichiarata dal contratto"),
        "upstream_refs": [],
    }
    entry.update(over)
    return entry


def financial_config(ctx, **over):
    config = ctx["testkit"].financial_config(
        financial_profile=PROFILE_ID, horizon_periods=12,
        anchor_date="2026-01-01")
    config.update(over)
    return config


def base_records(ctx, price="100", volume="10", churn="0.16",
                 variable_cost="40", headcount="2", payroll_unit="3000",
                 opex="12000", opening_cash="50000", **over):
    """I record canonici del caso NOMINALE, DICHIARATI riga per riga.

    I valori sono DATI DI CASO DI TEST, scelti perche' producono identita'
    esatte in `Decimal` e residui controllabili; nessuno di essi vive nel
    sorgente del motore (`FE-C-20`).
    """
    testkit = ctx["testkit"]
    declared = [
        record(testkit, 1, float(price), "EUR/count", category="pricing"),
        record(testkit, 2, float(volume), "count", category="market"),
        record(testkit, 3, float(churn), "ratio", category="retention"),
        record(testkit, 4, float(variable_cost), "EUR/count",
               category="unit_economics"),
        record(testkit, 5, float(headcount), "FTE", category="team"),
        record(testkit, 6, float(payroll_unit), "EUR/FTE", category="team"),
        record(testkit, 7, float(opex), "EUR", category="operations"),
        record(testkit, 8, float(opening_cash), "EUR", category="finance"),
    ]
    by_id = {entry["id"]: entry for entry in declared}
    for ref, patch in (over or {}).items():
        if ref in by_id:
            by_id[ref].update(patch)
    return by_id


def with_triplet(records, ref, low, base_value, high):
    """Dichiara sul record la TERNA di scenario.

    I tre valori sono gli ESTREMI dichiarati, non gia' assegnati a uno
    scenario: e' la POLARITA' di scenario a decidere quale estremo diventa
    Downside e quale Upside, ed e' precisamente per questo che il profilo
    `subscription_saas` annota che «applicare Downside = High a churn_rate e
    a retention_rate sarebbe un errore di lettura».
    """
    entry = records[ref]
    entry["base_case"] = float(base_value)
    entry["downside_case"] = float(low)
    entry["upside_case"] = float(high)
    return entry


def triplet_records(ctx, **over):
    """I record del caso nominale, ciascuno con la TERNA DIFFERENZIATA.

    La copertura di scenario e' PIENA (sette ruoli richiesti su sette), che e'
    la forma della fixture `F-1`.
    """
    records = base_records(ctx, **over)
    spread = {
        "ASS-001": ("90", "100", "110"),      # unit_price       revenue_like
        "ASS-002": ("8", "10", "12"),         # customer_volume  revenue_like
        "ASS-003": ("0.10", "0.16", "0.24"),  # churn_rate       cost_like
        "ASS-004": ("36", "40", "44"),        # variable_cost    cost_like
        "ASS-005": ("2", "2", "2"),           # headcount        cost_like
        "ASS-006": ("2700", "3000", "3300"),  # payroll_unit     cost_like
        "ASS-007": ("10800", "12000", "13200"),  # opex          cost_like
    }
    for ref, (low, mid, high) in spread.items():
        with_triplet(records, ref, low, mid, high)
    return records


def base_rows(ctx, records, horizon=12):
    """Le SETTE righe dei ruoli richiesti dal profilo `subscription_saas`."""
    last = horizon - 1
    return [
        row(ctx, "DRV-001", "unit_price", "ASS-001", "EUR/count", "per_unit",
            "per_unit", "preserve_rate", "NOT_APPLICABLE", records),
        row(ctx, "DRV-002", "customer_volume", "ASS-002", "count", "stock",
            "monthly", "carry_level", "constant", records,
            start_period=0, end_period=last,
            revenue_category="operating_revenue"),
        row(ctx, "DRV-003", "churn_rate", "ASS-003", "ratio", "rate",
            "annual", "compound", "NOT_APPLICABLE", records),
        row(ctx, "DRV-004", "variable_cost", "ASS-004", "EUR/count",
            "per_unit", "per_unit", "preserve_rate", "NOT_APPLICABLE",
            records, cost_category="operating_cost"),
        row(ctx, "DRV-005", "headcount", "ASS-005", "FTE", "stock",
            "monthly", "carry_level", "constant", records,
            start_period=0, end_period=last,
            cost_category="operating_cost"),
        row(ctx, "DRV-006", "payroll_unit_cost", "ASS-006", "EUR/FTE",
            "per_unit", "per_unit", "preserve_rate", "NOT_APPLICABLE",
            records, cost_category="operating_cost"),
        row(ctx, "DRV-007", "opex", "ASS-007", "EUR", "flow", "annual",
            "allocate", "uniform", records, start_period=0, end_period=last,
            cost_category="operating_cost"),
    ]


def engine_input(ctx, rows, records, config=None, opening_cash_ref="ASS-008",
                 declare_config=True, **over):
    payload = {
        "profile_id": PROFILE_ID,
        "stage": STAGE10,
        "phase": "egress",
        "driver_bindings": rows,
        "canonical_records": list(records.values()),
        "consumed_by_engine": [entry["driver_id"] for entry in rows],
        "opening_cash_ref": opening_cash_ref,
    }
    if declare_config:
        payload["financial_config"] = config or financial_config(ctx)
    payload.update(over)
    return payload


# --------------------------------------------------------------------------
# Invocazione del punto d'ingresso dichiarato
# --------------------------------------------------------------------------


def make_project(ctx, base, fixture_id="F-1", name=None,
                 include_financial_config=True):
    project, fixture = ctx["testkit"].make_stage10_fixture_project(
        base, fixture_id, name=name,
        include_financial_config=include_financial_config)
    return project, fixture


def run_engine(ctx, project, payload, entry_point=None, env_extra=None,
               output_name="engine-output.json"):
    """Invoca il punto d'ingresso DICHIARATO e restituisce report e payload.

    Tutto vive sotto una directory temporanea deterministica, rimossa al
    termine. Nessun path canonico e' passato al motore e nessuna cartella
    `10_financial-plan/` e' creata da questo harness.
    """
    entry = Path(entry_point) if entry_point else ctx["entry_point"]
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    if not entry.is_file():
        return {
            "available": False,
            "reason": MISSING_CAPABILITY_REASON,
            "exit_code": None,
            "report": None,
            "result": None,
            "observed": set(),
            "payload_digest": digest,
            "stdout": "",
            "stderr": f"{entry} non esiste",
        }
    with tempfile.TemporaryDirectory(prefix="fin_core_run_") as work:
        candidate = Path(work) / "candidate"
        candidate.mkdir(parents=True)
        source = candidate / "engine-input.json"
        source.write_text(blob, encoding="utf-8")
        target = Path(work) / output_name
        command = [sys.executable, str(entry),
                   "--project", str(project),
                   "--stage", payload.get("stage", STAGE10),
                   "--phase", payload.get("phase", "egress"),
                   "--candidate", str(candidate),
                   "--engine-input", str(source),
                   "--engine-output", str(target)]
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        if env_extra:
            env.update(env_extra)
        proc = subprocess.run(command, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              cwd=str(ctx["root"]), env=env)
        result = None
        if target.is_file():
            try:
                result = json.loads(target.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise HarnessDefect(
                    f"payload del motore non e' JSON: {exc}")
    report = None
    if proc.stdout.strip().startswith("{"):
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            report = None
    observed = set()
    if report:
        observed |= {e.get("code") for e in report.get("errors") or []}
        observed |= {c.get("check_id") for c in report.get("checks") or []
                     if c.get("status") == "FAIL"}
    return {
        "available": True,
        "reason": "",
        "exit_code": proc.returncode,
        "report": report,
        "result": result,
        "observed": {code for code in observed if code},
        "payload_digest": digest,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "command": " ".join(command),
    }


# --------------------------------------------------------------------------
# Utilita' di lettura del payload intermedio NON canonico
# --------------------------------------------------------------------------


def plan_of(run):
    result = run.get("result")
    if not isinstance(result, dict):
        return None
    return result.get("financial_payload")


def projection_of(run):
    result = run.get("result")
    if not isinstance(result, dict):
        return None
    return result.get("governance_projection")


def modules_of(run):
    plan = plan_of(run)
    if not isinstance(plan, dict):
        return {}
    return ((plan.get("results") or {}).get("modules")) or {}


def dec(value):
    """Un valore atteso e ASSENTE dal payload e' un RED del contratto, non un
    difetto di harness: il motore non ha emesso cio' che dichiarava."""
    if value is None:
        raise ValueError("valore atteso ASSENTE dal payload del motore")
    return Decimal(str(value))


def series_of(module, index):
    series = (module or {}).get("series") or {}
    return dec(series.get(str(index)))


#: I moduli che lo schema del piano finanziario descrive con una forma PROPRIA
#: invece che con `$defs/module_result`. Entrambi restano
#: `additionalProperties: false`.
MODULES_WITH_OWN_SHAPE = ("break_even", "kpi", "milestone_coverage")

_MODULES_POINTER = ("#/properties/financial_plan/properties/results/"
                    "properties/modules/properties")


def module_schema_pointer(module_id):
    """Il puntatore di schema con cui validare il modulo."""
    if module_id in MODULES_WITH_OWN_SHAPE:
        return f"{_MODULES_POINTER}/{module_id}"
    return "#/$defs/module_result"


def metric_of(module, name):
    metrics = (module or {}).get("metrics") or {}
    if name not in metrics:
        return None
    return metrics[name]


def errors_with(run, code, ref=None):
    report = run.get("report") or {}
    out = []
    for entry in report.get("errors") or []:
        if entry.get("code") != code:
            continue
        if ref is not None and entry.get("ref") != ref:
            continue
        out.append(entry)
    return out


def checks_with(run, check_id, status=None):
    report = run.get("report") or {}
    out = []
    for entry in report.get("checks") or []:
        if entry.get("check_id") != check_id:
            continue
        if status is not None and entry.get("status") != status:
            continue
        out.append(entry)
    return out


def validate_ref(ctx, instance, pointer, label, findings):
    """Valida una sezione del payload per `$ref`.

    Lo schema del piano finanziario NON e' modificato e nessun secondo schema
    e' creato: si valida la SOLA sezione prodotta dal motore.
    """
    schema = ctx["schema"]
    node = schema
    for token in pointer.strip("#/").split("/"):
        node = node[token]
    resolved = dict(node)
    resolved["$defs"] = schema["$defs"]
    validator = ctx["jsonschema"].Draft202012Validator(resolved)
    for error in sorted(validator.iter_errors(instance),
                        key=lambda err: list(map(str, err.absolute_path))):
        path = "/".join(map(str, error.absolute_path)) or "(radice)"
        findings.append(f"{label}: {path}: {error.message}")


# --------------------------------------------------------------------------
# Ricalcolo INDIPENDENTE dell'harness  --  mai copiato dal motore
# --------------------------------------------------------------------------


def period_rate(annual, fraction):
    with decimal.localcontext() as local:
        local.prec = HARNESS_PRECISION
        return Decimal(1) - (Decimal(1) - annual) ** fraction


def expected_survival(annual_rate, index, fractions):
    with decimal.localcontext() as local:
        local.prec = HARNESS_PRECISION
        survival = Decimal(1)
        for step in range(index + 1):
            survival *= (Decimal(1) - period_rate(annual_rate, fractions[step]))
        return survival


def month_fractions(horizon):
    """Il caso nominale usa `anchor_date` al primo giorno: nessun parziale."""
    return [Decimal(1) / Decimal(12) for _ in range(horizon)]


def expected_runway(ending, horizon, limit):
    """Ricalcolo INDIPENDENTE di UNA misura di runway dalla PROPRIA soglia.

    Restituisce `(misura, periodo_di_prima_violazione)`. La MISURA e' sempre un
    indice di periodo -- l'ORIZZONTE quando la soglia non e' mai attraversata --
    mentre il periodo di prima violazione NON ESISTE in quel caso. E' questa
    differenza di DOMINIO, non l'uguaglianza dei valori, a distinguere le due
    grandezze: due misure calcolate da soglie diverse possono coincidere su un
    piano perfettamente sano, e trattarlo come collasso respingerebbe il piano
    che lo Stage 10 esiste per produrre.
    """
    for index in range(horizon):
        if ending[index] < limit:
            return index, index
    return horizon, None


def expected_funding_gap(ending, limit):
    """Ricalcolo INDIPENDENTE di UN riassunto di fabbisogno."""
    worst = min(ending) if ending else Decimal(0)
    return max(Decimal(0), limit - worst)


# --------------------------------------------------------------------------
# Contratti
# --------------------------------------------------------------------------
#
# Ogni contratto restituisce una lista di RAGIONI. Lista vuota => GREEN.
# Ogni contratto esegue ALMENO un caso POSITIVO e ALMENO un caso NEGATIVO,
# e ogni caso negativo e' ATTRIBUITO.


def _nominal(ctx, base, records=None, rows=None, config=None, name=None,
             fixture_id="F-1", include_financial_config=True, **over):
    declared = records if records is not None else base_records(ctx)
    project, _ = make_project(ctx, base, fixture_id=fixture_id, name=name,
                              include_financial_config=include_financial_config)
    built = rows if rows is not None else base_rows(ctx, declared)
    payload = engine_input(ctx, built, declared, config=config, **over)
    return project, declared, built, payload


def c01(ctx):
    """`FE-C-01` `T-FIN-CALENDAR` -- calendario da `financial_config`."""
    findings = []
    with tempfile.TemporaryDirectory(prefix="fin_core_c01_") as base:
        base = Path(base)
        # POSITIVO / RED-1 -- l'orizzonte SEGUE la configurazione dichiarata.
        for horizon in (12, 7):
            project, records, rows, payload = _nominal(
                ctx, base, name=f"c01-h{horizon}",
                config=financial_config(ctx, horizon_periods=horizon),
                rows=None)
            payload["driver_bindings"] = base_rows(ctx, records,
                                                   horizon=horizon)
            run = run_engine(ctx, project, payload)
            if not run["available"]:
                return [run["reason"]], [run]
            calendar = (plan_of(run) or {}).get("results", {}).get("calendar")
            if not calendar:
                findings.append(
                    f"RED-1: nessun calendario prodotto per horizon={horizon}")
                continue
            if calendar.get("horizon_periods") != horizon:
                findings.append(
                    f"RED-1: horizon_periods={calendar.get('horizon_periods')!r} "
                    f"invece di {horizon}: l'orizzonte non segue "
                    "financial_config (costante di codice?)")
            if len(calendar.get("periods") or []) != horizon:
                findings.append(
                    f"RED-1: {len(calendar.get('periods') or [])} periodi "
                    f"invece di {horizon}")
            validate_ref(ctx, calendar,
                         "#/properties/financial_plan/properties/results/"
                         "properties/calendar", "calendar", findings)
            if horizon == 12:
                first = run
        # RED-2 -- `anchor_date` DICHIARATA, mai da now().
        anchors = {}
        for anchor in ("2026-01-01", "2027-03-01"):
            project, records, rows, payload = _nominal(
                ctx, base, name=f"c01-a{anchor.replace('-', '')}",
                config=financial_config(ctx, anchor_date=anchor))
            run = run_engine(ctx, project, payload)
            calendar = (plan_of(run) or {}).get("results", {}).get("calendar")
            anchors[anchor] = (calendar or {}).get("anchor_date")
            if (calendar or {}).get("anchor_date") != anchor:
                findings.append(
                    f"RED-2: anchor_date={anchors[anchor]!r} invece di "
                    f"{anchor!r}: derivata dall'orologio?")
            periods = (calendar or {}).get("periods") or []
            if periods and periods[0].get("start_date") != anchor:
                findings.append(
                    f"RED-2: periods[0].start_date={periods[0].get('start_date')!r} "
                    f"non coincide con anchor_date {anchor!r}")
        # RED-3 -- primo periodo PARZIALE dichiarato con `day_fraction`.
        project, records, rows, payload = _nominal(
            ctx, base, name="c01-partial",
            config=financial_config(ctx, anchor_date="2026-01-15"))
        partial_run = run_engine(ctx, project, payload)
        calendar = (plan_of(partial_run) or {}).get("results", {}).get("calendar")
        periods = (calendar or {}).get("periods") or []
        if not periods:
            findings.append("RED-3: nessun periodo prodotto sull'ancora 15/01")
        else:
            if periods[0].get("partial") is not True:
                findings.append(
                    "RED-3: periods[0].partial != True su anchor_date "
                    "2026-01-15: primo periodo reso pieno in silenzio")
            fraction = periods[0].get("day_fraction")
            if fraction is None:
                findings.append(
                    "RED-3: periods[0].day_fraction assente: la quota del "
                    "periodo parziale non e' dichiarata")
            else:
                expected = Decimal(17) / Decimal(31)
                if abs(dec(fraction) - expected) > Decimal("1e-9"):
                    findings.append(
                        f"RED-3: day_fraction={fraction!r} invece di 17/31")
            if len(periods) > 1 and periods[1].get("partial") is not False:
                findings.append(
                    "RED-3: il secondo periodo e' dichiarato parziale")
        # RED-3 esclusione di falso positivo: il caso vale ANCHE con
        # `financial_config` valido -- ed e' proprio questo il caso.
        if not findings and (plan_of(partial_run) or {}).get("validation", {}) \
                .get("result") == "FAIL":
            findings.append(
                "RED-3: il calendario parziale ha prodotto FAIL: il contratto "
                "deve valere con financial_config VALIDO")
        # RED-4 -- `financial_config` ASSENTE => financial_config_missing.
        project, records, rows, payload = _nominal(
            ctx, base, name="c01-noconfig", include_financial_config=False,
            declare_config=False)
        missing = run_engine(ctx, project, payload)
        attributed = [e for e in errors_with(missing, CODE_CONFIG_MISSING)
                      if PROJECT_CONFIG_REL in (e.get("message") or "")]
        if not attributed:
            findings.append(
                f"RED-4: {CODE_CONFIG_MISSING} non attribuito al PROGETTO "
                f"({PROJECT_CONFIG_REL} non nominato nel messaggio); "
                f"osservati={sorted(missing['observed'])}")
        if CODE_CONFIG_INVALID in missing["observed"]:
            findings.append(
                f"RED-4: attribuzione VIETATA: {CODE_CONFIG_INVALID} non "
                "soddisfa il contratto di financial_config ASSENTE")
        if (plan_of(missing) or {}).get("results", {}).get("calendar"):
            findings.append(
                "RED-4: calendario prodotto benche' financial_config sia "
                "assente: il gate non precede il calcolo")
    return findings, [first, partial_run, missing]


def c02(ctx):
    """`FE-C-02` `T-FIN-REVENUE` -- ricavi = pattern x driver."""
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_core_c02_") as base:
        base = Path(base)
        project, records, rows, payload = _nominal(ctx, base, name="c02")
        run = run_engine(ctx, project, payload)
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        revenue = modules_of(run).get("revenue")
        if not revenue:
            return ["modulo revenue assente dal payload"], runs
        validate_ref(ctx, revenue, "#/$defs/module_result", "revenue", findings)
        price = dec(records["ASS-001"]["value"])
        volume = dec(records["ASS-002"]["value"])
        churn = dec(records["ASS-003"]["value"])
        fractions = month_fractions(12)
        for index in range(12):
            survival = expected_survival(churn, index, fractions)
            expected = volume * survival * price
            observed = series_of(revenue, index)
            if abs(observed - expected) > Decimal("1e-6"):
                findings.append(
                    f"periodo {index}: revenue={observed} invece di "
                    f"{expected} (volume x survival x prezzo); DRV-001, "
                    "DRV-002, DRV-003")
                break
        # Il pattern e' RICORRENTE: la base decade periodo dopo periodo.
        if series_of(revenue, 11) >= series_of(revenue, 0):
            findings.append(
                "il ricavo non decade lungo l'orizzonte: il pattern "
                "subscription_recurring non consuma il churn (DRV-003)")
        # NEGATIVO -- con churn NULLO la serie e' PIATTA e pari a volume x
        # prezzo: e' il caso che distingue «pattern applicato» da «pattern
        # ignorato», ed e' il caso negativo del contratto.
        flat = base_records(ctx, churn="0")
        project2, _ = make_project(ctx, base, name="c02-flat")
        flat_rows = base_rows(ctx, flat)
        flat_run = run_engine(ctx, project2, engine_input(ctx, flat_rows, flat))
        runs.append(flat_run)
        flat_revenue = modules_of(flat_run).get("revenue") or {}
        if not flat_revenue:
            findings.append(
                "caso negativo: nessun modulo revenue sul caso a churn nullo")
        else:
            expected_flat = volume * price
            for index in (0, 11):
                observed = series_of(flat_revenue, index)
                if observed != expected_flat:
                    findings.append(
                        f"caso negativo: periodo {index}: revenue={observed} "
                        f"invece di {expected_flat} con churn NULLO; DRV-001, "
                        "DRV-002")
                    break
            if series_of(flat_revenue, 11) == series_of(revenue, 11):
                findings.append(
                    "caso negativo: cambiare il solo DRV-003 (churn) non "
                    "cambia il ricavo: il pattern non lo consuma e il "
                    "contratto non discrimina")
        # Esclusione di falso positivo: il contratto fallisce anche con
        # `REC-01` disattivata -- qui misurato NON leggendo `REC-01`.
        recon = ((plan_of(run) or {}).get("reconciliations") or {})
        if "REC-01" not in recon:
            findings.append(
                "REC-01 assente dal payload: la riconciliazione dev'essere "
                "riportata SEMPRE")
    return findings, runs


def c03(ctx):
    """`FE-C-03` `T-FIN-COGS` -- ogni costo variabile legato e' consumato."""
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_core_c03_") as base:
        base = Path(base)
        # POSITIVO -- DUE costi variabili legati, ENTRAMBI consumati.
        records = base_records(ctx)
        records["ASS-009"] = record(ctx["testkit"], 9, 5.0, "EUR/count",
                                    category="unit_economics")
        rows = base_rows(ctx, records)
        rows.append(row(ctx, "DRV-009", "variable_cost", "ASS-009",
                        "EUR/count", "per_unit", "per_unit", "preserve_rate",
                        "NOT_APPLICABLE", records, cardinality="many",
                        cost_category="operating_cost"))
        for entry in rows:
            if entry["role"] == "variable_cost":
                entry["cardinality"] = "many"
        project, _ = make_project(ctx, base, name="c03")
        run = run_engine(ctx, project, engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        cogs = modules_of(run).get("cogs")
        if not cogs:
            return ["modulo cogs assente dal payload"], runs
        validate_ref(ctx, cogs, "#/$defs/module_result", "cogs", findings)
        consumed = set(cogs.get("input_driver_refs") or [])
        for driver in ("DRV-002", "DRV-004", "DRV-009"):
            if driver not in consumed:
                findings.append(
                    f"DRV nominato: {driver} non compare fra gli "
                    f"input_driver_refs di cogs: un costo variabile legato "
                    f"e' escluso dal totale; consumati={sorted(consumed)}")
        unit_total = dec(records["ASS-004"]["value"]) + \
            dec(records["ASS-009"]["value"])
        volume = dec(records["ASS-002"]["value"])
        churn = dec(records["ASS-003"]["value"])
        fractions = month_fractions(12)
        expected = volume * expected_survival(churn, 0, fractions) * unit_total
        observed = series_of(cogs, 0)
        if abs(observed - expected) > Decimal("1e-6"):
            findings.append(
                f"periodo 0: cogs={observed} invece di {expected}: il "
                "dettaglio non coincide col totale")
        detail = sum((dec(line["series"]["0"]) for line in cogs.get("lines") or []
                      if "0" in (line.get("series") or {})), Decimal(0))
        if abs(detail - observed) > Decimal("1e-6"):
            findings.append(
                f"periodo 0: somma delle righe {detail} != totale {observed}")
        # NEGATIVO -- il secondo costo variabile NON e' legato: il totale
        # perde il proprio contributo e il DRV escluso e' NOMINATO.
        project2, _ = make_project(ctx, base, name="c03-missing")
        partial = [entry for entry in rows if entry["driver_id"] != "DRV-009"]
        negative = run_engine(ctx, project2,
                              engine_input(ctx, partial, records))
        runs.append(negative)
        neg_cogs = modules_of(negative).get("cogs") or {}
        if series_of(neg_cogs, 0) >= observed:
            findings.append(
                "caso negativo: escludere DRV-009 non abbassa il totale COGS: "
                "il modulo non consuma tutti i variable_cost")
        # Attribuzione VIETATA: `cogs_coverage_incomplete` e' un codice
        # AMBIENT del validator di binding.
        if "cogs_coverage_incomplete" in run["observed"]:
            findings.append(
                "attribuzione VIETATA: cogs_coverage_incomplete e' un codice "
                "del validator di binding e non soddisfa questo contratto")
    return findings, runs


def c04(ctx):
    """`FE-C-04` `T-FIN-HEADCOUNT` -- FTE sulla finestra DICHIARATA."""
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_core_c04_") as base:
        base = Path(base)
        # POSITIVO / RED-2 -- serie di LIVELLO sulla finestra DICHIARATA.
        records = base_records(ctx)
        rows = base_rows(ctx, records)
        for entry in rows:
            if entry["role"] == "headcount":
                entry["start_period"] = 6
                entry["end_period"] = 9
        project, _ = make_project(ctx, base, name="c04")
        run = run_engine(ctx, project, engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        headcount = modules_of(run).get("headcount")
        if not headcount:
            return ["modulo headcount assente dal payload"], runs
        validate_ref(ctx, headcount, "#/$defs/module_result", "headcount",
                     findings)
        level = dec(records["ASS-005"]["value"])
        for index in range(12):
            observed = series_of(headcount, index)
            expected = level if 6 <= index <= 9 else Decimal(0)
            if observed != expected:
                findings.append(
                    f"RED-2: periodo {index}: FTE={observed} invece di "
                    f"{expected}: la serie non e' allineata alla finestra "
                    "DICHIARATA [6, 9]")
                break
        # RED-3 -- nessun parsing di etichette: l'etichetta upstream "Y1H2"
        # e' presente sul record e NON deve muovere la finestra.
        labelled = copy.deepcopy(records)
        labelled["ASS-005"]["period"] = "Y1H2"
        labelled_rows = copy.deepcopy(rows)
        for entry in labelled_rows:
            if entry["driver_id"] == "DRV-005":
                entry["source_record_hash"] = ctx["fingerprint"](
                    labelled["ASS-005"])
        project2, _ = make_project(ctx, base, name="c04-label")
        run_label = run_engine(ctx, project2,
                               engine_input(ctx, labelled_rows, labelled))
        runs.append(run_label)
        label_module = modules_of(run_label).get("headcount") or {}
        for index in range(12):
            if series_of(label_module, index) != series_of(headcount, index):
                findings.append(
                    f"RED-3: la serie cambia al periodo {index} per la sola "
                    "presenza dell'etichetta 'Y1H2': il timing e' dedotto dal "
                    "nome")
                break
        # RED-1 -- binding headcount SENZA finestra => driver_period_undeclared
        undeclared = copy.deepcopy(rows)
        for entry in undeclared:
            if entry["role"] == "headcount":
                entry["start_period"] = None
                entry["end_period"] = None
        project3, _ = make_project(ctx, base, name="c04-undeclared")
        run_undeclared = run_engine(
            ctx, project3, engine_input(ctx, undeclared, records))
        runs.append(run_undeclared)
        if not errors_with(run_undeclared, CODE_PERIOD_UNDECLARED, "DRV-005"):
            findings.append(
                f"RED-1: {CODE_PERIOD_UNDECLARED} non attribuito a DRV-005; "
                f"osservati={sorted(run_undeclared['observed'])}")
        if "driver_frequency_undeclared" in run_undeclared["observed"]:
            findings.append(
                "RED-1: attribuzione VIETATA: driver_frequency_undeclared non "
                "soddisfa il contratto della finestra non dichiarata")
    return findings, runs


def c05(ctx):
    """`FE-C-05` `T-FIN-PAYROLL` -- payroll = Sigma (FTE x costo), `REC-03`,
    `REC-14`."""
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_core_c05_") as base:
        base = Path(base)
        records = base_records(ctx)
        rows = base_rows(ctx, records)
        project, _ = make_project(ctx, base, name="c05")
        run = run_engine(ctx, project, engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        payroll = modules_of(run).get("payroll")
        if not payroll:
            return ["modulo payroll assente dal payload"], runs
        validate_ref(ctx, payroll, "#/$defs/module_result", "payroll", findings)
        fte = dec(records["ASS-005"]["value"])
        unit = dec(records["ASS-006"]["value"])
        for index in range(12):
            observed = series_of(payroll, index)
            expected = fte * unit
            if observed != expected:
                findings.append(
                    f"periodo {index}: payroll={observed} invece di "
                    f"{expected} = FTE x costo unitario")
                break
        recon = (plan_of(run) or {}).get("reconciliations") or {}
        for rec_id in ("REC-03", "REC-14"):
            entry = recon.get(rec_id) or {}
            if entry.get("status") != "PASS":
                findings.append(
                    f"{rec_id} non PASS sul caso nominale: "
                    f"{entry.get('status')!r}")
        # Esclusione di falso positivo: `REC-03` verde con serie FTE priva di
        # senso. La serie e' RIPARTITA 1/12 nei record dichiarati: il totale
        # annuo resta identico e SOLO `REC-14` lo rileva.
        spread = base_records(ctx, headcount=str(float(fte) / 12),
                              payroll_unit=str(float(unit) * 12))
        project2, _ = make_project(ctx, base, name="c05-spread")
        spread_rows = base_rows(ctx, spread)
        for entry in spread_rows:
            if entry["role"] == "headcount":
                entry["timing_rule"] = "from_schedule"
                entry["timing_schedule"] = {"0": float(fte) / 12}
        spread_run = run_engine(ctx, project2,
                                engine_input(ctx, spread_rows, spread))
        runs.append(spread_run)
        spread_recon = (plan_of(spread_run) or {}).get("reconciliations") or {}
        rec03 = (spread_recon.get("REC-03") or {}).get("status")
        rec14 = (spread_recon.get("REC-14") or {}).get("status")
        if rec03 != "PASS":
            findings.append(
                "esclusione di falso positivo: REC-03 doveva restare PASS "
                f"sulla serie ripartita 1/12, osservato {rec03!r}")
        if rec14 == "PASS":
            findings.append(
                "esclusione di falso positivo: REC-14 e' PASS su una serie "
                "FTE che non copre la finestra dichiarata: il contratto NON "
                "e' soddisfatto da REC-03 PASS con REC-14 FAIL")
        residual = (spread_recon.get("REC-14") or {}).get("residual_breakdown")
        if rec14 != "PASS" and not residual:
            findings.append(
                "REC-14 FAIL senza residual_breakdown per ruolo: "
                "l'attribuzione manca")
    return findings, runs


def c06(ctx):
    """`FE-C-06` `T-FIN-OPEX` -- opex categorizzati (fixture F-7)."""
    findings = []
    runs = []
    fixture = ctx["testkit"].stage10_fixture("F-7")
    categories = [line["category"] for line in fixture["distinct"]]
    with tempfile.TemporaryDirectory(prefix="fin_core_c06_") as base:
        base = Path(base)
        records = base_records(ctx)
        rows = base_rows(ctx, records)
        for entry in rows:
            if entry["role"] == "opex":
                entry["cardinality"] = "many"
                entry["cost_category"] = categories[0]
        for offset, category in enumerate(categories[1:], start=1):
            ref = f"ASS-{10 + offset:03d}"
            records[ref] = record(ctx["testkit"], 10 + offset, 1200.0, "EUR",
                                  category="operations")
            rows.append(row(ctx, f"DRV-{10 + offset:03d}", "opex", ref, "EUR",
                            "flow", "annual", "allocate", "uniform", records,
                            start_period=0, end_period=11, cardinality="many",
                            cost_category=category))
        project, _ = make_project(ctx, base, fixture_id="F-7", name="c06")
        run = run_engine(ctx, project, engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        opex = modules_of(run).get("opex")
        if not opex:
            return ["modulo opex assente dal payload"], runs
        validate_ref(ctx, opex, "#/$defs/module_result", "opex", findings)
        lines = opex.get("lines") or []
        if len(lines) != len(categories):
            findings.append(
                f"righe opex: {len(lines)} invece di {len(categories)}")
        allowed = set(ctx["schema"]["$defs"]["cost_category"]["enum"])
        observed_categories = set()
        for line in lines:
            if "category" not in line:
                findings.append(
                    f"riga {line.get('line_id')!r} senza category: le righe "
                    "non sono categorizzate")
                continue
            if line["category"] not in allowed:
                findings.append(
                    f"riga {line.get('line_id')!r}: category="
                    f"{line['category']!r} fuori dalla tassonomia di fonti "
                    "e usi")
            observed_categories.add(line["category"])
        for category in categories:
            if category not in observed_categories:
                findings.append(
                    f"categoria {category!r} assente dalle righe opex")
        recon = (plan_of(run) or {}).get("reconciliations") or {}
        if (recon.get("REC-04") or {}).get("status") != "PASS":
            findings.append(
                f"REC-04 non PASS sul caso a tre categorie: "
                f"{(recon.get('REC-04') or {}).get('status')!r}")
        # NEGATIVO -- una riga PRIVA di categoria dichiarata: il totale
        # QUADRA comunque e il contratto deve fallire lo stesso.
        uncategorised = copy.deepcopy(rows)
        for entry in uncategorised:
            if entry["driver_id"] == "DRV-011":
                entry.pop("cost_category", None)
        project2, _ = make_project(ctx, base, fixture_id="F-7",
                                   name="c06-uncategorised")
        negative = run_engine(ctx, project2,
                              engine_input(ctx, uncategorised, records))
        runs.append(negative)
        neg_opex = modules_of(negative).get("opex") or {}
        neg_lines = neg_opex.get("lines") or []
        offending = [line for line in neg_lines if "category" not in line]
        if not offending:
            findings.append(
                "caso negativo: nessuna riga priva di category benche' "
                "DRV-011 non ne dichiari alcuna: il motore inventa la "
                "categoria")
        elif offending[0].get("line_id") is None:
            findings.append(
                "caso negativo: la riga priva di category non porta line_id: "
                "l'attribuzione manca")
        neg_total = series_of(neg_opex, 0) if neg_opex.get("series") else None
        pos_total = series_of(opex, 0)
        if neg_total is not None and neg_total != pos_total:
            findings.append(
                "caso negativo: il totale opex cambia togliendo la sola "
                "DICHIARAZIONE di categoria: il contratto deve fallire con "
                "il TOTALE INVARIATO")
    return findings, runs


def c07(ctx):
    """`FE-C-07` `T-FIN-RATE-CONVERSION` -- un tasso si COMPONE,
    `rate_conversion_not_compounded`, fixture F-6.

    Il contratto misura il tasso **APPLICATO AL CALCOLO**, non quello
    DICHIARATO nei metadati. Un valore corretto in `conversions_applied` NON lo
    soddisfa se il motore consuma un tasso diverso: e' esattamente la fuga
    della mutazione che sostituisce la sola SERIE consumata lasciando intatto
    il metadato. La misura e' quindi un RICALCOLO INDIPENDENTE del risultato
    finanziario a partire dal tasso COMPOSTO, confrontato con l'output DI
    PRODUZIONE.

    Il contratto presidia inoltre l'INSIEME PERMESSO CHIUSO della politica di
    conversione per OGNI natura di misura e la MAPPATURA DI CONFINE fra il
    vocabolario di binding e quello dello schema del piano finanziario.
    """
    findings = []
    runs = []
    fixture = ctx["testkit"].stage10_fixture("F-6")
    annual = Decimal(str(fixture["assumption"]["value"]))
    horizon = 12
    with tempfile.TemporaryDirectory(prefix="fin_core_c07_") as base:
        base = Path(base)
        records = base_records(ctx, churn=str(float(annual)))
        rows = base_rows(ctx, records)
        project, _ = make_project(ctx, base, fixture_id="F-6", name="c07")
        run = run_engine(ctx, project, engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        calendar = (plan_of(run) or {}).get("results", {}).get("calendar") or {}
        applied = [entry for entry in calendar.get("conversions_applied") or []
                   if entry.get("driver_id") == "DRV-003"]
        if not applied:
            findings.append(
                "conversions_applied[] privo della voce per DRV-003: una "
                "conversione che non compare nel report equivale a una non "
                "eseguita")
        else:
            entry = applied[0]
            if entry.get("conversion_policy") != "compound":
                findings.append(
                    f"DRV-003: conversion_policy={entry.get('conversion_policy')!r} "
                    "invece di compound")
            if not entry.get("formula"):
                findings.append("DRV-003: conversione senza formula")
            parameters = entry.get("parameters") or {}
            if "period_rate" not in parameters:
                findings.append(
                    "DRV-003: parameters privo di period_rate: la conversione "
                    "e' registrata ma non e' verificabile")
            else:
                observed = dec(parameters["period_rate"])
                compounded = period_rate(annual, Decimal(1) / Decimal(12))
                divided = annual / Decimal(12)
                if abs(observed - compounded) > Decimal("1e-6"):
                    findings.append(
                        f"{AMB_W2_02}: DRV-003 period_rate={observed} invece "
                        f"di {compounded} = 1-(1-r)^(1/12)")
                if abs(observed - divided) <= Decimal("1e-6"):
                    findings.append(
                        f"{AMB_W2_02}: DRV-003 period_rate coincide con la "
                        f"DIVISIONE lineare {divided}: il tasso e' ripartito "
                        "invece che composto")
        # ---- IL TASSO APPLICATO, non quello dichiarato --------------------
        # Il ricavo del periodo `t` e' `livello x sopravvivenza(t) x prezzo`,
        # e la sopravvivenza e' l'UNICA via per cui il tasso convertito entra
        # nei numeri. Invertendo l'identita' si ottiene il tasso che il motore
        # ha DAVVERO consumato, indipendentemente da cio' che dichiara.
        price = dec(records["ASS-001"]["value"])
        volume = dec(records["ASS-002"]["value"])
        fractions = month_fractions(horizon)
        compounded = period_rate(annual, Decimal(1) / Decimal(12))
        divided = annual / Decimal(12)
        revenue = modules_of(run).get("revenue") or {}
        if not revenue:
            findings.append(
                "modulo revenue assente: il tasso APPLICATO non e' misurabile "
                "e il contratto sarebbe soddisfatto dal solo metadato")
        else:
            for index in (0, 1, horizon - 1):
                expected = volume * expected_survival(annual, index,
                                                      fractions) * price
                produced = series_of(revenue, index)
                if abs(produced - expected) <= Decimal("1e-6"):
                    continue
                # Il tasso EFFETTIVAMENTE consumato, ricavato dall'output.
                applied_survival = produced / (volume * price)
                previous = (volume * expected_survival(annual, index - 1,
                                                       fractions) * price
                            if index else volume * price)
                step = (produced / previous) if previous != Decimal(0) else None
                implied = (Decimal(1) - step) if step is not None else None
                detail = (f"tasso di periodo APPLICATO {implied}"
                          if implied is not None else
                          f"sopravvivenza applicata {applied_survival}")
                if implied is not None and \
                        abs(implied - divided) <= Decimal("1e-6"):
                    detail += (f" = DIVISIONE LINEARE {divided} del tasso "
                               "annuo: il tasso e' RIPARTITO invece che "
                               "COMPOSTO")
                findings.append(
                    f"{AMB_W2_02}: DRV-003, periodo {index}: il tasso APPLICATO "
                    f"al calcolo non e' quello COMPOSTO {compounded}. "
                    f"revenue={produced} invece di {expected}; {detail}. Il "
                    "metadato conversions_applied[] puo' restare corretto: cio' "
                    "che questo contratto misura e' il calcolo, non la "
                    "dichiarazione")
                break
        # ---- INSIEME PERMESSO CHIUSO per OGNI natura di misura ------------
        # `per_unit`: il validator di binding impone `preserve_per_unit`; lo
        # schema del piano finanziario enumera `preserve_rate`. La mappatura di
        # confine congiunge i due vocabolari senza toccare nessuno dei due
        # artefatti.
        binding_form = copy.deepcopy(rows)
        for entry in binding_form:
            if entry["measure_kind"] == "per_unit":
                entry["conversion_policy"] = "preserve_per_unit"
        project_b, _ = make_project(ctx, base, fixture_id="F-6",
                                    name="c07-preserve-per-unit")
        mapped = run_engine(ctx, project_b,
                            engine_input(ctx, binding_form, records))
        runs.append(mapped)
        drivers = ((plan_of(mapped) or {}).get("driver_registry")
                   or {}).get("drivers") or []
        if not drivers:
            findings.append(
                "nessun driver emesso con la forma `preserve_per_unit` che il "
                "validator di binding impone")
        for driver in drivers:
            validate_ref(ctx, driver, "#/$defs/driver_entry",
                         f"driver_registry.{driver.get('driver_id')}", findings)
            policy = driver.get("conversion_policy")
            if driver.get("measure_kind") == "per_unit" and \
                    policy != "preserve_rate":
                findings.append(
                    f"{driver.get('driver_id')}: conversion_policy={policy!r} "
                    "emessa per un driver per_unit: il payload emesso porta il "
                    "vocabolario dello SCHEMA (`preserve_rate`) "
                    "attraverso la mappatura di confine, e non il vocabolario "
                    "di binding verbatim")
            if driver.get("measure_kind") == "rate" and policy != "compound":
                findings.append(
                    f"{driver.get('driver_id')}: conversion_policy={policy!r} "
                    "su un driver rate: `rate` e `per_unit` restano DUE "
                    "politiche distinte e non sono mai fuse")
        if mapped["available"] and mapped["exit_code"] != 0:
            findings.append(
                f"la forma `preserve_per_unit` imposta dal validator di "
                f"binding e' RESPINTA dal motore (exit {mapped['exit_code']}, "
                f"osservati={sorted(mapped['observed'])}): i due vocabolari "
                "non sono congiunti")
        # Il valore unitario e' PRESERVATO: `per_unit` non e' composto.
        nominal_cogs = modules_of(run).get("cogs") or {}
        mapped_cogs = modules_of(mapped).get("cogs") or {}
        if nominal_cogs and mapped_cogs and \
                series_of(nominal_cogs, 0) != series_of(mapped_cogs, 0):
            findings.append(
                "la mappatura di confine cambia i NUMERI: "
                f"cogs[0]={series_of(mapped_cogs, 0)} invece di "
                f"{series_of(nominal_cogs, 0)}. La mappatura e' LESSICALE e "
                "deve preservare la semantica")
        # NEGATIVO-1 -- `allocate` su un driver `rate` NON e' derivabile dalla
        # classe di unita': la variante `allocate` della fixture F-6 e'
        # respinta, non applicata in silenzio.
        allocate_rows = copy.deepcopy(rows)
        for entry in allocate_rows:
            if entry["role"] == "churn_rate":
                entry["conversion_policy"] = "allocate"
        project2, _ = make_project(ctx, base, fixture_id="F-6",
                                   name="c07-allocate")
        negative = run_engine(ctx, project2,
                              engine_input(ctx, allocate_rows, records))
        runs.append(negative)
        if AMB_W2_02 not in negative["observed"]:
            findings.append(
                f"caso negativo: {AMB_W2_02} assente su un driver rate con "
                f"conversion_policy allocate; osservati="
                f"{sorted(negative['observed'])}")
        elif not errors_with(negative, AMB_W2_02, "DRV-003"):
            findings.append(
                f"caso negativo: {AMB_W2_02} presente ma NON attribuito a "
                "DRV-003")
        # NEGATIVO-2 -- politica ARBITRARIA su una natura di misura DIVERSA da
        # `rate`: senza verifica il motore accetterebbe qualunque stringa e la
        # emetterebbe verbatim in una sezione che va validata per `$ref`
        # contro lo schema del piano finanziario.
        # NEGATIVO-3 -- politica valida per un'ALTRA natura di misura.
        for label, target, policy in (
                ("arbitraria", "per_unit", "totally_invented_policy"),
                ("di un'altra natura", "per_unit", "compound"),
                ("di un'altra natura", "stock", "allocate"),
                ("di un'altra natura", "flow", "carry_level")):
            broken = copy.deepcopy(rows)
            offenders = []
            for entry in broken:
                if entry["measure_kind"] == target:
                    entry["conversion_policy"] = policy
                    offenders.append(entry["driver_id"])
            project_n, _ = make_project(
                ctx, base, fixture_id="F-6",
                name=f"c07-{target}-{policy}".replace("_", "-"))
            rejected = run_engine(ctx, project_n,
                                  engine_input(ctx, broken, records))
            runs.append(rejected)
            attributed = errors_with(rejected, CODE_CONVERSION_POLICY)
            if not attributed:
                findings.append(
                    f"caso negativo: politica {label} {policy!r} su "
                    f"measure_kind {target!r} ACCETTATA senza alcun "
                    f"{CODE_CONVERSION_POLICY}; osservati="
                    f"{sorted(rejected['observed'])}")
            elif not any(item.get("ref") in offenders for item in attributed):
                findings.append(
                    f"caso negativo: {CODE_CONVERSION_POLICY} non attribuito "
                    f"ad alcuno dei driver {offenders}")
            if rejected["available"] and rejected["exit_code"] == 0:
                findings.append(
                    f"caso negativo: politica {label} {policy!r} su {target!r} "
                    "non BLOCCA il calcolo (exit 0)")
            if AMB_W2_02 in rejected["observed"] and target != "rate":
                findings.append(
                    f"caso negativo: attribuzione VIETATA: {AMB_W2_02} presidia "
                    f"la natura `rate`, non {target!r}")
        # Esclusione di falso positivo: il contratto fallisce anche con
        # REC-01, REC-05 e REC-12 tutte verdi.
        recon = (plan_of(run) or {}).get("reconciliations") or {}
        for rec_id in ("REC-01", "REC-05", "REC-12"):
            if (recon.get(rec_id) or {}).get("status") not in ("PASS",
                                                               "NOT_APPLICABLE"):
                findings.append(
                    f"esclusione di falso positivo: {rec_id} non e' verde sul "
                    "caso nominale e il contratto perderebbe la propria "
                    "specificita'")
    return findings, runs


def c08(ctx):
    """`FE-C-08` `T-FIN-DETERMINISM` -- `engine_determinism_violated`."""
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_core_c08_") as base:
        base = Path(base)
        records = base_records(ctx)
        rows = base_rows(ctx, records)
        payload = engine_input(ctx, rows, records)
        project, _ = make_project(ctx, base, name="c08")
        first = run_engine(ctx, project, payload)
        runs.append(first)
        if not first["available"]:
            return [first["reason"]], runs
        second = run_engine(ctx, project, payload)
        runs.append(second)
        meta_a = (plan_of(first) or {}).get("calculation_metadata") or {}
        meta_b = (plan_of(second) or {}).get("calculation_metadata") or {}
        checksum_a = (meta_a.get("output_checksums") or {}).get("base")
        checksum_b = (meta_b.get("output_checksums") or {}).get("base")
        if not checksum_a:
            findings.append(
                "RED-1: output_checksums.base assente: il ricalcolo "
                "deterministico non e' verificabile")
        elif checksum_a != checksum_b:
            findings.append(
                f"{AMB_W2_03}: output_checksums.base diverge fra due "
                f"esecuzioni sullo stesso input: {checksum_a} != {checksum_b}")
        hash_a = meta_a.get("engine_source_hash")
        if not hash_a:
            findings.append("RED-2: engine_source_hash assente")
        # RED-2 -- il sorgente MODIFICATO deve cambiare `engine_source_hash`.
        mutated_dir = Path(base) / "mutated"
        mutated_dir.mkdir()
        mutated = mutated_dir / "validate_financial_engine.py"
        original = ctx["entry_point"].read_text(encoding="utf-8")
        mutated.write_text(
            original + "\n# delta di sorgente della sonda FE-C-08\n",
            encoding="utf-8")
        env_extra = {"PYTHONPATH": str(ctx["root"] / VALIDATORS_REL)}
        third = run_engine(ctx, project, payload, entry_point=mutated,
                           env_extra=env_extra)
        runs.append(third)
        meta_c = (plan_of(third) or {}).get("calculation_metadata") or {}
        hash_c = meta_c.get("engine_source_hash")
        if not hash_c:
            findings.append(
                "RED-2: il sorgente modificato non ha prodotto "
                "engine_source_hash")
        elif hash_a == hash_c:
            findings.append(
                f"{AMB_W2_03}: engine_source_hash INVARIATO dopo una modifica "
                f"del sorgente ({hash_a}): l'hash e' congelato a una costante")
        version_a = meta_a.get("engine_version")
        version_c = meta_c.get("engine_version")
        if version_a != version_c:
            findings.append(
                "RED-2 attribuzione VIETATA: un cambio di engine_version non "
                "soddisfa il contratto, che misura engine_source_hash")
        # Il motore dichiara la propria autoverifica di determinismo.
        if not checks_with(first, AMB_W2_03, "PASS"):
            findings.append(
                f"il motore non emette il check {AMB_W2_03} sul caso "
                "nominale: l'autoverifica di determinismo non e' riportata")
    return findings, runs


def c09(ctx):
    """`FE-C-09` `T-FIN-PNL` -- nessuna fonte finanziaria nel P&L
    (`financing_in_pnl`)."""
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_core_c09_") as base:
        base = Path(base)
        records = base_records(ctx)
        rows = base_rows(ctx, records)
        project, _ = make_project(ctx, base, name="c09")
        run = run_engine(ctx, project, engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        pnl = modules_of(run).get("pnl")
        if not pnl:
            return ["modulo pnl assente dal payload"], runs
        validate_ref(ctx, pnl, "#/$defs/module_result", "pnl", findings)
        if CODE_FINANCING_IN_PNL in run["observed"]:
            findings.append(
                f"{CODE_FINANCING_IN_PNL} presente sul caso nominale, che non "
                "contiene alcuna fonte finanziaria")
        revenue = series_of(modules_of(run)["revenue"], 0)
        cogs = series_of(modules_of(run)["cogs"], 0)
        payroll = series_of(modules_of(run)["payroll"], 0)
        opex = series_of(modules_of(run)["opex"], 0)
        ebitda = metric_of(pnl, "ebitda_0")
        if ebitda is None:
            findings.append("pnl privo della metrica ebitda_0")
        elif dec(ebitda) != revenue - cogs - payroll - opex:
            findings.append(
                f"EBITDA periodo 0 = {ebitda} invece di "
                f"{revenue - cogs - payroll - opex}")
        # NEGATIVO -- una riga `equity_financing` dichiarata fra i costi.
        financed = copy.deepcopy(rows)
        records["ASS-012"] = record(ctx["testkit"], 12, 25000.0, "EUR",
                                    category="finance")
        financed.append(row(ctx, "DRV-012", "opex", "ASS-012", "EUR", "flow",
                            "annual", "allocate", "one_off", records,
                            start_period=0, end_period=0, cardinality="many",
                            cost_category="equity_financing"))
        for entry in financed:
            if entry["role"] == "opex":
                entry["cardinality"] = "many"
        project2, _ = make_project(ctx, base, name="c09-financing")
        negative = run_engine(ctx, project2,
                              engine_input(ctx, financed, records))
        runs.append(negative)
        attributed = errors_with(negative, CODE_FINANCING_IN_PNL)
        if not attributed:
            findings.append(
                f"caso negativo: {CODE_FINANCING_IN_PNL} assente con una riga "
                f"equity_financing; osservati={sorted(negative['observed'])}")
        elif not any(entry.get("ref") for entry in attributed):
            findings.append(
                f"caso negativo: {CODE_FINANCING_IN_PNL} non attribuito ad "
                "alcuna RIGA")
        if "financing_in_revenue" in negative["observed"]:
            findings.append(
                "attribuzione VIETATA: financing_in_revenue non soddisfa "
                "questo contratto")
        neg_pnl = modules_of(negative).get("pnl") or {}
        for line in neg_pnl.get("lines") or []:
            if line.get("category") == "equity_financing":
                findings.append(
                    f"caso negativo: la riga {line.get('line_id')!r} "
                    "equity_financing e' entrata nel P&L")
        # Esclusione di falso positivo: il totale di cassa resta corretto.
        neg_recon = (plan_of(negative) or {}).get("reconciliations") or {}
        if (neg_recon.get("REC-05") or {}).get("status") != "PASS":
            findings.append(
                "esclusione di falso positivo: REC-05 non e' PASS sul caso "
                "negativo e il contratto perderebbe la propria specificita'")
    return findings, runs


def c10(ctx):
    """`FE-C-10` `T-FIN-CASH-FLOW` -- roll-forward `REC-05`, saldo di
    apertura mai fra le fonti (`opening_balance_as_source`)."""
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_core_c10_") as base:
        base = Path(base)
        records = base_records(ctx)
        rows = base_rows(ctx, records)
        project, _ = make_project(ctx, base, name="c10")
        run = run_engine(ctx, project, engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        cash = modules_of(run).get("cash_flow")
        if not cash:
            return ["modulo cash_flow assente dal payload"], runs
        validate_ref(ctx, cash, "#/$defs/module_result", "cash_flow", findings)
        opening = dec(records["ASS-008"]["value"])
        if dec(metric_of(cash, "opening_0")) != opening:
            findings.append(
                f"opening_0={metric_of(cash, 'opening_0')!r} invece di "
                f"{opening}")
        eur = Decimal(str((ctx["enforcement"].get("tolerances") or {})["EUR"]))
        for index in range(12):
            o = dec(metric_of(cash, f"opening_{index}"))
            i = dec(metric_of(cash, f"cash_in_{index}"))
            u = dec(metric_of(cash, f"cash_out_{index}"))
            e = dec(metric_of(cash, f"ending_{index}"))
            residual = (o + i - u) - e
            if residual.copy_abs() > eur:
                findings.append(
                    f"RED-1: periodo {index}: opening {o} + in {i} - out {u} "
                    f"!= ending {e}; residuo {residual} oltre la tolleranza "
                    f"EUR {eur}")
                break
        recon = (plan_of(run) or {}).get("reconciliations") or {}
        rec05 = recon.get("REC-05") or {}
        if rec05.get("status") != "PASS":
            findings.append(f"REC-05 non PASS: {rec05.get('status')!r}")
        if not rec05.get("residual_breakdown"):
            findings.append(
                "REC-05 senza residual_breakdown per periodo: "
                "l'attribuzione manca anche quando la riconciliazione passa")
        if AMB_W2_01 in run["observed"]:
            findings.append(
                f"{AMB_W2_01} presente sul caso nominale, dove il saldo di "
                "apertura NON e' fra le fonti")
        # RED-2 -- il saldo di apertura DICHIARATO anche come fonte.
        as_source = copy.deepcopy(rows)
        as_source.append(row(ctx, "DRV-008", "opex", "ASS-008", "EUR", "flow",
                             "annual", "allocate", "one_off", records,
                             start_period=0, end_period=0, cardinality="many",
                             cost_category="other_operating_income"))
        for entry in as_source:
            if entry["role"] == "opex":
                entry["cardinality"] = "many"
        project2, _ = make_project(ctx, base, name="c10-source")
        negative = run_engine(ctx, project2,
                              engine_input(ctx, as_source, records))
        runs.append(negative)
        attributed = errors_with(negative, AMB_W2_01)
        if not attributed:
            findings.append(
                f"RED-2: {AMB_W2_01} assente benche' ASS-008 (saldo di "
                f"apertura) sia dichiarato fra le fonti; osservati="
                f"{sorted(negative['observed'])}")
        elif not any(entry.get("ref") in ("DRV-008", "ASS-008")
                     for entry in attributed):
            findings.append(
                f"RED-2: {AMB_W2_01} non attribuito alla VOCE DI APERTURA "
                "(DRV-008 / ASS-008)")
        if "funding_gap_as_source" in negative["observed"]:
            findings.append(
                "RED-2: attribuzione VIETATA: funding_gap_as_source non "
                "soddisfa questo contratto")
    return findings, runs


def c11(ctx):
    """`FE-C-11` `T-FIN-RUNWAY` -- `cash_metrics_collapsed`.

    Le QUATTRO grandezze di cassa del modulo `runway` sono `runway_to_zero`,
    `runway_to_buffer` e i due periodi di prima violazione. La coppia
    `funding_gap_to_zero`/`funding_gap_to_buffer` appartiene al modulo
    `funding_gap`: il contratto verifica ESPLICITAMENTE che `runway` non la
    esponga.
    """
    findings = []
    runs = []
    keys = ("runway_to_zero", "runway_to_buffer",
            "first_period_below_zero", "first_period_below_buffer")
    with tempfile.TemporaryDirectory(prefix="fin_core_c11_") as base:
        base = Path(base)
        records = base_records(ctx, opening_cash="30000")
        rows = base_rows(ctx, records)
        config = financial_config(
            ctx, cash_buffer_policy={"kind": "absolute", "value": 20000})
        project, _ = make_project(ctx, base, name="c11")
        run = run_engine(ctx, project,
                         engine_input(ctx, rows, records, config=config))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        runway = modules_of(run).get("runway")
        if not runway:
            return ["modulo runway assente dal payload"], runs
        validate_ref(ctx, runway, "#/$defs/module_result", "runway", findings)
        values = {}
        for key in keys:
            value = metric_of(runway, key)
            if value is None:
                findings.append(f"runway privo della chiave {key!r}")
            values[key] = value
        # Il collasso NON e' l'uguaglianza dei VALORI: due misure calcolate da
        # soglie DIVERSE coincidono in casi legittimi. Cio' che il contratto
        # misura e' la PROVENIENZA -- ogni misura emessa coincide con quella che
        # l'harness RICALCOLA dalla PROPRIA soglia, sulla stessa serie di cassa.
        cash = modules_of(run).get("cash_flow") or {}
        ending = [dec(metric_of(cash, f"ending_{index}"))
                  for index in range(12)]
        expected_zero = expected_runway(ending, 12, Decimal(0))
        expected_buffer = expected_runway(ending, 12, Decimal(20000))
        for key, expected in (("runway_to_zero", expected_zero[0]),
                              ("runway_to_buffer", expected_buffer[0])):
            observed = values.get(key)
            if not isinstance(observed, int) or isinstance(observed, bool):
                findings.append(
                    f"{AMB_W2_04}: {key}={observed!r} non e' un INDICE DI "
                    "PERIODO: un periodo di prima violazione -- che vale "
                    "'NOT_APPLICABLE' quando la soglia non e' attraversata -- "
                    "usato COME misura viola il dominio della grandezza")
            elif observed != expected:
                findings.append(
                    f"{AMB_W2_04}: {key}={observed!r} invece di {expected}, "
                    "che e' il valore prodotto dalla PROPRIA soglia sulla "
                    "stessa serie di cassa: la misura e' SOSTITUITA, ALIASSATA "
                    "o derivata dalla definizione sbagliata")
        for key, expected in (
                ("first_period_below_zero", expected_zero[1]),
                ("first_period_below_buffer", expected_buffer[1])):
            observed = values.get(key)
            wanted = "NOT_APPLICABLE" if expected is None else expected
            if observed != wanted:
                findings.append(
                    f"{AMB_W2_04}: {key}={observed!r} invece di {wanted!r}: il "
                    "periodo di prima violazione resta AUSILIARIO e ha il "
                    "proprio dominio, distinto da quello della misura")
        # SEPARAZIONE DEI MODULI. I tre moduli aggiuntivi ESISTONO, ma le
        # quattro metriche di cassa restano DISTINTE e ciascuna vive nel
        # PROPRIO modulo: `runway` porta `runway_to_*`, `funding_gap` porta
        # `funding_gap_to_*`. Un `runway` che esponesse `funding_gap_to_zero`
        # collasserebbe due moduli, che e' il collasso delle misure di cassa
        # sull'altro asse.
        for foreign in ("funding_gap", "break_even"):
            if metric_of(runway, f"{foreign}_to_zero") is not None:
                findings.append(
                    f"runway espone {foreign}_to_zero: la grandezza appartiene "
                    f"al modulo {foreign!r}, non a runway")
        # ---- PIANO SANO: nessuna soglia attraversata ----------------------
        # E' l'esito che lo Stage 10 esiste per produrre. Le due misure di
        # runway valgono ENTRAMBE l'orizzonte e i due riassunti di fabbisogno
        # valgono ENTRAMBI zero: e' un'uguaglianza LEGITTIMA, non un collasso.
        # Un piano solvibile, sempre sopra il buffer dichiarato e con tutte le
        # riconciliazioni verdi, NON puo' essere respinto dal gate di egress.
        healthy_records = base_records(
            ctx, price="100", volume="200", churn="0.10", variable_cost="30",
            headcount="3", payroll_unit="3500", opex="60000",
            opening_cash="150000")
        healthy_config = financial_config(
            ctx, cash_buffer_policy={"kind": "absolute", "value": 100000})
        project_h, _ = make_project(ctx, base, name="c11-healthy")
        healthy = run_engine(
            ctx, project_h,
            engine_input(ctx, base_rows(ctx, healthy_records),
                         healthy_records, config=healthy_config))
        runs.append(healthy)
        healthy_runway = modules_of(healthy).get("runway") or {}
        healthy_gap = modules_of(healthy).get("funding_gap") or {}
        healthy_buffer = modules_of(healthy).get("cash_buffer") or {}
        healthy_cash = modules_of(healthy).get("cash_flow") or {}
        if not healthy_runway:
            findings.append(
                "piano sano: nessun modulo runway prodotto; osservati="
                f"{sorted(healthy['observed'])}")
        else:
            healthy_ending = [dec(metric_of(healthy_cash, f"ending_{index}"))
                              for index in range(12)]
            if min(healthy_ending) <= Decimal(0):
                findings.append(
                    "piano sano: la cassa scende sotto ZERO e la fixture non "
                    "esercita piu' il caso solvibile")
            if min(healthy_ending) <= Decimal(100000):
                findings.append(
                    "piano sano: la cassa scende sotto il BUFFER dichiarato e "
                    "la fixture non esercita piu' il caso sano")
            for key in ("runway_to_zero", "runway_to_buffer"):
                if metric_of(healthy_runway, key) != 12:
                    findings.append(
                        f"piano sano: {key}={metric_of(healthy_runway, key)!r} "
                        "invece dell'ORIZZONTE 12 su un piano che non "
                        "attraversa alcuna soglia")
            for key in ("funding_gap_to_zero", "funding_gap_to_buffer"):
                value = metric_of(healthy_gap, key)
                if value == "NOT_APPLICABLE" or dec(value) != Decimal(0):
                    findings.append(
                        f"piano sano: {key}={value!r} invece di 0 su un piano "
                        "che non attraversa alcuna soglia")
            if healthy_buffer.get("status") != "PASS":
                findings.append(
                    f"piano sano: cash_buffer status="
                    f"{healthy_buffer.get('status')!r} invece di PASS")
        if AMB_W2_04 in healthy["observed"]:
            findings.append(
                f"{AMB_W2_04}: un piano SOLVIBILE, sempre sopra il buffer "
                "dichiarato, e' respinto perche' le due misure di runway "
                "valgono ENTRAMBE l'orizzonte. L'uguaglianza di due misure "
                "calcolate da soglie DIVERSE non e' un collasso: e' il "
                "percorso che lo Stage 10 esiste per produrre")
        healthy_recon = (plan_of(healthy) or {}).get("reconciliations") or {}
        not_green = sorted(rec for rec, entry in healthy_recon.items()
                           if entry.get("status") not in ("PASS",
                                                          "NOT_APPLICABLE"))
        if not_green:
            findings.append(
                f"piano sano: riconciliazioni non verdi {not_green}: la "
                "fixture non esercita piu' il piano integralmente riconciliato")
        healthy_result = ((plan_of(healthy) or {}).get("validation")
                          or {}).get("result")
        if healthy_result == "FAIL":
            findings.append(
                "piano sano: validation.result=FAIL su un piano solvibile con "
                "tutte le riconciliazioni verdi; osservati="
                f"{sorted(healthy['observed'])}")
        # ---- ATTRAVERSAMENTO COINCIDENTE ----------------------------------
        # Zero e buffer attraversati nello STESSO periodo: le due misure
        # coincidono di nuovo, e di nuovo LEGITTIMAMENTE, perche' ciascuna
        # resta calcolata dalla PROPRIA soglia.
        coincident_config = financial_config(
            ctx, cash_buffer_policy={"kind": "absolute", "value": 1})
        coincident_records = base_records(ctx, opening_cash="20000")
        project_c, _ = make_project(ctx, base, name="c11-coincident")
        coincident = run_engine(
            ctx, project_c,
            engine_input(ctx, base_rows(ctx, coincident_records),
                         coincident_records, config=coincident_config))
        runs.append(coincident)
        co_runway = modules_of(coincident).get("runway") or {}
        if not co_runway:
            findings.append(
                "attraversamento coincidente: nessun modulo runway prodotto")
        else:
            if metric_of(co_runway, "runway_to_zero") != \
                    metric_of(co_runway, "runway_to_buffer"):
                findings.append(
                    "attraversamento coincidente: le due misure NON "
                    "coincidono e la fixture non esercita piu' il caso "
                    f"(zero={metric_of(co_runway, 'runway_to_zero')!r}, "
                    f"buffer={metric_of(co_runway, 'runway_to_buffer')!r})")
            if AMB_W2_04 in coincident["observed"]:
                findings.append(
                    f"{AMB_W2_04}: zero e buffer attraversati nello STESSO "
                    "periodo sono trattati come collasso, mentre ciascuna "
                    "misura resta calcolata dalla PROPRIA soglia")
        # NEGATIVO -- senza policy di buffer le due metriche di buffer sono
        # NOT_APPLICABLE DICHIARATO, mai uguali a quelle di zero.
        project2, _ = make_project(ctx, base, name="c11-nobuffer")
        negative = run_engine(ctx, project2,
                              engine_input(ctx, rows, records))
        runs.append(negative)
        neg_runway = modules_of(negative).get("runway") or {}
        for key in ("runway_to_buffer", "first_period_below_buffer"):
            value = metric_of(neg_runway, key)
            if value != "NOT_APPLICABLE":
                findings.append(
                    f"caso negativo: {key}={value!r} invece di "
                    "'NOT_APPLICABLE' con cash_buffer_policy assente: uno "
                    "zero implicito e' vietato")
        if AMB_W2_04 in negative["observed"]:
            findings.append(
                f"caso negativo: {AMB_W2_04} emesso benche' le metriche di "
                "buffer siano NOT_APPLICABLE dichiarato")
        # Esclusione di falso positivo: il contratto fallisce anche con
        # `REC-05` verde.
        recon = (plan_of(run) or {}).get("reconciliations") or {}
        if (recon.get("REC-05") or {}).get("status") != "PASS":
            findings.append(
                "esclusione di falso positivo: REC-05 non e' PASS sul caso "
                "nominale")
    return findings, runs


def c12(ctx):
    """`FE-C-12` `T-FIN-BUFFER` -- soglia di buffer dichiarata o
    NOT_APPLICABLE."""
    findings = []
    runs = []
    # La cassa NON va MAI sotto zero su questa fixture, e il buffer e'
    # comunque violato: e' l'esclusione di falso positivo del contratto.
    with tempfile.TemporaryDirectory(prefix="fin_core_c12_") as base:
        base = Path(base)
        records = base_records(ctx, opening_cash="100000")
        rows = base_rows(ctx, records)
        config = financial_config(
            ctx, cash_buffer_policy={"kind": "absolute", "value": 95000})
        project, _ = make_project(ctx, base, name="c12")
        run = run_engine(ctx, project,
                         engine_input(ctx, rows, records, config=config))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        buffer_module = modules_of(run).get("cash_buffer")
        if not buffer_module:
            return ["modulo cash_buffer assente dal payload"], runs
        validate_ref(ctx, buffer_module, "#/$defs/module_result",
                     "cash_buffer", findings)
        if buffer_module.get("status") == "NOT_APPLICABLE":
            findings.append(
                "cash_buffer NOT_APPLICABLE benche' la policy sia dichiarata")
        threshold = metric_of(buffer_module, "threshold")
        if threshold is None or dec(threshold) != Decimal(95000):
            findings.append(f"soglia di buffer={threshold!r} invece di 95000")
        violations = buffer_module.get("lines")
        first = metric_of(buffer_module, "first_violation_period")
        entity = metric_of(buffer_module, "first_violation_shortfall")
        if first is None or first == "NOT_APPLICABLE":
            findings.append(
                "violazione di buffer non segnalata: first_violation_period "
                f"={first!r} su una cassa che scende sotto la soglia")
        if entity is None or entity == "NOT_APPLICABLE":
            findings.append(
                "violazione di buffer senza ENTITA': "
                f"first_violation_shortfall={entity!r}")
        del violations
        # NEGATIVO -- policy ASSENTE => NOT_APPLICABLE DICHIARATO, mai 0.
        project2, _ = make_project(ctx, base, name="c12-nopolicy")
        negative = run_engine(ctx, project2,
                              engine_input(ctx, rows, records))
        runs.append(negative)
        neg_buffer = modules_of(negative).get("cash_buffer")
        if neg_buffer is None:
            findings.append(
                "caso negativo: il modulo cash_buffer e' OMESSO invece che "
                "dichiarato NOT_APPLICABLE")
        else:
            if neg_buffer.get("status") != "NOT_APPLICABLE":
                findings.append(
                    f"caso negativo: cash_buffer status="
                    f"{neg_buffer.get('status')!r} invece di NOT_APPLICABLE "
                    "con policy assente")
            reason = neg_buffer.get("not_applicable_reason") or ""
            if "cash_buffer_policy" not in reason:
                findings.append(
                    f"caso negativo: not_applicable_reason={reason!r} non "
                    "NOMINA cash_buffer_policy")
            if metric_of(neg_buffer, "threshold") in (0, "0", 0.0):
                findings.append(
                    "caso negativo: la policy assente e' trattata come soglia "
                    "ZERO")
        # Esclusione di falso positivo: il contratto vale anche quando la
        # cassa non va mai sotto zero -- e' il caso nominale qui sopra.
        cash = modules_of(run).get("cash_flow") or {}
        if dec(metric_of(cash, "ending_11")) < 0:
            findings.append(
                "esclusione di falso positivo: la cassa va sotto ZERO nel "
                "caso nominale e il contratto misurerebbe il segno invece "
                "della soglia")
    return findings, runs


def _module_literals(path):
    """Letterali del sorgente, con file e riga (`FE-C-20`, `FE-C-31`)."""
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and \
                    isinstance(body[0].value, ast.Constant) and \
                    isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    numbers, strings, names = [], [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            if id(node) in docstrings:
                continue
            if isinstance(node.value, bool):
                continue
            if isinstance(node.value, (int, float)):
                numbers.append((node.lineno, node.value))
            elif isinstance(node.value, str):
                strings.append((node.lineno, node.value))
        elif isinstance(node, ast.Name):
            names.append((node.lineno, node.id))
        elif isinstance(node, ast.Attribute):
            names.append((node.lineno, node.attr))
    return text, numbers, strings, names


#: Costanti STRUTTURALI ammesse nel sorgente del motore: indici di periodo,
#: mesi per periodo, precisione decimale. L'elenco ESCLUDE l'orizzonte,
#: `anchor_date` e la valuta, che vivono in `financial_config`, e ogni valore
#: economico (prezzo, salario, churn, costo unitario, benchmark).
STRUCTURAL_NUMBERS = frozenset({0, 1, 2, 3, 4, 12, 28})


def c20(ctx):
    """`FE-C-20` `T-FIN-NO-ECONOMIC-HARDCODE` -- nessun letterale economico
    nel sorgente del motore."""
    findings = []
    entry = ctx["entry_point"]
    if not entry.is_file():
        return [MISSING_CAPABILITY_REASON], []
    text, numbers, strings, _ = _module_literals(entry)
    for line, value in numbers:
        if value in STRUCTURAL_NUMBERS:
            continue
        findings.append(
            f"{ENTRY_POINT_REL}:{line}: letterale numerico {value!r} fuori "
            "dalle costanti strutturali ammesse: e' un valore economico o una "
            "coordinata (orizzonte / valuta) che deve vivere in "
            "financial_config")
    for line, value in strings:
        if len(value) == 3 and value.isalpha() and value.isupper():
            findings.append(
                f"{ENTRY_POINT_REL}:{line}: letterale di VALUTA {value!r} nel "
                "sorgente del motore: la valuta vive in financial_config")
        if len(value) == 10 and value[4] == "-" and value[7] == "-" and \
                value.replace("-", "").isdigit():
            findings.append(
                f"{ENTRY_POINT_REL}:{line}: letterale di DATA {value!r} nel "
                "sorgente del motore: anchor_date vive in financial_config")
    # Caso POSITIVO della scansione: il modulo di test che la esegue contiene
    # DELIBERATAMENTE letterali economici, e la scansione li rileva. Senza
    # questo caso la scansione potrebbe essere vacua.
    probe = Path(__file__).resolve()
    _, probe_numbers, _, _ = _module_literals(probe)
    detected = [value for _, value in probe_numbers
                if value not in STRUCTURAL_NUMBERS]
    if not detected:
        findings.append(
            "la scansione non rileva alcun letterale economico nemmeno nel "
            "modulo di test, che ne contiene per costruzione: la scansione e' "
            "vacua")
    del text
    return findings, []


def _tolerance_pairs(result):
    """Coppie (`check_id`, tolleranza serializzata, unita', soglia applicata).

    La soglia APPLICATA non puo' vivere dentro `reconciliation` ne' dentro
    `checks[]`: entrambi gli oggetti sono `additionalProperties: false` nello
    schema del piano finanziario, e aggiungervi un campo lo violerebbe. Vive
    percio' nel `tolerance_ledger` dell'envelope intermedio NON canonico,
    accanto al payload.
    """
    plan = (result or {}).get("financial_payload") or {}
    ledger = (result or {}).get("tolerance_ledger") or {}
    pairs = []
    for rec_id, entry in sorted((plan.get("reconciliations") or {}).items()):
        pairs.append((rec_id, entry.get("tolerance"),
                      entry.get("tolerance_unit"), ledger.get(rec_id)))
    for entry in (plan.get("validation") or {}).get("checks") or []:
        if entry.get("tolerance") is not None:
            pairs.append((entry.get("check_id"), entry.get("tolerance"), None,
                          ledger.get(entry.get("check_id"))))
    return pairs


def c22(ctx):
    """`FE-C-22` -- guardia di tolleranza: stringa serializzata = soglia
    applicata."""
    findings = []
    runs = []
    tolerances = ctx["enforcement"].get("tolerances") or {}
    with tempfile.TemporaryDirectory(prefix="fin_core_c22_") as base:
        base = Path(base)
        records = base_records(ctx)
        rows = base_rows(ctx, records)
        project, _ = make_project(ctx, base, name="c22")
        run = run_engine(ctx, project, engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        plan = plan_of(run)
        if not plan:
            return ["payload del motore assente"], runs
        pairs = _tolerance_pairs(run.get("result"))
        if not pairs:
            findings.append(
                "nessuna coppia (check_id, tolerance) emessa: la guardia "
                "sarebbe vacua")
        for check_id, serialized, unit, applied in pairs:
            if serialized is None:
                findings.append(f"{check_id}: tolerance assente")
                continue
            parts = str(serialized).split()
            if len(parts) != 2:
                findings.append(
                    f"{check_id}: tolerance={serialized!r} non e' nella forma "
                    "'<unita'> <soglia>'")
                continue
            label, number = parts
            try:
                parsed = Decimal(number)
            except decimal.InvalidOperation:
                findings.append(
                    f"{check_id}: tolerance={serialized!r}: la soglia non e' "
                    "parsabile")
                continue
            if applied is None:
                findings.append(
                    f"{check_id}: la soglia APPLICATA non e' riportata "
                    "(tolerance_value): la coppia non e' verificabile")
                continue
            if parsed != dec(applied):
                findings.append(
                    f"{check_id}: la stringa {serialized!r} parsa a {parsed} "
                    f"mentre la soglia APPLICATA e' {applied}")
            # `REC-14` porta la tolleranza NELL'UNITA' DEL DRIVER:
            # la soglia non e' nuova, e' quella ESATTA di `count`.
            source = tolerances.get(label)
            if source is None:
                source = tolerances.get("count")
            del unit
            if source is None:
                findings.append(
                    f"{check_id}: l'unita' {label!r} non ha una soglia in "
                    "enforcement-config.json.tolerances")
            elif Decimal(str(source)) != parsed:
                findings.append(
                    f"{check_id}: soglia {parsed} diversa da "
                    f"enforcement-config.tolerances[{label!r}]={source!r}")
        # Caso NEGATIVO -- la guardia deve rilevare una coppia incoerente.
        probe = {"check_id": "PROBE", "tolerance": "EUR 0.02",
                 "tolerance_value": tolerances.get("EUR", "0.01")}
        parsed = Decimal(str(probe["tolerance"]).split()[1])
        if parsed == Decimal(str(probe["tolerance_value"])):
            findings.append(
                "caso negativo: la sonda di incoerenza non e' incoerente: la "
                "guardia non discrimina")
        # Il letterale dichiarato "ratio 1e-6" e' PRESERVATO.
        ratio = [pair for pair in pairs if pair[1] and
                 str(pair[1]).startswith("ratio")]
        if ratio and str(ratio[0][1]) != "ratio 1e-6":
            findings.append(
                f"il letterale dichiarato 'ratio 1e-6' e' stato riscritto in "
                f"{ratio[0][1]!r}")
    return findings, runs


def c23(ctx):
    """`FE-C-23` -- regressione fail-closed sul progetto demo.

    Il demo NON e' l'ingresso del motore: l'ingresso e' il payload di binding
    gia' risolto. Il demo compare QUI, e solo qui, come regressione
    ATTRIBUITA.
    """
    findings = []
    runs = []
    demo = ctx["root"] / DEMO_PROJECT_REL
    before = ctx["testkit"].snapshot_tree(demo)
    records = base_records(ctx)
    rows = [entry for entry in base_rows(ctx, records)
            if entry["role"] != "opex"]
    payload = engine_input(ctx, rows, records, declare_config=False)
    run = run_engine(ctx, demo, payload)
    runs.append(run)
    if not run["available"]:
        return [run["reason"]], runs
    if not [e for e in errors_with(run, CODE_CONFIG_MISSING)
            if PROJECT_CONFIG_REL in (e.get("message") or "")]:
        findings.append(
            f"{CODE_CONFIG_MISSING} non attribuito al progetto demo "
            f"({PROJECT_CONFIG_REL} non nominato); "
            f"osservati={sorted(run['observed'])}")
    if not errors_with(run, CODE_ROLE_UNBOUND, "opex"):
        findings.append(
            f"{CODE_ROLE_UNBOUND} non attribuito al ruolo 'opex'; il codice "
            "GLOBALE non soddisfa il contratto")
    plan = plan_of(run) or {}
    modules = (plan.get("results") or {}).get("modules") or {}
    if modules:
        findings.append(
            f"il motore ha calcolato sul demo: moduli prodotti="
            f"{sorted(modules)}; l'esito dovuto e' FAIL con ZERO valori")
    if (plan.get("validation") or {}).get("result") != "FAIL":
        findings.append(
            f"validation.result="
            f"{(plan.get('validation') or {}).get('result')!r} invece di FAIL")
    if run["exit_code"] != 1:
        findings.append(
            f"exit code {run['exit_code']} invece di 1 sul demo")
    after = ctx["testkit"].snapshot_tree(demo)
    if before != after:
        findings.append(
            "il progetto demo NON e' byte-identico prima e dopo "
            "l'invocazione del motore")
    if (demo / STAGE10).exists():
        findings.append(
            f"la cartella {STAGE10}/ e' stata creata nel progetto demo")
    return findings, runs


def c24(ctx):
    """`FE-C-24` -- purezza di esecuzione: nessun path canonico scritto,
    nessun progetto mutato, nessuna cartella di Stage 10 creata."""
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_core_c24_") as base:
        base = Path(base)
        records = base_records(ctx)
        rows = base_rows(ctx, records)
        project, _ = make_project(ctx, base, name="c24")
        before = ctx["testkit"].snapshot_tree(project)
        run = run_engine(ctx, project, engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        after = ctx["testkit"].snapshot_tree(project)
        if before != after:
            changed = sorted(set(before) ^ set(after)) or sorted(
                key for key in before if before[key] != after.get(key))
            findings.append(
                f"snapshot del progetto NON byte-identico: {changed}")
        if (project / STAGE10).exists():
            findings.append(
                f"la cartella {STAGE10}/ e' stata creata nel progetto")
        for candidate in project.rglob("structured-output.json"):
            findings.append(
                f"output canonico scritto: {candidate.relative_to(project)}")
        # Caso NEGATIVO -- il motore RIFIUTA un `--engine-output` canonico.
        canonical = project / STAGE10 / "structured-output.json"
        command = [sys.executable, str(ctx["entry_point"]),
                   "--project", str(project), "--stage", STAGE10,
                   "--phase", "egress", "--candidate", str(project),
                   "--engine-input", "-",
                   "--engine-output", str(canonical)]
        proc = subprocess.run(
            command, input=json.dumps(engine_input(ctx, rows, records)),
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=str(ctx["root"]))
        if proc.returncode != 2:
            findings.append(
                f"caso negativo: un --engine-output su path canonico esce "
                f"{proc.returncode} invece di 2 (errore d'uso)")
        if canonical.exists():
            findings.append(
                "caso negativo: il motore ha SCRITTO il path canonico "
                f"{canonical}")
        if (project / STAGE10).exists():
            findings.append(
                f"caso negativo: la cartella {STAGE10}/ e' stata creata")
        final = ctx["testkit"].snapshot_tree(project)
        if final != before:
            findings.append(
                "snapshot del progetto mutato dal caso negativo")
    return findings, runs


def _projection_case(ctx, base, name, records, rows, config=None, **over):
    project, _ = make_project(ctx, base, name=name)
    payload = engine_input(ctx, rows, records, config=config, **over)
    return run_engine(ctx, project, payload)


def c25(ctx):
    """`FE-C-25` `T-FIN-ASSUMPTION-STATE-PRESERVED` -- stato delle assunzioni
    propagato per modulo e per piano, mai promosso."""
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_core_c25_") as base:
        base = Path(base)
        # Caso A -- nominale: tutti i driver `inferred`, PIU' un input
        # governato OPZIONALE CONSUMATO (`conversion_rate`) e un input del
        # registro NON CONSUMATO (`ops_capacity`).
        records = base_records(ctx)
        records["ASS-020"] = record(ctx["testkit"], 20, 0.5, "ratio",
                                    category="conversion")
        records["ASS-021"] = record(ctx["testkit"], 21, 4.0, "count",
                                    category="operations")
        rows = base_rows(ctx, records)
        rows.append(row(ctx, "DRV-020", "conversion_rate", "ASS-020", "ratio",
                        "rate", "monthly", "compound", "NOT_APPLICABLE",
                        records, scenario_polarity="revenue_like"))
        rows.append(row(ctx, "DRV-021", "ops_capacity", "ASS-021", "count",
                        "stock", "monthly", "carry_level", "constant", records,
                        start_period=0, end_period=11,
                        scenario_polarity="neutral"))
        consumed = [entry["driver_id"] for entry in rows
                    if entry["driver_id"] != "DRV-021"]
        run = _projection_case(ctx, base, "c25-a", records, rows,
                               consumed_by_engine=consumed)
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        plan = plan_of(run) or {}
        projection = projection_of(run) or {}
        modules = (plan.get("results") or {}).get("modules") or {}
        # COMPLETEZZA -- verificata INDIPENDENTEMENTE dal valore.
        produced = set(modules)
        projected = set((projection.get("modules") or {}))
        missing = sorted(produced - projected)
        orphan = sorted(projected - produced)
        if missing:
            findings.append(
                f"RED-4: moduli PRODOTTI e OMESSI da "
                f"governance_projection.modules: {missing}")
        if orphan:
            findings.append(
                f"RED-4: voci di proiezione prive del modulo corrispondente: "
                f"{orphan}")
        if produced and sorted(produced) != sorted(M4_ALL_MODULES):
            findings.append(
                f"moduli prodotti {sorted(produced)} diversi dai quattordici "
                f"del motore {sorted(M4_ALL_MODULES)}")
        # VALORE -- ciascuna voce porta il MINIMO dei propri riferimenti.
        status_by_driver = {}
        for driver in (plan.get("driver_registry") or {}).get("drivers") or []:
            status_by_driver[driver["driver_id"]] = driver["status"]
        for module_id, entry in sorted((projection.get("modules") or {}).items()):
            refs = entry.get("input_driver_refs") or []
            declared = entry.get("propagated_status")
            if declared not in STATUS_ORDER:
                findings.append(
                    f"{module_id}: propagated_status={declared!r} fuori "
                    "dall'enumerazione chiusa di driver_status")
                continue
            if not refs:
                continue
            minimum = min((status_by_driver.get(ref, "unresolved")
                           for ref in refs), key=STATUS_ORDER.index)
            if declared != minimum:
                lowering = [ref for ref in refs
                            if status_by_driver.get(ref) == minimum]
                findings.append(
                    f"RED-1: {module_id}: propagated_status={declared!r} "
                    f"invece del MINIMO {minimum!r}; i DRV che lo abbassano "
                    f"sono {lowering}")
            module_result = modules.get(module_id) or {}
            module_refs = set(module_result.get("input_driver_refs") or [])
            if module_refs and set(refs) != module_refs:
                findings.append(
                    f"{module_id}: input_driver_refs della proiezione "
                    f"{sorted(refs)} diversi da quelli del modulo "
                    f"{sorted(module_refs)}")
        # RED-3 -- nessun campo di stato dentro `module_result`.
        #
        # `break_even` e `kpi` NON sono `$defs/module_result`: lo schema
        # dichiara per ciascuno un oggetto PROPRIO e CHIUSO. Validarli
        # contro `module_result` misurerebbe lo schema sbagliato; ciascuno va
        # validato contro la PROPRIA forma, che resta `additionalProperties:
        # false` e quindi altrettanto stringente sul divieto di RED-3.
        for module_id, module_result in sorted(modules.items()):
            validate_ref(ctx, module_result, module_schema_pointer(module_id),
                         f"module_result[{module_id}]", findings)
            for key in ("propagated_status", "driver_status",
                        "assumption_status"):
                if key in module_result:
                    findings.append(
                        f"RED-3: {module_id}: il campo {key!r} e' stato "
                        "INSERITO dentro module_result: e' un delta di schema "
                        "mascherato")
        # Coerenza col livello di PIANO, e INSIEME esatto del minimo.
        plan_status = (projection.get("plan") or {}).get("propagated_status")
        canonical = (plan.get("validation") or {}).get("propagated_status")
        if plan_status != canonical:
            findings.append(
                f"RED-2: governance_projection.plan.propagated_status="
                f"{plan_status!r} diverso da validation.propagated_status="
                f"{canonical!r}")
        if plan_status != "inferred":
            findings.append(
                f"caso A: propagated_status di piano={plan_status!r} invece "
                "di 'inferred' sulla fixture")
        # La mappa degli scenari NON e' vuota. La sua SEMANTICA -- uno stato
        # PROPRIO per ciascuno scenario prodotto -- e' misurata SEPARATAMENTE
        # da `FS-C-19` in `test_fin_scenarios.py`: qui si misura solo che la
        # mappa esista, sia CHIUSA sui tre scenari e porti valori
        # dall'enumerazione chiusa.
        scenarios = projection.get("scenarios")
        if not isinstance(scenarios, dict) or \
                sorted(scenarios) != sorted(SCENARIO_IDS):
            findings.append(
                f"governance_projection.scenarios={scenarios!r}: la "
                f"mappa porta esattamente i tre scenari {sorted(SCENARIO_IDS)}")
        else:
            for scenario_id, entry in sorted(scenarios.items()):
                if entry.get("propagated_status") not in STATUS_ORDER:
                    findings.append(
                        f"scenarios[{scenario_id}]: propagated_status="
                        f"{entry.get('propagated_status')!r} fuori "
                        "dall'enumerazione chiusa di driver_status")
        # La proiezione NON porta numeri.
        blob = json.dumps(projection, sort_keys=True)
        for token in ("series", "amount", "metrics", "checksum"):
            if token in blob:
                findings.append(
                    f"la proiezione di governance contiene il token {token!r}: "
                    "porta STATO e RIFERIMENTI, mai quantita'")
        # Caso B -- l'input governato OPZIONALE CONSUMATO e' `placeholder`:
        # ABBASSA il minimo di PIANO, e il caveat resta VISIBILE.
        lowered = copy.deepcopy(records)
        lowered["ASS-020"].pop("evidence_classification", None)
        rows_b = copy.deepcopy(rows)
        for entry in rows_b:
            if entry["driver_id"] == "DRV-020":
                entry["status"] = "placeholder"
                entry["source_record_hash"] = ctx["fingerprint"](
                    lowered["ASS-020"])
        run_b = _projection_case(ctx, base, "c25-b", lowered, rows_b,
                                 consumed_by_engine=consumed)
        runs.append(run_b)
        projection_b = projection_of(run_b) or {}
        plan_b = plan_of(run_b) or {}
        status_b = (projection_b.get("plan") or {}).get("propagated_status")
        if status_b != "placeholder":
            findings.append(
                f"RED-2: con un input governato OPZIONALE CONSUMATO in stato "
                f"'placeholder' (DRV-020) il minimo di PIANO e' {status_b!r} "
                "invece di 'placeholder': il minimo e' calcolato sui soli "
                "input RICHIESTI")
        warnings_b = [w for w in ((plan_b.get("validation") or {}).get("warnings")
                                  or []) if w.get("code") == CODE_PLACEHOLDER_OPTIONAL]
        if not warnings_b:
            findings.append(
                f"RED-2: il caveat {CODE_PLACEHOLDER_OPTIONAL} non e' emesso "
                "per DRV-020: il caveat e' stato RIASSORBITO")
        elif not any("DRV-020" in (w.get("affected_refs") or [])
                     for w in warnings_b):
            findings.append(
                f"RED-2: {CODE_PLACEHOLDER_OPTIONAL} non attribuito a DRV-020")
        # Caso C -- l'input del registro NON CONSUMATO non partecipa.
        unconsumed = copy.deepcopy(records)
        unconsumed["ASS-021"].pop("evidence_classification", None)
        rows_c = copy.deepcopy(rows)
        for entry in rows_c:
            if entry["driver_id"] == "DRV-021":
                entry["status"] = "placeholder"
                entry["source_record_hash"] = ctx["fingerprint"](
                    unconsumed["ASS-021"])
        run_c = _projection_case(ctx, base, "c25-c", unconsumed, rows_c,
                                 consumed_by_engine=consumed)
        runs.append(run_c)
        projection_c = projection_of(run_c) or {}
        status_c = (projection_c.get("plan") or {}).get("propagated_status")
        if status_c != "inferred":
            findings.append(
                f"un input del registro NON CONSUMATO (DRV-021, placeholder) "
                f"abbassa il minimo di PIANO a {status_c!r}: la regola si e' "
                "rovesciata nella propria simmetrica")
        # Esclusione di falso positivo: tutte le REC-* sono verdi.
        recon = plan.get("reconciliations") or {}
        not_green = sorted(rec for rec, entry in recon.items()
                           if entry.get("status") not in ("PASS",
                                                          "NOT_APPLICABLE"))
        if not_green:
            findings.append(
                f"esclusione di falso positivo: le REC-* {not_green} non sono "
                "verdi sul caso A e il contratto perderebbe la propria "
                "specificita'")
    return findings, runs


def c26(ctx):
    """`FE-C-26` `T-FIN-ASSUMPTION-PROVENANCE` -- provenienza completa dei
    driver assunti e dei benchmark."""
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_core_c26_") as base:
        base = Path(base)
        records = base_records(ctx)
        rows = base_rows(ctx, records)
        project, _ = make_project(ctx, base, name="c26")
        run = run_engine(ctx, project, engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        plan = plan_of(run) or {}
        drivers = (plan.get("driver_registry") or {}).get("drivers") or []
        if not drivers:
            return ["driver_registry vuoto nel payload"], runs
        for driver in drivers:
            validate_ref(ctx, driver, "#/$defs/driver_entry",
                         f"driver_entry[{driver.get('driver_id')}]", findings)
            if driver.get("status") == "confirmed":
                continue
            for field in ("source_ref", "source_path", "source_record_hash",
                          "rationale", "confidence"):
                if not driver.get(field):
                    findings.append(
                        f"{driver.get('driver_id')}: campo di provenienza "
                        f"{field!r} assente su un driver non confirmed")
        # RED-1 -- driver assunto privo di `rationale`.
        no_rationale = copy.deepcopy(rows)
        for entry in no_rationale:
            if entry["driver_id"] == "DRV-004":
                entry.pop("rationale", None)
        project2, _ = make_project(ctx, base, name="c26-red1")
        red1 = run_engine(ctx, project2,
                          engine_input(ctx, no_rationale, records))
        runs.append(red1)
        attributed = errors_with(red1, CODE_UNRESOLVED_REQUIRED, "DRV-004")
        if not attributed:
            findings.append(
                f"RED-1: {CODE_UNRESOLVED_REQUIRED} non attribuito a DRV-004 "
                f"privo di rationale; osservati={sorted(red1['observed'])}")
        elif "rationale" not in (attributed[0].get("message") or ""):
            findings.append(
                "RED-1: il messaggio non NOMINA il campo mancante 'rationale'")
        # RED-2 -- benchmark `external_source` privo di `evidence_refs[]`.
        benchmark = copy.deepcopy(records)
        benchmark["ASS-004"]["evidence_classification"] = "external_source"
        bench_rows = copy.deepcopy(rows)
        for entry in bench_rows:
            if entry["driver_id"] == "DRV-004":
                entry["source_record_hash"] = ctx["fingerprint"](
                    benchmark["ASS-004"])
                entry["evidence_refs"] = []
        project3, _ = make_project(ctx, base, name="c26-red2")
        red2 = run_engine(ctx, project3,
                          engine_input(ctx, bench_rows, benchmark))
        runs.append(red2)
        attributed2 = errors_with(red2, CODE_UNRESOLVED_REQUIRED, "DRV-004")
        if not attributed2:
            findings.append(
                f"RED-2: {CODE_UNRESOLVED_REQUIRED} non attribuito a DRV-004 "
                f"benchmark senza evidence_refs; osservati="
                f"{sorted(red2['observed'])}")
        elif "evidence_refs" not in (attributed2[0].get("message") or ""):
            findings.append(
                "RED-2: il messaggio non NOMINA il campo mancante "
                "'evidence_refs'")
        if CODE_SOURCE_PATH in red2["observed"]:
            findings.append(
                f"RED-2: attribuzione VIETATA: {CODE_SOURCE_PATH} e' un "
                "codice del validator di binding e non soddisfa questo "
                "contratto")
        # Esclusione di falso positivo: il valore e' aritmeticamente corretto
        # e riconciliato, e il contratto fallisce lo stesso.
        recon2 = (plan_of(red2) or {}).get("reconciliations") or {}
        if recon2 and any(entry.get("status") == "FAIL"
                          for entry in recon2.values()):
            findings.append(
                "esclusione di falso positivo: una REC-* e' FAIL sul caso "
                "RED-2 e il contratto perderebbe la propria specificita'")
    return findings, runs


def c27(ctx):
    """`FE-C-27` `T-FIN-SOURCE-PRECEDENCE` -- precedenza delle fonti.

    CONVENZIONE DICHIARATA: `source_priority` e' un intero e la priorita' e'
    CRESCENTE, come nel validator di binding
    (`validate_financial_binding.check_cardinality_and_conflicts`, `top = max`).
    """
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_core_c27_") as base:
        base = Path(base)
        records = base_records(ctx)
        records["ASS-030"] = record(ctx["testkit"], 30, 90.0, "EUR/count",
                                    category="pricing",
                                    validation_status="validated",
                                    evidence_classification="verified_fact")
        rows = base_rows(ctx, records)
        for entry in rows:
            if entry["role"] == "unit_price":
                entry["source_priority"] = 6
                entry["status"] = "confirmed"
                entry["source_ref"] = "ASS-030"
                entry["source_record_hash"] = ctx["fingerprint"](
                    records["ASS-030"])
                entry["cardinality"] = "one"
        # Candidato di priorita' INFERIORE sullo stesso ruolo, senza DEC-*.
        challenger = row(ctx, "DRV-031", "unit_price", "ASS-001", "EUR/count",
                         "per_unit", "per_unit", "preserve_rate",
                         "NOT_APPLICABLE", records, source_priority=3,
                         cardinality="one")
        project, _ = make_project(ctx, base, name="c27")
        run = run_engine(ctx, project,
                         engine_input(ctx, rows + [challenger], records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        # POSITIVO -- la priorita' MAGGIORE vince, il perdente e' registrato
        # con `supersedes` e NESSUNA sovrascrittura silenziosa avviene.
        if errors_with(run, CODE_SOURCE_CONFLICT):
            findings.append(
                f"{CODE_SOURCE_CONFLICT} emesso su priorita' DISTINTE, dove "
                "la precedenza e' risolta e non conflittuale")
        plan = plan_of(run) or {}
        superseded = (plan.get("driver_registry") or {}).get("superseded") or []
        if not superseded:
            findings.append(
                "il candidato perdente non e' registrato con supersedes")
        else:
            entry = superseded[0]
            if entry.get("winner") != "DRV-001" or \
                    entry.get("supersedes") != "DRV-031":
                findings.append(
                    f"supersedes: vincitore={entry.get('winner')!r}, "
                    f"perdente={entry.get('supersedes')!r}: ha vinto il "
                    "candidato di priorita' INFERIORE")
            for key, value in (("winner_priority", 6),
                               ("superseded_priority", 3)):
                if entry.get(key) != value:
                    findings.append(
                        f"supersedes: {key}={entry.get(key)!r} invece di "
                        f"{value}: la priorita' di ENTRAMBI i candidati "
                        "dev'essere attribuita")
        # Il valore EFFETTIVAMENTE consumato e' quello del vincitore.
        revenue = modules_of(run).get("revenue") or {}
        expected = dec(records["ASS-030"]["value"]) * \
            dec(records["ASS-002"]["value"]) * \
            expected_survival(dec(records["ASS-003"]["value"]), 0,
                              month_fractions(12))
        if revenue and abs(series_of(revenue, 0) - expected) > Decimal("1e-6"):
            findings.append(
                f"periodo 0: revenue={series_of(revenue, 0)} invece di "
                f"{expected}: il motore consuma il valore del candidato di "
                "priorita' INFERIORE")
        # NEGATIVO -- priorita' PARI con riferimenti DISTINTI e senza DEC-*:
        # la scelta implicita e' VIETATA e il piano si BLOCCA.
        equal = copy.deepcopy(rows) + [copy.deepcopy(challenger)]
        for entry in equal:
            if entry["role"] == "unit_price":
                entry["source_priority"] = 6
        project2, _ = make_project(ctx, base, name="c27-equal")
        blocked = run_engine(ctx, project2, engine_input(ctx, equal, records))
        runs.append(blocked)
        attributed = errors_with(blocked, CODE_SOURCE_CONFLICT, "unit_price")
        if not attributed:
            findings.append(
                f"priorita' PARI con valori divergenti: "
                f"{CODE_SOURCE_CONFLICT} non attribuito al ruolo "
                f"'unit_price'; osservati={sorted(blocked['observed'])}")
        else:
            message = attributed[0].get("message") or ""
            for token in ("DRV-001", "DRV-031", "6"):
                if token not in message:
                    findings.append(
                        f"il messaggio di {CODE_SOURCE_CONFLICT} non NOMINA "
                        f"{token!r}: la priorita' di ENTRAMBI i candidati "
                        "dev'essere attribuita")
                    break
        if (plan_of(blocked) or {}).get("results", {}).get("modules"):
            findings.append(
                "priorita' PARI: il motore ha calcolato invece di bloccare")
        # Esclusione di falso positivo: il contratto fallisce anche quando i
        # due valori COINCIDONO entro tolleranza.
        same = copy.deepcopy(records)
        same["ASS-030"]["value"] = float(records["ASS-001"]["value"])
        same_rows = copy.deepcopy(rows) + [copy.deepcopy(challenger)]
        for entry in same_rows:
            if entry["driver_id"] == "DRV-001":
                entry["source_record_hash"] = ctx["fingerprint"](
                    same["ASS-030"])
            if entry["role"] == "unit_price":
                entry["source_priority"] = 6
        project3, _ = make_project(ctx, base, name="c27-same")
        identical = run_engine(ctx, project3,
                               engine_input(ctx, same_rows, same))
        runs.append(identical)
        if not errors_with(identical, CODE_SOURCE_CONFLICT):
            findings.append(
                "esclusione di falso positivo: con valori COINCIDENTI il "
                f"contratto non emette {CODE_SOURCE_CONFLICT}: misura lo "
                "scarto invece della REGOLA")
    return findings, runs


def c28(ctx):
    """`FE-C-28` `T-FIN-DERIVED-NOT-ASSUMABLE` -- un derivato si ricalcola,
    non si valida a mano."""
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_core_c28_") as base:
        base = Path(base)
        records = base_records(ctx)
        records["ASS-040"] = record(
            ctx["testkit"], 40, 60.0, "EUR/count", category="unit_economics",
            kind="derived",
            derivation={"method": "bottom_up", "strategy": "selected_ref",
                        "variables": {"price": "ASS-001",
                                      "cost": "ASS-004"},
                        "expression": "price - cost"})
        rows = base_rows(ctx, records)
        derived = row(ctx, "DRV-040", "variable_cost", "ASS-040", "EUR/count",
                      "per_unit", "per_unit", "preserve_rate",
                      "NOT_APPLICABLE", records, cardinality="many",
                      input_kind="derived", cost_category="operating_cost")
        for entry in rows:
            if entry["role"] == "variable_cost":
                entry["cardinality"] = "many"
        project, _ = make_project(ctx, base, name="c28")
        run = run_engine(ctx, project,
                         engine_input(ctx, rows + [derived], records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        passed = checks_with(run, CHECK_DERIVED, "PASS")
        if not passed:
            findings.append(
                f"il check {CHECK_DERIVED} non e' riportato sul caso nominale: "
                "un controllo che non compare equivale a un controllo non "
                "eseguito")
        # NEGATIVO -- l'output derivato e' marcato come assunzione EDITABILE.
        editable = copy.deepcopy(records)
        editable["ASS-040"]["validation_status"] = "needs_info"
        editable["ASS-040"]["validation_required"] = True
        neg_rows = copy.deepcopy(rows)
        neg_derived = copy.deepcopy(derived)
        neg_derived["source_record_hash"] = ctx["fingerprint"](
            editable["ASS-040"])
        project2, _ = make_project(ctx, base, name="c28-editable")
        negative = run_engine(ctx, project2,
                              engine_input(ctx, neg_rows + [neg_derived],
                                           editable))
        runs.append(negative)
        failed = checks_with(negative, CHECK_DERIVED, "FAIL")
        if not failed:
            findings.append(
                f"caso negativo: {CHECK_DERIVED} non e' FAIL su un derivato "
                f"marcato come assunzione editabile; osservati="
                f"{sorted(negative['observed'])}")
        else:
            entry = failed[0]
            refs = entry.get("affected_refs") or []
            if "DRV-040" not in refs:
                findings.append(
                    f"caso negativo: {CHECK_DERIVED} non attribuito a DRV-040")
            message = entry.get("message") or ""
            if "ASS-001" not in message and "derivation" not in message:
                findings.append(
                    "caso negativo: il messaggio non NOMINA la derivazione "
                    "del valore derivato")
        if CODE_INFORMATIONAL in negative["observed"]:
            findings.append(
                f"attribuzione VIETATA: {CODE_INFORMATIONAL} non soddisfa "
                "questo contratto")
        # Esclusione di falso positivo: la derivazione RICALCOLA esattamente
        # il valore e il contratto fallisce lo stesso.
        expected = dec(records["ASS-001"]["value"]) - \
            dec(records["ASS-004"]["value"])
        if dec(editable["ASS-040"]["value"]) != expected:
            findings.append(
                "esclusione di falso positivo: il derivato NON ricalcola "
                f"esattamente ({editable['ASS-040']['value']} != {expected}) e "
                "il contratto misurerebbe l'aritmetica invece della regola")
    return findings, runs


def c29(ctx):
    """`FE-C-29` `T-FIN-UNBOUND-ROLE-GATE` -- un ruolo richiesto non legato
    blocca il calcolo, senza valori di ripiego."""
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_core_c29_") as base:
        base = Path(base)
        records = base_records(ctx)
        rows = [entry for entry in base_rows(ctx, records)
                if entry["role"] != "opex"]
        project, _ = make_project(ctx, base, name="c29")
        run = run_engine(ctx, project, engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        if not errors_with(run, CODE_ROLE_UNBOUND, "opex"):
            findings.append(
                f"{CODE_ROLE_UNBOUND} non attribuito al RUOLO 'opex'; "
                f"osservati={sorted(run['observed'])}")
        if CODE_UNRESOLVED_REQUIRED in run["observed"]:
            findings.append(
                f"attribuzione VIETATA: {CODE_UNRESOLVED_REQUIRED} globale non "
                "soddisfa questo contratto")
        plan = plan_of(run) or {}
        modules = (plan.get("results") or {}).get("modules") or {}
        if modules:
            findings.append(
                f"il motore ha STIMATO invece di fallire: moduli prodotti="
                f"{sorted(modules)}; nessun valore, nessuno zero")
        unbound = (plan.get("driver_registry") or {}).get(
            "unbound_required_roles") or []
        if "opex" not in unbound:
            findings.append(
                f"unbound_required_roles={unbound!r} non NOMINA 'opex'")
        if run["exit_code"] != 1:
            findings.append(f"exit code {run['exit_code']} invece di 1")
        # POSITIVO -- con OGNI ruolo legato il gate non scatta.
        project2, _ = make_project(ctx, base, name="c29-bound")
        positive = run_engine(ctx, project2,
                              engine_input(ctx, base_rows(ctx, records),
                                           records))
        runs.append(positive)
        if CODE_ROLE_UNBOUND in positive["observed"]:
            findings.append(
                f"caso positivo: {CODE_ROLE_UNBOUND} emesso con ogni ruolo "
                "legato")
        if not (plan_of(positive) or {}).get("results", {}).get("modules"):
            findings.append(
                "caso positivo: nessun modulo prodotto con ogni ruolo legato")
    return findings, runs


def c30(ctx):
    """`FE-C-30` `T-FIN-READINESS-SEPARATION` -- esito di calcolo e stato
    propagato restano distinti."""
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_core_c30_") as base:
        base = Path(base)
        records = base_records(ctx)
        rows = base_rows(ctx, records)
        project, _ = make_project(ctx, base, name="c30")
        run = run_engine(ctx, project, engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        validation = (plan_of(run) or {}).get("validation") or {}
        result = validation.get("result")
        status = validation.get("propagated_status")
        if result is None:
            findings.append("validation.result assente")
        if status is None:
            findings.append("validation.propagated_status assente")
        if result in ("PASS", "WARNING") and status != "inferred":
            findings.append(
                f"con tutti i driver 'inferred' lo stato propagato e' "
                f"{status!r}: la prontezza di calcolo ha RIASSORBITO lo stato")
        if result == status:
            findings.append(
                f"result e propagated_status coincidono ({result!r}): le due "
                "grandezze sono collassate")
        # Il motore non dichiara la prontezza investor-ready.
        blob = json.dumps(plan_of(run) or {}, sort_keys=True)
        for token in ("investor_ready", "investor-ready", "investorReady"):
            if token in blob:
                findings.append(
                    f"il payload dichiara la prontezza {token!r}: non e' un "
                    "esito del motore finanziario")
        # NEGATIVO -- con un driver `placeholder` CONSUMATO il calcolo resta
        # possibile (result != FAIL su ruolo opzionale) e lo stato SCENDE.
        lowered = copy.deepcopy(records)
        lowered["ASS-020"] = record(ctx["testkit"], 20, 0.5, "ratio",
                                    category="conversion")
        lowered["ASS-020"].pop("evidence_classification", None)
        rows_b = copy.deepcopy(rows)
        rows_b.append(row(ctx, "DRV-020", "conversion_rate", "ASS-020",
                          "ratio", "rate", "monthly", "compound",
                          "NOT_APPLICABLE", lowered, status="placeholder",
                          scenario_polarity="revenue_like"))
        project2, _ = make_project(ctx, base, name="c30-lowered")
        negative = run_engine(ctx, project2,
                              engine_input(ctx, rows_b, lowered))
        runs.append(negative)
        neg_validation = (plan_of(negative) or {}).get("validation") or {}
        if neg_validation.get("result") == "FAIL":
            findings.append(
                "caso negativo: result=FAIL su un ruolo OPZIONALE placeholder: "
                "il gate fail-closed dei ruoli RICHIESTI e' stato esteso")
        if neg_validation.get("propagated_status") != "placeholder":
            findings.append(
                f"caso negativo: propagated_status="
                f"{neg_validation.get('propagated_status')!r} invece di "
                "'placeholder': lo stato e' DERIVATO da result")
        # Esclusione di falso positivo: tutte le REC-* verdi.
        recon = (plan_of(run) or {}).get("reconciliations") or {}
        not_green = sorted(rec for rec, entry in recon.items()
                           if entry.get("status") not in ("PASS",
                                                          "NOT_APPLICABLE"))
        if not_green:
            findings.append(
                f"esclusione di falso positivo: REC-* non verdi {not_green}")
    return findings, runs


#: Token di PRESENTAZIONE vietati in un ramo di calcolo, di gate o di stato.
PRESENTATION_TOKENS = frozenset({"orange", "fill", "style", "styles", "theme",
                                 "colour", "color", "rgb", "font", "fonts",
                                 "shading", "highlight"})

_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|[0-9]+")


def identifier_tokens(identifier):
    """Segmenta un identificatore in PAROLE, non in sottostringhe.

    La scansione a sottostringa sarebbe falsamente positiva su ogni prosa
    italiana (`informational` contiene `format`, `fonti` contiene `font`): un
    contratto che fallisce per una parola italiana non misura una dipendenza
    dalla presentazione. La segmentazione per parola misura esattamente cio'
    che la regola vieta: un identificatore DI RESA in un ramo di calcolo.
    """
    tokens = set()
    for part in str(identifier).replace("-", "_").split("_"):
        tokens |= {match.group(0).lower() for match in _WORD.finditer(part)}
    return tokens


def c31(ctx):
    """`FE-C-31` `T-FIN-NO-PRESENTATION-DEPENDENCY` -- nessuna dipendenza
    del calcolo dalla presentazione."""
    findings = []
    entry = ctx["entry_point"]
    if not entry.is_file():
        return [MISSING_CAPABILITY_REASON], []
    text, _, strings, names = _module_literals(entry)
    for line, value in names:
        hit = identifier_tokens(value) & PRESENTATION_TOKENS
        if hit:
            findings.append(
                f"{ENTRY_POINT_REL}:{line}: identificatore {value!r} porta il "
                f"token di presentazione {sorted(hit)} dentro un ramo di "
                "calcolo, un gate o uno stato")
    for line, value in strings:
        lowered = value.strip().lower()
        if lowered.startswith("#") and len(lowered) in (4, 7) and \
                all(char in "0123456789abcdef#" for char in lowered):
            findings.append(
                f"{ENTRY_POINT_REL}:{line}: letterale RGB {value!r} nel "
                "sorgente del motore")
        if lowered in PRESENTATION_TOKENS:
            findings.append(
                f"{ENTRY_POINT_REL}:{line}: letterale di presentazione "
                f"{value!r} nel sorgente del motore")
    # Caso POSITIVO della scansione: su un sorgente che CONTIENE un token la
    # scansione deve rilevarlo, altrimenti sarebbe vacua.
    probe = ast.parse("def render():\n    cell_style = 1\n    return cell_style\n")
    detected = [node.id for node in ast.walk(probe)
                if isinstance(node, ast.Name) and
                identifier_tokens(node.id) & PRESENTATION_TOKENS]
    if not detected:
        findings.append(
            "la scansione non rileva un token di presentazione nemmeno su un "
            "sorgente che lo contiene: la scansione e' vacua")
    if identifier_tokens("informational") & PRESENTATION_TOKENS:
        findings.append(
            "la scansione e' falsamente positiva sulla parola "
            "'informational': misura sottostringhe invece che parole")
    del text
    return findings, []


# --------------------------------------------------------------------------
# Break-even, KPI, fabbisogno e confine con lo Stage 11
# --------------------------------------------------------------------------
#
# I contratti di scenario `FS-C-01` ... `FS-C-07` e `FS-C-19` vivono in
# `tests/integration/test_fin_scenarios.py`. Qui vivono `T-FIN-BREAK-EVEN`,
# `T-FIN-KPI`, `T-FIN-FUNDING-GAP` e la proiezione di governance `FS-C-20`,
# piu' i contratti che misurano il motore e non gli scenari: `FS-C-15`
# (tolleranza estesa), `FS-C-17` (confine Stage 11), `FS-C-18` (determinismo
# PER SCENARIO).


def module_series(module):
    """La serie di un `module_result`, come mappa periodo -> `Decimal`."""
    series = (module or {}).get("series") or {}
    return {int(key): Decimal(str(value)) for key, value in series.items()}


def break_even_case(ctx, base, name, **over):
    records = base_records(ctx, **over)
    rows = base_rows(ctx, records)
    project, _ = make_project(ctx, base, name=name)
    return run_engine(ctx, project, engine_input(ctx, rows, records)), records


def c_m4_08(ctx):
    """`FS-C-08` `T-FIN-BREAK-EVEN` -- esito del pareggio DICHIARATO,
    `REC-15`.

    RED-1  break-even calcolato con margine unitario <= 0 SENZA dichiararlo
    RED-2  pareggio fuori orizzonte riportato come RAGGIUNTO
    """
    findings = []
    runs = []
    horizon = 12
    with tempfile.TemporaryDirectory(prefix="fin_ext_c08_") as base:
        base = Path(base)
        # ---- caso NOT_REACHED: margine positivo, pareggio fuori orizzonte --
        run, records = break_even_case(ctx, base, "c08-not-reached")
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        module = modules_of(run).get("break_even")
        if not module:
            return ["modulo break_even assente dal payload"], runs
        validate_ref(ctx, module,
                     "#/properties/financial_plan/properties/results/"
                     "properties/modules/properties/break_even",
                     "break_even", findings)
        price = dec(records["ASS-001"]["value"])
        variable = dec(records["ASS-004"]["value"])
        payroll_unit = dec(records["ASS-006"]["value"])
        heads = dec(records["ASS-005"]["value"])
        opex = dec(records["ASS-007"]["value"])
        expected_margin = price - variable
        expected_fixed = heads * payroll_unit + opex / Decimal(horizon)
        if dec(module.get("unit_margin")) != expected_margin:
            findings.append(
                f"unit_margin={module.get('unit_margin')!r} invece di "
                f"{expected_margin} (= prezzo {price} - costo variabile "
                f"{variable})")
        fixed = {int(k): Decimal(str(v)) for k, v in
                 (module.get("fixed_costs_per_period") or {}).items()}
        if len(fixed) != horizon:
            findings.append(
                f"fixed_costs_per_period ha {len(fixed)} periodi invece di "
                f"{horizon}: i costi fissi sono un PROFILO, non uno scalare")
        elif fixed.get(0) != expected_fixed:
            findings.append(
                f"fixed_costs_per_period[0]={fixed.get(0)} invece di "
                f"{expected_fixed} (= payroll {heads * payroll_unit} + quota "
                f"opex {opex / Decimal(horizon)})")
        if module.get("outcome") != "NOT_REACHED":
            findings.append(
                f"RED-2: outcome={module.get('outcome')!r} invece di "
                "'NOT_REACHED': con margine lordo per periodo sotto i costi "
                "fissi il pareggio NON e' raggiunto nell'orizzonte, e "
                "riportarlo come raggiunto e' un difetto")
        if module.get("first_break_even_period") is not None:
            findings.append(
                f"RED-2: first_break_even_period="
                f"{module.get('first_break_even_period')!r} su un caso "
                "NOT_REACHED: il primo periodo POSITIVO non e' il pareggio")
        # L'esito e' DICHIARATO: `outcome` esiste sempre, mai un `null` muto.
        if "outcome" not in module:
            findings.append(
                "outcome ASSENTE: first_break_even_period null senza outcome "
                "non soddisfa il contratto (attribuzione vietata)")
        # ---- caso REACHED: volume tale da superare i costi fissi -----------
        reached_run, _ = break_even_case(ctx, base, "c08-reached", volume="200")
        runs.append(reached_run)
        reached = modules_of(reached_run).get("break_even") or {}
        if reached.get("outcome") != "REACHED":
            findings.append(
                f"caso REACHED: outcome={reached.get('outcome')!r} invece di "
                "'REACHED' con margine lordo sopra i costi fissi")
        if reached.get("first_break_even_period") is None:
            findings.append(
                "caso REACHED: first_break_even_period assente benche' "
                "l'esito sia REACHED")
        # ---- RED-1: margine unitario <= 0 ----------------------------------
        na_run, _ = break_even_case(ctx, base, "c08-not-reachable",
                                    variable_cost="140")
        runs.append(na_run)
        na = modules_of(na_run).get("break_even") or {}
        if na.get("outcome") != "NOT_REACHABLE":
            findings.append(
                f"RED-1: outcome={na.get('outcome')!r} con margine unitario "
                "<= 0: il pareggio e' NON RAGGIUNGIBILE e va DICHIARATO, mai "
                "calcolato in silenzio")
        if na.get("break_even_volume") is not None:
            findings.append(
                f"RED-1: break_even_volume={na.get('break_even_volume')!r} "
                "emesso con margine unitario <= 0: una divisione per un "
                "margine non positivo non produce un pareggio")
        if not na.get("not_applicable_reason") and na.get("status") == \
                "NOT_APPLICABLE":
            findings.append(
                "RED-1: status NOT_APPLICABLE senza not_applicable_reason")
        # Esclusione di falso positivo: il contratto fallisce anche con
        # `REC-15` VERDE su un caso REACHED.
        rec15 = ((plan_of(reached_run) or {}).get("reconciliations")
                 or {}).get("REC-15") or {}
        if rec15.get("status") != "PASS":
            findings.append(
                "esclusione di falso positivo: REC-15 non e' PASS sul caso "
                "REACHED; il contratto perderebbe la propria specificita'")
    return findings, runs


def c_m4_09(ctx):
    """`FS-C-09` `T-FIN-KPI` -- set minimo di otto KPI, sempre presenti.

    RED  un KPI privo di driver OMESSO dal report.
    Tutti e OTTO gli indicatori sono presenti; quello non calcolabile e'
    `NOT_APPLICABLE` con `missing_driver_roles` NOMINATI.
    """
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_ext_c09_") as base:
        base = Path(base)
        records = base_records(ctx)
        rows = base_rows(ctx, records)
        project, _ = make_project(ctx, base, name="c09")
        run = run_engine(ctx, project, engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        _kpi_inspection(ctx, run, rows, records, "nominale", findings)
        indicators = ((modules_of(run).get("kpi") or {}).get("indicators")
                      or {})
        # I due indicatori che il profilo attivo NON puo' calcolare sono
        # NOMINATI: `cac` (nessun ruolo di acquisizione nel profilo) e
        # `milestone_coverage` (modulo non prodotto dal motore).
        for kpi_id in ("cac", "ltv_cac_ratio", "milestone_coverage"):
            entry = indicators.get(kpi_id) or {}
            if entry.get("status") != "NOT_APPLICABLE":
                findings.append(
                    f"{kpi_id}: status={entry.get('status')!r} invece di "
                    "NOT_APPLICABLE: il profilo subscription_saas non lega "
                    "alcun driver che lo renda calcolabile")
        # ---- CASI AVVERSARI: ruoli legati nominati come mancanti ----------
        # (a) OGNI ruolo richiesto LEGATO e CONSUMATO -- incluso quello che il
        #     modulo `break_even` usa -- e il pareggio NON raggiunto entro
        #     l'orizzonte: la ragione e' FINANZIARIA, e nessun ruolo legato puo'
        #     comparire come mancante.
        # (b) margine unitario <= 0: il pareggio non e' RAGGIUNGIBILE.
        for position, (label, over) in enumerate((
                ("(a) pareggio NON RAGGIUNTO, 7/7 ruoli legati", {}),
                ("(b) margine unitario <= 0",
                 {"price": "40", "variable_cost": "40"}))):
            case_records = base_records(ctx, **over)
            case_rows = base_rows(ctx, case_records)
            project_a, _ = make_project(ctx, base,
                                        name=f"c09-adversarial-{position}")
            case_run = run_engine(ctx, project_a,
                                  engine_input(ctx, case_rows, case_records))
            runs.append(case_run)
            _kpi_inspection(ctx, case_run, case_rows, case_records, label,
                            findings)
            case_kpi = ((modules_of(case_run).get("kpi") or {})
                        .get("indicators") or {})
            outcome = (modules_of(case_run).get("break_even")
                       or {}).get("outcome")
            entry = case_kpi.get("break_even_period") or {}
            if entry.get("status") == "NOT_APPLICABLE" and \
                    entry.get("missing_driver_roles"):
                findings.append(
                    f"{label}: break_even_period nomina "
                    f"{entry.get('missing_driver_roles')} mentre il modulo "
                    f"break_even dello STESSO payload dichiara "
                    f"outcome={outcome!r}: i due blocchi si CONTRADDICONO e la "
                    "ragione finanziaria e' soppressa da un input che non manca")
            if entry.get("status") == "NOT_APPLICABLE" and \
                    str(outcome) not in str(entry.get("notes") or ""):
                findings.append(
                    f"{label}: break_even_period NOT_APPLICABLE senza citare "
                    f"outcome={outcome!r} del modulo break_even: la ragione "
                    "DICHIARATA non e' quella vera")
        # (c) UN ruolo NON legato -- `cac` -- e SETTE ruoli legati. Il ruolo
        #     mancante puo' comparire SOLTANTO negli indicatori che DIPENDONO da
        #     esso: un elenco GLOBALE lo farebbe comparire ovunque, ed e'
        #     esattamente la differenza fra un insieme per KPI e una lista
        #     copiata. `break_even_period` usa `variable_cost`, che e' LEGATO e
        #     CONSUMATO nello stesso payload, e non puo' nominarlo.
        for kpi_id, entry in sorted(indicators.items()):
            named = set(entry.get("missing_driver_roles") or [])
            dependencies = set(KPI_DEPENDENCIES.get(kpi_id) or ())
            if "cac" in named and "cac" not in dependencies:
                findings.append(
                    f"(c) {kpi_id}: missing_driver_roles nomina 'cac', che non "
                    "appartiene al suo insieme di dipendenza: l'elenco e' "
                    "GLOBALE e non SPECIFICO per KPI")
            if kpi_id in ("cac", "ltv_cac_ratio") and "cac" not in named:
                findings.append(
                    f"(c) {kpi_id}: dipende da 'cac', che NON e' legato in "
                    f"questo payload, e non lo nomina: missing={sorted(named)}")
            if "variable_cost" in named:
                findings.append(
                    f"(c) {kpi_id}: nomina 'variable_cost', che e' LEGATO e "
                    "CONSUMATO (DRV-004) nello stesso payload")
        # ---- CASI AVVERSARI: ruolo legato ma inutilizzabile ---------------
        # (d) ruolo LEGATO ma INUTILIZZABILE, con OGNI dipendenza legata:
        #     `churn_rate` e' legato a DRV-003 e vale ZERO. La vita media
        #     diverge, quindi `ltv` NON e' calcolabile -- ma il dato NON manca.
        # (e) caso MISTO: `cac` GENUINAMENTE ASSENTE e `churn_rate` LEGATO a
        #     zero convivono su `ltv_cac_ratio`. E' il caso in cui una lista
        #     sola renderebbe i due fatti INDISTINGUIBILI.
        zero_churn = base_records(ctx, volume="200", churn="0")
        zero_churn["ASS-040"] = record(ctx["testkit"], 40, 250.0, "EUR/count",
                                       category="acquisition")
        zero_rows = base_rows(ctx, zero_churn)
        zero_rows.append(row(ctx, "DRV-040", "cac", "ASS-040", "EUR/count",
                             "per_unit", "per_unit", "preserve_rate",
                             "NOT_APPLICABLE", zero_churn,
                             scenario_polarity="cost_like"))
        mixed_records = base_records(ctx, churn="0")
        mixed_rows = base_rows(ctx, mixed_records)
        for label, case_rows, case_records, targets in (
                ("(d) churn_rate LEGATO a ZERO, 8/8 ruoli legati",
                 zero_rows, zero_churn, ("ltv", "ltv_cac_ratio")),
                ("(e) MISTO: cac ASSENTE + churn_rate LEGATO a ZERO",
                 mixed_rows, mixed_records, ("ltv", "ltv_cac_ratio"))):
            project_u, _ = make_project(
                ctx, base, name=f"c09-unusable-{len(runs)}")
            case_run = run_engine(ctx, project_u,
                                  engine_input(ctx, case_rows, case_records))
            runs.append(case_run)
            _kpi_inspection(ctx, case_run, case_rows, case_records, label,
                            findings)
            case_kpi = ((modules_of(case_run).get("kpi") or {})
                        .get("indicators") or {})
            bound = {entry["role"] for entry in case_rows}
            for kpi_id in targets:
                entry = case_kpi.get(kpi_id) or {}
                named = set(entry.get("missing_driver_roles") or [])
                if entry.get("status") != "NOT_APPLICABLE":
                    findings.append(
                        f"{label}: {kpi_id} status={entry.get('status')!r}: "
                        "una dipendenza LEGATA ma INUTILIZZABILE rende "
                        "l'indicatore non calcolabile")
                if "churn_rate" in named:
                    findings.append(
                        f"{label}: {kpi_id}: 'churn_rate' e' LEGATO a "
                        "DRV-003 e nominato MANCANTE: il dato non manca, e' "
                        "il suo VALORE a non servire")
                if named & bound:
                    findings.append(
                        f"{label}: {kpi_id}: missing_driver_roles nomina "
                        f"ruoli LEGATI {sorted(named & bound)}")
            ratio_entry = case_kpi.get("ltv_cac_ratio") or {}
            ratio_named = set(ratio_entry.get("missing_driver_roles") or [])
            ratio_note = ratio_entry.get("notes") or ""
            expected_named = {"cac"} - bound
            if ratio_named != expected_named:
                findings.append(
                    f"{label}: ltv_cac_ratio: missing_driver_roles="
                    f"{sorted(ratio_named)} invece di "
                    f"{sorted(expected_named)}: il campo deve portare i soli "
                    "ruoli ASSENTI")
            if "churn_rate" not in ratio_note:
                findings.append(
                    f"{label}: ltv_cac_ratio: la nota tipizzata non nomina "
                    f"'churn_rate' (notes={ratio_note!r}): l'unico portatore "
                    "della distinzione fra ASSENTE e INUTILIZZABILE manca")
        # ---- OGNI dipendenza disponibile => KPI CALCOLATO ------------------
        full = base_records(ctx, volume="200")
        full["ASS-040"] = record(ctx["testkit"], 40, 250.0, "EUR/count",
                                 category="acquisition")
        full_rows = base_rows(ctx, full)
        full_rows.append(row(ctx, "DRV-040", "cac", "ASS-040", "EUR/count",
                             "per_unit", "per_unit", "preserve_rate",
                             "NOT_APPLICABLE", full,
                             scenario_polarity="cost_like"))
        project_f, _ = make_project(ctx, base, name="c09-complete")
        complete = run_engine(ctx, project_f,
                              engine_input(ctx, full_rows, full))
        runs.append(complete)
        _kpi_inspection(ctx, complete, full_rows, full, "dipendenze COMPLETE",
                        findings)
        complete_kpi = ((modules_of(complete).get("kpi") or {})
                        .get("indicators") or {})
        for kpi_id in ("cac", "ltv", "ltv_cac_ratio", "break_even_period"):
            entry = complete_kpi.get(kpi_id) or {}
            if entry.get("status") != "PASS":
                findings.append(
                    f"dipendenze COMPLETE: {kpi_id} status="
                    f"{entry.get('status')!r} con OGNI ruolo del proprio "
                    "insieme di dipendenza LEGATO e utilizzabile: un "
                    "indicatore calcolabile e' CALCOLATO, non NOT_APPLICABLE "
                    f"(missing={entry.get('missing_driver_roles')!r})")
    return findings, runs


#: L'insieme di dipendenza PROPRIO di ciascun indicatore, DICHIARATO
#: qui in modo INDIPENDENTE dal motore: se il motore lo cambiasse, il contratto
#: non lo seguirebbe. E' il metro rispetto al quale un ruolo NOMINATO come
#: mancante e' giudicato pertinente a QUELL'indicatore.
KPI_DEPENDENCIES = {
    "gross_margin_pct": ("unit_price", "customer_volume"),
    "monthly_burn": (),
    "runway": (),
    "cac": ("cac",),
    "ltv": ("unit_price", "customer_volume", "churn_rate"),
    "ltv_cac_ratio": ("unit_price", "customer_volume", "churn_rate", "cac"),
    "break_even_period": ("unit_price", "customer_volume", "variable_cost"),
    "milestone_coverage": ("milestone_cost",),
}


#: I marcatori che una spiegazione TIPIZZATA di
#: inutilizzabilita' DEVE portare. Non sono il testo della nota: sono le tre
#: cose che la nota deve DIRE — che il ruolo e' LEGATO, quale CONDIZIONE e'
#: stata osservata, e perche' il KPI non e' calcolabile. Cercarli e' piu'
#: debole che riscrivere la nota qui, ed e' precisamente cio' che serve:
#: il contratto misura la SOSTANZA dichiarata, non la formulazione.
UNUSABLE_NOTE_MARKERS = ("LEGATO", "INUTILIZZABILE", "OSSERVAT")


def _unusable_roles(rows, records):
    """I ruoli LEGATI il cui VALORE rende un indicatore indefinito.

    Sono INUTILIZZABILI, il che e' un fatto diverso dall'ASSENZA e altrettanto
    vero. Un ruolo inutilizzabile NON e' un ruolo mancante: il dato c'e'.
    L'harness li deriva dai record DICHIARATI, non da un elenco del motore, ed
    e' rispetto a questa derivazione INDIPENDENTE che `FS-C-09` esige la
    distinzione tipizzata fra ruolo assente e ruolo inutilizzabile.
    """
    by_role = {entry["role"]: entry for entry in rows}
    unusable = {}

    def declared(role):
        entry = by_role.get(role)
        if entry is None:
            return None
        value = (records.get(entry["source_ref"]) or {}).get("value")
        return None if value is None else Decimal(str(value))

    churn = declared("churn_rate")
    if churn is not None and churn <= Decimal(0):
        unusable.setdefault("ltv", set()).add("churn_rate")
        unusable.setdefault("ltv_cac_ratio", set()).add("churn_rate")
    cac = declared("cac")
    if cac is not None and cac <= Decimal(0):
        unusable.setdefault("ltv_cac_ratio", set()).add("cac")
    return {kpi_id: tuple(sorted(roles))
            for kpi_id, roles in unusable.items()}


def _kpi_inspection(ctx, run, rows, records, label, findings):
    """Ispezione del blocco KPI di UN payload di produzione.

    Misura DUE proprieta': la COMPLETEZZA del set minimo di otto, e la
    VERIDICITA' di `missing_driver_roles`. Un ruolo LEGATO e CONSUMATO nello
    stesso payload NON e' mancante: nominarlo sopprime la ragione finanziaria
    reale e contraddice il modulo che la dichiara nello stesso risultato.
    """
    module = modules_of(run).get("kpi")
    if not module:
        findings.append(f"{label}: modulo kpi assente dal payload")
        return
    bound_roles = {entry["role"]: entry["driver_id"] for entry in rows}
    unusable_roles = _unusable_roles(rows, records)
    validate_ref(ctx, module,
                     "#/properties/financial_plan/properties/results/"
                     "properties/modules/properties/kpi", "kpi", findings)
    indicators = module.get("indicators") or {}
    # RED -- l'OMISSIONE e' il difetto, e va misurata per NOME.
    omitted = [kpi_id for kpi_id in KPI_IDS if kpi_id not in indicators]
    if omitted:
        findings.append(
            f"RED: indicatori OMESSI dal report: {omitted}. Un indicatore "
            "assente si legge 'non pertinente' mentre la verita' e' 'non "
            "abbiamo il dato': va dichiarato NOT_APPLICABLE, mai omesso")
    extra = [kpi_id for kpi_id in indicators if kpi_id not in KPI_IDS]
    if extra:
        findings.append(
            f"indicatori FUORI dal set minimo di otto: {extra}")
    for kpi_id in KPI_IDS:
        entry = indicators.get(kpi_id)
        if not isinstance(entry, dict):
            continue
        validate_ref(ctx, entry, "#/$defs/kpi_indicator",
                     f"kpi.{kpi_id}", findings)
        if entry.get("kpi_id") != kpi_id:
            findings.append(
                f"{kpi_id}: kpi_id={entry.get('kpi_id')!r} non attribuito")
        if entry.get("status") == "NOT_APPLICABLE":
            roles = entry.get("missing_driver_roles")
            if roles is None:
                findings.append(
                    f"{kpi_id}: status NOT_APPLICABLE SENZA la chiave "
                    "missing_driver_roles: e' esattamente l'attribuzione "
                    "vietata dal contratto")
            elif not roles and not entry.get("notes"):
                findings.append(
                    f"{kpi_id}: NOT_APPLICABLE senza alcun ruolo mancante "
                    "e senza RAGIONE dichiarata: l'indicatore non e' "
                    "calcolabile e il report non dice perche'")
            # Ogni ruolo NOMINATO dev'essere GENUINAMENTE non disponibile
            # per QUESTO indicatore: un ruolo LEGATO e CONSUMATO nello
            # stesso payload non e' mancante, e nominarlo sopprime la
            # ragione vera sostituendola con un input che non manca.
            for role in roles or []:
                if role not in (KPI_DEPENDENCIES.get(kpi_id) or ()):
                    findings.append(
                        f"{label}: {kpi_id}: missing_driver_roles nomina "
                        f"{role!r}, che non appartiene all'insieme di "
                        "dipendenza di QUESTO indicatore: l'elenco e' GLOBALE "
                        "e non SPECIFICO per KPI")
                if role not in bound_roles:
                    continue
                # NESSUNA esenzione. Un ruolo LEGATO non puo'
                # comparire fra i MANCANTI, nemmeno quando e' inutilizzabile:
                # la sua inutilizzabilita' e' un fatto DIVERSO, e il suo
                # portatore e' la nota TIPIZZATA, non questa lista.
                findings.append(
                    f"{label}: {kpi_id}: missing_driver_roles nomina "
                    f"{role!r}, che e' LEGATO e CONSUMATO in questo payload "
                    f"(driver {bound_roles[role]}). Il ruolo e' scelto per "
                    "POSIZIONE invece che per ASSENZA, e la ragione "
                    "finanziaria reale e' SOPPRESSA")
            # ---- ASSENZA e INUTILIZZABILITA' distinte -------------------------
            # L'insieme dei MANCANTI e' derivato INDIPENDENTEMENTE dai ruoli
            # che il payload NON lega: dev'essere ESATTAMENTE quello. Ne segue
            # che un ruolo legato-ma-inutilizzabile non puo' nascondervisi, e
            # che nel caso MISTO i due fatti restano su portatori DIVERSI.
            absent = tuple(role for role in KPI_DEPENDENCIES.get(kpi_id) or ()
                           if role not in bound_roles)
            if sorted(set(roles or [])) != sorted(absent):
                findings.append(
                    f"{label}: {kpi_id}: missing_driver_roles="
                    f"{sorted(set(roles or []))} mentre i ruoli GENUINAMENTE "
                    f"ASSENTI dal payload sono {sorted(absent)}: il campo "
                    "significa ASSENZA e non puo' portare altro")
            note = entry.get("notes") or ""
            for role in unusable_roles.get(kpi_id, ()):
                if role in (roles or []):
                    findings.append(
                        f"{label}: {kpi_id}: il ruolo {role!r} e' LEGATO ma "
                        "INUTILIZZABILE e compare in missing_driver_roles "
                        f"insieme ai ruoli ASSENTI {sorted(absent)}: i due "
                        "fatti sono FUSI in una lista sola e un lettore a "
                        "valle non puo' distinguerli")
                if role not in note:
                    findings.append(
                        f"{label}: {kpi_id}: il ruolo {role!r} e' LEGATO ma "
                        "INUTILIZZABILE e nessuna spiegazione TIPIZZATA lo "
                        f"nomina (notes={note!r}): la distinzione fra 'non "
                        "abbiamo il dato' e 'il dato c'e' e non serve' non "
                        "esiste nel payload")
                    continue
                absent_markers = [marker for marker in UNUSABLE_NOTE_MARKERS
                                  if marker not in note]
                if absent_markers:
                    findings.append(
                        f"{label}: {kpi_id}: la nota su {role!r} non dichiara "
                        f"{absent_markers}: una spiegazione tipizzata deve "
                        "dire che il ruolo e' LEGATO, quale CONDIZIONE e' "
                        "stata OSSERVATA e perche' il KPI non e' calcolabile")
        elif entry.get("status") == "PASS":
            if entry.get("value") is None and not entry.get("series"):
                findings.append(
                    f"{kpi_id}: status PASS senza value ne' series")
            if not entry.get("recomputable_from"):
                findings.append(
                    f"{kpi_id}: PASS senza recomputable_from: ogni KPI "
                    "dev'essere RICALCOLABILE dagli output "
                    "dichiarati")
    # Il modulo esiste SEMPRE: e' il suo CONTENUTO a ridursi.
    if module.get("status") == "NOT_APPLICABLE":
        findings.append(
            f"{label}: il modulo kpi e' NOT_APPLICABLE: il modulo "
            "esiste sempre e si riduce soltanto il suo "
            "contenuto")


def c_m4_10(ctx):
    """`FS-C-10` `T-FIN-FUNDING-GAP` -- fabbisogno residuo come serie, mai
    una fonte.

    RED-1  gap NEGATIVO
    RED-2  gap conteggiato FRA LE FONTI          -> `funding_gap_as_source`
    RED-3  `financial_need` SCALARE identico a `funding_gap_to_buffer`
    """
    findings = []
    runs = []
    horizon = 12
    with tempfile.TemporaryDirectory(prefix="fin_ext_c10_") as base:
        base = Path(base)
        records = base_records(ctx)
        rows = base_rows(ctx, records)
        config = financial_config(
            ctx, cash_buffer_policy={"kind": "absolute", "value": 20000})
        project, _ = make_project(ctx, base, name="c10gap")
        run = run_engine(ctx, project,
                         engine_input(ctx, rows, records, config=config))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        module = modules_of(run).get("funding_gap")
        if not module:
            return ["modulo funding_gap assente dal payload"], runs
        validate_ref(ctx, module, "#/$defs/module_result", "funding_gap",
                     findings)
        # RED-3 -- `financial_need` e' una SERIE per periodo, mai uno scalare.
        need = module_series(module)
        if len(need) != horizon:
            findings.append(
                f"RED-3: financial_need ha {len(need)} valori invece di "
                f"{horizon}: e' il PROFILO TEMPORALE del "
                "fabbisogno residuo, e una serie non e' uno scalare")
        to_zero = metric_of(module, "funding_gap_to_zero")
        to_buffer = metric_of(module, "funding_gap_to_buffer")
        if to_zero is None or to_buffer is None:
            findings.append(
                "funding_gap_to_zero e funding_gap_to_buffer sono i DUE "
                "riassunti scalari del fabbisogno: mancano dalle metriche "
                f"(to_zero={to_zero!r}, to_buffer={to_buffer!r})")
        else:
            # RED-1 -- il gap non e' mai negativo: e' `max(0, ...)`.
            for label, value in (("funding_gap_to_zero", to_zero),
                                 ("funding_gap_to_buffer", to_buffer)):
                if value != "NOT_APPLICABLE" and dec(value) < Decimal(0):
                    findings.append(
                        f"RED-1: {label}={value!r} NEGATIVO: il fabbisogno e' "
                        "max(0, ...), mai un avanzo col segno meno")
            # RED-4 -- i DUE riassunti scalari sono calcolati da DUE soglie
            # distinte. Il contratto non misura la loro DISUGUAGLIANZA -- che
            # su un piano valido puo' benissimo non esserci -- ma la
            # PROVENIENZA: ciascuno coincide col ricalcolo INDIPENDENTE
            # dell'harness dalla PROPRIA soglia. Un riassunto SOSTITUITO con
            # l'altro non vi coincide.
            cash = modules_of(run).get("cash_flow") or {}
            ending = [dec(metric_of(cash, f"ending_{index}"))
                      for index in range(horizon)]
            for label, value, limit in (
                    ("funding_gap_to_zero", to_zero, Decimal(0)),
                    ("funding_gap_to_buffer", to_buffer, Decimal(20000))):
                expected = expected_funding_gap(ending, limit)
                if value == "NOT_APPLICABLE":
                    findings.append(
                        f"RED-4: {label}='NOT_APPLICABLE' con la policy di "
                        "buffer DICHIARATA")
                elif dec(value) != expected:
                    findings.append(
                        f"RED-4: {AMB_W2_04}: {label}={value!r} invece di "
                        f"{expected}, che e' il valore prodotto dalla PROPRIA "
                        "soglia sul minimo della stessa serie di cassa: il "
                        "riassunto e' SOSTITUITO con quello dell'altra soglia "
                        "o derivato dalla definizione sbagliata")
            if AMB_W2_04 in run["observed"]:
                findings.append(
                    f"{AMB_W2_04} emesso sul caso nominale, dove ciascuno dei "
                    "due riassunti proviene dalla propria soglia")
            # RED-3, attribuzione VIETATA: la sola PRESENZA di
            # `funding_gap_to_zero` non soddisfa il contratto; cio' che lo
            # soddisfa e' che `financial_need` sia una SERIE, e per un buffer
            # positivo la serie non puo' collassare sullo scalare.
            if len(need) == 1 and to_buffer != "NOT_APPLICABLE" and \
                    dec(next(iter(need.values()))) == dec(to_buffer):
                findings.append(
                    "RED-3: financial_need coincide con lo SCALARE "
                    "funding_gap_to_buffer: non deve coincidere, "
                    "perche' una serie non e' uno scalare")
        for index in sorted(need):
            if need[index] < Decimal(0):
                findings.append(
                    f"RED-1: financial_need[{index}]={need[index]} negativo: "
                    "il fabbisogno residuo e' max(0, ...)")
                break
        # `funding_gap` non e' ne' fonte ne' uso: nessuna riga categorizzata.
        for line in module.get("lines") or []:
            findings.append(
                f"funding_gap emette la riga categorizzata "
                f"{line.get('line_id')!r} in categoria "
                f"{line.get('category')!r}: funding_gap e' escluso dalla "
                "tassonomia di fonti e usi, ed e' un RESIDUO")
        if CODE_GAP_AS_SOURCE in run["observed"]:
            findings.append(
                f"{CODE_GAP_AS_SOURCE} presente sul caso nominale, dove il "
                "gap NON e' dichiarato fra le fonti")
        # ---- RED-2: il gap DICHIARATO fra le fonti -------------------------
        as_source = copy.deepcopy(rows)
        records["ASS-009"] = record(ctx["testkit"], 9, 30000.0, "EUR",
                                    category="finance")
        as_source.append(row(ctx, "DRV-009", "cash_buffer", "ASS-009", "EUR",
                             "stock", "monthly", "carry_level", "constant",
                             records, start_period=0, end_period=horizon - 1,
                             cardinality="many",
                             revenue_category="other_operating_income"))
        project2, _ = make_project(ctx, base, name="c10gap-source")
        negative = run_engine(ctx, project2,
                              engine_input(ctx, as_source, records,
                                           config=config))
        runs.append(negative)
        attributed = errors_with(negative, CODE_GAP_AS_SOURCE)
        if not attributed:
            findings.append(
                f"RED-2: {CODE_GAP_AS_SOURCE} assente benche' un driver di "
                "classe cash_buffer sia dichiarato in una categoria di FONTE; "
                f"osservati={sorted(negative['observed'])}")
        elif not any(entry.get("ref") in ("DRV-009", "ASS-009")
                     for entry in attributed):
            findings.append(
                f"RED-2: {CODE_GAP_AS_SOURCE} non attribuito ALLA RIGA "
                "(DRV-009 / ASS-009)")
        # Attribuzione VIETATA: `opening_balance_as_source` e' un ALTRO
        # contratto (`FE-C-10`) e non soddisfa questo.
        if AMB_W2_01 in negative["observed"] and not attributed:
            findings.append(
                f"RED-2: attribuzione VIETATA: {AMB_W2_01} non soddisfa "
                "T-FIN-FUNDING-GAP")
        # Esclusione di falso positivo: il contratto fallisce anche con
        # `REC-05` VERDE.
        rec05 = ((plan_of(run) or {}).get("reconciliations")
                 or {}).get("REC-05") or {}
        if rec05.get("status") != "PASS":
            findings.append(
                "esclusione di falso positivo: REC-05 non e' PASS sul caso "
                "nominale del gap: il contratto perderebbe la specificita'")
    return findings, runs


def c_m4_15(ctx):
    """`FS-C-15` -- guardia di tolleranza ESTESA alle riconciliazioni di
    break-even, scenari e categorie.

    Non basta che la stringa `tolerance` esista: deve PARSARE alla soglia
    APPLICATA dal confronto BERSAGLIO, cioe' allo stesso `rec_id`.
    """
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_ext_c15_") as base:
        base = Path(base)
        records = base_records(ctx)
        rows = base_rows(ctx, records)
        project, _ = make_project(ctx, base, name="c15tol")
        run = run_engine(ctx, project, engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        plan = plan_of(run) or {}
        recon = plan.get("reconciliations") or {}
        ledger = ((run.get("result") or {}).get("tolerance_ledger")) or {}
        tolerances = ctx["enforcement"].get("tolerances") or {}
        produced = [rec_id for rec_id in M4_REC_IDS if rec_id in recon]
        if sorted(produced) != sorted(M4_REC_IDS):
            findings.append(
                f"riconciliazioni di break-even, scenari e categorie "
                f"mancanti dal payload: "
                f"{sorted(set(M4_REC_IDS) - set(produced))}")
        for rec_id in produced:
            entry = recon[rec_id]
            unit = entry.get("tolerance_unit")
            serialized = entry.get("tolerance")
            applied = ledger.get(rec_id)
            if unit not in ("EUR", "ratio", "count", "FTE"):
                findings.append(
                    f"{rec_id}: tolerance_unit={unit!r} fuori dalle quattro "
                    "unita' ammesse")
                continue
            key = "count" if unit == "FTE" else unit
            declared = tolerances.get(key)
            if serialized is None:
                findings.append(f"{rec_id}: stringa tolerance ASSENTE")
                continue
            if applied is None:
                findings.append(
                    f"{rec_id}: soglia APPLICATA assente dal tolerance_ledger: "
                    "la sola PRESENZA della stringa non dimostra che lo stesso "
                    "valore parsato sia quello usato dal confronto")
                continue
            # Lo STESSO valore parsato dev'essere quello del confronto
            # BERSAGLIO: una corrispondenza su un ALTRO rec_id non soddisfa.
            if Decimal(str(applied)) != Decimal(str(declared)):
                findings.append(
                    f"{rec_id}: soglia applicata {applied!r} != "
                    f"enforcement-config.tolerances[{key!r}]={declared!r}")
            if str(declared) not in str(serialized):
                findings.append(
                    f"{rec_id}: la stringa tolerance {serialized!r} non porta "
                    f"la soglia applicata {declared!r}: una soglia cambiata "
                    "senza la sua rappresentazione e' un difetto")
        # NEGATIVO -- una corrispondenza appartenente a un ALTRO `rec_id` non
        # soddisfa: lo si dimostra verificando che le chiavi del ledger e
        # quelle delle riconciliazioni coincidano una a una.
        orphan = sorted(set(ledger) - set(recon))
        if orphan:
            findings.append(
                f"tolerance_ledger porta soglie prive della riconciliazione "
                f"corrispondente: {orphan}")
        missing = sorted(set(recon) - set(ledger))
        if missing:
            findings.append(
                f"riconciliazioni prive della soglia applicata nel ledger: "
                f"{missing}")
    return findings, runs


def c_m4_17(ctx):
    """`FS-C-17` -- confine con lo Stage 11.

    Nessuna delle SETTE chiavi di Stage 11 compare nell'output, e
    `use_of_proceeds_candidates` NON e' prodotto dal motore (lo compone il
    costruttore canonico).
    """
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_ext_c17_") as base:
        base = Path(base)
        records = base_records(ctx)
        rows = base_rows(ctx, records)
        config = financial_config(
            ctx, cash_buffer_policy={"kind": "absolute", "value": 20000})
        project, _ = make_project(ctx, base, name="c17")
        run = run_engine(ctx, project,
                         engine_input(ctx, rows, records, config=config))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        blob = json.dumps(run.get("result") or {}, sort_keys=True)
        keys = set()

        def walk(node):
            if isinstance(node, dict):
                keys.update(node.keys())
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(run.get("result") or {})
        # Ogni chiave vietata e' NOMINATA una per una: l'assenza di UNA SOLA
        # non soddisfa il contratto.
        for forbidden in STAGE11_FORBIDDEN_KEYS:
            if forbidden in keys:
                findings.append(
                    f"chiave di Stage 11 {forbidden!r} presente nell'output "
                    "dello Stage 10")
        # `use_of_proceeds_candidates` NON e' prodotto dal motore: il
        # contratto verifica che NON compaia, mai che sia corretto.
        if "use_of_proceeds_candidates" in keys:
            findings.append(
                "chiave 'use_of_proceeds_candidates' prodotta dal motore: "
                "la compone soltanto il costruttore canonico, e qui si verifica "
                "che NON compaia, tantomeno sommata a un importo richiesto")
        # Il MODULO `milestone_coverage` non e' prodotto dal motore. L'omonimo
        # INDICATORE del set minimo di KPI e' invece dichiarato `required`
        # dallo schema del piano finanziario ed e' dovuto: i due non vanno
        # confusi.
        if "milestone_coverage" in modules_of(run):
            findings.append(
                "il modulo 'milestone_coverage' e' prodotto dal motore: "
                "non e' un modulo del motore, come REC-09")
        # `financial_need` resta un PROFILO TEMPORALE: la prova che il confine
        # regge e' che il fabbisogno non sia collassato in un importo unico.
        need = module_series(modules_of(run).get("funding_gap"))
        if len(need) <= 1:
            findings.append(
                f"financial_need ha {len(need)} valori: collassato in uno "
                "scalare, e' il punto in cui una richiesta di funding si "
                "insinua")
        del blob
    return findings, runs


def c_m4_18(ctx):
    """`FS-C-18` `T-FIN-DETERMINISM` PER SCENARIO -- un checksum per ogni
    scenario prodotto.

    Un checksum per OGNI scenario prodotto; `null` DICHIARATO per quelli
    `NOT_APPLICABLE`. Il solo checksum `base` non soddisfa il contratto.
    """
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_ext_c18_") as base:
        base = Path(base)
        records = triplet_records(ctx)
        rows = base_rows(ctx, records)
        project, _ = make_project(ctx, base, name="c18")
        run = run_engine(ctx, project, engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        plan = plan_of(run) or {}
        scenarios = ((plan.get("results") or {}).get("scenarios")) or {}
        metadata = plan.get("calculation_metadata") or {}
        checksums = metadata.get("output_checksums") or {}
        produced = [sid for sid in SCENARIO_IDS
                    if (scenarios.get(sid) or {}).get("status") != \
                    "NOT_APPLICABLE"]
        if not produced:
            findings.append("nessuno scenario prodotto su copertura piena")
        for scenario_id in SCENARIO_IDS:
            entry = scenarios.get(scenario_id)
            if entry is None:
                findings.append(
                    f"scenario {scenario_id!r} assente da results.scenarios: "
                    "lo schema del piano finanziario lo dichiara required")
                continue
            validate_ref(ctx, entry, "#/$defs/scenario_result",
                         f"scenarios.{scenario_id}", findings)
            if scenario_id not in checksums:
                findings.append(
                    f"output_checksums privo della voce {scenario_id!r}: "
                    "omettere i checksum di downside/upside e' un difetto, "
                    "e il solo checksum base non soddisfa il contratto")
                continue
            value = checksums[scenario_id]
            if scenario_id in produced:
                if not isinstance(value, str) or len(value) != 64:
                    findings.append(
                        f"output_checksums[{scenario_id!r}]={value!r} non e' "
                        "uno sha256 su uno scenario PRODOTTO")
                if entry.get("output_checksum") != value:
                    findings.append(
                        f"scenario {scenario_id!r}: output_checksum del "
                        "scenario_result diverso da quello dei metadati")
            elif value is not None:
                findings.append(
                    f"output_checksums[{scenario_id!r}]={value!r} su uno "
                    "scenario NOT_APPLICABLE: il contratto esige null "
                    "DICHIARATO")
        # I checksum degli scenari PRODOTTI sono DISTINTI: tre input
        # differenziati non possono produrre lo stesso risultato.
        values = [checksums.get(sid) for sid in produced]
        if len(values) > 1 and len(set(values)) != len(values):
            findings.append(
                f"checksum COINCIDENTI fra scenari prodotti: {values}. Tre "
                "serie identiche etichettate diversamente sono un difetto")
    return findings, runs


#: I campi TIPIZZATI da cui ogni proprieta' di governance dev'essere
#: leggibile. Ricostruirne anche uno solo dalla PROSA -- da `notes` o da
#: `checks[].message` -- e' il difetto che il contratto rileva.
GOVERNANCE_TYPED_FIELDS = ("driver_id", "status", "input_kind", "source_ref",
                           "source_path", "rationale", "confidence", "unit",
                           "frequency", "measure_kind", "binding_method",
                           "source_priority")

#: Gli stati che rendono un driver ELEGGIBILE all'ispezione di governance: su un
#: piano interamente `confirmed` la proiezione sarebbe banale e il contratto
#: VACUO (esclusione del falso positivo).
GOVERNANCE_ELIGIBLE_STATUSES = ("inferred", "placeholder")

#: I marcatori che tradiscono un campo di governance spostato in PROSA.
GOVERNANCE_PROSE_MARKERS = ("status=", "input_kind=", "confidence=",
                            "source_ref=", "rationale=", "unit=",
                            "measure_kind=", "binding_method=")


def _eligible_drivers(drivers):
    """I driver su cui l'ispezione di governance ha davvero qualcosa da dire."""
    return [driver for driver in drivers
            if driver.get("status") in GOVERNANCE_ELIGIBLE_STATUSES
            and driver.get("binding_method") != "derived"]


def _governance_reach(run, drivers, expected_ids):
    """Il payload RAGGIUNGE davvero l'ispezione di governance?

    Restituisce l'elenco delle ragioni per cui NON la raggiunge. Serve a
    impedire due modi di essere verdi senza misurare nulla: un insieme
    eleggibile VUOTO, e un GATE BLOCCATO che non ha nulla a che vedere con la
    completezza di governance. Il registro dei driver e' emesso SEMPRE -- anche
    a gate bloccato -- quindi contarne la lunghezza NON basta.
    """
    reasons = []
    if "financial_engine_gate" in (run.get("observed") or set()):
        reasons.append(
            "il gate fail-closed ha bloccato il CALCOLO: un contratto che "
            "passasse qui sarebbe soddisfatto da un gate NON PERTINENTE alla "
            "completezza di governance; osservati="
            f"{sorted(run.get('observed') or [])}")
    if not modules_of(run):
        reasons.append(
            "nessun modulo prodotto: il payload non raggiunge l'ispezione di "
            "governance")
    eligible = _eligible_drivers(drivers)
    if len(eligible) < len(GOVERNANCE_ELIGIBLE_STATUSES):
        reasons.append(
            f"insieme eleggibile di {len(eligible)} driver: ne servono almeno "
            f"{len(GOVERNANCE_ELIGIBLE_STATUSES)}, e un insieme VUOTO o troppo "
            "piccolo renderebbe il contratto VACUO")
    statuses = {driver.get("status") for driver in eligible}
    for required_state in GOVERNANCE_ELIGIBLE_STATUSES:
        if required_state not in statuses:
            reasons.append(
                f"nessun driver {required_state!r} nell'insieme eleggibile "
                f"({sorted(statuses)}): la proiezione sarebbe banale")
    # Un `driver_id` assente o malformato dev'essere una CONSTATAZIONE
    # ATTRIBUITA, mai un'eccezione. `sorted()` su un insieme che contiene
    # `None` o un intero solleverebbe `TypeError`, e il contratto morirebbe per
    # errore di harness invece che per rilievo.
    observed_ids = set()
    for index, driver in enumerate(eligible):
        driver_id = driver.get("driver_id")
        if driver_id is None:
            reasons.append(
                f"driver eleggibile all'indice {index}: driver_id ASSENTE o "
                "null: la voce non e' attribuibile e la proiezione non e' "
                "ispezionabile")
            continue
        if not isinstance(driver_id, str) or not driver_id.strip():
            reasons.append(
                f"driver eleggibile all'indice {index}: driver_id "
                f"{driver_id!r} non e' un identificatore testuale non vuoto")
            continue
        if driver_id in observed_ids:
            reasons.append(
                f"driver eleggibile all'indice {index}: driver_id "
                f"{driver_id!r} DUPLICATO nell'insieme eleggibile: "
                "l'attribuzione diventa ambigua e due voci distinte "
                "sarebbero indistinguibili")
            continue
        observed_ids.add(driver_id)
    for driver_id in expected_ids:
        if driver_id not in observed_ids:
            reasons.append(
                f"il driver ATTESO {driver_id} non e' fra gli ispezionati "
                f"({sorted(observed_ids)})")
    return reasons


def _governance_findings(drivers):
    """Ogni campo di governance e' leggibile da un campo TIPIZZATO.

    Legge SOLO campi tipizzati del `driver_entry` di produzione: nessuna
    proprieta' e' ricostruita da `notes` ne' da `checks[].message`.
    """
    findings = []
    for driver in _eligible_drivers(drivers):
        driver_id = driver.get("driver_id") or "(driver senza driver_id)"
        for field in GOVERNANCE_TYPED_FIELDS:
            if driver.get(field) in (None, ""):
                findings.append(
                    f"{driver_id}: campo di governance {field!r} non leggibile "
                    "da un campo TIPIZZATO: ricostruirlo richiederebbe di "
                    "leggere PROSA")
        note = driver.get("notes")
        if isinstance(note, str) and note:
            for marker in GOVERNANCE_PROSE_MARKERS:
                if marker in note:
                    findings.append(
                        f"{driver_id}: notes porta {marker!r}: un campo di "
                        "governance spostato in PROSA e' un difetto")
    return findings


def c_m4_20(ctx):
    """`FS-C-20` `T-FIN-ASSUMPTION-REGISTER-PROJECTION` -- governance dei
    driver leggibile da campi TIPIZZATI.

    Per OGNI driver ELEGGIBILE, ogni campo di governance e' leggibile da un
    campo TIPIZZATO: mai da `notes`, mai da `checks[].message`, mai da prosa.

    Il contratto e' NON VACUO per costruzione: dichiara l'insieme eleggibile
    ATTESO, ne registra gli ID ISPEZIONATI, e verifica di aver davvero
    RAGGIUNTO l'ispezione. Il registro dei driver e' emesso SEMPRE -- anche a
    gate BLOCCATO -- quindi contarne la lunghezza non dimostra nulla; cio' che
    lo dimostra e' che il CALCOLO sia avvenuto e che l'insieme eleggibile
    contenga almeno un `inferred` e un `placeholder` NOMINATI.
    """
    findings = []
    runs = []
    expected_ids = ("DRV-001", "DRV-010")
    with tempfile.TemporaryDirectory(prefix="fin_ext_c20_") as base:
        base = Path(base)
        # Il `placeholder` vive su un ruolo OPZIONALE CONSUMATO
        # (`retention_rate`), non su uno RICHIESTO: e' il caso esatto di un
        # input opzionale CONSUMATO che ABBASSA lo stato propagato senza
        # bloccare il calcolo.
        records = base_records(ctx)
        records["ASS-010"] = record(ctx["testkit"], 10, 0.9, "ratio",
                                    category="retention")
        rows = base_rows(ctx, records)
        rows.append(row(ctx, "DRV-010", "retention_rate", "ASS-010", "ratio",
                        "rate", "annual", "compound", "NOT_APPLICABLE",
                        records, status="placeholder",
                        scenario_polarity="revenue_like"))
        project, _ = make_project(ctx, base, name="c20")
        run = run_engine(ctx, project, engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        plan = plan_of(run) or {}
        drivers = (plan.get("driver_registry") or {}).get("drivers") or []
        # ---- IL BERSAGLIO E' RAGGIUNTO ------------------------------------
        reach = _governance_reach(run, drivers, expected_ids)
        findings.extend(f"caso di produzione: {reason}" for reason in reach)
        eligible = _eligible_drivers(drivers)
        # La REGISTRAZIONE degli ID ispezionati non puo'
        # sollevare su un `driver_id` assente o non testuale.
        inspected = sorted(str(driver.get("driver_id")) for driver in eligible)
        if not reach:
            # Gli ID ISPEZIONATI sono REGISTRATI: senza di essi «il contratto e'
            # verde» non distingue «ha ispezionato» da «non aveva nulla da
            # ispezionare».
            findings.extend(
                f"caso di produzione: driver ispezionati {inspected}: {reason}"
                for reason in _governance_findings(drivers))
        # ---- SOTTOCASI: il contratto DEVE diventare RED --------------------
        # Ciascuno degrada una COPIA dell'output DI PRODUZIONE e verifica che
        # l'ispezione lo rilevi. Se un degrado passasse inosservato, il verde
        # del caso di produzione non proverebbe nulla.
        target = next((driver for driver in eligible
                       if driver.get("status") == "placeholder"), None)
        if target is None:
            findings.append(
                "nessun driver placeholder ispezionabile: i sottocasi di "
                "degrado non sarebbero eseguibili e il contratto sarebbe VACUO")
        else:
            def rejected(degraded):
                """Il payload degradato NON puo' superare il contratto.

                Vale come rifiuto sia un rilievo dell'ispezione, sia la perdita
                del bersaglio: se il driver atteso esce dall'insieme eleggibile
                perche' gli e' stato tolto il campo che lo qualifica, il
                contratto non lo sta ignorando in silenzio -- lo dichiara non
                raggiunto.
                """
                return bool(_governance_reach(run, degraded, expected_ids) or
                            _governance_findings(degraded))

            # 1  un campo tipizzato RIMOSSO
            stripped = copy.deepcopy(drivers)
            for driver in stripped:
                if driver.get("driver_id") == target.get("driver_id"):
                    driver.pop("input_kind", None)
            if not rejected(stripped):
                findings.append(
                    "sottocaso 1: rimuovere il campo tipizzato 'input_kind' da "
                    f"{target.get('driver_id')} NON rende il contratto RED: "
                    "l'ispezione non legge quel campo")
            # 2  un campo tipizzato spostato in `notes`: il valore vive SOLO in
            #    PROSA, e il campo tipizzato non c'e' piu'.
            in_notes = copy.deepcopy(drivers)
            for driver in in_notes:
                if driver.get("driver_id") == target.get("driver_id"):
                    driver["notes"] = (
                        f"confidence={driver.pop('confidence', None)}")
            if not rejected(in_notes):
                findings.append(
                    "sottocaso 2: spostare 'confidence' in notes su "
                    f"{target.get('driver_id')} NON rende il contratto RED: "
                    "un campo di governance vive in PROSA e passa")
            # 3  un campo tipizzato spostato in un `checks[].message`: il
            #    portatore vive FUORI dal `driver_entry`, ed e' il caso in cui
            #    la proprieta' sembra presente nel report ma non e' leggibile
            #    dal registro.
            in_message = copy.deepcopy(drivers)
            carrier = None
            for driver in in_message:
                if driver.get("driver_id") == target.get("driver_id"):
                    carrier = (f"status={driver.pop('status', None)} su "
                               f"{driver.get('driver_id')}")
            if carrier is None or not rejected(in_message):
                findings.append(
                    "sottocaso 3: spostare 'status' in un checks[].message NON "
                    "rende il contratto RED: l'ispezione accetta un campo di "
                    f"governance ricostruito da prosa ({carrier!r})")
            # 4  insieme eleggibile VUOTO: non puo' esistere un verde
            confirmed = copy.deepcopy(drivers)
            for driver in confirmed:
                driver["status"] = "confirmed"
            if not _governance_reach(run, confirmed, expected_ids):
                findings.append(
                    "sottocaso 4: un insieme eleggibile VUOTO (ogni driver "
                    "confirmed) supera la guardia di non vacuita': il contratto "
                    "potrebbe passare senza ispezionare alcunche'")
            if _governance_findings(confirmed):
                findings.append(
                    "sottocaso 4: l'ispezione produce rilievi su un insieme "
                    "eleggibile VUOTO: sta leggendo driver che non ispeziona")
            # 6  `driver_id` ASSENTE, NULL, NON TESTUALE o DUPLICATO.
            #    Ciascuna forma dev'essere RESPINTA con una
            #    CONSTATAZIONE ATTRIBUITA -- l'indice della voce o il valore
            #    malformato -- e MAI con un'eccezione non gestita.
            def malformed(kind):
                degraded = copy.deepcopy(drivers)
                victims = _eligible_drivers(degraded)
                if len(victims) < 2:
                    return None
                # Il bersaglio e' un driver ATTESO: cosi' l'ordinamento degli
                # ID ispezionati viene davvero raggiunto, ed e' li' che un
                # `driver_id` malformato si manifesterebbe come TypeError.
                position = next(
                    (index for index, entry in enumerate(victims)
                     if entry.get("driver_id") in expected_ids), 0)
                other = next(index for index in range(len(victims))
                             if index != position)
                if kind == "assente":
                    victims[position].pop("driver_id", None)
                elif kind == "null":
                    victims[position]["driver_id"] = None
                elif kind == "non testuale":
                    victims[position]["driver_id"] = 12345
                elif kind == "duplicato":
                    victims[other]["driver_id"] = \
                        victims[position].get("driver_id")
                return degraded

            for kind in ("assente", "null", "non testuale", "duplicato"):
                degraded = malformed(kind)
                if degraded is None:
                    findings.append(
                        f"sottocaso 6 ({kind}): meno di due driver eleggibili, "
                        "la forma malformata non e' esercitabile")
                    continue
                try:
                    reasons = _governance_reach(run, degraded, expected_ids)
                    _governance_findings(degraded)
                except Exception as exc:  # noqa: BLE001 - e' il difetto misurato
                    findings.append(
                        f"sottocaso 6 ({kind}): l'ispezione muore per "
                        f"ECCEZIONE {type(exc).__name__}: {exc}. Un contratto "
                        "deve riportare la PROPRIA constatazione, non un "
                        "errore di harness")
                    continue
                if not reasons:
                    findings.append(
                        f"sottocaso 6 ({kind}): un driver_id malformato NON "
                        "rende il contratto RED: la proiezione sarebbe "
                        "ispezionata su voci non attribuibili")
                    continue
                attributed = [reason for reason in reasons
                              if "all'indice" in reason]
                if not attributed:
                    findings.append(
                        f"sottocaso 6 ({kind}): il contratto e' RED ma nessun "
                        f"rilievo NOMINA la voce o il suo indice: {reasons}")
        # 5  un GATE BLOCCATO NON PERTINENTE alla completezza di governance non
        #    puo' soddisfare il contratto. E' la condizione che l'evidenza
        #    storica indicava come causa della vacuita': il registro dei driver
        #    e' emesso COMUNQUE -- sette su sette -- quindi la sola guardia
        #    sulla LUNGHEZZA non scatta, e serve la guardia sul RAGGIUNGIMENTO.
        blocked_rows = copy.deepcopy(rows)
        for entry in blocked_rows:
            if entry["role"] == "opex":
                entry["status"] = "placeholder"
        project_b, _ = make_project(ctx, base, name="c20-blocked")
        blocked = run_engine(ctx, project_b,
                             engine_input(ctx, blocked_rows, records))
        runs.append(blocked)
        blocked_plan = plan_of(blocked) or {}
        blocked_drivers = ((blocked_plan.get("driver_registry") or {})
                           .get("drivers") or [])
        if len(blocked_drivers) < len(blocked_rows):
            findings.append(
                "sottocaso 5: il motore NON emette il registro dei driver a "
                f"gate bloccato ({len(blocked_drivers)} su "
                f"{len(blocked_rows)}): la guardia di non vacuita' andrebbe "
                "ripensata, perche' questo contratto assume che il registro sia "
                "emesso SEMPRE")
        if not _governance_reach(blocked, blocked_drivers, expected_ids):
            findings.append(
                "sottocaso 5: un GATE BLOCCATO non pertinente alla completezza "
                "di governance supera la guardia di raggiungimento: il "
                "contratto sarebbe VERDE senza aver ispezionato la proiezione "
                f"(osservati={sorted(blocked['observed'])})")
        # `materiality` e `source_type` sono campi OPZIONALI di
        # `driver_entry` che il motore NON valorizza: la loro assenza dal
        # registro prodotto dal motore e' verificata.
        for absent in ("materiality", "source_type"):
            if any(absent in driver for driver in drivers):
                findings.append(
                    f"campo {absent!r} presente su driver_entry: il motore "
                    f"non valorizza questo campo opzionale")
        # `evidence_refs` resta un controllo CONDIZIONALE proprio: e' dovuto
        # dove la provenienza lo esige, non su ogni driver.
        for driver in eligible:
            if driver.get("status") == "unresolved" or \
                    driver.get("input_kind") == "external_source":
                if driver.get("evidence_refs") is None:
                    findings.append(
                        f"{driver.get('driver_id')}: evidence_refs assente su "
                        "un driver che ne richiede la provenienza")
    return findings, runs


# --------------------------------------------------------------------------
# Registro dei contratti
# --------------------------------------------------------------------------

CONTRACTS = [
    {
        "id": "FE-C-01", "name": "T-FIN-CALENDAR", "fn": c01,
        "rule": "calendario da financial_config: orizzonte, anchor_date e "
                "primo periodo parziale dichiarati",
        "fixture": "F-11 (valido / assente / invalido) su F-1",
        "red": "RED-1 orizzonte da costante; RED-2 anchor_date da now(); "
               "RED-3 primo periodo parziale reso pieno; RED-4 "
               "financial_config assente",
        "expected_codes": (CODE_CONFIG_MISSING,),
        "forbidden_codes": (CODE_CONFIG_INVALID,),
        "attribution": "financial_config_missing attribuito al progetto; "
                       "periods[0].partial == true",
        "mutation": "orizzonte da costante o anchor_date da now()",
    },
    {
        "id": "FE-C-02", "name": "T-FIN-REVENUE", "fn": c02,
        "rule": "ricavi = pattern di ricavo x driver, periodo per periodo",
        "fixture": "F-1",
        "red": "ricavi != pattern x driver in un solo periodo",
        "expected_codes": (),
        "forbidden_codes": (),
        "attribution": "scarto attribuito al PERIODO e al DRV-*",
        "mutation": "ricavo errato in un solo periodo",
    },
    {
        "id": "FE-C-03", "name": "T-FIN-COGS", "fn": c03,
        "rule": "ogni costo variabile legato entra nel totale COGS",
        "fixture": "F-1",
        "red": "un costo variabile legato escluso dal totale",
        "expected_codes": (),
        "forbidden_codes": ("cogs_coverage_incomplete",),
        "attribution": "DRV-* del costo escluso NOMINATO",
        "mutation": "costo variabile legato escluso dal totale",
    },
    {
        "id": "FE-C-04", "name": "T-FIN-HEADCOUNT", "fn": c04,
        "rule": "FTE come livello sulla finestra dichiarata, mai dedotta da "
                "etichette",
        "fixture": "F-4 (con e senza periodi)",
        "red": "RED-1 senza start/end_period; RED-2 serie non allineata; "
               "RED-3 indice ricavato da 'Y1H2'",
        "expected_codes": (CODE_PERIOD_UNDECLARED,),
        "forbidden_codes": ("driver_frequency_undeclared",),
        "attribution": "driver_period_undeclared attribuito a DRV-005",
        "mutation": "finestra FTE dedotta o assente",
    },
    {
        "id": "FE-C-05", "name": "T-FIN-PAYROLL", "fn": c05,
        "rule": "payroll = Sigma (FTE x costo unitario); REC-03 e REC-14",
        "fixture": "F-4",
        "red": "payroll != Sigma (FTE x costo unitario)",
        "expected_codes": (),
        "forbidden_codes": (),
        "attribution": "REC-03 residuo per RUOLO; REC-14 sulla serie FTE",
        "mutation": "payroll che ignora il costo unitario",
    },
    {
        "id": "FE-C-06", "name": "T-FIN-OPEX", "fn": c06,
        "rule": "opex categorizzati nella tassonomia di fonti e usi",
        "fixture": "F-7 (tre categorie)",
        "red": "una categoria omessa dal totale; righe NON categorizzate",
        "expected_codes": (),
        "forbidden_codes": (),
        "attribution": "riga line_id e category NOMINATI",
        "mutation": "categoria opex omessa dal totale",
    },
    {
        "id": "FE-C-07", "name": "T-FIN-RATE-CONVERSION", "fn": c07,
        "rule": "un tasso si COMPONE; politica di conversione nell'insieme "
                "chiuso della propria natura",
        "fixture": "F-6 (compound / allocate / preserve_per_unit / "
                   "politica arbitraria / politica di un'altra natura)",
        "red": "tasso annuo DIVISO per 12 nella SERIE CONSUMATA, col metadato "
               "intatto; politica di conversione arbitraria o di un'altra "
               "natura di misura accettata",
        "expected_codes": (AMB_W2_02, CODE_CONVERSION_POLICY),
        "forbidden_codes": (),
        "attribution": "il tasso APPLICATO al calcolo, ricavato dall'output di "
                       "produzione, con DRV-003 e il PERIODO nominati; "
                       "driver_conversion_policy_undeclared attribuito al DRV-*",
        "mutation": "tasso annuo diviso linearmente nella serie consumata",
    },
    {
        "id": "FE-C-08", "name": "T-FIN-DETERMINISM", "fn": c08,
        "rule": "ricalcolo deterministico e engine_source_hash coerente col "
                "sorgente",
        "fixture": "F-1",
        "red": "RED-1 due esecuzioni -> checksum diversi; RED-2 sorgente "
               "modificato senza cambio di engine_source_hash",
        "expected_codes": (AMB_W2_03,),
        "forbidden_codes": (),
        "attribution": "output_checksums.base e engine_source_hash NOMINATI",
        "mutation": "checksum instabili o hash di sorgente non aggiornato",
    },
    {
        "id": "FE-C-09", "name": "T-FIN-PNL", "fn": c09,
        "rule": "nessuna fonte finanziaria nel P&L",
        "fixture": "F-1 + riga equity_financing",
        "red": "una fonte finanziaria compare nel P&L",
        "expected_codes": (CODE_FINANCING_IN_PNL,),
        "forbidden_codes": ("financing_in_revenue",),
        "attribution": "financing_in_pnl attribuito alla RIGA",
        "mutation": "fonte finanziaria conteggiata nel P&L",
    },
    {
        "id": "FE-C-10", "name": "T-FIN-CASH-FLOW", "fn": c10,
        "rule": "roll-forward di cassa REC-05; saldo di apertura mai fra le "
                "fonti",
        "fixture": "F-1",
        "red": "RED-1 opening + in - out != ending; RED-2 opening_cash_balance "
               "fra le SOURCES",
        "expected_codes": (AMB_W2_01,),
        "forbidden_codes": ("funding_gap_as_source",),
        "attribution": "REC-05 residuo per PERIODO; RED-2 attribuito alla "
                       "voce di apertura",
        "mutation": "roll-forward rotto o saldo di apertura fra le SOURCES",
    },
    {
        "id": "FE-C-11", "name": "T-FIN-RUNWAY", "fn": c11,
        "rule": "quattro misure di cassa distinte, ciascuna dalla propria "
                "soglia",
        "fixture": "F-1 con cash_buffer_policy; piano SOLVIBILE che non "
                   "attraversa alcuna soglia; attraversamento COINCIDENTE",
        "red": "una misura di cassa SOSTITUITA, ALIASSATA o derivata dalla "
               "definizione sbagliata; un periodo di prima violazione usato "
               "COME misura",
        "expected_codes": (AMB_W2_04,),
        "forbidden_codes": (),
        "attribution": "ogni misura confrontata col RICALCOLO INDIPENDENTE "
                       "dalla PROPRIA soglia; l'uguaglianza NUMERICA di due "
                       "misure distinte NON soddisfa il contratto",
        "mutation": "misura di cassa sostituita o aliassata",
    },
    {
        "id": "FE-C-12", "name": "T-FIN-BUFFER", "fn": c12,
        "rule": "soglia di buffer dichiarata o modulo NOT_APPLICABLE "
                "nominato",
        "fixture": "F-1 (policy presente / assente)",
        "red": "violazione non segnalata; policy assente trattata come 0",
        "expected_codes": (),
        "forbidden_codes": (),
        "attribution": "module_status NOT_APPLICABLE con "
                       "not_applicable_reason che NOMINA cash_buffer_policy",
        "mutation": "policy di buffer assente trattata come zero",
    },
    {
        "id": "FE-C-20", "name": "T-FIN-NO-ECONOMIC-HARDCODE", "fn": c20,
        "rule": "nessun letterale economico nel sorgente del motore",
        "fixture": "scansione statica del sorgente del motore",
        "red": "un letterale economico nel sorgente del motore",
        "expected_codes": (),
        "forbidden_codes": (),
        "attribution": "il FILE e la RIGA del letterale NOMINATI",
        "mutation": "letterale economico nel sorgente del motore",
    },
    {
        "id": "FE-C-22", "name": "tolerance-guard", "fn": c22,
        "rule": "stringa di tolleranza = soglia applicata da enforcement-"
                "config",
        "fixture": "F-1",
        "red": "la stringa checks[].tolerance non corrisponde alla soglia "
               "numerica applicata",
        "expected_codes": (),
        "forbidden_codes": (),
        "attribution": "coppia (check_id, tolerance) NOMINATA",
        "mutation": "soglia cambiata senza la sua rappresentazione",
    },
    {
        "id": "FE-C-23", "name": "demo-fail-closed", "fn": c23,
        "rule": "il progetto demo non e' l'ingresso del motore: fail-closed "
                "attribuito",
        "fixture": "examples/fictional-startup",
        "red": "il motore calcola qualcosa sul demo",
        "expected_codes": (CODE_CONFIG_MISSING, CODE_ROLE_UNBOUND),
        "forbidden_codes": (),
        "attribution": "financial_config_missing al PROGETTO e "
                       "driver_role_unbound al RUOLO opex",
        "mutation": "calcolo eseguito sul demo",
    },
    {
        "id": "FE-C-24", "name": "execution-purity", "fn": c24,
        "rule": "purezza di esecuzione: nessun path canonico, nessun "
                "progetto mutato",
        "fixture": "F-1",
        "red": "il motore scrive un path canonico o muta un progetto",
        "expected_codes": (),
        "forbidden_codes": (),
        "attribution": "diff dello snapshot VUOTO, nominato",
        "mutation": "scrittura di un path canonico o mutazione del progetto",
    },
    {
        "id": "FE-C-25", "name": "T-FIN-ASSUMPTION-STATE-PRESERVED",
        "fn": c25,
        "rule": "stato propagato = minimo dei propri riferimenti, per modulo"
                " e per piano",
        "fixture": "F-1 con almeno un driver inferred",
        "red": "RED-1 stato promosso; RED-2 minimo di piano sui soli input "
               "RICHIESTI; RED-3 campo di stato dentro module_result; RED-4 "
               "modulo prodotto OMESSO dalla mappa",
        "expected_codes": (),
        "forbidden_codes": (),
        "attribution": "module_id e DRV-* che abbassa lo stato; per RED-4 il "
                       "module_id OMESSO",
        "mutation": "stato promosso o modulo omesso dalla proiezione",
    },
    {
        "id": "FE-C-26", "name": "T-FIN-ASSUMPTION-PROVENANCE", "fn": c26,
        "rule": "provenienza completa dei driver assunti e dei benchmark",
        "fixture": "F-1 con un driver external_source non validato",
        "red": "RED-1 driver assunto privo di rationale o source_ref; RED-2 "
               "benchmark senza evidence_refs[] o senza data",
        "expected_codes": (CODE_UNRESOLVED_REQUIRED,),
        "forbidden_codes": (CODE_SOURCE_PATH,),
        "attribution": "il DRV-* e il CAMPO mancante, NOMINATI",
        "mutation": "driver o benchmark privi di provenienza accettati",
    },
    {
        "id": "FE-C-27", "name": "T-FIN-SOURCE-PRECEDENCE", "fn": c27,
        "rule": "precedenza delle fonti per source_priority crescente",
        "fixture": "F-1 con due candidati sullo stesso ruolo",
        "red": "un benchmark di priorita' INFERIORE sovrascrive un valore "
               "confirmed senza DEC-*",
        "expected_codes": (CODE_SOURCE_CONFLICT,),
        "forbidden_codes": (),
        "attribution": "source_priority di ENTRAMBI i candidati e il DRV-* "
                       "vincente",
        "mutation": "candidato di priorita' inferiore vincente",
    },
    {
        "id": "FE-C-28", "name": "T-FIN-DERIVED-NOT-ASSUMABLE", "fn": c28,
        "rule": "un valore derived si ricalcola, non si valida a mano",
        "fixture": "F-5",
        "red": "un valore input_kind derived e' marcato come assunzione "
               "editabile o validabile",
        "expected_codes": (CHECK_DERIVED,),
        "forbidden_codes": (CODE_INFORMATIONAL,),
        "attribution": "il DRV-* derived e la sua DERIVAZIONE, NOMINATI",
        "mutation": "derivato marcato come assunzione editabile",
    },
    {
        "id": "FE-C-29", "name": "T-FIN-UNBOUND-ROLE-GATE", "fn": c29,
        "rule": "ruolo richiesto non legato: gate bloccato, nessun valore di"
                " ripiego",
        "fixture": "F-1 privata del ruolo opex",
        "red": "un ruolo richiesto privo di legame governato e' STIMATO",
        "expected_codes": (CODE_ROLE_UNBOUND,),
        "forbidden_codes": (CODE_UNRESOLVED_REQUIRED,),
        "attribution": "driver_role_unbound attribuito al RUOLO opex",
        "mutation": "ruolo richiesto non legato stimato",
    },
    {
        "id": "FE-C-30", "name": "T-FIN-READINESS-SEPARATION", "fn": c30,
        "rule": "esito di calcolo e stato propagato restano distinti",
        "fixture": "F-1 con tutti i driver inferred",
        "red": "validation.result PASS presentato come prontezza "
               "investor-ready",
        "expected_codes": (),
        "forbidden_codes": (),
        "attribution": "ENTRAMBE le grandezze NOMINATE e DIVERSE",
        "mutation": "esito di calcolo presentato come prontezza investor-"
                    "ready",
    },
    {
        "id": "FE-C-31", "name": "T-FIN-NO-PRESENTATION-DEPENDENCY",
        "fn": c31,
        "rule": "nessuna dipendenza del calcolo dalla presentazione",
        "fixture": "scansione statica del sorgente + F-1",
        "red": "il sorgente nomina un colore, uno stile, un tema o un "
               "attributo di resa in un ramo di calcolo",
        "expected_codes": (),
        "forbidden_codes": (),
        "attribution": "il FILE e la RIGA del token, NOMINATI",
        "mutation": "token di resa in un ramo di calcolo",
    },
    # ---- break-even, KPI, fabbisogno e confine con lo Stage 11 ------------
    {
        "id": "FS-C-08", "name": "T-FIN-BREAK-EVEN", "fn": c_m4_08,
        "rule": "esito del pareggio dichiarato; REC-15",
        "fixture": "F-1 + variante margine <= 0",
        "red": "RED-1 break-even con margine unitario <= 0 senza dichiararlo; "
               "RED-2 pareggio fuori orizzonte riportato come raggiunto",
        "expected_codes": (),
        "forbidden_codes": (),
        "attribution": "outcome fra REACHED/NOT_REACHED/NOT_REACHABLE "
                       "NOMINATO",
        "mutation": "pareggio fuori orizzonte riportato come raggiunto",
    },
    {
        "id": "FS-C-09", "name": "T-FIN-KPI", "fn": c_m4_09,
        "rule": "set minimo di otto KPI con missing_driver_roles veritieri",
        "fixture": "F-1 privata di cac; pareggio NON RAGGIUNTO; margine "
                   "unitario <= 0; F-1 con OGNI dipendenza legata",
        "red": "un KPI privo di driver OMESSO dal report; un ruolo LEGATO e "
               "CONSUMATO nominato fra i missing_driver_roles; un ruolo "
               "estraneo all'insieme di dipendenza dell'indicatore",
        "expected_codes": (),
        "forbidden_codes": (),
        "attribution": "kpi_id + missing_driver_roles NOMINATI, ciascuno "
                       "confrontato con l'insieme di dipendenza PROPRIO "
                       "dell'indicatore e con i ruoli EFFETTIVAMENTE legati",
        "mutation": "KPI omesso o ruolo legato nominato come mancante",
    },
    {
        "id": "FS-C-10", "name": "T-FIN-FUNDING-GAP", "fn": c_m4_10,
        "rule": "fabbisogno residuo come serie, mai negativo, mai una fonte",
        "fixture": "F-1",
        "red": "RED-1 gap negativo; RED-2 gap fra le fonti; RED-3 "
               "financial_need scalare identico a funding_gap_to_buffer; "
               "RED-4 un riassunto scalare SOSTITUITO con quello dell'altra "
               "soglia",
        "expected_codes": (),
        "forbidden_codes": (AMB_W2_01,),
        "attribution": "funding_gap_as_source attribuito alla RIGA; "
                       "financial_need e' una SERIE; ciascun riassunto "
                       "confrontato col RICALCOLO INDIPENDENTE dalla PROPRIA "
                       "soglia",
        "mutation": "fabbisogno scalare, negativo o fra le fonti",
    },
    {
        "id": "FS-C-15", "name": "T-FIN-TOLERANCE-GUARD-M4",
        "fn": c_m4_15,
        "rule": "tolleranza delle riconciliazioni = soglia applicata, per "
                "rec_id",
        "fixture": "F-1, F-7, F-10",
        "red": "una soglia cambiata senza la sua rappresentazione",
        "expected_codes": (),
        "forbidden_codes": (),
        "attribution": "(check_id, tolerance) dello STESSO rec_id bersaglio",
        "mutation": "soglia cambiata senza la sua rappresentazione",
    },
    {
        "id": "FS-C-17", "name": "T-FIN-NO-STAGE-11-KEYS", "fn": c_m4_17,
        "rule": "nessuna chiave di Stage 11 nell'output dello Stage 10",
        "fixture": "F-1",
        "red": "l'output nomina una delle sette chiavi di Stage 11, oppure "
               "use_of_proceeds_candidates sommati a un importo",
        "expected_codes": (),
        "forbidden_codes": (),
        "attribution": "chiave vietata NOMINATA, una per una",
        "mutation": "chiave di Stage 11 emessa dal motore",
    },
    {
        "id": "FS-C-18", "name": "T-FIN-DETERMINISM-SCENARIO",
        "fn": c_m4_18,
        "rule": "un checksum per ogni scenario prodotto, null per i "
                "NOT_APPLICABLE",
        "fixture": "F-1",
        "red": "output_checksums mancante per uno scenario prodotto",
        "expected_codes": (),
        "forbidden_codes": (),
        "attribution": "output_checksums.{base,downside,upside}",
        "mutation": "checksum di downside/upside omessi",
    },
    {
        "id": "FS-C-20", "name": "T-FIN-ASSUMPTION-REGISTER-PROJECTION",
        "fn": c_m4_20,
        "rule": "campi di governance dei driver leggibili da campi TIPIZZATI",
        "fixture": "F-1 con placeholder su ruolo OPZIONALE consumato; cinque "
                   "sottocasi di degrado dell'output di produzione",
        "red": "un campo tipizzato RIMOSSO; un campo spostato in notes; un "
               "campo spostato in checks[].message; insieme eleggibile VUOTO; "
               "gate BLOCCATO non pertinente alla completezza di governance",
        "expected_codes": (),
        "forbidden_codes": (),
        "attribution": "gli ID dei driver ISPEZIONATI sono REGISTRATI, e "
                       "l'insieme dei campi ricostruiti e' riportato driver "
                       "per driver",
        "mutation": "campo di governance spostato in prosa",
    },
]

CONTRACT_IDS = tuple(entry["id"] for entry in CONTRACTS)


# --------------------------------------------------------------------------
# Esecuzione
# --------------------------------------------------------------------------


def run_one(ctx, contract):
    try:
        findings, runs = contract["fn"](ctx)
    except HarnessDefect:
        raise
    except (KeyError, TypeError, ValueError, decimal.InvalidOperation) as exc:
        findings = [f"errore di valutazione del contratto: {exc!r}"]
        runs = []
    observed = set()
    for run in runs or ():
        observed |= set(run.get("observed") or ())
    return {
        "contract": contract,
        "red": bool(findings),
        "findings": findings,
        "observed": sorted(observed),
        "runs": runs or [],
    }


def specificity(results):
    """Misura di specificita': su quanti report osservati l'insieme
    atteso di ciascun contratto sarebbe soddisfatto."""
    reports = []
    for result in results:
        for run in result["runs"]:
            if run.get("report") is not None:
                reports.append(set(run.get("observed") or ()))
    measures = {}
    for result in results:
        expected = set(result["contract"]["expected_codes"])
        if not expected:
            measures[result["contract"]["id"]] = (0, len(reports))
            continue
        count = sum(1 for observed in reports if expected <= observed)
        measures[result["contract"]["id"]] = (count, len(reports))
    return measures


def format_line(result, measure):
    contract = result["contract"]
    state = "RED" if result["red"] else "GREEN"
    count, total = measure
    return (
        "{state:<5} {cid:<12} {name:<34} observed={observed} "
        "specificity={count}/{total} attribution={attr} | EXPECTED: {exp} "
        "| reason={reason}".format(
            state=state, cid=contract["id"], name=contract["name"],
            observed=result["observed"] or "-", count=count, total=total,
            attr=contract["attribution"],
            exp=", ".join(contract["expected_codes"]) or "(strutturale)",
            reason="; ".join(result["findings"]) or "-"))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(
        prog="test_fin_engine.py", add_help=True,
        description="Contratti del motore finanziario dello Stage 10.")
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

    try:
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

    measures = specificity(results)
    for result in results:
        print(format_line(result, measures[result["contract"]["id"]]))
    red = [result for result in results if result["red"]]
    print("SUMMARY: {total} contratti, {red} RED, {green} GREEN "
          "(entry point {ep}: {state})".format(
              total=len(results), red=len(red), green=len(results) - len(red),
              ep=ENTRY_POINT_REL,
              state="presente" if ctx["entry_point"].is_file() else "ASSENTE"))
    if red:
        return EXIT_RED
    print("PASS: T-FIN-ENGINE {n} contratti del motore finanziario"
          .format(n=len(results)))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
