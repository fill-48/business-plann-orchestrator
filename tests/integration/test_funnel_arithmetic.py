#!/usr/bin/env python3
"""T-FUNNEL-MATH — validate_funnel_arithmetic (Stage 6: go-to-market).

Stage 6, fasi egress/impact. Verifica sul sales funnel: ogni tasso è un
ASS-/P-ASS- ratio in [0,1]; customers_out è derived e coincide col
prodotto leads × Π(tassi) ricalcolato indipendentemente dal validator
(funnel_product_mismatch); coerenza CAC = spend / customers_out
(cac_mismatch, unità EUR/count); churn esplicito dovuto a Stage 6
(missing_required); ricalcolo DSL dell'intera catena raggiungibile.

Binding col transaction manager: apply a Stage 6 include il validator nel
journal; a Stage 5 il validator non gira (matrice di enforcement).
"""
import argparse
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit
import bpo_m5_fixtures as m5


class TestFailure(AssertionError):
    pass


NAME = "validate_funnel_arithmetic"


def run_validator(root, project, candidate=None, stage=m5.S6,
                  phase="egress"):
    return kit.run_validator_cli(root, NAME, project=project, stage=stage,
                                 phase=phase, candidate=candidate)


def expect_pass(root, project, candidate, label, stage=m5.S6,
                phase="egress"):
    before = kit.snapshot_tree(project)
    exit_code, out, err = run_validator(root, project, candidate, stage,
                                        phase)
    if exit_code != 0:
        raise TestFailure(f"{label}: expected exit 0, got {exit_code} "
                          f"(out {out.strip()!r} err {err.strip()!r})")
    report = kit.parse_report(out, label)
    if kit.snapshot_tree(project) != before:
        raise TestFailure(f"{label}: validator mutated the project")
    return report


def expect_fail(root, project, candidate, code, label, stage=m5.S6,
                phase="egress"):
    before = kit.snapshot_tree(project)
    exit_code, out, err = run_validator(root, project, candidate, stage,
                                        phase)
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


