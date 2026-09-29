#!/usr/bin/env python3
"""Schema contracts of the shared registers (assumptions, conditions,
proposed assumptions, project-status).

Discriminating checks:
- conditions-register.schema.json exists and accepts/rejects the right shapes;
- assumptions-register.schema.json still accepts the minimal legacy entry
  (no extended fields) and accepts the extended derived form
  (kind/derivation/currency/period/scenario/evidence_classification),
  rejecting malformed derivations, non-canonical ids and non-numeric ratios;
- proposed-assumptions.schema.json is a separate candidate contract for P-ASS-*;
- project-status.schema.json admits only the real gate states;
- the example-startup fixture ships valid conditions and assumptions registers.

Semantic validation uses `jsonschema` when installed; otherwise the test
degrades to explicit shape assertions on the schema documents themselves.
"""
import argparse
import json
import sys
from pathlib import Path

SCHEMAS_REL = ".claude/skills/business-plan-orchestrator/schemas"
FIXTURE_REL = "examples/fictional-startup/shared"


class TestFailure(AssertionError):
    pass


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def get_validator():
    try:
        from jsonschema import Draft202012Validator
        return Draft202012Validator
    except Exception:  # noqa: BLE001
        return None


def assert_valid(validator_cls, schema, instance, label):
    if validator_cls is None:
        return
    errors = list(validator_cls(schema).iter_errors(instance))
    if errors:
        raise TestFailure(f"{label}: expected valid, got: {errors[0].message}")


def assert_invalid(validator_cls, schema, instance, label):
    if validator_cls is None:
        return
    errors = list(validator_cls(schema).iter_errors(instance))
    if not errors:
        raise TestFailure(f"{label}: expected schema rejection, got valid")


BASE_COND = {
    "id": "COND-001",
    "stage": "03_value-proposition",
    "description": "Validare il pricing con almeno 3 interviste",
    "severity": "high",
    "owner": "founder",
    "validation_action": "Interviste strutturate a buyer del beachhead",
    "due_before_stage": "04_market-and-competition",
    "resolution_status": "open",
}

LEGACY_ASSUMPTION = {
    "id": "ASS-001",
    "category": "pricing",
    "variable": "price_per_user_month",
    "statement": "Prezzo mensile per utente",
    "value": 4.99,
    "display_value": "4,99 EUR/mese/utente",
    "unit": "EUR/mese/utente",
    "source": "Founder interview",
    "owner": "founder",
    "confidence": "low",
    "validation_status": "unvalidated",
    "affected_sections": ["00_idea-discovery"],
    "last_updated": "2026-07-14",
    "previous_values": [],
}

DERIVED_ASSUMPTION = {
    "id": "ASS-041",
    "category": "market",
    "variable": "som_y3_revenue",
    "statement": "Ricavo SOM anno 3, scenario base",
    "kind": "derived",
    "unit": "EUR",
    "currency": "EUR",
    "period": "Y3",
    "scenario": "base",
    "derivation": {
        "formula": "eligible_customers * reachable_share * arpa_year",
        "variables": {
            "eligible_customers": "ASS-020",
            "reachable_share": "ASS-021",
            "arpa_year": "ASS-013",
        },
        "method": "bottom_up",
    },
    "value": 1250000,
    "display_value": "1,25 M€ (Y3, base)",
    "evidence_refs": ["EVD-012"],
    "evidence_classification": "model_estimate",
    "validation_status": "unvalidated",
    "affected_sections": ["04_market-and-competition"],
}

SELECTED_REF_ASSUMPTION = {
    "id": "ASS-052",
    "category": "market",
    "variable": "tam_canonical",
    "statement": "TAM canonico riconciliato",
    "kind": "derived",
    "unit": "EUR",
    "currency": "EUR",
    "period": "Y1",
    "scenario": "base",
    "derivation": {
        "method": "reconciliation",
        "strategy": "selected_ref",
        "selected_ref": "ASS-051",
        "variables": {"tam_topdown": "ASS-050", "tam_bottomup": "ASS-051"},
    },
    "value": 900000,
    "evidence_classification": "external_source",
    "rationale": "Stima bottom-up preferita: fonti primarie recenti",
    "decision_ref": "DEC-014",
    "validation_status": "unvalidated",
}

