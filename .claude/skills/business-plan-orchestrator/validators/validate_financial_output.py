#!/usr/bin/env python3
"""Validator dell'OUTPUT CANONICO dello Stage 10.

QUARTO validator finanziario, dichiarato in `config/enforcement-config.json`
con `stages: [10]` e `phases: ["egress","impact"]`, ed elencato in
`egress_required`: e' l'unico validator dello Stage 10 che il Transaction
Manager invoca al confine di egress, perche' valida il documento canonico,
l'unico artefatto che esista a quel confine. Gli altri tre (binding, motore,
riconciliazione) sono validator di pipeline interna sui payload intermedi.

PERCHE' UN QUARTO VALIDATOR. Il documento CANONICO ha una forma — radice con
`schema_version`, sezione `governance`, `use_of_proceeds_candidates` — che
NESSUNO degli altri tre validator valida: il motore valida il payload
INTERMEDIO per `$ref` sulle sole sezioni di competenza. Senza il quarto, un
canonico invalido raggiungerebbe il Transaction Manager.

CHE COSA VALIDA
---------------
  - lo SCHEMA INTERO, radice compresa, e la versione dichiarata;
  - la validita' rispetto al PROFILO ATTIVO;
  - `D1` materialita' del driver, `D2` tipo di fonte, `D3` prontezza
    investor-ready, `D4` proiezione di governance (etichette interne dei
    quattro portatori del canonico, riprese nei messaggi degli esiti);
  - le categorie candidate di uso dei proventi e la GUARDIA DI EQUIVALENZA
    STRUTTURALE;
  - l'assenza di VERITA' NUMERICA nella governance, su DUE FRONTI: strutturale
    (lo schema non dichiara tipi numerici) e COMPORTAMENTALE (questo modulo
    respinge un numero iniettato, con il path NOMINATO). Il solo fronte
    strutturale garantirebbe il divieto per costruzione dello schema e non
    per contratto;
  - la GRAMMATICA ESATTA dei token di `timing_window_empty`;
  - l'assenza di ASSUNZIONI SILENZIOSE e la coerenza della prontezza;
  - la completezza di moduli e scenari e la copertura delle milestone;
  - i CANDIDATI di uso dei proventi, mai un'allocazione;
  - la tracciabilita' a fonti ed evidenze;
  - il DETERMINISMO canonico del documento sul disco;
  - il DIVIETO DI RICALCOLO del costruttore, con AUTO-SONDA del rilevatore;
  - il comportamento su RUN BLOCCATA e la guardia sulla directory della
    skill (vedi `check_real_project`).

Exit code: 0 valido · 1 canonico invalido · 2 errore d'uso · 3 stato corrotto.
"""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _framework as fw  # noqa: E402

VALIDATOR_NAME = "validate_financial_output"
STAGE10 = "10_financial-plan"
SUPPORTED_PHASES = ("egress", "impact")
CANONICAL_NAME = "structured-output.json"

SCHEMA_VERSION = "1.1.0"

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = SKILL_ROOT.joinpath("schemas", "financial-plan.schema.json")
SOURCE_REGISTER_PATH = SKILL_ROOT.joinpath("schemas",
                                           "source-register.schema.json")
BUILDER_PATH = SKILL_ROOT.joinpath("output", "build_canonical_output.py")
BUILDER_REL = (".claude/skills/business-plan-orchestrator/output/"
               "build_canonical_output.py")

MODULE_IDS = (
    "revenue", "cogs", "gross_margin", "headcount", "payroll", "opex", "pnl",
    "cash_flow", "balance_sheet", "runway", "cash_buffer", "break_even",
    "funding_gap", "milestone_coverage", "kpi",
)
SCENARIO_IDS = ("base", "downside", "upside")
STATUS_ORDER = ("unresolved", "placeholder", "inferred", "confirmed")
RECONCILIATION_IDS = (
    "REC-01", "REC-02", "REC-03", "REC-04", "REC-05", "REC-06", "REC-09",
    "REC-11", "REC-12", "REC-13", "REC-14", "REC-15",
)

#: Le SETTE chiavi che lo Stage 11 possiede e che lo Stage 10 non produce.
STAGE11_FORBIDDEN_KEYS = ("funding_ask", "instrument", "valuation",
                          "round_size", "ownership", "dilution", "terms")

#: GRAMMATICA CHIUSA dei tre token di `affected_refs[]` per
#: `timing_window_empty`. Il pattern DRIVER e' quello di
#: `$defs.drv_id`, RIUSATO ALLA LETTERA: nessun pattern nuovo e' coniato.
TOKEN_DRIVER_RE = re.compile(r"^DRV-(?:[0-9]{3}|[1-9][0-9]{3,})$")
TOKEN_MODULE_RE = re.compile(
    r"^module:(?:balance_sheet|break_even|cash_buffer|cash_flow|cogs|"
    r"funding_gap|gross_margin|headcount|kpi|milestone_coverage|opex|payroll|"
    r"pnl|revenue|runway)$")
TOKEN_SCENARIO_RE = re.compile(r"^scenario:(?:base|downside|upside)$")

CODE_TIMING_WINDOW_EMPTY = "timing_window_empty"

#: Codici degli esiti. Sono IDENTIFICATORI STRUTTURALI della classe `check_id`,
#: nella forma che gli altri validator gia' usano (`scenario_coverage`,
#: `financial_engine_gate`, `driver_status_mapping`): nessun codice di dominio
#: e' coniato qui. `derived_artifact_stale` e' invece un codice di dominio gia'
#: esistente, con severita' FAIL e mai WARNING.
CODE_SCHEMA = "canonical_schema"
CODE_SCHEMA_VERSION = "canonical_schema_version"
CODE_PROFILE = "canonical_profile"
CODE_MODULES = "canonical_modules"
CODE_SCENARIOS = "canonical_scenarios"
CODE_RECONCILIATIONS = "canonical_reconciliations"
CODE_GOVERNANCE = "canonical_governance"
CODE_GOVERNANCE_NUMERIC = "canonical_governance_numeric"
CODE_READINESS = "canonical_investor_readiness"
CODE_MATERIALITY = "canonical_materiality"
CODE_SOURCE_TYPE = "canonical_source_type"
CODE_USE_OF_PROCEEDS = "canonical_use_of_proceeds"
CODE_WARNING_ATTRIBUTION = "canonical_warning_attribution"
CODE_SILENT_ASSUMPTION = "canonical_silent_assumption"
CODE_TRACEABILITY = "canonical_traceability"
CODE_DETERMINISM = "canonical_determinism"
CODE_NO_RECOMPUTE = "canonical_no_recompute"
CODE_STAGE_BOUNDARY = "canonical_stage_boundary"
CODE_BLOCKED_RUN = "canonical_blocked_run"
CODE_REAL_PROJECT = "real_project_write_forbidden"
CODE_STALE = "derived_artifact_stale"


