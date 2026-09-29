#!/usr/bin/env python3
"""Shared fixtures for the Stage 4-9 domain tests (not a test file).

Builds canonical projects that have really completed Stage 4 (and Stage 5)
with a coherent, recomputable assumption chain, plus candidate proposals
for business model (Stage 5) and sales funnel (Stage 6). The canonical
chain mirrors the T-MARKET-MATH happy path: TAM 10M >= SAM 3M >= SOM 1M,
weighted_average reconciliation, SOM bottom-up (10000 * 0.1 * 1000).
"""
import copy

import bpo_testkit as kit

S4 = "04_market-and-competition"
S5 = "05_business-model"
S6 = "06_go-to-market"

COMPLETED_THROUGH_4 = ["00_idea-discovery", "01_problem-and-need",
                       "02_customer-segmentation", "03_value-proposition",
                       S4]
COMPLETED_THROUGH_5 = COMPLETED_THROUGH_4 + [S5]

PRICING_ID = "ASS-012"
SOM_ID = "ASS-011"
ARPA_ID = "ASS-003"
MARGIN_ID = "ASS-015"
REVENUE_ID = "ASS-017"


def entry(ref, variable, value, unit, category="market", **over):
    """Register entry; `ref` may be canonical (ASS-*) or proposed (P-ASS-*)."""
    out = {
        "id": ref,
        "category": category,
        "variable": variable,
        "statement": f"{variable} (fixture di test)",
        "value": value,
        "display_value": f"{value} {unit}",
        "unit": unit,
        "source": "fixture",
        "owner": "founder",
        "confidence": "low",
        "validation_status": "unvalidated",
        "evidence_classification": "founder_assumption",
        "affected_sections": [S5],
        "last_updated": "2026-07-16",
        "previous_values": [],
    }
    out.update(over)
    return out


def derived(ref, variable, value, unit, formula, variables, method,
            strategy=None, **over):
    derivation = {"method": method, "variables": variables}
    if formula is not None:
        derivation["formula"] = formula
    if strategy is not None:
        derivation["strategy"] = strategy
    out = entry(ref, variable, value, unit,
                kind="derived", derivation=derivation,
                currency="EUR" if str(unit).startswith("EUR") else None,
                period="Y1", scenario="base",
                evidence_classification="model_estimate")
    out.update(over)
    return out


def landscape():
    cats = {}
    for i, cat in enumerate(("direct", "indirect", "substitutes"), start=1):
        cats[cat] = {"competitors": [{
            "id": f"CMP-00{i}",
            "name": f"{cat} player",
            "assessment": "forte sull'enterprise, scoperto sulle PMI",
        }]}
    for cat in ("internal", "non_consumption", "status_quo"):
        cats[cat] = {
            "result": "none_identified",
            "research_notes": "directory di settore e interviste beachhead",
            "rationale": "nessun attore rilevante per il segmento",
        }
    return {"categories": cats}


def market_assumptions():
    """Canonical Stage 4 chain (ASS-001..ASS-011), fully recomputable."""
    return [
        entry("ASS-001", "eligible_customers", 10000, "count"),
        entry("ASS-002", "reachable_share", 0.1, "ratio"),
        entry("ASS-003", "arpa_year", 1000, "EUR/count"),
        entry("ASS-004", "tam_topdown", 10000000, "EUR"),
        derived("ASS-005", "tam_bottomup", 10000000, "EUR",
                "eligible_customers * arpa_year",
                {"eligible_customers": "ASS-001", "arpa_year": "ASS-003"},
                "bottom_up"),
        entry("ASS-006", "w_topdown", 0.6, "ratio"),
        entry("ASS-007", "w_bottomup", 0.4, "ratio"),
        derived("ASS-008", "tam_canonical", 10000000, "EUR",
                "tam_topdown * w_topdown + tam_bottomup * w_bottomup",
                {"tam_topdown": "ASS-004", "tam_bottomup": "ASS-005",
                 "w_topdown": "ASS-006", "w_bottomup": "ASS-007"},
                "reconciliation", strategy="weighted_average"),
        entry("ASS-009", "addressable_share", 0.3, "ratio"),
        derived("ASS-010", "sam_topdown", 3000000, "EUR",
                "tam_canonical * addressable_share",
                {"tam_canonical": "ASS-008", "addressable_share": "ASS-009"},
                "top_down"),
        derived("ASS-011", "som_y1_revenue", 1000000, "EUR",
                "eligible_customers * reachable_share * arpa_year",
                {"eligible_customers": "ASS-001",
                 "reachable_share": "ASS-002",
                 "arpa_year": "ASS-003"}, "bottom_up"),
    ]


