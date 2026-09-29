#!/usr/bin/env python3
"""T-UPD-CRASH — crash points e recovery dei comandi transazionali
`update-assumption` e `resolve-condition`.

Copre ogni crash point del mode `update_assumption`:

| Crash point                        | Recovery attesa                        |
|------------------------------------|----------------------------------------|
| pre-snapshot (`preparing`), view già materializzata | rollback banale, nessuna mutazione; view residua rimossa dal recover |
| post-snapshot, pre-applying        | idem                                   |
| a metà `applying`                  | restore snapshot BYTE-IDENTICO di tutti i target; nessun `DEC-` consumato; retry → stesso `reserved_decision_id` |
| post-write, pre-marker             | `verify_write_set` OK → marker-only idempotente; evento audit non duplicato |
| post-commit, retry dell'operazione | `already_applied`, exit 0              |
| doppio recover / nessun journal    | no-op idempotente                      |

Copre inoltre le **due guardie pre-commit** dei comandi di update, che
chiudono la finestra fra validazione e marker `committed`:

| Guardia                            | Atteso                                 |
|------------------------------------|----------------------------------------|
| CAS di conferma (TOCTOU) — registro mutato fra `validated` e `applying` | `canonical_drift`, exit 1, rolled_back, byte dello scrittore concorrente intatti, nessun `DEC-` consumato |
| CAS di conferma — decisions-register mutato nella stessa finestra | idem, `shared/decisions-register.json` nel messaggio di drift |
| `verify_write_set` — target del write-set corrotto dopo la write e prima del verify | `content_verification_failed`, exit 3, `restore_snapshot`, rolled_back, nessun marker `committed`, nessun audit `applied` |

Discriminante di mutazione: se `update-assumption` scrivesse senza
journal, il crash a metà lascerebbe stato parziale e le asserzioni di
restore byte-identico fallirebbero; se il `DEC-` fosse scritto nel canonico
prima di `applying`, il rollback lo consumerebbe e il retry allocherebbe
`DEC-002` invece di `DEC-001`; rimuovendo un ramo del blocco `if drift:` la
transazione sovrascriverebbe in silenzio lo scrittore concorrente;
neutralizzando `verify_write_set` → rollback un write parziale finirebbe
marcato `committed`.
"""
import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit


class TestFailure(AssertionError):
    pass


STAGE = "01_problem-and-need"


def project_with(tmp, name):
    return kit.make_project(
        tmp, name=name, current_stage=STAGE, status="in_progress",
        completed=["00_idea-discovery"],
        assumptions=[kit.base_assumption(1), kit.base_assumption(2)])


def payload(tm, project, operation_id="op-crash", value=555.0):
    register = kit.read_json(project / "shared/assumptions-register.json")
    entry = next(e for e in register if e["id"] == "ASS-001")
    return {
        "operation_id": operation_id,
        "reason": "aggiornamento confermato",
        "decision": {
            "decision_type": "assumption_update",
            "options_considered": "mantenere vs aggiornare",
            "motivation": "evidenza aggiornata",
            "impact": "nessun derivato coinvolto",
            "approver": "founder",
        },
        "changes": [{"assumption_id": "ASS-001",
                     "expected_record_hash": tm.record_fingerprint(entry),
                     "updates": {"value": value}}],
    }


def run_update(root, project, doc, tmp, name, env_extra=None):
    path = Path(tmp) / name
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return kit.run_tm_cli(root, "update-assumption", "--project", project,
                          "--changes", path, env_extra=env_extra)


def audit_events(project):
    path = project / "shared/audit-log.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line]


def update_journals(project, state=None):
    out = []
    for path in kit.find_journals(project):
        journal = kit.read_json(path)
        if journal.get("mode") != "update_assumption":
            continue
        if state and journal.get("state") != state:
            continue
        out.append((path, journal))
    return out