# --------------------------------------------------------------------------
# RILEVATORE AST del divieto di ricalcolo, e la sua AUTO-SONDA
# --------------------------------------------------------------------------
#
# ELENCO CHIUSO DELLE OPERAZIONI AMMESSE nel costruttore canonico: tutto cio'
# che non e' qui sotto e' VIETATO, senza eccezioni e senza allow-list per
# nome di variabile — che sarebbe un'euristica e renderebbe la scansione
# vacua. Il costruttore compone path con `Path.joinpath` e stringhe con
# f-string e `str.join`: e' il PREZZO DICHIARATO di una scansione non vacua.

FORBIDDEN_BINOPS = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
    ast.FloorDiv: "//", ast.Mod: "%", ast.Pow: "**", ast.MatMult: "@",
}
FORBIDDEN_CALLS = ("sum", "round", "abs", "pow", "divmod", "Decimal", "float",
                   "complex", "int")
FORBIDDEN_IMPORTS = ("validate_financial_engine", "formula_dsl", "decimal")

#: SORGENTE SINTETICO dell'AUTO-SONDA. CONTIENE le violazioni e il rilevatore
#: DEVE rilevarle: e' cio' che rende la scansione NON VACUA PER COSTRUZIONE,
#: con lo stesso schema di auto-sonda usato dal motore. Non e' eseguito: e'
#: solo parsato.
AST_SELF_PROBE_SOURCE = '''
import validate_financial_engine
from decimal import Decimal


def leak_arithmetic(revenue_series, cogs_series):
    """Somma DUE serie di dominio invece di copiarle: e' un ricalcolo."""
    return revenue_series["0"] + cogs_series["0"]


def leak_conversion(value):
    """Converte una grandezza di dominio: e' un ricalcolo mascherato."""
    return float(Decimal(value))


def leak_accumulator(series):
    total = 0
    for value in series.values():
        total += value
    return total
'''


def scan_forbidden_recomputation(source, label="<source>"):
    """Scansione statica del DIVIETO DI RICALCOLO nel costruttore canonico.

    Restituisce l'elenco dei rilievi, ciascuno con FILE e RIGA. Un elenco VUOTO
    significa scansione PULITA; la sua non-vacuita' e' provata separatamente
    dall'AUTO-SONDA su `AST_SELF_PROBE_SOURCE`.
    """
    findings = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"{label}:{exc.lineno}: sorgente non parsabile: {exc.msg}"]
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp):
            symbol = FORBIDDEN_BINOPS.get(type(node.op))
            if symbol:
                findings.append(
                    f"{label}:{node.lineno}: operatore aritmetico "
                    f"{symbol!r} VIETATO: il costruttore e' una proiezione "
                    "totale, non un secondo motore")
        elif isinstance(node, ast.AugAssign):
            symbol = FORBIDDEN_BINOPS.get(type(node.op))
            if symbol:
                findings.append(
                    f"{label}:{node.lineno}: assegnamento aritmetico "
                    f"{symbol!r}= VIETATO: e' un accumulatore di dominio")
        elif isinstance(node, ast.UnaryOp) and isinstance(
                node.op, (ast.USub, ast.UAdd)):
            if not isinstance(node.operand, ast.Constant):
                findings.append(
                    f"{label}:{node.lineno}: segno unario su un'espressione "
                    "non costante: e' un'operazione su una grandezza")
        elif isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in FORBIDDEN_CALLS:
                findings.append(
                    f"{label}:{node.lineno}: chiamata VIETATA {name!r}: "
                    "aggregazione o conversione numerica fuori dall'elenco "
                    "chiuso di operazioni ammesse")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IMPORTS:
                    findings.append(
                        f"{label}:{node.lineno}: import VIETATO "
                        f"{alias.name!r}")
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module in FORBIDDEN_IMPORTS:
                findings.append(
                    f"{label}:{node.lineno}: import VIETATO da {module!r}")
    return findings


def self_probe_findings():
    """AUTO-SONDA: il rilevatore eseguito sul sorgente sintetico che CONTIENE
    la violazione. Un elenco vuoto significa rilevatore VACUO."""
    return scan_forbidden_recomputation(AST_SELF_PROBE_SOURCE,
                                        label="<auto-sonda AST>")


# --------------------------------------------------------------------------
# Accessori
# --------------------------------------------------------------------------


def canonical_json(document):
    body = json.dumps(document, indent=2, ensure_ascii=True, sort_keys=True)
    return "".join([body, "\n"])


def load_json(path, label):
    target = Path(path)
    if not target.is_file():
        raise fw.ValidatorUsageError(f"{label} assente: {target}")
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise fw.CanonicalStateError(f"{label} non e' JSON: {exc}")


def walk_values(node, path):
    """Ogni valore raggiungibile, col PROPRIO path DOTTATO."""
    if isinstance(node, dict):
        for key in sorted(node):
            child = ".".join([path, str(key)])
            yield child, key, node[key]
            for item in walk_values(node[key], child):
                yield item
    elif isinstance(node, list):
        for index, value in enumerate(node):
            child = "".join([path, "[", str(index), "]"])
            yield child, None, value
            for item in walk_values(value, child):
                yield item


def minimum_status(statuses):
    values = [status for status in statuses if status in STATUS_ORDER]
    if not values:
        return None
    return min(values, key=STATUS_ORDER.index)


# --------------------------------------------------------------------------
# Controlli
# --------------------------------------------------------------------------


