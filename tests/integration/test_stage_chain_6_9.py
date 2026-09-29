#!/usr/bin/env python3
"""T-STAGE-CHAIN-6-9 — catena reale Stage 6->9 su file.

Percorre l'intera catena Stage 6->7->8->9 sulla pipeline reale
(ingress gate -> governance in_progress -> candidate stage-bounded -> validator
egress -> transaction_manager advance-stage), esattamente come i workflow
07-10, senza mai copiare file canonici a mano. Verifica, invariante per
invariante:

- ingress bloccato senza il precedente `approved*`: entrare in uno stage il
  cui predecessore non è in `completed_stages` è respinto dal gate;
- ogni avanzamento è un journal `advance` `committed`; nessun P-ASS residuo
  nel registro canonico; structured-output e handoff canonici scritti;
- `project-status` (current/completed) aggiornato dopo ogni advance;
- nessun candidate promosso su FAIL: un'incoerenza pilotata a Stage 7
  (capacità operativa < volumi GTM) fa fallire l'egress cross-stage, l'advance
  è rejected, il canonico resta byte-identico e lo stato non avanza; il
  candidate corretto poi passa;
- stato dopo la chiusura dello Stage 9: `current_stage = 10_financial-plan`,
  DENTRO il release boundary, `next_action` boundary-aware, e ogni tentativo
  operativo oltre l'ULTIMO stage di `stage_order` -> identificatore assente
  -> errore d'uso exit 2 senza mutazioni (forma T2: lo Stage 13 e' DENTRO il
  confine ed e' l'ultimo stage).

La verifica interattiva in una sessione Claude Code reale resta manuale;
questo test ne è la controparte deterministica su file.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit
import bpo_m5_fixtures as m5
import test_stage_chain_1_3 as chain


class TestFailure(AssertionError):
    pass


S6, S7, S8, S9 = m5.S6, m5.S7, m5.S8, m5.S9
S10 = "10_financial-plan"
S11 = "11_funding-request"
S12 = "12_data-room"
S13 = "13_document-generation"
#: Forma T2: identificatore ASSENTE da `stage_order`.
ABSENT_STAGE = "14_after-terminal"


def enter_stage6(tmp, name):
    """Progetto canonico Stage 4-5 applicati, allo Stage 6 `not_started`
    (il punto da cui riparte la catena Stage 6-9)."""
    project = m5.make_stage6_project(tmp, name)
    kit.write_json(project / "shared" / "risk-register.json",
                   m5.risk_register())
    (project / "shared" / "project-status.md").write_text(
        kit.project_status_text(name, S6, "not_started",
                                m5.COMPLETED_THROUGH_5), encoding="utf-8")
    return project


def ops_structured(capacity_ref):
    """Operations model Stage 7 con tre processi core (matrice ruoli->processi
    vera per lo Stage 8), capacità riferita al driver `capacity_ref`."""
    doc = m5.operations_structured(capacity_ref=capacity_ref)
    doc["operations_model"]["core_processes"] += [
        {"id": "OPS-004", "entity_type": "core_process",
         "name": "Erogazione e assistenza continuativa",
         "make_buy_partner": "make", "owner_hint": "Head of Delivery",
         "bottleneck": False},
        {"id": "OPS-005", "entity_type": "core_process",
         "name": "Integrazione con i canali partner",
         "make_buy_partner": "partner", "owner_hint": "Head of Partnerships",
         "bottleneck": False},
    ]
    return doc


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
    if not (project / completed_last / "structured-output.json").exists():
        raise TestFailure(f"{label}: structured-output canonico assente per "
                          f"{completed_last}")
    if not (project / completed_last / "handoff.md").exists():
        raise TestFailure(f"{label}: handoff canonico assente per "
                          f"{completed_last}")
    return front


def committed_advances(project):
    return [j for j in (kit.read_json(p) for p in kit.find_journals(project))
            if j.get("mode") == "advance" and j.get("state") == "committed"]


def egress_ok(root, project, stage, candidate):
    """Egress reale (gate + refint), esattamente come i workflow 07-10."""
    exit_code, out, err = chain.gate(root, project, stage, "egress", candidate)
    chain.expect_zero(f"{stage} gate egress", exit_code, out, err)
    exit_code, out, err = chain.refint(root, project, stage, "egress",
                                       candidate)
    chain.expect_zero(f"{stage} refint egress", exit_code, out, err)


def happy_chain(root, tmp):
    """Catena felice 6->9: ogni advance committed, stato e canonico coerenti."""
    p = enter_stage6(tmp, "chain-a")

    r6 = chain.run_stage(root, p, S6, structured=m5.funnel_structured(),
                         proposed=m5.funnel_proposed())
    if r6.get("result") != "applied":
        raise TestFailure(f"S6 advance non applied: {r6}")
    check_state(root, p, S7, S6, "after stage 6")
    customers_ass = r6["pass_map"]["P-ASS-004"]
    churn_ass = r6["pass_map"]["P-ASS-007"]

    # ingress bloccato senza il precedente approved*: con S7 corrente (S7 non
    # ancora in completed_stages) l'ingresso a S8 è respinto dal gate.
    exit_code, out, _ = chain.gate(root, p, S8, "ingress")
    if exit_code == 0:
        raise TestFailure("S8 ingress senza S7 approvato deve essere bloccato")

    r7 = chain.run_stage(root, p, S7,
                         structured=ops_structured("P-ASS-101"),
                         proposed=m5.ops_proposed())
    if r7.get("result") != "applied":
        raise TestFailure(f"S7 advance non applied: {r7}")
    check_state(root, p, S8, S7, "after stage 7")
    ops_capacity_ass = r7["pass_map"]["P-ASS-101"]

    r8 = chain.run_stage(root, p, S8, structured=m5.team_structured(),
                         proposed=m5.team_proposed())
    if r8.get("result") != "applied":
        raise TestFailure(f"S8 advance non applied: {r8}")
    check_state(root, p, S9, S8, "after stage 8")
    fte_lead_ass = r8["pass_map"]["P-ASS-201"]
    fte_open_ass = r8["pass_map"]["P-ASS-202"]

    fpi = m5.financial_plan_inputs(
        funnel_customers_ref=customers_ass, churn_ref=churn_ass,
        ops_capacity_ref=ops_capacity_ass,
        headcount_driver_refs=[fte_lead_ass, fte_open_ass])
    r9 = chain.run_stage(root, p, S9,
                         structured=m5.milestone_structured(inputs=fpi),
                         proposed=m5.milestone_proposed(),
                         gate_result="approved")
    if r9.get("result") != "applied":
        raise TestFailure(f"S9 advance non applied: {r9}")

    front = chain.status_front(root, p)
    expected = m5.COMPLETED_THROUGH_8 + [S9]
    if front["completed_stages"] != expected:
        raise TestFailure(f"catena finale errata: {front['completed_stages']}")
    advances = committed_advances(p)
    if len(advances) != 4:
        raise TestFailure(f"attesi 4 advance committed (6->9), trovati "
                          f"{len(advances)}")

    # stato dopo la chiusura dello Stage 9: current allo Stage 10, DENTRO il
    # release boundary, next_action boundary-aware.
    if front["current_stage"] != S10:
        raise TestFailure(f"current_stage atteso dopo lo Stage 9: {S10}, "
                          f"trovato {front['current_stage']}")
    if front.get("status") != "not_started":
        raise TestFailure(f"status dopo lo Stage 9: {front.get('status')!r}")
    next_action = front.get("next_action", "")
    if "release boundary" in next_action.lower():
        raise TestFailure(
            "next_action non deve portare il messaggio di confine — lo "
            f"Stage 10 e' DENTRO il release boundary: {next_action!r}")
    if f"avviare {S10}" not in next_action:
        raise TestFailure(f"next_action deve invitare ad avviare lo Stage "
                          f"10: {next_action!r}")

    # matrice impact 4->9 verde sul canonico finale
    for name, stage in (("validate_market_arithmetic", m5.S4),
                        ("validate_unit_economics", m5.S5),
                        ("validate_funnel_arithmetic", S6),
                        ("validate_cross_stage_consistency", S9),
                        ("validate_operations_feasibility", S7),
                        ("validate_team_and_governance", S8),
                        ("validate_milestone_chain", S9)):
        exit_code, out, err = kit.run_validator_cli(
            root, name, project=p, stage=stage, phase="impact")
        chain.expect_zero(f"final impact {name}", exit_code, out, err)
    return p


def beyond_boundary(root, project):
    """Ogni tentativo operativo oltre l'ULTIMO stage di `stage_order` ->
    identificatore assente -> errore d'uso, exit 2, nessuna mutazione
    canonica (forma T2): lo Stage 13 e' DENTRO il release boundary ed e'
    l'ultimo stage, quindi non esiste uno stage reale «oltre»."""
    before = kit.snapshot_canonical(project)
    candidate = kit.make_candidate(
        project, ABSENT_STAGE, tx_id="tx-absent",
        structured={"document_generation": {}}, handoff="# Handoff\n")
    for command in ("apply", "advance-stage"):
        exit_code, out, err = kit.run_tm_cli(
            root, command, "--project", project, "--stage", ABSENT_STAGE,
            "--candidate", candidate)
        if exit_code != 2:
            raise TestFailure(f"{command} oltre l'ultimo stage deve dare exit "
                              f"2 (errore d'uso), ottenuto {exit_code}")
    if kit.snapshot_canonical(project) != before:
        raise TestFailure("tentativi oltre l'ultimo stage hanno mutato il "
                          "canonico")


