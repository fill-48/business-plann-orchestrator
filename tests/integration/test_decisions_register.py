#!/usr/bin/env python3
"""T-DECISIONS-REGISTER — `shared/decisions-register.json` come fonte canonica
delle decisioni DEC-*.

Il decision-log Markdown NON è più una fonte di allocazione: è una vista
umana derivata e append-only. L'allocazione del prossimo `DEC-*` usa
esclusivamente gli id di *definizione* dell'array JSON schema-enforced, più
il floor conservativo dell'eventuale attestazione `initialized_from`.

Invarianti verificate qui (livello loader/allocatore, puro):
- lo schema `decisions-register.schema.json` è un JSON Schema valido e
  discrimina fixture valide da fixture invalide;
- allocazione deterministica dai soli id di definizione, nella forma canonica
  degli id (DEC-001..DEC-999, poi numeri pieni), mai dal Markdown;
- controlli applicativi di unicità del loader: `id` duplicato,
  `operation_id` duplicato, `target_refs` con duplicato interno al record e
  `request_payload_hash` assente/malformato sono STATO CANONICO CORROTTO
  (exit 3), non allocazioni silenziose — `uniqueItems` di JSON Schema non
  esprime l'unicità per chiave dentro un oggetto e non va usato come difesa;
- init lazy su un progetto che ha solo il decision-log Markdown (nessun
  registro JSON ancora creato): floor conservativo su
  TUTTE le occorrenze `DEC-[0-9]+` del decision-log (anche quelle di
  riferimento in prosa: un floor può solo saltare numeri, mai collidere),
  attestazione `initialized_from` completa, nessun record importato da prosa;
- decision-log illeggibile → exit 3, nessun registro creato.

I casi transazionali (init dentro la transazione, crash a metà init,
rollback senza consumo di id, canonical_drift) sono verificati dai test dei
comandi `update-assumption`/`resolve-condition`, che sono l'unico percorso
che scrive questo registro. In concreto: il registro
mutato fra `validated` e `applying` → `canonical_drift` è coperto da
`test_update_crash.check_canonical_drift_register` /
`check_canonical_drift_decisions` e da
`test_resolve_condition.check_canonical_drift_conditions` /
`check_canonical_drift_decisions`.

Discriminante di mutazione: allocando dal decision-log invece che dall'array
JSON, il caso «registro con DEC-002 e decision-log che cita DEC-900» ritorna
DEC-901 invece di DEC-003 e questo test diventa RED.
"""
import argparse
import hashlib
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit


class TestFailure(AssertionError):
    pass


def record(dec_id, operation_id, refs=None, decision_type="assumption_update"):
    return {
        "id": dec_id,
        "operation_id": operation_id,
        "request_payload_hash": "a" * 64,
        "decision_type": decision_type,
        "target_refs": ["ASS-001"] if refs is None else refs,
        "options_considered": "mantenere il valore corrente",
        "motivation": "evidenza aggiornata dal founder",
        "impact": "SOM Y1 ricalcolato",
        "approver": "founder",
        "created_at": "2026-07-20T10:00:00+00:00",
    }


def register(records, initialized_from=None):
    return {
        "schema_version": "1.0",
        "initialized_from": initialized_from,
        "decisions": records,
    }


def expect_corrupted(tm, fn, label):
    try:
        fn()
    except tm.fw.CanonicalStateError:
        return
    except Exception as exc:  # noqa: BLE001
        raise TestFailure(
            f"{label}: attesa CanonicalStateError, ottenuta "
            f"{exc.__class__.__name__}: {exc}")
    raise TestFailure(f"{label}: stato corrotto accettato senza errore")


def make_project(tmp, name, decision_log="# Decision Log\n", decisions=None):
    project = kit.make_project(tmp, name=name,
                               current_stage="01_problem-and-need",
                               status="in_progress")
    (project / "shared/decision-log.md").write_text(decision_log,
                                                    encoding="utf-8")
    if decisions is not None:
        kit.write_json(project / "shared/decisions-register.json", decisions)
    return project


