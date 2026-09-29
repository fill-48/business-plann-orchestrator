#!/usr/bin/env python3
"""T-MARKET-MATH — validate_market_arithmetic (Stage 4: mercato e concorrenza).

Verifica su overlay candidate ⊕ canonico: SOM bottom-up obbligatorio e
ricalcolato dalla DSL; ordinamento SOM ≤ SAM ≤ TAM sul valore canonico
riconciliato; top-down o triangolazione indipendente per TAM/SAM;
riconciliazione obbligatoria con ≥2 metodi (weighted_average con pesi che
sommano a 1; selected_ref con rationale, DEC- e valore coerente); ogni
categoria del competitive landscape valutata (`none_identified` solo con
research_notes + rationale). Fasi: egress (candidate) e impact (canonico).

Binding col transaction manager: i validator di dominio girano solo per gli
stage della propria matrice di enforcement — advance/apply a Stage 1-3 non deve
invocare il market validator, apply a Stage 4 deve includerlo nel journal.
"""
import argparse
import copy
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit


class TestFailure(AssertionError):
    pass


S4 = "04_market-and-competition"
COMPLETED_THROUGH_3 = ["00_idea-discovery", "01_problem-and-need",
                       "02_customer-segmentation", "03_value-proposition"]
CATEGORIES = ("direct", "indirect", "substitutes", "internal",
              "non_consumption", "status_quo")


def base(idx, variable, value, unit, category="market", **over):
    entry = {
        "id": f"P-ASS-{idx:03d}",
        "category": category,
        "variable": variable,
        "statement": f"{variable} (fixture)",
        "value": value,
        "display_value": f"{value} {unit}",
        "unit": unit,
        "source": "fixture",
        "owner": "founder",
        "confidence": "low",
        "validation_status": "unvalidated",
        "evidence_classification": "founder_assumption",
        "affected_sections": [S4],
        "last_updated": "2026-07-16",
        "previous_values": [],
    }
    entry.update(over)
    return entry


def derived(idx, variable, value, unit, formula, variables, method,
            strategy=None, selected_ref=None, **over):
    derivation = {"method": method, "variables": variables}
    if formula is not None:
        derivation["formula"] = formula
    if strategy is not None:
        derivation["strategy"] = strategy
    if selected_ref is not None:
        derivation["selected_ref"] = selected_ref
    entry = base(idx, variable, value, unit,
                 kind="derived", derivation=derivation,
                 currency="EUR" if unit.startswith("EUR") else None,
                 period="Y1", scenario="base",
                 evidence_classification="model_estimate")
    entry.update(over)
    return entry


def market_proposed():
    """Catena TAM/SAM/SOM valida: 2 stime TAM + weighted_average, SAM
    top-down, SOM bottom-up; 1'000'000 <= 3'000'000 <= 10'000'000."""
    return [
        base(1, "eligible_customers", 10000, "count"),
        base(2, "reachable_share", 0.1, "ratio"),
        base(3, "arpa_year", 1000, "EUR/count"),
        base(4, "tam_topdown", 10000000, "EUR"),
        derived(5, "tam_bottomup", 10000000, "EUR",
                "eligible_customers * arpa_year",
                {"eligible_customers": "P-ASS-001",
                 "arpa_year": "P-ASS-003"}, "bottom_up"),
        base(6, "w_topdown", 0.6, "ratio"),
        base(7, "w_bottomup", 0.4, "ratio"),
        derived(8, "tam_canonical", 10000000, "EUR",
                "tam_topdown * w_topdown + tam_bottomup * w_bottomup",
                {"tam_topdown": "P-ASS-004", "tam_bottomup": "P-ASS-005",
                 "w_topdown": "P-ASS-006", "w_bottomup": "P-ASS-007"},
                "reconciliation", strategy="weighted_average"),
        base(9, "addressable_share", 0.3, "ratio"),
        derived(10, "sam_topdown", 3000000, "EUR",
                "tam_canonical * addressable_share",
                {"tam_canonical": "P-ASS-008",
                 "addressable_share": "P-ASS-009"}, "top_down"),
        derived(11, "som_y1_revenue", 1000000, "EUR",
                "eligible_customers * reachable_share * arpa_year",
                {"eligible_customers": "P-ASS-001",
                 "reachable_share": "P-ASS-002",
                 "arpa_year": "P-ASS-003"}, "bottom_up"),
    ]