def market_structured():
    return {
        "market_model": {"tam_ref": "ASS-008", "sam_ref": "ASS-010",
                         "som_ref": SOM_ID, "geography": "IT",
                         "period": "Y1"},
        "competitive_landscape": landscape(),
    }


def business_assumptions():
    """Canonical Stage 5 chain (ASS-012..ASS-017)."""
    return [
        entry(PRICING_ID, "price_net", 100, "EUR/count", category="pricing"),
        entry("ASS-013", "cogs_unit", 30, "EUR/count", category="cost"),
        entry("ASS-014", "support_unit", 10, "EUR/count", category="cost"),
        derived(MARGIN_ID, "contribution_margin_unit", 60, "EUR/count",
                "price_net - (cogs_unit + support_unit)",
                {"price_net": PRICING_ID, "cogs_unit": "ASS-013",
                 "support_unit": "ASS-014"}, "bottom_up"),
        entry("ASS-016", "units_y1", 5000, "count", category="demand"),
        derived(REVENUE_ID, "revenue_y1", 500000, "EUR",
                "units_y1 * price_net",
                {"units_y1": "ASS-016", "price_net": PRICING_ID},
                "bottom_up"),
    ]


def business_structured(price=100, pricing_ref=PRICING_ID,
                        revenue_ref=REVENUE_ID, margin_ref=MARGIN_ID):
    model = {
        "pricing_ref": pricing_ref,
        "revenue_ref": revenue_ref,
        "contribution_margin_ref": margin_ref,
        "recurrence": "annual",
        "channel": "direct",
    }
    if price is not None:
        model["price"] = price
    return {"business_model": model}


def business_proposed(price=100, margin=60):
    """Stage-5 candidate proposals (P-ASS-001..P-ASS-006)."""
    return [
        entry("P-ASS-001", "price_net", price, "EUR/count",
              category="pricing"),
        entry("P-ASS-002", "cogs_unit", 30, "EUR/count", category="cost"),
        entry("P-ASS-003", "support_unit", 10, "EUR/count", category="cost"),
        derived("P-ASS-004", "contribution_margin_unit", margin, "EUR/count",
                "price_net - (cogs_unit + support_unit)",
                {"price_net": "P-ASS-001", "cogs_unit": "P-ASS-002",
                 "support_unit": "P-ASS-003"}, "bottom_up"),
        entry("P-ASS-005", "units_y1", 5000, "count", category="demand"),
        derived("P-ASS-006", "revenue_y1",
                round(5000 * price, 2), "EUR",
                "units_y1 * price_net",
                {"units_y1": "P-ASS-005", "price_net": "P-ASS-001"},
                "bottom_up"),
    ]


def business_structured_proposed(price=100):
    return business_structured(price=price, pricing_ref="P-ASS-001",
                               revenue_ref="P-ASS-006",
                               margin_ref="P-ASS-004")


def funnel_proposed(leads=20000, rate1=0.25, rate2=0.2, spend=200000,
                    churn=0.15, arpa_ref=ARPA_ID):
    """Stage-6 candidate proposals; customers/cac/capacity kept coherent."""
    customers = round(leads * rate1 * rate2)
    cac = round(spend / customers, 2)
    capacity = customers * 1000  # arpa_year canonico (ASS-003)
    return [
        entry("P-ASS-001", "leads_y1", leads, "count", category="gtm"),
        entry("P-ASS-002", "rate_mql_sql", rate1, "ratio", category="gtm"),
        entry("P-ASS-003", "rate_sql_win", rate2, "ratio", category="gtm"),
        derived("P-ASS-004", "customers_out_y1", customers, "count",
                "leads_y1 * rate_mql_sql * rate_sql_win",
                {"leads_y1": "P-ASS-001", "rate_mql_sql": "P-ASS-002",
                 "rate_sql_win": "P-ASS-003"}, "bottom_up"),
        entry("P-ASS-005", "sm_spend_y1", spend, "EUR", category="gtm"),
        derived("P-ASS-006", "cac_y1", cac, "EUR/count",
                "sm_spend_y1 / customers_out_y1",
                {"sm_spend_y1": "P-ASS-005",
                 "customers_out_y1": "P-ASS-004"}, "bottom_up"),
        entry("P-ASS-007", "churn_annual", churn, "ratio", category="gtm"),
        derived("P-ASS-008", "gtm_capacity_revenue_y1", capacity, "EUR",
                "customers_out_y1 * arpa_year",
                {"customers_out_y1": "P-ASS-004", "arpa_year": arpa_ref},
                "bottom_up"),
    ]