def check_schema(document, schema, report):
    try:
        import jsonschema
    except ImportError as exc:
        # RUNTIME-CHECK con FALLBACK DICHIARATO: la validazione di schema del
        # canonico NON e' degradabile a una validazione di forma. In assenza
        # della capability il validator si FERMA e lo DICHIARA, e non emette
        # mai un PASS silenzioso.
        raise fw.ValidatorUsageError(
            f"jsonschema non disponibile ({exc}): la validazione di schema del "
            "documento canonico non e' degradabile — fail-closed, nessun PASS "
            "e' emesso in assenza della capability")
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document),
                    key=lambda err: list(map(str, err.absolute_path)))
    for error in errors:
        path = ".".join(map(str, error.absolute_path)) or "(radice)"
        report.add_error(
            CODE_SCHEMA, ref=path,
            message=f"il documento canonico e' respinto dallo schema: "
                    f"{error.message}",
            expected="conformita' a schemas/financial-plan.schema.json",
            actual=path)
    report.add_check(
        CODE_SCHEMA, "FAIL" if errors else "PASS",
        affected_refs=["schemas/financial-plan.schema.json"],
        message=f"validazione di schema INTERA: {len(errors)} violazioni")
    version = document.get("schema_version")
    if version != SCHEMA_VERSION:
        report.add_error(
            CODE_SCHEMA_VERSION, ref="schema_version",
            message=f"schema_version {version!r} invece di "
                    f"{SCHEMA_VERSION!r} (versione di schema attesa)",
            expected=SCHEMA_VERSION, actual=version)
    return not errors


def check_profile(plan, report):
    registry = plan.get("driver_registry") or {}
    profile_id = registry.get("profile_id")
    if not profile_id:
        report.add_error(
            CODE_PROFILE, ref="driver_registry.profile_id",
            message="il canonico non dichiara il profilo attivo: nessun "
                    "valore di ripiego e' applicato a runtime")
        return
    path = SKILL_ROOT.joinpath("profiles", f"{profile_id}.json")
    if not path.is_file():
        report.add_error(
            CODE_PROFILE, ref=str(profile_id),
            message=f"profilo attivo inesistente: {profile_id!r}")
        return
    profile = json.loads(path.read_text(encoding="utf-8"))
    modules = (plan.get("results") or {}).get("modules") or {}
    for module_id in sorted(profile.get("not_applicable_modules") or ()):
        entry = modules.get(module_id) or {}
        if entry.get("status") != "NOT_APPLICABLE":
            report.add_error(
                CODE_PROFILE, ref=module_id,
                message=f"{module_id} e' dichiarato in "
                        f"not_applicable_modules del profilo {profile_id} ma "
                        f"il canonico lo pubblica con status "
                        f"{entry.get('status')!r}",
                expected="NOT_APPLICABLE NOMINATO e MOTIVATO",
                actual=entry.get("status"))
        elif not (entry.get("reason") or entry.get("not_applicable_reason")):
            report.add_error(
                CODE_PROFILE, ref=module_id,
                message=f"{module_id}: NOT_APPLICABLE senza motivazione "
                        "NOMINATA")
    bound = {entry.get("role") for entry in registry.get("drivers") or ()}
    declared = set(registry.get("unbound_required_roles") or ())
    for role in sorted(profile.get("required_driver_roles") or ()):
        if role in bound or role in declared:
            continue
        report.add_error(
            CODE_PROFILE, ref=role,
            message=f"il ruolo RICHIESTO dal profilo {profile_id} e' "
                    f"{role!r}: non e' legato ad alcun driver e non compare "
                    "in unbound_required_roles[]. Non esiste valore di "
                    "ripiego: un ruolo richiesto non legato e' NOMINATO, mai "
                    "stimato",
            expected="il ruolo NOMINATO in unbound_required_roles[]",
            actual=sorted(declared))
    report.add_check(
        CODE_PROFILE, "PASS",
        affected_refs=[profile_id],
        message="validita' rispetto al profilo attivo verificata su "
                "not_applicable_modules e required_driver_roles")


def check_modules_and_scenarios(plan, report):
    results = plan.get("results") or {}
    modules = results.get("modules") or {}
    for module_id in MODULE_IDS:
        if module_id not in modules:
            report.add_error(
                CODE_MODULES, ref=module_id,
                message=f"il modulo {module_id} e' ASSENTE dal canonico: un "
                        "modulo non prodotto o non pertinente porta "
                        "NOT_APPLICABLE con motivazione NOMINATA, mai "
                        "un'omissione")
            continue
        entry = modules[module_id] or {}
        if entry.get("module_id") != module_id:
            report.add_error(
                CODE_MODULES, ref=module_id,
                message=f"module_id {entry.get('module_id')!r} non coincide "
                        f"con la chiave {module_id!r}")
        if entry.get("status") == "NOT_APPLICABLE" and not (
                entry.get("not_applicable_reason") or entry.get("reason")):
            report.add_error(
                CODE_MODULES, ref=module_id,
                message=f"{module_id}: NOT_APPLICABLE senza motivazione "
                        "NOMINATA")
    for module_id in sorted(modules):
        if module_id not in MODULE_IDS:
            report.add_error(
                CODE_MODULES, ref=module_id,
                message=f"modulo SCONOSCIUTO nel canonico: {module_id!r}")
    coverage_module = modules.get("milestone_coverage") or {}
    if coverage_module.get("status") != "NOT_APPLICABLE":
        seen = set()
        for entry in coverage_module.get("milestones") or ():
            ref = entry.get("milestone_ref")
            if ref in seen:
                report.add_error(
                    CODE_MODULES, ref=str(ref),
                    message=f"milestone {ref!r} riportata piu' di una volta "
                            "nella copertura")
            seen.add(ref)
            if entry.get("coverage_status") not in ("funded", "at_risk",
                                                    "unfunded"):
                report.add_error(
                    CODE_MODULES, ref=str(ref),
                    message=f"coverage_status "
                            f"{entry.get('coverage_status')!r} fuori "
                            "dall'enumerazione dichiarata")
    scenarios = results.get("scenarios") or {}
    for scenario_id in SCENARIO_IDS:
        entry = scenarios.get(scenario_id)
        if entry is None:
            report.add_error(
                CODE_SCENARIOS, ref=scenario_id,
                message=f"lo scenario {scenario_id} e' ASSENTE dal canonico: "
                        "uno scenario non prodotto porta NOT_APPLICABLE "
                        "DICHIARATO, mai un'assenza")
            continue
        if entry.get("scenario") != scenario_id:
            report.add_error(
                CODE_SCENARIOS, ref=scenario_id,
                message=f"scenario {entry.get('scenario')!r} non coincide con "
                        f"la chiave {scenario_id!r}")
        if entry.get("status") == "NOT_APPLICABLE" and not entry.get(
                "not_applicable_reason"):
            report.add_error(
                CODE_SCENARIOS, ref=scenario_id,
                message=f"{scenario_id}: NOT_APPLICABLE senza motivazione "
                        "NOMINATA")
    if "coverage" not in scenarios:
        report.add_error(
            CODE_SCENARIOS, ref="coverage",
            message="results.scenarios.coverage assente: la copertura e' "
                    "riportata NOMINALMENTE, mai riassorbita")
    recon = plan.get("reconciliations") or {}
    for rec_id in RECONCILIATION_IDS:
        entry = recon.get(rec_id)
        if entry is None:
            report.add_error(
                CODE_RECONCILIATIONS, ref=rec_id,
                message=f"{rec_id} assente: un controllo che non compare nel "
                        "report equivale a un controllo non eseguito")
            continue
        if entry.get("status") == "NOT_APPLICABLE" and not entry.get(
                "not_applicable_reason"):
            report.add_error(
                CODE_RECONCILIATIONS, ref=rec_id,
                message=f"{rec_id}: NOT_APPLICABLE senza motivazione NOMINATA")
    report.add_check(
        CODE_MODULES, "PASS", affected_refs=list(MODULE_IDS),
        message="completezza di moduli, scenari e riconciliazioni verificata")


