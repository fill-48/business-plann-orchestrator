#!/usr/bin/env python3
"""T-OPS-FEASIBILITY — validate_operations_feasibility (Stage 7: operations e IP).

Stage 7, fasi egress/impact. Un caso RED per ogni error code del validator:
capacity_not_derived, value_mismatch, unit_mismatch, core_process_unsourced,
ops_cost_not_ref, dependency_category_not_assessed, regulatory_not_assessed,
ip_protection_missing, unresolved_ref (risk), invalid (capacità <= 0),
missing_required. Più: three-state (progetto a stage 5 -> not_yet_required),
fuori matrice -> exit 2, binding col transaction manager (validator nel
journal; egress Stage 7 verde su fixture). La tipizzazione entity_type delle
definizioni OPS- è di validate_referential_integrity, coperta da
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


NAME = "validate_operations_feasibility"


def run_validator(root, project, candidate=None, stage=m5.S7, phase="egress"):
    return kit.run_validator_cli(root, NAME, project=project, stage=stage,
                                 phase=phase, candidate=candidate)


def expect_pass(root, project, candidate, label, stage=m5.S7, phase="egress"):
    before = kit.snapshot_tree(project)
    exit_code, out, err = run_validator(root, project, candidate, stage, phase)
    if exit_code != 0:
        raise TestFailure(f"{label}: expected exit 0, got {exit_code} "
                          f"(out {out.strip()!r} err {err.strip()!r})")
    report = kit.parse_report(out, label)
    if kit.snapshot_tree(project) != before:
        raise TestFailure(f"{label}: validator mutated the project")
    return report


def expect_fail(root, project, candidate, code, label, stage=m5.S7,
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


def candidate_with(project, structured, proposed=None, tx_id="tx-ops-001"):
    if proposed is None:
        proposed = m5.ops_proposed()
    return kit.make_candidate(project, m5.S7, tx_id=tx_id,
                              structured=structured, proposed=proposed)


def run(root):
    if not (root / kit.VALIDATORS_REL / f"{NAME}.py").exists():
        raise TestFailure(f"missing validator: {NAME}.py")

    with tempfile.TemporaryDirectory(prefix="bpo-ops-") as tmp:
        tmp = Path(tmp)

        # 1. Happy path Stage 7: operations model completo e coerente.
        p = m5.make_stage7_project(tmp, "ops-happy")
        c = candidate_with(p, m5.operations_structured())
        report = expect_pass(root, p, c, "operations happy path")
        warn = {w["code"] for w in report["warnings"]}
        if "single_source_dependency" not in warn:
            raise TestFailure("single-source dependency must warn, got "
                              f"{warn}")

        # 2. Processi core assenti -> missing_required.
        p = m5.make_stage7_project(tmp, "ops-nocore")
        struct = m5.operations_structured()
        struct["operations_model"]["core_processes"] = []
        expect_fail(root, p, candidate_with(p, struct), "missing_required",
                    "empty core processes")

        # 3. Processo core senza make/buy/partner -> core_process_unsourced.
        p = m5.make_stage7_project(tmp, "ops-mbp")
        struct = m5.operations_structured()
        del struct["operations_model"]["core_processes"][0]["make_buy_partner"]
        expect_fail(root, p, candidate_with(p, struct),
                    "core_process_unsourced", "core without make/buy/partner")

        # 4. Capacità non derivata (ASS- primario, nessuna formula).
        p = m5.make_stage7_project(tmp, "ops-capnd")
        struct = m5.operations_structured(capacity_ref=m5.LEADS_ID)
        expect_fail(root, p, candidate_with(p, struct),
                    "capacity_not_derived", "capacity not derived")

        # 5. Capacità derivata ma ricalcolo divergente -> value_mismatch.
        p = m5.make_stage7_project(tmp, "ops-capvm")
        expect_fail(root, p,
                    candidate_with(p, m5.operations_structured(),
                                   proposed=m5.ops_proposed(capacity=9999)),
                    "value_mismatch", "capacity recompute drift")

        # 6. Unità della capacità incompatibile con i volumi GTM.
        p = m5.make_stage7_project(tmp, "ops-capunit")
        prop = m5.ops_proposed()
        for item in prop:
            if item["variable"] == "ops_capacity_units":
                item["unit"] = "EUR"
        expect_fail(root, p,
                    candidate_with(p, m5.operations_structured(),
                                   proposed=prop),
                    "unit_mismatch", "capacity unit vs GTM volumes")

        # 7. Capacità <= 0 -> invalid.
        p = m5.make_stage7_project(tmp, "ops-capzero")
        expect_fail(root, p,
                    candidate_with(p, m5.operations_structured(),
                                   proposed=m5.ops_proposed(capacity=0,
                                                            installed=0)),
                    "invalid", "capacity not positive")

        # 8. Costo operativo letterale invece di ASS- -> ops_cost_not_ref.
        p = m5.make_stage7_project(tmp, "ops-costlit")
        expect_fail(root, p,
                    candidate_with(p, m5.operations_structured(
                        unit_ops_cost_refs=[30])),
                    "ops_cost_not_ref", "ops cost literal")

        # 9. Dipendenza critica non valutata -> dependency_category_not_assessed.
        p = m5.make_stage7_project(tmp, "ops-dep")
        struct = m5.operations_structured()
        del struct["operations_model"]["critical_dependencies"][0]["mitigation"]
        expect_fail(root, p, candidate_with(p, struct),
                    "dependency_category_not_assessed", "dependency unassessed")

        # 10. Requisito regolatorio non valutato -> regulatory_not_assessed.
        p = m5.make_stage7_project(tmp, "ops-reg")
        struct = m5.operations_structured()
        del struct["operations_model"]["regulatory_requirements"][0][
            "assessment"]
        expect_fail(root, p, candidate_with(p, struct),
                    "regulatory_not_assessed", "regulatory unassessed")

        # 11. Asset IP senza protezione -> ip_protection_missing.
        p = m5.make_stage7_project(tmp, "ops-ip")
        struct = m5.operations_structured()
        del struct["operations_model"]["ip_strategy"]["assets"][0]["protection"]
        expect_fail(root, p, candidate_with(p, struct),
                    "ip_protection_missing", "ip asset without protection")

        # 12. risk_ref non presente nel risk-register -> unresolved_ref.
        p = m5.make_stage7_project(tmp, "ops-risk")
        expect_fail(root, p,
                    candidate_with(p, m5.operations_structured(
                        risk_refs=["RISK-999"])),
                    "unresolved_ref", "risk ref unresolved")

        # 13. structured-output senza operations_model -> missing_required.
        p = m5.make_stage7_project(tmp, "ops-noblock")
        expect_fail(root, p, candidate_with(p, {}), "missing_required",
                    "no operations_model")

        # 14. structured-output assente in egress -> missing_required.
        p = m5.make_stage7_project(tmp, "ops-nostruct")
        c = kit.make_candidate(p, m5.S7, tx_id="tx-ops-empty",
                               proposed=m5.ops_proposed())
        expect_fail(root, p, c, "missing_required", "no structured output")

        # 15. Three-state: progetto a stage 5, impact su Stage 7 -> PASS
        #     not_yet_required (mai FAIL prima dello Stage 7).
        p5 = m5.make_stage5_project(tmp, "ops-early")
        report = expect_pass(root, p5, None, "three-state stage 5",
                             stage=m5.S7, phase="impact")
        if "not_yet_required" not in [w["code"] for w in report["warnings"]]:
            raise TestFailure("stage 5 project must be not_yet_required")

        # 16. Fuori matrice: stage 6 -> exit 2 (errore d'uso, non gate).
        exit_code, _, _ = run_validator(root, p5, None, stage=m5.S6,
                                        phase="impact")
        if exit_code != 2:
            raise TestFailure(f"stage fuori matrice must exit 2, got "
                              f"{exit_code}")

        # 17. Pass-through: egress a Stage 8 NON enforce l'operations model
        #     (egress attivo solo per lo Stage 7; a 8-9 gira in impact).
        #     Il candidate è quello REALE di uno Stage 8 — team_governance su
        #     un progetto che ha davvero applicato lo Stage 7 — e non un
        #     documento di Stage 7 riletto a un altro stage: un input che il
        #     validator avrebbe accettato comunque non dimostrerebbe nulla.
        p = m5.make_stage8_project(tmp, "ops-egress8")
        c = kit.make_candidate(p, m5.S8, tx_id="tx-ops-8",
                               structured=m5.team_structured(),
                               proposed=m5.team_proposed())
        report = expect_pass(root, p, c, "egress stage 8 pass-through",
                             stage=m5.S8, phase="egress")
        if report["errors"] or report["warnings"]:
            raise TestFailure("egress Stage 8 deve essere pass-through "
                              f"(nessun errore/warning): {report}")

        # 17b. Il PASS sopra viene dal pass-through, non dalla forma del
        #      candidate: lo STESSO candidate letto come Stage 7 è un
        #      missing_required (nessun operations_model). Senza questa prova
        #      il caso 17 sarebbe vacuo.
        expect_fail(root, p, c, "missing_required",
                    "the same Stage 8 candidate is not a Stage 7 ops model",
                    stage=m5.S7, phase="egress")

        # ------------------------- binding col transaction manager
        # egress Stage 7 verde su fixture: apply passa e il validator è nel
        # journal insieme a stage_gate/refint/cross-stage.
        p = m5.make_stage7_project(tmp, "ops-tm")
        c = candidate_with(p, m5.operations_structured())
        exit_code, out, err = kit.run_tm_cli(
            root, "apply", "--project", p, "--stage", m5.S7, "--candidate", c)
        if exit_code != 0:
            raise TestFailure(f"TM apply stage 7 must pass, got {exit_code} "
                              f"(out {out.strip()!r} err {err.strip()!r})")
        journal = kit.read_json(kit.find_journals(p)[-1])
        ran = {v["validator"] for v in journal.get("validation", [])}
        if NAME not in ran:
            raise TestFailure(f"TM egress at stage 7 must run {NAME}: {ran}")

        # candidate con difetto ops -> TM rejected, canonico invariato.
        p = m5.make_stage7_project(tmp, "ops-tm-reject")
        struct = m5.operations_structured()
        del struct["operations_model"]["ip_strategy"]["assets"][0]["protection"]
        c = candidate_with(p, struct, tx_id="tx-ops-reject")
        before = kit.snapshot_canonical(p)
        exit_code, out, err = kit.run_tm_cli(
            root, "apply", "--project", p, "--stage", m5.S7, "--candidate", c)
        if exit_code != 1:
            raise TestFailure("TM apply with ops defect must be rejected, got "
                              f"{exit_code}")
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
    print("PASS: T-OPS-FEASIBILITY operations model capacity/make-buy-partner/"
          "dependencies/regulatory/IP feasibility")


if __name__ == "__main__":
    main()