def funnel_structured(pricing_ref=PRICING_ID, refs=None):
    base = {
        "leads_ref": "P-ASS-001",
        "stages": [
            {"name": "mql_to_sql", "rate_ref": "P-ASS-002"},
            {"name": "sql_to_win", "rate_ref": "P-ASS-003"},
        ],
        "customers_out_ref": "P-ASS-004",
        "spend_ref": "P-ASS-005",
        "cac_ref": "P-ASS-006",
        "churn_ref": "P-ASS-007",
        "capacity_revenue_ref": "P-ASS-008",
        "pricing_ref": pricing_ref,
    }
    if refs:
        base.update(refs)
    return {"sales_funnel": base}


def make_stage5_project(tmp, name):
    """Canonical project entering Stage 5: Stage 4 applied and completed."""
    project = kit.make_project(
        tmp, name=name, current_stage=S5, status="in_progress",
        completed=COMPLETED_THROUGH_4, assumptions=market_assumptions())
    kit.write_json(project / S4 / "structured-output.json",
                   market_structured())
    return project


def make_stage6_project(tmp, name, assumptions_extra=None):
    """Canonical project entering Stage 6: Stage 4-5 applied and completed."""
    assumptions = market_assumptions() + business_assumptions()
    if assumptions_extra:
        assumptions = assumptions + assumptions_extra
    project = kit.make_project(
        tmp, name=name, current_stage=S6, status="in_progress",
        completed=COMPLETED_THROUGH_5, assumptions=assumptions)
    kit.write_json(project / S4 / "structured-output.json",
                   market_structured())
    kit.write_json(project / S5 / "structured-output.json",
                   business_structured())
    return project


def with_variable(proposed, variable, **changes):
    out = copy.deepcopy(proposed)
    for item in out:
        if item["variable"] == variable:
            item.update(copy.deepcopy(changes))
            return out
    raise AssertionError(f"fixture senza variabile {variable}")


# ---------------------------------------------------------------------------
# Stage 6 canonico + Stage 7 (operations & IP).
#
# Estensione ADDITIVA: nessuna firma esistente cambia. Serve alle prove T-OPS-FEASIBILITY e T-CROSS-EXT (parte ops), che
# hanno bisogno di un progetto entrato allo Stage 7 con gli Stage 4-6
# canonici (funnel applicato: gli ASS- del GTM non sono più P-ASS-).
# ---------------------------------------------------------------------------
S7 = "07_operations-and-ip"

COMPLETED_THROUGH_6 = COMPLETED_THROUGH_5 + [S6]

# GTM canonico (Stage 6 applicato): ASS-018..025, ricalcolabile.
LEADS_ID = "ASS-018"
CUSTOMERS_OUT_ID = "ASS-021"
GTM_CAPACITY_REVENUE_ID = "ASS-025"


def gtm_assumptions():
    """Catena canonica dello Stage 6 (funnel applicato), tutta ricalcolabile.

    customers_out = leads x tassi = 1000; capacity_revenue = customers_out x
    arpa_year (ASS-003 = 1000 EUR) = 1_000_000 = SOM canonico (ASS-011)."""
    return [
        entry(LEADS_ID, "leads_y1", 20000, "count", category="gtm"),
        entry("ASS-019", "rate_mql_sql", 0.25, "ratio", category="gtm"),
        entry("ASS-020", "rate_sql_win", 0.2, "ratio", category="gtm"),
        derived(CUSTOMERS_OUT_ID, "customers_out_y1", 1000, "count",
                "leads_y1 * rate_mql_sql * rate_sql_win",
                {"leads_y1": LEADS_ID, "rate_mql_sql": "ASS-019",
                 "rate_sql_win": "ASS-020"}, "bottom_up"),
        entry("ASS-022", "sm_spend_y1", 200000, "EUR", category="gtm"),
        derived("ASS-023", "cac_y1", 200, "EUR/count",
                "sm_spend_y1 / customers_out_y1",
                {"sm_spend_y1": "ASS-022",
                 "customers_out_y1": CUSTOMERS_OUT_ID}, "bottom_up"),
        entry("ASS-024", "churn_annual", 0.15, "ratio", category="gtm"),
        derived(GTM_CAPACITY_REVENUE_ID, "gtm_capacity_revenue_y1", 1000000,
                "EUR", "customers_out_y1 * arpa_year",
                {"customers_out_y1": CUSTOMERS_OUT_ID, "arpa_year": ARPA_ID},
                "bottom_up"),
    ]