def run(root):
    if not (root / kit.VALIDATORS_REL / f"{NAME}.py").exists():
        raise TestFailure(f"missing validator: {NAME}.py")

    with tempfile.TemporaryDirectory(prefix="bpo-funnel-") as tmp:
        tmp = Path(tmp)

        # 1. Funnel coerente: PASS (20000 * 0.25 * 0.2 = 1000; CAC 200).
        p1 = m5.make_stage6_project(tmp, "f1")
        c1 = kit.make_candidate(p1, m5.S6,
                                structured=m5.funnel_structured(),
                                proposed=m5.funnel_proposed())
        expect_pass(root, p1, c1, "funnel happy path")

        # 2. customers_out diverso dal prodotto dei tassi: FAIL.
        p2 = m5.make_stage6_project(tmp, "f2")
        prop = m5.with_variable(m5.funnel_proposed(), "customers_out_y1",
                                value=1500, display_value="1500 count")
        c2 = kit.make_candidate(p2, m5.S6,
                                structured=m5.funnel_structured(),
                                proposed=prop)
        expect_fail(root, p2, c2, "funnel_product_mismatch",
                    "customers_out drift")

        # 3. CAC incoerente con spend / customers_out: FAIL cac_mismatch.
        p3 = m5.make_stage6_project(tmp, "f3")
        prop = m5.with_variable(m5.funnel_proposed(), "cac_y1",
                                value=120, display_value="120 EUR/count")
        c3 = kit.make_candidate(p3, m5.S6,
                                structured=m5.funnel_structured(),
                                proposed=prop)
        expect_fail(root, p3, c3, "cac_mismatch", "CAC drift")

        # 4. Tasso fuori [0,1]: FAIL rate_out_of_bounds (il funnel non
        #    amplifica i lead).
        p4 = m5.make_stage6_project(tmp, "f4")
        prop = m5.funnel_proposed()
        prop = m5.with_variable(prop, "rate_mql_sql", value=1.5,
                                display_value="1.5 ratio")
        prop = m5.with_variable(prop, "customers_out_y1", value=6000,
                                display_value="6000 count")
        prop = m5.with_variable(prop, "cac_y1", value=33.33,
                                display_value="33.33 EUR/count")
        prop = m5.with_variable(prop, "gtm_capacity_revenue_y1",
                                value=6000000,
                                display_value="6000000 EUR")
        c4 = kit.make_candidate(p4, m5.S6,
                                structured=m5.funnel_structured(),
                                proposed=prop)
        expect_fail(root, p4, c4, "rate_out_of_bounds", "rate > 1")

        # 5. Churn assente: FAIL missing_required (dovuto a Stage 6).
        p5 = m5.make_stage6_project(tmp, "f5")
        doc = m5.funnel_structured()
        del doc["sales_funnel"]["churn_ref"]
        c5 = kit.make_candidate(p5, m5.S6, structured=doc,
                                proposed=m5.funnel_proposed())
        expect_fail(root, p5, c5, "missing_required", "churn missing")

        # 6. CAC con unità sbagliata: FAIL unit_mismatch.
        p6 = m5.make_stage6_project(tmp, "f6")
        prop = m5.with_variable(m5.funnel_proposed(), "cac_y1",
                                unit="EUR", display_value="200 EUR")
        c6 = kit.make_candidate(p6, m5.S6,
                                structured=m5.funnel_structured(),
                                proposed=prop)
        expect_fail(root, p6, c6, "unit_mismatch", "CAC unit")

        # 7. structured-output senza sales_funnel: FAIL missing_required.
        p7 = m5.make_stage6_project(tmp, "f7")
        c7 = kit.make_candidate(p7, m5.S6, structured={},
                                proposed=m5.funnel_proposed())
        expect_fail(root, p7, c7, "missing_required", "no funnel")

        # 8. Fuori matrice: Stage 5 o fase candidate -> exit 2.
        p8 = m5.make_stage6_project(tmp, "f8")
        c8 = kit.make_candidate(p8, m5.S6,
                                structured=m5.funnel_structured(),
                                proposed=m5.funnel_proposed())
        exit_code, _, _ = run_validator(root, p8, c8, stage=m5.S5)
        if exit_code != 2:
            raise TestFailure(f"stage fuori matrice must exit 2, got "
                              f"{exit_code}")
        exit_code, _, _ = run_validator(root, p8, c8, phase="candidate")
        if exit_code != 2:
            raise TestFailure(f"fase fuori matrice must exit 2, got "
                              f"{exit_code}")

        # ------------------------- binding col transaction manager
        # apply a Stage 6: il journal include il funnel validator.
        p9 = m5.make_stage6_project(tmp, "f9")
        c9 = kit.make_candidate(p9, m5.S6,
                                structured=m5.funnel_structured(),
                                proposed=m5.funnel_proposed())
        exit_code, out, err = kit.run_tm_cli(
            root, "apply", "--project", p9, "--stage", m5.S6,
            "--candidate", c9)
        if exit_code != 0:
            raise TestFailure(f"TM apply stage 6 must pass, got {exit_code} "
                              f"(out {out.strip()!r} err {err.strip()!r})")
        journal = kit.read_json(kit.find_journals(p9)[-1])
        ran = {v["validator"] for v in journal.get("validation", [])}
        if NAME not in ran:
            raise TestFailure(
                f"TM egress at stage 6 must run {NAME}: {ran}")

        # impact sul canonico appena applicato: PASS; poi deriva del CAC
        # canonico -> impact FAIL cac_mismatch.
        expect_pass(root, p9, None, "impact on canonical", phase="impact")
        register = kit.read_json(p9 / "shared/assumptions-register.json")
        for item in register:
            if item.get("variable") == "cac_y1":
                item["value"] = 500
        kit.write_json(p9 / "shared/assumptions-register.json", register)
        exit_code, out, _ = run_validator(root, p9, None, phase="impact")
        if exit_code != 1:
            raise TestFailure("impact on drifted CAC must exit 1, got "
                              f"{exit_code}")
        report = kit.parse_report(out, "impact drift")
        if "cac_mismatch" not in [e["code"] for e in report["errors"]]:
            raise TestFailure("impact drift: expected cac_mismatch")

        # apply a Stage 5: il funnel validator NON gira (matrice di enforcement).
        p10 = m5.make_stage5_project(tmp, "f10")
        c10 = kit.make_candidate(
            p10, m5.S5, structured=m5.business_structured_proposed(),
            proposed=m5.business_proposed())
        exit_code, out, err = kit.run_tm_cli(
            root, "apply", "--project", p10, "--stage", m5.S5,
            "--candidate", c10)
        if exit_code != 0:
            raise TestFailure(
                "TM apply stage 5 must skip the funnel validator, got "
                f"{exit_code} (out {out.strip()!r} err {err.strip()!r})")
        journal = kit.read_json(kit.find_journals(p10)[-1])
        ran = {v["validator"] for v in journal.get("validation", [])}
        if NAME in ran:
            raise TestFailure(
                "TM egress at stage 5 must not run the funnel validator")

        # candidate con prodotto incoerente -> TM rejected senza mutazioni.
        p11 = m5.make_stage6_project(tmp, "f11")
        prop = m5.with_variable(m5.funnel_proposed(), "customers_out_y1",
                                value=1500, display_value="1500 count")
        c11 = kit.make_candidate(p11, m5.S6,
                                 structured=m5.funnel_structured(),
                                 proposed=prop)
        before = kit.snapshot_canonical(p11)
        exit_code, out, err = kit.run_tm_cli(
            root, "apply", "--project", p11, "--stage", m5.S6,
            "--candidate", c11)
        if exit_code != 1:
            raise TestFailure("TM apply with funnel drift must be rejected, "
                              f"got {exit_code}")
        if kit.snapshot_canonical(p11) != before:
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
    print("PASS: T-FUNNEL-MATH funnel product + CAC coherence + explicit "
          "churn")


if __name__ == "__main__":
    main()
