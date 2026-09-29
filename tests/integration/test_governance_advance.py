#!/usr/bin/env python3
"""T-GOVERNANCE-ADVANCE — binding del gate, advance atomico, identità del
candidate.

- binding del gate: governance-status non può impostare approved /
  approved_with_conditions (né completed_stages/current_stage): qualunque
  approvazione passa dal percorso transazionale advance-stage.
- advance atomico: advance-stage è un'unica transazione recuperabile che applica
  output, registri, handoff, gate, current_stage, completed_stages e audit;
  la transizione è derivata da current_stage + stage_order, validata prima
  e verificata dopo la write; rollback integrale su failure intermedia.
- identità del candidate: il candidate definitivo è lo snapshot immutabile in shared/.tx/
  preso sotto lock; una modifica concorrente del candidate attivo dopo lo
  snapshot non entra nel canonico; una modifica dello snapshot o degli
  artefatti di enforcement (config/validator/schemi) viene rilevata.
"""
import argparse
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit


class TestFailure(AssertionError):
    pass


STAGE = "01_problem-and-need"
NEXT = "02_customer-segmentation"


def make_tx_project(tmp, name, status="in_progress", completed=None):
    return kit.make_project(
        tmp, name=name, current_stage=STAGE, status=status,
        completed=completed or ["00_idea-discovery"],
        assumptions=[kit.base_assumption(1), kit.base_assumption(2)])


def make_tx_candidate(project, tx_hint="tx-a", conditions=None):
    candidate = kit.make_candidate(
        project, STAGE, tx_id=tx_hint,
        structured={"problem_statement": {"id": "SEG-001",
                                          "problem_ref": "ASS-001",
                                          "revenue_ref": "P-ASS-001"}},
        proposed=[{"id": "P-ASS-001", "category": "market",
                   "statement": "Driver ricavo", "kind": "primary",
                   "unit": "EUR", "value": 2000,
                   "validation_status": "unvalidated"}],
        handoff="# Handoff\n\nDriver: P-ASS-001.\n")
    if conditions is not None:
        kit.write_json(candidate / "proposed-conditions.json", conditions)
    return candidate


def advance_tm(root, project, candidate, stage=STAGE, extra=None,
               env_extra=None):
    args = ["advance-stage", "--project", project, "--stage", stage,
            "--candidate", candidate]
    if extra:
        args += extra
    return kit.run_tm_cli(root, *args, env_extra=env_extra)


def front_matter(root, project):
    fw = kit.load_module(root, kit.VALIDATORS_REL, "_framework")
    return fw.parse_front_matter(
        (project / "shared/project-status.md").read_text(encoding="utf-8"))


def audit_events(project):
    path = project / "shared/audit-log.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line]


def run_h01(root, tmp):
    for forbidden in ("approved", "approved_with_conditions"):
        # fixture in cui l'approvazione sarebbe COERENTE (stage nei
        # completed): solo l'allow-list amministrativa può respingerla
        p = make_tx_project(tmp, f"h01-{forbidden}",
                            status="needs_revision",
                            completed=["00_idea-discovery", STAGE])
        before = kit.snapshot_canonical(p)
        exit_code, out, err = kit.run_tm_cli(
            root, "governance-status", "--project", p,
            "--updates", json.dumps({"status": forbidden}),
            "--reason", "tentativo di bypass del gate")
        if exit_code == 0:
            raise TestFailure(
                f"gate binding: governance-status set {forbidden} without "
                "validators")
        if kit.snapshot_canonical(p) != before:
            raise TestFailure(f"gate binding: {forbidden} attempt mutated the state")
        if front_matter(root, p)["status"] != "needs_revision":
            raise TestFailure(f"gate binding: status changed to {forbidden}")
        gov = [e for e in audit_events(p)
               if e.get("action") == "governance_status_update"]
        if gov:
            raise TestFailure(
                "gate binding: rejected governance attempt must not log an applied "
                "governance event")

    # campi di avanzamento mai governabili direttamente
    p = make_tx_project(tmp, "h01-fields")
    for payload in ('{"completed_stages": ["00_idea-discovery", '
                    '"01_problem-and-need"]}',
                    '{"current_stage": "06_go-to-market"}'):
        exit_code, _, _ = kit.run_tm_cli(
            root, "governance-status", "--project", p,
            "--updates", payload, "--reason", "bypass")
        if exit_code == 0:
            raise TestFailure(f"gate binding: governable field escaped: {payload}")

    # gli stati amministrativi allow-listed restano governabili
    p = make_tx_project(tmp, "h01-admin")
    exit_code, _, err = kit.run_tm_cli(
        root, "governance-status", "--project", p,
        "--updates", '{"status": "needs_revision"}',
        "--reason", "richiesta revisione")
    if exit_code != 0:
        raise TestFailure(f"gate binding: admin state rejected: {err.strip()!r}")


