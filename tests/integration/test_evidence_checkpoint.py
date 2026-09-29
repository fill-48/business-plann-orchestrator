#!/usr/bin/env python3
"""T-EVIDENCE-CHECKPOINT — checkpoint evidenze tra Stage 3 e Stage 4.

Regola vincolante: uno Stage 3 fondato solo su founder assumptions /
model estimate / missing_information non può essere approvato; al massimo
approved_with_conditions con una COND che porti validation_action, owner e
due_before_stage. Enforced da validate_stage_gate in fase egress leggendo le
classi di evidenza del value-proposition (structured-output.json del
candidate).

Il validator resta puro e read-only; il checkpoint non si applica agli altri
stage. Invocazione via CLI, esattamente come i workflow.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit


class TestFailure(AssertionError):
    pass


STAGE3 = "03_value-proposition"
COMPLETED_THROUGH_2 = ["00_idea-discovery", "01_problem-and-need",
                       "02_customer-segmentation"]


def gate(root, project, stage, phase, candidate=None):
    return kit.run_validator_cli(root, "validate_stage_gate", project=project,
                                 stage=stage, phase=phase, candidate=candidate)


def proof_point(classification, refs=None, claim="riduce il costo del 30%"):
    entry = {"claim": claim, "evidence_classification": classification}
    if refs is not None:
        entry["evidence_refs"] = refs
    return entry


def vp_structured(proof_points):
    return {
        "value_proposition": {
            "id": "VP-001",
            "mapping": [
                {"pain": "processo manuale lento",
                 "reliever": "automazione del flusso"},
            ],
            "proof_points": proof_points,
        }
    }


def checkpoint_cond(**over):
    cond = {
        "id": "COND-101",
        "stage": STAGE3,
        "description": "Value proposition fondata solo su assunzioni founder",
        "severity": "high",
        "owner": "founder",
        "validation_action": "5 interviste buyer con test di pricing",
        "due_before_stage": "04_market-and-competition",
        "resolution_status": "open",
    }
    cond.update(over)
    return cond


def stage3_project(tmp, name, evidence=None, conditions=None):
    return kit.make_project(
        tmp, name=name, current_stage=STAGE3, status="in_progress",
        completed=COMPLETED_THROUGH_2,
        evidence=evidence if evidence is not None else [
            {"id": "EVD-001",
             "statement": "Report di settore: costo medio processo 40k/anno",
             "classification": "external_source",
             "confidence": "medium", "relevance": "high",
             "affected_assumptions": []}],
        conditions=conditions)


def expect_exit(root, project, candidate, expected_exit, label):
    before = kit.snapshot_tree(project)
    exit_code, out, err = gate(root, project, STAGE3, "egress",
                               candidate=candidate)
    if exit_code != expected_exit:
        raise TestFailure(f"{label}: expected exit {expected_exit}, got "
                          f"{exit_code} (out {out.strip()!r} "
                          f"err {err.strip()!r})")
    report = kit.parse_report(out, label)
    if kit.snapshot_tree(project) != before:
        raise TestFailure(f"{label}: validator mutated the project")
    return report


def expect_checkpoint_fail(root, project, candidate, code, label):
    report = expect_exit(root, project, candidate, 1, label)
    codes = [e["code"] for e in report["errors"]]
    if code not in codes:
        raise TestFailure(f"{label}: expected error code {code}, got {codes}")
    return report


def run(root):
    with tempfile.TemporaryDirectory(prefix="bpo-evcheck-") as tmp:
        tmp = Path(tmp)

        # 1. Proof point con evidenza validata (external_source + EVD ref):
        #    il checkpoint passa senza warning né errori.
        p1 = stage3_project(tmp, "p1")
        cand1 = kit.make_candidate(p1, STAGE3, structured=vp_structured([
            proof_point("external_source", refs=["EVD-001"]),
            proof_point("founder_assumption"),
        ]))
        report = expect_exit(root, p1, cand1, 0, "checkpoint validated")
        if report["result"] != "PASS":
            raise TestFailure("checkpoint validated: expected PASS, got "
                              f"{report['result']}")

        # 2. Solo founder_assumption/model_estimate, nessuna COND che copra il
        #    checkpoint: FAIL (Stage 3 non approvabile, checkpoint evidenze).
        p2 = stage3_project(tmp, "p2")
        cand2 = kit.make_candidate(p2, STAGE3, structured=vp_structured([
            proof_point("founder_assumption"),
            proof_point("model_estimate"),
        ]))
        expect_checkpoint_fail(root, p2, cand2, "evidence_checkpoint",
                               "checkpoint only-assumptions")

        # 3. Solo assunzioni ma con COND proposta nel candidate (owner,
        #    validation_action, due_before_stage a valle): WARNING, exit 0 —
        #    percorso approved_with_conditions.
        p3 = stage3_project(tmp, "p3")
        cand3 = kit.make_candidate(p3, STAGE3, structured=vp_structured([
            proof_point("founder_assumption"),
        ]))
        kit.write_json(cand3 / "proposed-conditions.json", [checkpoint_cond()])
        report = expect_exit(root, p3, cand3, 0, "checkpoint with COND")
        if report["result"] != "WARNING":
            raise TestFailure("checkpoint with COND: expected WARNING, got "
                              f"{report['result']}")
        warn_codes = [w["code"] for w in report["warnings"]]
        if "evidence_unvalidated" not in warn_codes:
            raise TestFailure("checkpoint with COND: expected warning "
                              f"evidence_unvalidated, got {warn_codes}")

        # 4. COND proposta senza validation_action: non copre il checkpoint.
        p4 = stage3_project(tmp, "p4")
        cand4 = kit.make_candidate(p4, STAGE3, structured=vp_structured([
            proof_point("founder_assumption"),
        ]))
        kit.write_json(cand4 / "proposed-conditions.json",
                       [checkpoint_cond(validation_action="")])
        expect_checkpoint_fail(root, p4, cand4, "evidence_checkpoint",
                               "COND without validation_action")

        # 4b. COND proposta con due_before_stage non a valle dello Stage 3:
        #     non copre il checkpoint (deve vincolare uno stage successivo).
        p4b = stage3_project(tmp, "p4b")
        cand4b = kit.make_candidate(p4b, STAGE3, structured=vp_structured([
            proof_point("model_estimate"),
        ]))
        kit.write_json(cand4b / "proposed-conditions.json",
                       [checkpoint_cond(
                           due_before_stage="02_customer-segmentation")])
        expect_checkpoint_fail(root, p4b, cand4b, "evidence_checkpoint",
                               "COND due upstream")

        # 5. Classe validata senza evidence_refs: claim non sostanziato.
        p5 = stage3_project(tmp, "p5")
        cand5 = kit.make_candidate(p5, STAGE3, structured=vp_structured([
            proof_point("external_source"),
        ]))
        expect_checkpoint_fail(root, p5, cand5, "invalid",
                               "validated class without refs")

        # 6. Nessun proof point: dato dovuto mancante in egress Stage 3.
        p6 = stage3_project(tmp, "p6")
        cand6 = kit.make_candidate(p6, STAGE3, structured=vp_structured([]))
        expect_checkpoint_fail(root, p6, cand6, "missing_required",
                               "no proof points")

        p6b = stage3_project(tmp, "p6b")
        cand6b = kit.make_candidate(p6b, STAGE3,
                                    structured={"value_proposition": {}})
        expect_checkpoint_fail(root, p6b, cand6b, "missing_required",
                               "no proof_points key")

        p6c = stage3_project(tmp, "p6c")
        cand6c = kit.make_candidate(p6c, STAGE3)
        expect_checkpoint_fail(root, p6c, cand6c, "missing_required",
                               "no structured output")

        # 7. Classe di evidenza fuori dal vocabolario delle 6 classi.
        p7 = stage3_project(tmp, "p7")
        cand7 = kit.make_candidate(p7, STAGE3, structured=vp_structured([
            proof_point("gut_feeling"),
        ]))
        expect_checkpoint_fail(root, p7, cand7, "invalid",
                               "unknown evidence class")

        # 8. Il checkpoint non si applica agli altri stage: egress di Stage 1
        #    senza proof point passa (nessun errore checkpoint).
        p8 = kit.make_project(tmp, name="p8",
                              current_stage="01_problem-and-need",
                              status="in_progress")
        cand8 = kit.make_candidate(p8, "01_problem-and-need",
                                   structured={"problem_statement": {
                                       "type": "cost", "intensity": "high"}})
        report = expect_exit_stage(root, p8, cand8, "01_problem-and-need",
                                   0, "no checkpoint on stage 1")
        if report["result"] != "PASS":
            raise TestFailure("no checkpoint on stage 1: expected PASS, got "
                              f"{report['result']}")

        # 9. missing_information conta come non validata: da sola richiede
        #    una COND, non un'approvazione piena.
        p9 = stage3_project(tmp, "p9")
        cand9 = kit.make_candidate(p9, STAGE3, structured=vp_structured([
            proof_point("missing_information"),
        ]))
        expect_checkpoint_fail(root, p9, cand9, "evidence_checkpoint",
                               "missing_information alone")

        # 10. COND canonica open già registrata (resume): copre il checkpoint
        #     senza duplicare la proposta nel candidate.
        p10 = stage3_project(tmp, "p10", conditions=[checkpoint_cond()])
        cand10 = kit.make_candidate(p10, STAGE3, structured=vp_structured([
            proof_point("founder_assumption"),
        ]))
        report = expect_exit(root, p10, cand10, 0, "canonical COND covers")
        if report["result"] != "WARNING":
            raise TestFailure("canonical COND covers: expected WARNING, got "
                              f"{report['result']}")


def expect_exit_stage(root, project, candidate, stage, expected_exit, label):
    before = kit.snapshot_tree(project)
    exit_code, out, err = gate(root, project, stage, "egress",
                               candidate=candidate)
    if exit_code != expected_exit:
        raise TestFailure(f"{label}: expected exit {expected_exit}, got "
                          f"{exit_code} (out {out.strip()!r} "
                          f"err {err.strip()!r})")
    report = kit.parse_report(out, label)
    if kit.snapshot_tree(project) != before:
        raise TestFailure(f"{label}: validator mutated the project")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-EVIDENCE-CHECKPOINT evidence gate on Stage 3 egress")


if __name__ == "__main__":
    main()
