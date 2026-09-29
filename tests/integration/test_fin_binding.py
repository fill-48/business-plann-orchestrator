#!/usr/bin/env python3
"""Harness dei SEDICI contratti di binding e integrita' dei driver.

Ogni contratto costruisce un input di binding COMPLETO con un difetto
DICHIARATO, lo trasmette a `validators/validate_financial_binding.py` e
verifica che il report porti i codici di errore attesi.

STRUTTURA A TRE LIVELLI
-----------------------
A  PREPARAZIONE   radice del repository, fixture (`F-*` del testkit,
                  consumate in SOLA LETTURA, o progetto demo committato),
                  COSTRUZIONE COMPLETA dell'input di binding del contratto,
                  risoluzione del punto d'ingresso dichiarato.
                  DEVE riuscire: `--selfcheck` esce 0. Un fallimento qui e' un
                  DIFETTO DI HARNESS, non evidenza RED.
B  INVOCAZIONE    invocazione del punto d'ingresso dichiarato
                  `validators/validate_financial_binding.py` con il payload
                  del livello A. Se il punto d'ingresso manca, la ragione e'
                  UNIFORME e dichiarata,
                  `MISSING_CAPABILITY: validate_financial_binding`, exit 1.
C  DICHIARAZIONE  il CODICE DI ERRORE ATTESO del contratto, REGISTRATO qui e
                  CONFRONTATO con i codici osservati nel report.

SEMANTICA DEGLI EXIT CODE
-------------------------
    0   tutti i contratti GREEN (o `--selfcheck` riuscito)
    1   almeno un contratto RED
    2   errore d'uso (EXIT_USAGE) -- evidenza NON valida
    3   stato canonico non valido (EXIT_STATE) -- evidenza NON valida

CHE COSA QUESTO HARNESS NON CONTIENE
------------------------------------
Nessuna logica di CALCOLO finanziario e nessuna funzione di RISOLUZIONE del
binding: l'input di ogni contratto e' DICHIARATO riga per riga a
partire dal canonico committato e dalle fixture del testkit, mai cercato o
dedotto. Nessun valore economico e' introdotto fuori dal canonico demo e dalle
fixture `F-1`...`F-13`: i soli letterali strutturali sono
indici di periodo, quote di ripartizione e priorita' di fonte.
"""
import argparse
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# --------------------------------------------------------------------------
# Costanti strutturali
# --------------------------------------------------------------------------

SKILL_REL = ".claude/skills/business-plan-orchestrator"
VALIDATORS_REL = f"{SKILL_REL}/validators"
TRANSACTION_REL = f"{SKILL_REL}/transaction"
PROFILES_REL = f"{SKILL_REL}/profiles"
TESTKIT_REL = "tests/integration"

#: Punto d'ingresso DICHIARATO del binding.
ENTRY_POINT_REL = f"{VALIDATORS_REL}/validate_financial_binding.py"
ENTRY_POINT_NAME = "validate_financial_binding"

#: Ragione UNIFORME e dichiarata del fallimento di livello B quando il punto
#: d'ingresso manca. E' uniforme perche' la capacita' mancante e' UNA SOLA; i
#: codici specifici sono DICHIARATI al livello C.
MISSING_CAPABILITY_REASON = f"MISSING_CAPABILITY: {ENTRY_POINT_NAME}"

DEMO_PROJECT_REL = "examples/fictional-startup"
STAGE10 = "10_financial-plan"

EXIT_OK = 0
EXIT_RED = 1
EXIT_USAGE = 2
EXIT_STATE = 3

LEVEL_A = "A"
LEVEL_B = "B"
LEVEL_C = "C"

#: Campi OBBLIGATORI di un `driver_binding`. Il livello A
#: verifica che l'input sia COSTRUITO per intero: la chiave e' sempre presente,
#: e il difetto deliberato del contratto e' DICHIARATO a parte, mai ottenuto
#: omettendo silenziosamente un campo.
BINDING_REQUIRED_FIELDS = (
    "driver_id", "role", "driver_class", "producer_stage", "source_ref",
    "source_path", "source_record_hash", "cardinality", "unit", "currency",
    "measure_kind", "frequency", "conversion_policy", "timing_rule",
    "start_period", "end_period", "scenario_polarity", "status",
    "source_priority", "binding_method", "double_count_risk", "input_kind",
)
BINDING_OPTIONAL_FIELDS = (
    "semantic_name", "confidence", "evidence_refs", "decision_ref",
    "upstream_refs", "notes",
    "exhaustive_search", "rationale", "declared_exclusions",
    "variable_cost_bindings", "custom_schedule", "level_schedule",
    "scenario_coverage",
)

#: Esito dichiarato del contratto `T-FIN-INPUT-KIND`: un driver
#: `informational` consumato dal motore e' un FAIL.
AMB_02_EXPECTED = ("driver_informational_consumed -- esito dichiarato: FAIL")

#: Codice di errore emesso da `validate_financial_binding` quando un driver
#: `informational` e' consumato dal motore. L'alternativa
#: `driver_input_kind_consumed` NON esiste e non e' accettata.
AMB_02_FIXED_CODE = "driver_informational_consumed"
#: Origine del codice: la tassonomia di errori del validator di binding.
AMB_02_FIXED_BY = "tassonomia di errori di validate_financial_binding"

#: DISCRIMINAZIONE ATTRIBUITA della riga `RED-2` di `F-8`.
#:
#: PERCHE' ESISTE. `expected_codes` e' un vincolo GLOBALE sull'insieme dei
#: codici osservati, senza attribuzione di riga. Nel payload di
#: `T-FIN-EXPLICIT-DECLARATION` il codice `driver_source_path_unverifiable` e'
#: SOVRADETERMINATO: lo emettono anche `DRV-010` (guard di prefisso FPI) e
#: `DRV-012` (ramo «il path non risolve affatto»). Senza questa verifica il
#: ramo semantico di `RED-2` si potrebbe RIMUOVERE e il contratto resterebbe
#: GREEN.
#:
#: CHE COSA FA. Esige, IN AGGIUNTA agli `expected_codes` e senza sostituirli,
#: che il report porti una voce di `errors[]` ATTRIBUIBILE a `DRV-011` che
#: provi il disallineamento SEMANTICO. Usa SOLO campi canonici gia' emessi
#: (`code`, `ref`, `message`, `expected`, `actual`): nessun campo nuovo e'
#: introdotto nell'output di produzione.
#:
#: CHE COSA NON FA. Non tocca `DRV-010` ne' `DRV-012`, non modifica la
#: fixture, non indebolisce alcun contratto: e' dichiarata dal SOLO
#: contratto che la porta, e i quindici contratti restanti eseguono la regola
#: di accettazione INVARIATA.
ATTRIBUTION_F8_RED2 = {
    "label": "RED-2 / DRV-011 -- disallineamento SEMANTICO: "
             "business_model.contribution_margin_ref risolve ad ASS-018 "
             "mentre source_ref dichiara ASS-015",
    "code": "driver_source_path_unverifiable",
    "ref": "DRV-011",
    #: il path risolve a questo `ASS-*` ...
    "actual": "ASS-018",
    #: ... mentre la riga ne dichiara un altro.
    "expected": "ASS-015",
    #: il messaggio deve NOMINARE il path, i due riferimenti e la natura
    #: SEMANTICA del difetto.
    "message_contains": (
        "business_model.contribution_margin_ref",
        "ASS-018",
        "ASS-015",
        "semantica diversa",
    ),
    #: e NON deve essere uno degli altri due esiti di `check_source_path`:
    #: ne' il guard di prefisso FPI, ne' il path irrisolvibile.
    "message_excludes": (
        "fuori dalla FPI",
        "non risolve in alcun artefatto canonico",
    ),
}


def attribution_violation(report, spec):
    """Verifica l'evidenza ATTRIBUITA di `spec` nel report.

    Restituisce `None` se l'evidenza esiste, altrimenti la RAGIONE del RED.
    La ragione e' esplicita sul caso critico: il codice puo' essere presente
    GLOBALMENTE mentre l'attribuzione specifica manca.
    """
    code, ref = spec["code"], spec["ref"]
    errors = report.get("errors") or []
    globally_present = any(e.get("code") == code for e in errors)
    candidates = [e for e in errors
                  if e.get("code") == code and e.get("ref") == ref]
    if not candidates:
        return ("nessuna voce errors[] con code={!r} attribuita a ref={!r}"
                "{}".format(
                    code, ref,
                    "; il codice E' presente globalmente su altre righe: "
                    "l'attribuzione specifica manca" if globally_present
                    else "; il codice e' assente anche globalmente"))
    misses = []
    for error in candidates:
        why = []
        for field in ("expected", "actual"):
            if field in spec and str(error.get(field)) != spec[field]:
                why.append("{}={!r} invece di {!r}".format(
                    field, error.get(field), spec[field]))
        message = error.get("message") or ""
        for token in spec.get("message_contains", ()):
            if token not in message:
                why.append(f"il messaggio non nomina {token!r}")
        for token in spec.get("message_excludes", ()):
            if token in message:
                why.append(f"il messaggio nomina {token!r}: e' un ALTRO ramo")
        if not why:
            return None
        misses.append("; ".join(why))
    return ("voce errors[] su {} presente ma NON prova il disallineamento "
            "semantico atteso: {}".format(ref, " | ".join(misses)))