def run_m01(root, tmp):
    # ---- avanzamento end-to-end ---------------------------------------------
    p = make_tx_project(tmp, "m01a")
    c = make_tx_candidate(p)
    exit_code, out, err = advance_tm(root, p, c)
    if exit_code != 0:
        raise TestFailure(f"advance advance failed: exit {exit_code} "
                          f"(out {out.strip()!r} err {err.strip()!r})")
    front = front_matter(root, p)
    if front["current_stage"] != NEXT:
        raise TestFailure(
            f"advance: current_stage must advance to {NEXT}, got "
            f"{front['current_stage']}")
    if front["completed_stages"] != ["00_idea-discovery", STAGE]:
        raise TestFailure(
            f"advance: completed_stages wrong: {front['completed_stages']}")
    if front["status"] != "not_started":
        raise TestFailure(
            f"advance: next stage must start as not_started, got "
            f"{front['status']}")
    register_ids = {e["id"] for e in
                    kit.read_json(p / "shared/assumptions-register.json")}
    if "ASS-003" not in register_ids:
        raise TestFailure("advance: proposed assumption not allocated")
    structured = kit.read_json(p / STAGE / "structured-output.json")
    if structured["problem_statement"]["revenue_ref"] != "ASS-003":
        raise TestFailure("advance: structured-output not applied/substituted")
    if "ASS-003" not in (p / STAGE / "handoff.md").read_text(
            encoding="utf-8"):
        raise TestFailure("advance: handoff not applied in the same tx")
    journal = [kit.read_json(j) for j in kit.find_journals(p)
               if kit.read_json(j)["state"] == "committed"][0]
    write_paths = {e["path"] for e in journal["write_set"]}
    expected = {"shared/assumptions-register.json",
                f"{STAGE}/structured-output.json", f"{STAGE}/handoff.md",
                "shared/project-status.md", "shared/audit-log.jsonl"}
    if not expected <= write_paths:
        raise TestFailure(
            f"advance: advance write-set incomplete: {sorted(write_paths)}")
    advanced = [e for e in audit_events(p)
                if e.get("action") == "tx_advance_stage"
                and e.get("result") == "applied"]
    if len(advanced) != 1:
        raise TestFailure("advance: exactly one advance audit event expected")
    if c.exists():
        raise TestFailure("advance: candidate must be cleaned after advance")
    # l'ingresso nello stage successivo è ora autorizzato
    exit_code, out, err = kit.run_validator_cli(
        root, "validate_stage_gate", project=p, stage=NEXT, phase="ingress")
    if exit_code != 0:
        raise TestFailure(
            f"advance: ingress into {NEXT} must pass after advance, got "
            f"{exit_code} (out {out.strip()!r})")

    # ---- approved_with_conditions con COND tracciate ------------------------
    p = make_tx_project(tmp, "m01b")
    cond = {
        "id": "COND-001", "stage": STAGE,
        "description": "Validare il driver con 3 interviste",
        "severity": "high", "owner": "founder",
        "validation_action": "interviste", "resolution_status": "open",
        "due_before_stage": "04_market-and-competition",
    }
    c = make_tx_candidate(p, conditions=[cond])
    exit_code, out, err = advance_tm(
        root, p, c, extra=["--gate-result", "approved_with_conditions"])
    if exit_code != 0:
        raise TestFailure(f"advance conditional advance failed: "
                          f"{out.strip()!r} {err.strip()!r}")
    conditions = kit.read_json(p / "shared/conditions-register.json")
    if not any(e.get("id") == "COND-001" for e in conditions):
        raise TestFailure("advance: COND not applied in the same transaction")

    # approved_with_conditions senza COND -> rifiutato
    p = make_tx_project(tmp, "m01c")
    c = make_tx_candidate(p)
    before = kit.snapshot_canonical(p)
    exit_code, out, _ = advance_tm(
        root, p, c, extra=["--gate-result", "approved_with_conditions"])
    if exit_code == 0:
        raise TestFailure(
            "advance: approved_with_conditions without COND must be rejected")
    if kit.snapshot_canonical(p) != before:
        raise TestFailure("advance: rejected conditional advance mutated state")

    # ---- transizioni arbitrarie rifiutate -----------------------------------
    p = make_tx_project(tmp, "m01d")
    c = kit.make_candidate(p, "02_customer-segmentation", tx_id="tx-skip",
                           structured={"x": "ASS-001"})
    before = kit.snapshot_canonical(p)
    exit_code, _, _ = advance_tm(root, p, c,
                                 stage="02_customer-segmentation")
    if exit_code == 0:
        raise TestFailure("advance: skipping ahead of current_stage allowed")
    if kit.snapshot_canonical(p) != before:
        raise TestFailure("advance: rejected skip mutated the state")
    front = front_matter(root, p)
    if front["current_stage"] != STAGE or \
            front["completed_stages"] != ["00_idea-discovery"]:
        raise TestFailure("advance: rejected skip changed the transition state")

    # stage già completato: nessuna ri-approvazione silenziosa
    p = make_tx_project(tmp, "m01e", status="approved",
                        completed=["00_idea-discovery", STAGE])
    c = make_tx_candidate(p)
    before = kit.snapshot_canonical(p)
    exit_code, _, _ = advance_tm(root, p, c)
    if exit_code == 0:
        raise TestFailure("advance: re-advancing a completed stage allowed")
    if kit.snapshot_canonical(p) != before:
        raise TestFailure("advance: rejected re-advance mutated the state")

    # ---- rollback integrale su failure intermedia ---------------------------
    p = make_tx_project(tmp, "m01f")
    c = make_tx_candidate(p)
    before = kit.snapshot_canonical(p)
    exit_code, _, _ = advance_tm(
        root, p, c, env_extra={"BPO_TX_TEST_CRASH": "after_writes:2"})
    if exit_code == 0:
        raise TestFailure("advance: crash hook did not fire")
    exit_code, _, err = kit.run_tm_cli(root, "recover", "--project", p)
    if exit_code != 0:
        raise TestFailure(f"advance recover failed: {err.strip()!r}")
    if kit.snapshot_canonical(p) != before:
        raise TestFailure(
            "advance: interrupted advance must roll back integrally")
    front = front_matter(root, p)
    if front["current_stage"] != STAGE or front["status"] != "in_progress":
        raise TestFailure("advance: rollback must restore the pre-advance gate")