def gtm_structured(pricing_ref=PRICING_ID):
    return {"sales_funnel": {
        "leads_ref": LEADS_ID,
        "stages": [
            {"name": "mql_to_sql", "rate_ref": "ASS-019"},
            {"name": "sql_to_win", "rate_ref": "ASS-020"},
        ],
        "customers_out_ref": CUSTOMERS_OUT_ID,
        "spend_ref": "ASS-022",
        "cac_ref": "ASS-023",
        "churn_ref": "ASS-024",
        "capacity_revenue_ref": GTM_CAPACITY_REVENUE_ID,
        "pricing_ref": pricing_ref,
    }}


# Stage 7 — capacità operativa proposta come P-ASS- (candidate), ricalcolabile:
# ops_capacity = installed_capacity (count) x utilization (ratio) = 1200 count.
OPS_CAPACITY_ID = "P-ASS-101"
COGS_ID = "ASS-013"  # costo operativo unitario canonico dello Stage 5


def ops_proposed(capacity=1200, installed=1500, utilization=0.8):
    return [
        entry("P-ASS-102", "installed_capacity", installed, "count",
              category="operations"),
        entry("P-ASS-103", "utilization", utilization, "ratio",
              category="operations"),
        derived(OPS_CAPACITY_ID, "ops_capacity_units", capacity, "count",
                "installed_capacity * utilization",
                {"installed_capacity": "P-ASS-102",
                 "utilization": "P-ASS-103"}, "bottom_up"),
    ]


def operations_structured(capacity_ref=OPS_CAPACITY_ID,
                          unit_ops_cost_refs=None, risk_refs=None):
    if unit_ops_cost_refs is None:
        unit_ops_cost_refs = [COGS_ID]
    if risk_refs is None:
        risk_refs = ["RISK-001"]
    return {"operations_model": {
        "core_processes": [{
            "id": "OPS-001",
            "entity_type": "core_process",
            "name": "Provisioning e onboarding cliente",
            "make_buy_partner": "make",
            "owner_hint": "Head of Operations",
            "bottleneck": True,
        }],
        "capacity_ref": capacity_ref,
        "unit_ops_cost_refs": list(unit_ops_cost_refs),
        "critical_dependencies": [{
            "id": "OPS-002",
            "entity_type": "dependency",
            "name": "Fornitore IaaS cloud",
            "category": "infrastructure",
            "single_source": True,
            "mitigation": "contratti multi-region + piano di exit documentato",
        }],
        "regulatory_requirements": [{
            "requirement": "Trattamento dati personali (GDPR)",
            "assessment": "DPA firmati e registro dei trattamenti predisposto",
        }],
        "ip_strategy": {
            "assets": [{
                "id": "OPS-003",
                "entity_type": "ip_asset",
                "name": "Motore di matching proprietario",
                "protection": "trade_secret",
                "rationale": "know-how core non brevettabile, tenuto segreto",
            }],
            "know_how_protection": "NDA e segregazione dei repository",
        },
        "risk_refs": list(risk_refs),
    }}


def risk_register():
    return [{
        "id": "RISK-001",
        "statement": "Interruzione del fornitore cloud single-source",
        "category": "operational",
        "severity": "medium",
        "likelihood": "medium",
        "mitigation": "multi-region + piano di exit",
        "status": "open",
        "owner": "founder",
    }]


def make_stage7_project(tmp, name, assumptions_extra=None):
    """Progetto canonico entrato allo Stage 7: Stage 4-6 applicati e completati.

    Gli Stage 4-6 sono canonici (structured-output + registro ASS-); lo
    Stage 7 vive nel candidate (operations_model + P-ASS- di capacità)."""
    assumptions = (market_assumptions() + business_assumptions()
                   + gtm_assumptions())
    if assumptions_extra:
        assumptions = assumptions + assumptions_extra
    project = kit.make_project(
        tmp, name=name, current_stage=S7, status="in_progress",
        completed=COMPLETED_THROUGH_6, assumptions=assumptions)
    kit.write_json(project / S4 / "structured-output.json",
                   market_structured())
    kit.write_json(project / S5 / "structured-output.json",
                   business_structured())
    kit.write_json(project / S6 / "structured-output.json",
                   gtm_structured())
    kit.write_json(project / "shared" / "risk-register.json", risk_register())
    (project / S7).mkdir(exist_ok=True)
    return project


# ---------------------------------------------------------------------------
# Stage 7 canonico + Stage 8 (team & governance).
#
# Estensione ADDITIVA: nessuna firma esistente cambia e le fixture dello
# Stage 7 restano byte-identiche. Serve a T-TEAM-GOV, che ha
# bisogno di un progetto entrato allo Stage 8 con gli Stage 4-7 canonici (la
# capacità operativa non è più un P-ASS-) e con più di un processo core, così
# che la copertura ruoli->processi sia una matrice vera e non un caso banale.
# ---------------------------------------------------------------------------
S8 = "08_team-and-governance"