def check_governance(plan, report):
    """`D4` — mappa FINITA e CHIUSA, senza VERITA' NUMERICA.

    La governance porta stati e riferimenti, mai una quantita'.
    """
    governance = plan.get("governance") or {}
    if not governance:
        report.add_error(
            CODE_GOVERNANCE, ref="financial_plan.governance",
            message="sezione di governance assente: D4 esige una proiezione "
                    "canonica chiusa")
        return
    for key in sorted(governance):
        if key not in ("plan", "modules", "scenarios"):
            report.add_error(
                CODE_GOVERNANCE, ref=key,
                message=f"chiave SCONOSCIUTA in governance: {key!r}")
    entries = governance.get("modules") or {}
    for module_id in MODULE_IDS:
        if module_id not in entries:
            report.add_error(
                CODE_GOVERNANCE, ref=module_id,
                message=f"governance.modules non porta la voce {module_id!r}: "
                        "la mappa e' FINITA e CHIUSA sui quindici module_id")
    for key in sorted(entries):
        if key not in MODULE_IDS:
            report.add_error(
                CODE_GOVERNANCE, ref=key,
                message=f"chiave di modulo SCONOSCIUTA in governance.modules: "
                        f"{key!r}")
    scenarios_block = governance.get("scenarios") or {}
    if "coverage" in scenarios_block:
        report.add_error(
            CODE_GOVERNANCE, ref="coverage",
            message="governance.scenarios porta la chiave `coverage`: "
                    "`coverage` NON e' uno scenario, e' il blocco di "
                    "MISURA della copertura, i cui `ratio` e `threshold` sono "
                    "NUMERICI, e ammetterlo introdurrebbe tipi numerici in "
                    "governance")
    for scenario_id in SCENARIO_IDS:
        if scenario_id not in scenarios_block:
            report.add_error(
                CODE_GOVERNANCE, ref=scenario_id,
                message=f"governance.scenarios non porta {scenario_id!r}")
    # FRONTE COMPORTAMENTALE del divieto: nessun valore NUMERICO, e nessuna
    # chiave fuori dall'insieme DICHIARATO, a NESSUNA profondita'.
    allowed_keys = {"plan", "modules", "scenarios", "propagated_status",
                    "status", "not_applicable_reason", "input_driver_refs",
                    "driver_refs"}
    allowed_keys.update(MODULE_IDS)
    allowed_keys.update(SCENARIO_IDS)
    for path, key, value in walk_values(governance, "financial_plan.governance"):
        if key is not None and key not in allowed_keys:
            report.add_error(
                CODE_GOVERNANCE_NUMERIC, ref=path,
                message=f"campo NON DICHIARATO nella sezione di governance: "
                        f"{path} = {value!r}. La governance porta STATO e "
                        "RIFERIMENTI, MAI una quantita': una seconda fonte "
                        "numerica di verita' e' precisamente cio' che "
                        "D-04 vieta",
                expected="solo propagated_status, status, "
                         "not_applicable_reason, input_driver_refs, "
                         "driver_refs",
                actual=key)
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            report.add_error(
                CODE_GOVERNANCE_NUMERIC, ref=path,
                message=f"valore NUMERICO nella sezione di governance: "
                        f"{path} = {value!r}",
                expected="nessun tipo numerico, a nessuna profondita'",
                actual=value)
    # Uno stato SEPARATO per ogni scenario, calcolato sul PROPRIO set risolto.
    results_scenarios = (plan.get("results") or {}).get("scenarios") or {}
    for scenario_id in SCENARIO_IDS:
        entry = scenarios_block.get(scenario_id) or {}
        result = results_scenarios.get(scenario_id) or {}
        own = sorted(set(result.get("driver_refs") or []))
        declared = list(entry.get("driver_refs") or [])
        if own and declared != own:
            report.add_error(
                CODE_GOVERNANCE, ref=scenario_id,
                message=f"governance.scenarios.{scenario_id}: driver_refs "
                        f"{declared} diversi dal set risolto PROPRIO di "
                        f"quello scenario {own}: lo stato e' stato CALCOLATO "
                        "UNA VOLTA E COPIATO da un altro scenario",
                expected=own, actual=declared)
        if result.get("status") == "NOT_APPLICABLE" and \
                entry.get("status") != "NOT_APPLICABLE":
            report.add_error(
                CODE_GOVERNANCE, ref=scenario_id,
                message=f"governance.scenarios.{scenario_id}: status "
                        f"{entry.get('status')!r} mentre lo scenario NON e' "
                        "prodotto")
    # Il minimo di PIANO e' preso su TUTTI gli input consumati, RICHIESTI E
    # OPZIONALI, e COINCIDE con `validation.propagated_status`.
    validation = plan.get("validation") or {}
    plan_status = (governance.get("plan") or {}).get("propagated_status")
    if plan_status != validation.get("propagated_status"):
        report.add_error(
            CODE_GOVERNANCE, ref="financial_plan.governance.plan",
            message=f"governance.plan.propagated_status {plan_status!r} NON "
                    f"coincide con validation.propagated_status "
                    f"{validation.get('propagated_status')!r}",
            expected=validation.get("propagated_status"), actual=plan_status)
    status_by_driver = {entry.get("driver_id"): entry.get("status")
                        for entry in (plan.get("driver_registry") or {}).get(
                            "drivers") or ()}
    consumed = set()
    for entry in entries.values():
        consumed.update(entry.get("input_driver_refs") or [])
    for entry in scenarios_block.values():
        consumed.update(entry.get("driver_refs") or [])
    observed = minimum_status(
        [status_by_driver.get(ref) for ref in sorted(consumed)])
    if observed is not None and plan_status != observed:
        excluded = sorted(
            ref for ref in consumed
            if status_by_driver.get(ref) in STATUS_ORDER
            and STATUS_ORDER.index(status_by_driver[ref])
            < STATUS_ORDER.index(plan_status or STATUS_ORDER[0]))
        report.add_error(
            CODE_GOVERNANCE, ref=",".join(excluded) or "(nessun driver)",
            message=f"governance.plan.propagated_status {plan_status!r} non e' "
                    f"il MINIMO sugli input DICHIARATI e CONSUMATI, che e' "
                    f"{observed!r}: gli input ESCLUSI dal minimo sono "
                    f"{excluded}. L'asse richiesto/opzionale NON e' l'asse "
                    "della propagazione, e un caveat non e' mai riassorbito",
            expected=observed, actual=plan_status)
    report.add_check(
        CODE_GOVERNANCE, "PASS",
        affected_refs=["financial_plan.governance"],
        message="governance canonica: quindici moduli, tre scenari, nessun "
                "tipo numerico, minimo di piano coerente")


