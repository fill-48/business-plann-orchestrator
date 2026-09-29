#!/usr/bin/env python3
"""T-STAGE-WORKFLOWS — contratto strutturale dei workflow degli Stage 1-9.

I workflow di stage devono: invocare i validator di base (stage gate +
referential integrity) e quelli di dominio nelle fasi giuste, passare dal
transaction manager (mai scrittura canonica manuale), confinare i subagent
nel candidate workspace (.working/<tx>/), usare P-ASS-* per le proposte e
rispettare la numerazione dei file (Stage 1 -> 02_problem-and-need.md, ...).
I runtime-agent devono rispettare il contratto di
`reference/architecture.md` §11.2 (12 chiavi). SKILL.md deve esporre il
mapping Stage <-> folder <-> workflow e i file del contratto devono esistere.
"""
import argparse
import json
import re
import sys
from pathlib import Path


class TestFailure(AssertionError):
    pass


SKILL_REL = ".claude/skills/business-plan-orchestrator"

AGENT_CONTRACT_KEYS = (
    "role", "objective", "scope", "required_inputs", "optional_inputs",
    "methodology_files", "allowed_tools", "forbidden_actions",
    "expected_output", "output_schema", "quality_checks",
    "escalation_conditions")

COMMON_WORKFLOW_MARKERS = (
    "validate_stage_gate", "validate_referential_integrity",
    "--phase ingress", "--phase candidate", "--phase egress",
    "transaction_manager.py", "advance-stage",
    ".working/", "proposed-assumptions.json", "P-ASS-",
    "structured-output.json", "section-draft.md", "handoff.md",
)

WORKFLOWS = {
    "02_problem-and-need.md": {
        "stage": "01_problem-and-need",
        "agent": "customer-problem-analyst",
        "methodology": "methodology/problem-and-need.md",
        "extra": ("percepito", "dimostrato"),
    },
    "03_customer-segmentation.md": {
        "stage": "02_customer-segmentation",
        "agent": "customer-problem-analyst",
        "methodology": "methodology/customer-segmentation.md",
        "extra": ("SEG-", "beachhead", "buyer"),
    },
    "04_value-proposition.md": {
        "stage": "03_value-proposition",
        "agent": "value-proposition-strategist",
        "methodology": "methodology/value-proposition.md",
        "extra": ("VP-", "proof_points", "proposed-conditions.json",
                  "approved_with_conditions", "evidence_unvalidated",
                  "evidence_checkpoint"),
    },
    "05_market-and-competition.md": {
        "stage": "04_market-and-competition",
        "agent": "market-competition-analyst",
        "methodology": "methodology/market-sizing-and-competition.md",
        "extra": ("validate_market_arithmetic", "market_model",
                  "tam_ref", "sam_ref", "som_ref", "bottom_up",
                  "competitive_landscape", "none_identified",
                  "reconciliation", "CMP-"),
    },
    "06_business-model.md": {
        "stage": "05_business-model",
        "agent": "business-model-analyst",
        "methodology": "methodology/business-model.md",
        "extra": ("validate_unit_economics",
                  "validate_cross_stage_consistency", "business_model",
                  "pricing_ref", "revenue_ref", "contribution_margin_ref",
                  "price_conflict", "negative_margin"),
    },
    "07_go-to-market.md": {
        "stage": "06_go-to-market",
        "agent": "go-to-market-analyst",
        "methodology": "methodology/go-to-market.md",
        "extra": ("validate_funnel_arithmetic",
                  "validate_cross_stage_consistency", "sales_funnel",
                  "customers_out_ref", "cac_ref", "churn_ref",
                  "capacity_revenue_ref", "gtm_capacity_below_som",
                  "price_divergence",
                  # il passo *history* del ciclo di conflitto passa dal
                  # comando transazionale, non da una scrittura mediata
                  # dall'orchestratore
                  "show-assumption", "update-assumption", "--changes",
                  "expected_record_hash", "operation_id"),
    },
}

# Il passo *history* non deve descrivere un update mediato
# dall'orchestratore: l'aggiornamento con history passa da
# `update-assumption`. La stringa vietata è verificata sul solo workflow 07.
FORBIDDEN_IN_07 = ("update mediato\n   dall'orchestratore",
                   "update mediato dall'orchestratore")