COMPLETED_THROUGH_7 = COMPLETED_THROUGH_6 + [S7]

# Stage 7 applicato: la catena di capacità vive nel registro canonico.
OPS_CAPACITY_CANONICAL_ID = "ASS-028"

# Stage 8: FTE e driver di costo headcount proposti nel candidate.
FTE_LEAD_ID = "P-ASS-201"
FTE_OPEN_ID = "P-ASS-202"
HEADCOUNT_COST_ID = "P-ASS-204"

CORE_PROCESS_IDS = ("OPS-001", "OPS-004", "OPS-005")


def ops_assumptions(capacity=1200, installed=1500, utilization=0.8):
    """Catena canonica dello Stage 7 (operations applicato), ricalcolabile:
    ops_capacity_units = installed_capacity x utilization = 1200 count."""
    return [
        entry("ASS-026", "installed_capacity", installed, "count",
              category="operations"),
        entry("ASS-027", "utilization", utilization, "ratio",
              category="operations"),
        derived(OPS_CAPACITY_CANONICAL_ID, "ops_capacity_units", capacity,
                "count", "installed_capacity * utilization",
                {"installed_capacity": "ASS-026", "utilization": "ASS-027"},
                "bottom_up"),
    ]


def canonical_operations_structured():
    """Operations model canonico dello Stage 7 con tre processi core.

    Riusa `operations_structured()` (invariata) e vi aggiunge i due
    processi core OPS-004/OPS-005: la copertura ruoli->processi dello Stage 8
    ha bisogno di una matrice, non di un solo processo."""
    doc = operations_structured(capacity_ref=OPS_CAPACITY_CANONICAL_ID)
    doc["operations_model"]["core_processes"] += [
        {
            "id": "OPS-004",
            "entity_type": "core_process",
            "name": "Erogazione e assistenza continuativa",
            "make_buy_partner": "make",
            "owner_hint": "Head of Delivery",
            "bottleneck": False,
        },
        {
            "id": "OPS-005",
            "entity_type": "core_process",
            "name": "Integrazione con i canali partner",
            "make_buy_partner": "partner",
            "owner_hint": "Head of Partnerships",
            "bottleneck": False,
        },
    ]
    return doc


def operations_buy_partner_only():
    """Operations model canonico con SOLI processi `buy`/`partner`, nessuno
    `make`, e nessun ruolo che li copra.

    Discriminante per `headcount_capacity_incoherent`: se il filtro
    make-only si allargasse a `buy`/`partner`, questi due processi
    verrebbero segnalati perché nessun ruolo li copre. Con il filtro
    corretto restano fuori dal controllo, non perché coperti."""
    doc = canonical_operations_structured()
    doc["operations_model"]["core_processes"] = [
        {
            "id": "OPS-101",
            "entity_type": "core_process",
            "name": "Contabilità esternalizzata",
            "make_buy_partner": "buy",
            "owner_hint": "Head of Operations",
            "bottleneck": False,
        },
        {
            "id": "OPS-102",
            "entity_type": "core_process",
            "name": "Logistica tramite partner",
            "make_buy_partner": "partner",
            "owner_hint": "Head of Partnerships",
            "bottleneck": False,
        },
    ]
    return doc


def team_proposed(headcount_cost=45000.0, fte_lead=1.0, fte_open=1.0,
                  cost_per_fte=45000.0, fte_unit="FTE"):
    """Driver di team proposti nel candidate dello Stage 8 (P-ASS-201..204).

    Il costo headcount è derivato dai driver (FTE x costo unitario): è il
    ricalcolo che rende discriminante `value_mismatch`."""
    return [
        entry(FTE_LEAD_ID, "fte_ceo", fte_lead, fte_unit, category="team"),
        entry(FTE_OPEN_ID, "fte_head_partnerships", fte_open, fte_unit,
              category="team"),
        entry("P-ASS-203", "cost_per_fte_year", cost_per_fte, "EUR/FTE",
              category="team"),
        derived(HEADCOUNT_COST_ID, "headcount_cost_partnerships",
                headcount_cost, "EUR",
                "fte_head_partnerships * cost_per_fte_year",
                {"fte_head_partnerships": FTE_OPEN_ID,
                 "cost_per_fte_year": "P-ASS-203"}, "bottom_up"),
    ]