def run_h02(root, tmp):
    # ---- modifica concorrente del candidate attivo dopo lo snapshot --------
    p = make_tx_project(tmp, "h02a")
    c = make_tx_candidate(p)
    tamper = 'structured-output.json={"tampered": "unvalidated-content"}'
    exit_code, out, err = kit.run_tm_cli(
        root, "apply", "--project", p, "--stage", STAGE, "--candidate", c,
        env_extra={"BPO_TX_TEST_MUTATE_ACTIVE": tamper})
    if exit_code != 0:
        raise TestFailure(
            f"candidate identity: apply with concurrent active-candidate mutation must "
            f"commit the validated snapshot, got {exit_code} "
            f"(out {out.strip()!r} err {err.strip()!r})")
    structured = kit.read_json(p / STAGE / "structured-output.json")
    if "tampered" in json.dumps(structured):
        raise TestFailure(
            "candidate identity: unvalidated concurrent content entered the canonical "
            "state")
    if structured["problem_statement"]["revenue_ref"] != "ASS-003":
        raise TestFailure(
            "candidate identity: committed bytes must correspond to the validated "
            "snapshot")
    journal = [kit.read_json(j) for j in kit.find_journals(p)
               if kit.read_json(j)["state"] == "committed"][0]
    if not journal.get("candidate_hash"):
        raise TestFailure("candidate identity: journal must record the snapshot hash")
    hashes = journal.get("enforcement_hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise TestFailure(
            "candidate identity: journal must record config/validator/schema identity")
    expected_keys = {"config/enforcement-config.json",
                     "validators/_framework.py",
                     "validators/validate_stage_gate.py",
                     "validators/validate_referential_integrity.py",
                     "schemas/assumptions-register.schema.json"}
    if not expected_keys <= set(hashes):
        raise TestFailure(
            f"candidate identity: enforcement identity incomplete: {sorted(hashes)}")

    # ---- modifica dello snapshot dopo la validazione -> rilevata ------------
    p = make_tx_project(tmp, "h02b")
    c = make_tx_candidate(p)
    before = kit.snapshot_canonical(p)
    exit_code, out, _ = kit.run_tm_cli(
        root, "apply", "--project", p, "--stage", STAGE, "--candidate", c,
        env_extra={"BPO_TX_TEST_MUTATE_SNAPSHOT": tamper})
    if exit_code == 0:
        raise TestFailure("candidate identity: tampered snapshot must not commit")
    codes = {e["code"] for e in kit.tm_result(out, "h02b")["errors"]}
    if "candidate_changed" not in codes:
        raise TestFailure(f"candidate identity: expected candidate_changed, got {codes}")
    if kit.snapshot_canonical(p) != before:
        raise TestFailure("candidate identity: tampered snapshot mutated the state")

    # ---- modifica degli artefatti di enforcement -> rilevata ----------------
    tm = kit.load_module(root, kit.TRANSACTION_REL, "transaction_manager")
    p = make_tx_project(tmp, "h02c")
    c = make_tx_candidate(p)
    before = kit.snapshot_canonical(p)
    orig = tm.enforcement_artifact_hashes
    calls = {"n": 0}

    def drifting(config, loaded=False):
        calls["n"] += 1
        out = orig(config, loaded=loaded)
        if calls["n"] > 1:
            key = sorted(out)[0]
            out = dict(out)
            out[key] = "0" * 64
        return out

    tm.enforcement_artifact_hashes = drifting
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                rc = tm.cmd_apply(argparse.Namespace(
                    project=str(p), stage=STAGE, candidate=str(c),
                    report=None))
            except tm.TransactionError as exc:
                rc = exc.exit_code
    finally:
        tm.enforcement_artifact_hashes = orig
    if rc == 0:
        raise TestFailure(
            "candidate identity: enforcement artifact drift must abort the commit")
    if kit.snapshot_canonical(p) != before:
        raise TestFailure(
            "candidate identity: enforcement drift left canonical mutations")
    journals = [kit.read_json(j) for j in kit.find_journals(p)]
    if any(j["state"] == "committed" for j in journals):
        raise TestFailure("candidate identity: journal committed despite identity drift")


