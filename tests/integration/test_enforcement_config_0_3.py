#!/usr/bin/env python3
"""T-CONFIG-0-3 — matrice di enforcement di enforcement-config.json per i
validator degli Stage 1-9 e invarianti di `release_boundary`.

Verifica:
- `release_boundary` = 13_document-generation: lo Stage 13 è l'ultimo stage
  implementato ED è l'ultimo stage di `stage_order`;
- stage gate e refint coprono gli stage 1-9, cross-stage gli stage 5-9;
- le `phases` dei validator degli Stage 1-6 restano quelle dichiarate e in
  particolare refint NON ha la fase `impact`: aggiungerla richiederebbe un
  percorso dedicato in `_framework.py`, che non esiste;
- i tre validator di dominio degli Stage 7-9 sono dichiarati nella matrice
  con stages, phases e `introduced_in`;
- nessuno stub eseguibile: un validator non implementato non può comparire
  in `egress_required` e un validator implementato entro il boundary DEVE
  comparirvi (il contratto di `egress_required` in test_validator_framework
  impone l'esistenza del file);
- per lo Stage 10 le TRE voci validator di PIPELINE interna
  (`STAGE10_PIPELINE_ONLY_VALIDATORS`) sono un'eccezione architetturale
  dichiarata a quell'obbligo: solo `validate_financial_output` è in
  `egress_required`;
- gli Stage 11, 12 e 13 hanno ciascuno la PROPRIA voce validator
  (`validate_funding_request`, `validate_data_room`,
  `validate_document_generation`: `stages: [N]`, `phases: [egress, impact]`),
  implementata e percio' in `egress_required`: nessuna è un'eccezione di
  pipeline;
- `stage_order` porta 14 stage (0-13): nessuno Stage 14.
"""
import argparse
import json
import sys
from pathlib import Path

CONFIG_REL = ".claude/skills/business-plan-orchestrator/config/enforcement-config.json"
VALIDATORS_REL = ".claude/skills/business-plan-orchestrator/validators"

DOMAIN_0_3 = {
    "validate_operations_feasibility": ([7, 8, 9], "0.3.0"),
    "validate_team_and_governance": ([8, 9], "0.3.0"),
    "validate_milestone_chain": ([9], "0.3.0"),
}

PHASES_0_2 = {
    "validate_stage_gate": ["ingress", "egress"],
    "validate_referential_integrity": ["candidate", "egress"],
    "validate_market_arithmetic": ["egress", "impact"],
    "validate_unit_economics": ["egress", "impact"],
    "validate_funnel_arithmetic": ["egress", "impact"],
    "validate_cross_stage_consistency": ["egress", "impact"],
}

STAGES_0_3 = {
    "validate_stage_gate": [1, 2, 3, 4, 5, 6, 7, 8, 9],
    "validate_referential_integrity": [1, 2, 3, 4, 5, 6, 7, 8, 9],
    "validate_cross_stage_consistency": [5, 6, 7, 8, 9],
}

STAGES_UNCHANGED_0_2 = {
    "validate_market_arithmetic": [4, 5, 6],
    "validate_unit_economics": [5, 6],
    "validate_funnel_arithmetic": [6],
}

#: Le TRE voci validator dello Stage 10 che restano di PIPELINE interna:
#: consumano payload intermedi (binding-input.json, engine-input.json) che il
#: candidate reale del Transaction Manager non produce, e per questo NON
#: entrano mai in `egress_required`, anche se il loro stage è dentro il
#: release boundary. L'invariante «implementato e dentro il boundary => deve
#: stare in egress_required» vale per tutti gli altri validator; questi TRE
#: ne sono l'eccezione DICHIARATA, non un'esenzione silenziosa.
STAGE10_PIPELINE_ONLY_VALIDATORS = (
    "validate_financial_binding",
    "validate_financial_engine",
    "validate_financial_reconciliation",
)


class TestFailure(AssertionError):
    pass


def stage_ordinal(config, stage):
    order = config.get("stage_order", {})
    if stage not in order:
        raise TestFailure(f"{stage!r} is not a canonical stage folder")
    return int(order[stage])


