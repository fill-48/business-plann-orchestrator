#!/usr/bin/env python3
"""T-REFINT — validate_referential_integrity (riferimenti e derivation).

Verifica: risoluzione dei riferimenti ASS-*/EVD-* canonici e P-ASS-*
transaction-local nell'overlay candidate ⊕ canonico; P-ASS-* non risolvibile
-> FAIL; nessun duplicato numerico; nessun P-ASS-* nei file canonici;
integrità delle derivation proposte (formula whitelist, nomi dichiarati in
variables) con invalid_formula -> exit 1. Validator puro (nessuna mutazione).
"""
import argparse
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit


class TestFailure(AssertionError):
    pass


def refint(root, project, candidate, phase="egress",
           stage="01_problem-and-need"):
    return kit.run_validator_cli(
        root, "validate_referential_integrity", project=project, stage=stage,
        phase=phase, candidate=candidate)


def expect_fail(root, project, candidate, code, label, phase="egress"):
    before = kit.snapshot_tree(project)
    exit_code, out, err = refint(root, project, candidate, phase)
    if exit_code != 1:
        raise TestFailure(f"{label}: expected exit 1, got {exit_code} "
                          f"(out: {out.strip()!r} err: {err.strip()!r})")
    report = kit.parse_report(out, label)
    codes = [e["code"] for e in report["errors"]]
    if code not in codes:
        raise TestFailure(f"{label}: expected error code {code}, got {codes}")
    if kit.snapshot_tree(project) != before:
        raise TestFailure(f"{label}: validator mutated the project")
    return report


def good_proposed():
    return [
        {
            "id": "P-ASS-001",
            "category": "market",
            "variable": "som_y1_revenue",
            "statement": "Ricavo SOM Y1",
            "kind": "derived",
            "unit": "EUR",
            "currency": "EUR",
            "period": "Y1",
            "scenario": "base",
            "derivation": {
                "formula": "customers * arpa",
                "variables": {"customers": "P-ASS-002", "arpa": "ASS-002"},
                "method": "bottom_up",
            },
            "value": 120000,
            "evidence_classification": "model_estimate",
            "validation_status": "unvalidated",
        },
        {
            "id": "P-ASS-002",
            "category": "market",
            "variable": "customers_y1",
            "statement": "Clienti Y1",
            "kind": "primary",
            "unit": "count",
            "value": 100,
            "validation_status": "unvalidated",
        },
    ]


def good_structured():
    return {
        "problem_statement": {
            "id": "SEG-001",
            "problem_ref": "ASS-001",
            "evidence_refs": ["EVD-001"],
            "revenue_ref": "P-ASS-001",
        }
    }


def make_fixture(tmp, name, structured=None, proposed=None, assumptions=None,
                 canonical_extra=None):
    project = kit.make_project(
        tmp, name=name, current_stage="01_problem-and-need",
        status="in_progress", assumptions=assumptions,
        evidence=[{"id": "EVD-001", "statement": "Intervista pilota"}])
    if canonical_extra:
        for rel, data in canonical_extra.items():
            kit.write_json(project / rel, data)
    candidate = kit.make_candidate(
        project, "01_problem-and-need",
        structured=good_structured() if structured is None else structured,
        proposed=good_proposed() if proposed is None else proposed)
    return project, candidate