def landscape():
    cats = {}
    for cat in ("direct", "indirect", "substitutes"):
        cats[cat] = {"competitors": [{
            "id": f"CMP-00{len(cats) + 1}",
            "name": f"{cat} player",
            "assessment": "presidia il segmento enterprise, non le PMI",
        }]}
    for cat in ("internal", "non_consumption", "status_quo"):
        cats[cat] = {
            "result": "none_identified",
            "research_notes": "ricerca su directory di settore e interviste",
            "rationale": "nessun attore rilevante per il beachhead",
        }
    return {"categories": cats}


def structured(proposed_refs=None):
    refs = proposed_refs or {"tam_ref": "P-ASS-008", "sam_ref": "P-ASS-010",
                             "som_ref": "P-ASS-011"}
    return {
        "market_model": dict(refs, geography="IT", period="Y1"),
        "competitive_landscape": landscape(),
    }


def stage4_project(tmp, name):
    return kit.make_project(tmp, name=name, current_stage=S4,
                            status="in_progress",
                            completed=COMPLETED_THROUGH_3)


def run_market(root, project, candidate=None, stage=S4, phase="egress"):
    return kit.run_validator_cli(root, "validate_market_arithmetic",
                                 project=project, stage=stage, phase=phase,
                                 candidate=candidate)


def expect_pass(root, project, candidate, label, stage=S4, phase="egress"):
    before = kit.snapshot_tree(project)
    exit_code, out, err = run_market(root, project, candidate, stage, phase)
    if exit_code != 0:
        raise TestFailure(f"{label}: expected exit 0, got {exit_code} "
                          f"(out {out.strip()!r} err {err.strip()!r})")
    report = kit.parse_report(out, label)
    if kit.snapshot_tree(project) != before:
        raise TestFailure(f"{label}: validator mutated the project")
    return report


def expect_fail(root, project, candidate, code, label, stage=S4,
                phase="egress"):
    before = kit.snapshot_tree(project)
    exit_code, out, err = run_market(root, project, candidate, stage, phase)
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


def with_entry(proposed, variable, **changes):
    out = copy.deepcopy(proposed)
    for entry in out:
        if entry["variable"] == variable:
            entry.update(copy.deepcopy(changes))
            return out
    raise AssertionError(f"fixture senza variabile {variable}")


