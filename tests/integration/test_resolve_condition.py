#!/usr/bin/env python3
"""T-RESOLVE-CONDITION — chiusura transazionale delle COND-*
(comando `resolve-condition` del transaction manager).

Apertura, blocco su COND scadute (`condition_due`) e chiusura delle COND
sono tutte transazionali: una chiusura non journaled, interrotta da un
crash a metà, lascerebbe `resolution_status` incoerente con decision-log e
audit.

**Regola unica della precondizione**, senza eccezioni:

| `--resolution` | `--decision`  | `--evidence-ref`      | `DEC-*` |
|----------------|---------------|-----------------------|---------|
| `resolved`     | obbligatorio  | obbligatorio          | sempre  |
| `waived`       | obbligatorio  | assente (⇒ rejected)  | sempre  |

`--decision` è il *contenuto* del record `DEC-*` e la giustificazione di
governance: non è un'alternativa all'evidenza. `resolved` significa
`verified_fact` e richiede quindi **anche** l'evidenza; un `--evidence-ref`
in una risoluzione `waived` è una contraddizione semantica e va respinto invece che
ignorato in silenzio. Non esiste chiusura di condizione senza decisione
tracciata.

**Ruolo della validation view.** `resolve-condition`
materializza la view per uniformità di ciclo di vita con `update-assumption`
(stesso campo di journal, stesso cleanup, stesso ramo di recovery), **non**
come input dei controlli: `schema_errors` e `decisions_register_problems`
girano sugli oggetti proposti in memoria, che sono gli stessi byte poi
committati. `check_validation_view_is_not_an_input` documenta esattamente
questo comportamento.

**Guardie pre-commit.** CAS di conferma su entrambi i rami
(`conditions_hash`, `decisions_register_hash`) → `canonical_drift`, exit 1,
COND ancora `open`, nessun `DEC-` consumato; `verify_write_set` su un target
corrotto dopo la write → `content_verification_failed`, exit 3, rollback da
snapshot, nessun marker `committed`.

Invarianti verificate anche: `evidence_not_found` per lettura diretta del
registro evidenze (mai refint); `condition_not_open`; idempotenza
via `operation_id` + `request_payload_hash` (con `evidence_ref` normalizzato
a `null` nel ramo waived); nessuna matrice impact; il blocco `condition_due`
cessa dopo la chiusura; crash a metà `applying` recuperato con il
decisions-register nel write-set.
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


def condition(cond_id="COND-001", status="open"):
    return {
        "id": cond_id,
        "stage": "00_idea-discovery",
        "description": "Validare il pricing con tre clienti beachhead",
        "severity": "high",
        "owner": "founder",
        "validation_action": "tre interviste con conferma di prezzo",
        "due_before_stage": STAGE,
        "resolution_status": status,
        "created_at": "2026-07-10",
    }


def evidence():
    return [{
        "id": "EVD-001",
        "statement": "Tre clienti beachhead confermano il prezzo di 100 EUR",
        "classification": "internal_evidence",
        "source": "interviste 2026-07-18",
        "status": "validated",
    }]


def decision_json(decision_type="condition_resolution", motivation=None,
                  approver="founder"):
    doc = {
        "decision_type": decision_type,
        "options_considered": "chiudere con evidenza vs rinviare",
        "impact": "il gate di Stage 1 non è più bloccato",
        "approver": approver,
    }
    if motivation is not False:
        doc["motivation"] = motivation or "evidenza raccolta e verificata"
    return json.dumps(doc, ensure_ascii=False)


def make_cond_project(tmp, name, conditions=None):
    return kit.make_project(
        tmp, name=name, current_stage=STAGE, status="in_progress",
        completed=["00_idea-discovery"],
        conditions=conditions if conditions is not None else [condition()],
        evidence=evidence())


def resolve(root, project, resolution="resolved", cond="COND-001",
            operation_id="op-1", decision=None, evidence_ref="EVD-001",
            reason="chiusura confermata dal founder", env_extra=None):
    args = ["resolve-condition", "--project", project, "--condition", cond,
            "--resolution", resolution, "--operation-id", operation_id,
            "--reason", reason]
    if decision is not False:
        args += ["--decision", decision if decision else decision_json()]
    if evidence_ref is not None:
        args += ["--evidence-ref", evidence_ref]
    return kit.run_tm_cli(root, *args, env_extra=env_extra)


def expect_rejected(root, project, label, code, **kwargs):
    before = kit.snapshot_canonical(project)
    exit_code, out, err = resolve(root, project, **kwargs)
    if exit_code != 1:
        raise TestFailure(
            f"{label}: atteso exit 1, ottenuto {exit_code} "
            f"(out {out.strip()!r} err {err.strip()!r})")
    result = kit.tm_result(out, label)
    codes = {e["code"] for e in result.get("errors", [])}
    if code not in codes:
        raise TestFailure(f"{label}: atteso {code}, ottenuti {sorted(codes)}")
    if kit.snapshot_canonical(project) != before:
        raise TestFailure(f"{label}: rifiuto con mutazione canonica")


def check_resolved_branch(root, tmp):
    project = make_cond_project(tmp, "resolved")
    exit_code, out, err = resolve(root, project)
    if exit_code != 0:
        raise TestFailure(
            f"resolved: exit {exit_code} (out {out.strip()!r} "
            f"err {err.strip()!r})")
    result = kit.tm_result(out, "resolved")
    if result.get("decision_id") != "DEC-001":
        raise TestFailure(f"ogni resolve deve allocare un DEC-*: {result}")

    conditions = kit.read_json(project / "shared/conditions-register.json")
    cond = conditions[0]
    if cond["resolution_status"] != "resolved":
        raise TestFailure(f"resolution_status: {cond}")
    if cond.get("resolved_by") != "DEC-001":
        raise TestFailure(f"resolved_by deve puntare al DEC allocato: {cond}")
    if cond.get("evidence_ref") != "EVD-001":
        raise TestFailure(f"evidence_ref non registrato: {cond}")
    if not cond.get("last_updated"):
        raise TestFailure("last_updated non aggiornato")

    decisions = kit.read_json(project / "shared/decisions-register.json")
    record = decisions["decisions"][0]
    if record["decision_type"] != "condition_resolution":
        raise TestFailure(f"decision_type: {record}")
    if record["target_refs"] != ["COND-001"]:
        raise TestFailure(f"target_refs: {record}")

    log = (project / "shared/decision-log.md").read_text(encoding="utf-8")
    if "DEC-001" not in log or "COND-001" not in log:
        raise TestFailure("decision-log senza la riga derivata")

    events = [json.loads(line) for line in
              (project / "shared/audit-log.jsonl").read_text(
                  encoding="utf-8").splitlines() if line]
    resolved_events = [e for e in events
                       if e.get("action") == "tx_resolve_condition"]
    if not resolved_events or resolved_events[-1].get("operation_id") != "op-1":
        raise TestFailure(f"evento audit condition_resolved assente: {events}")

    journal = [kit.read_json(p) for p in kit.find_journals(project)
               if kit.read_json(p)["state"] == "committed"][0]
    if journal["mode"] != "resolve_condition":
        raise TestFailure(f"journal mode: {journal['mode']!r}")
    paths = {e["path"] for e in journal["write_set"]}
    expected = {"shared/conditions-register.json",
                "shared/decisions-register.json", "shared/decision-log.md",
                "shared/project-status.md", "shared/audit-log.jsonl"}
    if paths != expected:
        raise TestFailure(f"write-set inatteso: {sorted(paths)}")
    if "shared/assumptions-register.json" in paths:
        raise TestFailure(
            "resolve-condition non deve toccare l'assumptions-register")

    # nessuna matrice impact: la risoluzione non muta dati quantitativi
    if journal.get("validators_invoked"):
        raise TestFailure(
            "resolve-condition non deve eseguire la matrice impact: "
            f"{journal['validators_invoked']}")
    # refint non è invocato in nessun caso
    for entry in journal.get("validation", []):
        if entry.get("validator") == "validate_referential_integrity":
            raise TestFailure("refint invocato dalla pre-commit validation")
    return project


def check_waived_branch(root, tmp):
    project = make_cond_project(tmp, "waived")
    exit_code, out, err = resolve(root, project, resolution="waived",
                                  evidence_ref=None, operation_id="op-waive")
    if exit_code != 0:
        raise TestFailure(
            f"waived: exit {exit_code} (out {out.strip()!r} "
            f"err {err.strip()!r})")
    result = kit.tm_result(out, "waived")
    if result.get("decision_id") != "DEC-001":
        raise TestFailure(
            f"anche una risoluzione waived alloca sempre un DEC-*: {result}")
    cond = kit.read_json(project / "shared/conditions-register.json")[0]
    if cond["resolution_status"] != "waived":
        raise TestFailure(f"resolution_status: {cond}")
    if cond.get("evidence_ref") is not None:
        raise TestFailure(
            f"una risoluzione waived non deve registrare un'evidenza: {cond}")


def check_precondition_matrix(root, tmp):
    project = make_cond_project(tmp, "precond")

    expect_rejected(root, project, "resolved senza --decision",
                    "decision_required", decision=False)
    expect_rejected(root, project, "resolved con decisione non conforme",
                    "decision_required",
                    decision=decision_json(motivation=False))
    expect_rejected(root, project, "resolved con decision_type errato",
                    "decision_required",
                    decision=decision_json(decision_type="assumption_update"))
    expect_rejected(root, project, "resolved con decisione non JSON",
                    "decision_required", decision="{non json")
    expect_rejected(root, project, "resolved senza --evidence-ref",
                    "evidence_required", evidence_ref=None)
    expect_rejected(root, project, "waived senza --decision",
                    "decision_required", resolution="waived",
                    evidence_ref=None, decision=False)
    expect_rejected(root, project, "waived con --evidence-ref",
                    "evidence_not_allowed_for_waiver", resolution="waived")
    expect_rejected(root, project, "resolved con EVD-* inesistente",
                    "evidence_not_found", evidence_ref="EVD-404")
    expect_rejected(root, project, "COND-* inesistente", "condition_not_open",
                    cond="COND-404")

    if (project / "shared/decisions-register.json").exists():
        raise TestFailure(
            "nessun rifiuto deve creare il decisions-register")

    # COND già chiusa: non più `open`
    project_closed = make_cond_project(tmp, "closed",
                                       conditions=[condition(status="resolved")])
    expect_rejected(root, project_closed, "COND non open", "condition_not_open")


def check_idempotence(root, tmp):
    project = make_cond_project(tmp, "idem")
    exit_code, out, _ = resolve(root, project, operation_id="op-idem")
    if exit_code != 0:
        raise TestFailure("setup idempotenza fallito")
    before = {k: v for k, v in kit.snapshot_tree(project).items()
              if not k.startswith("shared/.tx/")}

    # retry identico, con reason variato: già applicato, nessuna scrittura
    exit_code, out, err = resolve(root, project, operation_id="op-idem",
                                  reason="testo diverso")
    if exit_code != 0:
        raise TestFailure(f"retry: exit {exit_code} (err {err.strip()!r})")
    if kit.tm_result(out, "retry")["result"] != "already_applied":
        raise TestFailure("il retry deve dare already_applied")
    after = {k: v for k, v in kit.snapshot_tree(project).items()
             if not k.startswith("shared/.tx/")}
    if after != before:
        raise TestFailure("already_applied ha scritto qualcosa")

    # stesso operation_id, payload diverso -> conflitto
    exit_code, out, _ = resolve(root, project, operation_id="op-idem",
                                resolution="waived", evidence_ref=None)
    if exit_code != 1:
        raise TestFailure("payload diverso con stesso operation_id deve "
                          "essere respinto")
    codes = {e["code"] for e in kit.tm_result(out, "conflict")["errors"]}
    if "operation_id_conflict" not in codes:
        raise TestFailure(f"atteso operation_id_conflict, ottenuti {codes}")


def check_hash_normalisation(root, tm):
    """`evidence_ref` normalizzato a null nel ramo waived, così
    che la chiave di idempotenza sia totalmente definita in entrambi i rami;
    `reason` sempre escluso."""
    decision = json.loads(decision_json())
    waived_absent = tm.resolve_request_payload_hash(
        "COND-001", "waived", None, decision, "op")
    waived_spurious = tm.resolve_request_payload_hash(
        "COND-001", "waived", "EVD-001", decision, "op")
    if waived_absent != waived_spurious:
        raise TestFailure(
            "nel ramo waived evidence_ref va normalizzato a null")
    resolved_a = tm.resolve_request_payload_hash(
        "COND-001", "resolved", "EVD-001", decision, "op")
    resolved_b = tm.resolve_request_payload_hash(
        "COND-001", "resolved", "EVD-002", decision, "op")
    if resolved_a == resolved_b:
        raise TestFailure(
            "nel ramo resolved l'evidence_ref partecipa all'identità")
    if resolved_a == waived_absent:
        raise TestFailure("la resolution deve partecipare all'identità")


def check_gate_unblocked(root, tmp):
    project = make_cond_project(tmp, "gate")

    def gate_codes():
        exit_code, out, err = kit.run_validator_cli(
            root, "validate_stage_gate", project=project, stage=STAGE,
            phase="ingress")
        if exit_code == 2:
            raise TestFailure(f"gate usage error: {err.strip()!r}")
        return {e["code"] for e in kit.parse_report(out, "gate")["errors"]}

    if "condition_due" not in gate_codes():
        raise TestFailure(
            "setup: la COND aperta e dovuta deve bloccare il gate")
    exit_code, _, err = resolve(root, project, operation_id="op-gate")
    if exit_code != 0:
        raise TestFailure(f"resolve fallita: {err.strip()!r}")
    if "condition_due" in gate_codes():
        raise TestFailure(
            "dopo la chiusura la COND non deve più bloccare il gate")


def check_crash_recovery(root, tmp):
    project = make_cond_project(tmp, "crash")
    before = kit.snapshot_canonical(project)
    exit_code, _, _ = resolve(root, project, operation_id="op-crash",
                              env_extra={"BPO_TX_TEST_CRASH":
                                         "after_writes:1"})
    if exit_code == 0:
        raise TestFailure("il crash non deve dare exit 0")
    journal_path = kit.find_journals(project)[-1]
    if kit.read_json(journal_path)["state"] != "applying":
        raise TestFailure("il crash a metà applying deve lasciare applying")

    exit_code, out, err = kit.run_tm_cli(root, "recover", "--project", project)
    if exit_code != 0:
        raise TestFailure(f"recover: {err.strip()!r}")
    if kit.read_json(journal_path)["state"] != "rolled_back":
        raise TestFailure("un applying incompleto deve essere rolled back")
    if kit.snapshot_canonical(project) != before:
        raise TestFailure(
            "il rollback deve ripristinare esattamente lo stato precedente, "
            "decisions-register incluso")
    if (project / "shared/decisions-register.json").exists():
        raise TestFailure(
            "il rollback deve eliminare il decisions-register creato dalla "
            "transazione (pre_hash null)")

    # retry dopo rollback: nessun DEC consumato
    exit_code, out, err = resolve(root, project, operation_id="op-retry")
    if exit_code != 0:
        raise TestFailure(f"retry dopo rollback: {err.strip()!r}")
    if kit.tm_result(out, "retry")["decision_id"] != "DEC-001":
        raise TestFailure("il rollback ha consumato un DEC-*")


CONDITIONS_REL = "shared/conditions-register.json"
DECISIONS_REL = "shared/decisions-register.json"


def concurrent_bytes(doc):
    """Byte di uno scrittore concorrente su UNA riga: l'hook di test scrive
    testo e un contenuto multi-riga subirebbe la traduzione newline di
    Windows, falsificando i byte attesi dal test."""
    return json.dumps(doc, ensure_ascii=False)


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_journals(project, state=None, operation_id=None):
    out = []
    for path in kit.find_journals(project):
        journal = kit.read_json(path)
        if journal.get("mode") != "resolve_condition":
            continue
        if state and journal.get("state") != state:
            continue
        if operation_id and journal.get("operation_id") != operation_id:
            continue
        out.append(journal)
    return out


def expect_drift(root, project, before, rel, mutated, label, **kwargs):
    """CAS di conferma: fra `validated` e `applying` il canonico muta.
    La transazione deve fermarsi prima di qualsiasi scrittura."""
    exit_code, out, err = resolve(
        root, project,
        env_extra={"BPO_TX_TEST_MUTATE_CANONICAL": f"{rel}={mutated}"},
        **kwargs)
    if exit_code != 1:
        raise TestFailure(
            f"{label}: atteso exit 1, ottenuto {exit_code} "
            f"(out {out.strip()!r} err {err.strip()!r})")
    errors = kit.tm_result(out, label).get("errors", [])
    codes = {e["code"] for e in errors}
    if "canonical_drift" not in codes:
        raise TestFailure(f"{label}: atteso canonical_drift, ottenuti "
                          f"{sorted(codes)}")
    if not any(rel in e.get("message", "") for e in errors):
        raise TestFailure(
            f"{label}: il messaggio non nomina il file divergente: {errors}")

    operation_id = kwargs.get("operation_id")
    drifted = [j for j in resolve_journals(project, "rolled_back",
                                           operation_id)
               if (j.get("error") or {}).get("code") == "canonical_drift"]
    if len(drifted) != 1:
        raise TestFailure(
            f"{label}: atteso un journal rolled_back con canonical_drift, "
            f"trovati {len(drifted)}")
    if resolve_journals(project, "committed", operation_id):
        raise TestFailure(f"{label}: nessun marker committed deve comparire")

    expected = dict(before)
    expected[rel] = sha256_text(mutated)
    after = kit.snapshot_canonical(project)
    if after != expected:
        differing = sorted(k for k in set(expected) | set(after)
                           if expected.get(k) != after.get(k))
        raise TestFailure(
            f"{label}: i byte dello scrittore concorrente devono restare "
            f"intatti e nulla d'altro deve cambiare ({differing})")
    return drifted[0]


def check_canonical_drift_conditions(root, tmp):
    """Ramo `conditions_hash`: il registro delle condizioni muta fra la
    validazione e l'applicazione. La COND resta `open`, il decisions-register
    non nasce, il `DEC-` riservato non è consumato."""
    project = make_cond_project(tmp, "drift-cond")
    before = kit.snapshot_canonical(project)
    conditions = kit.read_json(project / CONDITIONS_REL)
    conditions[0]["description"] = "descrizione riscritta da un altro processo"
    mutated = concurrent_bytes(conditions)

    journal = expect_drift(root, project, before, CONDITIONS_REL, mutated,
                           "drift conditions", operation_id="op-drift-cond")

    cond = kit.read_json(project / CONDITIONS_REL)[0]
    if cond["resolution_status"] != "open":
        raise TestFailure(
            f"drift: la COND deve restare open, trovato "
            f"{cond['resolution_status']!r}")
    if (project / DECISIONS_REL).exists():
        raise TestFailure(
            "drift: il decisions-register assente prima deve restare assente")
    reserved = journal.get("reserved_decision_id")
    if reserved != "DEC-001":
        raise TestFailure(f"DEC riservato inatteso: {reserved!r}")

    # retry con lo STESSO operation_id: stesso DEC-, mai consumato dal drift
    exit_code, out, err = resolve(root, project, operation_id="op-drift-cond")
    if exit_code != 0:
        raise TestFailure(f"retry dopo drift: {err.strip()!r}")
    if kit.tm_result(out, "retry drift")["decision_id"] != reserved:
        raise TestFailure(f"il retry deve riallocare {reserved}: il drift ha "
                          "consumato un DEC-*")


def check_canonical_drift_decisions(root, tmp):
    """Ramo `decisions_register_hash`: il registro delle decisioni muta nella
    stessa finestra. La mutazione non aggiunge record, quindi il `DEC-`
    riservato resta identico al retry."""
    project = make_cond_project(
        tmp, "drift-dec",
        conditions=[condition(), condition(cond_id="COND-002")])
    exit_code, _, err = resolve(root, project, operation_id="op-setup")
    if exit_code != 0:
        raise TestFailure(f"setup drift-decisions: {err.strip()!r}")

    before = kit.snapshot_canonical(project)
    decisions = kit.read_json(project / DECISIONS_REL)
    decisions["decisions"][0]["motivation"] = "riscritta da un altro processo"
    mutated = concurrent_bytes(decisions)

    journal = expect_drift(root, project, before, DECISIONS_REL, mutated,
                           "drift decisions", cond="COND-002",
                           operation_id="op-drift-dec")

    after = kit.read_json(project / DECISIONS_REL)
    if len(after["decisions"]) != 1:
        raise TestFailure(
            f"il drift non deve aggiungere record: {after['decisions']}")
    if kit.read_json(project / CONDITIONS_REL)[1]["resolution_status"] != "open":
        raise TestFailure("drift: COND-002 deve restare open")
    reserved = journal.get("reserved_decision_id")
    if reserved != "DEC-002":
        raise TestFailure(f"DEC riservato inatteso: {reserved!r}")

    exit_code, out, err = resolve(root, project, cond="COND-002",
                                  operation_id="op-drift-dec")
    if exit_code != 0:
        raise TestFailure(f"retry dopo drift decisions: {err.strip()!r}")
    if kit.tm_result(out, "retry drift dec")["decision_id"] != reserved:
        raise TestFailure(f"il retry deve riallocare {reserved}: il drift ha "
                          "consumato un DEC-*")


def check_content_verification_failed(root, tmp):
    """Target del write-set corrotto dopo la write e prima di
    `verify_write_set`: rollback da snapshot, exit 3, nessun marker
    `committed`, COND ancora open, nessun `DEC-` consumato."""
    project = make_cond_project(tmp, "verify-cond")
    before = kit.snapshot_canonical(project)
    exit_code, out, err = resolve(
        root, project, operation_id="op-verify",
        env_extra={"BPO_TX_TEST_CORRUPT_AFTER_WRITE":
                   "shared/decision-log.md=corrotto dopo la write"})
    if exit_code != 3:
        raise TestFailure(
            f"write-set corrotto: atteso exit 3, ottenuto {exit_code} "
            f"(out {out.strip()!r} err {err.strip()!r})")
    codes = {e["code"] for e in kit.tm_result(out, "verify").get("errors", [])}
    if "content_verification_failed" not in codes:
        raise TestFailure(
            f"atteso content_verification_failed, ottenuti {sorted(codes)}")
    failed = [j for j in resolve_journals(project, "rolled_back", "op-verify")
              if (j.get("error") or {}).get("code")
              == "content_verification_failed"]
    if len(failed) != 1:
        raise TestFailure(
            f"atteso un journal rolled_back con content_verification_failed, "
            f"trovati {len(failed)}")
    if resolve_journals(project, "committed", "op-verify"):
        raise TestFailure(
            "un write-set non verificato non deve produrre un marker "
            "committed")
    if kit.snapshot_canonical(project) != before:
        raise TestFailure(
            "restore_snapshot non ha ripristinato lo stato byte-identico")
    if (project / DECISIONS_REL).exists():
        raise TestFailure(
            "il rollback deve eliminare il decisions-register creato dalla "
            "transazione (pre_hash null)")
    events = [json.loads(line) for line in
              (project / "shared/audit-log.jsonl").read_text(
                  encoding="utf-8").splitlines() if line]
    if [e for e in events if e.get("result") == "applied"]:
        raise TestFailure(
            f"audit transazionale: l'evento audit `applied` è nel write-set e deve tornare "
            f"indietro col rollback: {events}")

    exit_code, out, err = resolve(root, project, operation_id="op-verify")
    if exit_code != 0:
        raise TestFailure(f"retry dopo verifica fallita: {err.strip()!r}")
    if kit.tm_result(out, "retry verify")["decision_id"] != "DEC-001":
        raise TestFailure("il rollback post-verify ha consumato un DEC-*")


def check_validation_view_is_not_an_input(root, tmp):
    """La view è materializzata per uniformità di ciclo di
    vita con `update-assumption` (stesso journal, stesso cleanup, stesso
    recovery), **non** come input dei controlli: `schema_errors` e
    `decisions_register_problems` girano sugli oggetti proposti in memoria.

    L'asserzione documenta esattamente questo: il journal registra il path
    della view, nessun validator è invocato su di essa, e dopo il commit non
    resta alcuna view su disco."""
    project = make_cond_project(tmp, "view-role")
    exit_code, _, err = resolve(root, project, operation_id="op-view")
    if exit_code != 0:
        raise TestFailure(f"setup view-role: {err.strip()!r}")
    journal = resolve_journals(project, "committed")[0]
    view_rel = journal.get("validation_view_path")
    if not view_rel:
        raise TestFailure(
            "la view resta nel ciclo di vita transazionale: il journal deve registrarne il "
            "path per il cleanup e per il recovery")
    if journal.get("validators_invoked") or journal.get("validation"):
        raise TestFailure(
            "la view NON è input di alcun controllo: resolve-condition non "
            f"invoca validator ({journal.get('validators_invoked')})")
    if (project / view_rel).exists():
        raise TestFailure(f"view residua dopo il commit: {view_rel}")


def run(root):
    tm = kit.load_module(root, kit.TRANSACTION_REL, "transaction_manager")
    check_hash_normalisation(root, tm)
    with tempfile.TemporaryDirectory(prefix="bpo-cond-") as tmp:
        tmp = Path(tmp)
        check_resolved_branch(root, tmp)
        check_waived_branch(root, tmp)
        check_precondition_matrix(root, tmp)
        check_idempotence(root, tmp)
        check_gate_unblocked(root, tmp)
        check_crash_recovery(root, tmp)
        check_canonical_drift_conditions(root, tmp)
        check_canonical_drift_decisions(root, tmp)
        check_content_verification_failed(root, tmp)
        check_validation_view_is_not_an_input(root, tmp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-RESOLVE-CONDITION chiusura transazionale delle COND-*")


if __name__ == "__main__":
    main()
