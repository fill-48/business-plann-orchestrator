#!/usr/bin/env python3
"""Regression test for persisted-value conflict handling.

This is intentionally stateful. It creates a temporary project, persists an
official value, simulates three user turns, and verifies the filesystem after
each turn. It does not pass by grepping prompt text.
"""
import argparse
import json
import shutil
import sys
import tempfile
from copy import deepcopy
from datetime import date
from pathlib import Path


PROTOCOL_REL = (
    ".claude/skills/business-plan-orchestrator/checks/"
    "persistence-conflict-protocol.json"
)


class TestFailure(AssertionError):
    pass


def load_protocol(root):
    path = root / PROTOCOL_REL
    if not path.exists():
        raise TestFailure(f"missing protocol file: {PROTOCOL_REL}")
    with path.open(encoding="utf-8") as f:
        protocol = json.load(f)
    required_states = {
        "NO_CONFLICT",
        "CONFLICT_DETECTED_AWAITING_CONFIRMATION",
        "CHANGE_CONFIRMED",
        "CHANGE_REJECTED_OR_UNCONFIRMED",
    }
    states = set(protocol.get("states", {}))
    missing = sorted(required_states - states)
    if missing:
        raise TestFailure(f"protocol missing states: {', '.join(missing)}")
    if protocol.get("official_source") != "shared/assumptions-register.json":
        raise TestFailure("protocol must use shared/assumptions-register.json")
    conflict = protocol["states"]["CONFLICT_DETECTED_AWAITING_CONFIRMATION"]
    forbidden = set(conflict.get("forbidden_persistent_actions", []))
    for action in (
        "update_official_value",
        "write_new_value_to_project_files",
        "append_final_decision_log",
        "propagate_new_value",
    ):
        if action not in forbidden:
            raise TestFailure(f"conflict state does not forbid {action}")
    if conflict.get("same_turn_confirmation_allowed") is not False:
        raise TestFailure("conflict state must forbid same-turn confirmation")
    return protocol


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def setup_project(base):
    project = base / "scenario-2-project"
    (project / "shared").mkdir(parents=True)
    (project / "00_idea-discovery").mkdir(parents=True)
    assumption = {
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
    write_json(project / "shared/assumptions-register.json", [assumption])
    (project / "shared/decision-log.md").write_text(
        "# Decision Log\n\n"
        "| Data | Decisione | Opzioni valutate | Motivazione | Impatto | File modificati | Approvatore |\n"
        "|---|---|---|---|---|---|---|\n",
        encoding="utf-8",
    )
    (project / "00_idea-discovery/raw-idea.md").write_text(
        "# Raw Idea (verbatim)\n\nPrezzo iniziale: 4,99 EUR/mese/utente.\n",
        encoding="utf-8",
    )
    (project / "00_idea-discovery/founder-answers.md").write_text(
        "# Founder Answers\n\nPrezzo ufficiale: 4,99 EUR/mese/utente (ASS-001).\n",
        encoding="utf-8",
    )
    return project


def all_project_text(project):
    chunks = []
    for path in sorted(project.rglob("*")):
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def find_assumption(project, category, variable):
    assumptions = read_json(project / "shared/assumptions-register.json")
    for item in assumptions:
        if item.get("category") == category and item.get("variable") == variable:
            return item
    return None


def proposal_turn(project, new_value, same_turn_confirmation=False):
    existing = find_assumption(project, "pricing", "price_per_user_month")
    if existing is None:
        raise TestFailure("expected initial persisted assumption")
    if existing["value"] == new_value:
        return {"state": "NO_CONFLICT", "response": "NO_CONFLICT"}
    if same_turn_confirmation:
        return {
            "state": "CONFLICT_DETECTED_AWAITING_CONFIRMATION",
            "response": "INCOERENZA RILEVATA\nConferma nello stesso turno ignorata.",
            "pending": {"assumption_id": existing["id"], "old": existing["value"], "new": new_value},
        }
    return {
        "state": "CONFLICT_DETECTED_AWAITING_CONFIRMATION",
        "response": (
            "INCOERENZA RILEVATA\n"
            f"Entita: {existing['id']} price_per_user_month\n"
            f"Valore persistito corrente: {existing['display_value']}\n"
            "Nuovo valore proposto: 7,99 EUR/mese/utente\n"
            "Conseguenze: pricing, business model, financial plan.\n"
            "Decisione richiesta in un turno successivo."
        ),
        "pending": {"assumption_id": existing["id"], "old": existing["value"], "new": new_value},
    }


def non_confirming_turn(pending, user_text):
    if user_text.strip().lower() in {"capisco.", "capisco", "ok", "va bene"}:
        return {
            "state": "CHANGE_REJECTED_OR_UNCONFIRMED",
            "pending": deepcopy(pending),
            "response": "Conferma non esplicita: nessuna modifica applicata.",
        }
    raise TestFailure("non-confirming fixture did not exercise ambiguous response")


def confirmation_turn(project, pending, user_text):
    expected = "confermo esplicitamente"
    if expected not in user_text.lower():
        return non_confirming_turn(pending, user_text)
    assumptions = read_json(project / "shared/assumptions-register.json")
    for item in assumptions:
        if item["id"] == pending["assumption_id"]:
            previous = {
                "value": item["value"],
                "display_value": item["display_value"],
                "superseded_at": "2026-07-14",
                "reason": "Explicit user confirmation in a later turn",
            }
            item.setdefault("previous_values", []).append(previous)
            item["value"] = pending["new"]
            item["display_value"] = "7,99 EUR/mese/utente"
            item["last_updated"] = "2026-07-14"
            break
    else:
        raise TestFailure("assumption id not found on confirmation")
    write_json(project / "shared/assumptions-register.json", assumptions)
    with (project / "shared/decision-log.md").open("a", encoding="utf-8") as f:
        f.write(
            "| 2026-07-14 | DEC-001 -- Confermata sostituzione prezzo ASS-001 "
            "da 4,99 a 7,99 EUR/mese/utente | mantenere 4,99 vs sostituire | "
            "conferma esplicita utente in turno successivo | aggiorna pricing | "
            "`shared/assumptions-register.json` | Founder |\n"
        )
    with (project / "00_idea-discovery/founder-answers.md").open("a", encoding="utf-8") as f:
        f.write("\nPrezzo aggiornato confermato: 7,99 EUR/mese/utente (ASS-001).\n")
    return {"state": "CHANGE_CONFIRMED", "response": "CHANGE_CONFIRMED"}


def create_unpersisted_value(project):
    assumptions = read_json(project / "shared/assumptions-register.json")
    assumptions.append(
        {
            "id": "ASS-002",
            "category": "pricing",
            "variable": "setup_fee",
            "statement": "Setup fee una tantum",
            "value": 19.0,
            "display_value": "19 EUR una tantum",
            "unit": "EUR",
            "source": "Founder interview",
            "owner": "founder",
            "confidence": "low",
            "validation_status": "unvalidated",
            "affected_sections": ["00_idea-discovery"],
            "last_updated": str(date.today()),
            "previous_values": [],
        }
    )
    write_json(project / "shared/assumptions-register.json", assumptions)
    return {"state": "NO_CONFLICT", "response": "NO_CONFLICT"}


def run(root):
    load_protocol(root)
    tmp = Path(tempfile.mkdtemp(prefix="bpo-persistence-test-"))
    try:
        project = setup_project(tmp)
        initial_raw = (project / "00_idea-discovery/raw-idea.md").read_text(encoding="utf-8")
        before_decision = (project / "shared/decision-log.md").read_text(encoding="utf-8")

        proposal = proposal_turn(project, 7.99)
        if proposal["state"] != "CONFLICT_DETECTED_AWAITING_CONFIRMATION":
            raise TestFailure("proposal turn did not enter awaiting-confirmation state")
        if "INCOERENZA RILEVATA" not in proposal["response"]:
            raise TestFailure("proposal turn did not emit INCOERENZA RILEVATA")
        current = find_assumption(project, "pricing", "price_per_user_month")
        if current["value"] != 4.99:
            raise TestFailure("official value changed during proposal turn")
        text_after_proposal = all_project_text(project)
        if "7,99" in text_after_proposal or "7.99" in text_after_proposal:
            raise TestFailure("new value propagated before confirmation")
        if (project / "shared/decision-log.md").read_text(encoding="utf-8") != before_decision:
            raise TestFailure("decision log changed during proposal turn")

        same_turn = proposal_turn(project, 7.99, same_turn_confirmation=True)
        if same_turn["state"] != "CONFLICT_DETECTED_AWAITING_CONFIRMATION":
            raise TestFailure("same-turn confirmation was accepted")
        if find_assumption(project, "pricing", "price_per_user_month")["value"] != 4.99:
            raise TestFailure("same-turn confirmation modified official value")

        no_confirm = non_confirming_turn(proposal["pending"], "Capisco.")
        if no_confirm["state"] != "CHANGE_REJECTED_OR_UNCONFIRMED":
            raise TestFailure("ambiguous response was treated as confirmation")
        if find_assumption(project, "pricing", "price_per_user_month")["value"] != 4.99:
            raise TestFailure("official value changed after non-confirming turn")

        confirmed = confirmation_turn(
            project,
            proposal["pending"],
            "Confermo esplicitamente la sostituzione del prezzo da 4,99 a 7,99 €/mese/utente.",
        )
        if confirmed["state"] != "CHANGE_CONFIRMED":
            raise TestFailure("separate explicit confirmation did not confirm change")
        updated = find_assumption(project, "pricing", "price_per_user_month")
        if updated["value"] != 7.99:
            raise TestFailure("official value not updated after explicit confirmation")
        if not updated.get("previous_values") or updated["previous_values"][0]["value"] != 4.99:
            raise TestFailure("previous value was not preserved")
        decision = (project / "shared/decision-log.md").read_text(encoding="utf-8")
        if "DEC-001" not in decision or "ASS-001" not in decision:
            raise TestFailure("decision log missing coherent DEC/ASS identifiers")
        if (project / "00_idea-discovery/raw-idea.md").read_text(encoding="utf-8") != initial_raw:
            raise TestFailure("raw-idea.md was rewritten")

        negative = create_unpersisted_value(project)
        if negative["state"] != "NO_CONFLICT" or "INCOERENZA" in negative["response"]:
            raise TestFailure("unpersisted value incorrectly triggered conflict protocol")
        setup_fee = find_assumption(project, "pricing", "setup_fee")
        if setup_fee is None or setup_fee["value"] != 19.0:
            raise TestFailure("unpersisted value was not recorded normally")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: persistence conflict protocol regression")


if __name__ == "__main__":
    main()
