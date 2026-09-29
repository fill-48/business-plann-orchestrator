#!/usr/bin/env python3
"""T-UNIT-ECONOMICS — validate_unit_economics (Stage 5-6: business model).

Stage 5-6, fasi egress/impact. Verifica sul business model: prezzo = un
solo ASS- di pricing con valore strettamente positivo; il prezzo
eventualmente duplicato nello structured-output coincide con l'ASS-pricing
(la divergenza è T-PRICE, testata a parte); ricavo come formula di driver
(revenue derived con derivation.variables); contribution margin derived
dalla formula prezzo − costi variabili unitari, ricalcolato dalla DSL
(mismatch → FAIL). Il CAC NON appartiene a questo test (T-FUNNEL-MATH):
uno Stage 5 senza funnel deve passare (semantica not_yet_required).

Binding col transaction manager: apply a Stage 5 include il validator nel
journal; candidate con margine divergente → rejected senza mutazioni.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit
import bpo_m5_fixtures as m5


class TestFailure(AssertionError):
    pass


NAME = "validate_unit_economics"


def run_validator(root, project, candidate=None, stage=m5.S5,
                  phase="egress"):
    return kit.run_validator_cli(root, NAME, project=project, stage=stage,
                                 phase=phase, candidate=candidate)


def expect_pass(root, project, candidate, label, stage=m5.S5,
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


def expect_fail(root, project, candidate, code, label, stage=m5.S5,
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

    with tempfile.TemporaryDirectory(prefix="bpo-ue-") as tmp:
        tmp = Path(tmp)

        # 1. Happy path Stage 5 (nessun funnel presente: il CAC non è dovuto
        #    qui — not_yet_required, mai FAIL).
        p1 = m5.make_stage5_project(tmp, "u1")
        c1 = kit.make_candidate(p1, m5.S5,
                                structured=m5.business_structured_proposed(),
                                proposed=m5.business_proposed())
        expect_pass(root, p1, c1, "unit economics happy path")

        # 2. Contribution margin divergente dal ricalcolo: FAIL.
        p2 = m5.make_stage5_project(tmp, "u2")
        prop = m5.with_variable(m5.business_proposed(),
                                "contribution_margin_unit", value=75,
                                display_value="75 EUR/count")
        c2 = kit.make_candidate(p2, m5.S5,
                                structured=m5.business_structured_proposed(),
                                proposed=prop)
        expect_fail(root, p2, c2, "value_mismatch", "margin recompute drift")

        # 3. Margine senza derivation (numero a mano): FAIL margin_not_derived.
        p3 = m5.make_stage5_project(tmp, "u3")
        prop = m5.business_proposed()
        prop = [e for e in prop
                if e["variable"] != "contribution_margin_unit"]
        prop.append(m5.entry("P-ASS-004", "contribution_margin_unit", 60,
                             "EUR/count"))
        c3 = kit.make_candidate(p3, m5.S5,
                                structured=m5.business_structured_proposed(),
                                proposed=prop)
        expect_fail(root, p3, c3, "margin_not_derived", "margin primary")

        # 4. Margine che non referenzia il prezzo tra le variables: FAIL.
        p4 = m5.make_stage5_project(tmp, "u4")
        prop = m5.with_variable(
            m5.business_proposed(), "contribution_margin_unit",
            value=-30, display_value="-30 EUR/count",
            derivation={"method": "bottom_up",
                        "formula": "support_unit - "
                                   "(cogs_unit + support_unit)",
                        "variables": {"cogs_unit": "P-ASS-002",
                                      "support_unit": "P-ASS-003"}})
        c4 = kit.make_candidate(p4, m5.S5,
                                structured=m5.business_structured_proposed(),
                                proposed=prop)
        expect_fail(root, p4, c4, "margin_missing_price",
                    "margin without price variable")

        # 5. Ricavo non formula-based (primary): FAIL revenue_not_derived.
        p5 = m5.make_stage5_project(tmp, "u5")
        prop = m5.business_proposed()
        prop = [e for e in prop if e["variable"] != "revenue_y1"]
        prop.append(m5.entry("P-ASS-006", "revenue_y1", 500000, "EUR"))
        c5 = kit.make_candidate(p5, m5.S5,
                                structured=m5.business_structured_proposed(),
                                proposed=prop)
        expect_fail(root, p5, c5, "revenue_not_derived", "revenue primary")

        # 6. Prezzo non positivo (zero): FAIL price_not_positive (scoped al
        #    pricing, non a tutte le assumptions EUR).
        p6 = m5.make_stage5_project(tmp, "u6")
        prop = m5.with_variable(m5.business_proposed(), "price_net",
                                value=0, display_value="0 EUR/count")
        prop = m5.with_variable(prop, "contribution_margin_unit",
                                value=-40, display_value="-40 EUR/count")
        prop = m5.with_variable(prop, "revenue_y1", value=0,
                                display_value="0 EUR")
        c6 = kit.make_candidate(
            p6, m5.S5, structured=m5.business_structured_proposed(price=0),
            proposed=prop)
        expect_fail(root, p6, c6, "price_not_positive", "price zero")

        # 7. Margine negativo ma coerente: PASS con warning negative_margin
        #    (rosso metodologico, non errore aritmetico).
        p7 = m5.make_stage5_project(tmp, "u7")
        prop = m5.with_variable(m5.business_proposed(), "cogs_unit",
                                value=120, display_value="120 EUR/count")
        prop = m5.with_variable(prop, "contribution_margin_unit",
                                value=-30, display_value="-30 EUR/count")
        c7 = kit.make_candidate(p7, m5.S5,
                                structured=m5.business_structured_proposed(),
                                proposed=prop)
        report = expect_pass(root, p7, c7, "negative margin warning")
        warn_codes = [w["code"] for w in report["warnings"]]
        if "negative_margin" not in warn_codes:
            raise TestFailure("negative margin must produce a warning, got "
                              f"{warn_codes}")

        # 8. structured-output senza business_model: FAIL missing_required.
        p8 = m5.make_stage5_project(tmp, "u8")
        c8 = kit.make_candidate(p8, m5.S5, structured={},
                                proposed=m5.business_proposed())
        expect_fail(root, p8, c8, "missing_required", "no business model")

        # 9. Fuori matrice: Stage 4 o fase candidate -> exit 2.
        p9 = m5.make_stage5_project(tmp, "u9")
        c9 = kit.make_candidate(p9, m5.S5,
                                structured=m5.business_structured_proposed(),
                                proposed=m5.business_proposed())
        exit_code, _, _ = run_validator(root, p9, c9, stage=m5.S4)
        if exit_code != 2:
            raise TestFailure(f"stage fuori matrice must exit 2, got "
                              f"{exit_code}")
        exit_code, _, _ = run_validator(root, p9, c9, phase="candidate")
        if exit_code != 2:
            raise TestFailure(f"fase fuori matrice must exit 2, got "
                              f"{exit_code}")

        # 10. Impact sul canonico Stage 5 applicato: PASS; poi deriva del
        #     margine canonico -> FAIL value_mismatch.
        p10 = m5.make_stage6_project(tmp, "u10")
        expect_pass(root, p10, None, "impact on canonical", stage=m5.S6,
                    phase="impact")
        register = kit.read_json(p10 / "shared/assumptions-register.json")
        for item in register:
            if item.get("variable") == "contribution_margin_unit":
                item["value"] = 99
        kit.write_json(p10 / "shared/assumptions-register.json", register)
        exit_code, out, _ = run_validator(root, p10, None, stage=m5.S6,
                                          phase="impact")
        if exit_code != 1:
            raise TestFailure("impact on drifted margin must exit 1, got "
                              f"{exit_code}")
        report = kit.parse_report(out, "impact drift")
        if "value_mismatch" not in [e["code"] for e in report["errors"]]:
            raise TestFailure("impact drift: expected value_mismatch")

        # ------------------------- binding col transaction manager
        p11 = m5.make_stage5_project(tmp, "u11")
        c11 = kit.make_candidate(p11, m5.S5,
                                 structured=m5.business_structured_proposed(),
                                 proposed=m5.business_proposed())
        exit_code, out, err = kit.run_tm_cli(
            root, "apply", "--project", p11, "--stage", m5.S5,
            "--candidate", c11)
        if exit_code != 0:
            raise TestFailure(f"TM apply stage 5 must pass, got {exit_code} "
                              f"(out {out.strip()!r} err {err.strip()!r})")
        journal = kit.read_json(kit.find_journals(p11)[-1])
        ran = {v["validator"] for v in journal.get("validation", [])}
        if NAME not in ran:
            raise TestFailure(
                f"TM egress at stage 5 must run {NAME}: {ran}")

        # candidate con margine divergente -> TM rejected, canonico invariato.
        p12 = m5.make_stage5_project(tmp, "u12")
        prop = m5.with_variable(m5.business_proposed(),
                                "contribution_margin_unit", value=75,
                                display_value="75 EUR/count")
        c12 = kit.make_candidate(p12, m5.S5,
                                 structured=m5.business_structured_proposed(),
                                 proposed=prop)
        before = kit.snapshot_canonical(p12)
        exit_code, out, err = kit.run_tm_cli(
            root, "apply", "--project", p12, "--stage", m5.S5,
            "--candidate", c12)
        if exit_code != 1:
            raise TestFailure("TM apply with margin drift must be rejected, "
                              f"got {exit_code}")
        if kit.snapshot_canonical(p12) != before:
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
    print("PASS: T-UNIT-ECONOMICS contribution margin recompute + "
          "driver-based revenue + pricing single source")


if __name__ == "__main__":
    main()