def team_structured(roles=None, capability_gaps=None, hiring_plan=None,
                    decision_rights=None, equity_split=None, risk_refs=None):
    """Structured output dello Stage 8 conforme a team-governance.schema.json.

    Default coerente: ogni processo core coperto, ogni gap indirizzato, ogni
    decision right con un solo owner, equity che somma esattamente a 1."""
    if roles is None:
        roles = [
            {
                "id": "ROLE-001",
                "person": "Giulia Rossi (co-founder, CEO)",
                "responsibilities": [
                    "Provisioning e onboarding dei clienti",
                    "Erogazione del servizio e qualità",
                ],
                "covers_processes": ["OPS-001", "OPS-004"],
                "fte_ref": FTE_LEAD_ID,
            },
            {
                "id": "ROLE-002",
                "open_position": "Head of Partnerships",
                "responsibilities": ["Integrazione e gestione dei canali "
                                     "partner"],
                "covers_processes": ["OPS-005"],
                "fte_ref": FTE_OPEN_ID,
            },
        ]
    if capability_gaps is None:
        capability_gaps = [{
            "gap": "Compliance privacy (DPO) non presidiata internamente",
            # addressed_by porta il MECCANISMO risolvibile (qui l'advisor
            # dichiarato in advisors[]); la spiegazione discorsiva sta in
            # notes. Vedi il contratto in workflows/09_team-and-governance.md.
            "addressed_by": "advisor: Studio Legale Esempio",
            "notes": ("incarico legale esterno attivo, con retainer annuale "
                      "e clausola di reperibilità"),
        }]
    if hiring_plan is None:
        hiring_plan = [{
            "role_ref": "ROLE-002",
            "period": "Y1H2",
            "cost_driver_ref": HEADCOUNT_COST_ID,
        }]
    if decision_rights is None:
        decision_rights = [
            {"area": "Prodotto e roadmap", "owner_ref": "ROLE-001"},
            {"area": "Partnership e canali", "owner_ref": "ROLE-002",
             "consulted_refs": ["ROLE-001"]},
        ]
    if equity_split is None:
        equity_split = [
            {"holder": "Giulia Rossi", "share": 0.6},
            {"holder": "Marco Bianchi", "share": 0.4},
        ]
    if risk_refs is None:
        risk_refs = ["RISK-001"]
    return {"team_governance": {
        "roles": roles,
        "capability_gaps": capability_gaps,
        "hiring_plan": hiring_plan,
        "decision_rights": decision_rights,
        "governance": {
            "structure": "Srl con due soci fondatori e patto parasociale",
            "equity_split": equity_split,
            "vesting": "4 anni con cliff a 12 mesi",
            "incentives": "pool opzioni 10% riservato ai primi assunti",
        },
        "advisors": [{"name": "Studio Legale Esempio", "area": "IP e privacy"}],
        "risk_refs": list(risk_refs),
    }}


# Stage 8 applicato: gli stessi driver, con id canonici.
CANONICAL_TEAM_IDS = {
    FTE_LEAD_ID: "ASS-029",
    FTE_OPEN_ID: "ASS-030",
    "P-ASS-203": "ASS-031",
    HEADCOUNT_COST_ID: "ASS-032",
}


def team_assumptions(**kwargs):
    """Catena canonica dello Stage 8 (team applicato): gli stessi driver di
    `team_proposed()` con id `ASS-`, per le prove in fase impact."""
    out = []
    for item in copy.deepcopy(team_proposed(**kwargs)):
        item["id"] = CANONICAL_TEAM_IDS[item["id"]]
        derivation = item.get("derivation")
        if isinstance(derivation, dict):
            derivation["variables"] = {
                key: CANONICAL_TEAM_IDS.get(ref, ref)
                for key, ref in derivation["variables"].items()}
        out.append(item)
    return out


def canonical_team_structured(**kwargs):
    """Structured output dello Stage 8 con i driver canonici (`ASS-`)."""
    doc = copy.deepcopy(team_structured(**kwargs))
    block = doc["team_governance"]
    for role in block["roles"]:
        role["fte_ref"] = CANONICAL_TEAM_IDS.get(role["fte_ref"],
                                                 role["fte_ref"])
    for item in block["hiring_plan"]:
        item["cost_driver_ref"] = CANONICAL_TEAM_IDS.get(
            item["cost_driver_ref"], item["cost_driver_ref"])
    return doc


