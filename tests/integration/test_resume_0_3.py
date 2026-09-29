#!/usr/bin/env python3
"""T-RESUME-0.3 — ripresa a metà catena Stage 7-9 su file reale.

Estende T-RESUME (catena Stage 1-6) agli Stage 7-9, sempre su file
persistiti reali (mai return mockati):

- interruzione dopo Stage 6/7/8 → ripresa nello Stage 7/8/9: current_stage e
  next_action puntano al workflow corretto; gli stage approvati NON si
  riaprono (ingress/egress → stage_already_completed; apply → rejected senza
  mutazioni);
- crash di `advance-stage` a metà `applying` (Stage 7) → recover: rollback
  byte-identico, nessuno stage riaperto, `completed_stages` monotono, retry
  con id deterministici che porta a Stage 8;
- crash di `update-assumption` a metà `applying` su uno Stage 7-9 → recover:
  rollback byte-identico, nessun `DEC-*` consumato, retry deterministico;
- crash prima del marker `committed` su `advance-stage` (Stage 8) → recover
  marker-only: l'avanzamento sopravvive, il canonico non è riscritto;
- chiusura dello Stage 9: la ripresa punta ad avviare lo Stage 10, DENTRO
  il release boundary; nessuno stage esiste oltre l'ultimo di `stage_order`
  (bersaglio assente da `stage_order`: exit 2).
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit
import bpo_m5_fixtures as m5


class TestFailure(AssertionError):
    pass


S6, S7, S8, S9 = m5.S6, m5.S7, m5.S8, m5.S9
S10 = "10_financial-plan"
S11 = "11_funding-request"
S12 = "12_data-room"
S13 = "13_document-generation"
#: Forma T2: un identificatore ASSENTE da `stage_order`, bersaglio non vacuo
#: «oltre» l'ultimo stage.
ABSENT_STAGE = "14_after-terminal"


def status_front(root, project):
    text = (project / "shared/project-status.md").read_text(encoding="utf-8")
    module = kit.load_module(root, kit.VALIDATORS_REL, "_framework")
    return module.parse_front_matter(text)


def leaf_update_payload(tm, project, operation_id="op-upd", value=0.16):
    """Update coerente di una foglia (churn ASS-024): nessun derivato
    dipende da essa, quindi l'impact 4..current resta verde."""
    register = kit.read_json(project / "shared/assumptions-register.json")
    entry = next(e for e in register if e["id"] == "ASS-024")
    return {
        "operation_id": operation_id,
        "reason": "churn rivisto su nuova evidenza",
        "decision": {
            "decision_type": "assumption_update",
            "options_considered": "mantenere vs aggiornare",
            "motivation": "coorte pilota aggiornata",
            "impact": "nessun derivato coinvolto",
            "approver": "founder",
        },
        "changes": [{"assumption_id": "ASS-024",
                     "expected_record_hash": tm.record_fingerprint(entry),
                     "updates": {"value": value}}],
    }


def run_update(root, project, doc, tmp, name, env_extra=None):
    path = Path(tmp) / name
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return kit.run_tm_cli(root, "update-assumption", "--project", project,
                          "--changes", path, env_extra=env_extra)


def advance_candidate(project, stage):
    """Candidate coerente per l'advance dello stage indicato (fixture condivise
    degli Stage 7-9)."""
    if stage == S7:
        return kit.make_candidate(
            project, S7, tx_id="tx-s7",
            structured=m5.operations_structured(capacity_ref="P-ASS-101"),
            proposed=m5.ops_proposed())
    if stage == S8:
        return kit.make_candidate(
            project, S8, tx_id="tx-s8", structured=m5.team_structured(),
            proposed=m5.team_proposed())
    if stage == S9:
        return kit.make_candidate(
            project, S9, tx_id="tx-s9",
            structured=m5.milestone_structured(),
            proposed=m5.milestone_proposed())
    raise AssertionError(stage)


def check_no_reopen(root, project, completed_stage):
    """Uno stage in completed_stages non si riapre al resume (§15)."""
    exit_code, out, _ = kit.run_validator_cli(
        root, "validate_stage_gate", project=project, stage=completed_stage,
        phase="ingress")
    if exit_code != 1:
        raise TestFailure(f"reopen ingress {completed_stage} deve dare exit 1, "
                          f"got {exit_code}")
    report = kit.parse_report(out, f"reopen {completed_stage}")
    if "stage_already_completed" not in [e["code"] for e in report["errors"]]:
        raise TestFailure(f"reopen {completed_stage}: atteso "
                          "stage_already_completed")
    before = kit.snapshot_canonical(project)
    reopen = kit.make_candidate(project, completed_stage, tx_id="tx-reopen",
                                structured={"x": 1})
    exit_code, _, _ = kit.run_tm_cli(root, "apply", "--project", project,
                                     "--stage", completed_stage,
                                     "--candidate", reopen)
    if exit_code != 1:
        raise TestFailure(f"apply su {completed_stage} completato deve essere "
                          f"rejected, got {exit_code}")
    if kit.snapshot_canonical(project) != before:
        raise TestFailure(f"reopen rejected di {completed_stage} ha mutato il "
                          "canonico")