def piloted_incoherence(root, tmp):
    """Nessun candidate promosso su FAIL: incoerenza pilotata a Stage 7
    (capacità 500 < volumi GTM 1000). Egress cross-stage FAIL, advance
    rejected, canonico byte-identico, stato non avanzato; poi il candidate
    corretto passa e lo stato avanza."""
    p = enter_stage6(tmp, "chain-b")
    chain.run_stage(root, p, S6, structured=m5.funnel_structured(),
                    proposed=m5.funnel_proposed())
    check_state(root, p, S7, S6, "chain-b after stage 6")

    exit_code, out, err = chain.gate(root, p, S7, "ingress")
    chain.expect_zero("S7 ingress", exit_code, out, err)
    chain.set_in_progress(root, p, "chain-b-stage7")

    bad = kit.make_candidate(
        p, S7, tx_id="tx-s7-bad",
        structured=ops_structured("P-ASS-101"),
        proposed=m5.ops_proposed(capacity=500, installed=500,
                                 utilization=1.0))
    exit_code, out, _ = kit.run_validator_cli(
        root, "validate_cross_stage_consistency", project=p, stage=S7,
        phase="egress", candidate=bad)
    if exit_code != 1:
        raise TestFailure("incoerenza pilotata: cross-stage egress deve "
                          f"fallire, exit {exit_code}")
    report = kit.parse_report(out, "piloted S7 incoherence")
    if "ops_capacity_below_gtm" not in [e["code"] for e in report["errors"]]:
        raise TestFailure("incoerenza pilotata: atteso ops_capacity_below_gtm")

    before = kit.snapshot_canonical(p)
    exit_code, out, _ = kit.run_tm_cli(
        root, "advance-stage", "--project", p, "--stage", S7,
        "--candidate", bad, "--gate-result", "approved")
    if exit_code != 1:
        raise TestFailure("incoerenza pilotata: advance deve essere rejected, "
                          f"exit {exit_code}")
    if kit.snapshot_canonical(p) != before:
        raise TestFailure("incoerenza pilotata: l'advance rejected ha mutato "
                          "il canonico")
    if (p / S7 / "structured-output.json").exists():
        raise TestFailure("incoerenza pilotata: candidate promosso al canonico "
                          "su FAIL")
    front = chain.status_front(root, p)
    if front["current_stage"] != S7 or S7 in front["completed_stages"]:
        raise TestFailure("incoerenza pilotata: lo stato non deve avanzare")

    # candidate corretto: egress verde e advance committed (stato già in_progress)
    good = kit.make_candidate(
        p, S7, tx_id="tx-s7-good", structured=ops_structured("P-ASS-101"),
        proposed=m5.ops_proposed())
    egress_ok(root, p, S7, good)
    exit_code, out, err = kit.run_tm_cli(
        root, "advance-stage", "--project", p, "--stage", S7,
        "--candidate", good, "--gate-result", "approved")
    chain.expect_zero("S7 advance corretto", exit_code, out, err)
    check_state(root, p, S8, S7, "chain-b after good stage 7")


def run(root):
    with tempfile.TemporaryDirectory(prefix="bpo-chain69-") as tmp:
        tmp = Path(tmp)
        project = happy_chain(root, tmp)
        beyond_boundary(root, project)
        piloted_incoherence(root, tmp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-STAGE-CHAIN-6-9 catena reale Stage 6->9, ingress gated, "
          "nessuna promozione su FAIL, Stage 10 avviabile dentro il release "
          "boundary")


if __name__ == "__main__":
    main()