def check_pre_applying_crash(root, tm, tmp):
    """Journal non ancora in `applying`: rollback banale, view residua
    rimossa. I crash in `preparing`/`snapshot_taken`/`validated` sono
    indistinguibili per il recovery: nessuna scrittura canonica è avvenuta."""
    for state in ("preparing", "snapshot_taken", "validated"):
        project = project_with(tmp, f"pre-{state}")
        before = kit.snapshot_canonical(project)
        tx_dir = project / "shared/.tx"
        tx_dir.mkdir(parents=True, exist_ok=True)
        view = tx_dir / f"tx-{state}-validation-view"
        (view / "shared").mkdir(parents=True)
        (view / "shared/assumptions-register.json").write_text(
            "[]", encoding="utf-8")
        kit.write_json(tx_dir / f"tx-{state}.json", {
            "transaction_id": f"tx-{state}",
            "project": str(project),
            "stage": None,
            "mode": "update_assumption",
            "operation_id": "op-interrupted",
            "state": state,
            "snapshot_path": f"shared/.tx/tx-{state}-snapshot",
            "validation_view_path": f"shared/.tx/tx-{state}-validation-view",
            "reserved_decision_id": "DEC-001",
            "write_set": [],
            "pass_map": {},
            "timestamps": {},
        })
        exit_code, out, err = kit.run_tm_cli(root, "recover", "--project",
                                             project)
        if exit_code != 0:
            raise TestFailure(f"recover ({state}): {err.strip()!r}")
        journal = kit.read_json(tx_dir / f"tx-{state}.json")
        if journal["state"] != "rolled_back":
            raise TestFailure(
                f"journal in {state} deve essere rolled_back, trovato "
                f"{journal['state']!r}")
        if kit.snapshot_canonical(project) != before:
            raise TestFailure(f"recover ({state}) ha mutato il canonico")
        if view.exists():
            raise TestFailure(
                f"la validation view residua di un journal {state} deve "
                "essere rimossa dal recover")
        if (project / "shared/decisions-register.json").exists():
            raise TestFailure(
                f"un journal {state} non deve aver consumato alcun DEC-*")


def check_mid_applying_crash(root, tm, tmp):
    """Un crash dopo N write canoniche su 5 lascia stato parziale: il recover
    ripristina lo snapshot byte per byte."""
    for writes in (1, 2, 3, 4):
        project = project_with(tmp, f"mid-{writes}")
        before = kit.snapshot_canonical(project)
        doc = payload(tm, project)
        exit_code, _, _ = run_update(
            root, project, doc, tmp, f"mid{writes}.json",
            env_extra={"BPO_TX_TEST_CRASH": f"after_writes:{writes}"})
        if exit_code == 0:
            raise TestFailure(f"crash after_writes:{writes} non deve dare 0")
        journals = update_journals(project, "applying")
        if len(journals) != 1:
            raise TestFailure(
                f"after_writes:{writes}: atteso un journal in applying")
        if kit.snapshot_canonical(project) == before:
            raise TestFailure(
                f"setup after_writes:{writes}: attesa una scrittura parziale")

        exit_code, out, err = kit.run_tm_cli(root, "recover", "--project",
                                             project)
        if exit_code != 0:
            raise TestFailure(f"recover after_writes:{writes}: {err.strip()!r}")
        journal = kit.read_json(journals[0][0])
        if journal["state"] != "rolled_back":
            raise TestFailure(
                f"after_writes:{writes}: applying incompleto deve essere "
                f"rolled_back, trovato {journal['state']!r}")
        after = kit.snapshot_canonical(project)
        if after != before:
            differing = sorted(set(before) ^ set(after)) or [
                k for k in before if before[k] != after.get(k)]
            raise TestFailure(
                f"after_writes:{writes}: il rollback non ha ripristinato lo "
                f"stato byte-identico ({differing})")
        if (project / "shared/decisions-register.json").exists():
            raise TestFailure(
                f"after_writes:{writes}: il decisions-register creato dalla "
                "transazione deve sparire con il rollback (pre_hash null)")

        # retry: il DEC- riservato è ri-derivato identico, mai consumato
        exit_code, out, err = run_update(root, project,
                                         payload(tm, project,
                                                 operation_id="op-retry"),
                                         tmp, f"retry{writes}.json")
        if exit_code != 0:
            raise TestFailure(
                f"after_writes:{writes}: retry fallito {err.strip()!r}")
        if kit.tm_result(out, "retry")["decision_id"] != "DEC-001":
            raise TestFailure(
                f"after_writes:{writes}: il rollback ha consumato un DEC-*")