def make_stage8_project(tmp, name, assumptions_extra=None,
                        operations=None, conditions=None):
    """Progetto canonico entrato allo Stage 8: Stage 4-7 applicati e completati.

    Gli Stage 4-7 sono canonici (structured-output + registro ASS-); lo
    Stage 8 vive nel candidate (team_governance + P-ASS- di FTE/costi)."""
    assumptions = (market_assumptions() + business_assumptions()
                   + gtm_assumptions() + ops_assumptions())
    if assumptions_extra:
        assumptions = assumptions + assumptions_extra
    project = kit.make_project(
        tmp, name=name, current_stage=S8, status="in_progress",
        completed=COMPLETED_THROUGH_7, assumptions=assumptions,
        conditions=conditions)
    kit.write_json(project / S4 / "structured-output.json",
                   market_structured())
    kit.write_json(project / S5 / "structured-output.json",
                   business_structured())
    kit.write_json(project / S6 / "structured-output.json",
                   gtm_structured())
    if operations is None:
        operations = canonical_operations_structured()
    if operations is not False:
        kit.write_json(project / S7 / "structured-output.json", operations)
    kit.write_json(project / "shared" / "risk-register.json", risk_register())
    for stage in (S7, S8):
        (project / stage).mkdir(exist_ok=True)
    return project


# ---------------------------------------------------------------------------
# Stage 8 canonico + Stage 9 (roadmap e milestone).
#
# Estensione ADDITIVA: nessuna firma esistente cambia e le fixture degli
# Stage 7-8 restano byte-identiche. Serve a T-MILESTONE-CHAIN
# e alla parte team di T-CROSS-EXT, che hanno bisogno di un progetto entrato
# allo Stage 9 con gli Stage 4-8 canonici (i ROLE- e i driver di team non sono
# più proposte) e di una roadmap che copra **tutte e quattro** le categorie di
# milestone: `milestone_category_not_assessed` è discriminante solo se il caso
# verde le valuta davvero tutte.
# ---------------------------------------------------------------------------
S9 = "09_roadmap-and-milestones"

COMPLETED_THROUGH_8 = COMPLETED_THROUGH_7 + [S8]

CHURN_ID = "ASS-024"

# Stage 9: i costi delle milestone sono driver proposti nel candidate.
MILESTONE_COST_IDS = ("P-ASS-301", "P-ASS-302", "P-ASS-303", "P-ASS-304")

# Stage 9 applicato: gli stessi driver con id canonici (prove in fase impact).
CANONICAL_MILESTONE_COST_IDS = {
    "P-ASS-301": "ASS-033",
    "P-ASS-302": "ASS-034",
    "P-ASS-303": "ASS-035",
    "P-ASS-304": "ASS-036",
}

MILESTONE_COST_VARIABLES = (
    "milestone_cost_mvp",
    "milestone_cost_partner_channel",
    "milestone_cost_delivery_scaleup",
    "milestone_cost_governance_setup",
)

MILESTONE_COST_VALUES = (80000.0, 40000.0, 25000.0, 15000.0)

# (num, category, owner_ref, start_date, target_date, depends_on, title,
#  success_criteria, go_no_go_rule, exit_criteria, risk_refs)
#
# MIL-003 parte esattamente il giorno in cui chiude la sua dipendenza
# (2026-12-15): il confine incluso della cronologia («date uguali -> PASS») è quindi
# esercitato dal caso verde, non solo da un caso dedicato.
MILESTONE_SPECS = (
    (1, "technical", "ROLE-001", "2026-09-01", "2026-12-15", [],
     "MVP in produzione sul primo cliente pilota",
     ["10 clienti pilota attivi per 30 giorni consecutivi"],
     "Go se la retention pilota >= 70%",
     "MVP stabile per 30 giorni consecutivi",
     ["RISK-001"]),
    (2, "commercial", "ROLE-002", "2027-01-07", "2027-06-30", ["MIL-001"],
     "Canale partner a regime",
     ["CAC <= 250 EUR per due mesi consecutivi"],
     "Go se il CAC resta entro il target del funnel",
     "Canale replicabile e documentato",
     []),
    (3, "operational", "ROLE-001", "2026-12-15", "2027-03-31", ["MIL-001"],
     "Provisioning industrializzato alla capacità dichiarata",
     ["Lead time di attivazione < 48h sul 90% dei casi"],
     "Go se la capacità misurata >= capacità dichiarata",
     "Runbook operativo approvato e collaudato",
     ["RISK-001"]),
    (4, "organizational", "ROLE-002", "2026-09-01", "2026-11-30", [],
     "Governance e deleghe formalizzate",
     ["Patto parasociale firmato e deleghe deliberate"],
     "Go se le deleghe coprono ogni area di decision right",
     "Verbale con le deleghe operative in vigore",
     []),
)