def run_r2h02(root, tmp):
    # Stato coerente di partenza: lo stage 01 è approvato e nei completed,
    # current_stage == 01 (unico caso legittimo di current in completed:
    # deliverable approvato). Un deliverable già approvato NON deve poter
    # essere riaperto: la riapertura di uno stage approvato non è supportata.
    p = kit.make_project(
        tmp, name="r2h02a", current_stage=STAGE, status="approved",
        completed=["00_idea-discovery", STAGE],
        assumptions=[kit.base_assumption(1), kit.base_assumption(2)])
    before = kit.snapshot_canonical(p)

    # 1) governance-status non deve poter portare a in_progress uno stage
    # già completed (riapertura silenziosa senza ISSUE).
    exit_code, out, err = kit.run_tm_cli(
        root, "governance-status", "--project", p,
        "--updates", '{"status": "in_progress"}',
        "--reason", "tentativo di riapertura di uno stage completato")
    if exit_code == 0:
        raise TestFailure(
            "no reopen: governance-status reopened a completed stage to "
            "in_progress")
    if front_matter(root, p)["status"] != "approved":
        raise TestFailure(
            "no reopen: completed stage status changed by governance-status")
    if kit.snapshot_canonical(p) != before:
        raise TestFailure("no reopen: reopen attempt mutated the canonical state")

    # 2) composizione governance-status(in_progress) -> apply: la riscrittura
    # canonica di un deliverable già approvato deve essere sempre rifiutata.
    c = make_tx_candidate(p, tx_hint="tx-reopen")
    before2 = kit.snapshot_canonical(p)
    ids_before = {e["id"] for e in
                  kit.read_json(p / "shared/assumptions-register.json")}
    exit_code, out, err = kit.run_tm_cli(
        root, "apply", "--project", p, "--stage", STAGE, "--candidate", c)
    if exit_code == 0:
        raise TestFailure(
            "no reopen: apply re-applied output to a completed stage")
    if kit.snapshot_canonical(p) != before2:
        raise TestFailure("no reopen: rejected reopen apply mutated the state")
    ids_after = {e["id"] for e in
                 kit.read_json(p / "shared/assumptions-register.json")}
    if ids_after != ids_before:
        raise TestFailure(
            "no reopen: apply on a completed stage consumed an ASS id")
    if any(kit.read_json(j).get("state") == "committed"
           for j in kit.find_journals(p)):
        raise TestFailure("no reopen: a committed journal reopened the stage")

    # 3) l'egress su uno stage presente in completed_stages è sempre respinto
    # dal validator (con qualunque gate state ammesso all'ingresso normale).
    exit_code, out, err = kit.run_validator_cli(
        root, "validate_stage_gate", project=p, stage=STAGE, phase="egress",
        candidate=c)
    if exit_code == 0:
        raise TestFailure(
            "no reopen: egress on a completed stage must never pass")


