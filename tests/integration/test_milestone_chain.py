#!/usr/bin/env python3
"""T-MILESTONE-CHAIN — validate_milestone_chain (Stage 9: roadmap e milestone).

Stage 9, fasi egress/impact. Un caso RED per ogni error code del validator:
milestone_cycle_detected (auto-dipendenza e ciclo a due nodi),
milestone_dependency_unresolved, milestone_date_incoherent (target < start e
dipendenza cronologicamente incoerente), invalid (data non ISO-8601),
milestone_owner_unresolved, milestone_cost_unresolved,
milestone_criteria_missing, milestone_category_not_assessed (categoria
omessa e categoria fuori vocabolario), financial_input_unresolved (blocco
assente, chiave assente, ref irrisolvibile, classe dichiarata vuota,
interfaccia incompleta rispetto ai costi delle milestone) e
missing_required.

Più: i due warning (milestone_target_above_capacity, che è il segnale
non bloccante del ciclo di capacità operativa — il detect bloccante resta del cross-stage — e
long_gap_between_milestones), i casi VERDI che rendono discriminanti i
negativi (DAG disconnesso, forward reference intra-array, confine di data
incluso), three-state (progetto a stage 5 -> not_yet_required), fuori
matrice -> exit 2 e il binding col transaction manager.

La risoluzione dei namespace tipizzati (definizioni `MIL-` uniche, forward
reference, `owner_ref` verso `ROLE-` esistenti, `future_namespace_ref`) è di
validate_referential_integrity, coperta da T-REFINT-EXT: qui non si
duplica. Il validator di dominio verifica la semantica di Stage 9 — grafo,
cronologia, completezza della milestone e contratto financial_plan_inputs —
sul canonico
dello Stage 8, che refint non conosce.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit
import bpo_m5_fixtures as m5


class TestFailure(AssertionError):
    pass


NAME = "validate_milestone_chain"


def run_validator(root, project, candidate=None, stage=m5.S9, phase="egress"):
    return kit.run_validator_cli(root, NAME, project=project, stage=stage,
                                 phase=phase, candidate=candidate)


def expect_pass(root, project, candidate, label, stage=m5.S9, phase="egress"):
    before = kit.snapshot_tree(project)
    exit_code, out, err = run_validator(root, project, candidate, stage, phase)
    if exit_code != 0:
        raise TestFailure(f"{label}: expected exit 0, got {exit_code} "
                          f"(out {out.strip()!r} err {err.strip()!r})")
    report = kit.parse_report(out, label)
    if kit.snapshot_tree(project) != before:
        raise TestFailure(f"{label}: validator mutated the project")
    return report


def expect_fail(root, project, candidate, code, label, stage=m5.S9,
                phase="egress"):
    before = kit.snapshot_tree(project)
    exit_code, out, err = run_validator(root, project, candidate, stage, phase)
    if exit_code != 1:
        raise TestFailure(f"{label}: expected exit 1, got {exit_code} "
                          f"(out {out.strip()!r} err {err.strip()!r})")
    report = kit.parse_report(out, label)
    codes = [e["code"] for e in report["errors"]]
    if code not in codes:
        raise TestFailure(f"{label}: expected error code {code}, got {codes}")
    if kit.snapshot_tree(project) != before:
        raise TestFailure(f"{label}: validator mutated the project")
    return report


def candidate_with(project, structured, proposed=None, tx_id="tx-mil-001"):
    if proposed is None:
        proposed = m5.milestone_proposed()
    return kit.make_candidate(project, m5.S9, tx_id=tx_id,
                              structured=structured, proposed=proposed)


def refs_for(report, code):
    return [e["ref"] for e in report["errors"] if e["code"] == code]


def with_milestone(index, **changes):
    """Structured output di Stage 9 con una sola milestone modificata."""
    struct = m5.milestone_structured()
    milestone = struct["milestone_plan"]["milestones"][index]
    for key, value in changes.items():
        if value is KeyError:
            milestone.pop(key, None)
        else:
            milestone[key] = value
    return struct


def with_inputs(**changes):
    """Structured output di Stage 9 con financial_plan_inputs modificato."""
    struct = m5.milestone_structured()
    inputs = struct["milestone_plan"]["financial_plan_inputs"]
    for key, value in changes.items():
        if value is KeyError:
            inputs.pop(key, None)
        else:
            inputs[key] = value
    return struct


def two_node_cycle():
    """MIL-001 -> MIL-002 -> MIL-001: il grafo non è più un DAG."""
    struct = m5.milestone_structured()
    struct["milestone_plan"]["milestones"][0]["depends_on"] = ["MIL-002"]
    return struct


def disconnected_dag():
    """Due componenti indipendenti: legittimo, nessuna regola lo vieta."""
    struct = m5.milestone_structured()
    for milestone in struct["milestone_plan"]["milestones"]:
        milestone["depends_on"] = []
    return struct


def forward_reference():
    """MIL-002 è definita dopo MIL-001 ma MIL-004 (ultima) la referenzia
    all'indietro; MIL-003 referenzia in avanti MIL-002. Nessun ciclo."""
    struct = m5.milestone_structured()
    milestones = struct["milestone_plan"]["milestones"]
    # MIL-003 (indice 2) dipende da MIL-002, definita PRIMA nell'array ma con
    # target 2027-06-30: sposto le date perché la cronologia resti coerente.
    milestones[2]["depends_on"] = ["MIL-002"]
    milestones[2]["start_date"] = "2027-06-30"
    milestones[2]["target_date"] = "2027-09-30"
    # MIL-001 (indice 0) dipende da MIL-004, definita DOPO nell'array.
    milestones[0]["depends_on"] = ["MIL-004"]
    milestones[0]["start_date"] = "2026-11-30"
    milestones[0]["target_date"] = "2026-12-15"
    return struct


