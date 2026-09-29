#!/usr/bin/env python3
"""T-STAGE-CHAIN-1-3 — gate Stage 1-3 verdi sulla pipeline reale.

Percorre la catena esattamente come i workflow 02-04: ingress gate →
governance-status in_progress → candidate stage-bounded → validator egress →
transaction_manager advance-stage. Verifica:

- catena felice 01→02→03 con evidenza validata: gate verdi, stato avanzato,
  P-ASS-* allocati, nessun P-ASS nel canonico;
- checkpoint evidenze end-to-end: Stage 3 solo-assunzioni senza COND → egress
  FAIL e advance rejected senza mutazioni canoniche; con COND proposta →
  approved_with_conditions applicato, COND open nel registro canonico e
  ingresso a Stage 4 bloccato da condition_due finché la COND resta open.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit


class TestFailure(AssertionError):
    pass


S1 = "01_problem-and-need"
S2 = "02_customer-segmentation"
S3 = "03_value-proposition"
S4 = "04_market-and-competition"

EVIDENCE = [{
    "id": "EVD-001",
    "statement": "Report di settore: costo del processo manuale 40k/anno",
    "classification": "external_source",
    "confidence": "medium", "relevance": "high",
    "affected_assumptions": [],
}]


def p_ass(idx, category, variable, statement, value, unit="EUR"):
    return {
        "id": f"P-ASS-{idx:03d}",
        "category": category,
        "variable": variable,
        "statement": statement,
        "value": value,
        "display_value": f"{value} {unit}",
        "unit": unit,
        "source": "Founder interview",
        "owner": "founder",
        "confidence": "low",
        "validation_status": "unvalidated",
        "evidence_classification": "founder_assumption",
        "affected_sections": [],
        "last_updated": "2026-07-16",
        "previous_values": [],
    }


def checkpoint_cond():
    return {
        "id": "COND-101",
        "stage": S3,
        "description": "VP fondata solo su assunzioni founder",
        "severity": "high",
        "owner": "founder",
        "validation_action": "5 interviste buyer con test di pricing",
        "due_before_stage": S4,
        "resolution_status": "open",
    }


def gate(root, project, stage, phase, candidate=None):
    return kit.run_validator_cli(root, "validate_stage_gate", project=project,
                                 stage=stage, phase=phase,
                                 candidate=candidate)


def refint(root, project, stage, phase, candidate):
    return kit.run_validator_cli(root, "validate_referential_integrity",
                                 project=project, stage=stage, phase=phase,
                                 candidate=candidate)


def expect_zero(step, exit_code, out, err):
    if exit_code != 0:
        raise TestFailure(f"{step}: expected exit 0, got {exit_code} "
                          f"(out {out.strip()!r} err {err.strip()!r})")


def set_in_progress(root, project, task):
    exit_code, out, err = kit.run_tm_cli(
        root, "governance-status", "--project", project,
        "--updates", '{"status": "in_progress", "current_task": "%s"}' % task,
        "--reason", "ingress autorizzato dai validator (chain test)")
    expect_zero(f"governance-status {task}", exit_code, out, err)


def status_front(root, project):
    text = (project / "shared/project-status.md").read_text(encoding="utf-8")
    module = kit.load_module(root, kit.VALIDATORS_REL, "_framework")
    return module.parse_front_matter(text)


def run_stage(root, project, stage, structured, proposed, gate_result=None,
              conditions=None):
    """Esegue un intero stage come da workflow: ingress → in_progress →
    candidate → egress (entrambi i validator) → advance-stage."""
    exit_code, out, err = gate(root, project, stage, "ingress")
    expect_zero(f"{stage} ingress", exit_code, out, err)
    set_in_progress(root, project, f"chain-{stage}")
    candidate = kit.make_candidate(project, stage, tx_id=f"tx-{stage}",
                                   structured=structured, proposed=proposed)
    if conditions is not None:
        kit.write_json(candidate / "proposed-conditions.json", conditions)
    exit_code, out, err = refint(root, project, stage, "candidate", candidate)
    expect_zero(f"{stage} refint candidate", exit_code, out, err)
    exit_code, out, err = gate(root, project, stage, "egress", candidate)
    expect_zero(f"{stage} gate egress", exit_code, out, err)
    exit_code, out, err = refint(root, project, stage, "egress", candidate)
    expect_zero(f"{stage} refint egress", exit_code, out, err)
    args = ["advance-stage", "--project", project, "--stage", stage,
            "--candidate", candidate]
    if gate_result:
        args += ["--gate-result", gate_result]
    exit_code, out, err = kit.run_tm_cli(root, *args)
    expect_zero(f"{stage} advance-stage", exit_code, out, err)
    return kit.tm_result(out, f"{stage} advance-stage")


def run(root):
    with tempfile.TemporaryDirectory(prefix="bpo-chain-") as tmp:
        tmp = Path(tmp)

        # ------------------------------------------------ catena felice A
        pa = kit.make_project(tmp, name="chain-a", current_stage=S1,
                              status="not_started",
                              completed=["00_idea-discovery"],
                              evidence=EVIDENCE)

        result = run_stage(
            root, pa, S1,
            structured={"problem_statement": {
                "type": "cost",
                "description": "processo manuale lento e costoso",
                "affected_roles": ["operations manager"],
                "frequency": "daily",
                "intensity": "high",
                "perceived_vs_demonstrated": "perceived_and_demonstrated",
                "current_cost_refs": ["P-ASS-001"],
                "alternatives": [{"name": "status quo",
                                  "why_insufficient": "40k/anno di rework"}],
                "evidence_refs": ["EVD-001"],
            }},
            proposed=[p_ass(1, "problem", "current_cost_year",
                            "Costo annuo del problema", 40000)])
        if result.get("result") != "applied":
            raise TestFailure(f"stage 1 advance not applied: {result}")
        cost_ass = result["pass_map"]["P-ASS-001"]

        front = status_front(root, pa)
        if front["current_stage"] != S2 or S1 not in \
                front["completed_stages"]:
            raise TestFailure(f"after stage 1: bad status {front}")
        canon = kit.read_json(pa / S1 / "structured-output.json")
        if canon["problem_statement"]["current_cost_refs"] != [cost_ass]:
            raise TestFailure("stage 1 canonical output must reference the "
                              "allocated ASS-*")

        result = run_stage(
            root, pa, S2,
            structured={"customer_segments": [{
                "id": "SEG-001",
                "name": "PMI manifatturiere",
                "description": "PMI con processo manuale",
                "roles": {"user": "operatore", "buyer": "titolare",
                          "decision_maker": "titolare",
                          "influencer": "consulente",
                          "payer": "titolare", "gatekeeper": "IT esterno"},
                "problem_ref": S1,
                "problem_fit": "sostiene il costo registrato",
                "accessibility": "associazioni di categoria",
                "buying_process": "acquisto diretto, ciclo 2 mesi",
                "size_refs": ["P-ASS-001"],
                "evidence_refs": ["EVD-001"],
                "cost_ref": cost_ass,
            }],
                "beachhead": {"segment_ref": "SEG-001",
                              "selection_criteria":
                                  "intensità × accessibilità",
                              "rationale": "accesso via associazione"}},
            proposed=[p_ass(1, "segment", "segment_size",
                            "Numerosità del segmento", 1200, unit="count")])
        if result.get("result") != "applied":
            raise TestFailure(f"stage 2 advance not applied: {result}")

        vp_validated = {"value_proposition": {
            "id": "VP-001",
            "segment_ref": "SEG-001",
            "jobs": ["produrre senza rework"],
            "pains": ["40k/anno di rework"],
            "gains": ["margine recuperato"],
            "mapping": [{"pain": "rework", "reliever": "automazione"}],
            "switching_rationale": "vs status quo manuale",
            "value_metrics": [{"metric": "ore risparmiate",
                               "ref": "P-ASS-001"}],
            "proof_points": [{
                "claim": "riduce il rework del 30%",
                "evidence_classification": "external_source",
                "evidence_refs": ["EVD-001"],
            }],
        }}
        result = run_stage(
            root, pa, S3, structured=vp_validated,
            proposed=[p_ass(1, "value", "hours_saved_month",
                            "Ore risparmiate al mese", 120, unit="count")])
        if result.get("result") != "applied":
            raise TestFailure(f"stage 3 advance not applied: {result}")

        front = status_front(root, pa)
        if front["current_stage"] != S4:
            raise TestFailure(f"after stage 3: bad status {front}")
        if front["completed_stages"] != ["00_idea-discovery", S1, S2, S3]:
            raise TestFailure(
                f"completed chain wrong: {front['completed_stages']}")
        exit_code, out, err = gate(root, pa, S4, "ingress")
        expect_zero("stage 4 ingress after approved chain", exit_code, out,
                    err)

        # ------------------ checkpoint evidenze, percorso B: solo assunzioni
        pb = kit.make_project(tmp, name="chain-b", current_stage=S3,
                              status="not_started",
                              completed=["00_idea-discovery", S1, S2],
                              evidence=EVIDENCE)
        exit_code, out, err = gate(root, pb, S3, "ingress")
        expect_zero("B stage 3 ingress", exit_code, out, err)
        set_in_progress(root, pb, "chain-b-stage3")

        vp_founder_only = {"value_proposition": {
            "id": "VP-001",
            "segment_ref": "SEG-001",
            "jobs": ["…"], "pains": ["…"], "gains": ["…"],
            "mapping": [{"pain": "rework", "reliever": "automazione"}],
            "switching_rationale": "vs status quo",
            "value_metrics": [],
            "proof_points": [{
                "claim": "riduce il rework del 30%",
                "evidence_classification": "founder_assumption",
            }],
        }}
        cand_no_cond = kit.make_candidate(pb, S3, tx_id="tx-no-cond",
                                          structured=vp_founder_only)
        exit_code, out, err = gate(root, pb, S3, "egress", cand_no_cond)
        if exit_code != 1:
            raise TestFailure("B: founder-only egress must fail, got "
                              f"{exit_code} (out {out.strip()!r})")
        before = kit.snapshot_canonical(pb)
        exit_code, out, err = kit.run_tm_cli(
            root, "advance-stage", "--project", pb, "--stage", S3,
            "--candidate", cand_no_cond, "--gate-result", "approved")
        if exit_code != 1:
            raise TestFailure("B: advance without COND must be rejected, got "
                              f"{exit_code}")
        if kit.snapshot_canonical(pb) != before:
            raise TestFailure("B: rejected advance mutated canonical state")

        # con COND proposta: approved_with_conditions passa
        cand_cond = kit.make_candidate(pb, S3, tx_id="tx-with-cond",
                                       structured=vp_founder_only)
        kit.write_json(cand_cond / "proposed-conditions.json",
                       [checkpoint_cond()])
        exit_code, out, err = gate(root, pb, S3, "egress", cand_cond)
        expect_zero("B egress with COND", exit_code, out, err)
        report = kit.parse_report(out, "B egress with COND")
        if report["result"] != "WARNING":
            raise TestFailure("B egress with COND: expected WARNING, got "
                              f"{report['result']}")
        exit_code, out, err = kit.run_tm_cli(
            root, "advance-stage", "--project", pb, "--stage", S3,
            "--candidate", cand_cond,
            "--gate-result", "approved_with_conditions")
        expect_zero("B advance with COND", exit_code, out, err)

        conds = kit.read_json(pb / "shared/conditions-register.json")
        open_cond = [c for c in conds if c.get("id") == "COND-101"
                     and c.get("resolution_status") == "open"]
        if not open_cond:
            raise TestFailure("B: COND-101 open must be canonical after "
                              f"commit, got {conds}")

        # la COND open dovuta prima dello Stage 4 blocca l'ingresso
        exit_code, out, err = gate(root, pb, S4, "ingress")
        if exit_code != 1:
            raise TestFailure("B: stage 4 ingress must be blocked by open "
                              f"COND, got {exit_code}")
        report = kit.parse_report(out, "B stage 4 ingress")
        codes = [e["code"] for e in report["errors"]]
        if "condition_due" not in codes:
            raise TestFailure(f"B: expected condition_due, got {codes}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-STAGE-CHAIN-1-3 Stage 1-3 gates green on the real "
          "pipeline")


if __name__ == "__main__":
    main()