def check_readiness(plan, report):
    """`D3` — le TRE prontezze restano DISTINTE.

    `result` (l'aritmetica chiude), `propagated_status` (di che cosa sono fatti
    i numeri) e `investor_readiness` (presentabilita' a un terzo) non si
    derivano l'una dall'altra.
    """
    validation = plan.get("validation") or {}
    readiness = validation.get("investor_readiness")
    if readiness is None:
        report.add_error(
            CODE_READINESS, ref="financial_plan.validation.investor_readiness",
            message="portatore di prontezza investor-ready assente: `result` "
                    "dice che l'aritmetica chiude, `propagated_status` dice "
                    "di che cosa sono fatti i numeri, e nessuno dei due dice "
                    "se il piano e' presentabile a un terzo")
        return
    registry = plan.get("driver_registry") or {}
    scenarios = (plan.get("results") or {}).get("scenarios") or {}
    coverage = scenarios.get("coverage") or {}
    recon = plan.get("reconciliations") or {}
    governance = plan.get("governance") or {}
    predicates = [
        ("financial_plan.validation.result",
         validation.get("result") == "PASS"),
        ("financial_plan.validation.propagated_status",
         validation.get("propagated_status") == "confirmed"),
        ("financial_plan.driver_registry.unbound_required_roles",
         not (registry.get("unbound_required_roles") or [])),
        ("financial_plan.results.scenarios.coverage.level",
         coverage.get("level") != "none"),
        ("financial_plan.reconciliations",
         not [rec for rec, entry in (recon or {}).items()
              if (entry or {}).get("severity") == "FAIL"
              and (entry or {}).get("status") == "FAIL"]),
        ("financial_plan.governance.plan.propagated_status",
         (governance.get("plan") or {}).get("propagated_status")
         == "confirmed"),
    ]
    violated = [name for name, holds in predicates if not holds]
    expected = "ready" if not violated else "not_ready"
    if readiness.get("status") != expected:
        report.add_error(
            CODE_READINESS, ref=",".join(violated) or "(nessun predicato)",
            message=f"investor_readiness.status "
                    f"{readiness.get('status')!r} contro {expected!r}: la "
                    "regola CONSERVATIVA di prontezza e' congiuntiva su SEI "
                    f"predicati, e quelli VIOLATI sono {violated}. Nessun "
                    "percorso deriva la prontezza da validation.result "
                    "soltanto",
            expected=expected, actual=readiness.get("status"))
    for reason in readiness.get("blocking_reasons") or ():
        if not reason.get("code"):
            report.add_error(
                CODE_READINESS, ref="blocking_reasons",
                message="ragione di blocco PRIVA di `code`: e' PROSA, e "
                        "le ragioni di blocco devono essere TIPIZZATE, mai "
                        "prosa da re-interpretare")
        if not (reason.get("affected_refs") or []):
            report.add_error(
                CODE_READINESS, ref=str(reason.get("code")),
                message=f"la ragione di blocco {reason.get('code')!r} e' "
                        "TIPIZZATA ma NON ATTRIBUITA: affected_refs[] e' "
                        "vuoto")
    if readiness.get("status") == "ready" and (
            readiness.get("blocking_reasons") or []):
        report.add_error(
            CODE_READINESS, ref="financial_plan.validation.investor_readiness",
            message="`ready` con ragioni di blocco NON VUOTE")
    report.add_check(
        CODE_READINESS, "PASS",
        affected_refs=["financial_plan.validation.result",
                       "financial_plan.validation.propagated_status",
                       "financial_plan.validation.investor_readiness"],
        message="le TRE prontezze sono TRE campi distinti e la terza non e' "
                "derivata dalle prime")


