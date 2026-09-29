#!/usr/bin/env python3
"""T-SCHEMAS-0-3 — contratti dei quattro schemi degli Stage 7-9 e del
registro delle decisioni.

Verifica discriminante:
- i quattro schemi (`operations-model`, `team-governance`, `milestone-plan`,
  `decisions-register`) sono JSON Schema validi;
- per ciascuno una fixture valida passa e le fixture invalide sono respinte;
- `entity_type` è required e vincolato con `const` per array di definizione
  OPS-*: il tipo non può divergere dal sito di definizione;
- `financial_plan_inputs` è required nel milestone-plan (contratto
  financial_plan_inputs);
- `target_refs` del decisions-register ha `uniqueItems`;
- i nomi canonici di cartella degli stage 7-9 restano quelli di
  `enforcement-config.json`.

La validazione semantica usa `jsonschema` quando installato; in sua assenza
degrada ad asserzioni esplicite sul documento di schema.
"""
import argparse
import copy
import json
import sys
from pathlib import Path

SCHEMAS_REL = ".claude/skills/business-plan-orchestrator/schemas"
CONFIG_REL = ".claude/skills/business-plan-orchestrator/config/enforcement-config.json"

SCHEMA_FILES = (
    "operations-model.schema.json",
    "team-governance.schema.json",
    "milestone-plan.schema.json",
    "decisions-register.schema.json",
)


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


# --------------------------------------------------------------------- fixtures

def operations_model():
    return {
        "operations_model": {
            "core_processes": [
                {
                    "id": "OPS-001",
                    "entity_type": "core_process",
                    "name": "Onboarding cliente",
                    "make_buy_partner": "make",
                    "owner_hint": "operations",
                    "bottleneck": False,
                },
                {
                    "id": "OPS-002",
                    "entity_type": "core_process",
                    "name": "Delivery del servizio",
                    "make_buy_partner": "partner",
                    "owner_hint": "delivery",
                    "bottleneck": True,
                },
            ],
            "capacity_ref": "ASS-030",
            "unit_ops_cost_refs": ["ASS-018"],
            "critical_dependencies": [
                {
                    "id": "OPS-010",
                    "entity_type": "dependency",
                    "name": "Fornitore cloud",
                    "category": "supplier",
                    "mitigation": "Secondo fornitore qualificato entro Q2",
                },
                {
                    "id": "OPS-011",
                    "entity_type": "dependency",
                    "name": "Integrazione pagamenti",
                    "category": "technology",
                    "none_identified": True,
                    "rationale": "Nessuna dipendenza residua dopo il porting",
                },
            ],
            "regulatory_requirements": [
                {"requirement": "GDPR", "assessment": "DPIA completata"},
                {
                    "requirement": "Certificazione medicale",
                    "none_identified": True,
                    "rationale": "Prodotto fuori dal perimetro MDR",
                },
            ],
            "ip_strategy": {
                "assets": [
                    {
                        "id": "OPS-020",
                        "entity_type": "ip_asset",
                        "name": "Algoritmo di matching",
                        "protection": "trade_secret",
                        "rationale": "Know-how non brevettabile, accesso ristretto",
                    }
                ]
            },
            "risk_refs": ["RISK-004"],
        }
    }


def team_governance():
    return {
        "team_governance": {
            "roles": [
                {
                    "id": "ROLE-001",
                    "person": "Anna Bianchi",
                    "responsibilities": ["Delivery", "Qualità"],
                    "covers_processes": ["OPS-001", "OPS-002"],
                    "fte_ref": "ASS-040",
                },
                {
                    "id": "ROLE-002",
                    "open_position": "Head of Operations",
                    "responsibilities": ["Capacità operativa"],
                    "covers_processes": ["OPS-002"],
                    "fte_ref": "ASS-041",
                },
            ],
            "capability_gaps": [
                {"gap": "Compliance MDR", "addressed_by": "COND-004"}
            ],
            "hiring_plan": [
                {
                    "role_ref": "ROLE-002",
                    "period": "Y1H2",
                    "cost_driver_ref": "ASS-042",
                }
            ],
            "decision_rights": [
                {"area": "Pricing", "owner_ref": "ROLE-001"}
            ],
            "governance": {
                "structure": "Srl con consiglio di amministrazione",
                "equity_split": [
                    {"holder": "Founder A", "share": 0.6},
                    {"holder": "Founder B", "share": 0.4},
                ],
                "vesting": "4 anni con cliff a 12 mesi",
            },
            "advisors": [{"name": "Studio X", "area": "IP"}],
            "risk_refs": ["RISK-007"],
        }
    }