def check_marker_only_recovery(root, tm, tmp):
    project = project_with(tmp, "marker")
    doc = payload(tm, project, operation_id="op-marker")
    exit_code, _, _ = run_update(root, project, doc, tmp, "marker.json",
                                 env_extra={"BPO_TX_TEST_CRASH":
                                            "before_commit"})
    if exit_code == 0:
        raise TestFailure("crash before_commit non deve dare exit 0")
    written = kit.snapshot_canonical(project)
    events_before = audit_events(project)
    applied_before = [e for e in events_before if e.get("result") == "applied"]
    if len(applied_before) != 1:
        raise TestFailure(
            f"setup: atteso un evento applied nel write-set, {events_before}")

    journals = update_journals(project, "applying")
    if len(journals) != 1:
        raise TestFailure("atteso un journal in applying")
    exit_code, out, err = kit.run_tm_cli(root, "recover", "--project", project)
    if exit_code != 0:
        raise TestFailure(f"recover marker-only: {err.strip()!r}")
    journal = kit.read_json(journals[0][0])
    if journal["state"] != "committed":
        raise TestFailure(
            "un applying completo e verificato va completato scrivendo solo "
            f"il marker, trovato {journal['state']!r}")
    if journal.get("recovery_action") != "completed_marker_only":
        raise TestFailure(f"recovery_action: {journal.get('recovery_action')}")
    if kit.snapshot_canonical(project) != written:
        raise TestFailure(
            "il completamento sicuro deve scrivere solo il marker, non i file")
    applied_after = [e for e in audit_events(project)
                     if e.get("result") == "applied"]
    if len(applied_after) != 1:
        raise TestFailure(
            "audit transazionale: l'evento audit di commit è già nel write-set verificato e "
            f"non va duplicato dal recovery: {applied_after}")

    # post-commit: il retry della stessa operazione è già applicato
    exit_code, out, err = run_update(root, project, doc, tmp, "marker2.json")
    if exit_code != 0:
        raise TestFailure(f"retry post-commit: exit {exit_code}")
    if kit.tm_result(out, "retry post-commit")["result"] != "already_applied":
        raise TestFailure("il retry post-commit deve dare already_applied")

    # doppio recover: no-op idempotente
    exit_code, _, err = kit.run_tm_cli(root, "recover", "--project", project)
    if exit_code != 0:
        raise TestFailure(f"secondo recover: {err.strip()!r}")
    if kit.snapshot_canonical(project) != written:
        raise TestFailure("il secondo recover non deve essere un no-op")


REGISTER_REL = "shared/assumptions-register.json"
DECISIONS_REL = "shared/decisions-register.json"
DECISION_LOG_REL = "shared/decision-log.md"


def concurrent_bytes(doc):
    """Byte di uno scrittore concorrente, serializzati su UNA riga.

    L'hook di test scrive testo con `write_text`: un contenuto multi-riga
    subirebbe la traduzione newline di Windows e i byte su disco non
    sarebbero più quelli attesi dal test."""
    return json.dumps(doc, ensure_ascii=False)


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def committed_journals(project, operation_id):
    return [j for _, j in update_journals(project, "committed")
            if j.get("operation_id") == operation_id]


def expect_drift(root, tm, tmp, project, before, rel, mutated, doc, name):
    """Esegue l'update con una mutazione canonica iniettata fra `validated` e
    `applying` e verifica l'intera post-condizione del CAS di conferma."""
    exit_code, out, err = run_update(
        root, project, doc, tmp, name,
        env_extra={"BPO_TX_TEST_MUTATE_CANONICAL": f"{rel}={mutated}"})
    if exit_code != 1:
        raise TestFailure(
            f"drift su {rel}: atteso exit 1, ottenuto {exit_code} "
            f"(out {out.strip()!r} err {err.strip()!r})")
    result = kit.tm_result(out, f"drift {rel}")
    errors = result.get("errors", [])
    codes = {e["code"] for e in errors}
    if "canonical_drift" not in codes:
        raise TestFailure(
            f"drift su {rel}: atteso canonical_drift, ottenuti {sorted(codes)}")
    if not any(rel in e.get("message", "") for e in errors):
        raise TestFailure(
            f"drift su {rel}: il messaggio non nomina il file divergente: "
            f"{errors}")

    operation_id = doc["operation_id"]
    drifted = [j for _, j in update_journals(project, "rolled_back")
               if (j.get("error") or {}).get("code") == "canonical_drift"
               and j.get("operation_id") == operation_id]
    if len(drifted) != 1:
        raise TestFailure(
            f"drift su {rel}: atteso un journal rolled_back con "
            f"canonical_drift, trovati {len(drifted)}")
    if committed_journals(project, operation_id):
        raise TestFailure(
            f"drift su {rel}: nessun marker committed deve essere scritto")

    expected = dict(before)
    expected[rel] = sha256_text(mutated)
    after = kit.snapshot_canonical(project)
    if after != expected:
        differing = sorted(k for k in set(expected) | set(after)
                           if expected.get(k) != after.get(k))
        raise TestFailure(
            f"drift su {rel}: la transazione deve lasciare intatti i byte "
            f"dello scrittore concorrente e non toccare nulla d'altro "
            f"({differing})")
    return drifted[0]


