#!/usr/bin/env python3
"""T-REFINT-EXT — namespace tipizzati OPS-/ROLE-/MIL- in
validate_referential_integrity (Stage 7-9).

Modello definizione/riferimento field-aware:
- la raccolta delle definizioni è distinta dalla risoluzione dei riferimenti
  e avviene sui soli siti di definizione dichiarati;
- una definizione non è mai trattata come un riferimento da risolvere;
- il candidate dello stage validato sostituisce IN BLOCCO le definizioni
  canoniche dello stesso stage (mai merge);
- unicità numerica per namespace, alias non canonici respinti;
- forward reference consentita dentro lo stesso array di definizione;
- riferimenti a namespace di stage futuri vietati;
- OPS-* è raccolto come coppia (id, entity_type) e covers_processes[]
  risolve solo verso entity_type core_process.

Error code distinti: duplicate_definition, unresolved_ref,
future_namespace_ref, covers_non_process, untyped_definition.

Tipizzazione OPS-*: una definizione OPS-* priva di entity_type, con valore fuori enum o
incompatibile con il proprio sito di definizione fallisce già in fase
candidate con untyped_definition, ancorato all'id della DEFINIZIONE e non al
riferimento downstream; un riferimento verso una definizione untyped non è
risolvibile.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit

STAGE_OPS = "07_operations-and-ip"
STAGE_TEAM = "08_team-and-governance"
STAGE_MIL = "09_roadmap-and-milestones"


class TestFailure(AssertionError):
    pass


# --------------------------------------------------------------- fixtures

def core_process(num, entity_type="core_process"):
    entry = {"id": f"OPS-{num:03d}", "name": f"Processo {num}",
             "make_buy_partner": "make", "owner_hint": "ops",
             "bottleneck": False}
    if entity_type is not None:
        entry["entity_type"] = entity_type
    return entry


def dependency(num):
    return {"id": f"OPS-{num:03d}", "entity_type": "dependency",
            "name": f"Dipendenza {num}", "category": "supplier",
            "mitigation": "Secondo fornitore"}


def ip_asset(num):
    return {"id": f"OPS-{num:03d}", "entity_type": "ip_asset",
            "name": f"Asset {num}", "protection": "trade_secret",
            "rationale": "know-how"}


def ops_doc(processes=None, dependencies=None, assets=None):
    return {"operations_model": {
        "core_processes": processes if processes is not None
        else [core_process(1), core_process(2)],
        "critical_dependencies": dependencies if dependencies is not None
        else [dependency(10)],
        "ip_strategy": {"assets": assets if assets is not None
                        else [ip_asset(20)]},
    }}


def role(num, covers=None):
    return {"id": f"ROLE-{num:03d}", "person": f"Persona {num}",
            "responsibilities": ["r"], "covers_processes": covers or []}


def team_doc(roles=None, decision_rights=None, hiring_plan=None):
    doc = {"team_governance": {
        "roles": roles if roles is not None else [role(1, ["OPS-001"])]}}
    if decision_rights is not None:
        doc["team_governance"]["decision_rights"] = decision_rights
    if hiring_plan is not None:
        doc["team_governance"]["hiring_plan"] = hiring_plan
    return doc


def milestone(num, depends_on=None, owner="ROLE-001"):
    return {"id": f"MIL-{num:03d}", "title": f"Milestone {num}",
            "category": "technical", "owner_ref": owner,
            "depends_on": depends_on or [], "start_date": "2026-09-01",
            "target_date": "2026-12-01"}


def milestone_doc(milestones=None):
    return {"milestone_plan": {
        "milestones": milestones if milestones is not None
        else [milestone(1)]}}


def build(tmp, name, stage, phase_docs, candidate_doc=None,
          current_stage=None):
    """Progetto con structured-output canonici per gli stage 7-9 e un
    candidate opzionale per lo stage validato."""
    project = kit.make_project(
        tmp, name=name, current_stage=current_stage or stage,
        status="in_progress",
        evidence=[{"id": "EVD-001", "statement": "Intervista pilota"}])
    for stage_name in (STAGE_OPS, STAGE_TEAM, STAGE_MIL):
        (project / stage_name).mkdir(exist_ok=True)
    for stage_name, doc in phase_docs.items():
        kit.write_json(project / stage_name / "structured-output.json", doc)
    candidate = kit.make_candidate(project, stage, structured=candidate_doc)
    return project, candidate


# --------------------------------------------------------------- assertions

def refint(root, project, candidate, stage, phase="egress"):
    return kit.run_validator_cli(
        root, "validate_referential_integrity", project=project, stage=stage,
        phase=phase, candidate=candidate)


def expect_pass(root, project, candidate, stage, label, phase="egress"):
    before = kit.snapshot_tree(project)
    exit_code, out, err = refint(root, project, candidate, stage, phase)
    if exit_code != 0:
        raise TestFailure(f"{label}: expected exit 0, got {exit_code} "
                          f"(out: {out.strip()!r} err: {err.strip()!r})")
    report = kit.parse_report(out, label)
    if kit.snapshot_tree(project) != before:
        raise TestFailure(f"{label}: validator mutated the project")
    return report


def expect_fail(root, project, candidate, stage, code, label, phase="egress",
                ref=None, absent=()):
    before = kit.snapshot_tree(project)
    exit_code, out, err = refint(root, project, candidate, stage, phase)
    if exit_code != 1:
        raise TestFailure(f"{label}: expected exit 1, got {exit_code} "
                          f"(out: {out.strip()!r} err: {err.strip()!r})")
    report = kit.parse_report(out, label)
    codes = [e["code"] for e in report["errors"]]
    if code not in codes:
        raise TestFailure(f"{label}: expected error code {code}, got {codes}")
    for forbidden in absent:
        if forbidden in codes:
            raise TestFailure(
                f"{label}: {forbidden} must stay distinct from {code}, "
                f"got {codes}")
    if ref is not None:
        anchored = [e["ref"] for e in report["errors"] if e["code"] == code]
        if ref not in anchored:
            raise TestFailure(
                f"{label}: {code} must be anchored to {ref}, got {anchored}")
    if kit.snapshot_tree(project) != before:
        raise TestFailure(f"{label}: validator mutated the project")
    return report


def run(root):
    if not (root / kit.VALIDATORS_REL /
            "validate_referential_integrity.py").exists():
        raise TestFailure("missing validator: validate_referential_integrity.py")

    with tempfile.TemporaryDirectory(prefix="bpo-refint-ext-") as tmp:
        tmp = Path(tmp)

        # --- definizioni valide, non auto-risolte come riferimenti ----------
        p, c = build(tmp, "ops-ok", STAGE_OPS, {}, candidate_doc=ops_doc())
        report = expect_pass(root, p, c, STAGE_OPS,
                             "valid OPS definitions", phase="candidate")
        if report["errors"]:
            raise TestFailure("valid definitions must not produce errors")

        p, c = build(tmp, "role-ok", STAGE_TEAM, {STAGE_OPS: ops_doc()},
                     candidate_doc=team_doc(
                         roles=[role(1, ["OPS-001", "OPS-002"])],
                         decision_rights=[{"area": "Pricing",
                                           "owner_ref": "ROLE-001"}],
                         hiring_plan=[{"role_ref": "ROLE-001",
                                       "period": "Y1", }]))
        expect_pass(root, p, c, STAGE_TEAM, "covers_processes to core_process")

        p, c = build(tmp, "mil-ok", STAGE_MIL,
                     {STAGE_OPS: ops_doc(), STAGE_TEAM: team_doc()},
                     candidate_doc=milestone_doc([milestone(1)]))
        expect_pass(root, p, c, STAGE_MIL, "milestone owner resolves")

        # --- forward reference dentro lo stesso array di definizione --------
        p, c = build(tmp, "mil-forward", STAGE_MIL,
                     {STAGE_OPS: ops_doc(), STAGE_TEAM: team_doc()},
                     candidate_doc=milestone_doc(
                         [milestone(1, depends_on=["MIL-002"]),
                          milestone(2)]))
        expect_pass(root, p, c, STAGE_MIL, "forward reference intra-array")

        # --- riferimenti non risolti ---------------------------------------
        p, c = build(tmp, "ops-missing", STAGE_TEAM, {STAGE_OPS: ops_doc()},
                     candidate_doc=team_doc(roles=[role(1, ["OPS-999"])]))
        expect_fail(root, p, c, STAGE_TEAM, "unresolved_ref",
                    "covers_processes to unknown OPS",
                    absent=("covers_non_process",))

        p, c = build(tmp, "role-missing", STAGE_MIL,
                     {STAGE_OPS: ops_doc(), STAGE_TEAM: team_doc()},
                     candidate_doc=milestone_doc(
                         [milestone(1, owner="ROLE-999")]))
        expect_fail(root, p, c, STAGE_MIL, "unresolved_ref",
                    "milestone owner unknown")

        p, c = build(tmp, "mil-missing", STAGE_MIL,
                     {STAGE_OPS: ops_doc(), STAGE_TEAM: team_doc()},
                     candidate_doc=milestone_doc(
                         [milestone(1, depends_on=["MIL-999"])]))
        expect_fail(root, p, c, STAGE_MIL, "unresolved_ref",
                    "depends_on unknown MIL")

        # --- tipizzazione OPS- ----------------------------------------------
        p, c = build(tmp, "covers-dep", STAGE_TEAM, {STAGE_OPS: ops_doc()},
                     candidate_doc=team_doc(roles=[role(1, ["OPS-010"])]))
        expect_fail(root, p, c, STAGE_TEAM, "covers_non_process",
                    "covers_processes to a dependency", ref="OPS-010",
                    absent=("unresolved_ref",))

        p, c = build(tmp, "covers-ip", STAGE_TEAM, {STAGE_OPS: ops_doc()},
                     candidate_doc=team_doc(roles=[role(1, ["OPS-020"])]))
        expect_fail(root, p, c, STAGE_TEAM, "covers_non_process",
                    "covers_processes to an ip_asset", ref="OPS-020",
                    absent=("unresolved_ref",))

        # --- C-R3-3: definizione OPS- untyped o mistyped --------------------
        # entity_type assente, in fase candidate dello stage che definisce
        p, c = build(tmp, "untyped-missing", STAGE_OPS, {},
                     candidate_doc=ops_doc(
                         processes=[core_process(1, entity_type=None)]))
        expect_fail(root, p, c, STAGE_OPS, "untyped_definition",
                    "core_process without entity_type (candidate)",
                    phase="candidate", ref="OPS-001")

        # entity_type fuori enum
        p, c = build(tmp, "untyped-enum", STAGE_OPS, {},
                     candidate_doc=ops_doc(
                         processes=[core_process(1, entity_type="process")]))
        expect_fail(root, p, c, STAGE_OPS, "untyped_definition",
                    "entity_type out of enum", phase="candidate",
                    ref="OPS-001")

        # entity_type incompatibile con il sito di definizione
        p, c = build(tmp, "untyped-site", STAGE_OPS, {},
                     candidate_doc=ops_doc(
                         processes=[core_process(1, entity_type="dependency")]))
        expect_fail(root, p, c, STAGE_OPS, "untyped_definition",
                    "entity_type incompatible with its definition site",
                    phase="candidate", ref="OPS-001")

        # il riferimento verso una definizione untyped non è valido, e
        # l'errore resta ancorato alla DEFINIZIONE, non al ruolo downstream
        p, c = build(tmp, "untyped-ref", STAGE_TEAM,
                     {STAGE_OPS: ops_doc(
                         processes=[core_process(1, entity_type=None)])},
                     candidate_doc=team_doc(roles=[role(1, ["OPS-001"])]))
        expect_fail(root, p, c, STAGE_TEAM, "untyped_definition",
                    "reference to an untyped OPS definition", ref="OPS-001")

        # --- unicità e forma canonica --------------------------------------
        p, c = build(tmp, "dup", STAGE_OPS, {},
                     candidate_doc=ops_doc(
                         processes=[core_process(1), core_process(1)]))
        expect_fail(root, p, c, STAGE_OPS, "duplicate_definition",
                    "duplicate OPS definition", phase="candidate")

        # duplicato tra due siti di definizione diversi dello stesso namespace
        p, c = build(tmp, "dup-cross", STAGE_OPS, {},
                     candidate_doc=ops_doc(processes=[core_process(1)],
                                           dependencies=[dependency(1)]))
        expect_fail(root, p, c, STAGE_OPS, "duplicate_definition",
                    "same OPS number in two definition sites",
                    phase="candidate")

        p, c = build(tmp, "alias-def", STAGE_OPS, {},
                     candidate_doc=ops_doc(
                         processes=[dict(core_process(1), id="OPS-0001")]))
        expect_fail(root, p, c, STAGE_OPS, "non_canonical_id",
                    "non canonical OPS definition id", phase="candidate")

        p, c = build(tmp, "alias-ref", STAGE_TEAM, {STAGE_OPS: ops_doc()},
                     candidate_doc=team_doc(roles=[role(1, ["OPS-0001"])]))
        expect_fail(root, p, c, STAGE_TEAM, "non_canonical_id",
                    "non canonical OPS reference")

        # --- namespace di stage futuro --------------------------------------
        future = team_doc(roles=[role(1, ["OPS-001"])])
        future["milestone_plan"] = {
            "milestones": [{"id": "MIL-001", "depends_on": ["MIL-002"]}]}
        p, c = build(tmp, "future-ns", STAGE_TEAM, {STAGE_OPS: ops_doc()},
                     candidate_doc=future)
        expect_fail(root, p, c, STAGE_TEAM, "future_namespace_ref",
                    "MIL reference inside a Stage 8 output")

        # --- il candidate sostituisce in blocco il canonico dello stage -----
        # canonico difettoso (duplicato) + candidate pulito -> PASS
        p, c = build(tmp, "replace-clean", STAGE_OPS,
                     {STAGE_OPS: ops_doc(
                         processes=[core_process(1), core_process(1)])},
                     candidate_doc=ops_doc())
        expect_pass(root, p, c, STAGE_OPS,
                    "candidate replaces the canonical definitions en bloc",
                    phase="candidate")
        # canonico pulito + candidate difettoso -> FAIL (nessun merge)
        p, c = build(tmp, "replace-dirty", STAGE_OPS,
                     {STAGE_OPS: ops_doc()},
                     candidate_doc=ops_doc(
                         processes=[core_process(1), core_process(1)]))
        expect_fail(root, p, c, STAGE_OPS, "duplicate_definition",
                    "canonical definitions never rescue a broken candidate",
                    phase="candidate")

        # --- regressioni degli Stage 1-6 preservate ------------------------
        # P-ASS-* mai nel canonico
        p, c = build(tmp, "pass-canonical", STAGE_TEAM,
                     {STAGE_OPS: dict(ops_doc(), leftover={"ref": "P-ASS-001"})},
                     candidate_doc=team_doc(roles=[role(1, ["OPS-001"])]))
        expect_fail(root, p, c, STAGE_TEAM, "pass_in_canonical",
                    "P-ASS leaked into a Stage 7 canonical output")

        # un progetto senza structured output 7-9 resta valido (three-state)
        p, c = build(tmp, "compat", STAGE_OPS, {}, candidate_doc=None)
        expect_pass(root, p, c, STAGE_OPS,
                    "project without stage 7-9 outputs stays valid",
                    phase="candidate")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-REFINT-EXT typed namespaces OPS-/ROLE-/MIL- (entity_type)")


if __name__ == "__main__":
    main()
