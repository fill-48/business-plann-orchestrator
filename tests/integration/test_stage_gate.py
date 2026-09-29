#!/usr/bin/env python3
"""T-GATE + T-GATE-CONDITIONS — validate_stage_gate.

T-GATE: un ingresso di stage non autorizzato produce exit != 0, nessuna
mutazione del progetto, project-status invariato e nessun output dello stage
non autorizzato. Copre anche conflict_awaiting_confirmation, riapertura di
stage approvati, not_applicable vietato, exit 2 (uso) ed exit 3 (canonico
corrotto).

T-GATE-CONDITIONS: una COND aperta con due_before_stage scaduta blocca
l'avanzamento; il confronto avviene per ordinale di stage: una COND dovuta a
uno stage successivo non blocca; resolved/waived non bloccano; uno stage
sconosciuto nel registro canonico è stato corrotto (exit 3).

Invoca il validator via CLI, esattamente come i workflow.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit


class TestFailure(AssertionError):
    pass


def gate(root, project, stage, phase, candidate=None):
    return kit.run_validator_cli(root, "validate_stage_gate", project=project,
                                 stage=stage, phase=phase, candidate=candidate)


def expect_fail(root, project, stage, phase, code, label, candidate=None):
    before = kit.snapshot_tree(project)
    exit_code, out, err = gate(root, project, stage, phase, candidate)
    if exit_code != 1:
        raise TestFailure(f"{label}: expected exit 1, got {exit_code} "
                          f"(stderr: {err.strip()!r})")
    report = kit.parse_report(out, label)
    if report["result"] != "FAIL":
        raise TestFailure(f"{label}: expected FAIL, got {report['result']}")
    codes = [e["code"] for e in report["errors"]]
    if code not in codes:
        raise TestFailure(f"{label}: expected error code {code}, got {codes}")
    if kit.snapshot_tree(project) != before:
        raise TestFailure(f"{label}: validator mutated the project")
    return report


def expect_pass(root, project, stage, phase, label, candidate=None):
    before = kit.snapshot_tree(project)
    exit_code, out, err = gate(root, project, stage, phase, candidate)
    if exit_code != 0:
        raise TestFailure(f"{label}: expected exit 0, got {exit_code} "
                          f"(out: {out.strip()!r} err: {err.strip()!r})")
    report = kit.parse_report(out, label)
    if report["result"] not in ("PASS", "WARNING"):
        raise TestFailure(f"{label}: unexpected result {report['result']}")
    if kit.snapshot_tree(project) != before:
        raise TestFailure(f"{label}: validator mutated the project")
    return report


def base_cond(**over):
    cond = {
        "id": "COND-001",
        "stage": "03_value-proposition",
        "description": "Validare pricing con interviste",
        "severity": "high",
        "owner": "founder",
        "validation_action": "3 interviste buyer",
        "due_before_stage": "04_market-and-competition",
        "resolution_status": "open",
    }
    cond.update(over)
    return cond


def run(root):
    if not (root / kit.VALIDATORS_REL / "validate_stage_gate.py").exists():
        raise TestFailure("missing validator: validate_stage_gate.py")

    with tempfile.TemporaryDirectory(prefix="bpo-gate-") as tmp:
        tmp = Path(tmp)

        # ------------------------------------------------------------ T-GATE
        # Unauthorized stage: 01 not completed, ingress to 02 must fail
        p1 = kit.make_project(tmp, name="p1")
        report = expect_fail(root, p1, "02_customer-segmentation", "ingress",
                             "stage_not_authorized", "T-GATE unauthorized")
        stage_dir = p1 / "02_customer-segmentation"
        if any(stage_dir.iterdir()):
            raise TestFailure(
                "T-GATE: unauthorized stage dir must stay without outputs")

        # Authorized successor passes
        expect_pass(root, p1, "01_problem-and-need", "ingress",
                    "T-GATE authorized ingress")

        # Predecessor completed but gate not approved*
        p2 = kit.make_project(tmp, name="p2", current_stage="00_idea-discovery",
                              status="needs_revision")
        expect_fail(root, p2, "01_problem-and-need", "ingress",
                    "predecessor_not_approved", "T-GATE predecessor gate")

        # Pending conflict blocks egress
        p3 = kit.make_project(tmp, name="p3",
                              current_stage="01_problem-and-need",
                              status="conflict_awaiting_confirmation")
        cand3 = kit.make_candidate(p3, "01_problem-and-need",
                                   structured={"problem_statement": "x"})
        expect_fail(root, p3, "01_problem-and-need", "egress",
                    "conflict_pending", "T-GATE conflict pending",
                    candidate=cand3)

        # Egress happy path (in_progress)
        p4 = kit.make_project(tmp, name="p4",
                              current_stage="01_problem-and-need",
                              status="in_progress")
        cand4 = kit.make_candidate(p4, "01_problem-and-need",
                                   structured={"problem_statement": "x"})
        expect_pass(root, p4, "01_problem-and-need", "egress",
                    "T-GATE egress in_progress", candidate=cand4)

        # Egress on the wrong stage (not the current one)
        expect_fail(root, p4, "02_customer-segmentation", "egress",
                    "stage_not_authorized", "T-GATE egress wrong stage",
                    candidate=cand4)

        # Approved stages are not reopened silently
        p5 = kit.make_project(
            tmp, name="p5", current_stage="01_problem-and-need",
            status="approved",
            completed=["00_idea-discovery", "01_problem-and-need"])
        expect_fail(root, p5, "01_problem-and-need", "ingress",
                    "stage_already_completed", "T-GATE reopen approved")
        expect_pass(root, p5, "02_customer-segmentation", "ingress",
                    "T-GATE next stage after approval")

        # not_applicable is forbidden for Stage 1-6
        p6 = kit.make_project(tmp, name="p6",
                              current_stage="01_problem-and-need",
                              status="not_applicable")
        cand6 = kit.make_candidate(p6, "01_problem-and-need",
                                   structured={"problem_statement": "x"})
        expect_fail(root, p6, "01_problem-and-need", "egress",
                    "invalid_state", "T-GATE not_applicable",
                    candidate=cand6)

        # Usage errors -> exit 2 (no report semantics)
        exit_code, _, _ = gate(root, p1, "01_problem-and-need", "sideways")
        if exit_code != 2:
            raise TestFailure(f"unknown phase must exit 2, got {exit_code}")
        exit_code, _, _ = gate(root, p1, "99_not-a-stage", "ingress")
        if exit_code != 2:
            raise TestFailure(f"unknown stage must exit 2, got {exit_code}")

        # Corrupted canonical state -> exit 3
        p7 = kit.make_project(tmp, name="p7")
        (p7 / "shared/project-status.md").write_text("no front matter\n",
                                                     encoding="utf-8")
        exit_code, _, _ = gate(root, p7, "01_problem-and-need", "ingress")
        if exit_code != 3:
            raise TestFailure(
                f"corrupted project-status must exit 3, got {exit_code}")

        # -------------------------------------------------- T-GATE-CONDITIONS
        completed = ["00_idea-discovery", "01_problem-and-need",
                     "02_customer-segmentation", "03_value-proposition"]

        def cond_project(name, cond):
            return kit.make_project(
                tmp, name=name, current_stage="03_value-proposition",
                status="approved_with_conditions", completed=completed,
                conditions=[cond])

        # Open COND due before the entered stage blocks (ordinal <=)
        p8 = cond_project("p8", base_cond())
        report = expect_fail(root, p8, "04_market-and-competition", "ingress",
                             "condition_due", "T-GATE-CONDITIONS open due")
        if "COND-001" not in report["affected_refs"]:
            raise TestFailure("condition_due must reference the COND id")

        # Open COND due at a later stage does not block (ordinal >)
        p9 = cond_project("p9", base_cond(
            due_before_stage="05_business-model"))
        expect_pass(root, p9, "04_market-and-competition", "ingress",
                    "T-GATE-CONDITIONS later due")

        # Resolved / waived do not block
        p10 = cond_project("p10", base_cond(resolution_status="resolved",
                                            resolved_by="DEC-002"))
        expect_pass(root, p10, "04_market-and-competition", "ingress",
                    "T-GATE-CONDITIONS resolved")
        p11 = cond_project("p11", base_cond(resolution_status="waived",
                                            resolved_by="DEC-003"))
        expect_pass(root, p11, "04_market-and-competition", "ingress",
                    "T-GATE-CONDITIONS waived")

        # Unknown stage folder in the canonical register -> corrupted state
        p12 = cond_project("p12", base_cond(
            due_before_stage="market-and-competition"))
        exit_code, _, _ = gate(root, p12, "04_market-and-competition",
                               "ingress")
        if exit_code != 3:
            raise TestFailure(
                "unknown due_before_stage in canonical register must exit 3, "
                f"got {exit_code}")

        # Open due COND blocks egress of the stage it was due before
        p13 = kit.make_project(
            tmp, name="p13", current_stage="04_market-and-competition",
            status="in_progress",
            completed=completed,
            conditions=[base_cond()])
        cand13 = kit.make_candidate(p13, "04_market-and-competition",
                                    structured={"market_model": "x"})
        expect_fail(root, p13, "04_market-and-competition", "egress",
                    "condition_due", "T-GATE-CONDITIONS egress due",
                    candidate=cand13)

        # ------------------------------ coerenza globale dello status
        def expect_exit3(project, stage, phase, label, candidate=None):
            exit_code, out, err = gate(root, project, stage, phase, candidate)
            if exit_code != 3:
                raise TestFailure(f"{label}: incoherent canonical status "
                                  f"must exit 3, got {exit_code} "
                                  f"(out {out.strip()!r})")

        # completed_stages con duplicati
        p14 = kit.make_project(
            tmp, name="p14", current_stage="01_problem-and-need",
            status="in_progress",
            completed=["00_idea-discovery", "00_idea-discovery"])
        expect_exit3(p14, "01_problem-and-need", "ingress",
                     "status coherence: duplicated completed_stages")

        # completed_stages fuori ordine
        p15 = kit.make_project(
            tmp, name="p15", current_stage="02_customer-segmentation",
            status="in_progress",
            completed=["01_problem-and-need", "00_idea-discovery"])
        expect_exit3(p15, "02_customer-segmentation", "ingress",
                     "status coherence: out-of-order completed_stages")

        # completed_stages non è un prefisso della pipeline (gap)
        p16 = kit.make_project(
            tmp, name="p16", current_stage="03_value-proposition",
            status="in_progress",
            completed=["00_idea-discovery", "02_customer-segmentation"])
        expect_exit3(p16, "03_value-proposition", "ingress",
                     "status coherence: non-prefix completed_stages")

        # current_stage futuro/incongruente: l'ingresso non passa più
        p17 = kit.make_project(
            tmp, name="p17", current_stage="05_business-model",
            status="in_progress", completed=["00_idea-discovery"])
        expect_exit3(p17, "01_problem-and-need", "ingress",
                     "status coherence: future current_stage")

        # gate approved* con current_stage non nei completed
        p18 = kit.make_project(
            tmp, name="p18", current_stage="01_problem-and-need",
            status="approved", completed=["00_idea-discovery"])
        expect_exit3(p18, "01_problem-and-need", "ingress",
                     "status coherence: approved but not completed")

        # stage già impostato (current == stage) con status in corso:
        # il re-ingresso non è ammesso
        p19 = kit.make_project(
            tmp, name="p19", current_stage="01_problem-and-need",
            status="in_progress", completed=["00_idea-discovery"])
        expect_fail(root, p19, "01_problem-and-need", "ingress",
                    "invalid_state",
                    "status coherence: re-ingress while in progress")

        # current == stage con status not_started è l'ingresso
        # legittimo (stage predisposto, non iniziato)
        p20 = kit.make_project(
            tmp, name="p20", current_stage="01_problem-and-need",
            status="not_started", completed=["00_idea-discovery"])
        expect_pass(root, p20, "01_problem-and-need", "ingress",
                    "status coherence: ingress from not_started")

        # COND canonica senza resolution_status: rifiutata, non ignorata
        p21 = kit.make_project(
            tmp, name="p21", current_stage="03_value-proposition",
            status="approved_with_conditions", completed=completed,
            conditions=[{k: v for k, v in base_cond().items()
                         if k != "resolution_status"}])
        expect_exit3(p21, "04_market-and-competition", "ingress",
                     "status coherence: condition without resolution_status")

        # COND con resolution_status fuori enum: rifiutata
        p22 = kit.make_project(
            tmp, name="p22", current_stage="03_value-proposition",
            status="approved_with_conditions", completed=completed,
            conditions=[base_cond(resolution_status="done")])
        expect_exit3(p22, "04_market-and-competition", "ingress",
                     "status coherence: condition with unknown "
                     "resolution_status")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-GATE + T-GATE-CONDITIONS stage gate enforcement")


if __name__ == "__main__":
    main()