def run(root):
    if not (root / kit.VALIDATORS_REL /
            "validate_referential_integrity.py").exists():
        raise TestFailure("missing validator: validate_referential_integrity.py")

    with tempfile.TemporaryDirectory(prefix="bpo-refint-") as tmp:
        tmp = Path(tmp)

        # Happy path: ASS/EVD canonici + P-ASS del candidate risolti
        p1, c1 = make_fixture(tmp, "p1")
        before = kit.snapshot_tree(p1)
        exit_code, out, err = refint(root, p1, c1)
        if exit_code != 0:
            raise TestFailure(f"happy path: expected exit 0, got {exit_code} "
                              f"(out: {out.strip()!r} err: {err.strip()!r})")
        kit.parse_report(out, "happy path")
        if kit.snapshot_tree(p1) != before:
            raise TestFailure("happy path: validator mutated the project")
        # candidate phase works too
        exit_code, out, _ = refint(root, p1, c1, phase="candidate")
        if exit_code != 0:
            raise TestFailure("candidate phase happy path must pass")

        # P-ASS-* non risolvibile nel candidate -> FAIL
        structured = good_structured()
        structured["problem_statement"]["revenue_ref"] = "P-ASS-999"
        p2, c2 = make_fixture(tmp, "p2", structured=structured)
        expect_fail(root, p2, c2, "unresolved_ref", "unresolved P-ASS")

        # ASS-* canonico inesistente -> FAIL
        structured = good_structured()
        structured["problem_statement"]["problem_ref"] = "ASS-999"
        p3, c3 = make_fixture(tmp, "p3", structured=structured)
        expect_fail(root, p3, c3, "unresolved_ref", "unresolved ASS")

        # EVD-* inesistente -> FAIL
        structured = good_structured()
        structured["problem_statement"]["evidence_refs"] = ["EVD-999"]
        p4, c4 = make_fixture(tmp, "p4", structured=structured)
        expect_fail(root, p4, c4, "unresolved_ref", "unresolved EVD")

        # P-ASS duplicato nel candidate -> FAIL (nessun duplicato numerico)
        proposed = good_proposed()
        proposed[1]["id"] = "P-ASS-001"
        p5, c5 = make_fixture(tmp, "p5", proposed=proposed)
        expect_fail(root, p5, c5, "invalid", "duplicate P-ASS in candidate")

        # Id canonico duplicato -> stato canonico corrotto (exit 3)
        dup = [kit.base_assumption(1), kit.base_assumption(1)]
        p6, c6 = make_fixture(tmp, "p6", assumptions=dup)
        exit_code, _, _ = refint(root, p6, c6)
        if exit_code != 3:
            raise TestFailure(
                f"duplicate canonical id must exit 3, got {exit_code}")

        # P-ASS-* presente nei file canonici -> FAIL
        p7, c7 = make_fixture(tmp, "p7", canonical_extra={
            "01_problem-and-need/structured-output.json":
                {"leftover": {"ref": "P-ASS-001"}}})
        expect_fail(root, p7, c7, "pass_in_canonical",
                    "P-ASS leaked into canonical files")

        # Formula con nodo non ammesso -> invalid_formula, exit 1 (mai 2)
        proposed = good_proposed()
        proposed[0]["derivation"]["formula"] = "min(customers, arpa)"
        p8, c8 = make_fixture(tmp, "p8", proposed=proposed)
        expect_fail(root, p8, c8, "invalid_formula",
                    "non-whitelisted formula node")

        # Identificatore non dichiarato in variables -> invalid_formula
        proposed = good_proposed()
        proposed[0]["derivation"]["formula"] = "customers * undeclared"
        p9, c9 = make_fixture(tmp, "p9", proposed=proposed)
        expect_fail(root, p9, c9, "invalid_formula",
                    "undeclared identifier in formula")

        # Variabile di derivation che non risolve -> FAIL
        proposed = good_proposed()
        proposed[0]["derivation"]["variables"]["arpa"] = "ASS-777"
        p10, c10 = make_fixture(tmp, "p10", proposed=proposed)
        expect_fail(root, p10, c10, "unresolved_ref",
                    "derivation variable unresolved")

        # Candidate JSON corrotto -> difetto del candidate (exit 1)
        p11, c11 = make_fixture(tmp, "p11")
        (c11 / "structured-output.json").write_text("{broken",
                                                    encoding="utf-8")
        expect_fail(root, p11, c11, "invalid", "corrupted candidate JSON")

        # ---------------------------------------- forma canonica: alias e cicli
        # Alias numerico nel registro canonico -> stato corrotto (exit 3)
        alias = [kit.base_assumption(1)]
        alias[0]["id"] = "ASS-0001"
        p12, c12 = make_fixture(tmp, "p12", assumptions=alias)
        exit_code, _, _ = refint(root, p12, c12)
        if exit_code != 3:
            raise TestFailure(
                f"canonical alias ASS-0001 must exit 3, got {exit_code}")

        # Alias numerico nell'id proposto -> difetto candidate (exit 1)
        proposed = good_proposed()
        proposed[1]["id"] = "P-ASS-0002"
        proposed[0]["derivation"]["variables"]["customers"] = "P-ASS-0002"
        p13, c13 = make_fixture(tmp, "p13", proposed=proposed)
        exit_code, out, _ = refint(root, p13, c13)
        if exit_code != 1:
            raise TestFailure(
                f"P-ASS-0002 alias must exit 1, got {exit_code}")

        # Alias numerico come riferimento -> FAIL non_canonical_id
        structured = good_structured()
        structured["problem_statement"]["problem_ref"] = "ASS-0001"
        p14, c14 = make_fixture(tmp, "p14", structured=structured)
        expect_fail(root, p14, c14, "non_canonical_id",
                    "alias reference ASS-0001")

        # Id canonici lunghi accettati (ASS-1000 non è un alias)
        big = [kit.base_assumption(1), kit.base_assumption(2),
               kit.base_assumption(3)]
        big[2]["id"] = "ASS-1000"
        big[2]["variable"] = "var_1000"
        structured = good_structured()
        structured["problem_statement"]["big_ref"] = "ASS-1000"
        proposed = good_proposed()
        p15, c15 = make_fixture(tmp, "p15", structured=structured,
                                assumptions=big, proposed=proposed)
        exit_code, out, err = refint(root, p15, c15)
        if exit_code != 0:
            raise TestFailure(f"ASS-1000 must be accepted, got {exit_code} "
                              f"(out {out.strip()!r})")

        # Self-cycle nella derivation proposta
        proposed = good_proposed()
        proposed[0]["derivation"]["formula"] = "self_ref"
        proposed[0]["derivation"]["variables"] = {"self_ref": "P-ASS-001"}
        p16, c16 = make_fixture(tmp, "p16", proposed=proposed)
        expect_fail(root, p16, c16, "circular_derivation", "self cycle")

        # Ciclo diretto P-ASS-001 <-> P-ASS-002
        proposed = good_proposed()
        proposed[1]["kind"] = "derived"
        proposed[1]["currency"] = "EUR"
        proposed[1]["period"] = "Y1"
        proposed[1]["scenario"] = "base"
        proposed[1]["evidence_classification"] = "model_estimate"
        proposed[1]["derivation"] = {
            "formula": "rev", "variables": {"rev": "P-ASS-001"},
            "method": "bottom_up"}
        p17, c17 = make_fixture(tmp, "p17", proposed=proposed)
        expect_fail(root, p17, c17, "circular_derivation", "direct cycle")

        # Ciclo indiretto a tre nodi
        proposed = good_proposed()
        proposed[1]["kind"] = "derived"
        proposed[1]["derivation"] = {
            "formula": "c", "variables": {"c": "P-ASS-003"},
            "method": "bottom_up"}
        proposed.append({
            "id": "P-ASS-003", "category": "market", "statement": "c",
            "kind": "derived", "unit": "count", "value": 5,
            "validation_status": "unvalidated",
            "derivation": {"formula": "a",
                           "variables": {"a": "P-ASS-001"},
                           "method": "bottom_up"}})
        p18, c18 = make_fixture(tmp, "p18", proposed=proposed)
        expect_fail(root, p18, c18, "circular_derivation", "indirect cycle")

        # Ciclo interamente canonico -> stato corrotto (exit 3)
        canon_cycle = [kit.base_assumption(1), kit.base_assumption(2)]
        canon_cycle[0]["derivation"] = {
            "formula": "x", "variables": {"x": "ASS-002"},
            "method": "bottom_up"}
        canon_cycle[1]["derivation"] = {
            "formula": "y", "variables": {"y": "ASS-001"},
            "method": "bottom_up"}
        p19, c19 = make_fixture(tmp, "p19", assumptions=canon_cycle)
        exit_code, _, _ = refint(root, p19, c19)
        if exit_code != 3:
            raise TestFailure(
                f"canonical-only cycle must exit 3, got {exit_code}")

        # Ciclo misto ASS-* / P-ASS-*: il canonico punta a un P-ASS (già
        # errore) e il candidate chiude il ciclo -> FAIL (exit 1)
        mixed = [kit.base_assumption(1), kit.base_assumption(2)]
        mixed[1]["derivation"] = {
            "formula": "v", "variables": {"v": "P-ASS-001"},
            "method": "bottom_up"}
        proposed = good_proposed()
        proposed[0]["derivation"]["formula"] = "w"
        proposed[0]["derivation"]["variables"] = {"w": "ASS-002"}
        p20, c20 = make_fixture(tmp, "p20", assumptions=mixed,
                                proposed=proposed)
        report = expect_fail(root, p20, c20, "circular_derivation",
                             "mixed ASS/P-ASS cycle")
        codes = {e["code"] for e in report["errors"]}
        if "pass_in_canonical" not in codes:
            raise TestFailure(
                "mixed cycle must also flag the P-ASS in the canonical "
                f"register, got {codes}")

        # Ratio proposto fuori [0,1] fermato dal percorso di integrity
        proposed = good_proposed()
        proposed[1]["unit"] = "ratio"
        proposed[1]["value"] = 1.5
        p21, c21 = make_fixture(tmp, "p21", proposed=proposed)
        expect_fail(root, p21, c21, "ratio_out_of_bounds",
                    "proposed ratio above 1")
        proposed = good_proposed()
        proposed[1]["unit"] = "ratio"
        proposed[1]["value"] = -0.2
        p22, c22 = make_fixture(tmp, "p22", proposed=proposed)
        expect_fail(root, p22, c22, "ratio_out_of_bounds",
                    "proposed negative ratio")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-REFINT referential integrity enforcement")


if __name__ == "__main__":
    main()
