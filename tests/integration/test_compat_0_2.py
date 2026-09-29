#!/usr/bin/env python3
"""T-COMPAT-0.2 — un progetto fermo allo Stage 6 resta valido sotto i
validator degli stage successivi.

Costruisce un progetto con **soli artefatti degli Stage 4-6** (canonici,
completato fino allo Stage 6, nessun structured-output Stage 7-9, nessun
decisions-register) e prova che la validazione degli Stage 7-9 non lo
rompe:

- il progetto carica e i suoi stage già completati restano validi: matrice
  impact 4-6 verde (market/unit-economics/funnel/cross-stage);
- i validator di dominio degli Stage 7-9 non ancora dovuti usano il terzo
  stato `not_yet_required` (PASS con warning, mai FAIL) — nessun artefatto
  Stage 7-9 è preteso prima del suo stage;
- i percorsi transazionali/di ripresa restano verdi (governance-status,
  recover idempotente su progetto pulito);
- nessun file dell'esempio diventa un requisito globale: un progetto utente
  ordinario fermo a Stage 6 supera ogni validator degli Stage 7-9 senza
  possedere i file Stage 7-9.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit
import bpo_m5_fixtures as m5


class TestFailure(AssertionError):
    pass


S4, S5, S6, S7, S8, S9 = m5.S4, m5.S5, m5.S6, m5.S7, m5.S8, m5.S9


def make_legacy_project(tmp, name):
    """Progetto fermo allo Stage 6: Stage 4-6 canonici e completati, allo
    Stage 7 `not_started`, senza alcun artefatto degli Stage 7-9."""
    assumptions = (m5.market_assumptions() + m5.business_assumptions()
                   + m5.gtm_assumptions())
    project = kit.make_project(
        tmp, name=name, current_stage=S7, status="not_started",
        completed=m5.COMPLETED_THROUGH_6, assumptions=assumptions)
    kit.write_json(project / S4 / "structured-output.json",
                   m5.market_structured())
    kit.write_json(project / S5 / "structured-output.json",
                   m5.business_structured())
    kit.write_json(project / S6 / "structured-output.json",
                   m5.gtm_structured())
    return project


def impact_green(root, project):
    """La matrice impact 4-6 resta verde: gli stage storici sono validi."""
    for name, stage in (("validate_market_arithmetic", S4),
                        ("validate_unit_economics", S5),
                        ("validate_funnel_arithmetic", S6),
                        ("validate_cross_stage_consistency", S6)):
        exit_code, out, err = kit.run_validator_cli(
            root, name, project=project, stage=stage, phase="impact")
        if exit_code != 0:
            raise TestFailure(f"impact {name} @ {stage}: exit {exit_code} "
                              f"(out {out.strip()!r} err {err.strip()!r})")


def three_state_not_required(root, project):
    """I validator di dominio degli Stage 7-9 al proprio stage, su un
    progetto che non lo ha ancora raggiunto, danno `not_yet_required`
    (PASS, mai FAIL)."""
    cases = [("validate_operations_feasibility", S7),
             ("validate_team_and_governance", S8),
             ("validate_milestone_chain", S9)]
    for name, stage in cases:
        exit_code, out, err = kit.run_validator_cli(
            root, name, project=project, stage=stage, phase="impact")
        if exit_code != 0:
            raise TestFailure(f"validator {name} @ {stage} su progetto "
                              "fermo a Stage 6 deve dare exit 0 "
                              f"(three-state), got {exit_code} "
                              f"(out {out.strip()!r})")
        report = kit.parse_report(out, f"three-state {name}")
        if report["result"] == "FAIL":
            raise TestFailure(f"validator {name} non deve mai FAIL su "
                              "progetto fermo a Stage 6")
        codes = [w["code"] for w in report["warnings"]]
        if "not_yet_required" not in codes:
            raise TestFailure(f"validator {name} @ {stage} deve emettere "
                              f"not_yet_required, warnings {codes}")

    # cross-stage (matrice 5-9) su Stage 7-9 non ancora prodotti: nessun FAIL.
    for stage in (S7, S8, S9):
        exit_code, out, err = kit.run_validator_cli(
            root, "validate_cross_stage_consistency", project=project,
            stage=stage, phase="impact")
        if exit_code != 0:
            raise TestFailure(f"cross-stage @ {stage} su progetto fermo a "
                              f"Stage 6 deve dare exit 0, got {exit_code} "
                              f"(out {out.strip()!r})")


def legacy_tx_paths(root, project):
    """I percorsi transazionali restano verdi: governance-status e recover
    idempotente su progetto pulito."""
    exit_code, out, err = kit.run_tm_cli(
        root, "governance-status", "--project", project,
        "--updates", '{"status": "in_progress", "current_task": "compat"}',
        "--reason", "compat: ingresso Stage 7 dopo lo Stage 6 approvato")
    if exit_code != 0:
        raise TestFailure(f"governance-status: exit {exit_code} "
                          f"(err {err.strip()!r})")
    before = kit.snapshot_canonical(project)
    exit_code, out, err = kit.run_tm_cli(root, "recover", "--project", project)
    if exit_code != 0:
        raise TestFailure(f"recover no-op: exit {exit_code} "
                          f"(err {err.strip()!r})")
    if kit.snapshot_canonical(project) != before:
        raise TestFailure("recover su progetto pulito deve essere no-op")


def run(root):
    with tempfile.TemporaryDirectory(prefix="bpo-compat02-") as tmp:
        tmp = Path(tmp)
        project = make_legacy_project(tmp, "stage6-project")
        impact_green(root, project)
        three_state_not_required(root, project)
        legacy_tx_paths(root, project)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-COMPAT-0.2 progetto fermo a Stage 6 valido sotto i "
          "validator Stage 7-9 (impact 4-6 verde, three-state, tx/resume "
          "verdi)")


if __name__ == "__main__":
    main()