AGENTS = {
    "customer-problem-analyst.md": (
        "01_problem-and-need", "02_customer-segmentation", ".working/",
        "P-ASS-", "SEG-"),
    "value-proposition-strategist.md": (
        "03_value-proposition", ".working/", "P-ASS-", "proof_points",
        "founder_assumption"),
    "market-competition-analyst.md": (
        "04_market-and-competition", ".working/", "P-ASS-", "CMP-",
        "bottom_up", "none_identified"),
    "business-model-analyst.md": (
        "05_business-model", ".working/", "P-ASS-", "pricing",
        "contribution margin", "derivation"),
    "go-to-market-analyst.md": (
        "06_go-to-market", ".working/", "P-ASS-", "funnel", "churn",
        "CAC"),
}

METHODOLOGY = {
    "problem-and-need.md": ("percepito", "dimostrato", "workaround"),
    "customer-segmentation.md": ("user", "buyer", "decision maker",
                                 "beachhead"),
    "value-proposition.md": ("jobs", "pains", "gains", "proof point",
                             "founder_assumption"),
    "market-sizing-and-competition.md": (
        "TAM", "SAM", "SOM", "bottom-up", "weighted_average",
        "selected_ref", "none_identified", "PESTEL", "Porter"),
    "business-model.md": ("prezzo", "contribution margin",
                          "unit economics", "ricavo", "driver",
                          "ricorrenza"),
    "go-to-market.md": ("funnel", "cac", "churn", "canali",
                        "capacità", "som"),
}

# --------------------------------------------------------------------------
# Stage 7 (operations & IP): stesso contratto strutturale degli Stage 1-6.
# --------------------------------------------------------------------------
WORKFLOWS_03 = {
    "08_operations-and-ip.md": {
        "stage": "07_operations-and-ip",
        "agent": "operations-ip-analyst",
        "methodology": "methodology/operations-and-ip.md",
        "extra": ("validate_operations_feasibility",
                  "validate_cross_stage_consistency", "operations_model",
                  "core_processes", "make_buy_partner", "capacity_ref",
                  "unit_ops_cost_refs", "critical_dependencies",
                  "regulatory_requirements", "ip_strategy",
                  "ops_capacity_below_gtm",
                  # il ciclo di capacità operativa e le condizioni passano
                  # dai comandi TM
                  "update-assumption", "resolve-condition"),
    },
}

AGENTS_03 = {
    "operations-ip-analyst.md": (
        "07_operations-and-ip", ".working/", "P-ASS-", "operations_model",
        "capacity", "make_buy_partner", "ip_strategy"),
}

METHODOLOGY_03 = {
    "operations-and-ip.md": ("operating model", "make", "buy", "partner",
                             "capacità", "dipendenze", "ip", "regolator",
                             "processi core"),
}

# Il contratto di `operations-ip-analyst` non deve suggerire che capacità e
# costi operativi producano indistintamente nuovi P-ASS-: i costi già
# coperti dai COGS dello Stage 5 si REFERENZIANO (ops_cost_divergence). La
# chiarificazione è documentale, non un cambio di comportamento.
AGENT_03_REQUIRED_CLARIFICATIONS = {
    "operations-ip-analyst.md": (
        "non già coperti dagli ASS- COGS dello Stage 5",),
}

# --------------------------------------------------------------------------
# Stage 8 (team & governance): stessa forma dello Stage 7.
# --------------------------------------------------------------------------
WORKFLOWS_04 = {
    "09_team-and-governance.md": {
        "stage": "08_team-and-governance",
        "agent": "team-governance-analyst",
        "methodology": "methodology/team-and-governance.md",
        "extra": ("validate_team_and_governance",
                  "validate_cross_stage_consistency", "team_governance",
                  "roles", "covers_processes", "capability_gaps",
                  "hiring_plan", "decision_rights", "equity_split",
                  "ROLE-", "core_process_unowned",
                  "capability_gap_unaddressed", "decision_right_ambiguous",
                  "equity_sum_exceeds_one", "open_position_unbudgeted",
                  "approved_with_conditions",
                  # gap e condizioni passano dai comandi TM, mai a mano
                  "update-assumption", "resolve-condition"),
    },
}