def resume_points_to_stage(root, tmp):
    """Interruzione dopo Stage 6/7/8: la ripresa entra nello Stage 7/8/9 e non
    riapre gli stage approvati."""
    cases = [
        (m5.make_stage7_project, S7, S6),
        (m5.make_stage8_project, S8, S7),
        (m5.make_stage9_project, S9, S8),
    ]
    for factory, current, prior in cases:
        project = factory(tmp, f"resume-into-{current}")
        front = status_front(root, project)
        if front["current_stage"] != current:
            raise TestFailure(f"resume: current_stage atteso {current}, "
                              f"trovato {front['current_stage']}")
        if prior not in front["completed_stages"]:
            raise TestFailure(f"resume: {prior} deve restare in "
                              "completed_stages")
        check_no_reopen(root, project, prior)


def crash_advance_rollback(root, tmp):
    """Crash di advance-stage a metà applying (Stage 7) → rollback + retry."""
    project = m5.make_stage7_project(tmp, "resume-crash-adv")
    completed_before = status_front(root, project)["completed_stages"]
    before = kit.snapshot_canonical(project)
    candidate = advance_candidate(project, S7)
    exit_code, _, _ = kit.run_tm_cli(
        root, "advance-stage", "--project", project, "--stage", S7,
        "--candidate", candidate, "--gate-result", "approved",
        env_extra={"BPO_TX_TEST_CRASH": "after_writes:2"})
    if exit_code == 0:
        raise TestFailure("crash mid-applying non deve dare exit 0")
    applying = [kit.read_json(p) for p in kit.find_journals(project)
                if kit.read_json(p).get("state") == "applying"]
    if not applying:
        raise TestFailure("crash mid-applying deve lasciare un journal applying")
    if kit.snapshot_canonical(project) == before:
        raise TestFailure("setup: attesa una scrittura parziale pre-recover")

    exit_code, _, err = kit.run_tm_cli(root, "recover", "--project", project)
    if exit_code != 0:
        raise TestFailure(f"recover (rollback) fallito: {err.strip()!r}")
    if kit.snapshot_canonical(project) != before:
        raise TestFailure("rollback: lo stato non è byte-identico al pre-crash")
    front = status_front(root, project)
    if front["current_stage"] != S7 or S7 in front["completed_stages"]:
        raise TestFailure("rollback: lo stato non deve avanzare")
    if front["completed_stages"] != completed_before:
        raise TestFailure("rollback: completed_stages non monotono/stabile")

    # retry: id deterministici, avanzamento a Stage 8, completed monotono
    retry = advance_candidate(project, S7)
    exit_code, out, err = kit.run_tm_cli(
        root, "advance-stage", "--project", project, "--stage", S7,
        "--candidate", retry, "--gate-result", "approved")
    if exit_code != 0:
        raise TestFailure(f"retry advance fallito: {err.strip()!r} "
                          f"out {out.strip()!r}")
    result = kit.tm_result(out, "retry advance S7")
    if result.get("result") != "applied":
        raise TestFailure(f"retry advance non applied: {result}")
    front = status_front(root, project)
    if front["current_stage"] != S8 or S7 not in front["completed_stages"]:
        raise TestFailure(f"dopo retry: stato errato {front}")
    if not set(completed_before).issubset(set(front["completed_stages"])):
        raise TestFailure("completed_stages non monotono attraverso il retry")
    if S8 not in front.get("next_action", ""):
        raise TestFailure("next_action deve puntare allo stage successivo, "
                          f"got {front.get('next_action')!r}")


def crash_update_rollback(root, tm, tmp):
    """Crash di update-assumption a metà applying (Stage 7) → rollback, nessun
    DEC- consumato, retry deterministico."""
    project = m5.make_stage7_project(tmp, "resume-crash-upd")
    before = kit.snapshot_canonical(project)
    doc = leaf_update_payload(tm, project, operation_id="op-crash")
    exit_code, _, _ = run_update(root, project, doc, tmp, "upd-crash.json",
                                 env_extra={"BPO_TX_TEST_CRASH":
                                            "after_writes:1"})
    if exit_code == 0:
        raise TestFailure("crash update mid-applying non deve dare exit 0")
    applying = [p for p in kit.find_journals(project)
                if kit.read_json(p).get("mode") == "update_assumption"
                and kit.read_json(p).get("state") == "applying"]
    if not applying:
        raise TestFailure("crash update deve lasciare un journal applying")

    exit_code, _, err = kit.run_tm_cli(root, "recover", "--project", project)
    if exit_code != 0:
        raise TestFailure(f"recover update fallito: {err.strip()!r}")
    if kit.snapshot_canonical(project) != before:
        raise TestFailure("rollback update: canonico non byte-identico")
    if (project / "shared/decisions-register.json").exists():
        raise TestFailure("rollback update: nessun DEC- deve essere consumato "
                          "(decisions-register non deve sopravvivere)")

    retry = leaf_update_payload(tm, project, operation_id="op-upd-retry")
    exit_code, out, err = run_update(root, project, retry, tmp,
                                     "upd-retry.json")
    if exit_code != 0:
        raise TestFailure(f"retry update fallito: {err.strip()!r}")
    result = kit.tm_result(out, "retry update")
    if result.get("decision_id") != "DEC-001":
        raise TestFailure("retry update: DEC- non deterministico "
                          f"({result.get('decision_id')})")