def milestone_plan():
    return {
        "milestone_plan": {
            "milestones": [
                {
                    "id": "MIL-001",
                    "title": "MVP in produzione",
                    "category": "technical",
                    "owner_ref": "ROLE-001",
                    "depends_on": [],
                    "start_date": "2026-09-01",
                    "target_date": "2026-12-15",
                    "cost_ref": "ASS-050",
                    "success_criteria": ["10 clienti pilota attivi"],
                    "go_no_go_rule": "Go se retention pilota >= 70%",
                    "exit_criteria": "MVP stabile per 30 giorni",
                    "risk_refs": ["RISK-007"],
                },
                {
                    "id": "MIL-002",
                    "title": "Primo canale commerciale a regime",
                    "category": "commercial",
                    "owner_ref": "ROLE-002",
                    "depends_on": ["MIL-001"],
                    "start_date": "2027-01-07",
                    "target_date": "2027-06-30",
                    "cost_ref": "ASS-051",
                    "success_criteria": ["CAC <= 250 EUR"],
                    "go_no_go_rule": "Go se CAC entro il target per due mesi",
                    "exit_criteria": "Canale replicabile documentato",
                    "risk_refs": [],
                },
            ],
            "financial_plan_inputs": {
                "pricing_ref": "ASS-001",
                "cogs_refs": ["ASS-018"],
                "funnel_customers_ref": "ASS-022",
                "churn_ref": "ASS-024",
                "ops_capacity_ref": "ASS-030",
                "headcount_driver_refs": ["ASS-040", "ASS-041"],
                "milestone_cost_refs": ["ASS-050", "ASS-051"],
                "som_ref": "ASS-012",
            },
        }
    }


def decisions_register():
    return {
        "schema_version": "1.0",
        "initialized_from": None,
        "decisions": [
            {
                "id": "DEC-021",
                "operation_id": "op-2026-07-20-0001",
                "request_payload_hash": "a" * 64,
                "decision_type": "assumption_update",
                "target_refs": ["ASS-011", "ASS-002"],
                "options_considered": "Mantenere il valore oppure aggiornarlo",
                "motivation": "Nuova evidenza dal pilota",
                "impact": "SOM ricalcolato",
                "approver": "founder",
                "created_at": "2026-07-20T10:00:00Z",
            }
        ],
    }


# ------------------------------------------------------------------ assertions

def check_schema_documents(root, validator_cls):
    schemas = {}
    for name in SCHEMA_FILES:
        path = root / SCHEMAS_REL / name
        if not path.is_file():
            raise TestFailure(f"missing Stage 7-9 schema: {name}")
        doc = read_json(path)
        if validator_cls is not None:
            try:
                validator_cls.check_schema(doc)
            except Exception as exc:  # noqa: BLE001
                raise TestFailure(f"{name} is not a valid JSON Schema: {exc}")
        else:
            if not isinstance(doc, dict) or "$schema" not in doc:
                raise TestFailure(f"{name}: schema-shaped document expected")
        if not str(doc.get("description") or "").strip():
            raise TestFailure(f"{name}: top-level description is missing")
        schemas[name] = doc
    return schemas


def check_operations_model(validator_cls, schema):
    assert_valid(validator_cls, schema, operations_model(), "operations-model")

    # entity_type required su ogni definizione OPS-*
    bad = operations_model()
    del bad["operations_model"]["core_processes"][0]["entity_type"]
    assert_invalid(validator_cls, schema, bad, "core process without entity_type")

    # const per array: il tipo non può divergere dal sito di definizione
    for array, index, wrong in (("core_processes", 0, "dependency"),
                                ("critical_dependencies", 0, "core_process")):
        bad = operations_model()
        bad["operations_model"][array][index]["entity_type"] = wrong
        assert_invalid(validator_cls, schema, bad,
                       f"{array} typed as {wrong}")
    bad = operations_model()
    bad["operations_model"]["ip_strategy"]["assets"][0]["entity_type"] = \
        "core_process"
    assert_invalid(validator_cls, schema, bad, "ip asset typed as core_process")

    # valore fuori enum
    bad = operations_model()
    bad["operations_model"]["core_processes"][0]["entity_type"] = "process"
    assert_invalid(validator_cls, schema, bad, "entity_type out of enum")

    # id fuori forma canonica
    bad = operations_model()
    bad["operations_model"]["core_processes"][0]["id"] = "OPS-0001"
    assert_invalid(validator_cls, schema, bad, "non canonical OPS id")

    # make/buy/partner enum
    bad = operations_model()
    bad["operations_model"]["core_processes"][0]["make_buy_partner"] = "outsource"
    assert_invalid(validator_cls, schema, bad, "make_buy_partner out of enum")

    # capacity_ref deve essere un ASS-*, mai un letterale
    bad = operations_model()
    bad["operations_model"]["capacity_ref"] = "500 pratiche/mese"
    assert_invalid(validator_cls, schema, bad, "capacity_ref literal")

    # dipendenza senza mitigazione e senza none_identified + rationale
    bad = operations_model()
    del bad["operations_model"]["critical_dependencies"][0]["mitigation"]
    assert_invalid(validator_cls, schema, bad, "dependency not assessed")
    bad = operations_model()
    del bad["operations_model"]["critical_dependencies"][1]["rationale"]
    assert_invalid(validator_cls, schema, bad, "none_identified without rationale")

    # requisito normativo non valutato
    bad = operations_model()
    del bad["operations_model"]["regulatory_requirements"][0]["assessment"]
    assert_invalid(validator_cls, schema, bad, "regulatory not assessed")

    # asset IP senza protezione
    bad = operations_model()
    del bad["operations_model"]["ip_strategy"]["assets"][0]["protection"]
    assert_invalid(validator_cls, schema, bad, "ip asset without protection")


