#!/usr/bin/env python3
"""T-PRICE — prezzo unico cross-artefatto (Stage 5-6).

Il prezzo duplicato in business-model (structured-output) deve coincidere
con l'ASS- di pricing referenziato (`pricing_ref`): la divergenza è un
conflitto (price_conflict, exit 1) e NON produce alcuna scrittura canonica
(il TM respinge; lo stato operativo passa a conflict_awaiting_confirmation
via governance e il gate resta bloccato finché il conflitto è pendente).
A valle (impact), una deriva del prezzo canonico è rilevata allo stesso
modo. La divergenza del pricing_ref tra Stage 5 e Stage 6 è coperta da
T-CONFLICT-IMPACT / validate_cross_stage_consistency (price_divergence).
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


NAME = "validate_unit_economics"


def run(root):
    if not (root / kit.VALIDATORS_REL / f"{NAME}.py").exists():
        raise TestFailure(f"missing validator: {NAME}.py")

    with tempfile.TemporaryDirectory(prefix="bpo-price-") as tmp:
        tmp = Path(tmp)

        # 1. Prezzo coerente con l'ASS-pricing: PASS.
        p1 = m5.make_stage5_project(tmp, "pr1")
        c1 = kit.make_candidate(p1, m5.S5,
                                structured=m5.business_structured_proposed(
                                    price=100),
                                proposed=m5.business_proposed())
        exit_code, out, err = kit.run_validator_cli(
            root, NAME, project=p1, stage=m5.S5, phase="egress",
            candidate=c1)
        if exit_code != 0:
            raise TestFailure(f"matching price must pass, got {exit_code} "
                              f"(out {out.strip()!r} err {err.strip()!r})")

        # 2. Prezzo divergente dall'ASS-pricing: FAIL price_conflict e
        #    nessuna scrittura canonica (TM rejected).
        p2 = m5.make_stage5_project(tmp, "pr2")
        c2 = kit.make_candidate(p2, m5.S5,
                                structured=m5.business_structured_proposed(
                                    price=120),
                                proposed=m5.business_proposed())
        exit_code, out, _ = kit.run_validator_cli(
            root, NAME, project=p2, stage=m5.S5, phase="egress",
            candidate=c2)
        if exit_code != 1:
            raise TestFailure(f"diverging price must exit 1, got {exit_code}")
        report = kit.parse_report(out, "price conflict")
        if "price_conflict" not in [e["code"] for e in report["errors"]]:
            raise TestFailure("expected price_conflict, got "
                              f"{[e['code'] for e in report['errors']]}")

        before = kit.snapshot_canonical(p2)
        exit_code, out, _ = kit.run_tm_cli(
            root, "apply", "--project", p2, "--stage", m5.S5,
            "--candidate", c2)
        if exit_code != 1:
            raise TestFailure("TM apply with price conflict must be "
                              f"rejected, got {exit_code}")
        if kit.snapshot_canonical(p2) != before:
            raise TestFailure("price conflict apply mutated canonical state")

        # 3. Stato operativo: il conflitto apre conflict_awaiting_confirmation
        #    (governance journaled) e il gate resta non valutabile finché
        #    pende (conflict_pending); la conferma esplicita lo riporta
        #    in_progress.
        exit_code, out, err = kit.run_tm_cli(
            root, "governance-status", "--project", p2,
            "--updates", json.dumps(
                {"status": "conflict_awaiting_confirmation"}),
            "--reason", "INCOERENZA RILEVATA: prezzo structured-output vs "
                        "ASS-pricing")
        if exit_code != 0:
            raise TestFailure(f"governance conflict state failed: "
                              f"{err.strip()!r}")
        # il candidate respinto è stato rimosso dal cleanup del TM: la
        # probe del gate usa un candidate fresco
        c2probe = kit.make_candidate(p2, m5.S5, tx_id="tx-price-probe",
                                     structured=m5.business_structured_proposed(
                                         price=120),
                                     proposed=m5.business_proposed())
        exit_code, out, _ = kit.run_validator_cli(
            root, "validate_stage_gate", project=p2, stage=m5.S5,
            phase="egress", candidate=c2probe)
        if exit_code != 1:
            raise TestFailure("gate with pending conflict must exit 1, got "
                              f"{exit_code}")
        report = kit.parse_report(out, "gate conflict")
        if "conflict_pending" not in [e["code"] for e in report["errors"]]:
            raise TestFailure("expected conflict_pending on the gate")

        exit_code, _, err = kit.run_tm_cli(
            root, "governance-status", "--project", p2,
            "--updates", json.dumps({"status": "in_progress"}),
            "--reason", "CHANGE_REJECTED_OR_UNCONFIRMED: si mantiene il "
                        "prezzo canonico, candidate da correggere")
        if exit_code != 0:
            raise TestFailure(f"governance resume failed: {err.strip()!r}")

        # 4. Candidate corretto (prezzo allineato): la transazione passa.
        c2b = kit.make_candidate(p2, m5.S5, tx_id="tx-price-fixed",
                                 structured=m5.business_structured_proposed(
                                     price=100),
                                 proposed=m5.business_proposed())
        exit_code, out, err = kit.run_tm_cli(
            root, "apply", "--project", p2, "--stage", m5.S5,
            "--candidate", c2b)
        if exit_code != 0:
            raise TestFailure("aligned price apply must pass, got "
                              f"{exit_code} (out {out.strip()!r} err "
                              f"{err.strip()!r})")

        # 5. Impact: deriva del prezzo canonico dopo l'applicazione ->
        #    price_conflict sul canonico (Stage 6, fase impact).
        p3 = m5.make_stage6_project(tmp, "pr3")
        register = kit.read_json(p3 / "shared/assumptions-register.json")
        for item in register:
            if item.get("id") == m5.PRICING_ID:
                item["value"] = 150
        kit.write_json(p3 / "shared/assumptions-register.json", register)
        exit_code, out, _ = kit.run_validator_cli(
            root, NAME, project=p3, stage=m5.S6, phase="impact")
        if exit_code != 1:
            raise TestFailure("canonical price drift must exit 1, got "
                              f"{exit_code}")
        report = kit.parse_report(out, "impact price drift")
        if "price_conflict" not in [e["code"] for e in report["errors"]]:
            raise TestFailure("expected price_conflict on impact, got "
                              f"{[e['code'] for e in report['errors']]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-PRICE business-model price == ASS-pricing (conflitto "
          "senza scrittura)")


if __name__ == "__main__":
    main()