def run_r2h01(root, tmp):
    # Il recovery marker-only (write-set completo, marker mancante) deve
    # RIVALIDARE lo snapshot del candidate e gli enforcement artifacts prima
    # di committare: un drift non deve poter essere sanato dal recovery.

    # (a) drift dello snapshot del candidate durante la finestra di crash
    p = make_tx_project(tmp, "r2h01a")
    c = make_tx_candidate(p)
    before = kit.snapshot_canonical(p)
    exit_code, _, _ = kit.run_tm_cli(
        root, "apply", "--project", p, "--stage", STAGE, "--candidate", c,
        env_extra={"BPO_TX_TEST_CRASH": "before_commit"})
    if exit_code == 0:
        raise TestFailure("recovery revalidation: before_commit crash expected")
    journal_path = kit.find_journals(p)[0]
    journal = kit.read_json(journal_path)
    if journal["state"] != "applying":
        raise TestFailure("recovery revalidation: setup expects state=applying")
    snap_dir = p / journal["candidate_snapshot_path"]
    target = next(f for f in sorted(snap_dir.rglob("*")) if f.is_file())
    target.write_text("tampered snapshot content\n", encoding="utf-8")
    exit_code, out, err = kit.run_tm_cli(root, "recover", "--project", p)
    if kit.read_json(journal_path)["state"] == "committed":
        raise TestFailure(
            "recovery revalidation: marker-only recovery committed a drifted candidate "
            "snapshot without revalidating its hash")
    if kit.snapshot_canonical(p) != before:
        raise TestFailure(
            "recovery revalidation: recovery of a drifted snapshot must restore the state")

    # (b) drift degli enforcement artifacts registrati nel journal
    p = make_tx_project(tmp, "r2h01b")
    c = make_tx_candidate(p)
    before = kit.snapshot_canonical(p)
    exit_code, _, _ = kit.run_tm_cli(
        root, "apply", "--project", p, "--stage", STAGE, "--candidate", c,
        env_extra={"BPO_TX_TEST_CRASH": "before_commit"})
    journal_path = kit.find_journals(p)[0]
    journal = kit.read_json(journal_path)
    enf = journal.get("enforcement_hashes")
    if not isinstance(enf, dict) or not enf:
        raise TestFailure("recovery revalidation: journal must record enforcement_hashes")
    enf[sorted(enf)[0]] = "0" * 64
    kit.write_json(journal_path, journal)
    exit_code, out, err = kit.run_tm_cli(root, "recover", "--project", p)
    if kit.read_json(journal_path)["state"] == "committed":
        raise TestFailure(
            "recovery revalidation: marker-only recovery committed despite enforcement "
            "artifact drift recorded in the journal")
    if kit.snapshot_canonical(p) != before:
        raise TestFailure(
            "recovery revalidation: recovery under enforcement drift must restore the state")