def run(root):
    if not (root / kit.VALIDATORS_REL /
            "validate_market_arithmetic.py").exists():
        raise TestFailure("missing validator: validate_market_arithmetic.py")

    with tempfile.TemporaryDirectory(prefix="bpo-market-") as tmp:
        tmp = Path(tmp)

        # 1. Catena valida completa: PASS.
        p1 = stage4_project(tmp, "m1")
        c1 = kit.make_candidate(p1, S4, structured=structured(),
                                proposed=market_proposed())
        expect_pass(root, p1, c1, "market happy path")

        # 2. SOM non bottom-up: FAIL.
        p2 = stage4_project(tmp, "m2")
        prop = market_proposed()
        som = [e for e in prop if e["variable"] == "som_y1_revenue"][0]
        som["derivation"]["method"] = "top_down"
        c2 = kit.make_candidate(p2, S4, structured=structured(),
                                proposed=prop)
        expect_fail(root, p2, c2, "som_not_bottom_up", "SOM top-down")

        # 2b. SOM primary (nessuna derivation): FAIL.
        p2b = stage4_project(tmp, "m2b")
        prop = market_proposed()
        prop = [e for e in prop if e["variable"] != "som_y1_revenue"]
        prop.append(base(11, "som_y1_revenue", 1000000, "EUR"))
        c2b = kit.make_candidate(p2b, S4, structured=structured(),
                                 proposed=prop)
        expect_fail(root, p2b, c2b, "som_not_bottom_up", "SOM primary")

        # 3. Ordinamento violato (SOM > SAM): FAIL market_ordering.
        p3 = stage4_project(tmp, "m3")
        prop = market_proposed()
        prop = with_entry(prop, "reachable_share", value=0.9,
                          display_value="0.9 ratio")
        prop = with_entry(prop, "som_y1_revenue", value=9000000,
                          display_value="9000000 EUR")
        c3 = kit.make_candidate(p3, S4, structured=structured(),
                                proposed=prop)
        expect_fail(root, p3, c3, "market_ordering", "SOM > SAM")

        # 4. Due stime TAM senza riconciliazione (ref diretto alla stima):
        #    FAIL reconciliation_missing (riconciliazione dei metodi di sizing).
        p4 = stage4_project(tmp, "m4")
        prop = [e for e in market_proposed()
                if e["variable"] not in ("tam_canonical",)]
        # sam dipende da tam_canonical: reindirizza su tam_topdown
        prop = with_entry(prop, "sam_topdown", derivation={
            "method": "top_down",
            "formula": "tam_topdown * addressable_share",
            "variables": {"tam_topdown": "P-ASS-004",
                          "addressable_share": "P-ASS-009"}})
        refs = {"tam_ref": "P-ASS-004", "sam_ref": "P-ASS-010",
                "som_ref": "P-ASS-011"}
        c4 = kit.make_candidate(p4, S4, structured=structured(refs),
                                proposed=prop)
        expect_fail(root, p4, c4, "reconciliation_missing",
                    "two methods without reconciliation")

        # 5. weighted_average con pesi che non sommano a 1: FAIL.
        p5 = stage4_project(tmp, "m5")
        prop = market_proposed()
        prop = with_entry(prop, "w_bottomup", value=0.3,
                          display_value="0.3 ratio")
        prop = with_entry(prop, "tam_canonical", value=9000000,
                          display_value="9000000 EUR")
        c5 = kit.make_candidate(p5, S4, structured=structured(),
                                proposed=prop)
        expect_fail(root, p5, c5, "reconciliation_invalid",
                    "weights not summing to 1")

        # 6. selected_ref valido: PASS; senza decision_ref: FAIL.
        def selected_prop(decision_ref="DEC-014"):
            prop = market_proposed()
            entry = [e for e in prop if e["variable"] == "tam_canonical"][0]
            entry["derivation"] = {
                "method": "reconciliation",
                "strategy": "selected_ref",
                "selected_ref": "P-ASS-005",
                "variables": {"tam_topdown": "P-ASS-004",
                              "tam_bottomup": "P-ASS-005"},
            }
            entry["rationale"] = "bottom-up più prudente e documentato"
            if decision_ref:
                entry["decision_ref"] = decision_ref
            return [e for e in prop
                    if e["variable"] not in ("w_topdown", "w_bottomup")]

        p6 = stage4_project(tmp, "m6")
        c6 = kit.make_candidate(p6, S4, structured=structured(),
                                proposed=selected_prop())
        expect_pass(root, p6, c6, "selected_ref valid")

        p6b = stage4_project(tmp, "m6b")
        c6b = kit.make_candidate(p6b, S4, structured=structured(),
                                 proposed=selected_prop(decision_ref=None))
        expect_fail(root, p6b, c6b, "reconciliation_invalid",
                    "selected_ref without decision_ref")

        # 6c. selected_ref con valore divergente dalla stima selezionata.
        p6c = stage4_project(tmp, "m6c")
        prop = selected_prop()
        prop = with_entry(prop, "tam_canonical", value=9500000,
                          display_value="9500000 EUR")
        c6c = kit.make_candidate(p6c, S4, structured=structured(),
                                 proposed=prop)
        expect_fail(root, p6c, c6c, "value_mismatch",
                    "selected_ref value drift")

        # 7. Ricalcolo derivato divergente: FAIL value_mismatch.
        p7 = stage4_project(tmp, "m7")
        prop = with_entry(market_proposed(), "som_y1_revenue",
                          value=999999, display_value="999999 EUR")
        c7 = kit.make_candidate(p7, S4, structured=structured(),
                                proposed=prop)
        expect_fail(root, p7, c7, "value_mismatch", "recompute mismatch")

        # 8. Landscape: categoria assente e none_identified immotivato.
        p8 = stage4_project(tmp, "m8")
        doc = structured()
        del doc["competitive_landscape"]["categories"]["status_quo"]
        c8 = kit.make_candidate(p8, S4, structured=doc,
                                proposed=market_proposed())
        expect_fail(root, p8, c8, "category_not_evaluated",
                    "missing category")

        p8b = stage4_project(tmp, "m8b")
        doc = structured()
        doc["competitive_landscape"]["categories"]["non_consumption"] = {
            "result": "none_identified"}
        c8b = kit.make_candidate(p8b, S4, structured=doc,
                                 proposed=market_proposed())
        expect_fail(root, p8b, c8b, "none_identified_unmotivated",
                    "none_identified without rationale")

        # 9. TAM senza metodo indipendente (solo bottom-up): FAIL.
        p9 = stage4_project(tmp, "m9")
        prop = [e for e in market_proposed()
                if e["variable"] not in ("tam_topdown", "tam_canonical",
                                         "w_topdown", "w_bottomup")]
        prop = with_entry(prop, "sam_topdown", derivation={
            "method": "top_down",
            "formula": "tam_bottomup * addressable_share",
            "variables": {"tam_bottomup": "P-ASS-005",
                          "addressable_share": "P-ASS-009"}})
        refs = {"tam_ref": "P-ASS-005", "sam_ref": "P-ASS-010",
                "som_ref": "P-ASS-011"}
        c9 = kit.make_candidate(p9, S4, structured=structured(refs),
                                proposed=prop)
        expect_fail(root, p9, c9, "triangulation_missing",
                    "TAM bottom-up only")

        # 10. structured-output assente in egress Stage 4: missing_required.
        p10 = stage4_project(tmp, "m10")
        c10 = kit.make_candidate(p10, S4)
        expect_fail(root, p10, c10, "missing_required",
                    "no structured output")

        # 11. Uso fuori matrice: stage 1 o fase candidate -> exit 2.
        p11 = stage4_project(tmp, "m11")
        c11 = kit.make_candidate(p11, S4, structured=structured(),
                                 proposed=market_proposed())
        exit_code, _, _ = run_market(root, p11, c11,
                                     stage="01_problem-and-need")
        if exit_code != 2:
            raise TestFailure(f"stage fuori matrice must exit 2, got "
                              f"{exit_code}")
        exit_code, _, _ = run_market(root, p11, c11, phase="candidate")
        if exit_code != 2:
            raise TestFailure(f"fase fuori matrice must exit 2, got "
                              f"{exit_code}")

        # ------------------------- F-1: positività TAM/SAM/SOM
        # Le grandezze di mercato sono numeri strettamente positivi: bool,
        # string, null, zero e negativi -> market_value_not_positive. Il
        # vincolo è scoped a TAM/SAM/SOM, non a tutte le assumptions EUR.

        # F-1a. TAM negativo.
        pf1 = stage4_project(tmp, "f1a")
        prop = with_entry(market_proposed(), "tam_canonical",
                          value=-10000000, display_value="-10000000 EUR")
        cf1 = kit.make_candidate(pf1, S4, structured=structured(),
                                 proposed=prop)
        expect_fail(root, pf1, cf1, "market_value_not_positive",
                    "F-1 TAM negative")

        # F-1b. SAM zero.
        pf2 = stage4_project(tmp, "f1b")
        prop = with_entry(market_proposed(), "sam_topdown",
                          value=0, display_value="0 EUR")
        cf2 = kit.make_candidate(pf2, S4, structured=structured(),
                                 proposed=prop)
        expect_fail(root, pf2, cf2, "market_value_not_positive",
                    "F-1 SAM zero")

        # F-1c. SOM negativo (valore diretto).
        pf3 = stage4_project(tmp, "f1c")
        prop = with_entry(market_proposed(), "som_y1_revenue",
                          value=-1000000, display_value="-1000000 EUR")
        cf3 = kit.make_candidate(pf3, S4, structured=structured(),
                                 proposed=prop)
        expect_fail(root, pf3, cf3, "market_value_not_positive",
                    "F-1 SOM negative")

        # F-1d. Driver bottom-up negativo che produce un SOM negativo: la
        # catena resta aritmeticamente coerente (10000 * -0.1 * 1000 =
        # -1000000, nessun value_mismatch) e l'ordinamento è rispettato:
        # l'UNICA violazione rilevabile è la positività del SOM.
        pf4 = stage4_project(tmp, "f1d")
        prop = with_entry(market_proposed(), "reachable_share",
                          value=-0.1, display_value="-0.1 ratio")
        prop = with_entry(prop, "som_y1_revenue", value=-1000000,
                          display_value="-1000000 EUR")
        cf4 = kit.make_candidate(pf4, S4, structured=structured(),
                                 proposed=prop)
        report = expect_fail(root, pf4, cf4, "market_value_not_positive",
                             "F-1 negative bottom-up driver")
        codes = {e["code"] for e in report["errors"]}
        if codes != {"market_value_not_positive"}:
            raise TestFailure(
                "F-1 negative driver: la sola violazione attesa è la "
                f"positività del SOM, got {sorted(codes)}")

        # F-1e. Valori non numerici (string numerica, bool, null) respinti.
        for kind, bad in (("string", "10000000"), ("bool", True),
                          ("null", None)):
            pfx = stage4_project(tmp, f"f1e-{kind}")
            prop = with_entry(market_proposed(), "tam_canonical", value=bad)
            cfx = kit.make_candidate(pfx, S4, structured=structured(),
                                     proposed=prop)
            expect_fail(root, pfx, cfx, "market_value_not_positive",
                        f"F-1 TAM {kind}")

        # F-1f. TM end-to-end: il candidate con SOM negativo è respinto
        # PRIMA di qualsiasi mutazione canonica (nessuna allocazione ASS).
        pf6 = stage4_project(tmp, "f1f")
        prop = with_entry(market_proposed(), "reachable_share",
                          value=-0.1, display_value="-0.1 ratio")
        prop = with_entry(prop, "som_y1_revenue", value=-1000000,
                          display_value="-1000000 EUR")
        cf6 = kit.make_candidate(pf6, S4, structured=structured(),
                                 proposed=prop)
        before = kit.snapshot_canonical(pf6)
        register_before = kit.read_json(
            pf6 / "shared/assumptions-register.json")
        exit_code, out, err = kit.run_tm_cli(
            root, "apply", "--project", pf6, "--stage", S4,
            "--candidate", cf6)
        if exit_code != 1:
            raise TestFailure("F-1 TM apply with negative SOM must be "
                              f"rejected (exit 1), got {exit_code} "
                              f"(out {out.strip()!r} err {err.strip()!r})")
        result = kit.tm_result(out, "F-1 TM rejection")
        if result["result"] != "rejected":
            raise TestFailure(
                f"F-1 TM rejection: expected rejected, got {result}")
        if kit.snapshot_canonical(pf6) != before:
            raise TestFailure(
                "F-1 rejected apply mutated the canonical state")
        register_after = kit.read_json(
            pf6 / "shared/assumptions-register.json")
        if register_after != register_before:
            raise TestFailure("F-1 rejected apply touched the register: "
                              "no ASS allocation allowed on FAIL")
        journal = kit.read_json(kit.find_journals(pf6)[-1])
        if journal.get("state") != "rolled_back":
            raise TestFailure("F-1 rejected apply: journal must be terminal "
                              f"rolled_back, got {journal.get('state')!r}")
        if journal.get("pass_map"):
            raise TestFailure("F-1 rejected apply: pass_map must stay empty "
                              f"(no ASS consumed), got {journal['pass_map']}")

        # ------------------------- binding col transaction manager
        # apply a Stage 4: il journal deve includere il market validator.
        p12 = stage4_project(tmp, "m12")
        c12 = kit.make_candidate(p12, S4, structured=structured(),
                                 proposed=market_proposed())
        exit_code, out, err = kit.run_tm_cli(
            root, "apply", "--project", p12, "--stage", S4,
            "--candidate", c12)
        if exit_code != 0:
            raise TestFailure(f"TM apply stage 4 must pass, got {exit_code} "
                              f"(out {out.strip()!r} err {err.strip()!r})")
        journals = kit.find_journals(p12)
        if not journals:
            raise TestFailure("TM apply stage 4: journal missing")
        journal = kit.read_json(journals[-1])
        ran = {v["validator"] for v in journal.get("validation", [])}
        if "validate_market_arithmetic" not in ran:
            raise TestFailure(
                f"TM egress at stage 4 must run the market validator: {ran}")

        # impact sul canonico appena applicato: PASS senza candidate.
        expect_pass(root, p12, None, "impact on canonical", phase="impact")

        # corruzione del SOM canonico -> impact FAIL value_mismatch.
        register = kit.read_json(p12 / "shared/assumptions-register.json")
        for entry in register:
            if entry.get("variable") == "som_y1_revenue":
                entry["value"] = 123456
        kit.write_json(p12 / "shared/assumptions-register.json", register)
        exit_code, out, err = run_market(root, p12, None, phase="impact")
        if exit_code != 1:
            raise TestFailure("impact on drifted SOM must exit 1, got "
                              f"{exit_code} (out {out.strip()!r})")
        report = kit.parse_report(out, "impact drift")
        codes = [e["code"] for e in report["errors"]]
        if "value_mismatch" not in codes:
            raise TestFailure(f"impact drift: expected value_mismatch, "
                              f"got {codes}")

        # apply a Stage 1: il market validator NON gira (matrice di enforcement) e la
        # transazione passa.
        p13 = kit.make_project(tmp, name="m13",
                               current_stage="01_problem-and-need",
                               status="in_progress",
                               completed=["00_idea-discovery"])
        c13 = kit.make_candidate(p13, "01_problem-and-need",
                                 structured={"problem_statement": {
                                     "type": "cost", "intensity": "high"}})
        exit_code, out, err = kit.run_tm_cli(
            root, "apply", "--project", p13, "--stage",
            "01_problem-and-need", "--candidate", c13)
        if exit_code != 0:
            raise TestFailure(
                "TM apply stage 1 must skip non-applicable domain "
                f"validators, got {exit_code} (out {out.strip()!r} err "
                f"{err.strip()!r})")
        journal = kit.read_json(kit.find_journals(p13)[-1])
        ran = {v["validator"] for v in journal.get("validation", [])}
        if "validate_market_arithmetic" in ran:
            raise TestFailure(
                "TM egress at stage 1 must not run the market validator")

        # candidate invalido a Stage 4 -> TM rejected, canonico invariato.
        p14 = stage4_project(tmp, "m14")
        prop = with_entry(market_proposed(), "som_y1_revenue",
                          value=9000000, display_value="9000000 EUR")
        prop = with_entry(prop, "reachable_share", value=0.9,
                          display_value="0.9 ratio")
        c14 = kit.make_candidate(p14, S4, structured=structured(),
                                 proposed=prop)
        before = kit.snapshot_canonical(p14)
        exit_code, out, err = kit.run_tm_cli(
            root, "apply", "--project", p14, "--stage", S4,
            "--candidate", c14)
        if exit_code != 1:
            raise TestFailure("TM apply with ordering violation must be "
                              f"rejected, got {exit_code}")
        if kit.snapshot_canonical(p14) != before:
            raise TestFailure("rejected market apply mutated canonical state")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-MARKET-MATH market arithmetic + reconciliation + "
          "landscape enforcement")


if __name__ == "__main__":
    main()