def check_driver_carriers(plan, report):
    """`D1`, `D2` e la tracciabilita' a fonti ed evidenze."""
    registry = plan.get("driver_registry") or {}
    schema = load_json(SCHEMA_PATH, "schema del piano finanziario")
    accepted = (((load_json(SOURCE_REGISTER_PATH, "source-register").get(
        "items") or {}).get("properties") or {}).get("source_type")
        or {}).get("enum")
    declared = ((((schema.get("$defs") or {}).get("driver_entry") or {}).get(
        "properties") or {}).get("source_type") or {}).get("enum")
    if list(declared or ()) != list(accepted or ()):
        report.add_error(
            CODE_SOURCE_TYPE, ref="$defs.driver_entry.properties.source_type",
            message=f"l'enum di source_type {declared} DIVERGE da quello "
                    f"ACCETTATO di source-register.schema.json {accepted}: e' "
                    "stato CONIATO invece che RIUSATO alla lettera",
            expected=accepted, actual=declared)
    materiality_enum = ((((schema.get("$defs") or {}).get("driver_entry")
                          or {}).get("properties") or {}).get("materiality")
                        or {}).get("enum")
    previous = None
    for entry in registry.get("drivers") or ():
        driver_id = entry.get("driver_id")
        if previous is not None and str(driver_id) < previous:
            report.add_error(
                CODE_DETERMINISM, ref=str(driver_id),
                message=f"drivers[] non e' ordinato per driver_id: "
                        f"{driver_id!r} segue {previous!r}")
        previous = str(driver_id)
        if "materiality" in entry and entry["materiality"] not in (
                materiality_enum or ()):
            report.add_error(
                CODE_MATERIALITY, ref=str(driver_id),
                message=f"{driver_id}: materiality "
                        f"{entry['materiality']!r} fuori dall'enum dichiarato "
                        f"{materiality_enum}",
                expected=materiality_enum, actual=entry.get("materiality"))
        if "materiality_basis" in entry and not str(
                entry["materiality_basis"]).strip():
            report.add_error(
                CODE_MATERIALITY, ref=str(driver_id),
                message=f"{driver_id}: materiality_basis vuota: la BASE del "
                        "giudizio e' dichiarata o e' assente, mai vuota")
        if "source_type" in entry and entry["source_type"] not in (
                accepted or ()):
            report.add_error(
                CODE_SOURCE_TYPE, ref=str(driver_id),
                message=f"{driver_id}: source_type "
                        f"{entry['source_type']!r} fuori dall'enum riusato",
                expected=accepted, actual=entry.get("source_type"))
        for field in ("source_ref", "source_path", "source_record_hash"):
            if not entry.get(field):
                report.add_error(
                    CODE_TRACEABILITY, ref=str(driver_id),
                    message=f"{driver_id}: {field} assente — un valore copiato "
                            "e non tracciabile e' D-05")
    report.add_check(
        CODE_MATERIALITY, "PASS", affected_refs=["driver_entry.materiality"],
        message="D1: portatore presente, nessuna soglia numerica, assenza mai "
                "resa come «bassa»")
    report.add_check(
        CODE_SOURCE_TYPE, "PASS", affected_refs=["driver_entry.source_type"],
        message="D2: enum RIUSATO alla lettera da source-register.schema.json")


def check_use_of_proceeds(plan, report):
    """Uso dei proventi: CATEGORIE candidate, e la GUARDIA DI EQUIVALENZA."""
    schema = load_json(SCHEMA_PATH, "schema del piano finanziario")
    slot = ((((((schema.get("properties") or {}).get("financial_plan") or {})
               .get("properties") or {}).get("results") or {})
             .get("properties") or {}).get("modules") or {})
    funding_schema = (slot.get("properties") or {}).get("funding_gap") or {}
    module_result = (schema.get("$defs") or {}).get("module_result") or {}
    canon = (lambda value: json.dumps(value, sort_keys=True,
                                      ensure_ascii=True,
                                      separators=(",", ":")))
    guard = []
    if funding_schema.get("type") != module_result.get("type"):
        guard.append("`type`")
    if funding_schema.get("additionalProperties") != module_result.get(
            "additionalProperties"):
        guard.append("`additionalProperties`")
    if list(funding_schema.get("required") or ()) != list(
            module_result.get("required") or ()):
        guard.append("`required` (stessa lista, stesso ordine)")
    base_props = set(module_result.get("properties") or ())
    inline_props = set(funding_schema.get("properties") or ())
    if inline_props != base_props | {"use_of_proceeds_candidates"}:
        guard.append("insieme dei nomi di proprieta'")
    for name in sorted(base_props & inline_props):
        left = (module_result.get("properties") or {})[name]
        right = (funding_schema.get("properties") or {})[name]
        if name == "module_id":
            expected = dict(left)
            expected["const"] = "funding_gap"
            if canon(expected) != canon(right):
                guard.append("properties.module_id (eccezione 2)")
            continue
        if canon(left) != canon(right):
            guard.append(f"sottoschema condiviso {name}")
    if guard:
        report.add_error(
            CODE_USE_OF_PROCEEDS,
            ref="results.modules.funding_gap",
            message="la GUARDIA DI EQUIVALENZA STRUTTURALE dello schema "
                    f"FALLISCE: {guard}. La base inline DEVE restare allineata "
                    "a $defs.module_result sotto il solo insieme di eccezioni "
                    "DICHIARATO",
            expected="allineamento a $defs.module_result", actual=guard)
    module = ((plan.get("results") or {}).get("modules") or {}).get(
        "funding_gap") or {}
    candidates = module.get("use_of_proceeds_candidates")
    if module.get("status") != "NOT_APPLICABLE" and not candidates:
        report.add_error(
            CODE_USE_OF_PROCEEDS, ref="funding_gap",
            message="funding_gap e' prodotto ma use_of_proceeds_candidates e' "
                    "ASSENTE: il portatore canonico esiste per essere "
                    "popolato")
    for entry in candidates or ():
        for key in sorted(entry):
            if key not in ("category_id", "label", "eligibility_basis",
                           "driver_refs"):
                report.add_error(
                    CODE_USE_OF_PROCEEDS, ref=str(entry.get("category_id")),
                    message=f"campo NON DICHIARATO sulla categoria "
                            f"{entry.get('category_id')!r}: {key!r}. Sono "
                            "CATEGORIE ELEGGIBILI, non un'allocazione: nessun "
                            "importo e' associato a una categoria")
        for path, key, value in walk_values(entry, str(
                entry.get("category_id"))):
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                report.add_error(
                    CODE_USE_OF_PROCEEDS, ref=path,
                    message=f"valore NUMERICO su una categoria di uso dei "
                            f"proventi: {path} = {value!r}")
    report.add_check(
        CODE_USE_OF_PROCEEDS, "PASS", affected_refs=["funding_gap"],
        message="use_of_proceeds_candidates: categorie eleggibili, nessun "
                "importo, guardia di equivalenza strutturale superata")