def run_r3n1(root, tmp):
    # La "loaded-bytes identity" del recovery deve essere discriminante.
    # enforcement_artifact_hashes(..., loaded=True) registra i byte IMPORTATI
    # (catturati all'import in _LOADED_SOURCE_HASHES), non un re-read da disco.
    # Per provarlo occorre far divergere disco e byte importati: si modifica un
    # sorgente di enforcement REALMENTE importato (formula_dsl.py) DOPO l'import
    # del transaction manager e PRIMA della registrazione, poi si esegue apply.
    # Con disco invariato loaded=True e loaded=False sono identici: la
    # divergenza esiste solo sotto drift ed è ciò che questo test costruisce.
    tm = kit.load_module(root, kit.TRANSACTION_REL, "transaction_manager")
    rel = "validators/formula_dsl.py"
    if rel not in tm._LOADED_SOURCE_HASHES:
        raise TestFailure(
            "loaded-bytes identity: formula_dsl.py deve essere fra i sorgenti importati "
            "hashati all'import (_LOADED_SOURCE_HASHES)")
    src = root / kit.SKILL_REL / rel
    import_hash = tm._LOADED_SOURCE_HASHES[rel]
    original = src.read_bytes()
    if tm.sha256_bytes(original) != import_hash:
        raise TestFailure(
            "loaded-bytes identity: setup — con disco immutato l'hash import-time deve "
            "coincidere col disco")

    p = make_tx_project(tmp, "r3n1")
    c = make_tx_candidate(p)
    before = kit.snapshot_canonical(p)
    try:
        # drift su disco DOPO l'import: byte diversi da quelli eseguiti dal
        # processo. Un commento in coda è innocuo -> gli egress validator
        # (subprocess che rileggono il disco) restano verdi.
        src.write_bytes(original + b"\n# R3-N1 loaded-bytes drift probe\n")
        drift_hash = tm.sha256_file(src)
        if drift_hash == import_hash:
            raise TestFailure("loaded-bytes identity: setup — il drift non ha cambiato l'hash")

        # (1) livello funzione: solo sotto drift i due percorsi divergono, e
        # loaded=True fissa i byte importati mentre loaded=False segue il disco.
        cfg = tm.fw.load_config()
        recorded_map = tm.enforcement_artifact_hashes(cfg, loaded=True)
        disk_map = tm.enforcement_artifact_hashes(cfg, loaded=False)
        if recorded_map[rel] != import_hash:
            raise TestFailure("loaded-bytes identity: loaded=True non fissa i byte importati")
        if disk_map[rel] != drift_hash:
            raise TestFailure("loaded-bytes identity: loaded=False non segue il drift su disco")
        if recorded_map[rel] == disk_map[rel]:
            raise TestFailure(
                "loaded-bytes identity: sotto drift loaded=True e loaded=False devono divergere")

        # (2) livello apply (discriminante del call-site): la registrazione con
        # loaded=True fissa nel journal i byte eseguiti; la verifica finale
        # (re-read da disco) rileva il drift -> rollback, nessun commit.
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                rc = tm.cmd_apply(argparse.Namespace(
                    project=str(p), stage=STAGE, candidate=str(c),
                    report=None))
            except tm.TransactionError as exc:
                rc = exc.exit_code
        if rc == 0:
            raise TestFailure(
                "loaded-bytes identity: apply ha committato pur avendo eseguito byte di "
                "enforcement diversi da quelli su disco (loaded-bytes identity "
                "non discriminata: sostituendo loaded=True con loaded=False la "
                "transazione committerebbe alla cieca)")
        if kit.snapshot_canonical(p) != before:
            raise TestFailure(
                "loaded-bytes identity: il rollback per drift deve ripristinare lo stato "
                "canonico")
        journal = kit.read_json(kit.find_journals(p)[0])
        recorded = journal.get("enforcement_hashes", {}).get(rel)
        if recorded != import_hash:
            raise TestFailure(
                "loaded-bytes identity: il journal deve registrare l'hash import-time (byte "
                f"eseguiti), non il disco driftato: {recorded!r}")
        if recorded == drift_hash:
            raise TestFailure(
                "loaded-bytes identity: il journal ha registrato l'hash del disco driftato "
                "(comportamento loaded=False)")
    finally:
        src.write_bytes(original)
    if src.read_bytes() != original:
        raise TestFailure(
            "loaded-bytes identity: ripristino del sorgente di enforcement fallito")


def run(root):
    with tempfile.TemporaryDirectory(prefix="bpo-govadv-") as tmp:
        tmp = Path(tmp)
        run_h01(root, tmp)
        run_m01(root, tmp)
        run_h02(root, tmp)
        run_r2h02(root, tmp)
        run_r2h01(root, tmp)
        run_r3n1(root, tmp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-GOVERNANCE-ADVANCE gate binding + atomic stage advance + "
          "immutable candidate identity")


if __name__ == "__main__":
    main()
