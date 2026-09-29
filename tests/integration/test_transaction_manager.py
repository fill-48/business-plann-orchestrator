#!/usr/bin/env python3
"""T-TX-ROLLBACK + T-TX-RECOVERY + T-PASS-ALLOCATION — transaction_manager.

- T-TX-ROLLBACK: una transazione interrotta con `applying` incompleto viene
  ripristinata dallo snapshot al resume; nessuna scrittura canonica parziale
  sopravvive.
- T-TX-RECOVERY: una transazione `applying` completa (tutti i file canonici
  scritti, incluso project-status.md) ma priva del marker `committed` viene
  completata in sicurezza scrivendo solo il marker (idempotente).
- T-PASS-ALLOCATION: allocazione P-ASS-* -> ASS-* deterministica in fase
  applying; nessun id consumato su FAIL o dopo rollback; sostituzione di
  tutti i riferimenti; journal con write-set, hash e pass_map.

Il TM è invocato via CLI (subprocess), come farebbero i workflow; i crash
sono simulati con l'hook di test BPO_TX_TEST_CRASH (os._exit, il lock resta
sul disco come in un crash reale).
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit
import test_market_arithmetic as market


class TestFailure(AssertionError):
    pass


STAGE = "01_problem-and-need"


def make_tx_project(tmp, name):
    return kit.make_project(
        tmp, name=name, current_stage=STAGE, status="in_progress",
        assumptions=[kit.base_assumption(1), kit.base_assumption(2)])


def proposed_entries():
    return [
        {
            "id": "P-ASS-001",
            "category": "market",
            "variable": "som_y1_revenue",
            "statement": "Ricavo SOM Y1",
            "kind": "derived",
            "unit": "EUR",
            "currency": "EUR",
            "period": "Y1",
            "scenario": "base",
            "derivation": {
                "formula": "customers * arpa",
                "variables": {"customers": "P-ASS-002", "arpa": "ASS-002"},
                "method": "bottom_up",
            },
            "value": 2000,
            "evidence_classification": "model_estimate",
            "validation_status": "unvalidated",
        },
        {
            "id": "P-ASS-002",
            "category": "market",
            "variable": "customers_y1",
            "statement": "Clienti Y1",
            "kind": "primary",
            "unit": "count",
            "value": 100,
            "validation_status": "unvalidated",
        },
    ]


def make_tx_candidate(project, tx_hint="tx-a"):
    return kit.make_candidate(
        project, STAGE, tx_id=tx_hint,
        structured={"problem_statement": {
            "id": "SEG-001",
            "problem_ref": "ASS-001",
            "revenue_ref": "P-ASS-001",
        }},
        proposed=proposed_entries(),
        handoff="# Handoff\n\nRicavo proposto: P-ASS-001.\n")


def apply_tm(root, project, candidate, env_extra=None):
    return kit.run_tm_cli(root, "apply", "--project", project, "--stage",
                          STAGE, "--candidate", candidate,
                          env_extra=env_extra)


def read_register(project):
    return kit.read_json(project / "shared/assumptions-register.json")


def canonical_text(project):
    chunks = []
    for p in sorted(Path(project).rglob("*")):
        rel = p.relative_to(project).as_posix()
        if not p.is_file() or rel.startswith("shared/.tx/") \
                or "/.working/" in rel:
            continue
        chunks.append(p.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def committed_journal(project, label):
    journals = kit.find_journals(project)
    if len(journals) != 1:
        raise TestFailure(f"{label}: expected 1 journal, got {len(journals)}")
    journal = kit.read_json(journals[0])
    return journal


def run(root):
    tm_path = root / kit.TRANSACTION_REL / "transaction_manager.py"
    if not tm_path.exists():
        raise TestFailure("missing module: transaction/transaction_manager.py")

    with tempfile.TemporaryDirectory(prefix="bpo-tx-") as tmp:
        tmp = Path(tmp)

        # ---------------------------------------------- T-PASS-ALLOCATION
        p1 = make_tx_project(tmp, "p1")
        c1 = make_tx_candidate(p1)
        exit_code, out, err = apply_tm(root, p1, c1)
        if exit_code != 0:
            raise TestFailure(f"apply happy path: exit {exit_code} "
                              f"(out: {out.strip()!r} err: {err.strip()!r})")
        result = kit.tm_result(out, "apply happy path")
        if result["result"] != "applied":
            raise TestFailure(f"apply result: {result['result']}")

        journal = committed_journal(p1, "T-PASS-ALLOCATION")
        for key in ("transaction_id", "project", "stage", "candidate_path",
                    "candidate_hash", "state", "snapshot_path", "write_set",
                    "pass_map", "timestamps"):
            if key not in journal:
                raise TestFailure(f"journal missing field: {key}")
        if journal["state"] != "committed":
            raise TestFailure(f"journal state: {journal['state']}")
        if journal["pass_map"] != {"P-ASS-001": "ASS-003",
                                   "P-ASS-002": "ASS-004"}:
            raise TestFailure(
                f"deterministic ascending allocation: {journal['pass_map']}")
        for entry in journal["write_set"]:
            for key in ("path", "pre_hash", "post_hash"):
                if key not in entry:
                    raise TestFailure(f"write_set entry missing {key}")
        write_paths = {e["path"] for e in journal["write_set"]}
        if "shared/project-status.md" not in write_paths:
            raise TestFailure(
                "project-status.md must be part of the same transaction")

        register = read_register(p1)
        by_id = {e["id"]: e for e in register}
        if set(by_id) != {"ASS-001", "ASS-002", "ASS-003", "ASS-004"}:
            raise TestFailure(f"allocated ids wrong: {sorted(by_id)}")
        derived = by_id["ASS-003"]
        if derived["derivation"]["variables"] != {"customers": "ASS-004",
                                                  "arpa": "ASS-002"}:
            raise TestFailure("P-ASS refs in derivation not substituted")
        structured = kit.read_json(p1 / STAGE / "structured-output.json")
        if structured["problem_statement"]["revenue_ref"] != "ASS-003":
            raise TestFailure("P-ASS ref in structured-output not substituted")
        text = canonical_text(p1)
        if "P-ASS" in text:
            raise TestFailure("P-ASS-* survived in canonical files")
        if "ASS-003" not in (p1 / STAGE / "handoff.md").read_text(
                encoding="utf-8"):
            raise TestFailure("handoff.md not rewritten with allocated ids")

        audit = p1 / "shared/audit-log.jsonl"
        if not audit.exists():
            raise TestFailure("audit-log.jsonl missing after apply")
        events = [json.loads(line) for line in
                  audit.read_text(encoding="utf-8").splitlines() if line]
        applied_events = [e for e in events if e.get("result") == "applied"]
        if not applied_events:
            raise TestFailure("no 'applied' audit event")
        for key in ("transaction_id", "stage", "action", "result",
                    "affected_refs"):
            if key not in applied_events[-1]:
                raise TestFailure(f"audit event missing {key}")
        if (p1 / "shared/.tx/project.lock").exists():
            raise TestFailure("lock not released after commit")

        # Sequential transaction reads the register at applying time
        c1b = kit.make_candidate(
            p1, STAGE, tx_id="tx-b",
            structured={"extra_ref": "P-ASS-001"},
            proposed=[{"id": "P-ASS-001", "category": "market",
                       "statement": "Nuovo driver", "kind": "primary",
                       "unit": "count", "value": 5,
                       "validation_status": "unvalidated"}])
        exit_code, out, err = apply_tm(root, p1, c1b)
        if exit_code != 0:
            raise TestFailure(f"second apply failed: {err.strip()!r}")
        if "ASS-005" not in {e["id"] for e in read_register(p1)}:
            raise TestFailure("second transaction must allocate ASS-005")

        # FAIL consumes no ids: broken candidate first, then a valid one
        p2 = make_tx_project(tmp, "p2")
        c2bad = kit.make_candidate(
            p2, STAGE, tx_id="tx-bad",
            structured={"problem_ref": "ASS-999"},
            proposed=proposed_entries())
        before = kit.snapshot_canonical(p2)
        exit_code, out, err = apply_tm(root, p2, c2bad)
        if exit_code == 0:
            raise TestFailure("invalid candidate must be rejected")
        result = kit.tm_result(out, "rejected apply")
        if result["result"] != "rejected":
            raise TestFailure(f"rejected result: {result['result']}")
        if kit.snapshot_canonical(p2) != before:
            raise TestFailure("rejected apply mutated canonical state")
        c2ok = make_tx_candidate(p2, tx_hint="tx-ok")
        exit_code, out, _ = apply_tm(root, p2, c2ok)
        if exit_code != 0:
            raise TestFailure("valid candidate after FAIL must apply")
        journal = [kit.read_json(j) for j in kit.find_journals(p2)
                   if kit.read_json(j)["state"] == "committed"][0]
        if journal["pass_map"]["P-ASS-001"] != "ASS-003":
            raise TestFailure(
                "FAIL consumed ASS ids: allocation must restart at ASS-003")

        # ------------------------------------------------- T-TX-ROLLBACK
        p3 = make_tx_project(tmp, "p3")
        c3 = make_tx_candidate(p3)
        before = kit.snapshot_canonical(p3)
        exit_code, out, err = apply_tm(
            root, p3, c3, env_extra={"BPO_TX_TEST_CRASH": "after_writes:1"})
        if exit_code == 0:
            raise TestFailure("crashed apply must not exit 0")
        journals = kit.find_journals(p3)
        if len(journals) != 1:
            raise TestFailure("crashed apply must leave its journal")
        if kit.read_json(journals[0])["state"] != "applying":
            raise TestFailure("crash mid-applying must leave state=applying")
        if kit.snapshot_canonical(p3) == before:
            raise TestFailure(
                "test setup: partial write expected before recovery")
        exit_code, out, err = kit.run_tm_cli(root, "recover", "--project", p3)
        if exit_code != 0:
            raise TestFailure(f"recover failed: {err.strip()!r}")
        result = kit.tm_result(out, "recover rollback")
        if kit.read_json(journals[0])["state"] != "rolled_back":
            raise TestFailure("incomplete applying must be rolled back")
        if kit.snapshot_canonical(p3) != before:
            raise TestFailure(
                "rollback must restore the exact pre-transaction state")
        if "ASS-003" in {e["id"] for e in read_register(p3)}:
            raise TestFailure("no allocated ASS may survive a rollback")

        # Retry after rollback: same deterministic ids (no consumption)
        c3b = make_tx_candidate(p3, tx_hint="tx-retry")
        exit_code, out, _ = apply_tm(root, p3, c3b)
        if exit_code != 0:
            raise TestFailure("apply after rollback must succeed")
        register = {e["id"] for e in read_register(p3)}
        if "ASS-003" not in register or "ASS-004" not in register:
            raise TestFailure("rollback consumed ids: expected ASS-003/004")

        # ------------------------------------------------- T-TX-RECOVERY
        p4 = make_tx_project(tmp, "p4")
        c4 = make_tx_candidate(p4)
        exit_code, out, err = apply_tm(
            root, p4, c4, env_extra={"BPO_TX_TEST_CRASH": "before_commit"})
        if exit_code == 0:
            raise TestFailure("crash before commit must not exit 0")
        journals = kit.find_journals(p4)
        journal = kit.read_json(journals[0])
        if journal["state"] != "applying":
            raise TestFailure("crash before marker must leave state=applying")
        # every canonical file of the write-set is already written
        written = kit.snapshot_canonical(p4)
        exit_code, out, err = kit.run_tm_cli(root, "recover", "--project", p4)
        if exit_code != 0:
            raise TestFailure(f"recover (complete) failed: {err.strip()!r}")
        journal = kit.read_json(journals[0])
        if journal["state"] != "committed":
            raise TestFailure(
                "complete applying without marker must be committed")
        if kit.snapshot_canonical(p4) != written:
            raise TestFailure(
                "safe completion must write only the marker, not the files")
        if "ASS-003" not in {e["id"] for e in read_register(p4)}:
            raise TestFailure("recovered commit lost allocated assumptions")
        # idempotent second recovery
        exit_code, _, err = kit.run_tm_cli(root, "recover", "--project", p4)
        if exit_code != 0:
            raise TestFailure(f"idempotent recover failed: {err.strip()!r}")
        if kit.snapshot_canonical(p4) != written:
            raise TestFailure("second recover must be a no-op")

        # Non-started journal states roll back trivially
        p5 = make_tx_project(tmp, "p5")
        tx_dir = p5 / "shared/.tx"
        tx_dir.mkdir(parents=True)
        kit.write_json(tx_dir / "tx-stub.json", {
            "transaction_id": "tx-stub", "project": str(p5), "stage": STAGE,
            "candidate_path": "x", "candidate_hash": "0" * 64,
            "state": "validated", "snapshot_path": None, "write_set": [],
            "pass_map": {}, "timestamps": {}})
        exit_code, out, _ = kit.run_tm_cli(root, "recover", "--project", p5)
        if exit_code != 0:
            raise TestFailure("recover of pre-applying journal must succeed")
        if kit.read_json(tx_dir / "tx-stub.json")["state"] != "rolled_back":
            raise TestFailure("pre-applying journal must be rolled back")

        # Corrupted journal -> exit 3
        (tx_dir / "tx-broken.json").write_text("{broken", encoding="utf-8")
        exit_code, _, _ = kit.run_tm_cli(root, "recover", "--project", p5)
        if exit_code != 3:
            raise TestFailure(
                f"corrupted journal must exit 3, got {exit_code}")

        # ------------------------------ validator egress con exit 2
        # Un validator REALMENTE invocato dal TM che termina con exit 2
        # (errore di configurazione: phases della matrice in disaccordo con
        # egress_required) deve respingere la transazione come ogni exit
        # != 0: result rejected, nessuna mutazione canonica, nessuna
        # allocazione ASS, journal terminale rolled_back. Discriminante di
        # mutazione: sostituendo nel TM `exit_code != 0` con `exit_code ==
        # 1` l'exit 2 verrebbe ignorato, gli altri validator passerebbero,
        # la transazione verrebbe applicata e questo test diventa RED.
        config_path = root / kit.CONFIG_REL
        config_backup = config_path.read_bytes()
        try:
            config = json.loads(config_backup.decode("utf-8"))
            spec = config["validators"]["validate_market_arithmetic"]
            if 4 not in [int(s) for s in spec["stages"]]:
                raise TestFailure(
                    "F-2 setup: il market validator deve restare in matrice "
                    "per lo Stage 4 (il filtro stage-aware non va aggirato)")
            spec["phases"] = ["impact"]
            config_path.write_text(
                json.dumps(config, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")

            p6 = market.stage4_project(tmp, "p6-exit2")
            c6 = kit.make_candidate(p6, market.S4,
                                    structured=market.structured(),
                                    proposed=market.market_proposed())
            before = kit.snapshot_canonical(p6)
            register_before = read_register(p6)
            exit_code, out, err = kit.run_tm_cli(
                root, "apply", "--project", p6, "--stage", market.S4,
                "--candidate", c6)
            if exit_code != 1:
                raise TestFailure(
                    "F-2: validator exit 2 in egress must reject the "
                    f"transaction (exit 1), got {exit_code} "
                    f"(out {out.strip()!r} err {err.strip()!r})")
            result = kit.tm_result(out, "F-2 exit-2 rejection")
            if result["result"] != "rejected":
                raise TestFailure(
                    f"F-2: expected result rejected, got {result}")
            codes = {e["code"] for e in result.get("errors", [])}
            if "validation_failed" not in codes:
                raise TestFailure(
                    f"F-2: expected validation_failed, got {sorted(codes)}")
            messages = " | ".join(e.get("message", "")
                                  for e in result.get("errors", []))
            if "exit 2" not in messages:
                raise TestFailure(
                    "F-2: rejection must name the validator exit code 2, "
                    f"got {messages!r}")
            if kit.snapshot_canonical(p6) != before:
                raise TestFailure(
                    "F-2: exit-2 rejection mutated the canonical state")
            if read_register(p6) != register_before:
                raise TestFailure(
                    "F-2: exit-2 rejection touched the register (no ASS "
                    "allocation allowed)")
            journal = kit.read_json(kit.find_journals(p6)[-1])
            if journal.get("state") != "rolled_back":
                raise TestFailure(
                    "F-2: journal must be terminal rolled_back, got "
                    f"{journal.get('state')!r}")
            if journal.get("pass_map"):
                raise TestFailure(
                    "F-2: pass_map must stay empty on rejection, got "
                    f"{journal['pass_map']}")
            ran = {v["validator"]: v["exit_code"]
                   for v in journal.get("validation", [])}
            if ran.get("validate_market_arithmetic") != 2:
                raise TestFailure(
                    "F-2: the journal must record the market validator "
                    f"really invoked with exit 2, got {ran}")
        finally:
            config_path.write_bytes(config_backup)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-TX-ROLLBACK + T-TX-RECOVERY + T-PASS-ALLOCATION")


if __name__ == "__main__":
    main()