def run(root):
    tm = kit.load_module(root, kit.TRANSACTION_REL, "transaction_manager")

    # ------------------------------------------------ schema
    valid = register([record("DEC-001", "op-1")])
    problems = tm.schema_errors("decisions-register", valid, "fixture")
    if problems:
        raise TestFailure(f"fixture valida rifiutata dallo schema: {problems}")

    invalid_cases = {
        "alias non canonico": register([record("DEC-0021", "op-1")]),
        "decision_type fuori enum": register(
            [record("DEC-001", "op-1", decision_type="freestyle")]),
        "target_refs duplicati": register(
            [record("DEC-001", "op-1", refs=["ASS-001", "ASS-001"])]),
        "target_refs vuoto": register([record("DEC-001", "op-1", refs=[])]),
        "hash malformato": register([{**record("DEC-001", "op-1"),
                                      "request_payload_hash": "xyz"}]),
    }
    for label, doc in invalid_cases.items():
        if not tm.schema_errors("decisions-register", doc, "fixture"):
            raise TestFailure(f"schema accetta una fixture invalida: {label}")
    missing_hash = register([record("DEC-001", "op-1")])
    del missing_hash["decisions"][0]["request_payload_hash"]
    if not tm.schema_errors("decisions-register", missing_hash, "fixture"):
        raise TestFailure("schema accetta un record senza request_payload_hash")

    # -------------------------------------------- allocazione canonica
    cases = [
        (register([]), "DEC-001", "registro vuoto"),
        (register([record("DEC-001", "op-1"), record("DEC-002", "op-2")]),
         "DEC-003", "id consecutivi"),
        (register([record("DEC-002", "op-2"), record("DEC-001", "op-1")]),
         "DEC-003", "ordine di scrittura irrilevante"),
        (register([], {"source": "shared/decision-log.md",
                       "source_sha256": "b" * 64, "derived_floor": 7}),
         "DEC-008", "floor senza record"),
        (register([record("DEC-010", "op-10")],
                  {"source": "shared/decision-log.md",
                   "source_sha256": "b" * 64, "derived_floor": 7}),
         "DEC-011", "record oltre il floor"),
        (register([record("DEC-005", "op-5")],
                  {"source": "shared/decision-log.md",
                   "source_sha256": "b" * 64, "derived_floor": 40}),
         "DEC-041", "floor oltre i record"),
        (register([record("DEC-999", "op-999")]), "DEC-1000",
         "forma canonica oltre 999"),
    ]
    for doc, expected, label in cases:
        got = tm.next_decision_id(doc)
        if got != expected:
            raise TestFailure(
                f"allocazione ({label}): atteso {expected}, ottenuto {got}")

    # -------------- l'allocazione NON guarda il Markdown (discriminante)
    with tempfile.TemporaryDirectory(prefix="bpo-dec-") as tmp:
        tmp = Path(tmp)

        p_md = make_project(
            tmp, "md-noise",
            decision_log="# Decision Log\n\n| DEC-900 | riferimento in prosa |\n",
            decisions=register([record("DEC-002", "op-2")]))
        doc, _ = tm.read_decisions_register(p_md)
        if tm.next_decision_id(doc) != "DEC-003":
            raise TestFailure(
                "l'allocazione ha guardato il decision-log Markdown invece "
                "degli id di definizione JSON")

        # ------------------------ controlli applicativi del loader
        corrupted = {
            "id duplicato": register([record("DEC-001", "op-1"),
                                      {**record("DEC-001", "op-2"),
                                       "created_at": "2026-07-21T10:00:00Z"}]),
            "operation_id duplicato": register([record("DEC-001", "op-1"),
                                                record("DEC-002", "op-1")]),
            "target_ref duplicato nel record": register(
                [record("DEC-001", "op-1", refs=["ASS-001", "ASS-001"])]),
            "request_payload_hash malformato": register(
                [{**record("DEC-001", "op-1"),
                  "request_payload_hash": "A" * 64}]),
        }
        for label, doc in corrupted.items():
            project = make_project(tmp, "corrupt-" + label.split()[0]
                                   + str(abs(hash(label)) % 1000),
                                   decisions=doc)
            expect_corrupted(tm, lambda p=project: tm.read_decisions_register(p),
                             f"loader: {label}")

        # registro sintatticamente rotto
        p_broken = make_project(tmp, "broken")
        (p_broken / "shared/decisions-register.json").write_text(
            "{not json", encoding="utf-8")
        expect_corrupted(tm, lambda: tm.read_decisions_register(p_broken),
                         "registro JSON malformato")

        # registro assente: nessun errore, nessuna invenzione
        p_absent = make_project(tmp, "absent")
        doc, raw = tm.read_decisions_register(p_absent)
        if doc is not None or raw is not None:
            raise TestFailure(
                "registro assente deve dare (None, None), non un registro "
                f"sintetico: {doc!r}")

        # ------------------------------------------- floor conservativo
        log = ("# Decision Log\n\n"
               "| ID | Data | Decisione |\n"
               "| DEC-004 | 2026-01-01 | scelta pricing |\n"
               "\nCome gia' argomentato in DEC-012, il driver resta ASS-002.\n")
        p_floor = make_project(tmp, "floor", decision_log=log)
        floor = tm.derive_decision_floor(p_floor)
        if floor != 12:
            raise TestFailure(
                "il floor deve contare TUTTE le occorrenze DEC-* del "
                f"decision-log (anche quelle di riferimento): atteso 12, "
                f"ottenuto {floor}")

        p_nolog = make_project(tmp, "nolog")
        (p_nolog / "shared/decision-log.md").unlink()
        if tm.derive_decision_floor(p_nolog) != 0:
            raise TestFailure("decision-log assente deve dare floor 0")

        p_empty = make_project(tmp, "emptylog", decision_log="# Decision Log\n")
        if tm.derive_decision_floor(p_empty) != 0:
            raise TestFailure("decision-log senza DEC-* deve dare floor 0")

        # decision-log illeggibile (byte non decodificabili) -> exit 3
        p_bad = make_project(tmp, "badlog")
        (p_bad / "shared/decision-log.md").write_bytes(b"# Log \xff\xfe\x00rot")
        expect_corrupted(tm, lambda: tm.derive_decision_floor(p_bad),
                         "decision-log illeggibile")

        # ------------------------------------- init lazy (floor conservativo)
        p_init = make_project(tmp, "init", decision_log=log)
        fresh = tm.init_decisions_register(p_init, "op-init-1")
        if tm.schema_errors("decisions-register", fresh, "init"):
            raise TestFailure("il registro inizializzato non è schema-valido")
        if fresh["decisions"]:
            raise TestFailure(
                "nessun record va importato dalla prosa del decision-log: "
                f"{fresh['decisions']}")
        attestation = fresh.get("initialized_from")
        if not isinstance(attestation, dict):
            raise TestFailure("init lazy senza attestazione initialized_from")
        for key in ("source", "source_sha256", "derived_floor",
                    "initialized_at", "operation_id"):
            if key not in attestation:
                raise TestFailure(f"initialized_from senza {key}")
        expected_sha = hashlib.sha256(
            (p_init / "shared/decision-log.md").read_bytes()).hexdigest()
        if attestation["source_sha256"] != expected_sha:
            raise TestFailure("source_sha256 non è l'hash del decision-log")
        if attestation["derived_floor"] != 12:
            raise TestFailure(
                f"derived_floor atteso 12, ottenuto {attestation['derived_floor']}")
        if attestation["operation_id"] != "op-init-1":
            raise TestFailure("initialized_from senza l'operation_id di origine")
        if tm.next_decision_id(fresh) != "DEC-013":
            raise TestFailure(
                "il primo id dopo l'init deve essere DEC-<floor+1>, "
                f"ottenuto {tm.next_decision_id(fresh)}")

        # determinismo: stessi byte -> stesso floor -> stesso id
        again = tm.init_decisions_register(p_init, "op-init-1")
        if (again["initialized_from"]["derived_floor"],
                tm.next_decision_id(again)) != (12, "DEC-013"):
            raise TestFailure("init lazy non deterministico sugli stessi byte")

        # ------------------------------------ lookup di idempotenza
        doc = register([record("DEC-001", "op-1"), record("DEC-002", "op-2")])
        found = tm.find_decision_by_operation_id(doc, "op-2")
        if not found or found["id"] != "DEC-002":
            raise TestFailure(f"lookup per operation_id fallito: {found!r}")
        if tm.find_decision_by_operation_id(doc, "op-assente") is not None:
            raise TestFailure("lookup deve dare None per operation_id ignoto")

        # il registro proposto (validation view) passa dagli stessi controlli
        problems = tm.decisions_register_problems(
            register([record("DEC-001", "op-1"), record("DEC-001", "op-2")]),
            "proposed")
        if not problems:
            raise TestFailure(
                "i controlli applicativi devono girare anche sul registro "
                "proposto nella validation view")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-DECISIONS-REGISTER decisions-register loader/allocator")


if __name__ == "__main__":
    main()