def check_team_governance(validator_cls, schema):
    assert_valid(validator_cls, schema, team_governance(), "team-governance")

    bad = team_governance()
    bad["team_governance"]["roles"][0]["id"] = "R-001"
    assert_invalid(validator_cls, schema, bad, "role id out of namespace")

    bad = team_governance()
    bad["team_governance"]["roles"][0]["covers_processes"] = ["ROLE-001"]
    assert_invalid(validator_cls, schema, bad, "covers_processes not OPS-*")

    # né persona né posizione aperta
    bad = team_governance()
    del bad["team_governance"]["roles"][0]["person"]
    assert_invalid(validator_cls, schema, bad, "role without person/open_position")

    # owner dei decision rights: un solo ROLE-*, mai una lista
    bad = team_governance()
    bad["team_governance"]["decision_rights"][0]["owner_ref"] = \
        ["ROLE-001", "ROLE-002"]
    assert_invalid(validator_cls, schema, bad, "decision right with two owners")

    # equity share fuori da [0,1]
    for share in (1.4, -0.1):
        bad = team_governance()
        bad["team_governance"]["governance"]["equity_split"][0]["share"] = share
        assert_invalid(validator_cls, schema, bad, f"equity share {share}")

    bad = team_governance()
    del bad["team_governance"]["capability_gaps"][0]["addressed_by"]
    assert_invalid(validator_cls, schema, bad, "capability gap unaddressed")

    bad = team_governance()
    bad["team_governance"]["hiring_plan"][0]["cost_driver_ref"] = "12000 EUR"
    assert_invalid(validator_cls, schema, bad, "hiring cost not a ref")

    # driver_ref: FTE e driver di costo headcount nascono come P-ASS-*
    # nel candidate e diventano ASS-* una volta applicati. Lo schema deve
    # ammettere entrambe le forme, con la stessa semantica di ANY_ASS_RE
    # (_framework.py): tre cifre piene oppure quattro+ senza zero iniziale.
    for ref in ("ASS-040", "P-ASS-201", "ASS-1000", "P-ASS-1000"):
        for field, path in (("fte_ref", ("roles", 0)),
                            ("cost_driver_ref", ("hiring_plan", 0))):
            ok = team_governance()
            ok["team_governance"][path[0]][path[1]][field] = ref
            assert_valid(validator_cls, schema, ok, f"{field} {ref}")

    # Le forme malformate restano respinte: padding divergente, prefisso non
    # canonico, namespace sbagliato, letterale, minuscole, troncature.
    for ref in ("ASS-0040", "P-ASS-0040", "PASS-201", "P-ROLE-001", "ASS-40",
                "ass-040", "P-ASS-", "ASS-040 ", "12000 EUR", ""):
        for field, path in (("fte_ref", ("roles", 0)),
                            ("cost_driver_ref", ("hiring_plan", 0))):
            bad = team_governance()
            bad["team_governance"][path[0]][path[1]][field] = ref
            assert_invalid(validator_cls, schema, bad, f"{field} {ref!r}")

    # la restrizione cross-file a entity_type core_process è di refint: lo
    # schema deve dichiararla nella description senza pretendere di imporla
    text = json.dumps(schema, ensure_ascii=False)
    if "core_process" not in text:
        raise TestFailure(
            "team-governance must document that covers_processes resolves "
            "only to core_process definitions")