AGENTS_04 = {
    "team-governance-analyst.md": (
        "08_team-and-governance", ".working/", "P-ASS-", "team_governance",
        "ROLE-", "capability gap", "decision rights", "governance",
        "equity"),
}

METHODOLOGY_04 = {
    "team-and-governance.md": ("ruoli", "responsabilità", "decision rights",
                               "capability gap", "hiring", "governance",
                               "equity", "incentivi", "advisor",
                               "processi core"),
}

# --------------------------------------------------------------------------
# Stage 9 (roadmap e milestone): stessa forma degli Stage 7-8; il workflow
# consegna allo Stage 10 il contratto financial_plan_inputs (vedi
# STAGE9_HANDOFF_MARKERS).
# --------------------------------------------------------------------------
WORKFLOWS_05 = {
    "10_roadmap-and-milestones.md": {
        "stage": "09_roadmap-and-milestones",
        "agent": "milestone-planner",
        "methodology": "methodology/roadmap-and-milestones.md",
        "extra": ("validate_milestone_chain",
                  "validate_cross_stage_consistency", "milestone_plan",
                  "milestones", "MIL-", "owner_ref", "depends_on",
                  "start_date", "target_date", "cost_ref",
                  "success_criteria", "go_no_go_rule", "exit_criteria",
                  "financial_plan_inputs", "milestone_cycle_detected",
                  "milestone_dependency_unresolved",
                  "milestone_date_incoherent", "milestone_owner_unresolved",
                  "milestone_cost_unresolved", "milestone_criteria_missing",
                  "milestone_category_not_assessed",
                  "financial_input_unresolved",
                  "headcount_capacity_incoherent",
                  # il ciclo di capacità operativa e le condizioni passano
                  # dai comandi TM
                  "update-assumption", "resolve-condition"),
    },
}

AGENTS_05 = {
    "milestone-planner.md": (
        "09_roadmap-and-milestones", ".working/", "P-ASS-", "milestone_plan",
        "MIL-", "ROLE-", "go_no_go_rule", "financial_plan_inputs",
        "critical path"),
}

METHODOLOGY_05 = {
    "roadmap-and-milestones.md": ("milestone", "dag", "dipendenze",
                                  "critical path", "owner", "go/no-go",
                                  "exit criteria", "categorie",
                                  "financial_plan_inputs", "anti-pattern"),
}

# Il workflow di Stage 9 consegna allo Stage 10 il contratto di sole
# referenze `financial_plan_inputs` e rimanda al workflow del piano
# finanziario: lo Stage 9 non e' piu' uno stage terminale.
STAGE9_HANDOFF_MARKERS = ("financial_plan_inputs", "Stage 10",
                          "11_financial-plan.md")

# Nessuna CARTELLA di stage 10-12 (`10_financial-plan`, ...) deve esistere
# nelle basi del pacchetto o nell'esempio: gli artefatti di quegli stage sono
# file con numerazione propria (es. `workflows/11_financial-plan.md`), mai
# cartelle segnaposto.
FORBIDDEN_STAGE_DIRS = ("10_financial-plan", "11_funding-request",
                        "12_data-room")

# Mappa TOKEN -> STAGE NOMINATO. L'ammissibilità di un token nei nomi dei
# file è funzione dell'ordinale dello stage che nomina, non del suo nome.
TOKEN_STAGES = (
    ("financial-plan", "10_financial-plan"),
    ("funding-request", "11_funding-request"),
    ("data-room", "12_data-room"),
    ("document-generation", "13_document-generation"),
)

# Token esclusi a prescindere dal confine. L'elenco è VUOTO: anche
# `document-generation` nomina uno stage implementato (lo Stage 13, ultimo di
# `stage_order`) ed è ammesso dal solo invariante parametrico al confine
# reale 13. L'elenco resta dichiarato per essere misurabile.
STAGE13_ABSOLUTE_TOKENS = ()


def read(root, rel):
    path = root / rel
    if not path.is_file():
        raise TestFailure(f"file richiesto assente: {rel}")
    text = path.read_text(encoding="utf-8")
    if len(text.strip()) < 400:
        raise TestFailure(f"{rel}: contenuto insufficiente per un contratto "
                          f"operativo ({len(text.strip())} caratteri)")
    return text