def check_warning_grammar(plan, report):
    """`timing_window_empty` — grammatica ESATTA dei tre token, verificata
    per COMPORTAMENTO."""
    validation = plan.get("validation") or {}
    for index, entry in enumerate(validation.get("warnings") or ()):
        if entry.get("code") != CODE_TIMING_WINDOW_EMPTY:
            continue
        path = f"financial_plan.validation.warnings[{index}]"
        refs = list(entry.get("affected_refs") or [])
        drivers = [ref for ref in refs if TOKEN_DRIVER_RE.match(str(ref))]
        modules = [ref for ref in refs if TOKEN_MODULE_RE.match(str(ref))]
        scenarios = [ref for ref in refs if TOKEN_SCENARIO_RE.match(str(ref))]
        outside = [ref for ref in refs
                   if not (TOKEN_DRIVER_RE.match(str(ref))
                           or TOKEN_MODULE_RE.match(str(ref))
                           or TOKEN_SCENARIO_RE.match(str(ref)))]
        if len(drivers) != 1 or len(modules) != 1 or len(scenarios) != 1:
            report.add_error(
                CODE_WARNING_ATTRIBUTION, ref=path,
                message=f"{CODE_TIMING_WINDOW_EMPTY}: affected_refs {refs} "
                        "non porta ESATTAMENTE un token DRV-*, ESATTAMENTE un "
                        "token module:<id> ed ESATTAMENTE un token "
                        "scenario:<id>",
                expected="un token per ciascuna delle TRE grammatiche",
                actual=refs)
        if outside:
            report.add_error(
                CODE_WARNING_ATTRIBUTION, ref=path,
                message=f"{CODE_TIMING_WINDOW_EMPTY}: token FUORI dalle tre "
                        f"grammatiche dichiarate: {outside}",
                expected="nessun token fuori grammatica", actual=outside)
        if "severity" in entry:
            report.add_error(
                CODE_WARNING_ATTRIBUTION, ref=path,
                message="il warning porta un campo `severity`: la severita' "
                        "WARNING e' portata dall'APPARTENENZA all'array, e "
                        "nessun campo e' aggiunto")
        message = str(entry.get("message") or "")
        prose = [token for token in ("scenario:", "module:") if token in
                 message]
        if TOKEN_DRIVER_RE.search(message) or re.search(r"DRV-[0-9]{3}",
                                                        message):
            prose.append("DRV-*")
        if prose:
            report.add_error(
                CODE_WARNING_ATTRIBUTION, ref=path,
                message=f"attribuzione messa in PROSA nel campo `message` "
                        f"invece che nel token tipizzato: {prose}. E' "
                        "«prosa da re-interpretare», e l'attribuzione vive "
                        "SOLO nei token tipizzati",
                expected="attribuzione SOLO in affected_refs[]", actual=prose)
    report.add_check(
        CODE_WARNING_ATTRIBUTION, "PASS",
        affected_refs=["financial_plan.validation.warnings"],
        message="grammatica dei token di timing_window_empty verificata per "
                "COMPORTAMENTO, non per dichiarazione")


def check_no_silent_assumption(plan, report):
    validation = plan.get("validation") or {}
    registry = plan.get("driver_registry") or {}
    statuses = [entry.get("status") for entry in registry.get("drivers") or ()]
    observed = minimum_status(statuses)
    propagated = validation.get("propagated_status")
    if observed is not None and propagated is not None:
        if STATUS_ORDER.index(propagated) > STATUS_ORDER.index(observed):
            weaker = sorted(entry.get("driver_id")
                            for entry in registry.get("drivers") or ()
                            if entry.get("status") in STATUS_ORDER
                            and STATUS_ORDER.index(entry["status"])
                            < STATUS_ORDER.index(propagated))
            report.add_error(
                CODE_SILENT_ASSUMPTION, ref=",".join(weaker),
                message=f"validation.propagated_status {propagated!r} e' PIU' "
                        f"ALTO del minimo {observed!r} degli stati dei driver "
                        f"del registro: il caveat portato da {weaker} e' stato "
                        "RIASSORBITO in un esito piu' pulito del vero",
                expected=observed, actual=propagated)
    if validation.get("result") == "PASS":
        for entry in validation.get("warnings") or ():
            if entry.get("code") == CODE_TIMING_WINDOW_EMPTY:
                report.add_error(
                    CODE_SILENT_ASSUMPTION, ref=str(entry.get("code")),
                    message="validation.result e' PASS mentre una finestra di "
                            "timing e' SVUOTATA: l'esito non puo' essere piu' "
                            "pulito dei propri caveat")
    report.add_check(
        CODE_SILENT_ASSUMPTION, "PASS",
        affected_refs=["financial_plan.validation.propagated_status"],
        message="nessun caveat riassorbito; unbound_required_roles[] "
                "nominativo")


def check_stage_boundary(document, report):
    for path, key, value in walk_values(document, "financial_plan"):
        if key in STAGE11_FORBIDDEN_KEYS:
            report.add_error(
                CODE_STAGE_BOUNDARY, ref=path,
                message=f"chiave di STAGE 11 nel canonico dello Stage 10: "
                        f"{key!r}. Lo Stage 10 si ferma al FABBISOGNO; "
                        "importo richiesto, strumento, valutazione e termini "
                        "sono Stage 11")
    report.add_check(
        CODE_STAGE_BOUNDARY, "PASS",
        affected_refs=list(STAGE11_FORBIDDEN_KEYS),
        message="nessuna chiave di Stage 11 o Stage 12 nel canonico")


def check_no_recompute(report):
    """Divieto di ricalcolo sul COSTRUTTORE DI PRODUZIONE, con AUTO-SONDA
    obbligatoria."""
    probe = self_probe_findings()
    if not probe:
        report.add_error(
            CODE_NO_RECOMPUTE, ref="<auto-sonda AST>",
            message="l'AUTO-SONDA non ha rilevato la violazione INIETTATA nel "
                    "sorgente sintetico: il rilevatore AST e' VACUO e la "
                    "scansione del costruttore non prova nulla")
    if not BUILDER_PATH.is_file():
        report.add_error(
            CODE_NO_RECOMPUTE, ref=BUILDER_REL,
            message="il costruttore canonico e' assente: la scansione del "
                    "divieto di ricalcolo non e' eseguibile")
        return
    findings = scan_forbidden_recomputation(
        BUILDER_PATH.read_text(encoding="utf-8"), label=BUILDER_REL)
    for finding in findings:
        report.add_error(
            CODE_NO_RECOMPUTE, ref=finding.split(":")[1] if ":" in finding
            else BUILDER_REL,
            message=finding)
    report.add_check(
        CODE_NO_RECOMPUTE, "FAIL" if findings else "PASS",
        affected_refs=[BUILDER_REL],
        message=f"scansione statica del costruttore: {len(findings)} rilievi; "
                f"auto-sonda del rilevatore: {len(probe)} rilievi sul "
                "sorgente sintetico")