PROPOSED_ASSUMPTION = {
    "id": "P-ASS-001",
    "category": "market",
    "variable": "som_y1_revenue",
    "statement": "Ricavo SOM Y1",
    "kind": "derived",
    "unit": "EUR",
    "currency": "EUR",
    "period": "Y1",
    "scenario": "base",
    "derivation": {
        "formula": "customers * arpa",
        "variables": {"customers": "P-ASS-002", "arpa": "ASS-002"},
        "method": "bottom_up",
    },
    "value": 120000,
    "evidence_classification": "model_estimate",
    "validation_status": "unvalidated",
}


def run(root):
    schemas = root / SCHEMAS_REL
    v = get_validator()

    # --- conditions-register.schema.json -----------------------------------
    cond_schema_path = schemas / "conditions-register.schema.json"
    if not cond_schema_path.exists():
        raise TestFailure("missing schema: conditions-register.schema.json")
    cond_schema = read_json(cond_schema_path)

    assert_valid(v, cond_schema, [], "empty conditions register")
    assert_valid(v, cond_schema, [BASE_COND], "well-formed COND entry")
    resolved = dict(BASE_COND, resolution_status="resolved",
                    resolved_by="DEC-003", evidence_ref="EVD-004")
    assert_valid(v, cond_schema, [resolved], "resolved COND entry")
    assert_invalid(v, cond_schema, [dict(BASE_COND, severity="critical")],
                   "COND severity outside enum")
    assert_invalid(v, cond_schema, [dict(BASE_COND, owner="anyone")],
                   "COND owner outside enum")
    assert_invalid(v, cond_schema, [dict(BASE_COND, resolution_status="done")],
                   "COND resolution_status outside enum")
    missing_due = {k: val for k, val in BASE_COND.items()
                   if k != "due_before_stage"}
    assert_invalid(v, cond_schema, [missing_due], "COND without due_before_stage")
    assert_invalid(v, cond_schema, [dict(BASE_COND, id="COND-1")],
                   "COND id must be COND-NNN")

    # --- assumptions-register.schema.json (extension) ----------------------
    ass_schema = read_json(schemas / "assumptions-register.schema.json")
    assert_valid(v, ass_schema, [LEGACY_ASSUMPTION],
                 "minimal legacy assumption (retro-compat)")
    assert_valid(v, ass_schema, [DERIVED_ASSUMPTION], "derived assumption")
    assert_valid(v, ass_schema, [SELECTED_REF_ASSUMPTION],
                 "selected_ref reconciliation assumption")
    assert_invalid(v, ass_schema, [dict(DERIVED_ASSUMPTION, kind="computed")],
                   "kind outside enum")
    no_vars = json.loads(json.dumps(DERIVED_ASSUMPTION))
    del no_vars["derivation"]["variables"]
    assert_invalid(v, ass_schema, [no_vars], "derivation without variables")
    no_formula = json.loads(json.dumps(DERIVED_ASSUMPTION))
    del no_formula["derivation"]["formula"]
    assert_invalid(v, ass_schema, [no_formula],
                   "non-selected_ref derivation without formula")
    bad_class = dict(DERIVED_ASSUMPTION, evidence_classification="guess")
    assert_invalid(v, ass_schema, [bad_class],
                   "evidence_classification outside the 6 classes")
    pass_id = dict(LEGACY_ASSUMPTION, id="P-ASS-001")
    assert_invalid(v, ass_schema, [pass_id],
                   "P-ASS-* must never validate as canonical id")

    # --- obblighi condizionali per kind=derived ----------------------------
    for missing in ("derivation", "unit", "currency", "period", "scenario",
                    "evidence_classification"):
        broken = json.loads(json.dumps(DERIVED_ASSUMPTION))
        del broken[missing]
        assert_invalid(v, ass_schema, [broken],
                       f"derived without required field: {missing}")

    # --- contratto selected_ref completo -----------------------------------
    no_rationale = json.loads(json.dumps(SELECTED_REF_ASSUMPTION))
    del no_rationale["rationale"]
    assert_invalid(v, ass_schema, [no_rationale],
                   "selected_ref without rationale")
    no_decision = json.loads(json.dumps(SELECTED_REF_ASSUMPTION))
    del no_decision["decision_ref"]
    assert_invalid(v, ass_schema, [no_decision],
                   "selected_ref without decision_ref")
    null_decision = json.loads(json.dumps(SELECTED_REF_ASSUMPTION))
    null_decision["decision_ref"] = None
    assert_invalid(v, ass_schema, [null_decision],
                   "selected_ref with null decision_ref")

    # --- le variables canoniche non ammettono P-ASS-* ----------------------
    pass_var = json.loads(json.dumps(DERIVED_ASSUMPTION))
    pass_var["derivation"]["variables"]["arpa_year"] = "P-ASS-001"
    assert_invalid(v, ass_schema, [pass_var],
                   "canonical variables must not admit P-ASS-*")
    pass_sel = json.loads(json.dumps(SELECTED_REF_ASSUMPTION))
    pass_sel["derivation"]["selected_ref"] = "P-ASS-001"
    assert_invalid(v, ass_schema, [pass_sel],
                   "canonical selected_ref must not admit P-ASS-*")

    # --- forma canonica degli id (niente alias con zeri) -------------------
    assert_invalid(v, ass_schema, [dict(LEGACY_ASSUMPTION, id="ASS-0001")],
                   "ASS-0001 alias must be rejected")
    big_id = dict(LEGACY_ASSUMPTION, id="ASS-1000")
    assert_valid(v, ass_schema, [big_id], "ASS-1000 is canonical")
    alias_var = json.loads(json.dumps(DERIVED_ASSUMPTION))
    alias_var["derivation"]["variables"]["arpa_year"] = "ASS-0013"
    assert_invalid(v, ass_schema, [alias_var],
                   "variables must use canonical ids (no ASS-0013)")

    # --- ratio canonico in [0,1] nello schema ------------------------------
    ratio_ok = dict(LEGACY_ASSUMPTION, unit="ratio", value=0.25)
    assert_valid(v, ass_schema, [ratio_ok], "ratio 0.25 valid")
    assert_invalid(v, ass_schema,
                   [dict(LEGACY_ASSUMPTION, unit="ratio", value=1.5)],
                   "ratio above 1 must be rejected by the schema")
    assert_invalid(v, ass_schema,
                   [dict(LEGACY_ASSUMPTION, unit="ratio", value=-0.1)],
                   "negative ratio must be rejected by the schema")
    # Un ratio deve essere ESCLUSIVAMENTE numerico in [0,1]. String,
    # booleani e null non passano (un ratio "150%" non deve superare lo schema).
    assert_invalid(v, ass_schema,
                   [dict(LEGACY_ASSUMPTION, unit="ratio", value="150%")],
                   "ratio as a string must be rejected by the schema")
    assert_invalid(v, ass_schema,
                   [dict(LEGACY_ASSUMPTION, unit="ratio", value="0.5")],
                   "ratio as a numeric string must be rejected by the schema")
    assert_invalid(v, ass_schema,
                   [dict(LEGACY_ASSUMPTION, unit="ratio", value=True)],
                   "ratio as a boolean must be rejected by the schema")
    assert_invalid(v, ass_schema,
                   [dict(LEGACY_ASSUMPTION, unit="ratio", value=None)],
                   "ratio as null must be rejected by the schema")

    # --- contratto candidate separato per P-ASS-* --------------------------
    proposed_schema_path = schemas / "proposed-assumptions.schema.json"
    if not proposed_schema_path.exists():
        raise TestFailure("missing schema: proposed-assumptions.schema.json")
    proposed_schema = read_json(proposed_schema_path)
    assert_valid(v, proposed_schema, [PROPOSED_ASSUMPTION],
                 "well-formed proposed assumption")
    assert_invalid(v, proposed_schema, [{"id": "P-ASS-001"}],
                   "only-id proposed assumption")
    assert_invalid(v, proposed_schema,
                   [dict(PROPOSED_ASSUMPTION, id="ASS-001")],
                   "proposed assumption with canonical id")
    assert_invalid(v, proposed_schema,
                   [dict(PROPOSED_ASSUMPTION, id="P-ASS-0001")],
                   "P-ASS-0001 alias must be rejected")
    incomplete = json.loads(json.dumps(PROPOSED_ASSUMPTION))
    del incomplete["currency"]
    assert_invalid(v, proposed_schema, [incomplete],
                   "proposed derived without currency")
    # Anche il contratto candidate impone ratio numerico in [0,1].
    ratio_proposed = dict(PROPOSED_ASSUMPTION, unit="ratio", value=0.25)
    del ratio_proposed["derivation"]
    ratio_proposed = dict(ratio_proposed, kind="primary")
    assert_valid(v, proposed_schema, [ratio_proposed],
                 "proposed ratio 0.25 valid")
    assert_invalid(v, proposed_schema,
                   [dict(ratio_proposed, value="150%")],
                   "proposed ratio as string must be rejected")
    assert_invalid(v, proposed_schema,
                   [dict(ratio_proposed, value=True)],
                   "proposed ratio as boolean must be rejected")
    assert_invalid(v, proposed_schema,
                   [dict(ratio_proposed, value=None)],
                   "proposed ratio as null must be rejected")
    assert_invalid(v, proposed_schema,
                   [dict(ratio_proposed, value=1.5)],
                   "proposed ratio above 1 must be rejected")

    # --- project-status allineato agli stati reali -------------------------
    status_schema = read_json(schemas / "project-status.schema.json")
    base_status = {
        "project_name": "x",
        "current_stage": "01_problem-and-need",
        "status": "in_progress",
        "completed_stages": ["00_idea-discovery"],
        "last_updated": "2026-07-16",
        "next_action": "test",
    }
    assert_valid(v, status_schema, base_status, "in_progress status")
    assert_valid(v, status_schema,
                 dict(base_status, status="conflict_awaiting_confirmation"),
                 "conflict_awaiting_confirmation must be a valid status")
    assert_invalid(v, status_schema, dict(base_status, status="in_review"),
                   "in_review is not a real gate state")
    assert_invalid(v, status_schema, dict(base_status, status="weird"),
                   "unknown status must be rejected")

    if v is None:
        # Shape-only fallback: the schema documents must at least declare the
        # extended fields.
        props = ass_schema["items"]["properties"]
        for key in ("kind", "derivation", "currency", "period", "scenario",
                    "evidence_classification"):
            if key not in props:
                raise TestFailure(f"assumptions schema missing property: {key}")
        for key in ("id", "stage", "severity", "owner", "validation_action",
                    "due_before_stage", "resolution_status"):
            if key not in cond_schema["items"]["properties"]:
                raise TestFailure(f"conditions schema missing property: {key}")

    # --- fixture ------------------------------------------------------------
    fixture = root / FIXTURE_REL / "conditions-register.json"
    if not fixture.exists():
        raise TestFailure("example-startup missing shared/conditions-register.json")
    cond_fixture = read_json(fixture)
    if not isinstance(cond_fixture, list):
        raise TestFailure("conditions-register fixture must be a JSON array")
    assert_valid(v, cond_schema, cond_fixture, "conditions-register fixture")
    ass_fixture = read_json(root / FIXTURE_REL / "assumptions-register.json")
    assert_valid(v, ass_schema, ass_fixture,
                 "assumptions-register fixture against extended schema")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: shared register schema contracts")


if __name__ == "__main__":
    main()