def must_contain(rel, text, markers, label):
    missing = [m for m in markers if m not in text]
    if missing:
        raise TestFailure(f"{rel}: {label} — marker assenti: {missing}")


def run(root):
    # ------------------------------------------------------------ workflows
    for name, spec in WORKFLOWS.items():
        rel = f"{SKILL_REL}/workflows/{name}"
        text = read(root, rel)
        must_contain(rel, text, COMMON_WORKFLOW_MARKERS,
                     "contratto comune dei workflow di stage")
        must_contain(rel, text, (spec["stage"], spec["agent"],
                                 spec["methodology"]),
                     "binding stage/agent/metodologia")
        must_contain(rel, text, spec["extra"], "contratto specifico di stage")
        # il candidate workspace è quello dello stage giusto
        if f"{spec['stage']}/.working/" not in text:
            raise TestFailure(
                f"{rel}: candidate workspace non stage-bounded "
                f"({spec['stage']}/.working/ assente)")
        if name == "07_go-to-market.md":
            for forbidden in FORBIDDEN_IN_07:
                if forbidden in text:
                    raise TestFailure(
                        f"{rel}: il passo *history* del ciclo di conflitto "
                        "descrive ancora un update mediato dall'orchestratore "
                        "(deve passare da update-assumption)")

    # ------------------------------------------------------- runtime agents
    for name, markers in AGENTS.items():
        rel = f"{SKILL_REL}/runtime-agents/{name}"
        text = read(root, rel)
        for key in AGENT_CONTRACT_KEYS:
            if not re.search(rf"^{key}:", text, re.MULTILINE):
                raise TestFailure(
                    f"{rel}: chiave di contratto §11.2 assente: {key}")
        must_contain(rel, text, markers, "confini e namespace dell'agent")
        must_contain(rel, text, ("shared/",),
                     "divieto esplicito sui registri condivisi")

    # --------------------------------------------------------- methodology
    for name, markers in METHODOLOGY.items():
        rel = f"{SKILL_REL}/methodology/{name}"
        text = read(root, rel)
        must_contain(rel, text.lower(),
                     tuple(m.lower() for m in markers),
                     "contenuto metodologico minimo")

    # ------------------------------------------------------------- SKILL.md
    skill = read(root, f"{SKILL_REL}/SKILL.md")
    for name, spec in WORKFLOWS.items():
        if name not in skill:
            raise TestFailure(f"SKILL.md: workflow {name} non instradato")
        if spec["stage"] not in skill:
            raise TestFailure(f"SKILL.md: stage {spec['stage']} non mappato")
    for agent in ("customer-problem-analyst", "value-proposition-strategist",
                  "market-competition-analyst", "business-model-analyst",
                  "go-to-market-analyst"):
        if agent not in skill:
            raise TestFailure(f"SKILL.md: runtime-agent {agent} non citato")

    # ------------------------------------------------------ file obbligatori
    expected = set()
    for name in WORKFLOWS:
        expected.add(f"{SKILL_REL}/workflows/{name}")
    for name in AGENTS:
        expected.add(f"{SKILL_REL}/runtime-agents/{name}")
    for name in METHODOLOGY:
        expected.add(f"{SKILL_REL}/methodology/{name}")
    expected.add("tests/integration/test_evidence_checkpoint.py")
    expected.add("tests/integration/test_stage_workflows.py")
    missing = sorted(p for p in expected if not (root / p).is_file())
    if missing:
        raise TestFailure(
            f"file obbligatori assenti (Stage 1-6): {missing}")

    run_release_03(root, skill)


