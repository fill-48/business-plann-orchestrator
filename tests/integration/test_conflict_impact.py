#!/usr/bin/env python3
"""T-CONFLICT-IMPACT — ciclo di conflitto Stage 6 → Stage 4 completo.

detect → block → conflict → confirm → history → impact → resubmit:

1. detect: validate_cross_stage_consistency rileva capacità GTM < SOM
   canonico (gtm_capacity_below_som, exit 1);
2. block: il transaction manager respinge la transazione (nessuna
   mutazione canonica, journal rolled_back);
3. conflict: lo stato operativo passa a conflict_awaiting_confirmation via
   governance journaled; il gate non è valutabile (conflict_pending);
4. confirm + history: la conferma esplicita (turno successivo) aggiorna
   l'ASS- del SOM e il driver con previous_values + DEC- (aggiornamento
   mediato dall'orchestratore: la scrittura simulata qui rappresenta
   l'esito confermato, con storico completo);
5. impact: i validator --phase impact su Stage 4-6 tornano exit 0 sul
   canonico aggiornato (e rilevano la deriva PRIMA dell'aggiornamento
   coerente del driver);
6. resubmit: il gate di Stage 6 viene rivalutato e advance-stage applica
   la transazione (committed).

Include il caso negativo: divergenza del pricing_ref tra funnel e business
model (price_divergence) e la semantica not_yet_required a Stage 5.
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


NAME = "validate_cross_stage_consistency"

IMPACT_MATRIX = (
    ("validate_market_arithmetic", m5.S4),
    ("validate_unit_economics", m5.S5),
    ("validate_funnel_arithmetic", m5.S6),
    (NAME, m5.S6),
)


def run_validator(root, project, name=NAME, candidate=None, stage=m5.S6,
                  phase="egress"):
    return kit.run_validator_cli(root, name, project=project, stage=stage,
                                 phase=phase, candidate=candidate)


def governance(root, project, status, reason):
    exit_code, out, err = kit.run_tm_cli(
        root, "governance-status", "--project", project,
        "--updates", json.dumps({"status": status}), "--reason", reason)
    if exit_code != 0:
        raise TestFailure(f"governance-status {status} failed: "
                          f"{err.strip()!r}")


def run_impact_matrix(root, project, label):
    """Rivalidazione downstream del ciclo di conflitto: tutti i validator
    di dominio in fase impact sugli Stage 4-6 devono tornare exit 0 sul
    canonico corrente."""
    for name, stage in IMPACT_MATRIX:
        exit_code, out, err = run_validator(root, project, name=name,
                                            candidate=None, stage=stage,
                                            phase="impact")
        if exit_code != 0:
            raise TestFailure(
                f"{label}: {name} --phase impact expected exit 0, got "
                f"{exit_code} (out {out.strip()!r} err {err.strip()!r})")


def conflicting_candidate(project, tx_id="tx-conflict"):
    """Funnel coerente al proprio interno ma con capacità GTM (800k EUR)
    inferiore al SOM canonico (1M EUR): 16000 * 0.25 * 0.2 = 800 clienti."""
    return kit.make_candidate(
        project, m5.S6, tx_id=tx_id,
        structured=m5.funnel_structured(),
        proposed=m5.funnel_proposed(leads=16000, spend=200000))


def run(root):
    if not (root / kit.VALIDATORS_REL / f"{NAME}.py").exists():
        raise TestFailure(f"missing validator: {NAME}.py")

    with tempfile.TemporaryDirectory(prefix="bpo-conflict-") as tmp:
        tmp = Path(tmp)

        # 0a. Semantica three-state a Stage 5: il funnel non è ancora dovuto
        #     -> nessun FAIL, warning not_yet_required.
        p0 = m5.make_stage5_project(tmp, "ci0")
        c0 = kit.make_candidate(p0, m5.S5,
                                structured=m5.business_structured_proposed(),
                                proposed=m5.business_proposed())
        exit_code, out, err = run_validator(root, p0, candidate=c0,
                                            stage=m5.S5)
        if exit_code != 0:
            raise TestFailure("cross-stage at stage 5 must not fail for the "
                              f"missing funnel, got {exit_code} "
                              f"(out {out.strip()!r} err {err.strip()!r})")
        report = kit.parse_report(out, "stage 5 three-state")
        if "not_yet_required" not in [w["code"] for w in report["warnings"]]:
            raise TestFailure("stage 5: expected not_yet_required warning, "
                              f"got {report['warnings']}")

        # 0b. Fuori matrice: Stage 4 -> exit 2.
        exit_code, _, _ = run_validator(root, p0, candidate=c0, stage=m5.S4)
        if exit_code != 2:
            raise TestFailure(f"stage fuori matrice must exit 2, got "
                              f"{exit_code}")

        # 0c. pricing_ref divergente tra funnel e business model: FAIL.
        p0c = m5.make_stage6_project(tmp, "ci0c")
        c0c = kit.make_candidate(
            p0c, m5.S6,
            structured=m5.funnel_structured(pricing_ref="ASS-013"),
            proposed=m5.funnel_proposed())
        exit_code, out, _ = run_validator(root, p0c, candidate=c0c)
        if exit_code != 1:
            raise TestFailure(f"price divergence must exit 1, got "
                              f"{exit_code}")
        report = kit.parse_report(out, "price divergence")
        if "price_divergence" not in [e["code"] for e in report["errors"]]:
            raise TestFailure("expected price_divergence, got "
                              f"{[e['code'] for e in report['errors']]}")

        # ------------------------------------ ciclo di conflitto completo
        p = m5.make_stage6_project(tmp, "ci1")
        candidate = conflicting_candidate(p)

        # 1. detect: capacità GTM (800k) < SOM canonico (1M) -> FAIL.
        exit_code, out, err = run_validator(root, p, candidate=candidate)
        if exit_code != 1:
            raise TestFailure(f"detect: expected exit 1, got {exit_code} "
                              f"(out {out.strip()!r} err {err.strip()!r})")
        report = kit.parse_report(out, "detect")
        if "gtm_capacity_below_som" not in [e["code"]
                                            for e in report["errors"]]:
            raise TestFailure("detect: expected gtm_capacity_below_som, got "
                              f"{[e['code'] for e in report['errors']]}")

        # 2. block: il TM respinge; nessuna mutazione canonica.
        before = kit.snapshot_canonical(p)
        exit_code, out, _ = kit.run_tm_cli(
            root, "advance-stage", "--project", p, "--stage", m5.S6,
            "--candidate", candidate, "--gate-result", "approved")
        if exit_code != 1:
            raise TestFailure(f"block: TM must reject, got {exit_code}")
        if kit.snapshot_canonical(p) != before:
            raise TestFailure("block: rejected transaction mutated the "
                              "canonical state")
        journal = kit.read_json(kit.find_journals(p)[-1])
        if journal.get("state") != "rolled_back":
            raise TestFailure("block: journal must be rolled_back, got "
                              f"{journal.get('state')!r}")

        # 3. conflict: stato operativo conflict_awaiting_confirmation
        #    (governance journaled), gate non valutabile.
        governance(root, p, "conflict_awaiting_confirmation",
                   "INCOERENZA RILEVATA: capacità GTM < SOM canonico "
                   f"({m5.SOM_ID})")
        exit_code, out, _ = kit.run_validator_cli(
            root, "validate_stage_gate", project=p, stage=m5.S6,
            phase="egress", candidate=conflicting_candidate(
                p, tx_id="tx-gate-probe"))
        if exit_code != 1:
            raise TestFailure("conflict: gate must exit 1 while pending, "
                              f"got {exit_code}")
        report = kit.parse_report(out, "conflict gate")
        if "conflict_pending" not in [e["code"] for e in report["errors"]]:
            raise TestFailure("conflict: expected conflict_pending")

        # Risposta ambigua/assente: lo stato NON cambia (resta awaiting).
        # (La transizione resta governata: nessun avanzamento possibile.)
        exit_code, _, _ = kit.run_tm_cli(
            root, "advance-stage", "--project", p, "--stage", m5.S6,
            "--candidate", conflicting_candidate(p, tx_id="tx-ambiguous"),
            "--gate-result", "approved")
        if exit_code == 0:
            raise TestFailure("conflict: advance while awaiting confirmation "
                              "must not pass")

        # 4. confirm + history (turno successivo, conferma esplicita):
        #    l'aggiornamento confermato abbassa il SOM canonico a 800k
        #    correggendo il driver reachable_share (0.1 -> 0.08), con
        #    previous_values + DEC- su entrambe le voci (update con
        #    history, mediato dall'orchestratore).
        register_path = p / "shared/assumptions-register.json"
        register = kit.read_json(register_path)
        superseded = {"superseded_at": "2026-07-16",
                      "reason": "CHANGE_CONFIRMED: capacità GTM reale "
                                "inferiore al SOM stimato (ciclo di "
                                "conflitto)",
                      "decision_id": "DEC-020"}
        for item in register:
            if item.get("id") == "ASS-002":  # reachable_share
                item["previous_values"] = [dict(superseded,
                                                value=item["value"])]
                item["value"] = 0.08
                item["display_value"] = "0.08 ratio"
            if item.get("id") == m5.SOM_ID:
                item["previous_values"] = [dict(superseded,
                                                value=item["value"])]
                item["value"] = 800000
                item["display_value"] = "800000 EUR"
        kit.write_json(register_path, register)
        decision_log = p / "shared/decision-log.md"
        decision_log.write_text(
            decision_log.read_text(encoding="utf-8")
            + "\n## DEC-020 — SOM ridotto a 800k EUR\n\n"
              "Conferma esplicita dell'utente (turno successivo): la "
              "capacità GTM sostenibile è 800 clienti/anno; reachable_share "
              "0.1 -> 0.08, som_y1_revenue 1000000 -> 800000 (ciclo di "
              "conflitto, storico in previous_values).\n", encoding="utf-8")

        # Storico verificabile: entrambe le voci portano previous_values+DEC.
        register = kit.read_json(register_path)
        for ref in ("ASS-002", m5.SOM_ID):
            item = [e for e in register if e.get("id") == ref][0]
            prev = item.get("previous_values")
            if not prev or prev[0].get("decision_id") != "DEC-020":
                raise TestFailure(f"history: {ref} senza previous_values "
                                  "con DEC-020")

        # 5. impact: la matrice --phase impact su Stage 4-6 torna verde sul
        #    canonico aggiornato (il funnel non è ancora canonico: il cross
        #    validator segnala not_yet_required, non FAIL).
        run_impact_matrix(root, p, "impact after confirmed update")

        # 6. resubmit: gate rivalutato e advance-stage applicato.
        governance(root, p, "in_progress",
                   "CHANGE_CONFIRMED applicato: si rivaluta il gate Stage 6")
        resubmit = conflicting_candidate(p, tx_id="tx-resubmit")
        exit_code, out, err = kit.run_tm_cli(
            root, "advance-stage", "--project", p, "--stage", m5.S6,
            "--candidate", resubmit, "--gate-result", "approved")
        if exit_code != 0:
            raise TestFailure(f"resubmit: advance must pass, got {exit_code} "
                              f"(out {out.strip()!r} err {err.strip()!r})")
        result = kit.tm_result(out, "resubmit")
        if result.get("advanced_to") != "07_operations-and-ip":
            raise TestFailure(f"resubmit: expected advance to Stage 7, got "
                              f"{result}")
        advances = [j for j in (kit.read_json(path)
                                for path in kit.find_journals(p))
                    if j.get("mode") == "advance"
                    and j.get("state") == "committed"]
        if not advances:
            raise TestFailure("resubmit: no committed advance journal")
        journal = advances[-1]
        ran = {v["validator"] for v in journal.get("validation", [])}
        if NAME not in ran:
            raise TestFailure(f"resubmit: {NAME} must run in egress: {ran}")
        front = (p / "shared/project-status.md").read_text(encoding="utf-8")
        if m5.S6 not in front or "07_operations-and-ip" not in front:
            raise TestFailure("resubmit: project-status must record the "
                              "advance")

        # 7. impact post-commit: ora il funnel è canonico e l'intera matrice
        #    resta verde (capacità 800k == SOM 800k).
        run_impact_matrix(root, p, "impact after commit")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-CONFLICT-IMPACT ciclo di conflitto "
          "detect/block/conflict/confirm/history/impact/resubmit")


if __name__ == "__main__":
    main()