def run(root):
    if not (root / kit.VALIDATORS_REL / f"{NAME}.py").exists():
        raise TestFailure(f"missing validator: {NAME}.py")

    with tempfile.TemporaryDirectory(prefix="bpo-mil-") as tmp:
        tmp = Path(tmp)

        # 1. Happy path Stage 9: DAG aciclico, date coerenti (MIL-003 parte
        #    esattamente quando chiude MIL-001: confine incluso), owner e costi
        #    risolti, quattro categorie valutate, financial_plan_inputs completo ->
        #    PASS pulito, nessun warning.
        p = m5.make_stage9_project(tmp, "mil-happy")
        c = candidate_with(p, m5.milestone_structured())
        report = expect_pass(root, p, c, "milestone happy path")
        if report["errors"] or report["warnings"]:
            raise TestFailure(f"happy path must be clean: {report}")

        # ------------------------------------------------------------ DAG
        # 2a. Ciclo a due nodi MIL-001 <-> MIL-002 -> milestone_cycle_detected
        #     ancorato a ENTRAMBI i nodi del ciclo (ref stabili).
        p = m5.make_stage9_project(tmp, "mil-cycle2")
        report = expect_fail(root, p, candidate_with(p, two_node_cycle()),
                             "milestone_cycle_detected", "two-node cycle")
        cycled = refs_for(report, "milestone_cycle_detected")
        if cycled != ["MIL-001", "MIL-002"]:
            raise TestFailure(
                "cycle reporting must anchor every involved MIL- in document "
                f"order, got {cycled}")

        # 2b. Auto-dipendenza: un nodo che dipende da sé è un ciclo.
        p = m5.make_stage9_project(tmp, "mil-selfcycle")
        report = expect_fail(root, p,
                             candidate_with(p, with_milestone(
                                 0, depends_on=["MIL-001"])),
                             "milestone_cycle_detected", "self dependency")
        if refs_for(report, "milestone_cycle_detected") != ["MIL-001"]:
            raise TestFailure(
                "a self-cycle must report exactly the offending milestone, "
                f"got {refs_for(report, 'milestone_cycle_detected')}")

        # 2c. DAG disconnesso: componenti indipendenti -> PASS (non vietato).
        p = m5.make_stage9_project(tmp, "mil-disconnected")
        report = expect_pass(root, p, candidate_with(p, disconnected_dag()),
                             "disconnected but acyclic graph")
        if report["errors"]:
            raise TestFailure(f"a disconnected DAG must pass: {report}")

        # 2d. Forward reference dentro lo stesso array: la risoluzione avviene
        #     dopo la raccolta completa, quindi è legittima.
        p = m5.make_stage9_project(tmp, "mil-forward")
        expect_pass(root, p, candidate_with(p, forward_reference()),
                    "forward reference inside the milestone array")

        # 2e. Dipendenza verso una MIL- inesistente.
        p = m5.make_stage9_project(tmp, "mil-depghost")
        report = expect_fail(root, p,
                             candidate_with(p, with_milestone(
                                 1, depends_on=["MIL-999"])),
                             "milestone_dependency_unresolved",
                             "dependency towards a ghost milestone")
        if refs_for(report, "milestone_dependency_unresolved") != ["MIL-999"]:
            raise TestFailure("the unresolved dependency must be the ref, got "
                              f"{refs_for(report, 'milestone_dependency_unresolved')}")

        # ---------------------------------------------------------- date
        # 3a. target_date precedente a start_date.
        p = m5.make_stage9_project(tmp, "mil-date-inverted")
        expect_fail(root, p,
                    candidate_with(p, with_milestone(
                        0, start_date="2026-12-15",
                        target_date="2026-09-01")),
                    "milestone_date_incoherent", "target before start")

        # 3b. Cronologia delle dipendenze: MIL-002 parte prima che MIL-001
        #     chiuda.
        p = m5.make_stage9_project(tmp, "mil-date-chain")
        report = expect_fail(root, p,
                             candidate_with(p, with_milestone(
                                 1, start_date="2026-10-01")),
                             "milestone_date_incoherent",
                             "milestone starting before its prerequisite ends")
        if "MIL-002" not in refs_for(report, "milestone_date_incoherent"):
            raise TestFailure(
                "the dependent milestone must be the reported ref: "
                f"{refs_for(report, 'milestone_date_incoherent')}")

        # 3c. Data non ISO-8601 -> invalid (casi limite).
        for index, (label, value) in enumerate((
                ("european format", "15/12/2026"),
                ("timestamp", "2026-12-15T00:00:00"),
                ("out of range", "2026-13-45"))):
            p = m5.make_stage9_project(tmp, f"mil-date-bad-{index}")
            expect_fail(root, p,
                        candidate_with(p, with_milestone(
                            0, target_date=value)),
                        "invalid", f"non ISO-8601 date ({label})")

        # --------------------------------------------------------- owner
        # 4a. Owner verso un ROLE- che non esiste nello Stage 8 canonico.
        p = m5.make_stage9_project(tmp, "mil-owner-ghost")
        report = expect_fail(root, p,
                             candidate_with(p, with_milestone(
                                 0, owner_ref="ROLE-999")),
                             "milestone_owner_unresolved", "ghost owner")
        if refs_for(report, "milestone_owner_unresolved") != ["ROLE-999"]:
            raise TestFailure("the ghost role must be the reported ref, got "
                              f"{refs_for(report, 'milestone_owner_unresolved')}")

        # 4b. Owner assente: una milestone senza responsabile non è eseguibile.
        p = m5.make_stage9_project(tmp, "mil-owner-missing")
        expect_fail(root, p,
                    candidate_with(p, with_milestone(0, owner_ref=KeyError)),
                    "milestone_owner_unresolved", "milestone without owner")

        # 4c. Owner scritto come nome di persona invece che come ROLE-.
        p = m5.make_stage9_project(tmp, "mil-owner-prose")
        expect_fail(root, p,
                    candidate_with(p, with_milestone(
                        0, owner_ref="Giulia Rossi")),
                    "milestone_owner_unresolved", "owner written as prose")

        # ---------------------------------------------------------- costo
        # 5a. Costo scritto come letterale invece che come driver ASS-.
        p = m5.make_stage9_project(tmp, "mil-cost-literal")
        expect_fail(root, p,
                    candidate_with(p, with_milestone(0, cost_ref=80000)),
                    "milestone_cost_unresolved", "cost as a literal amount")

        # 5b. Costo verso un driver inesistente.
        p = m5.make_stage9_project(tmp, "mil-cost-ghost")
        expect_fail(root, p,
                    candidate_with(p, with_milestone(
                        0, cost_ref="P-ASS-999")),
                    "milestone_cost_unresolved", "unresolved cost driver")

        # -------------------------------------------------------- criteri
        # 6a. success_criteria vuoti.
        p = m5.make_stage9_project(tmp, "mil-crit-empty")
        expect_fail(root, p,
                    candidate_with(p, with_milestone(0, success_criteria=[])),
                    "milestone_criteria_missing", "empty success criteria")

        # 6b. success_criteria presenti ma vuoti come stringa: un criterio in
        #     bianco non è misurabile.
        p = m5.make_stage9_project(tmp, "mil-crit-blank")
        expect_fail(root, p,
                    candidate_with(p, with_milestone(
                        0, success_criteria=["   "])),
                    "milestone_criteria_missing", "blank success criterion")

        # 6c. go_no_go_rule assente.
        p = m5.make_stage9_project(tmp, "mil-crit-gng")
        expect_fail(root, p,
                    candidate_with(p, with_milestone(
                        0, go_no_go_rule=KeyError)),
                    "milestone_criteria_missing", "missing go/no-go rule")

        # 6d. exit_criteria assente.
        p = m5.make_stage9_project(tmp, "mil-crit-exit")
        expect_fail(root, p,
                    candidate_with(p, with_milestone(
                        0, exit_criteria=KeyError)),
                    "milestone_criteria_missing", "missing exit criteria")

        # ------------------------------------------------------ categoria
        # 7a. Categoria omessa dalla roadmap: lo schema non prevede alcun
        #     none_identified per le categorie, quindi «valutata» significa
        #     almeno una milestone.
        p = m5.make_stage9_project(tmp, "mil-cat-missing")
        struct = m5.milestone_structured()
        del struct["milestone_plan"]["milestones"][3]  # organizational
        report = expect_fail(root, p, candidate_with(p, struct),
                             "milestone_category_not_assessed",
                             "organizational category left unassessed")
        refs = refs_for(report, "milestone_category_not_assessed")
        if not any("organizational" in str(ref) for ref in refs):
            raise TestFailure(
                f"the unassessed category must be named in the ref: {refs}")

        # 7b. Categoria fuori vocabolario canonico.
        p = m5.make_stage9_project(tmp, "mil-cat-unknown")
        expect_fail(root, p,
                    candidate_with(p, with_milestone(0, category="financial")),
                    "milestone_category_not_assessed",
                    "category outside the canonical vocabulary")

        # 7c. Categoria in bianco.
        p = m5.make_stage9_project(tmp, "mil-cat-blank")
        expect_fail(root, p,
                    candidate_with(p, with_milestone(0, category="  ")),
                    "milestone_category_not_assessed", "blank category")

        # ------------------------------- contratto financial_plan_inputs
        # 8a. financial_plan_inputs assente: lo Stage 10 non avrebbe alcun
        #     input risolvibile.
        p = m5.make_stage9_project(tmp, "mil-fpi-missing")
        struct = m5.milestone_structured()
        del struct["milestone_plan"]["financial_plan_inputs"]
        expect_fail(root, p, candidate_with(p, struct),
                    "financial_input_unresolved", "financial_plan_inputs absent")

        # 8b. Ogni chiave obbligatoria dell'interfaccia, una per una.
        for index, key in enumerate(("pricing_ref", "cogs_refs",
                                     "funnel_customers_ref", "churn_ref",
                                     "ops_capacity_ref",
                                     "headcount_driver_refs",
                                     "milestone_cost_refs", "som_ref")):
            p = m5.make_stage9_project(tmp, f"mil-fpi-key-{index}")
            report = expect_fail(root, p,
                                 candidate_with(p, with_inputs(**{key: KeyError})),
                                 "financial_input_unresolved",
                                 f"financial_plan_inputs without {key}")
            if not any(key in str(ref)
                       for ref in refs_for(report, "financial_input_unresolved")):
                raise TestFailure(
                    f"{key}: the missing interface key must be named in the "
                    f"ref: {refs_for(report, 'financial_input_unresolved')}")

        # 8c. Riferimento scalare non risolvibile.
        p = m5.make_stage9_project(tmp, "mil-fpi-ghost")
        expect_fail(root, p, candidate_with(p, with_inputs(som_ref="ASS-999")),
                    "financial_input_unresolved", "unresolved som_ref")

        # 8d. Riferimento di array non risolvibile.
        p = m5.make_stage9_project(tmp, "mil-fpi-ghost-array")
        expect_fail(root, p,
                    candidate_with(p, with_inputs(cogs_refs=["ASS-999"])),
                    "financial_input_unresolved", "unresolved cogs ref")

        # 8e. Valore duplicato invece di una referenza: l'interfaccia porta
        #     ref, mai numeri (contratto financial_plan_inputs).
        p = m5.make_stage9_project(tmp, "mil-fpi-literal")
        expect_fail(root, p, candidate_with(p, with_inputs(pricing_ref=100)),
                    "financial_input_unresolved", "literal price in the interface")

        # 8f. Classe di riferimenti dichiarata vuota: una chiave obbligatoria
        #     senza alcun ref non è risolvibile dallo Stage 10.
        p = m5.make_stage9_project(tmp, "mil-fpi-empty")
        expect_fail(root, p, candidate_with(p, with_inputs(cogs_refs=[])),
                    "financial_input_unresolved", "empty required ref class")

        # 8g. Interfaccia incompleta: un costo di milestone che non compare in
        #     milestone_cost_refs resterebbe invisibile allo Stage 10.
        p = m5.make_stage9_project(tmp, "mil-fpi-partial")
        report = expect_fail(
            root, p,
            candidate_with(p, with_inputs(
                milestone_cost_refs=list(m5.MILESTONE_COST_IDS[:3]))),
            "financial_input_unresolved",
            "milestone cost missing from the Stage 10 interface")
        if m5.MILESTONE_COST_IDS[3] not in refs_for(
                report, "financial_input_unresolved"):
            raise TestFailure(
                "the milestone cost left out of the interface must be the ref: "
                f"{refs_for(report, 'financial_input_unresolved')}")

        # ------------------------------------------------ missing_required
        # 9a. structured-output assente in egress.
        p = m5.make_stage9_project(tmp, "mil-nostruct")
        c = kit.make_candidate(p, m5.S9, tx_id="tx-mil-empty",
                               proposed=m5.milestone_proposed())
        expect_fail(root, p, c, "missing_required", "no structured output")

        # 9b. structured-output senza milestone_plan.
        p = m5.make_stage9_project(tmp, "mil-noblock")
        expect_fail(root, p, candidate_with(p, {}), "missing_required",
                    "no milestone_plan block")

        # 9c. milestones[] vuoto: una roadmap senza milestone non è una
        #     roadmap.
        p = m5.make_stage9_project(tmp, "mil-nomilestones")
        expect_fail(root, p,
                    candidate_with(p, m5.milestone_structured(milestones=[])),
                    "missing_required", "empty milestones")

        # 9d. Stage 8 canonico assente in egress di Stage 9: senza i ROLE-
        #     canonici la proprietà delle milestone non è verificabile.
        p = m5.make_stage9_project(tmp, "mil-noteam", team=False)
        report = expect_fail(root, p,
                             candidate_with(p, m5.milestone_structured()),
                             "missing_required", "no canonical Stage 8 output")
        if any(e["code"] == "milestone_owner_unresolved"
               for e in report["errors"]):
            raise TestFailure(
                "a missing canonical Stage 8 must not be reported as an owner "
                f"defect on every milestone: {report}")

        # --------------------------------------------------------- warning
        # 10a. milestone_target_above_capacity: i volumi dichiarati
        #      nell'interfaccia superano la capacità operativa canonica. È il
        #      SEGNALE del ciclo di capacità operativa: il detect bloccante è del cross-stage,
        #      qui resta warning (exit 0).
        target = m5.entry("ASS-040", "customers_target_roadmap", 5000, "count",
                          category="roadmap")
        p = m5.make_stage9_project(tmp, "mil-above-capacity",
                                   assumptions_extra=[target])
        report = expect_pass(root, p,
                             candidate_with(p, with_inputs(
                                 funnel_customers_ref="ASS-040")),
                             "commercial target above operating capacity")
        if "milestone_target_above_capacity" not in [w["code"] for w
                                                     in report["warnings"]]:
            raise TestFailure(
                f"a target above capacity must warn, not pass silently: "
                f"{report}")

        # 10b. long_gap_between_milestones: buco lungo fra la chiusura di una
        #      dipendenza e l'avvio della milestone che ne dipende.
        p = m5.make_stage9_project(tmp, "mil-longgap")
        report = expect_pass(root, p,
                             candidate_with(p, with_milestone(
                                 1, start_date="2028-01-07",
                                 target_date="2028-06-30")),
                             "long gap between dependent milestones")
        if "long_gap_between_milestones" not in [w["code"] for w
                                                 in report["warnings"]]:
            raise TestFailure(f"a long roadmap gap must warn: {report}")

        # ------------------------------------------------ three-state e uso
        # 11. Progetto a stage 5, impact su Stage 9 -> PASS not_yet_required
        #     (mai FAIL: un progetto che non ha ancora raggiunto lo Stage 9 resta
        #     valido).
        p5 = m5.make_stage5_project(tmp, "mil-early")
        report = expect_pass(root, p5, None, "three-state stage 5",
                             phase="impact")
        if "not_yet_required" not in [w["code"] for w in report["warnings"]]:
            raise TestFailure("stage 5 project must be not_yet_required")

        # 12. Fuori matrice: stage 8 -> exit 2 (errore d'uso, non gate).
        exit_code, _, _ = run_validator(root, p5, None, stage=m5.S8,
                                        phase="impact")
        if exit_code != 2:
            raise TestFailure(f"stage fuori matrice must exit 2, got "
                              f"{exit_code}")

        # 13. Fuori matrice: fase candidate -> exit 2.
        p = m5.make_stage9_project(tmp, "mil-phase")
        c = candidate_with(p, m5.milestone_structured())
        exit_code, _, _ = run_validator(root, p, c, phase="candidate")
        if exit_code != 2:
            raise TestFailure(f"fase fuori matrice must exit 2, got "
                              f"{exit_code}")

        # ---------------------------------------------------------- impact
        # 14a. Impact sul canonico dello Stage 9 applicato -> PASS.
        p = m5.make_stage9_project(tmp, "mil-impact-ok",
                                   assumptions_extra=m5.milestone_assumptions())
        kit.write_json(p / m5.S9 / "structured-output.json",
                       m5.canonical_milestone_structured())
        (p / "shared" / "project-status.md").write_text(
            kit.project_status_text(
                "mil-impact-ok", m5.S9, "approved",
                m5.COMPLETED_THROUGH_8 + [m5.S9]),
            encoding="utf-8")
        report = expect_pass(root, p, None, "impact on the applied roadmap",
                             phase="impact")
        if report["errors"] or report["warnings"]:
            raise TestFailure(f"applied roadmap must be clean: {report}")

        # 14b. Impact con difetto sul canonico: il ciclo non è più coperto da
        #      alcun egress, quindi deve emergere qui.
        p = m5.make_stage9_project(tmp, "mil-impact-cycle",
                                   assumptions_extra=m5.milestone_assumptions())
        broken = m5.canonical_milestone_structured()
        broken["milestone_plan"]["milestones"][0]["depends_on"] = ["MIL-002"]
        kit.write_json(p / m5.S9 / "structured-output.json", broken)
        (p / "shared" / "project-status.md").write_text(
            kit.project_status_text(
                "mil-impact-cycle", m5.S9, "approved",
                m5.COMPLETED_THROUGH_8 + [m5.S9]),
            encoding="utf-8")
        expect_fail(root, p, None, "milestone_cycle_detected",
                    "cycle detected in impact", phase="impact")

        # 14c. Stage 9 in completed_stages ma senza structured-output canonico
        #      -> missing_required (mai un PASS silenzioso).
        p = m5.make_stage9_project(tmp, "mil-impact-missing")
        (p / "shared" / "project-status.md").write_text(
            kit.project_status_text(
                "mil-impact-missing", m5.S9, "approved",
                m5.COMPLETED_THROUGH_8 + [m5.S9]),
            encoding="utf-8")
        expect_fail(root, p, None, "missing_required",
                    "stage 9 completed without canonical output",
                    phase="impact")

        # ------------------------- binding col transaction manager
        # egress Stage 9 verde su fixture: apply passa e il validator è nel
        # journal insieme a stage_gate/refint/cross-stage.
        p = m5.make_stage9_project(tmp, "mil-tm")
        c = candidate_with(p, m5.milestone_structured())
        exit_code, out, err = kit.run_tm_cli(
            root, "apply", "--project", p, "--stage", m5.S9, "--candidate", c)
        if exit_code != 0:
            raise TestFailure(f"TM apply stage 9 must pass, got {exit_code} "
                              f"(out {out.strip()!r} err {err.strip()!r})")
        journal = kit.read_json(kit.find_journals(p)[-1])
        ran = {v["validator"] for v in journal.get("validation", [])}
        if NAME not in ran:
            raise TestFailure(f"TM egress at stage 9 must run {NAME}: {ran}")

        # candidate con ciclo nel DAG -> TM rejected, canonico invariato.
        p = m5.make_stage9_project(tmp, "mil-tm-reject")
        c = candidate_with(p, two_node_cycle(), tx_id="tx-mil-reject")
        before = kit.snapshot_canonical(p)
        exit_code, out, err = kit.run_tm_cli(
            root, "apply", "--project", p, "--stage", m5.S9, "--candidate", c)
        if exit_code != 1:
            raise TestFailure("TM apply with a cyclic roadmap must be "
                              f"rejected, got {exit_code}")
        if kit.snapshot_canonical(p) != before:
            raise TestFailure("rejected apply mutated canonical state")

        # ------------------------- nessun artefatto dello Stage 10
        # Il validator non produce e non richiede alcun artefatto Stage 10:
        # financial_plan_inputs è refs-only.
        p = m5.make_stage9_project(tmp, "mil-no-stage10")
        c = candidate_with(p, m5.milestone_structured())
        expect_pass(root, p, c, "no Stage 10 artefact required")
        if (p / "10_financial-plan").exists():
            raise TestFailure("Stage 9 must not create any Stage 10 folder")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-MILESTONE-CHAIN DAG/date/owner/cost/criteria/category + "
          "financial_plan_inputs")


if __name__ == "__main__":
    main()