def crash_advance_marker_only(root, tmp):
    """Crash prima del marker committed (Stage 8) → recover marker-only:
    l'avanzamento sopravvive, il canonico non è riscritto."""
    project = m5.make_stage8_project(tmp, "resume-marker")
    candidate = advance_candidate(project, S8)
    exit_code, _, _ = kit.run_tm_cli(
        root, "advance-stage", "--project", project, "--stage", S8,
        "--candidate", candidate, "--gate-result", "approved",
        env_extra={"BPO_TX_TEST_CRASH": "before_commit"})
    if exit_code == 0:
        raise TestFailure("crash before_commit non deve dare exit 0")
    written = kit.snapshot_canonical(project)
    exit_code, _, err = kit.run_tm_cli(root, "recover", "--project", project)
    if exit_code != 0:
        raise TestFailure(f"recover marker-only fallito: {err.strip()!r}")
    completed_journals = [
        j for j in (kit.read_json(p) for p in kit.find_journals(project))
        if j.get("recovery_action") == "completed_marker_only"]
    if not completed_journals:
        raise TestFailure("recover deve completare la transazione marker-only")
    if kit.snapshot_canonical(project) != written:
        raise TestFailure("marker-only recovery non deve riscrivere il canonico")
    front = status_front(root, project)
    if front["current_stage"] != S9 or S8 not in front["completed_stages"]:
        raise TestFailure(f"dopo marker-only recovery: stato errato {front}")


def terminal_resume(root, tmp):
    """Chiusura dello Stage 9: la ripresa punta ad avviare lo Stage 10,
    DENTRO il release boundary; oltre l'ultimo stage di `stage_order` non
    esiste alcuno stage (forma T2).

    Il `next_action` boundary-aware è calcolato dalla STESSA funzione
    (`TM.boundary_next_action`) usata dall'advance, che non classifica oltre
    il confine alcuno stage di `stage_order`."""
    project = m5.make_stage9_project(tmp, "resume-terminal")
    candidate = advance_candidate(project, S9)
    exit_code, out, err = kit.run_tm_cli(
        root, "advance-stage", "--project", project, "--stage", S9,
        "--candidate", candidate, "--gate-result", "approved")
    if exit_code != 0:
        raise TestFailure(f"advance Stage 9 fallito: {err.strip()!r} "
                          f"out {out.strip()!r}")
    front = status_front(root, project)
    if front["current_stage"] != S10 or S9 not in front["completed_stages"]:
        raise TestFailure(f"stato dopo la chiusura dello Stage 9 errato: "
                          f"{front}")
    next_action = front.get("next_action", "")
    if "release boundary" in next_action.lower():
        raise TestFailure(
            "resume dopo lo Stage 9: next_action non deve portare il "
            f"messaggio di confine — lo Stage 10 e' DENTRO il release "
            f"boundary: {next_action!r}")
    if f"avviare {S10}" not in next_action:
        raise TestFailure("resume dopo lo Stage 9: next_action deve "
                          f"invitare ad avviare lo Stage 10: {next_action!r}")

    # Forma T2: con il confine sull'ULTIMO stage di
    # stage_order non esiste uno stage reale «oltre»; il bersaglio e' un
    # identificatore ASSENTE da stage_order, respinto come errore d'uso
    # (exit 2) prima di lock e I/O, senza alcuna mutazione.
    before = kit.snapshot_canonical(project)
    beyond = kit.make_candidate(project, ABSENT_STAGE, tx_id="tx-absent",
                                structured={"document_generation": {}})
    exit_code, out, _ = kit.run_tm_cli(
        root, "advance-stage", "--project", project, "--stage", ABSENT_STAGE,
        "--candidate", beyond)
    if exit_code != 2:
        raise TestFailure("resume dopo lo Stage 9: advance su uno stage "
                          "assente da "
                          f"stage_order deve dare exit 2, got {exit_code} "
                          f"{out.strip()[:200]!r}")
    if kit.snapshot_canonical(project) != before:
        raise TestFailure("resume dopo lo Stage 9: il tentativo oltre "
                          "l'ultimo stage ha mutato il canonico")


def run(root):
    tm = kit.load_module(root, kit.TRANSACTION_REL, "transaction_manager")
    with tempfile.TemporaryDirectory(prefix="bpo-resume03-") as tmp:
        tmp = Path(tmp)
        resume_points_to_stage(root, tmp)
        crash_advance_rollback(root, tmp)
        crash_update_rollback(root, tm, tmp)
        crash_advance_marker_only(root, tmp)
        terminal_resume(root, tmp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-RESUME-0.3 ripresa Stage 7-9, rollback/marker-only "
          "recovery, nessuna riapertura, ripresa dopo lo Stage 9 dentro il "
          "release boundary")


if __name__ == "__main__":
    main()
