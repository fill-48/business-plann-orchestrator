#!/usr/bin/env python3
"""T-TX-MODES — mode del journal e allow-list mode-specific del write-set.

Un'allow-list solo per stage permetterebbe a qualunque mode di scrivere
register, conditions, status e audit. L'allow-list è invece
**mode-specific**:

| mode                | paths ammessi                                              |
|---------------------|------------------------------------------------------------|
| apply / advance     | register, conditions, status, audit, <stage>/structured-output.json, <stage>/handoff.md |
| update_assumption   | register, decisions-register, decision-log, status, audit  |
| resolve_condition   | conditions, decisions-register, decision-log, status, audit |
| None (governance)   | status, audit                                              |

Invarianti verificate qui:
- i mode di base (`None`/`apply`/`advance`) sono accettati;
- i mode `update_assumption` e `resolve_condition` sono accettati con il
  proprio write-set;
- un path fuori dall'allow-list del PROPRIO mode è journal corrotto (exit 3),
  anche quando sarebbe legittimo per un altro mode — in particolare
  `shared/decisions-register.json` è ammesso SOLO nei mode update/resolve;
- un mode ignoto è journal corrotto (exit 3), sia via funzione pura sia via
  CLI `recover`.

Discriminante di mutazione: rimuovendo la specializzazione per mode (cioè
tornando a un'unica allow-list per stage) i casi «path legittimo per un
altro mode» passerebbero e questo test diventa RED.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit


class TestFailure(AssertionError):
    pass


STAGE = "01_problem-and-need"

REGISTER = "shared/assumptions-register.json"
CONDITIONS = "shared/conditions-register.json"
DECISIONS = "shared/decisions-register.json"
DECISION_LOG = "shared/decision-log.md"
STATUS = "shared/project-status.md"
AUDIT = "shared/audit-log.jsonl"


def journal(mode, paths, stage=STAGE, state="applying"):
    return {
        "transaction_id": "20260720T000000Z-abcdef0123",
        "project": "unused",
        "stage": stage,
        "mode": mode,
        "state": state,
        "snapshot_path": "shared/.tx/20260720T000000Z-abcdef0123-snapshot",
        "write_set": [{"path": p, "pre_hash": None, "post_hash": "a" * 64}
                      for p in paths],
        "pass_map": {},
        "timestamps": {"preparing": "2026-07-20T00:00:00+00:00"},
    }


def expect_ok(tm, mode, paths, label, stage=STAGE):
    doc = journal(mode, paths, stage=stage)
    try:
        tm.validate_journal(doc, Path("tx.json"))
    except tm.TransactionError as exc:
        raise TestFailure(f"{label}: journal valido rifiutato: {exc.message}")


def expect_corrupted(tm, mode, paths, label, stage=STAGE):
    doc = journal(mode, paths, stage=stage)
    try:
        tm.validate_journal(doc, Path("tx.json"))
    except tm.TransactionError as exc:
        if exc.exit_code != 3:
            raise TestFailure(
                f"{label}: atteso exit 3, ottenuto {exc.exit_code}")
        return
    raise TestFailure(f"{label}: journal corrotto accettato")


def run(root):
    tm = kit.load_module(root, kit.TRANSACTION_REL, "transaction_manager")

    # ------------------------------------------------ mode di base
    expect_ok(tm, None, [STATUS, AUDIT], "governance (mode None)")
    expect_ok(tm, "apply",
              [REGISTER, CONDITIONS, f"{STAGE}/structured-output.json",
               f"{STAGE}/handoff.md", STATUS, AUDIT], "apply")
    expect_ok(tm, "advance",
              [REGISTER, CONDITIONS, STATUS, AUDIT], "advance")

    # ------------------------------ mode update_assumption/resolve_condition
    expect_ok(tm, "update_assumption",
              [REGISTER, DECISIONS, DECISION_LOG, STATUS, AUDIT],
              "update_assumption write-set")
    expect_ok(tm, "resolve_condition",
              [CONDITIONS, DECISIONS, DECISION_LOG, STATUS, AUDIT],
              "resolve_condition write-set")

    # ------------------------------------- allow-list specifica del mode
    # decisions-register/decision-log NON sono ammessi nei mode di base
    expect_corrupted(tm, "apply", [REGISTER, DECISIONS, STATUS, AUDIT],
                     "decisions-register in mode apply")
    expect_corrupted(tm, "advance", [REGISTER, DECISION_LOG, STATUS, AUDIT],
                     "decision-log in mode advance")
    expect_corrupted(tm, None, [STATUS, AUDIT, DECISIONS],
                     "decisions-register in governance")
    # governance non tocca i registri
    expect_corrupted(tm, None, [REGISTER, STATUS, AUDIT],
                     "register in governance")
    # update_assumption non tocca il conditions-register...
    expect_corrupted(tm, "update_assumption",
                     [REGISTER, CONDITIONS, DECISIONS, STATUS, AUDIT],
                     "conditions in mode update_assumption")
    # ...né gli output di stage
    expect_corrupted(tm, "update_assumption",
                     [REGISTER, DECISIONS, f"{STAGE}/structured-output.json",
                      STATUS, AUDIT],
                     "structured-output in mode update_assumption")
    # resolve_condition non tocca l'assumptions-register
    expect_corrupted(tm, "resolve_condition",
                     [CONDITIONS, REGISTER, DECISIONS, STATUS, AUDIT],
                     "register in mode resolve_condition")

    # -------------------------------------- path duplicati nel write-set
    # Due entry sullo stesso path sono impossibili per
    # costruzione (il write-set nasce da un dict) e possono provenire solo da
    # un journal alterato a mano. La difesa a valle (verify + restore) è già
    # fail-closed, ma il journal va rifiutato come strutturalmente corrotto
    # PRIMA di ogni recovery o scrittura.
    expect_corrupted(tm, "update_assumption",
                     [REGISTER, REGISTER, DECISIONS, DECISION_LOG, STATUS,
                      AUDIT],
                     "path duplicato nel write-set update_assumption")
    expect_corrupted(tm, "resolve_condition",
                     [CONDITIONS, DECISIONS, DECISIONS, DECISION_LOG, STATUS,
                      AUDIT],
                     "path duplicato nel write-set resolve_condition")
    expect_corrupted(tm, "apply", [REGISTER, CONDITIONS, STATUS, AUDIT, AUDIT],
                     "path duplicato nel write-set apply")

    # ------------------------------------------------------ mode ignoto
    expect_corrupted(tm, "frobnicate", [STATUS, AUDIT], "mode sconosciuto")
    expect_corrupted(tm, "update-assumption", [REGISTER, DECISIONS, STATUS,
                                               AUDIT],
                     "mode con trattino invece di underscore")

    # ------------------------------------------- percorso reale: recover
    with tempfile.TemporaryDirectory(prefix="bpo-modes-") as tmp:
        project = kit.make_project(Path(tmp), name="modes",
                                   current_stage=STAGE, status="in_progress")
        tx_dir = project / "shared/.tx"
        tx_dir.mkdir(parents=True, exist_ok=True)
        kit.write_json(tx_dir / "tx-unknown-mode.json",
                       journal("frobnicate", [STATUS, AUDIT]))
        exit_code, _, _ = kit.run_tm_cli(root, "recover", "--project", project)
        if exit_code != 3:
            raise TestFailure(
                f"recover su journal con mode ignoto: atteso exit 3, "
                f"ottenuto {exit_code}")

        (tx_dir / "tx-unknown-mode.json").unlink()
        kit.write_json(tx_dir / "tx-bad-path.json",
                       journal("update_assumption",
                               [REGISTER, CONDITIONS, STATUS, AUDIT]))
        exit_code, _, _ = kit.run_tm_cli(root, "recover", "--project", project)
        if exit_code != 3:
            raise TestFailure(
                f"recover su write-set fuori allow-list del mode: atteso "
                f"exit 3, ottenuto {exit_code}")

        (tx_dir / "tx-bad-path.json").unlink()
        before = kit.snapshot_canonical(project)
        kit.write_json(tx_dir / "tx-dup-path.json",
                       journal("update_assumption",
                               [REGISTER, REGISTER, DECISIONS, DECISION_LOG,
                                STATUS, AUDIT]))
        exit_code, _, _ = kit.run_tm_cli(root, "recover", "--project", project)
        if exit_code != 3:
            raise TestFailure(
                f"recover su write-set con path duplicato: atteso exit 3, "
                f"ottenuto {exit_code}")
        if kit.snapshot_canonical(project) != before:
            raise TestFailure(
                "un journal con path duplicato deve essere rifiutato prima "
                "di qualsiasi recovery o scrittura")
        if kit.read_json(tx_dir / "tx-dup-path.json")["state"] != "applying":
            raise TestFailure(
                "il journal corrotto non va finalizzato: nessuna transizione "
                "di stato dopo il rifiuto strutturale")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-TX-MODES journal modes + mode-specific write-set allow-list")


if __name__ == "__main__":
    main()