def run_release_03(root, skill):
    """Stage 7: stesso contratto strutturale degli stage 1-6, con il confine
    esplicito verso lo Stage 8 (i ROLE- non esistono ancora)."""
    # ------------------------------------------------------------ workflows
    for name, spec in WORKFLOWS_03.items():
        rel = f"{SKILL_REL}/workflows/{name}"
        text = read(root, rel)
        must_contain(rel, text, COMMON_WORKFLOW_MARKERS,
                     "contratto comune dei workflow di stage")
        must_contain(rel, text, (spec["stage"], spec["agent"],
                                 spec["methodology"]),
                     "binding stage/agent/metodologia")
        must_contain(rel, text, spec["extra"], "contratto specifico di stage")
        if f"{spec['stage']}/.working/" not in text:
            raise TestFailure(
                f"{rel}: candidate workspace non stage-bounded "
                f"({spec['stage']}/.working/ assente)")
        # Nessuna anticipazione dello Stage 8: il workflow dichiara
        # esplicitamente il confine (i ROLE- non esistono ancora).
        must_contain(rel, text, ("anticipazione dello Stage 8",),
                     "confine esplicito verso lo Stage 8 (nessuna "
                     "anticipazione)")

    # ------------------------------------------------------- runtime agents
    for name, markers in AGENTS_03.items():
        rel = f"{SKILL_REL}/runtime-agents/{name}"
        text = read(root, rel)
        for key in AGENT_CONTRACT_KEYS:
            if not re.search(rf"^{key}:", text, re.MULTILINE):
                raise TestFailure(
                    f"{rel}: chiave di contratto §11.2 assente: {key}")
        must_contain(rel, text, markers, "confini e namespace dell'agent")
        must_contain(rel, text, ("shared/",),
                     "divieto esplicito sui registri condivisi")
        must_contain(rel, text,
                     AGENT_03_REQUIRED_CLARIFICATIONS.get(name, ()),
                     "contratto P-ASS- disambiguato (capacità vs costi già "
                     "coperti dallo Stage 5)")

    # --------------------------------------------------------- methodology
    for name, markers in METHODOLOGY_03.items():
        rel = f"{SKILL_REL}/methodology/{name}"
        text = read(root, rel)
        must_contain(rel, text.lower(),
                     tuple(m.lower() for m in markers),
                     "contenuto metodologico minimo")

    # ------------------------------------------------------------- SKILL.md
    for name, spec in WORKFLOWS_03.items():
        if name not in skill:
            raise TestFailure(f"SKILL.md: workflow {name} non instradato")
        if spec["stage"] not in skill:
            raise TestFailure(f"SKILL.md: stage {spec['stage']} non mappato")
        if spec["agent"] not in skill:
            raise TestFailure(
                f"SKILL.md: runtime-agent {spec['agent']} non citato")

    # ------------------------------------------------------ file obbligatori
    expected = set()
    for name in WORKFLOWS_03:
        expected.add(f"{SKILL_REL}/workflows/{name}")
    for name in AGENTS_03:
        expected.add(f"{SKILL_REL}/runtime-agents/{name}")
    for name in METHODOLOGY_03:
        expected.add(f"{SKILL_REL}/methodology/{name}")
    expected.add(f"{SKILL_REL}/validators/validate_operations_feasibility.py")
    missing = sorted(p for p in expected if not (root / p).is_file())
    if missing:
        raise TestFailure(
            f"file obbligatori assenti (Stage 7): {missing}")

    run_release_04(root, skill)


