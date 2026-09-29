#!/usr/bin/env python3
"""T-STATEFUL-INTEGRATION — idea → Stage 6 simulato su file.

Percorre la catena Stage 1→6 sulla pipeline reale (ingress
gate → governance → candidate stage-bounded → validator egress →
advance-stage transazionale), con una **incoerenza pilotata a Stage 5**
(contribution margin divergente dal ricalcolo): il gate la respinge senza
mutazioni canoniche, il candidate corretto passa. Dopo ogni gate verifica
lo stato persistito su file: project-status (current/completed), registro
senza P-ASS residui e con allocazione progressiva, structured-output e
handoff canonici scritti, journal committed, audit-log append-only.

Il vero E2E non è automatico: questo test simula lo stato su file; l'E2E
reale è una sessione Claude Code che esegue la skill su un progetto.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit
import bpo_m5_fixtures as m5
import test_market_arithmetic as market
import test_stage_chain_1_3 as chain


class TestFailure(AssertionError):
    pass


S1, S2, S3 = chain.S1, chain.S2, chain.S3
S4, S5, S6 = m5.S4, m5.S5, m5.S6
S7 = "07_operations-and-ip"


def check_state(root, project, current, completed_last, label):
    front = chain.status_front(root, project)
    if front["current_stage"] != current:
        raise TestFailure(f"{label}: current_stage atteso {current}, "
                          f"trovato {front['current_stage']}")
    if completed_last not in front["completed_stages"]:
        raise TestFailure(f"{label}: {completed_last} non in "
                          f"completed_stages {front['completed_stages']}")
    register_text = (project / "shared/assumptions-register.json") \
        .read_text(encoding="utf-8")
    if "P-ASS-" in register_text:
        raise TestFailure(f"{label}: P-ASS residuo nel registro canonico")
    canon = project / completed_last / "structured-output.json"
    if not canon.exists():
        raise TestFailure(f"{label}: structured-output canonico assente per "
                          f"{completed_last}")
    if not (project / completed_last / "handoff.md").exists():
        raise TestFailure(f"{label}: handoff canonico assente per "
                          f"{completed_last}")
    return front


def committed_advances(project):
    return [j for j in (kit.read_json(p) for p in kit.find_journals(project))
            if j.get("mode") == "advance" and j.get("state") == "committed"]


def run(root):
    with tempfile.TemporaryDirectory(prefix="bpo-e2e-") as tmp:
        tmp = Path(tmp)
        p = kit.make_project(tmp, name="e2e", current_stage=S1,
                             status="not_started",
                             completed=["00_idea-discovery"],
                             evidence=chain.EVIDENCE)

        # ------------------------------------------------- Stage 1 → 3
        result = chain.run_stage(
            root, p, S1,
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
            proposed=[chain.p_ass(1, "problem", "current_cost_year",
                                  "Costo annuo del problema", 40000)])
        cost_ass = result["pass_map"]["P-ASS-001"]
        check_state(root, p, S2, S1, "after stage 1")

        chain.run_stage(
            root, p, S2,
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
            proposed=[chain.p_ass(1, "segment", "segment_size",
                                  "Numerosità del segmento", 1200,
                                  unit="count")])
        check_state(root, p, S3, S2, "after stage 2")

        chain.run_stage(
            root, p, S3,
            structured={"value_proposition": {
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
            }},
            proposed=[chain.p_ass(1, "value", "hours_saved_month",
                                  "Ore risparmiate al mese", 120,
                                  unit="count")])
        check_state(root, p, S4, S3, "after stage 3")

        # ----------------------------------------------------- Stage 4
        result = chain.run_stage(root, p, S4,
                                 structured=market.structured(),
                                 proposed=market.market_proposed())
        pass4 = result["pass_map"]
        arpa_ass = pass4["P-ASS-003"]
        front = check_state(root, p, S5, S4, "after stage 4")
        canon4 = kit.read_json(p / S4 / "structured-output.json")
        if canon4["market_model"]["som_ref"] != pass4["P-ASS-011"]:
            raise TestFailure("stage 4: som_ref canonico non riscritto "
                              "sull'ASS allocato")

        # --------------------- Stage 5 con INCOERENZA PILOTATA (margine)
        exit_code, out, err = chain.gate(root, p, S5, "ingress")
        chain.expect_zero("stage 5 ingress", exit_code, out, err)
        chain.set_in_progress(root, p, "e2e-stage5")

        bad_prop = m5.with_variable(m5.business_proposed(),
                                    "contribution_margin_unit", value=75,
                                    display_value="75 EUR/count")
        bad_candidate = kit.make_candidate(
            p, S5, tx_id="tx-s5-bad",
            structured=m5.business_structured_proposed(),
            proposed=bad_prop)
        exit_code, out, _ = kit.run_validator_cli(
            root, "validate_unit_economics", project=p, stage=S5,
            phase="egress", candidate=bad_candidate)
        if exit_code != 1:
            raise TestFailure("piloted incoherence: unit economics egress "
                              f"must fail, got {exit_code}")
        report = kit.parse_report(out, "piloted incoherence")
        if "value_mismatch" not in [e["code"] for e in report["errors"]]:
            raise TestFailure("piloted incoherence: expected value_mismatch")
        before = kit.snapshot_canonical(p)
        exit_code, out, _ = kit.run_tm_cli(
            root, "advance-stage", "--project", p, "--stage", S5,
            "--candidate", bad_candidate, "--gate-result", "approved")
        if exit_code != 1:
            raise TestFailure("piloted incoherence: advance must be "
                              f"rejected, got {exit_code}")
        if kit.snapshot_canonical(p) != before:
            raise TestFailure("piloted incoherence: rejected advance "
                              "mutated the canonical state")
        front = chain.status_front(root, p)
        if front["current_stage"] != S5 or S5 in front["completed_stages"]:
            raise TestFailure("piloted incoherence: lo stato non deve "
                              "avanzare su rejection")

        # candidate corretto: il gate passa
        good_candidate = kit.make_candidate(
            p, S5, tx_id="tx-s5-good",
            structured=m5.business_structured_proposed(),
            proposed=m5.business_proposed())
        for name in ("validate_stage_gate", "validate_referential_integrity",
                     "validate_market_arithmetic", "validate_unit_economics",
                     "validate_cross_stage_consistency"):
            exit_code, out, err = kit.run_validator_cli(
                root, name, project=p, stage=S5, phase="egress",
                candidate=good_candidate)
            chain.expect_zero(f"stage 5 egress {name}", exit_code, out, err)
        exit_code, out, err = kit.run_tm_cli(
            root, "advance-stage", "--project", p, "--stage", S5,
            "--candidate", good_candidate, "--gate-result", "approved")
        chain.expect_zero("stage 5 advance", exit_code, out, err)
        result5 = kit.tm_result(out, "stage 5 advance")
        pricing_ass = result5["pass_map"]["P-ASS-001"]
        check_state(root, p, S6, S5, "after stage 5")

        # ----------------------------------------------------- Stage 6
        result = chain.run_stage(
            root, p, S6,
            structured=m5.funnel_structured(pricing_ref=pricing_ass),
            proposed=m5.funnel_proposed(arpa_ref=arpa_ass))
        check_state(root, p, S7, S6, "after stage 6")

        # ------------------------------------------ invarianti terminali
        front = chain.status_front(root, p)
        expected_chain = ["00_idea-discovery", S1, S2, S3, S4, S5, S6]
        if front["completed_stages"] != expected_chain:
            raise TestFailure(f"final chain wrong: "
                              f"{front['completed_stages']}")
        advances = committed_advances(p)
        if len(advances) != 6:
            raise TestFailure(f"expected 6 committed advances, got "
                              f"{len(advances)}")
        audit = (p / "shared/audit-log.jsonl").read_text(encoding="utf-8")
        applied = [ln for ln in audit.splitlines()
                   if '"tx_advance_stage"' in ln and '"applied"' in ln]
        if len(applied) != 6:
            raise TestFailure(f"audit-log: expected 6 applied advances, got "
                              f"{len(applied)}")
        rejected = [ln for ln in audit.splitlines() if '"rejected"' in ln]
        if not rejected:
            raise TestFailure("audit-log: la rejection pilotata a Stage 5 "
                              "deve essere tracciata")

        # matrice impact Stage 4-6 verde sul canonico finale
        for name, stage in (("validate_market_arithmetic", S4),
                            ("validate_unit_economics", S5),
                            ("validate_funnel_arithmetic", S6),
                            ("validate_cross_stage_consistency", S6)):
            exit_code, out, err = kit.run_validator_cli(
                root, name, project=p, stage=stage, phase="impact")
            chain.expect_zero(f"final impact {name}", exit_code, out, err)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-STATEFUL-INTEGRATION idea -> Stage 6 su file con "
          "incoerenza pilotata a Stage 5")


if __name__ == "__main__":
    main()