def check_determinism(document, path, report):
    text = Path(path).read_text(encoding="utf-8")
    rebuilt = canonical_json(document)
    if text != rebuilt:
        report.add_error(
            CODE_DETERMINISM, ref=str(path),
            message="il documento sul disco NON e' nella forma canonica "
                    "deterministica (chiavi ordinate, indentazione 2, "
                    "ensure_ascii, newline finale): due esecuzioni non "
                    "sarebbero byte-identiche",
            expected="forma canonica deterministica", actual="divergente")
    report.add_check(
        CODE_DETERMINISM, "PASS", affected_refs=[str(path)],
        message="forma canonica deterministica verificata sul documento reale")


def check_stale(document, payload_path, report):
    if payload_path is None:
        return
    payload = load_json(payload_path, "payload del motore")
    expected = ((((payload.get("financial_payload") or {}).get(
        "calculation_metadata") or {}).get("output_checksums")) or {}).get(
            "base")
    observed = ((((document.get("financial_plan") or {}).get(
        "calculation_metadata") or {}).get("output_checksums")) or {}).get(
            "base")
    if expected and observed and expected != observed:
        report.add_error(
            CODE_STALE, ref="calculation_metadata.output_checksums.base",
            message=f"documento canonico STANTIO: porta il checksum "
                    f"{observed!r} mentre il payload corrente porta "
                    f"{expected!r}. Un documento il cui checksum non coincide "
                    "col payload e' RIGENERATO, mai letto. Classificarlo "
                    "WARNING e' un FALLIMENTO del contratto: la severita' e' "
                    "FAIL",
            expected=expected, actual=observed)
    report.add_check(
        CODE_STALE, "PASS",
        affected_refs=["calculation_metadata.output_checksums.base"],
        message="freschezza del documento verificata contro il payload del "
                "motore")


def check_blocked_run(plan, report):
    validation = plan.get("validation") or {}
    if validation.get("result") == "FAIL":
        report.add_error(
            CODE_BLOCKED_RUN, ref="financial_plan.validation.result",
            message="un documento canonico ESISTE per una run BLOCCATA "
                    "(validation.result == FAIL): il payload non valido per "
                    "schema deve restare CONFINATO al percorso di "
                    "fallimento, e nessun file — nemmeno parziale, nemmeno "
                    "nel candidate — deve essere scritto")


def check_real_project(canonical, report):
    """Guardia sulla directory della skill.

    Se il documento canonico risolto cade dentro `SKILL_ROOT`, il validator
    registra un errore `real_project_write_forbidden`: i progetti vivono
    nella working directory dell'utente, mai nel pacchetto. In ogni altra
    posizione la guardia non interviene. Decide solo sul path, non dipende
    da dove la skill e' installata.
    """
    projects = SKILL_ROOT
    try:
        Path(canonical).resolve().relative_to(projects)
    except ValueError:
        return
    report.add_error(
        CODE_REAL_PROJECT, ref=str(canonical),
        message="documento canonico dentro la directory della skill: il "
                "pacchetto non e' mai scritto dalla generazione, e i progetti "
                "dell'utente vivono nella sua working directory")


# --------------------------------------------------------------------------
# Corpo del validator
# --------------------------------------------------------------------------


def check_output(args, report, canonical_arg, payload_arg):
    if canonical_arg:
        canonical = Path(canonical_arg)
    elif args.candidate:
        canonical = Path(args.candidate).joinpath(CANONICAL_NAME)
    else:
        # In phase=impact ne' --canonical ne' --candidate sono mai passati
        # (`_framework.py` vieta --candidate in questa fase). La TERZA
        # sorgente e' la superficie canonica PERSISTITA del progetto, la
        # stessa che gli altri validator di dominio gia' usano
        # (project / "<stage>/structured-output.json"). Nessuna seconda sede
        # e' inventata: si riusano SOLO le costanti gia' dichiarate qui sopra.
        canonical = args.project / STAGE10 / CANONICAL_NAME
    check_real_project(canonical, report)
    document = load_json(canonical, "documento canonico")
    schema = load_json(SCHEMA_PATH, "schema del piano finanziario")
    check_schema(document, schema, report)
    plan = document.get("financial_plan") or {}
    check_blocked_run(plan, report)
    check_profile(plan, report)
    check_modules_and_scenarios(plan, report)
    check_governance(plan, report)
    check_readiness(plan, report)
    check_driver_carriers(plan, report)
    check_use_of_proceeds(plan, report)
    check_warning_grammar(plan, report)
    check_no_silent_assumption(plan, report)
    check_stage_boundary(document, report)
    check_no_recompute(report)
    check_determinism(document, canonical, report)
    check_stale(document, payload_arg, report)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    pre = argparse.ArgumentParser(prog=VALIDATOR_NAME, add_help=False)
    pre.add_argument("--canonical")
    pre.add_argument("--engine-payload")
    try:
        known, rest = pre.parse_known_args(argv)
    except SystemExit:
        print(f"{VALIDATOR_NAME}: argomenti CLI non validi", file=sys.stderr)
        return fw.EXIT_USAGE

    def check_fn(args, config, state, report):
        del config, state
        if args.stage != STAGE10:
            raise fw.ValidatorUsageError(
                f"stage non pertinente a {VALIDATOR_NAME}: {args.stage} "
                f"(atteso {STAGE10})")
        if args.phase not in SUPPORTED_PHASES:
            raise fw.ValidatorUsageError(
                f"--phase non ammessa per {VALIDATOR_NAME}: {args.phase} "
                f"(ammesse: {SUPPORTED_PHASES})")
        check_output(args, report, known.canonical, known.engine_payload)

    fw.run_validator(VALIDATOR_NAME, check_fn, rest)
    return fw.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