def run_release_04(root, skill):
    """Stage 8: stesso contratto strutturale dello Stage 7,
    con il confine esplicito verso lo Stage 9 (i MIL- non esistono ancora)."""
    # ------------------------------------------------------------ workflows
    for name, spec in WORKFLOWS_04.items():
        rel = f"{SKILL_REL}/workflows/{name}"
        text = read(root, rel)
        must_contain(rel, text, COMMON_WORKFLOW_MARKERS,
                     "contratto comune dei workflow di stage")
        must_contain(rel, text, (spec["stage"], spec["agent"],
                                 spec["methodology"]),
                     "binding stage/agent/metodologia")
        must_contain(rel, text, spec["extra"], "contratto specifico di stage")
        if f"{spec['stage']}/.working/" not in text:
            raise TestFailure(
                f"{rel}: candidate workspace non stage-bounded "
                f"({spec['stage']}/.working/ assente)")
        # Nessuna anticipazione dello Stage 9: le milestone (MIL-) non
        # esistono ancora e il workflow deve dichiararlo.
        must_contain(rel, text, ("anticipazione dello Stage 9",),
                     "confine esplicito verso lo Stage 9 (nessuna "
                     "anticipazione)")

    # ------------------------------------------------------- runtime agents
    for name, markers in AGENTS_04.items():
        rel = f"{SKILL_REL}/runtime-agents/{name}"
        text = read(root, rel)
        for key in AGENT_CONTRACT_KEYS:
            if not re.search(rf"^{key}:", text, re.MULTILINE):
                raise TestFailure(
                    f"{rel}: chiave di contratto §11.2 assente: {key}")
        must_contain(rel, text, markers, "confini e namespace dell'agent")
        must_contain(rel, text, ("shared/",),
                     "divieto esplicito sui registri condivisi")

    # --------------------------------------------------------- methodology
    for name, markers in METHODOLOGY_04.items():
        rel = f"{SKILL_REL}/methodology/{name}"
        text = read(root, rel)
        must_contain(rel, text.lower(),
                     tuple(m.lower() for m in markers),
                     "contenuto metodologico minimo")

    # ------------------------------------------------------------- SKILL.md
    for name, spec in WORKFLOWS_04.items():
        if name not in skill:
            raise TestFailure(f"SKILL.md: workflow {name} non instradato")
        if spec["stage"] not in skill:
            raise TestFailure(f"SKILL.md: stage {spec['stage']} non mappato")
        if spec["agent"] not in skill:
            raise TestFailure(
                f"SKILL.md: runtime-agent {spec['agent']} non citato")

    # ------------------------------------------------------ file obbligatori
    expected = set()
    for name in WORKFLOWS_04:
        expected.add(f"{SKILL_REL}/workflows/{name}")
    for name in AGENTS_04:
        expected.add(f"{SKILL_REL}/runtime-agents/{name}")
    for name in METHODOLOGY_04:
        expected.add(f"{SKILL_REL}/methodology/{name}")
    expected.add(f"{SKILL_REL}/validators/validate_team_and_governance.py")
    missing = sorted(p for p in expected if not (root / p).is_file())
    if missing:
        raise TestFailure(
            f"file obbligatori assenti (Stage 8): {missing}")

    run_release_05(root, skill)


