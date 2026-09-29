#!/usr/bin/env python3
"""Validator framework contract: CLI parsing, report/exit codes, common
config, ordinal stage order, overlay and ASS-*/P-ASS-* resolution.

Unit-level: imports _framework directly. The end-to-end CLI contract is
exercised again through the real validators in T-GATE / T-REFINT.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit


class TestFailure(AssertionError):
    pass


def expect_usage_error(fw, fn, label):
    try:
        fn()
    except fw.ValidatorUsageError as exc:
        if getattr(exc, "exit_code", None) != 2:
            raise TestFailure(f"{label}: usage error must carry exit 2")
        return
    raise TestFailure(f"{label}: expected ValidatorUsageError")


def run(root):
    try:
        fw = kit.load_module(root, kit.VALIDATORS_REL, "_framework")
    except FileNotFoundError as exc:
        raise TestFailure(str(exc))

    # --- common config and ordinal stage order ------------------------------
    config = fw.load_config(root / kit.CONFIG_REL)
    order = config.get("stage_order", {})
    if len(order) < 13:
        raise TestFailure("stage_order must map all canonical stage folders")
    for stage, ordinal in (("00_idea-discovery", 0),
                           ("04_market-and-competition", 4),
                           ("12_data-room", 12)):
        if fw.stage_ordinal(stage, config) != ordinal:
            raise TestFailure(f"stage_ordinal({stage}) != {ordinal}")
    try:
        fw.stage_ordinal("99_not-a-stage", config)
    except fw.ValidatorUsageError:
        pass
    else:
        raise TestFailure("unknown stage must raise a usage error")
    for name in ("validate_stage_gate", "validate_referential_integrity"):
        if name not in config.get("validators", {}):
            raise TestFailure(f"config must declare validator: {name}")
    # Registrazione del validator della funding request nella matrice. La
    # forma è quella di `validate_financial_output`: ordinali, mai nomi di
    # cartella, e `phases: [egress, impact]` come tutte e quattro le voci
    # dello Stage 10 — dichiarare solo `[egress]` escluderebbe il validator
    # dalla fase impact. Nessuno stub: il controllo generico sotto esige il
    # file reale.
    funding = config.get("validators", {}).get("validate_funding_request")
    if not isinstance(funding, dict):
        raise TestFailure(
            "config must declare validator: validate_funding_request")
    if [int(s) for s in funding.get("stages", [])] != [11]:
        raise TestFailure(
            "validate_funding_request must declare stages [11], got "
            f"{funding.get('stages')}")
    if list(funding.get("phases", [])) != ["egress", "impact"]:
        raise TestFailure(
            "validate_funding_request must declare phases [egress, impact], "
            f"got {funding.get('phases')}")
    if funding.get("introduced_in") != "0.5.0":
        raise TestFailure(
            "validate_funding_request must declare introduced_in 0.5.0, got "
            f"{funding.get('introduced_in')!r}")
    if "validate_funding_request" not in config.get("egress_required", []):
        raise TestFailure(
            "validate_funding_request is implemented within the release "
            "boundary and must appear in egress_required")
    # Registrazione del validator della Data Room nella matrice, nella STESSA
    # forma di `validate_funding_request`: ordinali, mai nomi di cartella,
    # `phases: [egress, impact]`, e presenza in `egress_required`. Nessuno
    # stub: il controllo generico sotto esige il file reale.
    data_room = config.get("validators", {}).get("validate_data_room")
    if not isinstance(data_room, dict):
        raise TestFailure("config must declare validator: validate_data_room")
    if [int(s) for s in data_room.get("stages", [])] != [12]:
        raise TestFailure(
            "validate_data_room must declare stages [12], got "
            f"{data_room.get('stages')}")
    if list(data_room.get("phases", [])) != ["egress", "impact"]:
        raise TestFailure(
            "validate_data_room must declare phases [egress, impact], got "
            f"{data_room.get('phases')}")
    if data_room.get("introduced_in") != "0.6.0":
        raise TestFailure(
            "validate_data_room must declare introduced_in 0.6.0, got "
            f"{data_room.get('introduced_in')!r}")
    if "validate_data_room" not in config.get("egress_required", []):
        raise TestFailure(
            "validate_data_room is implemented within the release boundary "
            "and must appear in egress_required")
    # Registrazione del validator del documento finale nella matrice, nella
    # STESSA forma di `validate_data_room`: ordinali, mai nomi di cartella,
    # `phases: [egress, impact]`, e presenza in `egress_required`. Nessuno
    # stub: il controllo generico sotto esige il file reale.
    document = config.get("validators", {}).get("validate_document_generation")
    if not isinstance(document, dict):
        raise TestFailure(
            "config must declare validator: validate_document_generation")
    if [int(s) for s in document.get("stages", [])] != [13]:
        raise TestFailure(
            "validate_document_generation must declare stages [13], got "
            f"{document.get('stages')}")
    if list(document.get("phases", [])) != ["egress", "impact"]:
        raise TestFailure(
            "validate_document_generation must declare phases [egress, "
            f"impact], got {document.get('phases')}")
    if document.get("introduced_in") != "0.7.0":
        raise TestFailure(
            "validate_document_generation must declare introduced_in 0.7.0, "
            f"got {document.get('introduced_in')!r}")
    if "validate_document_generation" not in config.get("egress_required",
                                                        []):
        raise TestFailure(
            "validate_document_generation is implemented within the release "
            "boundary and must appear in egress_required")
    if not (root / kit.VALIDATORS_REL /
            "validate_document_generation.py").is_file():
        raise TestFailure(
            "validate_document_generation is declared but its file is "
            "missing: no executable stub is allowed")
    egress_required = config.get("egress_required", [])
    # I due validator di framework restano obbligatori per ogni stage; ogni
    # altro validator in egress_required deve essere dichiarato nella
    # matrice con la propria applicabilità per stage (un domain validator
    # entra nella lista solo se implementato davvero, con file e matrice
    # presenti — niente stub).
    for name in ("validate_stage_gate", "validate_referential_integrity"):
        if name not in egress_required:
            raise TestFailure(f"egress_required must include {name}")
    for name in egress_required:
        spec = config.get("validators", {}).get(name)
        if not isinstance(spec, dict) or "stages" not in spec:
            raise TestFailure(
                f"egress_required validator {name} must be declared in the "
                "config matrix with explicit stages")
        script = root / kit.VALIDATORS_REL / f"{name}.py"
        if not script.is_file():
            raise TestFailure(
                f"egress_required validator {name} has no implementation "
                "(no stub allowed)")
    expect_usage_error(
        fw, lambda: fw.load_config(root / "does-not-exist.json"),
        "missing config file")

    # --- CLI parsing contract ------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="bpo-fw-") as tmp:
        project = kit.make_project(tmp)
        candidate = kit.make_candidate(project, "01_problem-and-need")

        def parse(args):
            return fw.parse_args(args, "validate_stage_gate")

        good = parse(["--project", str(project), "--stage",
                      "01_problem-and-need", "--phase", "ingress"])
        if good.phase != "ingress":
            raise TestFailure("parse_args lost the phase")
        expect_usage_error(fw, lambda: parse(
            ["--project", str(project), "--stage", "01_problem-and-need"]),
            "missing --phase")
        expect_usage_error(fw, lambda: parse(
            ["--project", str(project), "--stage", "01_problem-and-need",
             "--phase", "sideways"]), "unknown --phase")
        expect_usage_error(fw, lambda: parse(
            ["--project", str(tmp) + "/missing", "--stage",
             "01_problem-and-need", "--phase", "ingress"]),
            "nonexistent project")
        expect_usage_error(fw, lambda: parse(
            ["--project", str(project), "--stage", "01_problem-and-need",
             "--phase", "egress"]), "egress without --candidate")
        expect_usage_error(fw, lambda: parse(
            ["--project", str(project), "--candidate", str(candidate),
             "--stage", "01_problem-and-need", "--phase", "ingress"]),
            "ingress with --candidate (no P-ASS-* admitted)")

        # --- report semantics ------------------------------------------------
        report = fw.Report("validate_stage_gate", "01_problem-and-need",
                           "ingress")
        if report.result != "PASS" or report.exit_code != 0:
            raise TestFailure("empty report must be PASS/exit 0")
        report.add_warning("not_yet_required", ref="ASS-060", message="later")
        if report.result != "WARNING" or report.exit_code != 0:
            raise TestFailure("warning-only report must be WARNING/exit 0")
        report.add_error("missing_required", ref="ASS-001", message="due")
        if report.result != "FAIL" or report.exit_code != 1:
            raise TestFailure("errors must force FAIL/exit 1")
        doc = json.loads(report.to_json())
        for key in ("result", "validator", "stage", "phase", "errors",
                    "warnings", "affected_refs"):
            if key not in doc:
                raise TestFailure(f"report JSON missing {key}")
        if doc["errors"][0]["code"] != "missing_required":
            raise TestFailure("error entries must carry their code")
        if "ASS-001" not in doc["affected_refs"]:
            raise TestFailure("affected_refs must collect touched ids")

        # --- project state + front matter ------------------------------------
        state = fw.ProjectState(project, config)
        if state.status["current_stage"] != "00_idea-discovery":
            raise TestFailure("front matter current_stage not parsed")
        if state.status["completed_stages"] != ["00_idea-discovery"]:
            raise TestFailure("front matter completed_stages not parsed")
        if state.status["status"] != "approved":
            raise TestFailure("front matter status not parsed")

        # fixture-format front matter (multi-line arrays) must parse too.
        # Invariante durevole sulla demo (lo stage raggiunto può cambiare):
        # il front matter della demo parsa, usa uno stage canonico ed è
        # semanticamente coerente.
        fixture_status = fw.parse_front_matter(
            (root / "examples/fictional-startup/shared/project-status.md")
            .read_text(encoding="utf-8"))
        fw.stage_ordinal(fixture_status["current_stage"], config)
        fw.validate_status_coherence(fixture_status, config)
        if "00_idea-discovery" not in fixture_status["completed_stages"]:
            raise TestFailure("fixture front matter not parsed")
        if not fixture_status["pending_stages"]:
            raise TestFailure("fixture multi-line array not parsed")

        # --- overlay and reference resolution --------------------------------
        kit.write_json(candidate / "proposed-assumptions.json", [
            {"id": "P-ASS-001", "category": "market", "statement": "p1",
             "validation_status": "unvalidated"},
            {"id": "P-ASS-002", "category": "market", "statement": "p2",
             "validation_status": "unvalidated"},
        ])
        overlay = fw.build_overlay(state, candidate)
        if fw.resolve_ref("ASS-001", overlay) is None:
            raise TestFailure("canonical ASS-001 must resolve via overlay")
        if fw.resolve_ref("P-ASS-002", overlay) is None:
            raise TestFailure("candidate P-ASS-002 must resolve via overlay")
        if fw.resolve_ref("P-ASS-999", overlay) is not None:
            raise TestFailure("unknown P-ASS must not resolve")
        canonical_only = fw.build_overlay(state, None)
        if fw.resolve_ref("P-ASS-001", canonical_only) is not None:
            raise TestFailure("without candidate no P-ASS may resolve")

        # duplicate proposed ids are a candidate fault
        kit.write_json(candidate / "proposed-assumptions.json", [
            {"id": "P-ASS-001", "statement": "a"},
            {"id": "P-ASS-001", "statement": "b"},
        ])
        try:
            fw.build_overlay(state, candidate)
        except fw.CandidateError as exc:
            if getattr(exc, "exit_code", None) != 1:
                raise TestFailure("candidate fault must map to exit 1")
        else:
            raise TestFailure("duplicate P-ASS ids must be a candidate fault")

        # --- corrupted canonical state -> exit 3 ------------------------------
        (project / "shared/assumptions-register.json").write_text(
            "{not json", encoding="utf-8")
        try:
            fw.ProjectState(project, config)
        except fw.CanonicalStateError as exc:
            if getattr(exc, "exit_code", None) != 3:
                raise TestFailure("corrupted canonical state must carry exit 3")
        else:
            raise TestFailure("corrupted canonical register must raise")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: validator framework contract")


if __name__ == "__main__":
    main()
