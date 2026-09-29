#!/usr/bin/env python3
"""T-RESUME — ripresa a metà catena su scala multi-stage (§15).

Su un progetto con Stage 1-4 completati:

- gli stage approvati NON si riaprono al resume: ingress/egress su uno
  stage in completed_stages → stage_already_completed; advance/apply →
  rejected senza mutazioni (la riapertura di uno stage approvato non è
  supportata dal transaction manager);
- una transazione multi-file interrotta a metà `applying` (crash duro con
  lock su disco) viene ripristinata dallo snapshot al `recover`: nessuna
  scrittura canonica parziale sopravvive, nessun ASS- consumato, il retry
  alloca gli stessi id deterministici;
- una transazione `applying` completa ma priva del marker `committed`
  viene completata marker-only al `recover` (idempotente), l'avanzamento
  di stage sopravvive al crash;
- la ripresa segue project-status: current_stage/next_action aggiornati
  dopo ogni esito.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit
import bpo_m5_fixtures as m5


class TestFailure(AssertionError):
    pass


def status_front(root, project):
    text = (project / "shared/project-status.md").read_text(encoding="utf-8")
    module = kit.load_module(root, kit.VALIDATORS_REL, "_framework")
    return module.parse_front_matter(text)


def make_business_candidate(project, tx_id):
    return kit.make_candidate(
        project, m5.S5, tx_id=tx_id,
        structured=m5.business_structured_proposed(),
        proposed=m5.business_proposed())


def run(root):
    with tempfile.TemporaryDirectory(prefix="bpo-resume-") as tmp:
        tmp = Path(tmp)
        p = m5.make_stage5_project(tmp, "resume")

        # ------------------- stage approvati non riaperti al resume (§15)
        for phase in ("ingress", "egress"):
            candidate = None
            if phase == "egress":
                candidate = kit.make_candidate(
                    p, m5.S4, tx_id=f"tx-probe-{phase}",
                    structured=market_probe())
            exit_code, out, _ = kit.run_validator_cli(
                root, "validate_stage_gate", project=p, stage=m5.S4,
                phase=phase, candidate=candidate)
            if exit_code != 1:
                raise TestFailure(f"reopen {phase} on completed stage must "
                                  f"exit 1, got {exit_code}")
            report = kit.parse_report(out, f"reopen {phase}")
            if "stage_already_completed" not in [e["code"]
                                                 for e in report["errors"]]:
                raise TestFailure(f"reopen {phase}: expected "
                                  "stage_already_completed")
        before = kit.snapshot_canonical(p)
        reopen = kit.make_candidate(p, m5.S4, tx_id="tx-reopen",
                                    structured=market_probe())
        exit_code, _, _ = kit.run_tm_cli(
            root, "apply", "--project", p, "--stage", m5.S4,
            "--candidate", reopen)
        if exit_code != 1:
            raise TestFailure("apply on completed stage must be rejected, "
                              f"got {exit_code}")
        if kit.snapshot_canonical(p) != before:
            raise TestFailure("rejected reopen mutated canonical state")

        # -------- rollback multi-stage: crash a metà applying (write-set
        # con registro + structured-output + handoff + status + audit)
        c1 = make_business_candidate(p, "tx-crash-mid")
        before = kit.snapshot_canonical(p)
        register_before = kit.read_json(
            p / "shared/assumptions-register.json")
        exit_code, out, err = kit.run_tm_cli(
            root, "advance-stage", "--project", p, "--stage", m5.S5,
            "--candidate", c1, "--gate-result", "approved",
            env_extra={"BPO_TX_TEST_CRASH": "after_writes:2"})
        if exit_code == 0:
            raise TestFailure("crash mid-applying must not exit 0")
        journals = kit.find_journals(p)
        crashed = [kit.read_json(j) for j in journals
                   if kit.read_json(j).get("state") == "applying"]
        if not crashed:
            raise TestFailure("crash mid-applying must leave an applying "
                              "journal")
        if kit.snapshot_canonical(p) == before:
            raise TestFailure("test setup: partial write expected before "
                              "recovery")
        exit_code, out, err = kit.run_tm_cli(root, "recover", "--project", p)
        if exit_code != 0:
            raise TestFailure(f"recover (rollback) failed: {err.strip()!r}")
        if kit.snapshot_canonical(p) != before:
            raise TestFailure("rollback must restore the exact "
                              "pre-transaction state across every file")
        if kit.read_json(p / "shared/assumptions-register.json") != \
                register_before:
            raise TestFailure("rollback: register must be byte-identical")
        front = status_front(root, p)
        if front["current_stage"] != m5.S5 or \
                m5.S5 in front["completed_stages"]:
            raise TestFailure("rollback: lo stato non deve avanzare")

        # retry dopo rollback: stessi id deterministici (ASS-012..)
        c2 = make_business_candidate(p, "tx-retry")
        exit_code, out, err = kit.run_tm_cli(
            root, "advance-stage", "--project", p, "--stage", m5.S5,
            "--candidate", c2, "--gate-result", "approved")
        if exit_code != 0:
            raise TestFailure(f"retry advance failed: {exit_code} "
                              f"(out {out.strip()!r} err {err.strip()!r})")
        result = kit.tm_result(out, "retry advance")
        if result["pass_map"].get("P-ASS-001") != m5.PRICING_ID:
            raise TestFailure("retry must allocate deterministic ids "
                              f"(atteso {m5.PRICING_ID}), got "
                              f"{result['pass_map']}")
        front = status_front(root, p)
        if front["current_stage"] != m5.S6 or \
                m5.S5 not in front["completed_stages"]:
            raise TestFailure(f"after retry: bad status {front}")
        if "06_go-to-market" not in front.get("next_action", ""):
            raise TestFailure("next_action deve puntare allo stage "
                              f"successivo, got {front.get('next_action')!r}")

        # -------- recovery marker-only: crash prima del marker committed
        # sull'avanzamento di Stage 6 (applying completo). Come da workflow,
        # l'ingresso nello stage passa da ingress gate + governance.
        exit_code, out, err = kit.run_validator_cli(
            root, "validate_stage_gate", project=p, stage=m5.S6,
            phase="ingress")
        if exit_code != 0:
            raise TestFailure(f"stage 6 ingress after resume: exit "
                              f"{exit_code} (out {out.strip()!r})")
        exit_code, _, err = kit.run_tm_cli(
            root, "governance-status", "--project", p,
            "--updates", '{"status": "in_progress", '
                         '"current_task": "resume-stage-6"}',
            "--reason", "ingress Stage 6 autorizzato dai validator")
        if exit_code != 0:
            raise TestFailure(f"governance in_progress failed: "
                              f"{err.strip()!r}")
        c3 = kit.make_candidate(
            p, m5.S6, tx_id="tx-crash-commit",
            structured=m5.funnel_structured(),
            proposed=m5.funnel_proposed())
        exit_code, out, err = kit.run_tm_cli(
            root, "advance-stage", "--project", p, "--stage", m5.S6,
            "--candidate", c3, "--gate-result", "approved",
            env_extra={"BPO_TX_TEST_CRASH": "before_commit"})
        if exit_code == 0:
            raise TestFailure("crash before commit must not exit 0")
        written = kit.snapshot_canonical(p)
        exit_code, out, err = kit.run_tm_cli(root, "recover", "--project", p)
        if exit_code != 0:
            raise TestFailure(f"recover (marker-only) failed: "
                              f"{err.strip()!r}")
        completed_journals = [
            j for j in (kit.read_json(path) for path in kit.find_journals(p))
            if j.get("recovery_action") == "completed_marker_only"]
        if not completed_journals:
            raise TestFailure("recover must complete the applying "
                              "transaction marker-only")
        if kit.snapshot_canonical(p) != written:
            raise TestFailure("marker-only recovery must not rewrite "
                              "canonical files")
        front = status_front(root, p)
        if front["current_stage"] != "07_operations-and-ip" or \
                m5.S6 not in front["completed_stages"]:
            raise TestFailure(f"after recovery: bad status {front}")

        # idempotenza del recover
        exit_code, _, err = kit.run_tm_cli(root, "recover", "--project", p)
        if exit_code != 0:
            raise TestFailure(f"idempotent recover failed: {err.strip()!r}")
        if kit.snapshot_canonical(p) != written:
            raise TestFailure("second recover must be a no-op")

        # matrice impact verde sul canonico ripreso
        for name, stage in (("validate_market_arithmetic", m5.S4),
                            ("validate_unit_economics", m5.S5),
                            ("validate_funnel_arithmetic", m5.S6),
                            ("validate_cross_stage_consistency", m5.S6)):
            exit_code, out, err = kit.run_validator_cli(
                root, name, project=p, stage=stage, phase="impact")
            if exit_code != 0:
                raise TestFailure(f"impact {name} after resume: exit "
                                  f"{exit_code} (out {out.strip()!r})")


def market_probe():
    """Structured minimale per le probe di riapertura dello Stage 4."""
    return {"market_model": {"tam_ref": "ASS-008", "sam_ref": "ASS-010",
                             "som_ref": "ASS-011"}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-RESUME ripresa a metà catena, rollback/recovery "
          "multi-stage, nessuna riapertura di stage approvati")


if __name__ == "__main__":
    main()