def milestone_proposed(values=None):
    """Driver di costo delle milestone proposti nel candidate (P-ASS-301..304)."""
    values = list(values or MILESTONE_COST_VALUES)
    return [entry(ref, MILESTONE_COST_VARIABLES[i], values[i], "EUR",
                  category="roadmap",
                  evidence_classification="model_estimate")
            for i, ref in enumerate(MILESTONE_COST_IDS)]


def milestone_list(cost_refs=None):
    """Le quattro milestone del caso verde, una per categoria."""
    refs = list(cost_refs or MILESTONE_COST_IDS)
    out = []
    for index, spec in enumerate(MILESTONE_SPECS):
        (num, category, owner, start, target, depends_on, title,
         criteria, go_no_go, exit_criteria, risk_refs) = spec
        out.append({
            "id": f"MIL-{num:03d}",
            "title": title,
            "category": category,
            "owner_ref": owner,
            "depends_on": list(depends_on),
            "start_date": start,
            "target_date": target,
            "cost_ref": refs[index],
            "success_criteria": list(criteria),
            "go_no_go_rule": go_no_go,
            "exit_criteria": exit_criteria,
            "risk_refs": list(risk_refs),
        })
    return out


def financial_plan_inputs(cost_refs=None, **over):
    """Contratto financial_plan_inputs verso lo Stage 10: sole referenze,
    nessun calcolo."""
    out = {
        "pricing_ref": PRICING_ID,
        "cogs_refs": [COGS_ID],
        "funnel_customers_ref": CUSTOMERS_OUT_ID,
        "churn_ref": CHURN_ID,
        "ops_capacity_ref": OPS_CAPACITY_CANONICAL_ID,
        "headcount_driver_refs": [CANONICAL_TEAM_IDS[FTE_LEAD_ID],
                                  CANONICAL_TEAM_IDS[FTE_OPEN_ID]],
        "milestone_cost_refs": list(cost_refs or MILESTONE_COST_IDS),
        "som_ref": SOM_ID,
    }
    out.update(copy.deepcopy(over))
    return out


def milestone_structured(milestones=None, inputs=None, cost_refs=None):
    """Structured output dello Stage 9 conforme a milestone-plan.schema.json."""
    return {"milestone_plan": {
        "milestones": milestone_list(cost_refs) if milestones is None
        else milestones,
        "financial_plan_inputs": financial_plan_inputs(cost_refs)
        if inputs is None else inputs,
    }}


def milestone_assumptions(values=None):
    """Catena canonica dello Stage 9 (roadmap applicata): gli stessi driver di
    `milestone_proposed()` con id `ASS-`, per le prove in fase impact."""
    out = []
    for item in copy.deepcopy(milestone_proposed(values)):
        item["id"] = CANONICAL_MILESTONE_COST_IDS[item["id"]]
        out.append(item)
    return out


def canonical_milestone_structured(**kwargs):
    """Structured output dello Stage 9 con i driver di costo canonici."""
    kwargs.setdefault("cost_refs",
                      [CANONICAL_MILESTONE_COST_IDS[ref]
                       for ref in MILESTONE_COST_IDS])
    return milestone_structured(**kwargs)


def make_stage9_project(tmp, name, assumptions_extra=None, operations=None,
                        team=None, conditions=None):
    """Progetto canonico entrato allo Stage 9: Stage 4-8 applicati e completati.

    Gli Stage 4-8 sono canonici (structured-output + registro ASS-); lo
    Stage 9 vive nel candidate (milestone_plan + P-ASS- di costo). `operations`
    e `team` accettano `False` per costruire il caso in cui l'upstream
    canonico manca."""
    assumptions = (market_assumptions() + business_assumptions()
                   + gtm_assumptions() + ops_assumptions()
                   + team_assumptions())
    if assumptions_extra:
        assumptions = assumptions + assumptions_extra
    project = kit.make_project(
        tmp, name=name, current_stage=S9, status="in_progress",
        completed=COMPLETED_THROUGH_8, assumptions=assumptions,
        conditions=conditions)
    kit.write_json(project / S4 / "structured-output.json",
                   market_structured())
    kit.write_json(project / S5 / "structured-output.json",
                   business_structured())
    kit.write_json(project / S6 / "structured-output.json",
                   gtm_structured())
    if operations is None:
        operations = canonical_operations_structured()
    if operations is not False:
        kit.write_json(project / S7 / "structured-output.json", operations)
    if team is None:
        team = canonical_team_structured()
    if team is not False:
        kit.write_json(project / S8 / "structured-output.json", team)
    kit.write_json(project / "shared" / "risk-register.json", risk_register())
    for stage in (S7, S8, S9):
        (project / stage).mkdir(exist_ok=True)
    return project