def check_canonical_drift_register(root, tm, tmp):
    """CAS di conferma, ramo `register_hash`: l'assumptions-register muta fra
    la validazione e l'applicazione. Il decisions-register non esiste prima e
    non deve esistere dopo; il `DEC-` riservato non è consumato."""
    project = project_with(tmp, "drift-register")
    before = kit.snapshot_canonical(project)
    register = kit.read_json(project / REGISTER_REL)
    for entry in register:
        if entry["id"] == "ASS-002":
            entry["value"] = 999.0
    mutated = concurrent_bytes(register)

    doc = payload(tm, project, operation_id="op-drift-register")
    journal = expect_drift(root, tm, tmp, project, before, REGISTER_REL,
                           mutated, doc, "drift-register.json")

    if (project / DECISIONS_REL).exists():
        raise TestFailure(
            "drift su register: il decisions-register assente prima della "
            "transazione deve restare assente")
    reserved = journal.get("reserved_decision_id")
    if reserved != "DEC-001":
        raise TestFailure(f"DEC riservato inatteso: {reserved!r}")

    # retry con lo STESSO operation_id: il drift non ha consumato il DEC-
    exit_code, out, err = run_update(root, project, doc, tmp,
                                     "drift-register-retry.json")
    if exit_code != 0:
        raise TestFailure(
            f"retry dopo drift: exit {exit_code} (err {err.strip()!r})")
    retried = kit.tm_result(out, "retry dopo drift")
    if retried.get("decision_id") != reserved:
        raise TestFailure(
            f"il retry deve riallocare {reserved}, ha allocato "
            f"{retried.get('decision_id')!r}: il drift ha consumato un DEC-*")


def check_canonical_drift_decisions(root, tm, tmp):
    """CAS di conferma, ramo `decisions_register_hash`: il registro delle
    decisioni muta nella stessa finestra. La mutazione non aggiunge record,
    quindi il `DEC-` riservato resta allocabile identico al retry."""
    project = project_with(tmp, "drift-decisions")
    exit_code, _, err = run_update(
        root, project, payload(tm, project, operation_id="op-setup"), tmp,
        "drift-decisions-setup.json")
    if exit_code != 0:
        raise TestFailure(f"setup drift-decisions: {err.strip()!r}")

    before = kit.snapshot_canonical(project)
    decisions = kit.read_json(project / DECISIONS_REL)
    if len(decisions["decisions"]) != 1:
        raise TestFailure("setup: atteso un solo record nel decisions-register")
    decisions["decisions"][0]["motivation"] = "riscritta da un altro processo"
    mutated = concurrent_bytes(decisions)

    doc = payload(tm, project, operation_id="op-drift-decisions", value=777.0)
    journal = expect_drift(root, tm, tmp, project, before, DECISIONS_REL,
                           mutated, doc, "drift-decisions.json")

    after = kit.read_json(project / DECISIONS_REL)
    if len(after["decisions"]) != 1:
        raise TestFailure(
            f"il drift non deve aggiungere record al decisions-register: "
            f"{after['decisions']}")
    reserved = journal.get("reserved_decision_id")
    if reserved != "DEC-002":
        raise TestFailure(f"DEC riservato inatteso: {reserved!r}")

    exit_code, out, err = run_update(root, project, doc, tmp,
                                     "drift-decisions-retry.json")
    if exit_code != 0:
        raise TestFailure(
            f"retry dopo drift decisions: exit {exit_code} "
            f"(err {err.strip()!r})")
    retried = kit.tm_result(out, "retry dopo drift decisions")
    if retried.get("decision_id") != reserved:
        raise TestFailure(
            f"il retry deve riallocare {reserved}, ha allocato "
            f"{retried.get('decision_id')!r}: il drift ha consumato un DEC-*")