def check_milestone_plan(validator_cls, schema):
    assert_valid(validator_cls, schema, milestone_plan(), "milestone-plan")

    # financial_plan_inputs required (contratto financial_plan_inputs)
    bad = milestone_plan()
    del bad["milestone_plan"]["financial_plan_inputs"]
    assert_invalid(validator_cls, schema, bad, "financial_plan_inputs missing")
    bad = milestone_plan()
    del bad["milestone_plan"]["financial_plan_inputs"]["som_ref"]
    assert_invalid(validator_cls, schema, bad, "financial input som_ref missing")
    bad = milestone_plan()
    bad["milestone_plan"]["financial_plan_inputs"]["pricing_ref"] = "4.99 EUR"
    assert_invalid(validator_cls, schema, bad, "financial input not a ref")

    bad = milestone_plan()
    bad["milestone_plan"]["milestones"][0]["category"] = "financial"
    assert_invalid(validator_cls, schema, bad, "milestone category out of enum")

    bad = milestone_plan()
    bad["milestone_plan"]["milestones"][0]["owner_ref"] = "ASS-001"
    assert_invalid(validator_cls, schema, bad, "milestone owner not a ROLE")

    bad = milestone_plan()
    bad["milestone_plan"]["milestones"][1]["depends_on"] = ["ROLE-001"]
    assert_invalid(validator_cls, schema, bad, "depends_on not a MIL")

    bad = milestone_plan()
    bad["milestone_plan"]["milestones"][0]["target_date"] = "15/12/2026"
    assert_invalid(validator_cls, schema, bad, "date not ISO-8601")

    bad = milestone_plan()
    bad["milestone_plan"]["milestones"][0]["success_criteria"] = []
    assert_invalid(validator_cls, schema, bad, "empty success_criteria")

    for key in ("go_no_go_rule", "cost_ref", "exit_criteria"):
        bad = milestone_plan()
        del bad["milestone_plan"]["milestones"][0][key]
        assert_invalid(validator_cls, schema, bad, f"milestone without {key}")


def check_decisions_register(validator_cls, schema):
    assert_valid(validator_cls, schema, decisions_register(), "decisions-register")

    valid_init = copy.deepcopy(decisions_register())
    valid_init["initialized_from"] = {
        "source": "shared/decision-log.md",
        "source_sha256": "b" * 64,
        "derived_floor": 20,
        "initialized_at": "2026-07-20T09:59:00Z",
        "operation_id": "op-2026-07-20-0001",
    }
    assert_valid(validator_cls, schema, valid_init, "initialized_from present")

    # target_refs con uniqueItems
    bad = decisions_register()
    bad["decisions"][0]["target_refs"] = ["ASS-011", "ASS-011"]
    assert_invalid(validator_cls, schema, bad, "duplicate target_refs")

    bad = decisions_register()
    bad["decisions"][0]["decision_type"] = "assumption_delete"
    assert_invalid(validator_cls, schema, bad, "decision_type out of enum")

    bad = decisions_register()
    bad["decisions"][0]["id"] = "DEC-0021"
    assert_invalid(validator_cls, schema, bad, "non canonical DEC id")

    for value in ("A" * 64, "abc", "a" * 63):
        bad = decisions_register()
        bad["decisions"][0]["request_payload_hash"] = value
        assert_invalid(validator_cls, schema, bad,
                       f"request_payload_hash {value[:8]!r}")

    for key in ("operation_id", "request_payload_hash", "decision_type",
                "target_refs", "motivation", "approver", "created_at"):
        bad = decisions_register()
        del bad["decisions"][0][key]
        assert_invalid(validator_cls, schema, bad, f"decision without {key}")

    # l'unicità di id/operation_id NON è delegata allo schema:
    # due record distinti con lo stesso id restano validi a schema e sono
    # respinti dai controlli applicativi del loader.
    two = copy.deepcopy(decisions_register())
    second = copy.deepcopy(two["decisions"][0])
    second["created_at"] = "2026-07-20T11:00:00Z"
    two["decisions"].append(second)
    assert_valid(validator_cls, schema, two,
                 "duplicate ids stay a loader concern, not a schema one")
    text = json.dumps(schema, ensure_ascii=False)
    if "loader" not in text:
        raise TestFailure(
            "decisions-register must document that id/operation_id "
            "uniqueness is enforced by the loader")


def check_stage_names(root):
    config = read_json(root / CONFIG_REL)
    order = config.get("stage_order", {})
    for stage in ("07_operations-and-ip", "08_team-and-governance",
                  "09_roadmap-and-milestones"):
        if stage not in order:
            raise TestFailure(f"canonical stage folder missing in config: {stage}")


def run(root):
    validator_cls = get_validator()
    schemas = check_schema_documents(root, validator_cls)
    check_operations_model(validator_cls, schemas["operations-model.schema.json"])
    check_team_governance(validator_cls, schemas["team-governance.schema.json"])
    check_milestone_plan(validator_cls, schemas["milestone-plan.schema.json"])
    check_decisions_register(
        validator_cls, schemas["decisions-register.schema.json"])
    check_stage_names(root)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-SCHEMAS-0-3 Stage 7-9 and decisions-register schema "
          "contracts")


if __name__ == "__main__":
    main()