class HarnessUsageError(Exception):
    """Errore d'uso dell'harness o della sua invocazione (exit 2)."""


class HarnessStateError(Exception):
    """Stato del repository o del canonico non utilizzabile (exit 3)."""


class HarnessDefect(Exception):
    """Difetto di harness rilevato al livello A (exit 3).

    Un fallimento di livello A NON e' evidenza RED: dimostrerebbe soltanto che
    l'harness e' rotto.
    """


# --------------------------------------------------------------------------
# Livello A -- preparazione
# --------------------------------------------------------------------------


def resolve_root(raw):
    """Radice del repository. Una radice non risolta e' errore d'uso."""
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


def load_testkit(root):
    """Importa `tests/integration/bpo_testkit.py` -- fixture `F-*` in SOLA LETTURA.

    Le fixture `F-1`...`F-13` sono definite nel testkit: questo harness le
    CONSUMA e non le modifica. Una fixture insufficiente e' un difetto di
    harness da segnalare, non da correggere qui.
    """
    import importlib.util

    path = root / TESTKIT_REL / "bpo_testkit.py"
    if not path.is_file():
        raise HarnessDefect(f"testkit assente: {path}")
    spec = importlib.util.spec_from_file_location("bpo_testkit", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bpo_testkit"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - difetto di harness
        raise HarnessDefect(f"testkit non importabile: {path}: {exc}")
    return module


def load_fingerprint(root, testkit):
    """`record_fingerprint` del Transaction Manager, in SOLA LETTURA.

    Riusa il CAS gia' esistente del Transaction Manager invece di introdurre
    una convenzione di fingerprint nuova. L'import non modifica il Transaction
    Manager.
    """
    try:
        module = testkit.load_module(root, TRANSACTION_REL,
                                     "transaction_manager")
    except Exception as exc:
        raise HarnessDefect(
            f"transaction_manager non importabile in sola lettura: {exc}")
    fingerprint = getattr(module, "record_fingerprint", None)
    if not callable(fingerprint):
        raise HarnessDefect(
            "transaction_manager senza record_fingerprint: il CAS esistente "
            "non e' riusabile")
    return fingerprint


def read_json(path, label):
    if not path.is_file():
        raise HarnessStateError(f"artefatto canonico assente: {label}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HarnessStateError(f"artefatto canonico corrotto: {label}: {exc}")


def load_demo(root):
    """Progetto demo COMMITTATO -- fixture di dieci dei sedici contratti.

    Consumato in sola lettura: nessun file del progetto demo e' scritto, e
    nessuna cartella `10_financial-plan/` e' creata dentro il demo.
    """
    project = root / DEMO_PROJECT_REL
    if not project.is_dir():
        raise HarnessStateError(f"progetto demo assente: {DEMO_PROJECT_REL}")
    assumptions = read_json(project / "shared" / "assumptions-register.json",
                            "shared/assumptions-register.json")
    if not isinstance(assumptions, list) or not assumptions:
        raise HarnessStateError(
            "assumptions-register.json del demo non e' una lista non vuota")
    by_id = {}
    for entry in assumptions:
        entry_id = entry.get("id")
        if entry_id:
            by_id.setdefault(entry_id, entry)
    business = read_json(project / "05_business-model" / "structured-output.json",
                         "05_business-model/structured-output.json")
    team = read_json(project / "08_team-and-governance" / "structured-output.json",
                     "08_team-and-governance/structured-output.json")
    roadmap = read_json(
        project / "09_roadmap-and-milestones" / "structured-output.json",
        "09_roadmap-and-milestones/structured-output.json")
    try:
        fpi = roadmap["milestone_plan"]["financial_plan_inputs"]
    except (KeyError, TypeError):
        raise HarnessStateError(
            "09_roadmap-and-milestones: financial_plan_inputs assente "
            "(interfaccia Stage 9 -> Stage 10)")
    return {
        "project_rel": DEMO_PROJECT_REL,
        "project_path": project,
        "assumptions": assumptions,
        "by_id": by_id,
        "business_model": business.get("business_model") or {},
        "team_governance": team.get("team_governance") or {},
        "milestone_plan": roadmap.get("milestone_plan") or {},
        "fpi": fpi,
    }


def load_profile(root, profile_id):
    path = root / PROFILES_REL / f"{profile_id}.json"
    profile = read_json(path, f"profiles/{profile_id}.json")
    for key in ("required_driver_roles", "role_measure_kind",
                "role_driver_class"):
        if key not in profile:
            raise HarnessStateError(
                f"profilo {profile_id} senza {key}: il ruolo non e' "
                "verificabile contro il profilo attivo")
    return profile


def record_of(demo, ref):
    """Record canonico del demo, o None. NON risolve alcun binding: legge."""
    return demo["by_id"].get(ref)


def binding(driver_id, role, profile, demo, fingerprint, source_ref,
            source_path, unit, currency, frequency, conversion_policy,
            timing_rule, cardinality="one", producer_stage="09_roadmap-and-milestones",
            measure_kind=None, start_period=0, end_period=11,
            scenario_polarity="cost_like", status="inferred",
            source_priority=10, binding_method="fpi_declared",
            double_count_risk="none", input_kind="operational",
            source_record_hash=None, **optional):
    """Costruisce UNA riga di `driver_binding` COMPLETA.

    E' un COSTRUTTORE DICHIARATIVO, non un risolutore: ogni valore e' passato
    esplicitamente dal contratto che lo dichiara, nessun campo e' cercato,
    dedotto dal nome della variabile o inferito dall'unita'. `measure_kind`,
    quando non e' esplicitamente dichiarato dal contratto, e' preso dal
    `role_measure_kind` del PROFILO ATTIVO -- cioe' dal dato di
    configurazione, mai da un'euristica.
    """
    record = record_of(demo, source_ref) if demo is not None else None
    if source_record_hash is None:
        source_record_hash = fingerprint(record) if record is not None \
            else fingerprint({"id": source_ref})
    row = {
        "driver_id": driver_id,
        "role": role,
        "driver_class": (profile.get("role_driver_class") or {}).get(role),
        "producer_stage": producer_stage,
        "source_ref": source_ref,
        "source_path": source_path,
        "source_record_hash": source_record_hash,
        "cardinality": cardinality,
        "unit": unit,
        "currency": currency,
        "measure_kind": measure_kind if measure_kind is not None
        else (profile.get("role_measure_kind") or {}).get(role),
        "frequency": frequency,
        "conversion_policy": conversion_policy,
        "timing_rule": timing_rule,
        "start_period": start_period,
        "end_period": end_period,
        "scenario_polarity": scenario_polarity,
        "status": status,
        "source_priority": source_priority,
        "binding_method": binding_method,
        "double_count_risk": double_count_risk,
        "input_kind": input_kind,
    }
    row.update(optional)
    return row


def demo_seed_bindings(profile, demo, fingerprint):
    """Le otto righe SEED della FPI del demo (modalita' `fpi_declared`).

    Sono l'input di partenza COMPLETO dei contratti che esercitano il progetto
    demo committato: ogni chiave della FPI si lega al ruolo omonimo del
    profilo, con `source_path` = `financial_plan_inputs.<chiave>`.
    """
    fpi = demo["fpi"]
    fpi_path = "milestone_plan.financial_plan_inputs"

    def unit_of(ref):
        record = record_of(demo, ref)
        return (record or {}).get("unit")

    def currency_of(ref):
        unit = unit_of(ref) or ""
        return "EUR" if unit.startswith("EUR") else None

    rows = [
        binding("DRV-001", "unit_price", profile, demo, fingerprint,
                fpi["pricing_ref"], f"{fpi_path}.pricing_ref",
                unit_of(fpi["pricing_ref"]), currency_of(fpi["pricing_ref"]),
                "annual", "preserve_per_unit", "NOT_APPLICABLE",
                scenario_polarity="revenue_like",
                start_period=0, end_period=None),
        binding("DRV-002", "customer_volume", profile, demo, fingerprint,
                fpi["funnel_customers_ref"],
                f"{fpi_path}.funnel_customers_ref",
                unit_of(fpi["funnel_customers_ref"]), None,
                "annual", "carry_level", "constant",
                scenario_polarity="revenue_like", decision_ref="DEC-001"),
        binding("DRV-003", "churn_rate", profile, demo, fingerprint,
                fpi["churn_ref"], f"{fpi_path}.churn_ref",
                unit_of(fpi["churn_ref"]), None,
                "annual", "compound", "NOT_APPLICABLE",
                start_period=0, end_period=None),
        binding("DRV-004", "variable_cost", profile, demo, fingerprint,
                fpi["cogs_refs"][0], f"{fpi_path}.cogs_refs[0]",
                unit_of(fpi["cogs_refs"][0]), currency_of(fpi["cogs_refs"][0]),
                "annual", "preserve_per_unit", "NOT_APPLICABLE",
                cardinality="many", start_period=0, end_period=None),
        binding("DRV-005", "headcount", profile, demo, fingerprint,
                fpi["headcount_driver_refs"][0],
                f"{fpi_path}.headcount_driver_refs[0]",
                unit_of(fpi["headcount_driver_refs"][0]), None,
                "annual", "carry_level", "constant", cardinality="many"),
        binding("DRV-006", "headcount", profile, demo, fingerprint,
                fpi["headcount_driver_refs"][1],
                f"{fpi_path}.headcount_driver_refs[1]",
                unit_of(fpi["headcount_driver_refs"][1]), None,
                "annual", "carry_level", "constant", cardinality="many"),
        binding("DRV-007", "ops_capacity", profile, demo, fingerprint,
                fpi["ops_capacity_ref"], f"{fpi_path}.ops_capacity_ref",
                unit_of(fpi["ops_capacity_ref"]), None,
                "annual", "carry_level", "constant"),
        binding("DRV-008", "serviceable_obtainable_market", profile, demo,
                fingerprint, fpi["som_ref"], f"{fpi_path}.som_ref",
                unit_of(fpi["som_ref"]), currency_of(fpi["som_ref"]),
                "annual", "carry_level", "constant",
                scenario_polarity="revenue_like"),
    ]
    return rows


# --------------------------------------------------------------------------
# Livello A -- costruttori di input, uno per contratto
#
# Ogni costruttore restituisce l'INPUT DI BINDING COMPLETO del proprio
# contratto, con il DIFETTO DELIBERATO dichiarato esplicitamente. Il difetto
# dichiarato e' cio' che distingue "input costruito e volutamente in
# violazione" da "input non costruito" e cio' che rende i sedici
# input distinti fra loro.
# --------------------------------------------------------------------------


def build_driver_binding(ctx):
    """`T-FIN-DRIVER-BINDING` -- ogni ruolo RICHIESTO dal profilo e' legato.

    Il ruolo `payroll_unit_cost` e' RICHIESTO da `subscription_saas` ma la FPI
    non lo espone: le otto righe seed lo lasciano scoperto. E' il ruolo
    richiesto non legato, sui dati committati.
    """
    rows = demo_seed_bindings(ctx["profile"], ctx["demo"], ctx["fingerprint"])
    bound = {row["role"] for row in rows}
    unbound = [role for role in ctx["profile"]["required_driver_roles"]
               if role not in bound]
    return {
        "driver_bindings": rows,
        "deliberate_defect": {
            "kind": "required_role_not_bound",
            "unbound_required_roles": unbound,
            "why": "la FPI non espone payroll_unit_cost: il ruolo "
                   "richiesto dal profilo attivo resta scoperto",
        },
    }


def build_refint(ctx):
    """`T-FIN-REFINT` -- nessun riferimento ghost."""
    rows = demo_seed_bindings(ctx["profile"], ctx["demo"], ctx["fingerprint"])
    ghost = "ASS-997"
    if record_of(ctx["demo"], ghost) is not None:
        raise HarnessDefect(
            f"{ghost} esiste nel canonico demo: il caso ghost non e' "
            "costruibile su questo riferimento")
    rows = copy.deepcopy(rows)
    rows[0] = dict(rows[0], source_ref=ghost,
                   source_path="milestone_plan.financial_plan_inputs.pricing_ref")
    return {
        "driver_bindings": rows,
        "deliberate_defect": {
            "kind": "ghost_reference",
            "ghost_ref": ghost,
            "on_role": rows[0]["role"],
            "why": "il riferimento non risolve in alcun record del canonico",
        },
    }


def build_cogs_coverage(ctx):
    """`T-FIN-COGS-COVERAGE` -- copertura COGS completa.

    Costruisce l'input dei QUATTRO casi: il caso nominale sulla demo -- dove
    `cogs_refs` copre `ASS-016` ma non `ASS-017` -- e i tre casi limite, tutti
    fail-closed, ottenuti mutando la sola catena del margine.
    """
    demo = ctx["demo"]
    rows = demo_seed_bindings(ctx["profile"], demo, ctx["fingerprint"])
    margin_ref = demo["business_model"].get("contribution_margin_ref")
    if not margin_ref:
        raise HarnessDefect(
            "05_business-model senza contribution_margin_ref: il caso "
            "nominale di copertura COGS non e' costruibile")
    margin = record_of(demo, margin_ref)
    if margin is None:
        raise HarnessDefect(
            f"contribution_margin_ref {margin_ref} non risolve nel canonico")
    margin_vars = list((margin.get("derivation") or {}).get("variables", {}).values())
    pricing_ref = demo["fpi"]["pricing_ref"]
    cost_vars = [ref for ref in margin_vars if ref != pricing_ref]
    covered = list(demo["fpi"]["cogs_refs"])
    uncovered = [ref for ref in cost_vars if ref not in covered]

    margin_not_derived = copy.deepcopy(margin)
    margin_not_derived.pop("derivation", None)
    margin_not_derived["kind"] = "primary"
    margin_price_absent = copy.deepcopy(margin)
    margin_price_absent["derivation"] = copy.deepcopy(margin.get("derivation") or {})
    margin_price_absent["derivation"]["variables"] = {
        name: ref
        for name, ref in (margin.get("derivation") or {}).get("variables", {}).items()
        if ref != pricing_ref
    }
    return {
        "driver_bindings": rows,
        "cogs_chain": {
            "margin_source_path": "business_model.contribution_margin_ref",
            "contribution_margin_ref": margin_ref,
            "margin_variables": margin_vars,
            "pricing_ref": pricing_ref,
            "cost_variables": cost_vars,
            "covered_by_cogs_refs": covered,
            "uncovered": uncovered,
            "declared_exclusions": [],
        },
        "edge_cases": {
            "cogs_margin_reference_missing": {
                "business_model": {
                    key: value
                    for key, value in demo["business_model"].items()
                    if key != "contribution_margin_ref"
                },
            },
            "cogs_margin_not_derived": {"margin_record": margin_not_derived},
            "cogs_margin_price_absent": {"margin_record": margin_price_absent},
        },
        "deliberate_defect": {
            "kind": "cogs_coverage_incomplete",
            "uncovered_cost_variables": uncovered,
            "why": "i costi variabili del contribution margin non sono tutti "
                   "coperti da cogs_refs, e nessuna esclusione e' dichiarata",
        },
    }


def build_source_hierarchy(ctx):
    """`T-FIN-SOURCE-HIERARCHY` -- due candidati a PARI priorita'."""
    demo = ctx["demo"]
    rows = demo_seed_bindings(ctx["profile"], demo, ctx["fingerprint"])
    primary = rows[0]
    rival_ref = "ASS-001"
    rival = record_of(demo, rival_ref)
    if rival is None:
        raise HarnessDefect(
            f"{rival_ref} assente dal canonico demo: il conflitto di fonte "
            "non e' costruibile sui dati committati")
    contender = binding(
        "DRV-101", "unit_price", ctx["profile"], demo, ctx["fingerprint"],
        rival_ref, "milestone_plan.financial_plan_inputs.pricing_ref",
        rival.get("unit"), "EUR", "monthly", "preserve_per_unit",
        "NOT_APPLICABLE", scenario_polarity="revenue_like",
        source_priority=primary["source_priority"], status="placeholder",
        start_period=0, end_period=None)
    return {
        "driver_bindings": rows + [contender],
        "deliberate_defect": {
            "kind": "source_conflict_unresolved",
            "role": "unit_price",
            "candidates": [primary["source_ref"], rival_ref],
            "equal_priority": primary["source_priority"],
            "decision_ref": None,
            "why": "due candidati per lo stesso ruolo, priorita' PARI e "
                   "nessun DEC-* che risolva: la scelta implicita e' vietata",
        },
    }


def build_units(ctx):
    """`T-FIN-UNITS` -- unita' canonica e compatibile col ruolo."""
    demo = ctx["demo"]
    rows = copy.deepcopy(demo_seed_bindings(ctx["profile"], demo,
                                            ctx["fingerprint"]))
    churn_index = next(i for i, row in enumerate(rows)
                       if row["role"] == "churn_rate")
    canonical_unit = rows[churn_index]["unit"]
    rows[churn_index] = dict(rows[churn_index], unit="%")
    price_index = next(i for i, row in enumerate(rows)
                       if row["role"] == "unit_price")
    mismatched = dict(rows[price_index], unit=rows[churn_index]["unit"])
    rows[price_index] = mismatched
    return {
        "driver_bindings": rows,
        "deliberate_defect": {
            "kind": "unit_violations",
            "non_canonical": {"role": "churn_rate", "unit": "%",
                              "canonical_unit": canonical_unit},
            "mismatch": {"role": "unit_price", "unit": "%",
                         "role_unit_class":
                             (ctx["profile"].get("role_unit_class") or {})
                             .get("unit_price")},
            "why": "un ratio espresso in percentuale trattato come frazione, e "
                   "un'unita' incompatibile con la classe del ruolo",
        },
    }


def build_frequency(ctx):
    """`T-FIN-FREQUENCY` -- frequenza DICHIARATA, mai dedotta dal nome."""
    rows = copy.deepcopy(demo_seed_bindings(ctx["profile"], ctx["demo"],
                                            ctx["fingerprint"]))
    target = next(i for i, row in enumerate(rows)
                  if row["role"] == "variable_cost")
    rows[target] = dict(rows[target], frequency=None)
    return {
        "driver_bindings": rows,
        "deliberate_defect": {
            "kind": "frequency_undeclared",
            "role": rows[target]["role"],
            "driver_id": rows[target]["driver_id"],
            "why": "la chiave frequency e' presente ma NON dichiarata: "
                   "dedurla dal nome della variabile e' vietato",
        },
    }


def build_timing(ctx):
    """`T-FIN-TIMING` -- Sigma quote di una `timing_rule` = 1, SOLO per `flow`.

    Due casi in un solo contratto:
    - la violazione: `custom_schedule` che somma 0.9 su un driver `flow`;
    - il CASO NEGATIVO DI AMBITO: la stessa verifica di somma applicata a
      `stock`, `rate` e `per_unit`, che ne sono ESENTI.
    """
    demo = ctx["demo"]
    rows = copy.deepcopy(demo_seed_bindings(ctx["profile"], demo,
                                            ctx["fingerprint"]))
    milestone_ref = demo["fpi"]["milestone_cost_refs"][0]
    record = record_of(demo, milestone_ref)
    if record is None:
        raise HarnessDefect(
            f"{milestone_ref} assente dal canonico demo: il driver flow non e' "
            "costruibile")
    schedule = {"0": 0.3, "1": 0.3, "2": 0.3}
    flow_row = binding(
        "DRV-102", "milestone_cost", ctx["profile"], demo, ctx["fingerprint"],
        milestone_ref, "milestone_plan.financial_plan_inputs.milestone_cost_refs[0]",
        record.get("unit"), "EUR", "one_off", "allocate", "custom_schedule",
        cardinality="many", start_period=0, end_period=2,
        custom_schedule=schedule)
    out_of_scope = [
        {"driver_id": row["driver_id"], "role": row["role"],
         "measure_kind": row["measure_kind"], "timing_rule": row["timing_rule"]}
        for row in rows
        if row["measure_kind"] in ("stock", "rate", "per_unit")
    ]
    return {
        "driver_bindings": rows + [flow_row],
        "deliberate_defect": {
            "kind": "rec_12_violation_on_flow",
            "driver_id": flow_row["driver_id"],
            "measure_kind": flow_row["measure_kind"],
            "custom_schedule": schedule,
            "schedule_sum": round(sum(schedule.values()), 10),
            "why": "la somma delle quote di un driver flow non e' 1 entro la "
                   "tolleranza ratio: la schedule perde massa",
        },
        "scope_negative_case": {
            "kind": "rec_12_must_not_apply",
            "exempt_bindings": out_of_scope,
            "why": "applicare la verifica di somma a stock, rate o per_unit e' "
                   "un errore di APPLICAZIONE della regola, non un piano "
                   "invalido: REC-12 vale SOLO per measure_kind flow",
        },
    }


def build_status_gate_single(ctx):
    """`T-FIN-STATUS-GATE-SINGLE` -- regressione FOCALIZZATA su `ASS-003`."""
    demo = ctx["demo"]
    rows = copy.deepcopy(demo_seed_bindings(ctx["profile"], demo,
                                            ctx["fingerprint"]))
    ref = "ASS-003"
    record = record_of(demo, ref)
    if record is None:
        raise HarnessDefect(
            f"{ref} assente dal canonico demo: il caso di non-promozione non "
            "e' costruibile sui dati committati")
    if record.get("value") is not None or \
            record.get("validation_status") != "needs_info":
        raise HarnessDefect(
            f"{ref} non e' piu' (value: null, needs_info) nel canonico demo: "
            "la fixture non regge il contratto")
    target = next(i for i, row in enumerate(rows)
                  if row["role"] == "churn_rate")
    rows[target] = dict(
        rows[target], source_ref=ref, unit=record.get("unit"),
        status="unresolved",
        source_record_hash=ctx["fingerprint"](record))
    return {
        "driver_bindings": rows,
        "deliberate_defect": {
            "kind": "unresolved_required_input",
            "role": rows[target]["role"],
            "source_ref": ref,
            "record_validation_status": record.get("validation_status"),
            "record_value": record.get("value"),
            "role_required": rows[target]["role"] in
                             ctx["profile"]["required_driver_roles"],
            "why": "un record (value: null, needs_info) su un ruolo RICHIESTO "
                   "non e' consumabile: promuoverlo a confirmed e' vietato",
        },
    }


def build_duplicate_explicit(ctx):
    """`T-FIN-DUPLICATE-EXPLICIT` -- due binding su `unit_price`.

    La FPI NON puo' esprimere due pricing (`pricing_ref` e' un singolo `$ref`
    sotto `additionalProperties: false`): il secondo binding puo' nascere solo
    da `explicit_declaration`, quindi il contratto esercita QUELLA via.
    """
    demo = ctx["demo"]
    rows = demo_seed_bindings(ctx["profile"], demo, ctx["fingerprint"])
    rival_ref = "ASS-001"
    rival = record_of(demo, rival_ref)
    if rival is None:
        raise HarnessDefect(
            f"{rival_ref} assente dal canonico demo: il duplicato esplicito "
            "non e' costruibile")
    duplicate = binding(
        "DRV-103", "unit_price", ctx["profile"], demo, ctx["fingerprint"],
        rival_ref, "explicit", rival.get("unit"), "EUR", "monthly",
        "preserve_per_unit", "NOT_APPLICABLE", cardinality="one",
        scenario_polarity="revenue_like",
        binding_method="explicit_declaration", decision_ref="DEC-004",
        exhaustive_search=["05_business-model/structured-output.json"],
        rationale="secondo pricing dichiarato a mano",
        start_period=0, end_period=None)
    return {
        "driver_bindings": rows + [duplicate],
        "deliberate_defect": {
            "kind": "driver_duplicate_binding_on_one",
            "role": "unit_price",
            "cardinality": "one",
            "bound_refs": [rows[0]["source_ref"], rival_ref],
            "second_binding_method": "explicit_declaration",
            "why": "un ruolo a cardinalita' one accetta UN solo binding: il "
                   "secondo arriva per dichiarazione esplicita, non dalla FPI",
        },
    }


def build_duplicate_many(ctx):
    """`T-FIN-DUPLICATE-MANY` -- duplicato su un ruolo a cardinalita' `many`.

    Su `cogs_refs` e `headcount_driver_refs` il duplicato E' realmente
    esprimibile via FPI, quindi il contratto esercita QUEL percorso.
    """
    demo = ctx["demo"]
    rows = demo_seed_bindings(ctx["profile"], demo, ctx["fingerprint"])
    cogs_row = next(row for row in rows if row["role"] == "variable_cost")
    headcount_row = next(row for row in rows if row["role"] == "headcount")
    dup_cogs = dict(copy.deepcopy(cogs_row), driver_id="DRV-104")
    dup_headcount = dict(copy.deepcopy(headcount_row), driver_id="DRV-105")
    return {
        "driver_bindings": rows + [dup_cogs, dup_headcount],
        "deliberate_defect": {
            "kind": "driver_duplicate_binding_on_many",
            "roles": ["variable_cost", "headcount"],
            "duplicated_refs": [cogs_row["source_ref"],
                                headcount_row["source_ref"]],
            "why": "lo STESSO source_ref e' legato due volte allo stesso ruolo "
                   "many: cardinalita' many non significa duplicati ammessi",
        },
    }


def build_ambiguity(ctx):
    """`T-FIN-AMBIGUITY` -- stesso `ASS-*` su DUE ruoli incompatibili."""
    demo = ctx["demo"]
    rows = demo_seed_bindings(ctx["profile"], demo, ctx["fingerprint"])
    price_row = next(row for row in rows if row["role"] == "unit_price")
    reused = binding(
        "DRV-106", "variable_cost", ctx["profile"], demo, ctx["fingerprint"],
        price_row["source_ref"],
        "milestone_plan.financial_plan_inputs.cogs_refs[0]",
        price_row["unit"], price_row["currency"], "annual",
        "preserve_per_unit", "NOT_APPLICABLE", cardinality="many",
        start_period=0, end_period=None)
    return {
        "driver_bindings": rows + [reused],
        "deliberate_defect": {
            "kind": "driver_ref_ambiguous",
            "source_ref": price_row["source_ref"],
            "roles": ["unit_price", "variable_cost"],
            "why": "lo stesso riferimento canonico serve un ricavo e un costo: "
                   "il riuso con semantica diversa e' ambiguita', non economia",
        },
    }


def build_input_kind(ctx):
    """`T-FIN-INPUT-KIND` -- un driver `informational` NON e' consumato.

    L'esito dichiarato e' FAIL con il codice `driver_informational_consumed`
    (`AMB_02_FIXED_CODE`).
    """
    demo = ctx["demo"]
    rows = copy.deepcopy(demo_seed_bindings(ctx["profile"], demo,
                                            ctx["fingerprint"]))
    target = next(i for i, row in enumerate(rows)
                  if row["role"] == "serviceable_obtainable_market")
    rows[target] = dict(rows[target], input_kind="informational")
    return {
        "driver_bindings": rows,
        "consumed_by_engine": [rows[target]["driver_id"]],
        "deliberate_defect": {
            "kind": "informational_driver_consumed",
            "driver_id": rows[target]["driver_id"],
            "input_kind": "informational",
            "why": "un input editabile ma NON operativo e' letto dal motore: "
                   "un parametro informativo diventa un input di calcolo",
        },
    }


def build_explicit_declaration(ctx):
    """`T-FIN-EXPLICIT-DECLARATION` -- fixture **F-8**, tre casi RED.

    RED-1  `source_path` inesistente
    RED-2  `source_path` che risolve a un `ASS-*` DIVERSO da `source_ref`
    RED-3  `explicit_declaration` senza `decision_ref`
    """
    fixture = ctx["fixtures"]["F-8"]
    for key in ("source_path_missing", "source_path_resolves_elsewhere",
                "explicit_declaration_without_decision_ref"):
        if key not in fixture:
            raise HarnessDefect(
                f"F-8 senza la variante {key}: la fixture non regge il "
                "contratto")
    rows = [copy.deepcopy(fixture["source_path_missing"]),
            copy.deepcopy(fixture["source_path_resolves_elsewhere"]),
            copy.deepcopy(fixture["explicit_declaration_without_decision_ref"])]
    for row in rows:
        row.setdefault("producer_stage", "05_business-model")
        row.setdefault("cardinality", "one")
    return {
        "driver_bindings": rows,
        "fixture_reference": {
            "justified_counter_example":
                copy.deepcopy(fixture["explicit_declaration_justified"]),
            "resolved_elsewhere_to": fixture.get("resolved_elsewhere_to"),
        },
        "deliberate_defect": {
            "kind": "explicit_declaration_escape_hatches",
            "red_1": {"driver_id": rows[0]["driver_id"],
                      "source_path": rows[0]["source_path"],
                      "why": "il path non esiste nell'artefatto canonico"},
            "red_2": {"driver_id": rows[1]["driver_id"],
                      "source_path": rows[1]["source_path"],
                      "source_ref": rows[1]["source_ref"],
                      "resolves_to": fixture.get("resolved_elsewhere_to"),
                      "why": "il path risolve a un ASS-* diverso da source_ref: "
                             "unita' compatibile, semantica diversa"},
            "red_3": {"driver_id": rows[2]["driver_id"],
                      "binding_method": rows[2]["binding_method"],
                      "decision_ref": rows[2]["decision_ref"],
                      "why": "explicit_declaration senza decision_ref, senza "
                             "exhaustive_search e senza rationale"},
        },
    }


def build_stock_flow(ctx):
    """`T-FIN-STOCK-FLOW` -- fixture **F-5**, tre casi RED.

    RED-1  binding senza `measure_kind`      -> `driver_measure_undeclared`
    RED-2  `stock` ripartito come flusso     -> violazione `REC-14`
    RED-3  `flow` portato a livello          -> violazione `REC-12`
    """
    fixture = ctx["fixtures"]["F-5"]
    for key in ("as_stock", "as_flow", "profile_role_measure_kind"):
        if key not in fixture:
            raise HarnessDefect(
                f"F-5 senza la variante {key}: la fixture non regge il "
                "contratto")
    undeclared = copy.deepcopy(fixture["as_stock"])
    undeclared["driver_id"] = "DRV-201"
    undeclared["measure_kind"] = None

    stock_as_flow = copy.deepcopy(fixture["as_stock"])
    stock_as_flow["driver_id"] = "DRV-202"
    stock_as_flow["timing_rule"] = "uniform"
    stock_as_flow["conversion_policy"] = "allocate"
    stock_as_flow["custom_schedule"] = None

    flow_as_level = copy.deepcopy(fixture["as_flow"])
    flow_as_level["driver_id"] = "DRV-203"
    flow_as_level["timing_rule"] = "constant"
    flow_as_level["conversion_policy"] = "carry_level"

    rows = [undeclared, stock_as_flow, flow_as_level]
    for row in rows:
        row.setdefault("producer_stage", "06_go-to-market")
        row.setdefault("cardinality", "one")
    return {
        "driver_bindings": rows,
        "profile_role_measure_kind": fixture["profile_role_measure_kind"],
        "shared_canonical_record": copy.deepcopy(fixture["assumption"]),
        "deliberate_defect": {
            "kind": "stock_flow_violations",
            "red_1": {"driver_id": undeclared["driver_id"],
                      "measure_kind": None,
                      "why": "measure_kind non dichiarato: dedurlo dal nome o "
                             "dall'unita' e' vietato"},
            "red_2": {"driver_id": stock_as_flow["driver_id"],
                      "declared_measure_kind": stock_as_flow["measure_kind"],
                      "applied_timing_rule": stock_as_flow["timing_rule"],
                      "why": "uno stock ripartito come flusso: il livello per "
                             "periodo non coincide piu' con la serie dichiarata"},
            "red_3": {"driver_id": flow_as_level["driver_id"],
                      "declared_measure_kind": flow_as_level["measure_kind"],
                      "applied_timing_rule": flow_as_level["timing_rule"],
                      "why": "un flusso portato a livello: le quote non sommano "
                             "piu' a 1"},
        },
    }


def build_driver_stale(ctx):
    """`T-FIN-DRIVER-STALE` -- il registry NON diverge dal canonico.

    `update-assumption` su un `ASS-*` legato, seguito da rilettura del registry
    SENZA rebinding: `source_record_hash` non coincide piu' con il record
    canonico corrente. Nessuna scrittura reale avviene qui: l'aggiornamento e'
    COSTRUITO in memoria dal record committato.
    """
    demo = ctx["demo"]
    fingerprint = ctx["fingerprint"]
    rows = copy.deepcopy(demo_seed_bindings(ctx["profile"], demo, fingerprint))
    target = next(i for i, row in enumerate(rows)
                  if row["role"] == "unit_price")
    ref = rows[target]["source_ref"]
    before = record_of(demo, ref)
    if before is None:
        raise HarnessDefect(
            f"{ref} assente dal canonico demo: il drift non e' costruibile")
    hash_before = fingerprint(before)
    after = copy.deepcopy(before)
    after["previous_values"] = list(after.get("previous_values") or []) + [{
        "value": before.get("value"),
        "decision_id": "DEC-005",
    }]
    after["last_updated"] = "2026-07-30"
    hash_after = fingerprint(after)
    if hash_before == hash_after:
        raise HarnessDefect(
            "record_fingerprint non distingue il record aggiornato: il drift "
            "non sarebbe rilevabile e il contratto non discriminerebbe")
    rows[target] = dict(rows[target], source_record_hash=hash_before)
    return {
        "driver_bindings": rows,
        "canonical_after_update": after,
        "deliberate_defect": {
            "kind": "driver_source_stale",
            "driver_id": rows[target]["driver_id"],
            "source_ref": ref,
            "bound_source_record_hash": hash_before,
            "current_source_record_hash": hash_after,
            "why": "il registry porta l'impronta del record PRIMA "
                   "dell'aggiornamento legittimo: il valore legato diverge dal "
                   "canonico corrente",
        },
    }


def build_status_matrix(ctx):
    """`T-FIN-STATUS-MATRIX` -- fixture **F-9**, mappatura TOTALE dello stato.

    Ogni combinazione `validation_status` x `evidence_classification` -- sei
    classi, l'ASSENZA e un valore FUORI enum -- piu' il caso `value: null`.
    """
    fixture = ctx["fixtures"]["F-9"]
    records = fixture.get("records")
    if not records:
        raise HarnessDefect("F-9 senza records: la matrice non e' costruibile")
    out_of_enum = fixture.get("out_of_enum_value")
    unmappable = [record["id"] for record in records
                  if record.get("evidence_classification") == out_of_enum]
    if not unmappable:
        raise HarnessDefect(
            "F-9 senza alcuna combinazione fuori enum: il caso fail-closed non "
            "e' costruibile")
    rows = []
    for index, record in enumerate(records, start=1):
        rows.append(binding(
            f"DRV-3{index:02d}", "customer_volume", ctx["profile"], None,
            ctx["fingerprint"], record["id"],
            "milestone_plan.financial_plan_inputs.funnel_customers_ref",
            record.get("unit"), None, "annual", "carry_level", "constant",
            producer_stage="06_go-to-market",
            source_record_hash=ctx["fingerprint"](record),
            status=None, decision_ref="DEC-001"))
    return {
        "driver_bindings": rows,
        "status_domain": fixture.get("status_order"),
        "canonical_records": copy.deepcopy(records),
        "combinations": fixture.get("combinations"),
        "deliberate_defect": {
            "kind": "driver_status_unmappable",
            "out_of_enum_value": out_of_enum,
            "unmappable_refs": unmappable,
            "why": "una combinazione priva di riga nella funzione totale di "
                   "mappatura dello stato non ha un ramo permissivo: e' FAIL, "
                   "mai un default",
        },
    }


# --------------------------------------------------------------------------
# I SEDICI contratti -- id, regola, fixture, costruttore, esito atteso
# --------------------------------------------------------------------------

CONTRACTS = (
    {
        "contract_id": "T-FIN-DRIVER-BINDING",
        "planning_section": "ogni ruolo richiesto dal profilo e' legato",
        "fixture_id": "demo",
        "fixture_label": f"progetto demo committato ({DEMO_PROJECT_REL})",
        "profile_id": "subscription_saas",
        "build": build_driver_binding,
        "expected_kind": "taxonomy",
        "expected_codes": ("driver_role_unbound",),
        "expected_text": "driver_role_unbound",
    },
    {
        "contract_id": "T-FIN-REFINT",
        "planning_section": "nessun riferimento canonico inesistente",
        "fixture_id": "demo",
        "fixture_label": f"progetto demo con ref inesistente ({DEMO_PROJECT_REL})",
        "profile_id": "subscription_saas",
        "build": build_refint,
        "expected_kind": "taxonomy",
        "expected_codes": ("driver_ref_unresolved",),
        "expected_text": "driver_ref_unresolved",
    },
    {
        "contract_id": "T-FIN-COGS-COVERAGE",
        "planning_section": "copertura COGS del contribution margin",
        "fixture_id": "demo",
        "fixture_label": f"progetto demo con cogs_refs=[\"ASS-016\"] "
                         f"({DEMO_PROJECT_REL})",
        "profile_id": "subscription_saas",
        "build": build_cogs_coverage,
        "expected_kind": "taxonomy",
        "expected_codes": ("cogs_coverage_incomplete",
                           "cogs_margin_reference_missing",
                           "cogs_margin_not_derived",
                           "cogs_margin_price_absent"),
        "expected_text": "cogs_coverage_incomplete (piu' i tre casi limite "
                         "COGS: cogs_margin_reference_missing, "
                         "cogs_margin_not_derived, cogs_margin_price_absent -- "
                         "tutti FAIL, nessuno 'non applicabile')",
    },
    {
        "contract_id": "T-FIN-SOURCE-HIERARCHY",
        "planning_section": "gerarchia delle fonti a priorita' distinte",
        "fixture_id": "demo",
        "fixture_label": "progetto demo, due candidati a pari priorita' "
                         "(ASS-015 e ASS-001)",
        "profile_id": "subscription_saas",
        "build": build_source_hierarchy,
        "expected_kind": "taxonomy",
        "expected_codes": ("source_conflict_unresolved",),
        "expected_text": "source_conflict_unresolved",
    },
    {
        "contract_id": "T-FIN-UNITS",
        "planning_section": "unita' canonica e compatibile col ruolo",
        "fixture_id": "demo",
        "fixture_label": "progetto demo, churn_ref con unit \"%\"",
        "profile_id": "subscription_saas",
        "build": build_units,
        "expected_kind": "taxonomy",
        "expected_codes": ("driver_unit_non_canonical", "driver_unit_mismatch"),
        "expected_text": "driver_unit_non_canonical (e driver_unit_mismatch "
                         "per l'unita' incompatibile con il ruolo)",
    },
    {
        "contract_id": "T-FIN-FREQUENCY",
        "planning_section": "frequenza dichiarata, mai dedotta",
        "fixture_id": "demo",
        "fixture_label": "progetto demo, driver senza frequency",
        "profile_id": "subscription_saas",
        "build": build_frequency,
        "expected_kind": "taxonomy",
        "expected_codes": ("driver_frequency_undeclared",),
        "expected_text": "driver_frequency_undeclared",
    },
    {
        "contract_id": "T-FIN-TIMING",
        "planning_section": "REC-12: Sigma quote = 1 solo per i flow",
        "fixture_id": "demo",
        "fixture_label": "progetto demo, custom_schedule che somma 0.9 su un "
                         "driver measure_kind: flow",
        "profile_id": "subscription_saas",
        "build": build_timing,
        "expected_kind": "normative_rec",
        "expected_codes": ("REC-12",),
        "expected_text": "violazione REC-12 (Sigma quote di ogni timing_rule = 1, "
                         "SOLO per measure_kind: flow; tolleranza ratio 1e-6, "
                         "severita' FAIL) -- esito normativo della "
                         "riconciliazione; piu' il caso negativo di "
                         "ambito: applicare la somma a stock/rate/per_unit e' "
                         "errore di APPLICAZIONE della regola",
    },
    {
        "contract_id": "T-FIN-STATUS-GATE-SINGLE",
        "planning_section": "input non risolto su ruolo richiesto: FAIL "
                            "al gate",
        "fixture_id": "demo",
        "fixture_label": "progetto demo, ASS-003 (value: null, needs_info) su "
                         "ruolo richiesto",
        "profile_id": "subscription_saas",
        "build": build_status_gate_single,
        "expected_kind": "taxonomy",
        "expected_codes": ("unresolved_required_input",),
        "expected_text": "unresolved_required_input => UNRESOLVED_INPUT => FAIL "
                         "al gate",
    },
    {
        "contract_id": "T-FIN-DUPLICATE-EXPLICIT",
        "planning_section": "un solo binding per un ruolo a cardinalita' "
                            "one",
        "fixture_id": "demo",
        "fixture_label": "progetto demo, due binding su unit_price via "
                         "explicit_declaration (ASS-015 + ASS-001)",
        "profile_id": "subscription_saas",
        "build": build_duplicate_explicit,
        "expected_kind": "taxonomy",
        "expected_codes": ("driver_duplicate_binding",),
        "expected_text": "driver_duplicate_binding",
    },
    {
        "contract_id": "T-FIN-DUPLICATE-MANY",
        "planning_section": "nessun duplicato sui ruoli a cardinalita' many",
        "fixture_id": "demo",
        "fixture_label": "progetto demo, duplicato sui ruoli many "
                         "(cogs_refs, headcount_driver_refs)",
        "profile_id": "subscription_saas",
        "build": build_duplicate_many,
        "expected_kind": "taxonomy",
        "expected_codes": ("driver_duplicate_binding",),
        "expected_text": "driver_duplicate_binding",
    },
    {
        "contract_id": "T-FIN-AMBIGUITY",
        "planning_section": "un riferimento non serve ruoli incompatibili",
        "fixture_id": "demo",
        "fixture_label": "progetto demo, stesso ASS-* su due ruoli "
                         "incompatibili (unit_price e variable_cost)",
        "profile_id": "subscription_saas",
        "build": build_ambiguity,
        "expected_kind": "taxonomy",
        "expected_codes": ("driver_ref_ambiguous",),
        "expected_text": "driver_ref_ambiguous",
    },
    {
        "contract_id": "T-FIN-INPUT-KIND",
        "planning_section": "un driver informational non e' mai consumato",
        "fixture_id": "demo",
        "fixture_label": "progetto demo, driver informational letto dal motore",
        "profile_id": "subscription_saas",
        "build": build_input_kind,
        "expected_kind": "declared_code",
        # `expected_codes` porta il codice emesso dal validator: con un
        # insieme VUOTO `satisfied = bool(expected) and all(...)` resterebbe
        # SEMPRE False e il contratto sarebbe RED per una ragione DIVERSA da
        # quella dichiarata.
        "expected_codes": (AMB_02_FIXED_CODE,),
        "expected_text": AMB_02_EXPECTED,
        "amb_02_fixed_code": AMB_02_FIXED_CODE,
        "amb_02_fixed_by": AMB_02_FIXED_BY,
    },
    {
        "contract_id": "T-FIN-EXPLICIT-DECLARATION",
        "planning_section": "explicit_declaration ristretta e cumulativa",
        "fixture_id": "F-8",
        "fixture_label": "F-8 (tests/integration/bpo_testkit.py, registro "
                         "STAGE10_FIXTURES) -- sola lettura",
        "profile_id": "subscription_saas",
        "build": build_explicit_declaration,
        "expected_kind": "taxonomy",
        "expected_codes": ("driver_source_path_unverifiable",
                           "driver_explicit_declaration_unjustified"),
        # Gli expected_codes restano INVARIATI e non sono sostituiti. A essi
        # si AGGIUNGE l'evidenza attribuita a DRV-011, che rende PORTANTE il
        # ramo `resolved != source_ref` per questo contratto. Senza di essa il
        # codice resta osservabile per via di DRV-010 e DRV-012 e il ramo
        # semantico non e' discriminato.
        "expected_attribution": (ATTRIBUTION_F8_RED2,),
        "expected_text": "RED-1 e RED-2: driver_source_path_unverifiable; "
                         "RED-3: driver_explicit_declaration_unjustified; "
                         "RED-2 ATTRIBUITA: DRV-011 "
                         "business_model.contribution_margin_ref -> ASS-018 "
                         "contro source_ref ASS-015, semantica diversa",
    },
    {
        "contract_id": "T-FIN-STOCK-FLOW",
        "planning_section": "natura della misura dichiarata; REC-12 e "
                            "REC-14",
        "fixture_id": "F-5",
        "fixture_label": "F-5 (tests/integration/bpo_testkit.py, registro "
                         "STAGE10_FIXTURES) -- sola lettura",
        "profile_id": "subscription_saas",
        "build": build_stock_flow,
        "expected_kind": "mixed",
        "expected_codes": ("driver_measure_undeclared", "REC-14", "REC-12"),
        "expected_text": "RED-1: driver_measure_undeclared; RED-2: violazione "
                         "REC-14 (livello di ogni periodo = serie dichiarata, "
                         "ogni variazione spiegata da un evento dichiarato -- "
                         "measure_kind: stock, severita' FAIL); RED-3: "
                         "violazione REC-12 (Sigma quote = 1 -- measure_kind: flow, "
                         "severita' FAIL). RED-2 e RED-3 sono ESITI NORMATIVI "
                         "delle riconciliazioni",
    },
    {
        "contract_id": "T-FIN-DRIVER-STALE",
        "planning_section": "impronta del record legato allineata al "
                            "canonico",
        "fixture_id": "demo",
        "fixture_label": "progetto demo + update-assumption costruito in "
                         "memoria su ASS-015",
        "profile_id": "subscription_saas",
        "build": build_driver_stale,
        "expected_kind": "taxonomy",
        "expected_codes": ("driver_source_stale",),
        "expected_text": "driver_source_stale",
    },
    {
        "contract_id": "T-FIN-STATUS-MATRIX",
        "planning_section": "mappatura di stato totale e fail-closed",
        "fixture_id": "F-9",
        "fixture_label": "F-9 (tests/integration/bpo_testkit.py, registro "
                         "STAGE10_FIXTURES) -- matrice 4 x 7 piu' i casi "
                         "speciali -- sola lettura",
        "profile_id": "subscription_saas",
        "build": build_status_matrix,
        "expected_kind": "taxonomy",
        "expected_codes": ("driver_status_unmappable",),
        "expected_text": "driver_status_unmappable",
    },
)

CONTRACT_IDS = tuple(entry["contract_id"] for entry in CONTRACTS)


# --------------------------------------------------------------------------
# Contesto e livello A eseguibile da solo
# --------------------------------------------------------------------------


def build_context(root):
    """Livello A condiviso: testkit, fixture, canonico demo, profili, CAS."""
    testkit = load_testkit(root)
    fingerprint = load_fingerprint(root, testkit)
    demo = load_demo(root)
    fixtures = {}
    for fixture_id in sorted({entry["fixture_id"] for entry in CONTRACTS}
                             - {"demo"}):
        try:
            fixtures[fixture_id] = testkit.stage10_fixture(fixture_id)
        except Exception as exc:
            raise HarnessDefect(
                f"fixture {fixture_id} non caricabile in sola lettura: {exc}")
    profiles = {}
    for profile_id in sorted({entry["profile_id"] for entry in CONTRACTS}):
        profiles[profile_id] = load_profile(root, profile_id)
    financial_cfg = testkit.stage10_fixture("F-11")
    if not financial_cfg.get("valid"):
        raise HarnessDefect(
            "F-11 senza variante `valid`: la configurazione finanziaria "
            "dell'input non e' costruibile")
    return {
        "root": root,
        "testkit": testkit,
        "fingerprint": fingerprint,
        "demo": demo,
        "fixtures": fixtures,
        "profiles": profiles,
        "financial_config": financial_cfg["valid"],
        "entry_point": root / ENTRY_POINT_REL,
    }


def check_binding_rows(contract_id, rows):
    """Il livello A verifica che l'input sia COSTRUITO, non che sia VALIDO.

    Ogni riga deve portare TUTTE le chiavi obbligatorie e nessuna
    chiave fuori dall'insieme dichiarato: il difetto del contratto e'
    deliberato e DICHIARATO, mai ottenuto omettendo una chiave in silenzio.
    """
    if not rows:
        raise HarnessDefect(
            f"{contract_id}: nessuna riga di binding costruita -- l'input non "
            "esiste, quindi il contratto non sarebbe esercitato")
    allowed = set(BINDING_REQUIRED_FIELDS) | set(BINDING_OPTIONAL_FIELDS)
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise HarnessDefect(
                f"{contract_id}: riga di binding {index} non e' un oggetto")
        missing = [field for field in BINDING_REQUIRED_FIELDS
                   if field not in row]
        if missing:
            raise HarnessDefect(
                f"{contract_id}: riga di binding {row.get('driver_id', index)} "
                f"incompleta, chiavi obbligatorie assenti: {missing}")
        unexpected = sorted(set(row) - allowed)
        if unexpected:
            raise HarnessDefect(
                f"{contract_id}: riga di binding {row.get('driver_id', index)} "
                f"con chiavi non previste: {unexpected}")


def level_a(ctx, contract):
    """Livello A del singolo contratto: COSTRUZIONE COMPLETA dell'input.

    DEVE riuscire. Un fallimento qui e' un difetto di harness, non
    evidenza RED, e si manifesta come exit 3 -- mai come exit 1.
    """
    contract_id = contract["contract_id"]
    profile = ctx["profiles"][contract["profile_id"]]
    fixture_id = contract["fixture_id"]
    if fixture_id != "demo" and fixture_id not in ctx["fixtures"]:
        raise HarnessDefect(
            f"{contract_id}: fixture {fixture_id} non disponibile")
    local = {
        "profile": profile,
        "demo": ctx["demo"],
        "fixtures": ctx["fixtures"],
        "fingerprint": ctx["fingerprint"],
    }
    built = contract["build"](local)
    rows = built.get("driver_bindings")
    check_binding_rows(contract_id, rows)
    if not built.get("deliberate_defect"):
        raise HarnessDefect(
            f"{contract_id}: input costruito senza difetto DICHIARATO -- un "
            "contratto senza violazione dichiarata non discrimina")
    entry_point = ctx["entry_point"]
    payload = {
        "contract_id": contract_id,
        "planning_section": contract["planning_section"],
        "fixture_id": fixture_id,
        "fixture": contract["fixture_label"],
        "profile_id": contract["profile_id"],
        "financial_config": ctx["financial_config"],
        "project": ctx["demo"]["project_rel"],
        "stage": STAGE10,
        "phase": "egress",
        "entry_point": ENTRY_POINT_REL,
        "entry_point_resolved": str(entry_point),
        "driver_binding_count": len(rows),
    }
    payload.update(built)
    return payload


def selfcheck(ctx):
    """`--selfcheck` -- SOLO il livello A, per TUTTI i contratti. Exit 0 atteso.

    La sua riuscita e' EVIDENZA POSITIVA che l'input di ogni contratto e' stato
    DAVVERO costruito prima che il livello B fallisse.
    """
    lines = []
    for contract in CONTRACTS:
        payload = level_a(ctx, contract)
        lines.append(
            "LEVEL A OK  {cid:<28} fixture={fx:<6} bindings={n:<3} "
            "defect={defect}".format(
                cid=payload["contract_id"], fx=payload["fixture_id"],
                n=payload["driver_binding_count"],
                defect=payload["deliberate_defect"]["kind"]))
    lines.append(
        f"LEVEL A OK  {len(CONTRACTS)} contratti preparati; punto d'ingresso "
        f"dichiarato: {ENTRY_POINT_REL}")
    lines.append(
        "LEVEL A OK  entry point presente: {}".format(
            "SI" if ctx["entry_point"].is_file() else "NO"))
    return lines


# --------------------------------------------------------------------------
# Livello B -- invocazione del punto d'ingresso dichiarato
# --------------------------------------------------------------------------


def serialize_payload(payload):
    """Serializzazione DETERMINISTICA del payload di livello A.

    `sort_keys=True` rende l'impronta riproducibile fra esecuzioni: due
    esecuzioni dello stesso contratto producono la STESSA impronta, e due
    contratti diversi producono impronte DIVERSE: SEDICI payload distinti,
    non uno.
    """
    blob = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
    return blob, hashlib.sha256(blob.encode("utf-8")).hexdigest()


def level_b(ctx, contract, payload):
    """Invoca il punto d'ingresso DICHIARATO e valuta l'esito.

    Se il punto d'ingresso manca, l'esito e' la ragione UNIFORME
    `MISSING_CAPABILITY: validate_financial_binding`, e il contratto e' RED al
    livello B -- mai al livello A.

    Quando il punto d'ingresso esiste l'invocazione e' reale: il report JSON e'
    letto e i codici OSSERVATI sono confrontati con quelli DICHIARATI al
    livello C. Nessuna assertion e' condizionale.

    TRASMISSIONE DEL PAYLOAD
    ------------------------
    Il payload costruito dal livello A PER IL CONTRATTO IN ESECUZIONE e'
    TRASMESSO al validator: il livello A produce la costruzione completa
    dell'input di binding del contratto e il livello B ne e' l'INVOCAZIONE.
    Senza il canale di trasmissione l'esito sarebbe STRUTTURALE e non
    SEMANTICO.

    Il payload e' materializzato ESCLUSIVAMENTE sotto una directory
    temporanea del sistema, che e' anche il candidate workspace della fase
    `egress`. NIENTE e' scritto dentro `examples/fictional-startup` e
    nessuna cartella `10_financial-plan/` e' creata nel demo.

    La fase e' quella DICHIARATA DAL PAYLOAD del contratto
    (`payload["phase"]`), mai una costante di questa funzione. La fase
    RICHIESTA e quella RIPORTATA dal validator sono entrambe registrate, cosi'
    che un payload dichiarato `egress` non possa essere eseguito in silenzio
    come `impact`.

    La semantica di `observed` (codici di `report.errors[]` e
    `check_id` dei `report.checks[]` con `status: FAIL`) e la regola
    `satisfied` (TUTTI gli `expected_codes` presenti fra gli `observed`)
    restano INVARIATE.
    """
    entry_point = ctx["entry_point"]
    blob, digest = serialize_payload(payload)
    phase = payload["phase"]
    if not entry_point.is_file():
        return {
            "red": True,
            "level": LEVEL_B,
            "reason": MISSING_CAPABILITY_REASON,
            "observed_codes": [],
            "detail": f"{ENTRY_POINT_REL} non esiste: la capacita' dichiarata "
                      "non e' implementata",
            "phase_requested": phase,
            "phase_reported": None,
            "payload_digest": digest,
            "payload_bytes": len(blob),
        }
    with tempfile.TemporaryDirectory(prefix="fin_binding_") as tmp:
        candidate = Path(tmp)
        binding_input = candidate / "binding-input.json"
        binding_input.write_text(blob, encoding="utf-8")
        command = [sys.executable, str(entry_point),
                   "--project", str(ctx["demo"]["project_path"]),
                   "--stage", payload["stage"], "--phase", phase,
                   "--candidate", str(candidate),
                   "--binding-input", str(binding_input)]
        try:
            proc = subprocess.run(command, capture_output=True, text=True,
                                  cwd=str(ctx["root"]))
        except OSError as exc:
            return {
                "red": True,
                "level": LEVEL_B,
                "reason": MISSING_CAPABILITY_REASON,
                "observed_codes": [],
                "detail": f"invocazione non eseguibile: {exc}",
                "phase_requested": phase,
                "phase_reported": None,
                "payload_digest": digest,
                "payload_bytes": len(blob),
            }
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {
            "red": True,
            "level": LEVEL_B,
            "reason": "INVALID_REPORT: il punto d'ingresso non ha prodotto un "
                      "report JSON su stdout",
            "observed_codes": [],
            "detail": (proc.stdout or "") + (proc.stderr or ""),
            "phase_requested": phase,
            "phase_reported": None,
            "payload_digest": digest,
            "payload_bytes": len(blob),
            "exit_code": proc.returncode,
        }
    observed = [error.get("code") for error in report.get("errors") or []]
    observed += [check.get("check_id") for check in report.get("checks") or []
                 if check.get("status") == "FAIL"]
    expected = list(contract["expected_codes"])
    satisfied = bool(expected) and all(code in observed for code in expected)
    reason = ("" if satisfied else
              "EXPECTED_CODES_NOT_OBSERVED: "
              f"attesi {expected}, osservati {observed}")
    # Discriminazione ATTRIBUITA, IN AGGIUNTA e mai al posto
    # della regola qui sopra. Si applica al SOLO contratto che la dichiara: i
    # quindici contratti che non portano `expected_attribution` eseguono la
    # regola di accettazione INVARIATA, byte per byte.
    if satisfied:
        for spec in contract.get("expected_attribution") or ():
            violation = attribution_violation(report, spec)
            if violation:
                satisfied = False
                reason = ("ATTRIBUTION_NOT_OBSERVED: {} -- {}".format(
                    spec["label"], violation))
                break
    return {
        "red": not satisfied,
        "level": LEVEL_B,
        "reason": reason,
        "observed_codes": observed,
        "detail": json.dumps(report, ensure_ascii=True),
        "exit_code": proc.returncode,
        "phase_requested": phase,
        "phase_reported": report.get("phase"),
        "payload_digest": digest,
        "payload_bytes": len(blob),
    }


# --------------------------------------------------------------------------
# Livello C -- dichiarazione, registrata e non eseguita
# --------------------------------------------------------------------------


def level_c(contract):
    return {
        "level": LEVEL_C,
        "expected_kind": contract["expected_kind"],
        "expected_codes": list(contract["expected_codes"]),
        "expected_text": contract["expected_text"],
    }


def run_contract(ctx, contract):
    payload = level_a(ctx, contract)
    outcome = level_b(ctx, contract, payload)
    declaration = level_c(contract)
    return {
        "contract_id": contract["contract_id"],
        "payload": payload,
        "outcome": outcome,
        "declaration": declaration,
    }


def format_contract_line(result):
    """Riga di esito del contratto.

    La riga espone anche la FASE usata dall'invocazione e l'impronta del
    PAYLOAD trasmesso: sono i due fatti registrati per ciascuna delle sedici
    invocazioni.
    """
    outcome = result["outcome"]
    declaration = result["declaration"]
    state = "RED" if outcome["red"] else "GREEN"
    phase = "{}->{}".format(outcome.get("phase_requested"),
                            outcome.get("phase_reported"))
    digest = (outcome.get("payload_digest") or "")[:12]
    return (
        "{state:<5} {cid:<28} level={level} phase={phase} payload={digest} "
        "observed={observed} reason={reason} | EXPECTED: "
        "{expected}".format(
            state=state, cid=result["contract_id"],
            level=outcome["level"], phase=phase, digest=digest or "-",
            observed=sorted(set(outcome.get("observed_codes") or [])) or "-",
            reason=outcome["reason"] or "-",
            expected=declaration["expected_text"]))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(
        prog="test_fin_binding.py", add_help=True,
        description="Harness dei sedici contratti di binding e integrita' "
                    "dei driver.")
    parser.add_argument("--root", required=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--selfcheck", action="store_true",
                      help="esegue SOLO il livello A; exit 0 atteso")
    mode.add_argument("--contract", help="esegue un solo contratto")
    mode.add_argument("--all", action="store_true",
                      help="esegue tutti i contratti (default)")
    parser.add_argument("--list", action="store_true",
                        help="elenca gli id dei sedici contratti")
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
        print(f"USAGE ERROR: contratto inesistente: {args.contract}; "
              f"ammessi: {', '.join(CONTRACT_IDS)}", file=sys.stderr)
        return EXIT_USAGE

    try:
        ctx = build_context(root)
        if args.selfcheck:
            for line in selfcheck(ctx):
                print(line)
            print(f"SELFCHECK OK: livello A riuscito per tutti i "
                  f"{len(CONTRACTS)} contratti")
            return EXIT_OK
        selected = [c for c in CONTRACTS
                    if not args.contract or c["contract_id"] == args.contract]
        results = [run_contract(ctx, contract) for contract in selected]
    except HarnessDefect as exc:
        print(f"HARNESS DEFECT (level A): {exc}", file=sys.stderr)
        return EXIT_STATE
    except HarnessStateError as exc:
        print(f"CANONICAL STATE ERROR: {exc}", file=sys.stderr)
        return EXIT_STATE
    except HarnessUsageError as exc:
        print(f"USAGE ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE

    for result in results:
        print(format_contract_line(result))
    red = [r for r in results if r["outcome"]["red"]]
    digests = {r["outcome"].get("payload_digest") for r in results}
    phases = sorted({r["outcome"].get("phase_requested") for r in results})
    print("SUMMARY: {total} contratti, {red} RED, {green} GREEN "
          "(entry point {ep}: {state})".format(
              total=len(results), red=len(red), green=len(results) - len(red),
              ep=ENTRY_POINT_REL,
              state="presente" if ctx["entry_point"].is_file() else "ASSENTE"))
    # Misura strumentata: i payload trasmessi al validator sono DISTINTI,
    # uno per contratto.
    print("PAYLOADS: {distinct} payload distinti su {total} invocazioni di "
          "livello B; fasi dichiarate dai payload: {phases}".format(
              distinct=len(digests), total=len(results),
              phases=", ".join(map(str, phases))))
    if red:
        return EXIT_RED
    print("PASS: T-FIN-BINDING sedici contratti di binding e integrita'")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
