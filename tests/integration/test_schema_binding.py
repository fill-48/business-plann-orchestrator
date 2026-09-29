#!/usr/bin/env python3
"""T-TX-SCHEMA-BINDING — gli schemi sono vincolati al percorso
di commit canonico del transaction manager.

- un candidate con proposed assumption "solo id" o derived incompleta viene
  rifiutato PRIMA del marker applying (exit 1, nessuna mutazione canonica);
- una proposed condition incompleta viene rifiutata;
- uno stato canonico preesistente schema-invalid blocca l'apply (exit 3);
- una dipendenza P-ASS-* rimasta nel registro canonico blocca l'apply;
- il risultato post-transform viene rivalidato: un transform difettoso
  (fault injection) non può committare documenti schema-invalid;
- un candidate con derivation cicliche viene rifiutato senza consumare id;
- se `jsonschema` non è disponibile il runtime fallisce fail-closed (exit 2)
  senza degradare a validazione shape-only.
"""
import argparse
import contextlib
import io
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit


class TestFailure(AssertionError):
    pass


STAGE = "01_problem-and-need"


def make_tx_project(tmp, name, assumptions=None, conditions=None):
    return kit.make_project(
        tmp, name=name, current_stage=STAGE, status="in_progress",
        assumptions=assumptions if assumptions is not None
        else [kit.base_assumption(1), kit.base_assumption(2)],
        conditions=conditions)


def valid_proposed():
    return [{
        "id": "P-ASS-001",
        "category": "market",
        "variable": "customers_y1",
        "statement": "Clienti anno 1",
        "kind": "primary",
        "unit": "count",
        "value": 100,
        "validation_status": "unvalidated",
    }]


def make_candidate(project, proposed, tx_hint="tx-a", conditions=None):
    candidate = kit.make_candidate(
        project, STAGE, tx_id=tx_hint,
        structured={"problem_statement": {"id": "SEG-001",
                                          "problem_ref": "ASS-001"}},
        proposed=proposed,
        handoff="# Handoff\n")
    if conditions is not None:
        kit.write_json(candidate / "proposed-conditions.json", conditions)
    return candidate


def apply_tm(root, project, candidate, env_extra=None):
    return kit.run_tm_cli(root, "apply", "--project", project, "--stage",
                          STAGE, "--candidate", candidate,
                          env_extra=env_extra)


def read_ids(project):
    return {e["id"] for e in
            kit.read_json(project / "shared/assumptions-register.json")}


def expect_rejected(root, tmp, name, proposed, label, conditions=None):
    project = make_tx_project(tmp, name)
    before = kit.snapshot_canonical(project)
    candidate = make_candidate(project, proposed, conditions=conditions)
    exit_code, out, err = apply_tm(root, project, candidate)
    if exit_code != 1:
        raise TestFailure(f"{label}: expected exit 1, got {exit_code} "
                          f"(out {out.strip()!r} err {err.strip()!r})")
    if kit.snapshot_canonical(project) != before:
        raise TestFailure(f"{label}: canonical state mutated")
    if read_ids(project) != {"ASS-001", "ASS-002"}:
        raise TestFailure(f"{label}: ASS ids consumed on rejection")
    return kit.tm_result(out, label)


