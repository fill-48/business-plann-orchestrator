#!/usr/bin/env python3
"""Shared helpers for the stateful integration tests.

Not a test file (the runner only picks up test_*.py). Provides temp-project
scaffolding, module loading from the skill package, validator CLI invocation
and tree snapshots for purity/no-mutation assertions.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

SKILL_REL = ".claude/skills/business-plan-orchestrator"
VALIDATORS_REL = f"{SKILL_REL}/validators"
TRANSACTION_REL = f"{SKILL_REL}/transaction"
CONFIG_REL = f"{SKILL_REL}/config/enforcement-config.json"

STAGES = [
    "00_idea-discovery",
    "01_problem-and-need",
    "02_customer-segmentation",
    "03_value-proposition",
    "04_market-and-competition",
    "05_business-model",
    "06_go-to-market",
]


def load_module(root, rel_dir, name):
    """Import a module by filename from the skill package (dirs have dashes)."""
    path = Path(root) / rel_dir / f"{name}.py"
    if not path.exists():
        raise FileNotFoundError(f"missing module: {rel_dir}/{name}.py")
    for candidate_dir in (Path(root) / VALIDATORS_REL,
                          Path(root) / TRANSACTION_REL):
        d = str(candidate_dir)
        if candidate_dir.is_dir() and d not in sys.path:
            sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def base_assumption(idx, **over):
    entry = {
        "id": f"ASS-{idx:03d}",
        "category": "pricing",
        "variable": f"var_{idx:03d}",
        "statement": f"Assunzione {idx}",
        "value": 10.0 * idx,
        "display_value": f"{10.0 * idx} EUR",
        "unit": "EUR",
        "source": "Founder interview",
        "owner": "founder",
        "confidence": "low",
        "validation_status": "unvalidated",
        "affected_sections": ["00_idea-discovery"],
        "last_updated": "2026-07-15",
        "previous_values": [],
    }
    entry.update(over)
    return entry


def project_status_text(project_name, current_stage, status, completed,
                        extra=None):
    completed_json = json.dumps(completed)
    lines = [
        "---",
        f"project_name: {project_name}",
        f'current_stage: "{current_stage}"',
        'current_task: "stage-work"',
        f'status: "{status}"',
        f"completed_stages: {completed_json}",
        'pending_stages: []',
        "approved_decisions: []",
        "open_questions: []",
        "critical_assumptions: []",
        "blocking_issues: []",
        'last_updated: "2026-07-15"',
        'next_action: "test fixture"',
    ]
    if extra:
        for key, value in extra.items():
            lines.append(f"{key}: {json.dumps(value)}")
    lines += ["---", "", f"# Project Status — {project_name}", ""]
    return "\n".join(lines) + "\n"


def make_project(base, name="tx-test-project", current_stage="00_idea-discovery",
                 status="approved", completed=None, assumptions=None,
                 conditions=None, evidence=None):
    project = Path(base) / name
    shared = project / "shared"
    shared.mkdir(parents=True)
    if completed is None:
        completed = ["00_idea-discovery"]
    if assumptions is None:
        assumptions = [base_assumption(1), base_assumption(2)]
    write_json(shared / "assumptions-register.json", assumptions)
    write_json(shared / "conditions-register.json", conditions or [])
    write_json(shared / "evidence-register.json", evidence or [])
    (shared / "decision-log.md").write_text("# Decision Log\n", encoding="utf-8")
    (shared / "project-status.md").write_text(
        project_status_text(name, current_stage, status, completed),
        encoding="utf-8")
    for stage in STAGES:
        (project / stage).mkdir(exist_ok=True)
    (project / "00_idea-discovery" / "handoff.md").write_text(
        "# Handoff\n\nnext_action: Stage 1\n", encoding="utf-8")
    return project


def make_candidate(project, stage, tx_id="tx-test-001", structured=None,
                   proposed=None, handoff="# Handoff\n"):
    candidate = project / stage / ".working" / tx_id
    candidate.mkdir(parents=True)
    if structured is not None:
        write_json(candidate / "structured-output.json", structured)
    if proposed is not None:
        write_json(candidate / "proposed-assumptions.json", proposed)
    (candidate / "handoff.md").write_text(handoff, encoding="utf-8")
    return candidate


def snapshot_tree(path):
    """Map of relative file path -> sha256, for no-mutation assertions."""
    out = {}
    for p in sorted(Path(path).rglob("*")):
        if p.is_file():
            out[p.relative_to(path).as_posix()] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return out


def run_validator_cli(root, name, project=None, stage=None, phase=None,
                      candidate=None, extra=None):
    """Invoke a validator exactly as the workflows do. Returns (exit, out, err)."""
    cmd = [sys.executable, str(Path(root) / VALIDATORS_REL / f"{name}.py")]
    if project is not None:
        cmd += ["--project", str(project)]
    if candidate is not None:
        cmd += ["--candidate", str(candidate)]
    if stage is not None:
        cmd += ["--stage", stage]
    if phase is not None:
        cmd += ["--phase", phase]
    if extra:
        cmd += list(extra)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    return proc.returncode, proc.stdout, proc.stderr


def run_tm_cli(root, *args, env_extra=None):
    """Invoke the transaction manager CLI. Returns (exit, stdout, stderr)."""
    cmd = [sys.executable,
           str(Path(root) / TRANSACTION_REL / "transaction_manager.py")]
    cmd += [str(a) for a in args]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    return proc.returncode, proc.stdout, proc.stderr


def tm_result(stdout, label=""):
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        raise AssertionError(
            f"{label}: transaction manager stdout is not JSON: {stdout!r}")
    if "result" not in result:
        raise AssertionError(f"{label}: TM output missing 'result'")
    return result


def find_journals(project):
    tx_dir = Path(project) / "shared" / ".tx"
    if not tx_dir.is_dir():
        return []
    return sorted(p for p in tx_dir.glob("*.json") if p.is_file())


def snapshot_canonical(project):
    """Tree snapshot excluding transactional/ephemeral/append-only areas."""
    out = {}
    for rel, digest in snapshot_tree(project).items():
        if rel.startswith("shared/.tx/") or "/.working/" in rel:
            continue
        if rel == "shared/audit-log.jsonl":
            continue
        out[rel] = digest
    return out


def parse_report(stdout, label=""):
    try:
        report = json.loads(stdout)
    except json.JSONDecodeError:
        raise AssertionError(
            f"{label}: validator stdout is not a JSON report: {stdout!r}")
    for key in ("result", "validator", "stage", "phase", "errors",
                "warnings", "affected_refs"):
        if key not in report:
            raise AssertionError(f"{label}: report missing key {key}")
    if report["result"] == "WARNING" and report["errors"]:
        raise AssertionError(f"{label}: WARNING must imply empty errors")
    if report["errors"] and report["result"] != "FAIL":
        raise AssertionError(f"{label}: errors imply result FAIL")
    return report


# ---------------------------------------------------------------------------
# Fixture sintetiche F-1 ... F-13 dello Stage 10 (financial plan).
#
# Sede unica: questo modulo e nessun altro; nessun modulo di fixture adiacente
# duplica o estende il registro.
#
# Le fixture sono DATI DI CASO DI TEST, non un progetto reale: nessuna entra in
# un progetto reale e nessun valore di fixture compare in un output di piano.
# Dichiarare una fixture sintetica non è «inventare dati»: è dichiarare che il
# caso di test è costruito, esattamente come fa make_project.
#
# Questo blocco è ADDITIVO e PURAMENTE DICHIARATIVO: non calcola nulla, non
# implementa alcun validator finanziario, non entra nel runner (il runner
# raccoglie solo tests/integration/test_*.py) e non scrive in alcun progetto reale.
# ---------------------------------------------------------------------------

STAGE10_REL = "10_financial-plan"

#: Le sei chiavi `required` di `financial_config`. Nessun fallback di
#: runtime esiste per esse: l'assenza di una qualunque è
#: `financial_config_invalid` -> FAIL, con le chiavi mancanti NOMINATE.
FINANCIAL_CONFIG_REQUIRED_KEYS = (
    "financial_profile",
    "anchor_date",
    "frequency",
    "horizon_periods",
    "currency",
    "calculation_policy_version",
)

#: Le quattro `validation_status` e le sette classi di evidenza (sei classi
#: canoniche più l'assenza) che la mappatura di stato TOTALE deve decidere.
VALIDATION_STATUSES = ("unvalidated", "validated", "needs_info", "rejected")
EVIDENCE_CLASSES = (
    "verified_fact",
    "internal_evidence",
    "external_source",
    "founder_assumption",
    "model_estimate",
    "missing_information",
)


def _driver_binding(driver_id, role, driver_class, measure_kind, unit,
                    **over):
    """Voce di binding/registry minima del driver registry.

    Contiene SOLO riferimenti e metadati: nessun `base_value`, nessun
    `scenario_values`, nessuna copia della derivazione.
    """
    entry = {
        "driver_id": driver_id,
        "semantic_name": role,
        "driver_class": driver_class,
        "role": role,
        "source_ref": "ASS-001",
        "source_path": "milestone_plan.financial_plan_inputs.pricing_ref",
        "source_record_hash": "0" * 64,
        "unit": unit,
        "currency": "EUR" if unit.startswith("EUR") else None,
        "measure_kind": measure_kind,
        "frequency": "annual",
        "conversion_policy": "allocate",
        "timing_rule": "uniform",
        "start_period": 0,
        "end_period": 11,
        "scenario_polarity": "revenue_like",
        "status": "inferred",
        "source_priority": 10,
        "binding_method": "fpi_declared",
        "double_count_risk": "none",
        "input_kind": "operational",
    }
    entry.update(over)
    return entry


def scenario_triplet(ref, base, downside, upside, unit="EUR", **over):
    """Record `ASS-*` con la terna di scenario DIFFERENZIATA.

    Tre serie identiche con tre etichette diverse sono un difetto, non una
    semplificazione: la terna di questa fixture è deliberatamente distinta.
    """
    entry = base_assumption(1, id=ref, variable=f"var_{ref.lower()}",
                            value=base, unit=unit,
                            display_value=f"{base} {unit}")
    entry.update({
        "base_case": base,
        "downside_case": downside,
        "upside_case": upside,
    })
    entry.update(over)
    return entry


def fixture_f1_full_scenario_coverage():
    """F-1 — copertura di scenario PIENA su tutti i driver richiesti."""
    roles = (
        ("DRV-001", "unit_price", "pricing", "per_unit", "EUR/count"),
        ("DRV-002", "customer_volume", "volume", "stock", "count"),
        ("DRV-003", "churn_rate", "churn", "rate", "ratio"),
        ("DRV-004", "variable_cost", "cogs", "per_unit", "EUR/count"),
        ("DRV-005", "headcount", "headcount", "stock", "FTE"),
        ("DRV-006", "payroll_unit_cost", "payroll", "per_unit", "EUR/FTE"),
        ("DRV-007", "opex", "opex", "flow", "EUR"),
    )
    drivers = []
    assumptions = []
    for index, (drv, role, klass, kind, unit) in enumerate(roles, start=1):
        ref = f"ASS-{index:03d}"
        drivers.append(_driver_binding(
            drv, role, klass, kind, unit, source_ref=ref,
            scenario_polarity="cost_like" if klass in (
                "churn", "cogs", "payroll", "opex") else "revenue_like",
            scenario_coverage="full"))
        assumptions.append(scenario_triplet(
            ref, base=100 + index, downside=90 + index, upside=110 + index,
            unit=unit))
    return {
        "fixture_id": "F-1",
        "covers": "copertura di scenario piena",
        "profile_id": "subscription_saas",
        "assumptions": assumptions,
        "driver_registry": {"drivers": drivers},
        "expected_coverage": {"level": "full", "ratio": 1.0,
                              "uncovered_driver_refs": []},
    }


def fixture_f2_partial_scenario_coverage():
    """F-2 — copertura PARZIALE: metà dei driver richiesti ha la terna."""
    full = fixture_f1_full_scenario_coverage()
    drivers = json.loads(json.dumps(full["driver_registry"]["drivers"]))
    assumptions = json.loads(json.dumps(full["assumptions"]))
    uncovered = []
    for position, driver in enumerate(drivers):
        if position % 2:
            driver["scenario_coverage"] = "none"
            uncovered.append(driver["driver_id"])
            for record in assumptions:
                if record["id"] == driver["source_ref"]:
                    for key in ("base_case", "downside_case", "upside_case"):
                        record.pop(key, None)
    covered = len(drivers) - len(uncovered)
    return {
        "fixture_id": "F-2",
        "covers": "copertura di scenario parziale",
        "profile_id": "subscription_saas",
        "assumptions": assumptions,
        "driver_registry": {"drivers": drivers},
        "expected_coverage": {"level": "partial",
                              "ratio": covered / len(drivers),
                              "uncovered_driver_refs": uncovered},
    }


def fixture_f3_no_scenario_coverage():
    """F-3 — copertura NULLA: nessun driver richiesto ha la terna.

    È la forma della fixture demo, dove 0 driver su 8 legati dalla FPI hanno
    una terna. Downside e Upside sono `NOT_APPLICABLE`: non prodotti e non
    etichettati.
    """
    full = fixture_f1_full_scenario_coverage()
    drivers = json.loads(json.dumps(full["driver_registry"]["drivers"]))
    assumptions = json.loads(json.dumps(full["assumptions"]))
    for driver in drivers:
        driver["scenario_coverage"] = "none"
    for record in assumptions:
        for key in ("base_case", "downside_case", "upside_case"):
            record.pop(key, None)
    return {
        "fixture_id": "F-3",
        "covers": "copertura di scenario nulla",
        "profile_id": "subscription_saas",
        "assumptions": assumptions,
        "driver_registry": {"drivers": drivers},
        "expected_coverage": {
            "level": "none", "ratio": 0.0,
            "uncovered_driver_refs": [d["driver_id"] for d in drivers]},
        "expected_scenarios": {"downside": "NOT_APPLICABLE",
                               "upside": "NOT_APPLICABLE"},
    }


def fixture_f4_headcount_periods():
    """F-4 — driver `headcount` CON periodi dichiarati e variante SENZA.

    Nessun parsing euristico di "Y1H2", "Y1" o simili è ammesso: in assenza di
    `start_period`/`end_period` l'esito atteso è `driver_period_undeclared`
    (nessuna euristica sulle etichette di periodo).
    """
    declared = _driver_binding(
        "DRV-005", "headcount", "headcount", "stock", "FTE",
        source_ref="ASS-005", conversion_policy="carry_level",
        timing_rule="constant", frequency="annual",
        scenario_polarity="cost_like", start_period=6, end_period=35)
    undeclared = json.loads(json.dumps(declared))
    undeclared["start_period"] = None
    undeclared["end_period"] = None
    return {
        "fixture_id": "F-4",
        "covers": "timing dell'organico",
        "declared": declared,
        "undeclared": undeclared,
        "upstream_period_label": "Y1H2",
        "expected_code_on_undeclared": "driver_period_undeclared",
    }


def fixture_f5_stock_vs_flow():
    """F-5 — stesso volume, STESSI NUMERI, dichiarato una volta `stock` e una
    volta `flow`.

    È l'ambiguità che nessuna riconciliazione rileva: `REC-01` torna in
    entrambi i casi. La dichiarazione di `measure_kind` è quindi obbligatoria
    e verificata contro `role_measure_kind` del profilo; dove l'interpretazione
    upstream non è univoca, richiede un `decision_ref`.
    """
    shared = base_assumption(24, id="ASS-024", variable="funnel_customers",
                             value=1200, unit="count",
                             display_value="1200 count", period="Y1")
    as_stock = _driver_binding(
        "DRV-002", "customer_volume", "volume", "stock", "count",
        source_ref="ASS-024",
        source_path="milestone_plan.financial_plan_inputs.funnel_customers_ref",
        conversion_policy="carry_level", timing_rule="constant",
        decision_ref="DEC-001")
    as_flow = json.loads(json.dumps(as_stock))
    as_flow.update({"measure_kind": "flow", "conversion_policy": "allocate",
                    "timing_rule": "uniform", "decision_ref": "DEC-002"})
    without_decision = json.loads(json.dumps(as_stock))
    without_decision["decision_ref"] = None
    return {
        "fixture_id": "F-5",
        "covers": "ambiguità stock/flusso, con lo stesso numero canonico",
        "assumption": shared,
        "as_stock": as_stock,
        "as_flow": as_flow,
        "without_decision_ref": without_decision,
        "profile_role_measure_kind": {"customer_volume": "stock"},
        "expected_code_on_incoherent_declaration": "driver_measure_undeclared",
        "expected_code_on_missing_decision_ref": "driver_measure_undeclared",
    }


def fixture_f6_rate_conversion():
    """F-6 — tasso annuo con `compound` e variante `allocate`.

    La divisione sottostima il tasso in direzione sistematicamente favorevole
    al piano, ed è invisibile alle riconciliazioni: `REC-01`, `REC-05` e
    `REC-11` tornano esattamente, perché l'errore è a MONTE delle identità.
    """
    record = base_assumption(27, id="ASS-027", variable="churn_annual",
                             value=0.16, unit="ratio",
                             display_value="0.16 ratio", category="retention")
    compound = _driver_binding(
        "DRV-003", "churn_rate", "churn", "rate", "ratio",
        source_ref="ASS-027",
        source_path="milestone_plan.financial_plan_inputs.churn_ref",
        currency=None, conversion_policy="compound",
        timing_rule="NOT_APPLICABLE", scenario_polarity="cost_like",
        start_period=None, end_period=None)
    allocate = json.loads(json.dumps(compound))
    allocate["conversion_policy"] = "allocate"
    return {
        "fixture_id": "F-6",
        "covers": "conversione dei tassi",
        "assumption": record,
        "compound": compound,
        "allocate": allocate,
        "declared_formula": "r_p = 1 - (1 - r_a) ** (p / a)",
        "expected_code_on_incoherent_policy":
            "driver_conversion_policy_undeclared",
    }


def fixture_f7_opex_categories():
    """F-7 — tre categorie opex distinte, e variante con un costo in DUE.

    La difesa contro il doppio conteggio non è un controllo a valle: è rendere
    le categorie mutuamente esclusive e poi misurare il residuo (`REC-13`).
    """
    distinct = [
        {"line_id": "OPEX-01", "category": "operating_cost",
         "driver_refs": ["DRV-007"], "series": {"0": 1000}},
        {"line_id": "OPEX-02", "category": "interest",
         "driver_refs": ["DRV-008"], "series": {"0": 200}},
        {"line_id": "OPEX-03", "category": "mandatory_financing_fee",
         "driver_refs": ["DRV-009"], "series": {"0": 50}},
    ]
    double_counted = json.loads(json.dumps(distinct))
    double_counted.append({"line_id": "OPEX-04", "category": "interest",
                           "driver_refs": ["DRV-007"], "series": {"0": 1000}})
    return {
        "fixture_id": "F-7",
        "covers": "doppio conteggio fra categorie di costo",
        "distinct": distinct,
        "double_counted": double_counted,
        "double_counted_driver_ref": "DRV-007",
        "expected_code_on_double_count": "milestone_cost_double_counted",
        "reconciliations": ["REC-04", "REC-13"],
    }


def fixture_f8_binding_escape_hatches():
    """F-8 — le tre vie di fuga del binding.

    Nessun binding è accettato sulla sola compatibilità di unità: è la
    proprietà che distingue «il riferimento esiste» da «il riferimento
    significa questo»: il binding verifica il significato, non solo
    l'esistenza del riferimento.
    """
    unresolvable = _driver_binding(
        "DRV-010", "unit_price", "pricing", "per_unit", "EUR/count",
        source_ref="ASS-015", source_path="business_model.does_not_exist")
    mismatched = _driver_binding(
        "DRV-011", "unit_price", "pricing", "per_unit", "EUR/count",
        source_ref="ASS-015",
        source_path="business_model.contribution_margin_ref",
        binding_method="upstream_field")
    explicit_without_decision = _driver_binding(
        "DRV-012", "payroll_unit_cost", "payroll", "per_unit", "EUR/FTE",
        source_ref="ASS-034", source_path="explicit",
        binding_method="explicit_declaration", decision_ref=None,
        scenario_polarity="cost_like")
    explicit_justified = json.loads(json.dumps(explicit_without_decision))
    explicit_justified.update({
        "decision_ref": "DEC-003",
        "exhaustive_search": [
            "05_business-model/structured-output.json",
            "08_team-and-governance/structured-output.json",
        ],
        "rationale": "nessun percorso canonico risolve il ruolo",
    })
    return {
        "fixture_id": "F-8",
        "covers": "vie di fuga del binding",
        "source_path_missing": unresolvable,
        "source_path_resolves_elsewhere": mismatched,
        "resolved_elsewhere_to": "ASS-018",
        "explicit_declaration_without_decision_ref":
            explicit_without_decision,
        "explicit_declaration_justified": explicit_justified,
        "expected_code_on_path": "driver_source_path_unverifiable",
        "expected_code_on_explicit":
            "driver_explicit_declaration_unjustified",
    }


def fixture_f9_status_matrix():
    """F-9 — ogni combinazione `validation_status` x `evidence_classification`,
    inclusi l'assenza della classe e un valore FUORI enum.

    La mappatura è una funzione TOTALE e fail-closed: la combinazione ignota
    non ha un ramo permissivo, ha `driver_status_unmappable` -> FAIL.
    """
    records = []
    index = 0
    for status in VALIDATION_STATUSES:
        for evidence in EVIDENCE_CLASSES + (None, "not_an_evidence_class"):
            index += 1
            record = base_assumption(index, id=f"ASS-{index:03d}",
                                     validation_status=status)
            if evidence is None:
                record.pop("evidence_classification", None)
            else:
                record["evidence_classification"] = evidence
            records.append(record)
    null_valued = base_assumption(index + 1, id=f"ASS-{index + 1:03d}",
                                  value=None, display_value="")
    null_valued["evidence_classification"] = "founder_assumption"
    records.append(null_valued)
    return {
        "fixture_id": "F-9",
        "covers": "mappatura di stato totale",
        "records": records,
        "combinations": len(records),
        "out_of_enum_value": "not_an_evidence_class",
        "expected_code_on_unmappable": "driver_status_unmappable",
        "status_order": ["unresolved", "placeholder", "inferred", "confirmed"],
    }


def fixture_f10_pnl_to_cash_bridge():
    """F-10 — ponte P&L -> cassa NON banale, con una voce di raccordo.

    Senza una voce di raccordo `REC-06` non discrimina: torna per costruzione
    e non dimostra nulla.
    """
    return {
        "fixture_id": "F-10",
        "covers": "REC-06 discriminante",
        "pnl_series": {"0": -500, "1": -300, "2": 100},
        "bridge_items": [
            {"item_id": "BRG-01", "label": "variazione crediti verso clienti",
             "series": {"0": -120, "1": 40, "2": 30}},
            {"item_id": "BRG-02", "label": "variazione debiti verso fornitori",
             "series": {"0": 60, "1": -20, "2": -10}},
        ],
        "cash_delta_series": {"0": -560, "1": -280, "2": 120},
        "reconciliation": "REC-06",
    }


def financial_config(**over):
    """`financial_config` VALIDO: le sei chiavi `required` più le opzionali
    eventualmente sovrascritte."""
    config = {
        "financial_profile": "subscription_saas",
        "anchor_date": "2026-01-01",
        "frequency": "monthly",
        "horizon_periods": 36,
        "currency": "EUR",
        "calculation_policy_version": "1.0.0",
    }
    config.update(over)
    return config


def fixture_f11_financial_config():
    """F-11 — `financial_config` VALIDO, ASSENTE e INVALIDO.

    Le tre varianti sono distinte perché i tre esiti lo sono: assente è
    `financial_config_missing`, privo di una chiave `required` è
    `financial_config_invalid` con le chiavi mancanti NOMINATE, e in nessuno
    dei due casi un valore è sostituito. `generic_startup`, `monthly` e
    36 periodi sono valori di INIZIALIZZAZIONE del template, mai fallback di
    runtime.
    """
    valid = financial_config()
    invalid_missing_key = {key: value for key, value in valid.items()
                           if key != "frequency"}
    invalid_unknown_key = dict(valid, unexpected_key="whatever")
    invalid_profile = dict(valid, financial_profile="not_a_profile")
    return {
        "fixture_id": "F-11",
        "covers": "configurazione finanziaria",
        "valid": valid,
        "absent": None,
        "invalid_missing_required_key": invalid_missing_key,
        "missing_required_key": "frequency",
        "invalid_unknown_key": invalid_unknown_key,
        "invalid_profile_outside_enum": invalid_profile,
        "required_keys": list(FINANCIAL_CONFIG_REQUIRED_KEYS),
        "expected_code_on_absent": "financial_config_missing",
        "expected_code_on_invalid": "financial_config_invalid",
        "no_runtime_fallback": True,
    }


def fixture_f12_complete_canonical_state():
    """F-12 — stato canonico COMPLETO con tutti i moduli calcolati dal motore,
    più la variante in cui un modulo opzionale è `NOT_APPLICABLE` DICHIARATO.
    `balance_sheet` è l'omissione dichiarata: il suo `decision_ref` è il
    valore fissato dallo schema del financial plan.

    Un modulo assente da un output si legge come «non pertinente», mentre la
    verità è «non è stato calcolato»: l'omissione è quindi sempre nominata.
    """
    modules = [
        "revenue", "cogs", "gross_margin", "headcount", "payroll", "opex",
        "pnl", "cash_flow", "runway", "cash_buffer", "break_even",
        "funding_gap", "milestone_coverage", "kpi",
    ]
    complete = {name: {"module_id": name, "status": "PASS"}
                for name in modules}
    complete["balance_sheet"] = {
        "module_id": "balance_sheet",
        "status": "NOT_APPLICABLE",
        "reason": "stato patrimoniale non calcolato: omissione dichiarata",
        "decision_ref": "DEC-S10-23",
    }
    with_optional_na = json.loads(json.dumps(complete))
    with_optional_na["cash_buffer"] = {
        "module_id": "cash_buffer",
        "status": "NOT_APPLICABLE",
        "not_applicable_reason":
            "cash_buffer_policy non dichiarata in financial_config",
    }
    return {
        "fixture_id": "F-12",
        "covers": "struttura completa e struttura con NOT_APPLICABLE visibile",
        "complete": complete,
        "with_optional_not_applicable": with_optional_na,
        "first_slice_modules": modules + ["balance_sheet"],
        "named_not_applicable_modules": ["balance_sheet"],
    }


def fixture_f13_divergent_derived_artifacts():
    """F-13 — derivati DELIBERATAMENTE divergenti dal canonico.

    Cinque divergenze, una per ciascun modo in cui un derivato può raccontare
    una storia diversa dal canonico. Nessun artefatto derivato è scritto qui:
    la fixture DICHIARA i casi, non li produce — li producono il renderer
    del capitolo e l'exporter del workbook.
    """
    canonical_checksum = "a" * 64
    return {
        "fixture_id": "F-13",
        "covers": "i codici di FAIL dei derivati e il divieto di hardcode",
        "canonical_source_checksum": canonical_checksum,
        "cases": [
            {"case": "a", "artifact": "chapter",
             "defect": "sezione obbligatoria mancante",
             "missing_section": "analisi di sensitività",
             "expected_code": "derived_artifact_incomplete"},
            {"case": "b", "artifact": "workbook",
             "defect": "foglio obbligatorio mancante e NON nominato",
             "missing_sheet": "Cash_Flow",
             "expected_code": "derived_artifact_incomplete"},
            {"case": "c", "artifact": "chapter",
             "defect": "valore alterato oltre tolleranza",
             "canonical_value": 1000, "derived_value": 1100,
             "tolerance": "0.01",
             "expected_code": "derived_artifact_numeric_mismatch"},
            {"case": "d", "artifact": "workbook",
             "defect": "canonical_source_checksum stantio",
             "declared_checksum": "b" * 64,
             "expected_code": "derived_artifact_stale"},
            {"case": "e", "artifact": "workbook",
             "defect": "letterale economico vietato in una cella",
             "cell": "Assumptions!B7", "literal": 780,
             "expected_code": "derived_artifact_numeric_mismatch"},
        ],
    }


#: Registro delle tredici fixture sintetiche. L'elenco è CHIUSO: F-1...F-13,
#: nessuna quattordicesima. F-12 e F-13 sono le due fixture dei deliverable
#: derivati obbligatori (capitolo e workbook) e vivono qui con le altre, perché
#: una fixture che serve un test non può nascere dopo di esso.
STAGE10_FIXTURES = {
    "F-1": fixture_f1_full_scenario_coverage,
    "F-2": fixture_f2_partial_scenario_coverage,
    "F-3": fixture_f3_no_scenario_coverage,
    "F-4": fixture_f4_headcount_periods,
    "F-5": fixture_f5_stock_vs_flow,
    "F-6": fixture_f6_rate_conversion,
    "F-7": fixture_f7_opex_categories,
    "F-8": fixture_f8_binding_escape_hatches,
    "F-9": fixture_f9_status_matrix,
    "F-10": fixture_f10_pnl_to_cash_bridge,
    "F-11": fixture_f11_financial_config,
    "F-12": fixture_f12_complete_canonical_state,
    "F-13": fixture_f13_divergent_derived_artifacts,
}


def stage10_fixture(fixture_id):
    """Restituisce la fixture sintetica richiesta, per id `F-N`."""
    try:
        builder = STAGE10_FIXTURES[fixture_id]
    except KeyError:
        raise AssertionError(
            f"fixture sintetica sconosciuta: {fixture_id!r}; l'elenco è "
            f"chiuso a {sorted(STAGE10_FIXTURES)}")
    return builder()


def make_stage10_fixture_project(base, fixture_id, name=None,
                                 include_financial_config=True):
    """Progetto temporaneo che porta una fixture sintetica dello Stage 10.

    Il progetto è TEMPORANEO e la cartella `10_financial-plan/` NON è creata:
    il progetto è fermo allo Stage 9 approvato e la fixture vive in
    `shared/`. Il metodo scrive solo `shared/`, esattamente come
    `make_project`.
    """
    fixture = stage10_fixture(fixture_id)
    project = make_project(
        base, name=name or f"s10-{fixture_id.lower()}",
        current_stage="09_roadmap-and-milestones", status="approved",
        assumptions=fixture.get("assumptions") or fixture.get("records"))
    config = {
        "project_name": project.name,
        "project_slug": project.name,
        "created_at": "2026-07-15",
        "release_scope": "0.4",
        "capability_map": {},
    }
    if include_financial_config:
        config["financial_config"] = financial_config(
            financial_profile=fixture.get("profile_id", "generic_startup"))
    write_json(project / "shared" / "project-config.json", config)
    write_json(project / "shared" / "stage10-fixture.json", fixture)
    return project, fixture