def run_release_05(root, skill):
    """Stage 9: stesso contratto strutturale degli Stage 7-8, con il
    passaggio esplicito allo Stage 10 tramite il contratto
    financial_plan_inputs; il milestone-planner non produce mai artefatti
    dello Stage 10."""
    # ------------------------------------------------------------ workflows
    for name, spec in WORKFLOWS_05.items():
        rel = f"{SKILL_REL}/workflows/{name}"
        text = read(root, rel)
        must_contain(rel, text, COMMON_WORKFLOW_MARKERS,
                     "contratto comune dei workflow di stage")
        must_contain(rel, text, (spec["stage"], spec["agent"],
                                 spec["methodology"]),
                     "binding stage/agent/metodologia")
        must_contain(rel, text, spec["extra"], "contratto specifico di stage")
        if f"{spec['stage']}/.working/" not in text:
            raise TestFailure(
                f"{rel}: candidate workspace non stage-bounded "
                f"({spec['stage']}/.working/ assente)")
        must_contain(rel, text, STAGE9_HANDOFF_MARKERS,
                     "passaggio esplicito allo Stage 10")

    # ------------------------------------------------------- runtime agents
    for name, markers in AGENTS_05.items():
        rel = f"{SKILL_REL}/runtime-agents/{name}"
        text = read(root, rel)
        for key in AGENT_CONTRACT_KEYS:
            if not re.search(rf"^{key}:", text, re.MULTILINE):
                raise TestFailure(
                    f"{rel}: chiave di contratto §11.2 assente: {key}")
        must_contain(rel, text, markers, "confini e namespace dell'agent")
        must_contain(rel, text, ("shared/",),
                     "divieto esplicito sui registri condivisi")
        # L'agent non deve mai produrre lo Stage 10: il contratto
        # financial_plan_inputs è di sole referenze e il piano finanziario è
        # prodotto dal proprio stage.
        must_contain(rel, text, ("10_financial-plan",),
                     "divieto esplicito di produrre artefatti Stage 10")

    # --------------------------------------------------------- methodology
    for name, markers in METHODOLOGY_05.items():
        rel = f"{SKILL_REL}/methodology/{name}"
        text = read(root, rel)
        must_contain(rel, text.lower(),
                     tuple(m.lower() for m in markers),
                     "contenuto metodologico minimo")

    # ------------------------------------------------------------- SKILL.md
    for name, spec in WORKFLOWS_05.items():
        if name not in skill:
            raise TestFailure(f"SKILL.md: workflow {name} non instradato")
        if spec["stage"] not in skill:
            raise TestFailure(f"SKILL.md: stage {spec['stage']} non mappato")
        if spec["agent"] not in skill:
            raise TestFailure(
                f"SKILL.md: runtime-agent {spec['agent']} non citato")

    # ------------------------------- nessuna cartella di stage segnaposto
    # Nessuna cartella `10_financial-plan`/`11_funding-request`/
    # `12_data-room` nelle basi del pacchetto o nell'esempio.
    for stage_dir in FORBIDDEN_STAGE_DIRS:
        for base in (f"{SKILL_REL}/workflows", f"{SKILL_REL}/methodology",
                     f"{SKILL_REL}/runtime-agents", f"{SKILL_REL}/schemas",
                     f"{SKILL_REL}/validators", "examples/fictional-startup"):
            if (root / base / stage_dir).exists():
                raise TestFailure(
                    f"{base}/{stage_dir} esiste: nessuna cartella di stage "
                    "segnaposto è ammessa nel pacchetto o nell'esempio")
    # Token nei nomi dei file — regola BOUNDARY-AWARE e PARAMETRICA.
    #
    # INVARIANTE. Un token è ammesso SE E SOLO SE lo stage che nomina è entro
    # il confine parametrico:
    #     stage_ordinal(<stage del token>) <= stage_ordinal(release_boundary) + 1
    # È la STESSA regola boundary-aware sotto cui vivono le voci validator di
    # enforcement-config.json. NON è un'eccezione nominale e NON è una lista
    # di permessi: una lista di permessi al posto dell'invariante renderebbe
    # la regola non più parametrica sul confine.
    #
    # Con la configurazione distribuita (confine 13, ultimo stage) tutti i
    # token sono ammessi, `document-generation` compreso (13 <= 13 + 1); il
    # rifiuto ai confini forzati più bassi è misurato dalla sonda parametrica
    # di `FO-C-21` (a).
    # Il controllo delle CARTELLE di stage (FORBIDDEN_STAGE_DIRS) resta
    # distinto da questa regola.
    enforcement = json.loads(
        (root / SKILL_REL / "config/enforcement-config.json")
        .read_text(encoding="utf-8"))
    stage_order = enforcement["stage_order"]
    boundary_ordinal = stage_order[enforcement["release_boundary"]]
    for forbidden, stage in TOKEN_STAGES:
        within_boundary = stage_order[stage] <= boundary_ordinal + 1
        admitted = within_boundary and forbidden not in STAGE13_ABSOLUTE_TOKENS
        for base in (f"{SKILL_REL}/workflows", f"{SKILL_REL}/methodology",
                     f"{SKILL_REL}/runtime-agents"):
            matches = sorted(p.name for p in (root / base).glob(f"*{forbidden}*"))
            if matches and not admitted:
                raise TestFailure(
                    f"{base}: artefatti oltre il boundary: {matches} "
                    f"(token {forbidden!r}, release_boundary "
                    f"{enforcement['release_boundary']!r})")

    # ------------------------------------------------------ file obbligatori
    expected = set()
    for name in WORKFLOWS_05:
        expected.add(f"{SKILL_REL}/workflows/{name}")
    for name in AGENTS_05:
        expected.add(f"{SKILL_REL}/runtime-agents/{name}")
    for name in METHODOLOGY_05:
        expected.add(f"{SKILL_REL}/methodology/{name}")
    expected.add(f"{SKILL_REL}/validators/validate_milestone_chain.py")
    expected.add("tests/integration/test_milestone_chain.py")
    missing = sorted(p for p in expected if not (root / p).is_file())
    if missing:
        raise TestFailure(
            f"file obbligatori assenti (Stage 9): {missing}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-STAGE-WORKFLOWS Stage 1-9 workflow/agent/methodology "
          "contract + token boundary-aware")


if __name__ == "__main__":
    main()
