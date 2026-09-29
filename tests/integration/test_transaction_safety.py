#!/usr/bin/env python3
"""T-TX-SAFETY — sicurezza del transaction manager: path containment, audit
transazionale, ciclo di vita del candidate, identità del lock.

- path containment: journal validato strutturalmente prima dell'uso;
  path assoluti, `..`, snapshot fuori da shared/.tx e componenti
  symlink/junction/reparse-point rifiutati (exit 3); nessun file esterno al
  progetto viene letto, scritto o cancellato da recovery/rollback.
- audit transazionale: shared/audit-log.jsonl fa parte del write-set;
  un failure della write audit non lascia mutazioni canoniche; crash prima
  del marker -> recovery marker-only con evento già presente; nessun doppio
  evento su retry/recovery; audit tamperato -> rollback.
- candidate lifecycle: dopo ogni esito terminale (commit, rejection,
  rollback, recovery) il candidate attivo non resta in <stage>/.working/;
  la copia di quarantena vive solo in shared/.tx/.
- PID reuse: il lock registra pid + process create identity + token;
  un lock con PID vivo ma identity diversa è stale, non held.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit


class TestFailure(AssertionError):
    pass


STAGE = "01_problem-and-need"


def make_tx_project(tmp, name):
    return kit.make_project(
        tmp, name=name, current_stage=STAGE, status="in_progress",
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


def apply_tm(root, project, candidate, env_extra=None):
    return kit.run_tm_cli(root, "apply", "--project", project, "--stage",
                          STAGE, "--candidate", candidate,
                          env_extra=env_extra)


def crash_applying(root, tmp, name):
    """Project with a crashed transaction stuck in state=applying."""
    project = make_tx_project(tmp, name)
    candidate = make_tx_candidate(project)
    exit_code, _, _ = apply_tm(
        root, project, candidate,
        env_extra={"BPO_TX_TEST_CRASH": "before_commit"})
    if exit_code == 0:
        raise TestFailure(f"{name}: crash hook did not fire")
    journals = kit.find_journals(project)
    if len(journals) != 1:
        raise TestFailure(f"{name}: expected exactly one journal")
    journal = kit.read_json(journals[0])
    if journal["state"] != "applying":
        raise TestFailure(f"{name}: setup expects state=applying")
    return project, journals[0], journal


def audit_events(project):
    path = Path(project) / "shared/audit-log.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line]


def applied_events(project, tx_id=None):
    return [e for e in audit_events(project)
            if e.get("action") == "tx_apply" and e.get("result") == "applied"
            and (tx_id is None or e.get("transaction_id") == tx_id)]


def make_link(link, target):
    """Symlink or NTFS junction; returns True if one was created."""
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return True
    except OSError:
        pass
    if os.name == "nt":
        try:
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
            return True
        except OSError:
            return False
    return False


def expect_recover_rejected(root, project, victim, victim_bytes, label):
    exit_code, out, err = kit.run_tm_cli(root, "recover", "--project", project)
    if exit_code != 3:
        raise TestFailure(f"{label}: tampered journal must exit 3, got "
                          f"{exit_code} (out {out.strip()!r} "
                          f"err {err.strip()!r})")
    if victim.exists() != (victim_bytes is not None):
        raise TestFailure(f"{label}: external victim was created/deleted")
    if victim_bytes is not None and victim.read_bytes() != victim_bytes:
        raise TestFailure(f"{label}: external victim was modified")


def run_c01(root, tmp):
    # ---- journal con path assoluto nel write-set --------------------------
    victim = tmp / "victim-outside.json"
    victim.write_text('{"external": true}\n', encoding="utf-8")
    victim_bytes = victim.read_bytes()

    project, jpath, journal = crash_applying(root, tmp, "c01a")
    journal["write_set"][0]["path"] = str(victim)
    kit.write_json(jpath, journal)
    expect_recover_rejected(root, project, victim, victim_bytes,
                            "containment absolute path")

    # ---- ../ nel write-set -------------------------------------------------
    project, jpath, journal = crash_applying(root, tmp, "c01b")
    journal["write_set"][0]["path"] = "../victim-outside.json"
    kit.write_json(jpath, journal)
    expect_recover_rejected(root, project, victim, victim_bytes,
                            "containment dotdot write-set")

    # ---- ../ nello snapshot path ------------------------------------------
    project, jpath, journal = crash_applying(root, tmp, "c01c")
    journal["snapshot_path"] = "../snap-outside"
    kit.write_json(jpath, journal)
    expect_recover_rejected(root, project, victim, victim_bytes,
                            "containment dotdot snapshot")

    # ---- snapshot path dentro il progetto ma fuori da shared/.tx ----------
    project, jpath, journal = crash_applying(root, tmp, "c01d")
    journal["snapshot_path"] = "02_customer-segmentation"
    kit.write_json(jpath, journal)
    exit_code, _, _ = kit.run_tm_cli(root, "recover", "--project", project)
    if exit_code != 3:
        raise TestFailure("path containment: snapshot path outside shared/.tx must "
                          f"exit 3, got {exit_code}")

    # ---- journal JSON valido ma strutturalmente incompleto -----------------
    project, jpath, journal = crash_applying(root, tmp, "c01e")
    del journal["write_set"]
    kit.write_json(jpath, journal)
    expect_recover_rejected(root, project, victim, victim_bytes,
                            "containment missing write_set")

    project, jpath, journal = crash_applying(root, tmp, "c01f")
    journal["write_set"] = [{"path": "shared/assumptions-register.json"}]
    kit.write_json(jpath, journal)
    expect_recover_rejected(root, project, victim, victim_bytes,
                            "containment write_set entry without hashes")

    project, jpath, journal = crash_applying(root, tmp, "c01g")
    journal["state"] = "totally-new-state"
    kit.write_json(jpath, journal)
    expect_recover_rejected(root, project, victim, victim_bytes,
                            "containment unknown journal state")

    # ---- symlink/junction escape -------------------------------------------
    outside = tmp / "outside-dir"
    outside.mkdir(exist_ok=True)
    outside_marker = outside / "structured-output.json"
    if outside_marker.exists():
        outside_marker.unlink()

    project, jpath, journal = crash_applying(root, tmp, "c01h")
    stage_dir = project / STAGE
    # sposta via la stage dir reale e rimpiazzala con un link verso l'esterno
    import shutil
    shutil.rmtree(stage_dir)
    if make_link(stage_dir, outside):
        exit_code, _, _ = kit.run_tm_cli(root, "recover", "--project", project)
        if exit_code != 3:
            raise TestFailure("path containment: reparse-point component must exit 3, "
                              f"got {exit_code}")
        if outside_marker.exists():
            raise TestFailure(
                "path containment: recovery wrote through a reparse point outside the "
                "project")
        leftovers = list(outside.iterdir())
        if leftovers:
            raise TestFailure(
                f"path containment: recovery leaked files outside the project: "
                f"{leftovers}")
    else:
        print("NOTE: symlink/junction non creabili in questo ambiente; "
              "controllo reparse-point saltato")


def run_r2c01(root, tmp):
    import shutil

    # ---- write-set con path interno NON autorizzato per mode/stage ---------
    # Un journal completo ma alterato non deve poter guidare restore/unlink su
    # un percorso interno non canonico (es. il .working di un altro stage).
    project, jpath, journal = crash_applying(root, tmp, "r2c01a")
    victim_internal = (project / "02_customer-segmentation" / ".working" /
                       "victim" / "leftover.json")
    victim_internal.parent.mkdir(parents=True, exist_ok=True)
    victim_internal.write_text('{"keep": true}\n', encoding="utf-8")
    journal["write_set"].append({
        "path": "02_customer-segmentation/.working/victim/leftover.json",
        "pre_hash": None, "post_hash": "0" * 64})
    kit.write_json(jpath, journal)
    exit_code, out, err = kit.run_tm_cli(root, "recover", "--project", project)
    if exit_code != 3:
        raise TestFailure(
            f"write-set containment: unauthorized write-set path must exit 3, got "
            f"{exit_code} (out {out.strip()!r})")
    if not victim_internal.exists():
        raise TestFailure(
            "write-set containment: recovery deleted an internal path via an unauthorized "
            "write-set entry")

    # ---- candidate_path alterato verso il .working di un altro stage -------
    project, jpath, journal = crash_applying(root, tmp, "r2c01b")
    other_working = (project / "03_value-proposition" / ".working" /
                     "other-tx")
    other_working.mkdir(parents=True, exist_ok=True)
    (other_working / "keep.json").write_text('{"keep": true}\n',
                                             encoding="utf-8")
    journal["candidate_path"] = str(other_working)
    kit.write_json(jpath, journal)
    exit_code, out, err = kit.run_tm_cli(root, "recover", "--project", project)
    if exit_code not in (0, 3):
        raise TestFailure(
            f"write-set containment: tampered candidate_path recovery exit {exit_code} "
            f"(out {out.strip()!r})")
    if not other_working.exists():
        raise TestFailure(
            "write-set containment: recovery removed another stage's .working via a "
            "tampered candidate_path")

    # ---- shared/.tx come junction/symlink verso l'esterno ------------------
    # Lock e journal devono passare dal boundary PRIMA di ogni I/O: se .tx è un
    # reparse point, non si scrive nulla fuori dal progetto.
    outside_tx = tmp / "outside-tx"
    outside_tx.mkdir(exist_ok=True)
    for leftover in list(outside_tx.iterdir()):
        if leftover.is_file():
            leftover.unlink()
    project = make_tx_project(tmp, "r2c01c")
    candidate = make_tx_candidate(project)
    tx_path = project / "shared" / ".tx"
    if tx_path.exists():
        shutil.rmtree(tx_path)
    if make_link(tx_path, outside_tx):
        exit_code, out, err = apply_tm(root, project, candidate)
        if exit_code == 0:
            raise TestFailure(
                "write-set containment: apply through a reparse-point shared/.tx must fail")
        leaked = list(outside_tx.iterdir())
        if leaked:
            raise TestFailure(
                "write-set containment: apply wrote lock/journal through the .tx reparse "
                f"point: {leaked}")
    else:
        print("NOTE: junction/symlink non creabili in questo ambiente; "
              "controllo reparse-point su shared/.tx saltato")


def run_h03(root, tmp):
    # ---- l'audit fa parte del write-set ------------------------------------
    p = make_tx_project(tmp, "h03a")
    c = make_tx_candidate(p)
    exit_code, out, err = apply_tm(root, p, c)
    if exit_code != 0:
        raise TestFailure(f"transactional audit happy path failed: {err.strip()!r} "
                          f"{out.strip()!r}")
    journal = kit.read_json(kit.find_journals(p)[0])
    write_paths = {e["path"] for e in journal["write_set"]}
    if "shared/audit-log.jsonl" not in write_paths:
        raise TestFailure(
            "transactional audit: shared/audit-log.jsonl must be part of the write-set")
    tx_id = journal["transaction_id"]
    if len(applied_events(p, tx_id)) != 1:
        raise TestFailure("transactional audit: exactly one applied event expected")

    # ---- crash sulla write dell'audit: nessuna mutazione canonica residua --
    p = make_tx_project(tmp, "h03b")
    c = make_tx_candidate(p)
    before = kit.snapshot_canonical(p)
    audit_before = audit_events(p)
    # write-set atteso: register, structured, handoff, status, audit (5)
    exit_code, _, _ = apply_tm(
        root, p, c, env_extra={"BPO_TX_TEST_CRASH": "after_writes:4"})
    if exit_code == 0:
        raise TestFailure("transactional audit: crash before the audit write expected")
    exit_code, _, err = kit.run_tm_cli(root, "recover", "--project", p)
    if exit_code != 0:
        raise TestFailure(f"transactional audit recover failed: {err.strip()!r}")
    journal = kit.read_json(kit.find_journals(p)[0])
    if journal["state"] != "rolled_back":
        raise TestFailure(
            "transactional audit: incomplete write-set (audit missing) must roll back, "
            f"got {journal['state']}")
    if kit.snapshot_canonical(p) != before:
        raise TestFailure(
            "transactional audit: canonical mutations survived an audit write failure")
    if applied_events(p):
        raise TestFailure("transactional audit: no applied event may exist after rollback")

    # ---- failure I/O in-process sulla write audit --------------------------
    p = make_tx_project(tmp, "h03c")
    c = make_tx_candidate(p)
    before = kit.snapshot_canonical(p)
    exit_code, out, _ = apply_tm(
        root, p, c, env_extra={"BPO_TX_TEST_FAIL_WRITE": "audit-log"})
    if exit_code == 0:
        raise TestFailure("transactional audit: induced audit I/O failure must not commit")
    if kit.snapshot_canonical(p) != before:
        raise TestFailure(
            "transactional audit: audit I/O failure left residual canonical mutations")
    if applied_events(p):
        raise TestFailure("transactional audit: applied event written despite I/O failure")
    committed = [j for j in kit.find_journals(p)
                 if kit.read_json(j)["state"] == "committed"]
    if committed:
        raise TestFailure("transactional audit: journal committed despite audit failure")
    # retry pulito: esattamente un evento applied
    c = make_tx_candidate(p, tx_hint="tx-retry")
    exit_code, _, err = apply_tm(root, p, c)
    if exit_code != 0:
        raise TestFailure(f"transactional audit retry failed: {err.strip()!r}")
    if len(applied_events(p)) != 1:
        raise TestFailure("transactional audit: retry must produce exactly one applied event")

    # ---- crash prima del marker: recovery marker-only, evento già presente -
    p = make_tx_project(tmp, "h03d")
    c = make_tx_candidate(p)
    exit_code, _, _ = apply_tm(
        root, p, c, env_extra={"BPO_TX_TEST_CRASH": "before_commit"})
    if exit_code == 0:
        raise TestFailure("transactional audit: before_commit crash expected")
    if len(applied_events(p)) != 1:
        raise TestFailure(
            "transactional audit: applied event must be written inside the write-set "
            "before the marker")
    exit_code, _, err = kit.run_tm_cli(root, "recover", "--project", p)
    if exit_code != 0:
        raise TestFailure(f"transactional audit marker-only recover failed: {err.strip()!r}")
    journal = kit.read_json(kit.find_journals(p)[0])
    if journal["state"] != "committed":
        raise TestFailure("transactional audit: complete write-set must be committed")
    if len(applied_events(p)) != 1:
        raise TestFailure("transactional audit: recovery duplicated the applied event")
    exit_code, _, _ = kit.run_tm_cli(root, "recover", "--project", p)
    if exit_code != 0:
        raise TestFailure("transactional audit: idempotent recover failed")
    if len(applied_events(p)) != 1:
        raise TestFailure("transactional audit: repeated recovery duplicated the event")

    # ---- audit tamperato dopo il crash -> rollback -------------------------
    p = make_tx_project(tmp, "h03e")
    c = make_tx_candidate(p)
    before = kit.snapshot_canonical(p)
    audit_pre = (p / "shared/audit-log.jsonl")
    exit_code, _, _ = apply_tm(
        root, p, c, env_extra={"BPO_TX_TEST_CRASH": "before_commit"})
    audit_pre.write_text("garbage\n", encoding="utf-8")
    exit_code, _, err = kit.run_tm_cli(root, "recover", "--project", p)
    if exit_code != 0:
        raise TestFailure(f"transactional audit tampered-audit recover failed: "
                          f"{err.strip()!r}")
    journal = kit.read_json(kit.find_journals(p)[0])
    if journal["state"] != "rolled_back":
        raise TestFailure(
            "transactional audit: tampered audit must cause rollback, not commit")
    if kit.snapshot_canonical(p) != before:
        raise TestFailure("transactional audit: rollback after audit tamper must restore "
                          "the canonical state")

    # ---- governance-status dentro il protocollo transazionale --------------
    p = make_tx_project(tmp, "h03f")
    exit_code, _, err = kit.run_tm_cli(
        root, "governance-status", "--project", p,
        "--updates", '{"status": "needs_revision"}',
        "--reason", "test governance journal")
    if exit_code != 0:
        raise TestFailure(f"governance update failed: {err.strip()!r}")
    journals = [kit.read_json(j) for j in kit.find_journals(p)]
    gov = [j for j in journals if j["state"] == "committed"
           and any(e["path"] == "shared/audit-log.jsonl"
                   for e in j.get("write_set", []))
           and any(e["path"] == "shared/project-status.md"
                   for e in j.get("write_set", []))]
    if not gov:
        raise TestFailure(
            "transactional audit: governance-status must run inside a journaled "
            "transaction whose write-set covers status + audit")

    # governance crash: lo status non resta mutato senza audit
    p = make_tx_project(tmp, "h03g")
    status_path = p / "shared/project-status.md"
    status_before = status_path.read_bytes()
    exit_code, _, _ = kit.run_tm_cli(
        root, "governance-status", "--project", p,
        "--updates", '{"status": "needs_revision"}',
        "--reason", "crash test",
        env_extra={"BPO_TX_TEST_CRASH": "after_writes:1"})
    if exit_code == 0:
        raise TestFailure("transactional audit: governance crash hook did not fire")
    exit_code, _, err = kit.run_tm_cli(root, "recover", "--project", p)
    if exit_code != 0:
        raise TestFailure(f"transactional audit governance recover failed: {err.strip()!r}")
    if status_path.read_bytes() != status_before:
        raise TestFailure(
            "transactional audit: interrupted governance write must be rolled back")


def run_m06(root, tmp):
    # ---- commit: candidate rimosso dalla posizione attiva ------------------
    p = make_tx_project(tmp, "m06a")
    c = make_tx_candidate(p)
    exit_code, _, err = apply_tm(root, p, c)
    if exit_code != 0:
        raise TestFailure(f"candidate lifecycle commit failed: {err.strip()!r}")
    if c.exists():
        raise TestFailure(
            "candidate lifecycle: candidate must not stay in .working/ after commit")
    journal = kit.read_json(kit.find_journals(p)[0])
    quarantine = journal.get("candidate_snapshot_path")
    if not quarantine or not str(quarantine).startswith("shared/.tx/"):
        raise TestFailure(
            "candidate lifecycle: the preserved candidate copy must live under shared/.tx/")
    if not (p / quarantine).is_dir():
        raise TestFailure("candidate lifecycle: quarantined candidate copy missing")

    # ---- rejection: candidate rimosso ---------------------------------------
    p = make_tx_project(tmp, "m06b")
    c = kit.make_candidate(
        p, STAGE, tx_id="tx-bad",
        structured={"problem_ref": "ASS-999"},
        proposed=[{"id": "P-ASS-001", "category": "market",
                   "statement": "x", "kind": "primary", "unit": "EUR",
                   "value": 1, "validation_status": "unvalidated"}])
    exit_code, _, _ = apply_tm(root, p, c)
    if exit_code == 0:
        raise TestFailure("candidate lifecycle: invalid candidate must be rejected")
    if c.exists():
        raise TestFailure(
            "candidate lifecycle: rejected candidate must not stay in .working/")

    # ---- rollback via recover: candidate rimosso ---------------------------
    p = make_tx_project(tmp, "m06c")
    c = make_tx_candidate(p)
    exit_code, _, _ = apply_tm(
        root, p, c, env_extra={"BPO_TX_TEST_CRASH": "after_writes:1"})
    if exit_code == 0:
        raise TestFailure("candidate lifecycle: crash hook did not fire")
    exit_code, _, err = kit.run_tm_cli(root, "recover", "--project", p)
    if exit_code != 0:
        raise TestFailure(f"candidate lifecycle recover failed: {err.strip()!r}")
    if c.exists():
        raise TestFailure(
            "candidate lifecycle: candidate must be removed after recovery rollback")

    # ---- recovery-commit: candidate rimosso --------------------------------
    p = make_tx_project(tmp, "m06d")
    c = make_tx_candidate(p)
    exit_code, _, _ = apply_tm(
        root, p, c, env_extra={"BPO_TX_TEST_CRASH": "before_commit"})
    exit_code, _, err = kit.run_tm_cli(root, "recover", "--project", p)
    if exit_code != 0:
        raise TestFailure(f"candidate lifecycle recover-commit failed: {err.strip()!r}")
    if kit.read_json(kit.find_journals(p)[0])["state"] != "committed":
        raise TestFailure("candidate lifecycle: recovery should have committed")
    if c.exists():
        raise TestFailure(
            "candidate lifecycle: candidate must be removed after recovery commit")
    working = p / STAGE / ".working"
    if working.exists() and any(working.rglob("*")):
        for leftover in working.rglob("*"):
            text = leftover.read_text(encoding="utf-8", errors="replace") \
                if leftover.is_file() else ""
            if "P-ASS-" in text:
                raise TestFailure(
                    "candidate lifecycle: P-ASS-* residue left reusable in .working/")

    # ---- lock held (nessuna transazione avviata): candidate preservato -----
    p = make_tx_project(tmp, "m06e")
    c = make_tx_candidate(p)
    tm = kit.load_module(root, kit.TRANSACTION_REL, "transaction_manager")
    tm.acquire_lock(p, "tx-holder")
    exit_code, _, _ = apply_tm(root, p, c)
    if exit_code == 0:
        raise TestFailure("candidate lifecycle: apply under foreign lock must fail")
    if not c.exists():
        raise TestFailure(
            "candidate lifecycle: lock rejection precedes the transaction and must not "
            "delete the candidate")
    tm.release_lock(p, "tx-holder")


def run_m07(root, tmp):
    tm = kit.load_module(root, kit.TRANSACTION_REL, "transaction_manager")

    # ---- il lock registra pid + create identity + token --------------------
    p = make_tx_project(tmp, "m07a")
    tm.acquire_lock(p, "tx-identity")
    info = kit.read_json(p / "shared/.tx/project.lock")
    for key in ("transaction_id", "pid", "created_at", "pid_create_time",
                "token"):
        if key not in info:
            raise TestFailure(f"lock identity: lock file missing {key}")
    tm.release_lock(p, "tx-identity")

    # ---- PID vivo ma identity diversa => stale, non held --------------------
    p = make_tx_project(tmp, "m07b")
    c = make_tx_candidate(p)
    alive_pid = os.getpid()  # certamente vivo per tutta la durata del test
    (p / "shared/.tx").mkdir(parents=True, exist_ok=True)
    kit.write_json(p / "shared/.tx/project.lock", {
        "transaction_id": "tx-reused-pid",
        "pid": alive_pid,
        "pid_create_time": "bogus-identity-from-previous-boot",
        "token": "deadbeef",
        "created_at": "2026-07-15T00:00:00+00:00",
    })
    exit_code, out, _ = apply_tm(root, p, c)
    if exit_code == 0:
        raise TestFailure("lock identity: reused-PID lock must not be silently taken")
    codes = {e["code"] for e in kit.tm_result(out, "m07")["errors"]}
    if "lock_stale" not in codes:
        raise TestFailure(
            f"lock identity: PID-reuse mismatch must be lock_stale, got {codes}")
    exit_code, _, err = kit.run_tm_cli(root, "recover", "--project", p)
    if exit_code != 0:
        raise TestFailure(f"lock identity recover failed: {err.strip()!r}")
    if (p / "shared/.tx/project.lock").exists():
        raise TestFailure("lock identity: recover must clear the identity-mismatch "
                          "lock")
    exit_code, _, err = apply_tm(root, p, c)
    if exit_code != 0:
        raise TestFailure(f"lock identity apply after recover failed: {err.strip()!r}")

    # ---- PID vivo con identity corretta => held ------------------------------
    p = make_tx_project(tmp, "m07c")
    c = make_tx_candidate(p)
    identity = tm._process_create_time(alive_pid)
    (p / "shared/.tx").mkdir(parents=True, exist_ok=True)
    kit.write_json(p / "shared/.tx/project.lock", {
        "transaction_id": "tx-alive",
        "pid": alive_pid,
        "pid_create_time": identity,
        "token": "cafebabe",
        "created_at": "2026-07-15T00:00:00+00:00",
    })
    exit_code, out, _ = apply_tm(root, p, c)
    if exit_code == 0:
        raise TestFailure("lock identity: live matching-identity lock must block")
    codes = {e["code"] for e in kit.tm_result(out, "m07-held")["errors"]}
    if "lock_held" not in codes:
        raise TestFailure(f"lock identity: expected lock_held, got {codes}")


def run(root):
    with tempfile.TemporaryDirectory(prefix="bpo-txsafe-") as tmp:
        tmp = Path(tmp)
        run_c01(root, tmp)
        run_r2c01(root, tmp)
        run_h03(root, tmp)
        run_m06(root, tmp)
        run_m07(root, tmp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-TX-SAFETY containment + audit protocol + candidate "
          "lifecycle + lock identity")


if __name__ == "__main__":
    main()
