#!/usr/bin/env python3
"""T-TEAM-GOV — validate_team_and_governance (Stage 8: team e governance).

Stage 8, fasi egress/impact. Un caso RED per ogni error code del validator:
core_process_unowned, capability_gap_unaddressed, decision_right_ambiguous
(0 e >1 owner), equity_sum_exceeds_one, fte_not_ref, value_mismatch,
unit_mismatch, unresolved_ref (risk), missing_required. Più: i due warning
(key_person_dependency, open_position_unbudgeted con l'escalation a error
quando lo stage può chiudere `approved` pieno), l'equity a somma esattamente
1 (confine incluso -> PASS), three-state (progetto a stage 5 ->
not_yet_required), fuori matrice -> exit 2, pass-through in egress di Stage 9
e binding col transaction manager.

La risoluzione dei namespace tipizzati (`covers_processes` -> OPS- con
entity_type core_process, `owner_ref`/`role_ref` -> ROLE- esistenti, id
duplicati) è di validate_referential_integrity, coperta da
T-REFINT-EXT: qui non si duplica.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit
import bpo_m5_fixtures as m5


class TestFailure(AssertionError):
    pass


NAME = "validate_team_and_governance"
S9 = "09_roadmap-and-milestones"


def run_validator(root, project, candidate=None, stage=m5.S8, phase="egress"):
    return kit.run_validator_cli(root, NAME, project=project, stage=stage,
                                 phase=phase, candidate=candidate)


def expect_pass(root, project, candidate, label, stage=m5.S8, phase="egress"):
    before = kit.snapshot_tree(project)
    exit_code, out, err = run_validator(root, project, candidate, stage, phase)
    if exit_code != 0:
        raise TestFailure(f"{label}: expected exit 0, got {exit_code} "
                          f"(out {out.strip()!r} err {err.strip()!r})")
    report = kit.parse_report(out, label)
    if kit.snapshot_tree(project) != before:
        raise TestFailure(f"{label}: validator mutated the project")
    return report


def expect_fail(root, project, candidate, code, label, stage=m5.S8,
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


def candidate_with(project, structured, proposed=None, tx_id="tx-team-001",
                   conditions=None):
    if proposed is None:
        proposed = m5.team_proposed()
    candidate = kit.make_candidate(project, m5.S8, tx_id=tx_id,
                                   structured=structured, proposed=proposed)
    if conditions is not None:
        kit.write_json(candidate / "proposed-conditions.json", conditions)
    return candidate


def roles_without_partnerships():
    """ROLE-002 non copre più OPS-005: un processo core resta senza owner."""
    doc = m5.team_structured()
    doc["team_governance"]["roles"][1]["covers_processes"] = []
    return doc


def with_gap(addressed_by, **kwargs):
    """Structured output di Stage 8 con un solo capability gap, indirizzato
    da `addressed_by`. Serve a isolare la risoluzione del meccanismo."""
    struct = m5.team_structured(**kwargs)
    struct["team_governance"]["capability_gaps"] = [{
        "gap": "Compliance privacy (DPO) non presidiata internamente",
        "addressed_by": addressed_by,
    }]
    return struct


def gap_refs(report):
    return [e["ref"] for e in report["errors"]
            if e["code"] == "capability_gap_unaddressed"]


# Candidate REALE di uno Stage 9 (milestone_plan popolato e risolvibile sul
# progetto fixture, che ha lo Stage 8 applicato). È **solo dato di prova** per
# il pass-through dell'egress: qui non si implementa nulla dello Stage 9 e
# nessun validator legge questo documento.
STAGE9_COST_REFS = ("P-ASS-301", "P-ASS-302")


def stage9_shaped_structured():
    return {"milestone_plan": {
        "milestones": [
            {
                "id": "MIL-001",
                "title": "MVP in produzione sul primo cliente pilota",
                "category": "technical",
                "owner_ref": "ROLE-001",
                "depends_on": [],
                "start_date": "2026-09-01",
                "target_date": "2026-12-15",
                "cost_ref": STAGE9_COST_REFS[0],
                "success_criteria": ["10 clienti pilota attivi"],
                "go_no_go_rule": "Go se la retention pilota >= 70%",
                "exit_criteria": "MVP stabile per 30 giorni consecutivi",
                "risk_refs": ["RISK-001"],
            },
            {
                "id": "MIL-002",
                "title": "Canale partner a regime",
                "category": "commercial",
                "owner_ref": "ROLE-002",
                "depends_on": ["MIL-001"],
                "start_date": "2027-01-07",
                "target_date": "2027-06-30",
                "cost_ref": STAGE9_COST_REFS[1],
                "success_criteria": ["CAC <= 250 EUR per due mesi"],
                "go_no_go_rule": "Go se il CAC resta entro target",
                "exit_criteria": "Canale replicabile documentato",
                "risk_refs": [],
            },
        ],
        "financial_plan_inputs": {
            "pricing_ref": m5.PRICING_ID,
            "cogs_refs": [m5.COGS_ID],
            "funnel_customers_ref": m5.CUSTOMERS_OUT_ID,
            "churn_ref": "ASS-024",
            "ops_capacity_ref": m5.OPS_CAPACITY_CANONICAL_ID,
            "headcount_driver_refs": [
                m5.CANONICAL_TEAM_IDS[m5.FTE_LEAD_ID],
                m5.CANONICAL_TEAM_IDS[m5.FTE_OPEN_ID],
            ],
            "milestone_cost_refs": list(STAGE9_COST_REFS),
            "som_ref": m5.SOM_ID,
        },
    }}


def stage9_shaped_proposed():
    return [
        m5.entry(STAGE9_COST_REFS[0], "milestone_cost_mvp", 80000.0, "EUR",
                 category="operations"),
        m5.entry(STAGE9_COST_REFS[1], "milestone_cost_partner", 40000.0, "EUR",
                 category="gtm"),
    ]


def open_condition(cond_id="COND-010", stage=m5.S8, due=S9):
    return {
        "id": cond_id,
        "stage": stage,
        "description": "Budget headcount da confermare col nuovo socio",
        "validation_action": "Delibera del CdA sul piano assunzioni",
        "owner": "founder",
        "due_before_stage": due,
        "resolution_status": "open",
    }


def run(root):
    if not (root / kit.VALIDATORS_REL / f"{NAME}.py").exists():
        raise TestFailure(f"missing validator: {NAME}.py")

    with tempfile.TemporaryDirectory(prefix="bpo-team-") as tmp:
        tmp = Path(tmp)

        # 1. Happy path Stage 8: ogni processo core coperto, gap indirizzato,
        #    decision right univoci, equity a somma esattamente 1 -> PASS
        #    pulito (nessun warning: il confine equity == 1 è incluso).
        p = m5.make_stage8_project(tmp, "team-happy")
        c = candidate_with(p, m5.team_structured())
        report = expect_pass(root, p, c, "team happy path")
        if report["errors"] or report["warnings"]:
            raise TestFailure(f"happy path must be clean: {report}")

        # 2. Processo core dello Stage 7 senza alcun ROLE- -> core_process_unowned.
        p = m5.make_stage8_project(tmp, "team-unowned")
        report = expect_fail(root, p,
                             candidate_with(p, roles_without_partnerships()),
                             "core_process_unowned", "core process unowned")
        refs = [e["ref"] for e in report["errors"]
                if e["code"] == "core_process_unowned"]
        if refs != ["OPS-005"]:
            raise TestFailure(
                f"core_process_unowned must point at the uncovered OPS- "
                f"definition, got {refs}")

        # ------------------------------------------------------------------
        # 3. capability_gap_unaddressed — risoluzione STRUTTURATA di
        #    addressed_by. Un gap è indirizzato solo se
        #    addressed_by risolve a un meccanismo reale: COND- esistente,
        #    assunzione pianificata (ruolo aperto + riga di hiring_plan con
        #    cost_driver_ref) o advisor dichiarato in advisors[]. La prosa
        #    rassicurante non è un meccanismo.
        # ------------------------------------------------------------------

        # 3a. addressed_by vuoto -> capability_gap_unaddressed, con un path
        #     stabile come ref (mai solo null).
        p = m5.make_stage8_project(tmp, "team-gap-blank")
        report = expect_fail(root, p, candidate_with(p, with_gap("   ")),
                             "capability_gap_unaddressed",
                             "gap addressed_by blank")
        if gap_refs(report) != ["team_governance.capability_gaps[0]"]:
            raise TestFailure(
                f"blank gap must be reported on a stable structured path, "
                f"got {gap_refs(report)}")

        # 3b. COND- inesistente: un gap «coperto» da una condizione che non
        #     esiste non è indirizzato; il ref è la COND- fantasma.
        p = m5.make_stage8_project(tmp, "team-gap-cond")
        report = expect_fail(root, p, candidate_with(p, with_gap("COND-042")),
                             "capability_gap_unaddressed",
                             "gap addressed by ghost COND")
        if gap_refs(report) != ["COND-042"]:
            raise TestFailure(f"ghost COND must be the reported ref, "
                              f"got {gap_refs(report)}")

        # 3c. la stessa COND-, se esiste nel registro canonico -> PASS.
        p = m5.make_stage8_project(tmp, "team-gap-cond-ok",
                                   conditions=[open_condition("COND-042")])
        expect_pass(root, p, candidate_with(p, with_gap("COND-042")),
                    "gap addressed by an existing canonical COND")

        # 3d. COND- solo proposta nel candidate (non ancora canonica) -> PASS:
        #     il percorso approved_with_conditions è un meccanismo reale.
        p = m5.make_stage8_project(tmp, "team-gap-cond-proposed")
        c = candidate_with(p, with_gap("COND-077"),
                           conditions=[open_condition("COND-077")])
        expect_pass(root, p, c, "gap addressed by a candidate-proposed COND")

        # 3e. Assunzione REALE: ruolo aperto + riga di hiring_plan con
        #     cost_driver_ref -> PASS.
        p = m5.make_stage8_project(tmp, "team-gap-hire-ok")
        expect_pass(root, p, candidate_with(p, with_gap("hire ROLE-002")),
                    "gap addressed by a budgeted open role")

        # 3f. Stesso ruolo aperto ma nessuna riga di hiring_plan: la promessa
        #     di assunzione non ha struttura -> error.
        p = m5.make_stage8_project(tmp, "team-gap-hire-noplan")
        report = expect_fail(
            root, p, candidate_with(p, with_gap("ROLE-002", hiring_plan=[])),
            "capability_gap_unaddressed", "gap addressed by an unplanned hire")
        if gap_refs(report) != ["ROLE-002"]:
            raise TestFailure(f"the ghost hiring mechanism must be the ref, "
                              f"got {gap_refs(report)}")

        # 3g. Riga di hiring_plan intestata a un ALTRO ruolo: ROLE-002 resta
        #     senza meccanismo -> error.
        p = m5.make_stage8_project(tmp, "team-gap-hire-wrongrole")
        struct = with_gap("hire ROLE-002", hiring_plan=[{
            "role_ref": "ROLE-001", "period": "Y1H2",
            "cost_driver_ref": m5.HEADCOUNT_COST_ID}])
        expect_fail(root, p, candidate_with(p, struct),
                    "capability_gap_unaddressed",
                    "gap addressed by a hire planned for another role")

        # 3h. Un ruolo già ricoperto non è un meccanismo di hiring: chi c'è
        #     già non chiude un gap dichiarato -> error.
        p = m5.make_stage8_project(tmp, "team-gap-hire-filled")
        expect_fail(root, p, candidate_with(p, with_gap("hire ROLE-001")),
                    "capability_gap_unaddressed",
                    "gap addressed by an already filled role")

        # 3i. Advisor dichiarato in advisors[] -> PASS, con l'etichetta e in
        #     forma nuda dopo la normalizzazione (trim/case/spazi).
        for idx, (label, text) in enumerate((
                ("labelled advisor", "advisor: Studio Legale Esempio"),
                ("normalised advisor", "  StUdIo   LeGaLe   EsEmPiO  "))):
            p = m5.make_stage8_project(tmp, f"team-gap-adv-{idx}")
            expect_pass(root, p, candidate_with(p, with_gap(text)),
                        f"gap addressed by a declared advisor ({label})")

        # 3j. Advisor mai dichiarato in advisors[] -> error.
        p = m5.make_stage8_project(tmp, "team-gap-adv-ghost")
        expect_fail(root, p,
                    candidate_with(p, with_gap("advisor: Studio Ignoto")),
                    "capability_gap_unaddressed",
                    "gap addressed by an undeclared advisor")

        # 3k. Prosa non verificabile: nessun meccanismo strutturato -> error.
        #     È il cuore di F1: qualunque stringa non vuota NON basta.
        for idx, text in enumerate((
                "will hire someone later",
                "advisor to be identified",
                "future CTO",
                "external support",
                "assumeremo un DPO appena ci sarà budget",
                "ROLE-999",
                "COND-0042")):
            p = m5.make_stage8_project(tmp, f"team-gap-prose-{idx}")
            expect_fail(root, p, candidate_with(p, with_gap(text)),
                        "capability_gap_unaddressed",
                        f"placeholder prose must not address a gap: {text!r}")

        # 4a. Due decision right sulla stessa area con owner diversi -> >1 owner.
        p = m5.make_stage8_project(tmp, "team-dr-many")
        struct = m5.team_structured()
        struct["team_governance"]["decision_rights"].append(
            {"area": "Prodotto e roadmap", "owner_ref": "ROLE-002"})
        expect_fail(root, p, candidate_with(p, struct),
                    "decision_right_ambiguous", "same area, two owners")

        # 4b. Decision right senza owner_ref -> 0 owner.
        p = m5.make_stage8_project(tmp, "team-dr-none")
        struct = m5.team_structured()
        del struct["team_governance"]["decision_rights"][0]["owner_ref"]
        expect_fail(root, p, candidate_with(p, struct),
                    "decision_right_ambiguous", "decision right without owner")

        # 5. Equity oltre 1 -> equity_sum_exceeds_one.
        p = m5.make_stage8_project(tmp, "team-equity")
        struct = m5.team_structured(equity_split=[
            {"holder": "Giulia Rossi", "share": 0.7},
            {"holder": "Marco Bianchi", "share": 0.4},
        ])
        expect_fail(root, p, candidate_with(p, struct),
                    "equity_sum_exceeds_one", "equity above one")

        # 6a. fte_ref letterale invece di un riferimento ASS- -> fte_not_ref.
        p = m5.make_stage8_project(tmp, "team-fte-literal")
        struct = m5.team_structured()
        struct["team_governance"]["roles"][0]["fte_ref"] = 1.0
        expect_fail(root, p, candidate_with(p, struct), "fte_not_ref",
                    "fte literal instead of ASS- ref")

        # 6b. cost_driver_ref del piano assunzioni non risolvibile.
        p = m5.make_stage8_project(tmp, "team-cost-ghost")
        struct = m5.team_structured()
        struct["team_governance"]["hiring_plan"][0]["cost_driver_ref"] = \
            "P-ASS-999"
        expect_fail(root, p, candidate_with(p, struct), "fte_not_ref",
                    "hiring cost driver unresolved")

        # 7. Driver di costo headcount derivato ma con ricalcolo divergente.
        p = m5.make_stage8_project(tmp, "team-vm")
        expect_fail(root, p,
                    candidate_with(p, m5.team_structured(),
                                   proposed=m5.team_proposed(
                                       headcount_cost=99999)),
                    "value_mismatch", "headcount cost recompute drift")

        # 8. Unità FTE disomogenee fra i ruoli: il totale headcount non è
        #    sommabile -> unit_mismatch. Il driver mutato (fte_ceo) NON entra
        #    in alcuna formula: l'errore può venire solo dal confronto fra i
        #    ruoli, non dall'algebra delle unità della DSL.
        p = m5.make_stage8_project(tmp, "team-unit")
        proposed = m5.with_variable(m5.team_proposed(), "fte_ceo",
                                    unit="count")
        expect_fail(root, p,
                    candidate_with(p, m5.team_structured(), proposed=proposed),
                    "unit_mismatch", "heterogeneous FTE units")

        # 9. risk_ref non presente nel risk-register -> unresolved_ref.
        p = m5.make_stage8_project(tmp, "team-risk")
        expect_fail(root, p,
                    candidate_with(p, m5.team_structured(
                        risk_refs=["RISK-999"])),
                    "unresolved_ref", "risk ref unresolved")

        # 10a. structured-output assente in egress -> missing_required.
        p = m5.make_stage8_project(tmp, "team-nostruct")
        c = kit.make_candidate(p, m5.S8, tx_id="tx-team-empty",
                               proposed=m5.team_proposed())
        expect_fail(root, p, c, "missing_required", "no structured output")

        # 10b. structured-output senza team_governance -> missing_required.
        p = m5.make_stage8_project(tmp, "team-noblock")
        expect_fail(root, p, candidate_with(p, {}), "missing_required",
                    "no team_governance block")

        # 10c. roles[] vuoto -> missing_required.
        p = m5.make_stage8_project(tmp, "team-noroles")
        expect_fail(root, p, candidate_with(p, m5.team_structured(roles=[])),
                    "missing_required", "empty roles")

        # 10d. decision_rights[] vuoto -> missing_required.
        p = m5.make_stage8_project(tmp, "team-nodr")
        expect_fail(root, p,
                    candidate_with(p, m5.team_structured(decision_rights=[])),
                    "missing_required", "empty decision rights")

        # 10e. Stage 7 canonico assente in egress di Stage 8: la copertura dei
        #      processi core non è verificabile -> missing_required.
        p = m5.make_stage8_project(tmp, "team-noops", operations=False)
        expect_fail(root, p, candidate_with(p, m5.team_structured()),
                    "missing_required", "no canonical Stage 7 output")

        # 11. Warning key_person_dependency: un solo ROLE- copre tutti i
        #     processi core (soglia strutturale).
        p = m5.make_stage8_project(tmp, "team-keyperson")
        struct = m5.team_structured()
        struct["team_governance"]["roles"][0]["covers_processes"] = \
            list(m5.CORE_PROCESS_IDS)
        struct["team_governance"]["roles"][1]["covers_processes"] = []
        report = expect_pass(root, p, candidate_with(p, struct),
                             "key person dependency")
        codes = [w["code"] for w in report["warnings"]]
        if "key_person_dependency" not in codes:
            raise TestFailure(f"key person concentration must warn: {codes}")

        # 12a. Posizione aperta senza cost_driver_ref e senza alcuna COND
        #      aperta: lo stage può chiudere solo `approved` pieno, quindi
        #      open_position_unbudgeted è un error.
        p = m5.make_stage8_project(tmp, "team-openpos-error")
        struct = m5.team_structured(hiring_plan=[])
        expect_fail(root, p, candidate_with(p, struct),
                    "open_position_unbudgeted", "open position unbudgeted")

        # 12b. Stessa posizione aperta, ma il candidate propone una COND-: il
        #      percorso è approved_with_conditions -> warning, non error.
        p = m5.make_stage8_project(tmp, "team-openpos-warn")
        struct = m5.team_structured(hiring_plan=[])
        c = candidate_with(p, struct, conditions=[open_condition()])
        report = expect_pass(root, p, c, "open position with condition")
        codes = [w["code"] for w in report["warnings"]]
        if "open_position_unbudgeted" not in codes:
            raise TestFailure(
                f"unbudgeted open position must warn with a COND: {codes}")

        # 12c. Stessa posizione aperta, NESSUN proposed-conditions.json, ma una
        #      COND- canonica ancora aperta: il percorso
        #      approved_with_conditions resta disponibile, quindi
        #      open_position_unbudgeted resta warning e non escala (F3).
        p = m5.make_stage8_project(tmp, "team-openpos-canonical-cond",
                                   conditions=[open_condition()])
        c = candidate_with(p, m5.team_structured(hiring_plan=[]))
        if (c / "proposed-conditions.json").exists():
            raise TestFailure("12c must prove the canonical path: the "
                              "candidate must carry no proposed-conditions")
        report = expect_pass(root, p, c,
                             "open position with a canonical open COND")
        codes = [w["code"] for w in report["warnings"]]
        if "open_position_unbudgeted" not in codes:
            raise TestFailure(
                f"a canonical open COND must keep the signal a warning, "
                f"not silence it: {report}")

        # 12d. La stessa COND- canonica ma già risolta non apre nulla: senza
        #      alcun percorso condizionato l'escalation torna un error.
        p = m5.make_stage8_project(
            tmp, "team-openpos-closed-cond",
            conditions=[dict(open_condition(), resolution_status="resolved")])
        expect_fail(root, p,
                    candidate_with(p, m5.team_structured(hiring_plan=[])),
                    "open_position_unbudgeted",
                    "a resolved COND does not open the conditional path")

        # 13. Three-state: progetto a stage 5, impact su Stage 8 -> PASS
        #     not_yet_required (mai FAIL prima dello Stage 8).
        p5 = m5.make_stage5_project(tmp, "team-early")
        report = expect_pass(root, p5, None, "three-state stage 5",
                             stage=m5.S8, phase="impact")
        if "not_yet_required" not in [w["code"] for w in report["warnings"]]:
            raise TestFailure("stage 5 project must be not_yet_required")

        # 14. Fuori matrice: stage 7 -> exit 2 (errore d'uso, non gate).
        exit_code, _, _ = run_validator(root, p5, None, stage=m5.S7,
                                        phase="impact")
        if exit_code != 2:
            raise TestFailure(f"stage fuori matrice must exit 2, got "
                              f"{exit_code}")

        # 15. Pass-through: egress a Stage 9 NON enforce il team model
        #     (l'egress è attivo solo allo Stage 8; a 9 gira in impact). Il
        #     candidate è quello REALE di uno Stage 9 — milestone_plan
        #     popolato, con owner_ref sui ROLE- canonici dello Stage 8,
        #     financial_plan_inputs risolvibili e P-ASS- di costo — su un
        #     progetto che ha davvero applicato lo Stage 8.
        p = m5.make_stage8_project(tmp, "team-egress9",
                                   assumptions_extra=m5.team_assumptions())
        kit.write_json(p / m5.S8 / "structured-output.json",
                       m5.canonical_team_structured())
        (p / "shared" / "project-status.md").write_text(
            kit.project_status_text(
                "team-egress9", S9, "in_progress",
                m5.COMPLETED_THROUGH_7 + [m5.S8]),
            encoding="utf-8")
        c = kit.make_candidate(p, S9, tx_id="tx-team-9",
                               structured=stage9_shaped_structured(),
                               proposed=stage9_shaped_proposed())
        report = expect_pass(root, p, c, "egress stage 9 pass-through",
                             stage=S9, phase="egress")
        if report["errors"] or report["warnings"]:
            raise TestFailure("egress Stage 9 deve essere pass-through "
                              f"(nessun errore/warning): {report}")

        # 15b. Il PASS sopra viene dal pass-through, non dalla forma del
        #      candidate: lo STESSO candidate letto come Stage 8 è un
        #      missing_required. Senza questa prova il caso 15 sarebbe vacuo.
        expect_fail(root, p, c, "missing_required",
                    "the same Stage 9 candidate is not a Stage 8 team model",
                    stage=m5.S8, phase="egress")

        # 16. Impact con Stage 8 nei completed ma senza structured-output
        #     canonico -> missing_required (mai un PASS silenzioso).
        p = m5.make_stage8_project(tmp, "team-impact-missing")
        (p / "shared" / "project-status.md").write_text(
            kit.project_status_text(
                "team-impact-missing", S9, "in_progress",
                m5.COMPLETED_THROUGH_7 + [m5.S8]),
            encoding="utf-8")
        expect_fail(root, p, None, "missing_required",
                    "stage 8 completed without canonical output",
                    stage=S9, phase="impact")

        # 17. In impact lo stage è già chiuso: l'escalation di
        #     open_position_unbudgeted è una regola di gate e non si applica
        #     retroattivamente — resta warning anche senza alcuna COND.
        p = m5.make_stage8_project(tmp, "team-impact-openpos",
                                   assumptions_extra=m5.team_assumptions())
        kit.write_json(p / m5.S8 / "structured-output.json",
                       m5.canonical_team_structured(hiring_plan=[]))
        (p / "shared" / "project-status.md").write_text(
            kit.project_status_text(
                "team-impact-openpos", S9, "in_progress",
                m5.COMPLETED_THROUGH_7 + [m5.S8]),
            encoding="utf-8")
        report = expect_pass(root, p, None, "impact keeps the gate rule out",
                             stage=S9, phase="impact")
        codes = [w["code"] for w in report["warnings"]]
        if "open_position_unbudgeted" not in codes:
            raise TestFailure(
                f"impact must still warn on the unbudgeted position: {report}")

        # ------------------------- binding col transaction manager
        # egress Stage 8 verde su fixture: apply passa e il validator è nel
        # journal insieme a stage_gate/refint/cross-stage.
        p = m5.make_stage8_project(tmp, "team-tm")
        c = candidate_with(p, m5.team_structured())
        exit_code, out, err = kit.run_tm_cli(
            root, "apply", "--project", p, "--stage", m5.S8, "--candidate", c)
        if exit_code != 0:
            raise TestFailure(f"TM apply stage 8 must pass, got {exit_code} "
                              f"(out {out.strip()!r} err {err.strip()!r})")
        journal = kit.read_json(kit.find_journals(p)[-1])
        ran = {v["validator"] for v in journal.get("validation", [])}
        if NAME not in ran:
            raise TestFailure(f"TM egress at stage 8 must run {NAME}: {ran}")

        # candidate con difetto di team -> TM rejected, canonico invariato.
        p = m5.make_stage8_project(tmp, "team-tm-reject")
        c = candidate_with(p, roles_without_partnerships(),
                           tx_id="tx-team-reject")
        before = kit.snapshot_canonical(p)
        exit_code, out, err = kit.run_tm_cli(
            root, "apply", "--project", p, "--stage", m5.S8, "--candidate", c)
        if exit_code != 1:
            raise TestFailure("TM apply with team defect must be rejected, "
                              f"got {exit_code}")
        if kit.snapshot_canonical(p) != before:
            raise TestFailure("rejected apply mutated canonical state")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-TEAM-GOV role coverage/capability gaps/decision rights/"
          "equity/headcount drivers")


if __name__ == "__main__":
    main()
