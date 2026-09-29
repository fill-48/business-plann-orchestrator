#!/usr/bin/env python3
"""T-UPDATE-ASSUMPTION — canonicalizzazione pinnata, `show-assumption` e
comando transazionale `update-assumption`.

Il test è organizzato per blocchi; oltre al comando `update-assumption`
(sezione dedicata più sotto) copre:

1. **Canonicalizzazione** — esistono DUE serializzazioni
   distinte e confonderle è un errore di implementazione:
   - `dump_json_bytes` (A) resta INVARIATA: byte dei file su disco,
     `indent=2`, `ensure_ascii=False`, newline finale, nessun `sort_keys`.
     È la base degli hash *dei registri* (CAS byte-level su disco);
   - `canonical_hash_bytes` (B) è nuova: `sort_keys=True`, separatori
     compatti, `ensure_ascii=True`, nessuna newline. Serve agli hash di
     **identità logica** (`request_payload_hash`, `expected_record_hash`),
     che devono essere invarianti per ordine chiavi e whitespace dell'input.
   `reason` è escluso dall'identità dell'operazione; `1` e `1.0`
   restano logicamente distinti (tipi JSON diversi).

2. **`show-assumption`** — read-only, nessun lock, stampa il record
   canonico e il `record_hash` che è l'input del CAS di `update-assumption`.

Discriminanti di mutazione: se `request_payload_hash` fosse calcolato sui
byte del file invece che sull'oggetto normalizzato, il retry con chiavi
riordinate non sarebbe riconosciuto; se `expected_record_hash` usasse (A)
invece di (B), il CAS fallirebbe per motivi cosmetici; se `reason`
partecipasse all'identità, un retry con reason variato aprirebbe una
seconda decisione.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit


class TestFailure(AssertionError):
    pass


STAGE = "04_market-and-competition"


def payload(operation_id="op-1", reason="revisione post-evidenza",
            value=1200.0):
    return {
        "operation_id": operation_id,
        "reason": reason,
        "decision": {
            "decision_type": "assumption_update",
            "options_considered": "mantenere 1000 oppure allineare a 1200",
            "motivation": "nuova evidenza di mercato",
            "impact": "SOM Y1 ricalcolato",
            "approver": "founder",
        },
        "changes": [
            {
                "assumption_id": "ASS-001",
                "expected_record_hash": "0" * 64,
                "updates": {"value": value},
            }
        ],
    }


def check_canonicalization(tm):
    # (A) invariata: byte dei file, ordine di inserimento preservato
    data = {"b": 1, "a": 2}
    dumped = tm.dump_json_bytes(data)
    if not dumped.endswith(b"\n"):
        raise TestFailure("dump_json_bytes deve mantenere la newline finale")
    if dumped.decode("utf-8").index('"b"') > dumped.decode("utf-8").index('"a"'):
        raise TestFailure(
            "dump_json_bytes non deve ordinare le chiavi (sarebbe una "
            "modifica breaking di ogni registro esistente)")
    if tm.dump_json_bytes({"k": "caffè"}) != \
            '{\n  "k": "caffè"\n}\n'.encode("utf-8"):
        raise TestFailure("dump_json_bytes deve restare ensure_ascii=False")

    # (B) nuova: identità logica, invariante per ordine chiavi e whitespace
    expected = b'{"a":2,"b":1}'
    if tm.canonical_hash_bytes({"b": 1, "a": 2}) != expected:
        raise TestFailure(
            "canonical_hash_bytes deve usare sort_keys e separatori compatti, "
            f"ottenuto {tm.canonical_hash_bytes({'b': 1, 'a': 2})!r}")
    if tm.canonical_hash_bytes({"k": "caffè"}) != b'{"k":"caff\\u00e8"}':
        raise TestFailure("canonical_hash_bytes deve essere ensure_ascii=True")
    if tm.canonical_hash_bytes({"a": 1}).endswith(b"\n"):
        raise TestFailure("canonical_hash_bytes non è un file: niente newline")

    # ordine chiavi e whitespace irrilevanti sullo stesso payload logico
    text_a = json.dumps(payload(), indent=4, sort_keys=False)
    text_b = json.dumps(payload(), separators=(",", ":"), sort_keys=True)
    hash_a = tm.update_request_payload_hash(json.loads(text_a))
    hash_b = tm.update_request_payload_hash(json.loads(text_b))
    if hash_a != hash_b:
        raise TestFailure(
            "request_payload_hash deve essere calcolato sull'oggetto "
            "normalizzato, non sui byte del file: ordine chiavi e "
            "whitespace diversi hanno prodotto hash diversi")

    # reason escluso dall'identità dell'operazione
    if tm.update_request_payload_hash(payload(reason="A")) != \
            tm.update_request_payload_hash(payload(reason="B")):
        raise TestFailure(
            "reason non deve partecipare all'identità dell'operazione")
    nested = payload()
    nested["changes"][0]["reason"] = "nota per-change"
    if tm.update_request_payload_hash(nested) != \
            tm.update_request_payload_hash(payload()):
        raise TestFailure("reason va escluso a ogni livello in cui compare")

    # payload logicamente diverso -> hash diverso
    if tm.update_request_payload_hash(payload(value=1200.0)) == \
            tm.update_request_payload_hash(payload(value=1300.0)):
        raise TestFailure(
            "un payload logicamente diverso deve produrre un hash diverso")
    if tm.update_request_payload_hash(payload(operation_id="op-1")) == \
            tm.update_request_payload_hash(payload(operation_id="op-2")):
        raise TestFailure("operation_id deve partecipare all'hash")

    # 1 vs 1.0: tipi JSON distinti, nessuna normalizzazione aggiuntiva
    if tm.canonical_hash_bytes({"v": 1}) == tm.canonical_hash_bytes({"v": 1.0}):
        raise TestFailure("1 e 1.0 devono restare logicamente distinti")

    # fingerprint del record: intero record, invariante per ordine chiavi
    record = kit.base_assumption(1)
    shuffled = dict(reversed(list(record.items())))
    if tm.record_fingerprint(record) != tm.record_fingerprint(shuffled):
        raise TestFailure(
            "expected_record_hash deve essere invariante rispetto all'ordine "
            "delle chiavi del record (CAS non cosmetico)")
    touched = dict(record, value=record["value"] + 1)
    if tm.record_fingerprint(record) == tm.record_fingerprint(touched):
        raise TestFailure("il fingerprint deve cambiare se il record cambia")
    # il CAS è sul record INTERO, non sul solo value
    other_field = dict(record, confidence="high")
    if tm.record_fingerprint(record) == tm.record_fingerprint(other_field):
        raise TestFailure(
            "il CAS deve coprire l'intero record, non il solo value")


def check_show_assumption(root, tmp):
    project = kit.make_project(
        tmp, name="show", current_stage=STAGE, status="in_progress",
        completed=["00_idea-discovery", "01_problem-and-need",
                   "02_customer-segmentation", "03_value-proposition"],
        assumptions=[kit.base_assumption(1), kit.base_assumption(2)])
    before = kit.snapshot_tree(project)

    exit_code, out, err = kit.run_tm_cli(
        root, "show-assumption", "--project", project,
        "--assumption", "ASS-001")
    if exit_code != 0:
        raise TestFailure(
            f"show-assumption: exit {exit_code} (err {err.strip()!r})")
    result = kit.tm_result(out, "show-assumption")
    if result.get("assumption", {}).get("id") != "ASS-001":
        raise TestFailure(f"show-assumption non ha stampato il record: {result}")
    digest = result.get("record_hash")
    if not isinstance(digest, str) or len(digest) != 64:
        raise TestFailure(f"record_hash assente o non sha256: {digest!r}")

    tm = kit.load_module(root, kit.TRANSACTION_REL, "transaction_manager")
    register = kit.read_json(project / "shared/assumptions-register.json")
    expected = tm.record_fingerprint(
        next(e for e in register if e["id"] == "ASS-001"))
    if digest != expected:
        raise TestFailure(
            "il record_hash di show-assumption deve essere esattamente "
            "l'expected_record_hash atteso da update-assumption")

    if kit.snapshot_tree(project) != before:
        raise TestFailure("show-assumption deve essere read-only")
    if (project / "shared/.tx/project.lock").exists():
        raise TestFailure("show-assumption non deve acquisire il lock")

    exit_code, out, _ = kit.run_tm_cli(
        root, "show-assumption", "--project", project,
        "--assumption", "ASS-404")
    if exit_code != 1:
        raise TestFailure(
            f"assunzione inesistente: atteso exit 1, ottenuto {exit_code}")
    result = kit.tm_result(out, "show-assumption not found")
    codes = {e["code"] for e in result.get("errors", [])}
    if "assumption_not_found" not in codes:
        raise TestFailure(f"atteso assumption_not_found, ottenuto {codes}")
    if kit.snapshot_tree(project) != before:
        raise TestFailure("show-assumption fallita ha mutato il progetto")


# --------------------------------------------------------------------------
# update-assumption
#
# I progetti di questa sezione hanno `current_stage` sotto lo Stage 4: la
# finestra impact `4..current_stage` è quindi vuota e i casi qui
# isolano il contratto del comando dal canale (b) della pre-commit
# validation, verificato da T-UPD-VIEW su un progetto a Stage 4+.
# --------------------------------------------------------------------------

UPD_STAGE = "01_problem-and-need"


def customers():
    return {
        "id": "ASS-001", "category": "market", "variable": "customers_y1",
        "statement": "Clienti Y1", "kind": "primary", "unit": "count",
        "value": 100, "display_value": "100 clienti",
        "evidence_classification": "founder_assumption",
        "evidence_refs": ["EVD-001"],
        "confidence": "low", "validation_status": "unvalidated",
        "last_updated": "2026-07-15", "previous_values": [],
    }


def arpa():
    return {
        "id": "ASS-002", "category": "pricing", "variable": "arpa_y1",
        "statement": "ARPA Y1", "kind": "primary", "unit": "EUR",
        "value": 10, "display_value": "10 EUR",
        "evidence_classification": "founder_assumption",
        "confidence": "low", "validation_status": "unvalidated",
        "last_updated": "2026-07-15", "previous_values": [],
    }


def revenue():
    return {
        "id": "ASS-003", "category": "market", "variable": "revenue_y1",
        "statement": "Ricavo Y1", "kind": "derived", "unit": "EUR",
        "currency": "EUR", "period": "Y1", "scenario": "base",
        "evidence_classification": "model_estimate",
        "derivation": {"formula": "customers * arpa",
                       "variables": {"customers": "ASS-001",
                                     "arpa": "ASS-002"},
                       "method": "bottom_up"},
        "value": 1000, "display_value": "1000 EUR",
        "validation_status": "unvalidated",
        "last_updated": "2026-07-15", "previous_values": [],
    }


def upd_project(tmp, name):
    return kit.make_project(
        tmp, name=name, current_stage=UPD_STAGE, status="in_progress",
        completed=["00_idea-discovery"],
        assumptions=[customers(), arpa(), revenue()],
        evidence=[{"id": "EVD-001",
                   "statement": "Interviste founder sui volumi Y1",
                   "classification": "internal_evidence",
                   "source": "interviste 2026-07-01",
                   "status": "validated"}])


def fingerprint(tm, project, assumption_id):
    register = kit.read_json(project / "shared/assumptions-register.json")
    entry = next(e for e in register if e["id"] == assumption_id)
    return tm.record_fingerprint(entry)


def changes_payload(tm, project, changes, operation_id="op-1",
                    reason="revisione confermata dal founder", decision=True):
    doc = {"operation_id": operation_id, "reason": reason, "changes": []}
    if decision:
        doc["decision"] = {
            "decision_type": "assumption_update",
            "options_considered": "mantenere il valore corrente vs allineare",
            "motivation": "nuova evidenza raccolta con il founder",
            "impact": "ricavo Y1 ricalcolato",
            "approver": "founder",
        }
    for assumption_id, updates in changes:
        doc["changes"].append({
            "assumption_id": assumption_id,
            "expected_record_hash": fingerprint(tm, project, assumption_id)
            if assumption_id.startswith("ASS-") and _exists(project,
                                                            assumption_id)
            else "0" * 64,
            "updates": updates,
        })
    return doc


def _exists(project, assumption_id):
    register = kit.read_json(project / "shared/assumptions-register.json")
    return any(e["id"] == assumption_id for e in register)


def run_update(root, project, doc, tmp, name="changes.json", env_extra=None):
    path = Path(tmp) / name
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return kit.run_tm_cli(root, "update-assumption", "--project", project,
                          "--changes", path, env_extra=env_extra)


def expect_rejected(root, project, doc, tmp, code, label, name="changes.json"):
    before = kit.snapshot_canonical(project)
    exit_code, out, err = run_update(root, project, doc, tmp, name=name)
    if exit_code != 1:
        raise TestFailure(
            f"{label}: atteso exit 1, ottenuto {exit_code} "
            f"(out {out.strip()!r} err {err.strip()!r})")
    result = kit.tm_result(out, label)
    if result["result"] != "rejected":
        raise TestFailure(f"{label}: result {result['result']!r}")
    codes = {e["code"] for e in result.get("errors", [])}
    if code not in codes:
        raise TestFailure(f"{label}: atteso {code}, ottenuti {sorted(codes)}")
    if kit.snapshot_canonical(project) != before:
        raise TestFailure(f"{label}: rifiuto con mutazione canonica")


def check_happy_path(root, tm, tmp):
    project = upd_project(tmp, "happy")
    doc = changes_payload(tm, project, [
        ("ASS-001", {"value": 120, "display_value": "120 clienti"}),
        ("ASS-003", {"value": 1200, "display_value": "1200 EUR"}),
    ])
    exit_code, out, err = run_update(root, project, doc, tmp)
    if exit_code != 0:
        raise TestFailure(
            f"happy path: exit {exit_code} (out {out.strip()!r} "
            f"err {err.strip()!r})")
    result = kit.tm_result(out, "update happy path")
    if result["result"] != "applied":
        raise TestFailure(f"happy path result: {result}")
    if result.get("decision_id") != "DEC-001":
        raise TestFailure(f"DEC allocato atteso DEC-001: {result}")

    register = {e["id"]: e for e in kit.read_json(
        project / "shared/assumptions-register.json")}
    if register["ASS-001"]["value"] != 120:
        raise TestFailure("il value non è stato aggiornato")
    if register["ASS-002"]["value"] != 10:
        raise TestFailure("un record fuori dal payload è stato toccato")
    history = register["ASS-001"]["previous_values"]
    if len(history) != 1:
        raise TestFailure(f"previous_values non appeso: {history}")
    entry = history[0]
    for key in ("value", "superseded_at", "reason", "decision_id"):
        if key not in entry:
            raise TestFailure(f"previous_values senza {key}: {entry}")
    if entry["value"] != 100:
        raise TestFailure(f"previous_values deve conservare il valore precedente: {entry}")
    if entry["decision_id"] != "DEC-001":
        raise TestFailure(
            f"previous_values.decision_id deve essere l'id DEFINITIVO, mai un "
            f"placeholder: {entry}")

    decisions = kit.read_json(project / "shared/decisions-register.json")
    if len(decisions["decisions"]) != 1:
        raise TestFailure(f"decisions-register: {decisions}")
    record = decisions["decisions"][0]
    if record["id"] != "DEC-001" or record["decision_type"] != "assumption_update":
        raise TestFailure(f"record DEC inatteso: {record}")
    if sorted(record["target_refs"]) != ["ASS-001", "ASS-003"]:
        raise TestFailure(
            "una sola decisione per operazione, con target_refs = tutti gli "
            f"assumption_id del payload: {record['target_refs']}")
    if record["operation_id"] != "op-1":
        raise TestFailure("il record DEC deve tracciare l'operation_id")
    if record["request_payload_hash"] != tm.update_request_payload_hash(doc):
        raise TestFailure("request_payload_hash non registrato correttamente")
    if decisions.get("initialized_from") is None:
        raise TestFailure(
            "init lazy su progetto senza decisions-register: manca l'attestazione initialized_from")

    log = (project / "shared/decision-log.md").read_text(encoding="utf-8")
    if "DEC-001" not in log:
        raise TestFailure("decision-log senza la riga derivata del DEC")

    events = [json.loads(line) for line in
              (project / "shared/audit-log.jsonl").read_text(
                  encoding="utf-8").splitlines() if line]
    applied = [e for e in events if e.get("action") == "tx_update_assumption"]
    if not applied or applied[-1].get("result") != "applied":
        raise TestFailure(f"evento audit assumption_updated assente: {events}")
    if applied[-1].get("operation_id") != "op-1":
        raise TestFailure("l'evento audit deve riportare l'operation_id")

    journals = [kit.read_json(p) for p in kit.find_journals(project)]
    committed = [j for j in journals if j["state"] == "committed"]
    if len(committed) != 1:
        raise TestFailure(
            "l'update multi-assumption deve stare in UN SOLO journal: "
            f"{[j['state'] for j in journals]}")
    journal = committed[0]
    if journal["mode"] != "update_assumption":
        raise TestFailure(f"journal mode: {journal['mode']!r}")
    for key in ("operation_id", "request_payload_hash", "reserved_decision_id",
                "decisions_register_hash", "register_hash", "target_refs"):
        if key not in journal:
            raise TestFailure(f"journal senza {key}")
    if journal["reserved_decision_id"] != "DEC-001":
        raise TestFailure("reserved_decision_id non registrato nel journal")
    paths = {e["path"] for e in journal["write_set"]}
    expected_paths = {"shared/assumptions-register.json",
                      "shared/decisions-register.json",
                      "shared/decision-log.md",
                      "shared/project-status.md",
                      "shared/audit-log.jsonl"}
    if paths != expected_paths:
        raise TestFailure(f"write-set inatteso: {sorted(paths)}")
    pre = {e["path"]: e["pre_hash"] for e in journal["write_set"]}
    if pre["shared/decisions-register.json"] is not None:
        raise TestFailure(
            "l'init lazy deve avere pre_hash null nel write-set, così che un "
            "rollback elimini il registro")
    return project, doc


def check_idempotence(root, tm, tmp):
    project, doc = check_happy_path(root, tm, tmp)
    before = kit.snapshot_tree(project)

    # stesso operation_id + stesso payload logico, ri-serializzato con chiavi
    # in ordine diverso e reason variato -> already_applied, nessuna scrittura
    retry = json.loads(json.dumps(doc, sort_keys=True))
    retry["reason"] = "testo completamente diverso"
    exit_code, out, err = run_update(root, project, retry, tmp,
                                     name="retry.json")
    if exit_code != 0:
        raise TestFailure(
            f"retry idempotente: atteso exit 0, ottenuto {exit_code} "
            f"(err {err.strip()!r})")
    result = kit.tm_result(out, "retry")
    if result["result"] != "already_applied":
        raise TestFailure(f"retry deve dare already_applied: {result}")
    after = {k: v for k, v in kit.snapshot_tree(project).items()
             if not k.startswith("shared/.tx/")}
    if after != {k: v for k, v in before.items()
                 if not k.startswith("shared/.tx/")}:
        raise TestFailure("already_applied ha scritto qualcosa")

    # stesso operation_id, payload logicamente diverso -> conflitto
    conflict = json.loads(json.dumps(doc))
    conflict["changes"][0]["updates"]["value"] = 999
    expect_rejected(root, project, conflict, tmp, "operation_id_conflict",
                    "stesso operation_id con payload diverso",
                    name="conflict.json")

    # nuovo operation_id con lo stesso valore -> NUOVA decisione, mai silenziata
    again = changes_payload(
        tm, project, [("ASS-001", {"value": 120})], operation_id="op-2")
    exit_code, out, err = run_update(root, project, again, tmp,
                                     name="again.json")
    if exit_code != 0:
        raise TestFailure(
            f"nuovo operation_id: exit {exit_code} (err {err.strip()!r})")
    result = kit.tm_result(out, "nuova decisione")
    if result.get("decision_id") != "DEC-002":
        raise TestFailure(
            f"un nuovo operation_id deve allocare una nuova decisione: {result}")


def check_contract_rejections(root, tm, tmp):
    project = upd_project(tmp, "reject")
    before = kit.snapshot_canonical(project)

    stale = changes_payload(tm, project, [("ASS-001", {"value": 120})])
    stale["changes"][0]["expected_record_hash"] = "b" * 64
    expect_rejected(root, project, stale, tmp, "stale_record_hash",
                    "CAS su fingerprint stantio")

    missing = changes_payload(tm, project, [("ASS-404", {"value": 1})])
    expect_rejected(root, project, missing, tmp, "assumption_not_found",
                    "assunzione inesistente")

    no_decision = changes_payload(tm, project, [("ASS-001", {"value": 120})],
                                  decision=False)
    expect_rejected(root, project, no_decision, tmp, "decision_required",
                    "payload senza decisione")

    bad_decision = changes_payload(tm, project, [("ASS-001", {"value": 120})])
    del bad_decision["decision"]["motivation"]
    expect_rejected(root, project, bad_decision, tmp, "decision_required",
                    "payload decisione non conforme")

    bad_field = changes_payload(tm, project,
                                [("ASS-001", {"unit": "count"})])
    expect_rejected(root, project, bad_field, tmp, "update_field_not_allowed",
                    "campo fuori whitelist")

    formula = changes_payload(
        tm, project, [("ASS-003", {"derivation.formula": "customers + arpa"})])
    expect_rejected(root, project, formula, tmp, "update_field_not_allowed",
                    "derivation.formula non è mai modificabile")

    duplicate = changes_payload(tm, project, [("ASS-001", {"value": 120}),
                                              ("ASS-001", {"value": 130})])
    expect_rejected(root, project, duplicate, tmp,
                    "duplicate_assumption_change",
                    "un record, un change")

    derived = changes_payload(tm, project, [("ASS-003", {"value": 5000})])
    expect_rejected(root, project, derived, tmp, "derived_update_incoherent",
                    "value di una derivata senza driver coerenti")

    if kit.snapshot_canonical(project) != before:
        raise TestFailure("i rifiuti di contratto hanno mutato il canonico")
    if (project / "shared/decisions-register.json").exists():
        raise TestFailure(
            "nessun rifiuto deve creare il decisions-register (nessuna "
            "scrittura canonica prima di applying)")

    # nessun DEC consumato dai rifiuti: il primo update valido resta DEC-001
    ok = changes_payload(tm, project, [("ASS-001", {"value": 120}),
                                       ("ASS-003", {"value": 1200})],
                         operation_id="op-after-reject")
    exit_code, out, err = run_update(root, project, ok, tmp, name="ok.json")
    if exit_code != 0:
        raise TestFailure(f"update dopo i rifiuti: exit {exit_code} "
                          f"(err {err.strip()!r})")
    if kit.tm_result(out, "post-reject").get("decision_id") != "DEC-001":
        raise TestFailure("un rifiuto ha consumato un DEC-*")


def check_internal_reference_channel(root, tm, tmp):
    """Canale TM-interno pre-commit dei riferimenti, controlli 2/3/4/5."""
    project = upd_project(tmp, "refchannel")

    # (2) chiavi di derivation.variables: aggiunta, rimozione, rinomina
    added = changes_payload(tm, project, [
        ("ASS-003", {"derivation.variables": {"customers": "ASS-001",
                                              "arpa": "ASS-002",
                                              "extra": "ASS-002"}})])
    expect_rejected(root, project, added, tmp, "derivation_keys_changed",
                    "chiave di derivation.variables aggiunta")

    removed = changes_payload(tm, project, [
        ("ASS-003", {"derivation.variables": {"customers": "ASS-001"}})])
    expect_rejected(root, project, removed, tmp, "derivation_keys_changed",
                    "chiave di derivation.variables rimossa")

    renamed = changes_payload(tm, project, [
        ("ASS-003", {"derivation.variables": {"clienti": "ASS-001",
                                              "arpa": "ASS-002"}})])
    expect_rejected(root, project, renamed, tmp, "derivation_keys_changed",
                    "chiave di derivation.variables rinominata")

    # (3) nuovo valore che non risolve nel registro aggiornato
    unresolved = changes_payload(tm, project, [
        ("ASS-003", {"derivation.variables": {"customers": "ASS-404",
                                              "arpa": "ASS-002"}})])
    expect_rejected(root, project, unresolved, tmp,
                    "derivation_variable_unresolved",
                    "derivation.variables verso un ASS-* inesistente")

    # (4) ciclo di derivation sull'intero registro risultante
    cycle = changes_payload(tm, project, [
        ("ASS-003", {"derivation.variables": {"customers": "ASS-003",
                                              "arpa": "ASS-002"}})])
    expect_rejected(root, project, cycle, tmp, "circular_derivation",
                    "ciclo derivativo introdotto dall'update")

    # (5) evidence_refs verso un EVD-* inesistente
    evidence = changes_payload(tm, project, [
        ("ASS-001", {"evidence_refs": ["EVD-001", "EVD-404"]})])
    expect_rejected(root, project, evidence, tmp, "evidence_ref_not_found",
                    "evidence_refs verso un EVD-* inesistente")

    # ri-referenziazione legittima: soli VALORI, chiavi invariate
    ok = changes_payload(tm, project, [
        ("ASS-002", {"value": 10}),
        ("ASS-003", {"derivation.variables": {"customers": "ASS-001",
                                              "arpa": "ASS-002"},
                     "value": 1000})],
        operation_id="op-rereference")
    exit_code, out, err = run_update(root, project, ok, tmp, name="okref.json")
    if exit_code != 0:
        raise TestFailure(
            "la sostituzione dei soli valori con chiavi invariate deve essere "
            f"ammessa: exit {exit_code} (out {out.strip()!r} err {err.strip()!r})")


def run(root):
    tm = kit.load_module(root, kit.TRANSACTION_REL, "transaction_manager")
    check_canonicalization(tm)
    with tempfile.TemporaryDirectory(prefix="bpo-upd-") as tmp:
        tmp = Path(tmp)
        check_show_assumption(root, tmp)
        check_idempotence(root, tm, tmp)
        check_contract_rejections(root, tm, tmp)
        check_internal_reference_channel(root, tm, tmp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-UPDATE-ASSUMPTION canonical hashes + show-assumption")


if __name__ == "__main__":
    main()