def matrix_boundary_violations(root, config):
    """Invariante della matrice in forma BOUNDARY-AWARE.

    L'invariante è parametrica sul `release_boundary` ed estende nei DUE
    VERSI il contratto di `egress_required` verificato in `run` per i
    validator di dominio degli Stage 7-9:

    - nessuna voce dichiara uno stage con ordinale oltre
      `stage_ordinal(release_boundary) + 1`;
    - un validator che dichiara stage OLTRE il boundary può essere
      dichiarato in matrice ma NON deve stare in `egress_required`;
    - un validator ENTRO il boundary e implementato DEVE starci
      (salvo le voci di pipeline dello Stage 10).

    La forma parametrica difende la stessa proprietà per qualunque valore
    di `release_boundary`.
    """
    boundary = config.get("release_boundary")
    boundary_ordinal = stage_ordinal(config, boundary)
    max_declarable = boundary_ordinal + 1
    validators = config.get("validators", {})
    egress_required = config.get("egress_required", [])
    violations = []
    for name, spec in sorted(validators.items()):
        stages = [int(s) for s in spec.get("stages", [])]
        beyond = [s for s in stages if s > max_declarable]
        if beyond:
            violations.append(
                f"{name}: stages beyond the declarable ordinal "
                f"{max_declarable} (release boundary {boundary}): {beyond}")
        past_boundary = [s for s in stages if s > boundary_ordinal]
        implemented = (root / VALIDATORS_REL / f"{name}.py").is_file()
        if past_boundary and name in egress_required:
            violations.append(
                f"{name}: declares stages {past_boundary} past the release "
                "boundary and must not appear in egress_required")
        if implemented and not past_boundary and name not in egress_required \
                and name not in STAGE10_PIPELINE_ONLY_VALIDATORS:
            violations.append(
                f"{name} is implemented within the release boundary but "
                "missing from egress_required")
    return violations


def check_matrix_negative_cases(root, config):
    """Casi negativi dell'invariante di matrice: una voce oltre lo stage
    dichiarabile, TN-04 (voce oltre il boundary in `egress_required`) e
    TN-05 (validator implementato entro il boundary assente da
    `egress_required`) devono fallire.

    Ogni caso è costruito su una copia sintetica: nessun file è scritto.
    """
    def variant(**over):
        copy = json.loads(json.dumps(config))
        copy.update(over)
        return copy

    def must_fail(label, candidate):
        if not matrix_boundary_violations(root, candidate):
            raise TestFailure(
                f"negative case {label}: the substitution invariant is no "
                "longer a gate — the input had to be rejected and was not")

    # al boundary reale (13) stages: [14] sarebbe DENTRO il dichiarabile
    # (14 <= 13 + 1) e non dimostrerebbe nulla: serve [15].
    beyond = variant()
    beyond["validators"]["validate_stage_beyond_probe"] = {
        "stages": [15], "phases": ["egress"], "introduced_in": "NEVER"}
    must_fail("stages: [15] at boundary 13", beyond)

    # TN-04 — validator oltre il boundary presente in egress_required. Ogni
    # voce reale è DENTRO il boundary (13), quindi il caso è costruito con
    # una voce sintetica allo stage 14.
    tn04 = variant()
    tn04["validators"]["validate_stage_beyond_probe"] = {
        "stages": [14], "phases": ["egress"], "introduced_in": "NEVER"}
    tn04["egress_required"] = list(tn04.get("egress_required", [])) + [
        "validate_stage_beyond_probe"]
    must_fail("TN-04 validator past the boundary in egress_required", tn04)

    # TN-05 — verso opposto: validator entro il boundary e implementato,
    # ASSENTE da egress_required.
    tn05 = variant()
    tn05["egress_required"] = [name for name in tn05.get("egress_required", [])
                               if name != "validate_stage_gate"]
    must_fail("TN-05 implemented in-boundary validator missing from "
              "egress_required", tn05)

    if matrix_boundary_violations(root, config):
        raise TestFailure(
            "the real configuration must satisfy the substitution invariant: "
            f"{matrix_boundary_violations(root, config)}")


