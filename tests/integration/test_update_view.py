#!/usr/bin/env python3
"""T-UPD-VIEW — validation view project-shaped e finestra impact pre-commit.

La fase `impact` dei validator usa sempre `--project` + `--phase impact`,
mai `--candidate`. Per validare PRIMA del
commit, il transaction manager materializza sotto
`shared/.tx/<tx>-validation-view/` una copia project-shaped del progetto con
i registri proposti, e passa quella come `--project`. Nessuna modifica a
`validators/_framework.py`.

Invarianti verificate qui:
- un update che romperebbe la catena quantitativa è **rejected** e il
  canonico resta byte-identico (se l'impact girasse sul canonico invece che
  sulla view, l'update verrebbe applicato → RED);
- i report nel journal riferiscono la **view** come `--project`;
- **completezza**: la view contiene tutti i file di `shared/`
  canonica, byte-identici tranne quelli sostituiti dalla transazione, più
  ogni `NN_*/structured-output.json`; i file sostituiti sono byte-identici a
  quelli committati (byte validati = byte committati);
- **esclusione `.tx/`**: `shared/.tx/` non compare nella view a nessuna
  profondità (senza l'esclusione la view conterrebbe sé stessa);
- **finestra impact fissa `4..current_stage`**: limite inferiore
  sempre Stage 4, superiore sempre `current_stage`, mai calcolata dal
  payload o da `affected_sections`, mai oltre il release boundary. Un update
  che tocca un solo `ASS-*` di Stage 4 fa comunque girare i validator fino
  al `current_stage`;
- **canale reale**: `validate_referential_integrity` NON compare
  tra i validator invocati in pre-commit (le sue fasi sono candidate/egress
  e con `--phase impact` produrrebbe exit 2);
- cleanup della view a ogni esito terminale; view residua dopo un crash
  inerte e rimossa dal `recover`.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit
import bpo_m5_fixtures as m5


class TestFailure(AssertionError):
    pass


def fingerprint(tm, project, assumption_id):
    register = kit.read_json(project / "shared/assumptions-register.json")
    entry = next(e for e in register if e["id"] == assumption_id)
    return tm.record_fingerprint(entry)


def payload(tm, project, changes, operation_id="op-view"):
    return {
        "operation_id": operation_id,
        "reason": "CHANGE_CONFIRMED: ciclo di conflitto",
        "decision": {
            "decision_type": "assumption_update",
            "options_considered": "mantenere il SOM stimato vs allinearlo "
                                  "alla capacità GTM reale",
            "motivation": "capacità GTM sostenibile inferiore al SOM stimato",
            "impact": "SOM Y1 e driver reachable_share aggiornati",
            "approver": "founder",
        },
        "changes": [
            {"assumption_id": ref,
             "expected_record_hash": fingerprint(tm, project, ref),
             "updates": updates}
            for ref, updates in changes
        ],
    }


def run_update(root, project, doc, tmp, name, env_extra=None):
    path = Path(tmp) / name
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return kit.run_tm_cli(root, "update-assumption", "--project", project,
                          "--changes", path, env_extra=env_extra)


def view_dirs(project):
    tx_dir = Path(project) / "shared/.tx"
    if not tx_dir.is_dir():
        return []
    return sorted(p for p in tx_dir.iterdir()
                  if p.is_dir() and p.name.endswith("-validation-view"))


def journal_for(project, state=None):
    journals = [kit.read_json(p) for p in kit.find_journals(project)]
    journals = [j for j in journals if j.get("mode") == "update_assumption"]
    if state:
        journals = [j for j in journals if j.get("state") == state]
    if not journals:
        raise TestFailure(f"nessun journal update_assumption in stato {state}")
    return journals[-1]


def coherent_changes():
    """Catena mantenuta coerente: 10000 * 0.08 * 1000 = 800000."""
    return [("ASS-002", {"value": 0.08, "display_value": "0.08 ratio"}),
            (m5.SOM_ID, {"value": 800000, "display_value": "800000 EUR"})]


def check_chain_breaking_update_is_rejected(root, tm, tmp):
    project = m5.make_stage6_project(tmp, "view-break")
    before = kit.snapshot_canonical(project)
    # reachable_share 0.1 -> 0.2 SENZA aggiornare il SOM derivato: il
    # ricalcolo sulla view diverge (10000 * 0.2 * 1000 = 2000000 != 1000000)
    doc = payload(tm, project,
                  [("ASS-002", {"value": 0.2, "display_value": "0.2 ratio"})],
                  operation_id="op-break")
    exit_code, out, err = run_update(root, project, doc, tmp, "break.json")
    if exit_code != 1:
        raise TestFailure(
            "un update che rompe la catena quantitativa deve essere "
            f"rejected: exit {exit_code} (out {out.strip()!r} "
            f"err {err.strip()!r})")
    result = kit.tm_result(out, "chain break")
    codes = {e["code"] for e in result.get("errors", [])}
    if "impact_validation_failed" not in codes:
        raise TestFailure(
            f"atteso impact_validation_failed, ottenuti {sorted(codes)}")
    if kit.snapshot_canonical(project) != before:
        raise TestFailure(
            "l'update rompi-catena ha mutato il canonico: la pre-commit "
            "validation non ha protetto lo stato")
    if (project / "shared/decisions-register.json").exists():
        raise TestFailure("un rifiuto ha creato il decisions-register")

    journal = journal_for(project, "rolled_back")
    ran = {v["validator"] for v in journal.get("validation", [])}
    if not ran:
        raise TestFailure("il journal non registra i validator invocati")
    failed = [v for v in journal["validation"] if v["exit_code"] != 0]
    if not failed:
        raise TestFailure(
            "il journal deve registrare il validator che ha fallito")
    if view_dirs(project):
        raise TestFailure(
            "la validation view non è stata rimossa dopo il rifiuto")


def check_window_and_channel(root, tm, tmp):
    project = m5.make_stage6_project(tmp, "view-window")
    doc = payload(tm, project, coherent_changes(), operation_id="op-window")
    exit_code, out, err = run_update(root, project, doc, tmp, "window.json")
    if exit_code != 0:
        raise TestFailure(
            f"update coerente: exit {exit_code} (out {out.strip()!r} "
            f"err {err.strip()!r})")

    journal = journal_for(project, "committed")
    invoked = journal.get("validators_invoked")
    if not isinstance(invoked, list) or not invoked:
        raise TestFailure(
            "il journal deve registrare validators_invoked con l'elenco "
            "effettivo dei validator lanciati sulla finestra")
    stages = {entry["stage"] for entry in invoked}
    names = {entry["validator"] for entry in invoked}

    # finestra fissa 4..current_stage (qui Stage 6)
    expected_stages = {m5.S4, m5.S5, m5.S6}
    if stages != expected_stages:
        raise TestFailure(
            "la finestra impact deve essere esattamente 4..current_stage, "
            f"trovati {sorted(stages)} invece di {sorted(expected_stages)}")

    # discriminante: il payload tocca ASS-002/ASS-011, che una
    # euristica su affected_sections collocherebbe allo Stage 4; la finestra
    # deve comunque arrivare al current_stage
    if not any(e["stage"] == m5.S6 for e in invoked):
        raise TestFailure(
            "la finestra è stata ristretta dal payload invece di restare "
            "4..current_stage")

    # refint non è mai un validator di fase impact
    if "validate_referential_integrity" in names:
        raise TestFailure(
            "validate_referential_integrity non deve essere invocato nella "
            "pre-commit validation: le sue fasi sono candidate/egress")
    for entry in journal.get("validation", []):
        if entry["validator"] == "validate_referential_integrity":
            raise TestFailure("refint compare nei report del journal")
        if entry.get("exit_code") != 0:
            raise TestFailure(
                f"validator fallito su un update coerente: {entry}")
        project_arg = entry.get("project")
        if not isinstance(project_arg, str) or \
                "-validation-view" not in project_arg:
            raise TestFailure(
                "i report devono riferire la validation view come --project, "
                f"trovato {project_arg!r}")

    if not journal.get("validation_view_path", "").startswith("shared/.tx/"):
        raise TestFailure(
            f"validation_view_path inatteso: {journal.get('validation_view_path')!r}")
    if view_dirs(project):
        raise TestFailure("la view non è stata rimossa dopo il commit")


def check_view_completeness(root, tm, tmp):
    """La view è ispezionata fermando la transazione appena prima del marker
    (crash duro): il cleanup non gira e la view resta su disco."""
    project = m5.make_stage6_project(tmp, "view-complete")
    doc = payload(tm, project, coherent_changes(), operation_id="op-complete")
    exit_code, _, _ = run_update(root, project, doc, tmp, "complete.json",
                                 env_extra={"BPO_TX_TEST_CRASH":
                                            "before_commit"})
    if exit_code == 0:
        raise TestFailure("il crash prima del marker non deve dare exit 0")
    views = view_dirs(project)
    if len(views) != 1:
        raise TestFailure(f"attesa una validation view residua: {views}")
    view = views[0]
    journal = journal_for(project, "applying")
    snapshot = project / journal["snapshot_path"]

    # (vi) esclusione ricorsiva di .tx/
    for path in view.rglob("*"):
        if ".tx" in path.relative_to(view).parts:
            raise TestFailure(
                "shared/.tx/ non deve comparire nella view a nessuna "
                f"profondità: {path.relative_to(view).as_posix()}")

    # (v) completezza: stesso insieme di file di shared/ canonica
    canonical_shared = {
        p.relative_to(project / "shared").as_posix()
        for p in (project / "shared").rglob("*")
        if p.is_file() and ".tx" not in p.relative_to(project / "shared").parts
    }
    # i file NATI dalla transazione (pre_hash null) non esistevano quando la
    # view è stata costruita: la view è una copia fedele del canonico
    # PRE-transazione, più i soli file proposti
    replaced = {"assumptions-register.json", "decisions-register.json"}
    created = {e["path"].split("shared/", 1)[1]
               for e in journal["write_set"] if e["pre_hash"] is None}
    expected_shared = (canonical_shared - created) | (replaced & canonical_shared)
    view_shared = {p.relative_to(view / "shared").as_posix()
                   for p in (view / "shared").rglob("*") if p.is_file()}
    if view_shared != expected_shared:
        raise TestFailure(
            "la view deve essere una copia COMPLETA di shared/, non un "
            f"sottoinsieme enumerato: mancanti {sorted(expected_shared - view_shared)}, "
            f"inattesi {sorted(view_shared - expected_shared)}")

    untouched_by_view = {"decision-log.md", "project-status.md"}
    for rel in sorted(expected_shared):
        view_bytes = (view / "shared" / rel).read_bytes()
        if rel in replaced:
            # byte validati = byte committati
            if view_bytes != (project / "shared" / rel).read_bytes():
                raise TestFailure(
                    f"{rel}: i byte validati nella view devono essere quelli "
                    "committati nel canonico")
        elif rel in untouched_by_view:
            if view_bytes != (snapshot / "shared" / rel).read_bytes():
                raise TestFailure(
                    f"{rel}: la view deve contenere la copia canonica "
                    "pre-transazione, non una rigenerazione")
        elif view_bytes != (project / "shared" / rel).read_bytes():
            raise TestFailure(
                f"{rel}: file non toccato dalla transazione, deve essere una "
                "copia byte-identica del canonico")

    # structured-output canonici di ogni stage
    for stage in (m5.S4, m5.S5):
        if not (view / stage / "structured-output.json").is_file():
            raise TestFailure(
                f"la view deve contenere {stage}/structured-output.json: è "
                "l'input dei validator di dominio in fase impact")
        if (view / stage / "structured-output.json").read_bytes() != \
                (project / stage / "structured-output.json").read_bytes():
            raise TestFailure(f"{stage}/structured-output.json non byte-identico")

    # la view è inerte e viene rimossa dal recover del journal terminale
    exit_code, out, err = kit.run_tm_cli(root, "recover", "--project", project)
    if exit_code != 0:
        raise TestFailure(f"recover fallito: {err.strip()!r}")
    if view_dirs(project):
        raise TestFailure(
            "il recover deve rimuovere la validation view residua")


def run(root):
    tm = kit.load_module(root, kit.TRANSACTION_REL, "transaction_manager")
    with tempfile.TemporaryDirectory(prefix="bpo-view-") as tmp:
        tmp = Path(tmp)
        check_chain_breaking_update_is_rejected(root, tm, tmp)
        check_window_and_channel(root, tm, tmp)
        check_view_completeness(root, tm, tmp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-UPD-VIEW validation view project-shaped + finestra impact")


if __name__ == "__main__":
    main()
