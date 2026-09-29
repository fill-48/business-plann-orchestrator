#!/usr/bin/env python3
"""T-TX-VALIDATION-BINDING + T-TX-CONTENT-RECOVERY + T-TX-LOCK + scritture di
governance (contratto di enforcement del transaction manager).

- T-TX-VALIDATION-BINDING: un orchestratore non può bypassare i validator
  invocando direttamente il transaction manager (riesecuzione autonoma degli
  egress); un candidate modificato dopo una validazione precedente viene
  rifiutato; un report riferito a un hash diverso viene rifiutato.
- T-TX-CONTENT-RECOVERY: recovery mai per sola esistenza dei file — un file
  del write-set esistente ma alterato/incompleto produce rollback, non un
  falso commit.
- T-TX-LOCK: due tentativi concorrenti sullo stesso progetto -> soltanto uno
  entra in applying; lock con transaction id/pid/timestamp; rilascio su
  commit e rollback; gestione conservativa dei lock stale.
- Governance: project-status.md modificabile solo via entry point
  governance-only, con audit event append-only.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit


class TestFailure(AssertionError):
    pass


STAGE = "01_problem-and-need"


def make_tx_project(tmp, name, status="in_progress"):
    return kit.make_project(
        tmp, name=name, current_stage=STAGE, status=status,
        assumptions=[kit.base_assumption(1), kit.base_assumption(2)])


def make_tx_candidate(project, tx_hint="tx-a"):
    return kit.make_candidate(
        project, STAGE, tx_id=tx_hint,
        structured={"problem_statement": {"id": "SEG-001",
                                          "problem_ref": "ASS-001",
                                          "revenue_ref": "P-ASS-001"}},
        proposed=[{"id": "P-ASS-001", "category": "market",
                   "statement": "Driver ricavo", "kind": "primary",
                   "unit": "EUR", "value": 2000,
                   "validation_status": "unvalidated"}],
        handoff="# Handoff\n\nDriver: P-ASS-001.\n")


def apply_tm(root, project, candidate, extra=None, env_extra=None):
    args = ["apply", "--project", project, "--stage", STAGE,
            "--candidate", candidate]
    if extra:
        args += extra
    return kit.run_tm_cli(root, *args, env_extra=env_extra)


def read_ids(project):
    return {e["id"] for e in
            kit.read_json(project / "shared/assumptions-register.json")}


def audit_events(project):
    path = project / "shared/audit-log.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line]


def run(root):
    tm = kit.load_module(root, kit.TRANSACTION_REL, "transaction_manager")

    with tempfile.TemporaryDirectory(prefix="bpo-txe-") as tmp:
        tmp = Path(tmp)

        # -------------------------------------------- T-TX-VALIDATION-BINDING
        # (a) bypass: gate egress FAIL (conflitto pendente); l'orchestratore
        # invoca direttamente il TM senza aver eseguito i validator.
        p1 = make_tx_project(tmp, "p1",
                             status="conflict_awaiting_confirmation")
        c1 = make_tx_candidate(p1)
        before = kit.snapshot_canonical(p1)
        exit_code, out, err = apply_tm(root, p1, c1)
        if exit_code == 0:
            raise TestFailure("bypass: TM applied without passing validators")
        result = kit.tm_result(out, "bypass")
        if result["result"] != "rejected":
            raise TestFailure(f"bypass: result {result['result']}")
        codes = {e["code"] for e in result["errors"]}
        if "validation_failed" not in codes:
            raise TestFailure(f"bypass: expected validation_failed, {codes}")
        if kit.snapshot_canonical(p1) != before:
            raise TestFailure("bypass: canonical state mutated")
        if "ASS-003" in read_ids(p1):
            raise TestFailure("bypass: ASS allocated despite FAIL")
        journals = [kit.read_json(j) for j in kit.find_journals(p1)]
        if not journals or journals[0]["state"] != "rolled_back":
            raise TestFailure("bypass: journal must be rolled_back")
        if any(j["state"] in ("applying", "committed") for j in journals):
            raise TestFailure("bypass: no journal may reach applying")
        # il journal registra la riesecuzione autonoma dei validator
        if not journals[0].get("validation"):
            raise TestFailure(
                "bypass: journal must record the autonomous validator re-run")

        # (b) candidate modificato dopo una validazione precedente
        p2 = make_tx_project(tmp, "p2")
        c2 = make_tx_candidate(p2)
        report_path = tmp / "p2-report.json"
        kit.write_json(report_path, {
            "candidate_hash": tm.hash_candidate(c2),
            "results": [{"validator": "validate_stage_gate", "exit_code": 0}],
        })
        # mutazione post-validazione (il contenuto resta valido di per sé)
        kit.write_json(c2 / "structured-output.json",
                       {"problem_statement": {"id": "SEG-001",
                                              "problem_ref": "ASS-002",
                                              "revenue_ref": "P-ASS-001"}})
        exit_code, out, _ = apply_tm(root, p2, c2,
                                     extra=["--report", report_path])
        if exit_code == 0:
            raise TestFailure("stale report: TM accepted a modified candidate")
        result = kit.tm_result(out, "stale report")
        codes = {e["code"] for e in result["errors"]}
        if "report_hash_mismatch" not in codes:
            raise TestFailure(f"stale report: expected report_hash_mismatch, "
                              f"got {codes}")
        if read_ids(p2) != {"ASS-001", "ASS-002"}:
            raise TestFailure("stale report: register mutated")

        # (c) report riferito a un hash differente (forgiato)
        # (la rejection precedente ha rimosso il candidate attivo)
        c2 = make_tx_candidate(p2, tx_hint="tx-b")
        kit.write_json(report_path, {"candidate_hash": "f" * 64,
                                     "results": []})
        exit_code, out, _ = apply_tm(root, p2, c2,
                                     extra=["--report", report_path])
        if exit_code == 0:
            raise TestFailure("forged report accepted")
        codes = {e["code"] for e in kit.tm_result(out, "forged")["errors"]}
        if "report_hash_mismatch" not in codes:
            raise TestFailure(f"forged report: {codes}")

        # controllo positivo: report coerente + validator verdi -> applied
        c2 = make_tx_candidate(p2, tx_hint="tx-c")
        kit.write_json(report_path, {"candidate_hash": tm.hash_candidate(c2),
                                     "results": []})
        exit_code, out, err = apply_tm(root, p2, c2,
                                       extra=["--report", report_path])
        if exit_code != 0:
            raise TestFailure(f"positive control failed: {err.strip()!r} "
                              f"{out.strip()!r}")
        journal = [kit.read_json(j) for j in kit.find_journals(p2)
                   if kit.read_json(j)["state"] == "committed"][0]
        reruns = {v["validator"]: v["exit_code"]
                  for v in journal["validation"]}
        if reruns != {"validate_stage_gate": 0,
                      "validate_referential_integrity": 0}:
            raise TestFailure(f"TM must re-run every egress validator: "
                              f"{reruns}")

        # ---------------------------------------------- T-TX-CONTENT-RECOVERY
        # file scritto ma alterato dopo il crash: rollback, non falso commit
        p3 = make_tx_project(tmp, "p3")
        c3 = make_tx_candidate(p3)
        before = kit.snapshot_canonical(p3)
        exit_code, _, _ = apply_tm(
            root, p3, c3, env_extra={"BPO_TX_TEST_CRASH": "before_commit"})
        if exit_code == 0:
            raise TestFailure("content-recovery setup: crash expected")
        target = p3 / STAGE / "structured-output.json"
        target.write_text(
            target.read_text(encoding="utf-8")[:20], encoding="utf-8")
        exit_code, out, err = kit.run_tm_cli(root, "recover", "--project", p3)
        if exit_code != 0:
            raise TestFailure(f"content recovery failed: {err.strip()!r}")
        journal = kit.read_json(kit.find_journals(p3)[0])
        if journal["state"] != "committed" and journal["state"] != "rolled_back":
            raise TestFailure(f"unexpected journal state {journal['state']}")
        if journal["state"] == "committed":
            raise TestFailure(
                "tampered write-set was falsely committed (existence-only "
                "recovery)")
        if kit.snapshot_canonical(p3) != before:
            raise TestFailure(
                "content recovery must restore the pre-transaction state")

        # file del write-set cancellato: rollback
        p4 = make_tx_project(tmp, "p4")
        c4 = make_tx_candidate(p4)
        before = kit.snapshot_canonical(p4)
        exit_code, _, _ = apply_tm(
            root, p4, c4, env_extra={"BPO_TX_TEST_CRASH": "before_commit"})
        (p4 / STAGE / "handoff.md").unlink()
        exit_code, _, err = kit.run_tm_cli(root, "recover", "--project", p4)
        if exit_code != 0:
            raise TestFailure(f"missing-file recovery failed: {err.strip()!r}")
        if kit.read_json(kit.find_journals(p4)[0])["state"] != "rolled_back":
            raise TestFailure("missing write-set file must cause rollback")
        if kit.snapshot_canonical(p4) != before:
            raise TestFailure("rollback after deletion must restore state")

        # --------------------------------------------------------- T-TX-LOCK
        p5 = make_tx_project(tmp, "p5")
        c5 = make_tx_candidate(p5)
        tm.acquire_lock(p5, "tx-concurrent")
        lock_file = p5 / "shared/.tx/project.lock"
        info = kit.read_json(lock_file)
        for key in ("transaction_id", "pid", "created_at"):
            if key not in info:
                raise TestFailure(f"lock file missing {key}")
        exit_code, out, _ = apply_tm(root, p5, c5)
        if exit_code == 0:
            raise TestFailure("second transaction entered despite the lock")
        codes = {e["code"] for e in kit.tm_result(out, "lock")["errors"]}
        if "lock_held" not in codes:
            raise TestFailure(f"expected lock_held, got {codes}")
        if kit.find_journals(p5):
            raise TestFailure(
                "locked-out transaction must not reach the journal "
                "(only one may enter applying)")
        tm.release_lock(p5, "tx-concurrent")
        exit_code, _, err = apply_tm(root, p5, c5)
        if exit_code != 0:
            raise TestFailure(f"apply after release failed: {err.strip()!r}")
        committed = [kit.read_json(j) for j in kit.find_journals(p5)
                     if kit.read_json(j)["state"] == "committed"]
        if len(committed) != 1:
            raise TestFailure("exactly one transaction may reach committed")
        if lock_file.exists():
            raise TestFailure("lock not released after commit")

        # lock rilasciato anche su rejected/rollback
        p6 = make_tx_project(tmp, "p6",
                             status="conflict_awaiting_confirmation")
        c6 = make_tx_candidate(p6)
        exit_code, _, _ = apply_tm(root, p6, c6)
        if exit_code == 0:
            raise TestFailure("p6 apply should be rejected")
        if (p6 / "shared/.tx/project.lock").exists():
            raise TestFailure("lock not released after rejection")

        # lock stale di processo morto: conservativo su apply, recover risolve
        p7 = make_tx_project(tmp, "p7")
        c7 = make_tx_candidate(p7)
        proc = subprocess.run([sys.executable, "-c",
                               "import os; print(os.getpid())"],
                              capture_output=True, text=True)
        dead_pid = int(proc.stdout.strip())
        (p7 / "shared/.tx").mkdir(parents=True, exist_ok=True)
        kit.write_json(p7 / "shared/.tx/project.lock",
                       {"transaction_id": "tx-dead", "pid": dead_pid,
                        "created_at": "2026-07-15T00:00:00+00:00"})
        exit_code, out, _ = apply_tm(root, p7, c7)
        if exit_code == 0:
            raise TestFailure("stale lock must not be silently taken by apply")
        codes = {e["code"] for e in kit.tm_result(out, "stale")["errors"]}
        if "lock_stale" not in codes:
            raise TestFailure(f"expected lock_stale, got {codes}")
        exit_code, _, err = kit.run_tm_cli(root, "recover", "--project", p7)
        if exit_code != 0:
            raise TestFailure(f"recover on stale lock failed: {err.strip()!r}")
        if (p7 / "shared/.tx/project.lock").exists():
            raise TestFailure("recover must clear the provably-dead lock")
        exit_code, _, err = apply_tm(root, p7, c7)
        if exit_code != 0:
            raise TestFailure(f"apply after stale recovery failed: "
                              f"{err.strip()!r}")

        # lock illeggibile: nessuna rimozione automatica
        p8 = make_tx_project(tmp, "p8")
        c8 = make_tx_candidate(p8)
        (p8 / "shared/.tx").mkdir(parents=True, exist_ok=True)
        (p8 / "shared/.tx/project.lock").write_text("garbage",
                                                    encoding="utf-8")
        exit_code, out, _ = apply_tm(root, p8, c8)
        if exit_code == 0:
            raise TestFailure("unreadable lock must block, not be removed")
        if not (p8 / "shared/.tx/project.lock").exists():
            raise TestFailure("unreadable lock must never be auto-removed")

        # ------------------------------------------------- governance writes
        p9 = make_tx_project(tmp, "p9")
        exit_code, out, err = kit.run_tm_cli(
            root, "governance-status", "--project", p9,
            "--updates", '{"status": "conflict_awaiting_confirmation"}',
            "--reason", "FAIL cross-check: conflitto su ASS-001")
        if exit_code != 0:
            raise TestFailure(f"governance update failed: {err.strip()!r}")
        fw = kit.load_module(root, kit.VALIDATORS_REL, "_framework")
        front = fw.parse_front_matter(
            (p9 / "shared/project-status.md").read_text(encoding="utf-8"))
        if front["status"] != "conflict_awaiting_confirmation":
            raise TestFailure("governance update not applied")
        events = audit_events(p9)
        gov = [e for e in events
               if e.get("action") == "governance_status_update"]
        if not gov:
            raise TestFailure("governance update must append an audit event")
        # stato non ammesso -> rifiuto
        exit_code, _, _ = kit.run_tm_cli(
            root, "governance-status", "--project", p9,
            "--updates", '{"status": "not_applicable"}',
            "--reason", "tentativo vietato")
        if exit_code == 0:
            raise TestFailure("not_applicable must be rejected (not a gate state)")
        # campo fuori dal perimetro governance -> rifiuto
        exit_code, _, _ = kit.run_tm_cli(
            root, "governance-status", "--project", p9,
            "--updates", '{"current_stage": "06_go-to-market"}',
            "--reason", "salto di stage")
        if exit_code == 0:
            raise TestFailure("current_stage must not be governable directly")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-TX-VALIDATION-BINDING + T-TX-CONTENT-RECOVERY + T-TX-LOCK")


if __name__ == "__main__":
    main()