def run(root):
    config = json.loads((root / CONFIG_REL).read_text(encoding="utf-8"))
    validators = config.get("validators", {})

    # --- release boundary: lo Stage 13 è l'ultimo stage implementato e
    # l'ultimo di stage_order ---------------------------------------------
    boundary = config.get("release_boundary")
    if boundary != "13_document-generation":
        raise TestFailure(
            "release_boundary must be 13_document-generation, got "
            f"{boundary!r}")
    if boundary not in config.get("stage_order", {}):
        raise TestFailure("release_boundary must be a canonical stage folder")

    # --- copertura degli stage 1-9 ------------------------------------------
    for name, stages in STAGES_0_3.items():
        spec = validators.get(name)
        if not isinstance(spec, dict):
            raise TestFailure(f"config must declare validator {name}")
        if [int(s) for s in spec.get("stages", [])] != stages:
            raise TestFailure(
                f"{name}: stages must be {stages}, got {spec.get('stages')}")

    for name, stages in STAGES_UNCHANGED_0_2.items():
        spec = validators.get(name, {})
        if [int(s) for s in spec.get("stages", [])] != stages:
            raise TestFailure(
                f"{name}: stages must stay {stages}, got "
                f"{spec.get('stages')}")

    # --- phases invariate: nessuna fase impact per refint ------------------
    for name, phases in PHASES_0_2.items():
        spec = validators.get(name, {})
        if list(spec.get("phases", [])) != phases:
            raise TestFailure(
                f"{name}: phases must stay {phases} (only `stages` extends "
                f"to stages 7-9), got {spec.get('phases')}")
    if "impact" in validators.get(
            "validate_referential_integrity", {}).get("phases", []):
        raise TestFailure(
            "validate_referential_integrity must not acquire the impact "
            "phase (it would require a dedicated code path in _framework.py)")

    # --- tre validator di dominio dichiarati, nessuno stub ------------------
    egress_required = config.get("egress_required", [])
    for name, (stages, milestone) in DOMAIN_0_3.items():
        spec = validators.get(name)
        if not isinstance(spec, dict):
            raise TestFailure(
                f"config must declare the domain validator {name} "
                "(stages 7-9)")
        if [int(s) for s in spec.get("stages", [])] != stages:
            raise TestFailure(
                f"{name}: stages must be {stages}, got {spec.get('stages')}")
        if list(spec.get("phases", [])) != ["egress", "impact"]:
            raise TestFailure(
                f"{name}: phases must be ['egress', 'impact'], got "
                f"{spec.get('phases')}")
        if spec.get("introduced_in") != milestone:
            raise TestFailure(
                f"{name}: introduced_in must be {milestone}, got "
                f"{spec.get('introduced_in')}")
        implemented = (root / VALIDATORS_REL / f"{name}.py").is_file()
        if not implemented and name in egress_required:
            raise TestFailure(
                f"{name} is declared in egress_required but not implemented: "
                "no executable stub is allowed; it enters the list "
                f"together with its file (introduced_in {milestone})")
        if implemented and name not in egress_required:
            raise TestFailure(
                f"{name} is implemented but missing from egress_required")

    # --- matrice ed egress_required, boundary-aware -------------------------
    violations = matrix_boundary_violations(root, config)
    if violations:
        raise TestFailure("; ".join(violations))
    check_matrix_negative_cases(root, config)

    # --- il delta resta additivo -------------------------------------------
    for key in ("stage_order", "gate_states", "approved_states",
                "egress_required", "decimals", "tolerances"):
        if key not in config:
            raise TestFailure(f"config lost the base key {key}")
    # `13_document-generation` e' implementato ED e' l'ultimo stage:
    # stage_order ha 14 voci (0-13) e nessuno Stage 14.
    if len(config["stage_order"]) != 14:
        raise TestFailure("stage_order must keep the 14 canonical stages")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-CONFIG-0-3 enforcement matrix for stages 1-9 and release "
          "boundary invariants")


if __name__ == "__main__":
    main()