def check_content_verification_failed(root, tm, tmp):
    """Un target del write-set corrotto DOPO la write e PRIMA di
    `verify_write_set`: la transazione non può essere marcata `committed`, lo
    snapshot va ripristinato e nessun `DEC-` va consumato."""
    project = project_with(tmp, "verify")
    before = kit.snapshot_canonical(project)
    doc = payload(tm, project, operation_id="op-verify")
    exit_code, out, err = run_update(
        root, project, doc, tmp, "verify.json",
        env_extra={"BPO_TX_TEST_CORRUPT_AFTER_WRITE":
                   f"{DECISION_LOG_REL}=corrotto dopo la write"})
    if exit_code != 3:
        raise TestFailure(
            f"write-set corrotto: atteso exit 3, ottenuto {exit_code} "
            f"(out {out.strip()!r} err {err.strip()!r})")
    codes = {e["code"] for e in kit.tm_result(out, "verify").get("errors", [])}
    if "content_verification_failed" not in codes:
        raise TestFailure(
            f"atteso content_verification_failed, ottenuti {sorted(codes)}")

    journals = update_journals(project, "rolled_back")
    failed = [(p, j) for p, j in journals
              if (j.get("error") or {}).get("code")
              == "content_verification_failed"]
    if len(failed) != 1:
        raise TestFailure(
            f"atteso un journal rolled_back con content_verification_failed, "
            f"trovati {len(failed)}")
    if committed_journals(project, "op-verify"):
        raise TestFailure(
            "un write-set non verificato non deve produrre un marker "
            "committed")

    after = kit.snapshot_canonical(project)
    if after != before:
        differing = sorted(k for k in set(before) | set(after)
                           if before.get(k) != after.get(k))
        raise TestFailure(
            f"restore_snapshot non ha ripristinato lo stato byte-identico "
            f"({differing})")
    if (project / DECISIONS_REL).exists():
        raise TestFailure(
            "il rollback deve eliminare il decisions-register creato dalla "
            "transazione (pre_hash null)")
    applied = [e for e in audit_events(project)
               if e.get("result") == "applied"]
    if applied:
        raise TestFailure(
            f"audit transazionale: l'evento audit `applied` fa parte del write-set e deve "
            f"tornare indietro col rollback: {applied}")

    exit_code, out, err = run_update(root, project, doc, tmp,
                                     "verify-retry.json")
    if exit_code != 0:
        raise TestFailure(
            f"retry dopo content_verification_failed: exit {exit_code} "
            f"(err {err.strip()!r})")
    if kit.tm_result(out, "retry verify")["decision_id"] != "DEC-001":
        raise TestFailure(
            "il rollback post-verify ha consumato un DEC-*")


def check_recover_without_journals(root, tmp):
    project = project_with(tmp, "nojournal")
    before = kit.snapshot_canonical(project)
    for _ in range(2):
        exit_code, out, err = kit.run_tm_cli(root, "recover", "--project",
                                             project)
        if exit_code != 0:
            raise TestFailure(f"recover senza journal: {err.strip()!r}")
    if kit.snapshot_canonical(project) != before:
        raise TestFailure("recover senza journal ha mutato il progetto")


def run(root):
    tm = kit.load_module(root, kit.TRANSACTION_REL, "transaction_manager")
    with tempfile.TemporaryDirectory(prefix="bpo-crash-") as tmp:
        tmp = Path(tmp)
        check_pre_applying_crash(root, tm, tmp)
        check_mid_applying_crash(root, tm, tmp)
        check_marker_only_recovery(root, tm, tmp)
        check_canonical_drift_register(root, tm, tmp)
        check_canonical_drift_decisions(root, tm, tmp)
        check_content_verification_failed(root, tm, tmp)
        check_recover_without_journals(root, tmp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-UPD-CRASH crash points e recovery dei comandi di update")


if __name__ == "__main__":
    main()