def run(root):
    with tempfile.TemporaryDirectory(prefix="bpo-schemabind-") as tmp:
        tmp = Path(tmp)

        # ---- proposed assumption con soltanto l'id --------------------------
        expect_rejected(root, tmp, "sb1", [{"id": "P-ASS-001"}],
                        "schema binding: only-id proposed assumption")

        # ---- derived priva dei campi obbligatori ----------------------------
        derived_incomplete = [{
            "id": "P-ASS-001",
            "category": "market",
            "statement": "SOM Y1",
            "kind": "derived",
            "unit": "EUR",
            "value": 1000,
            "validation_status": "unvalidated",
            "derivation": {
                "formula": "a",
                "variables": {"a": "ASS-001"},
                "method": "bottom_up",
            },
            # mancano currency / period / scenario / evidence_classification
        }]
        expect_rejected(root, tmp, "sb2", derived_incomplete,
                        "schema binding: incomplete derived proposed assumption")

        # ---- proposed condition incompleta ---------------------------------
        expect_rejected(
            root, tmp, "sb3", valid_proposed(),
            "schema binding: incomplete proposed condition",
            conditions=[{
                "id": "COND-001",
                "stage": STAGE,
                "description": "Validare il driver",
                # mancano severity/owner/validation_action/due/resolution
            }])

        # ---- stato canonico preesistente schema-invalid -> exit 3 ----------
        broken = [kit.base_assumption(1)]
        del broken[0]["statement"]
        project = make_tx_project(tmp, "sb4", assumptions=broken)
        before = kit.snapshot_canonical(project)
        candidate = make_candidate(project, valid_proposed())
        exit_code, out, err = apply_tm(root, project, candidate)
        if exit_code != 3:
            raise TestFailure(
                f"schema binding: invalid canonical register: expected exit 3, got "
                f"{exit_code} (out {out.strip()!r} err {err.strip()!r})")
        if kit.snapshot_canonical(project) != before:
            raise TestFailure(
                "schema binding: invalid canonical register: state mutated")

        # ---- P-ASS-* residuo nel registro canonico -> exit 3 ----------------
        tainted = [kit.base_assumption(1), kit.base_assumption(2, **{
            "kind": "derived",
            "currency": "EUR",
            "period": "Y1",
            "scenario": "base",
            "evidence_classification": "model_estimate",
            "derivation": {
                "formula": "x",
                "variables": {"x": "P-ASS-009"},
                "method": "bottom_up",
            },
        })]
        project = make_tx_project(tmp, "sb5", assumptions=tainted)
        before = kit.snapshot_canonical(project)
        candidate = make_candidate(project, valid_proposed())
        exit_code, out, err = apply_tm(root, project, candidate)
        if exit_code != 3:
            raise TestFailure(
                f"schema binding: P-ASS in canonical register: expected exit 3, got "
                f"{exit_code}")
        if kit.snapshot_canonical(project) != before:
            raise TestFailure("schema binding: P-ASS in canonical register: mutated")

        # ---- post-transform schema-invalid (fault injection) ---------------
        tm = kit.load_module(root, kit.TRANSACTION_REL, "transaction_manager")
        project = make_tx_project(tmp, "sb6")
        before = kit.snapshot_canonical(project)
        candidate = make_candidate(project, valid_proposed(), tx_hint="tx-ft")
        orig = tm.substitute_json

        def corrupting_substitute(node, pass_map):
            out = orig(node, pass_map)
            if isinstance(out, dict) and \
                    str(out.get("id", "")).startswith("ASS-") and \
                    "statement" in out:
                out = dict(out)
                del out["statement"]
            return out

        import contextlib
        import io
        tm.substitute_json = corrupting_substitute
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = tm.cmd_apply(argparse.Namespace(
                    project=str(project), stage=STAGE,
                    candidate=str(candidate), report=None))
        finally:
            tm.substitute_json = orig
        if rc == 0:
            raise TestFailure(
                "schema binding: post-transform: a corrupting transform was committed")
        if kit.snapshot_canonical(project) != before:
            raise TestFailure("schema binding: post-transform: canonical state mutated")
        journals = [kit.read_json(j) for j in kit.find_journals(project)]
        if any(j["state"] == "committed" for j in journals):
            raise TestFailure("schema binding: post-transform: journal committed")

        # ---- derivation cicliche nel candidate: rejected, nessun id --------
        cyc = [
            {"id": "P-ASS-001", "category": "market", "statement": "a",
             "kind": "derived", "unit": "EUR", "currency": "EUR",
             "period": "Y1", "scenario": "base",
             "evidence_classification": "model_estimate", "value": 1,
             "validation_status": "unvalidated",
             "derivation": {"formula": "b", "variables": {"b": "P-ASS-002"},
                            "method": "bottom_up"}},
            {"id": "P-ASS-002", "category": "market", "statement": "b",
             "kind": "derived", "unit": "EUR", "currency": "EUR",
             "period": "Y1", "scenario": "base",
             "evidence_classification": "model_estimate", "value": 1,
             "validation_status": "unvalidated",
             "derivation": {"formula": "a", "variables": {"a": "P-ASS-001"},
                            "method": "bottom_up"}},
        ]
        expect_rejected(root, tmp, "sb7", cyc,
                        "schema binding: cyclic candidate via transaction manager")

        # ---- ciclo di derivation nato SOLO dopo l'allocazione ------------
        # Il canonico contiene ASS-001 (derived) con un riferimento in avanti a
        # ASS-003, che non esiste ancora: l'overlay del candidate non vede il
        # ciclo. Il candidate propone P-ASS-001, allocato come ASS-003, che
        # punta indietro ad ASS-001. Dopo l'allocazione il registro contiene il
        # ciclo ASS-001 -> ASS-003 -> ASS-001: deve essere rifiutato prima del
        # commit e senza consumare l'id.
        forward = [
            kit.base_assumption(1, **{
                "kind": "derived", "unit": "EUR", "currency": "EUR",
                "period": "Y1", "scenario": "base",
                "evidence_classification": "model_estimate",
                "derivation": {"formula": "x", "variables": {"x": "ASS-003"},
                               "method": "bottom_up"}}),
            kit.base_assumption(2),
        ]
        project = make_tx_project(tmp, "sb9", assumptions=forward)
        before = kit.snapshot_canonical(project)
        back_proposed = [{
            "id": "P-ASS-001", "category": "market", "statement": "back-edge",
            "kind": "derived", "unit": "EUR", "currency": "EUR",
            "period": "Y1", "scenario": "base",
            "evidence_classification": "model_estimate", "value": 10,
            "validation_status": "unvalidated",
            "derivation": {"formula": "y", "variables": {"y": "ASS-001"},
                           "method": "bottom_up"}}]
        candidate = make_candidate(project, back_proposed, tx_hint="tx-cycle")
        exit_code, out, err = apply_tm(root, project, candidate)
        if exit_code == 0:
            raise TestFailure(
                "post-allocation cycle: post-allocation derivation cycle was committed "
                f"(out {out.strip()!r})")
        if kit.snapshot_canonical(project) != before:
            raise TestFailure(
                "post-allocation cycle: rejected post-allocation cycle mutated state")
        if read_ids(project) != {"ASS-001", "ASS-002"}:
            raise TestFailure(
                "post-allocation cycle: ASS id consumed on a post-allocation cycle")
        journals = [kit.read_json(j) for j in kit.find_journals(project)]
        if any(j["state"] == "committed" for j in journals):
            raise TestFailure("post-allocation cycle: journal committed despite the cycle")

        # ---- test discriminante per la validazione schema post-write -------
        # La corruzione avviene DOPO il controllo post-transform (che valida
        # l'oggetto new_register) e PRIMA della validazione dei byte scritti:
        # si inietta un'entry schema-invalid nei SOLI byte del registro. Il
        # write-set hash è calcolato sui byte corrotti (quindi combacia), la
        # verifica semantica del registro passa (id unico, nessun P-ASS,
        # nessun ciclo, allocazioni presenti), l'unica difesa che resta è la
        # rivalidazione a schema dei byte riletti in verify_write_set.
        # Rimuovendo SOLTANTO quella rivalidazione, questo test diventa RED.
        tm = kit.load_module(root, kit.TRANSACTION_REL, "transaction_manager")
        project = make_tx_project(tmp, "sb10")
        before = kit.snapshot_canonical(project)
        candidate = make_candidate(project, valid_proposed(), tx_hint="tx-pw")
        orig_dump = tm.dump_json_bytes

        def corrupt_register_bytes(data):
            if isinstance(data, list) and any(
                    isinstance(e, dict)
                    and str(e.get("id", "")).startswith("ASS-")
                    for e in data):
                # entry schema-invalid (mancano category/statement/
                # validation_status) ma con id unico, nessun P-ASS, nessuna
                # derivation: supera hash e verifiche semantiche, non lo schema
                data = list(data) + [{"id": "ASS-000"}]
            return orig_dump(data)

        tm.dump_json_bytes = corrupt_register_bytes
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    rc = tm.cmd_apply(argparse.Namespace(
                        project=str(project), stage=STAGE,
                        candidate=str(candidate), report=None))
                except tm.TransactionError as exc:
                    rc = exc.exit_code
        finally:
            tm.dump_json_bytes = orig_dump
        if rc == 0:
            raise TestFailure(
                "post-write schema: schema-invalid post-write bytes were committed "
                "(post-write schema validation is not discriminating)")
        if kit.snapshot_canonical(project) != before:
            raise TestFailure(
                "post-write schema: rejected post-write corruption mutated the state")
        journals = [kit.read_json(j) for j in kit.find_journals(project)]
        if any(j["state"] == "committed" for j in journals):
            raise TestFailure(
                "post-write schema: journal committed despite schema-invalid bytes")

        # ---- fail-closed senza jsonschema (exit 2, nessuna mutazione) ------
        shadow = tmp / "no-jsonschema"
        shadow.mkdir()
        (shadow / "jsonschema.py").write_text(
            "raise ImportError('jsonschema disabled by test')\n",
            encoding="utf-8")
        project = make_tx_project(tmp, "sb8")
        before = kit.snapshot_canonical(project)
        candidate = make_candidate(project, valid_proposed())
        exit_code, out, err = apply_tm(
            root, project, candidate,
            env_extra={"PYTHONPATH": str(shadow)})
        if exit_code != 2:
            raise TestFailure(
                "schema binding fail-closed: without jsonschema apply must exit 2 "
                f"(configuration), got {exit_code} (out {out.strip()!r} "
                f"err {err.strip()!r})")
        if kit.snapshot_canonical(project) != before:
            raise TestFailure("schema binding fail-closed: canonical state mutated")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-TX-SCHEMA-BINDING canonical schema enforcement at commit")


if __name__ == "__main__":
    main()
