#!/usr/bin/env python3
"""T-CROSS-EXT — validate_cross_stage_consistency sugli Stage 7-9.

Parte operations — le due invarianti introdotte dallo Stage 7:

- ops_capacity_below_gtm: la capacità operativa canonica non regge i volumi
  GTM (customers_out dello Stage 6) -> detect del ciclo di capacità operativa, con **block**
  dimostrato dal transaction manager (apply/advance rifiutati, canonico
  invariato);
- ops_cost_divergence: un costo operativo unitario che duplica una variabile
  di costo esistente con valore diverso (una variabile, un solo ASS-).

Parte team — l'invariante introdotta dallo Stage 8, che chiude la matrice
processi core <-> ruoli:

- headcount_capacity_incoherent: un processo core dichiarato `make` (quindi
  NON esternalizzato) che nessun ruolo copre con headcount reale — né una
  persona, né una posizione aperta con la propria riga di `hiring_plan` e il
  proprio driver di costo. La soglia è strutturale, non numerica: gli FTE
  dichiarati allo Stage 8 non sostengono i processi che lo Stage 7 dichiara
  di fare in casa.

Three-state: un progetto fermo allo Stage 6 non fa mai FAIL sui check degli
Stage 7-8, e un progetto fermo allo Stage 7 (senza team canonico) non fa mai
FAIL su headcount_capacity_incoherent.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import bpo_testkit as kit
import bpo_m5_fixtures as m5


class TestFailure(AssertionError):
    pass


NAME = "validate_cross_stage_consistency"


def run_validator(root, project, candidate=None, stage=m5.S7, phase="egress"):
    return kit.run_validator_cli(root, NAME, project=project, stage=stage,
                                 phase=phase, candidate=candidate)


def candidate_with(project, structured, proposed=None, tx_id="tx-cross-001"):
    if proposed is None:
        proposed = m5.ops_proposed()
    return kit.make_candidate(project, m5.S7, tx_id=tx_id,
                              structured=structured, proposed=proposed)


def expect_code(root, project, candidate, code, label, stage=m5.S7,
                phase="egress"):
    exit_code, out, err = run_validator(root, project, candidate, stage, phase)
    if exit_code != 1:
        raise TestFailure(f"{label}: expected exit 1, got {exit_code} "
                          f"(out {out.strip()!r} err {err.strip()!r})")
    report = kit.parse_report(out, label)
    codes = [e["code"] for e in report["errors"]]
    if code not in codes:
        raise TestFailure(f"{label}: expected {code}, got {codes}")


def run(root):
    if not (root / kit.VALIDATORS_REL / f"{NAME}.py").exists():
        raise TestFailure(f"missing validator: {NAME}.py")

    with tempfile.TemporaryDirectory(prefix="bpo-cross-") as tmp:
        tmp = Path(tmp)

        # 1. Happy path: capacità 1200 >= customers_out 1000; costi coerenti.
        p = m5.make_stage7_project(tmp, "cross-ok")
        c = candidate_with(p, m5.operations_structured())
        exit_code, out, err = run_validator(root, p, c)
        if exit_code != 0:
            raise TestFailure(f"cross-stage happy path: exit {exit_code} "
                              f"(out {out.strip()!r} err {err.strip()!r})")

        # 2. ops_capacity_below_gtm: capacità 500 < customers_out 1000 -> FAIL.
        p = m5.make_stage7_project(tmp, "cross-cap")
        prop = m5.ops_proposed(capacity=500, installed=500, utilization=1.0)
        c = candidate_with(p, m5.operations_structured(), proposed=prop)
        expect_code(root, p, c, "ops_capacity_below_gtm",
                    "capacity below GTM volumes")

        # 2b. block: il transaction manager rifiuta l'apply, canonico invariato.
        before = kit.snapshot_canonical(p)
        exit_code, out, err = kit.run_tm_cli(
            root, "apply", "--project", p, "--stage", m5.S7, "--candidate", c)
        if exit_code != 1:
            raise TestFailure("TM apply con capacità < GTM deve essere "
                              f"rifiutato, got {exit_code}")
        if kit.snapshot_canonical(p) != before:
            raise TestFailure("apply rifiutato ha mutato il canonico")

        # 3. ops_cost_divergence: costo operativo che duplica cogs_unit con
        #    valore diverso (ASS-030 cogs_unit 45 vs ASS-013 cogs_unit 30).
        dup_cost = m5.entry("ASS-030", "cogs_unit", 45, "EUR/count",
                            category="cost")
        p = m5.make_stage7_project(tmp, "cross-cost",
                                   assumptions_extra=[dup_cost])
        struct = m5.operations_structured(unit_ops_cost_refs=["ASS-030"])
        c = candidate_with(p, struct)
        expect_code(root, p, c, "ops_cost_divergence",
                    "operating cost duplicates COGS with a different value")

        # 4. Three-state: progetto fermo allo Stage 6 -> exit 0 (nessun check
        #    degli Stage 7-8).
        p6 = m5.make_stage6_project(tmp, "cross-legacy")
        c6 = kit.make_candidate(p6, m5.S6,
                                structured=m5.funnel_structured(),
                                proposed=m5.funnel_proposed())
        exit_code, out, err = run_validator(root, p6, c6, stage=m5.S6)
        if exit_code != 0:
            raise TestFailure(f"progetto fermo allo Stage 6: exit {exit_code} "
                              f"(out {out.strip()!r} err {err.strip()!r})")

        run_headcount(root, tmp)


# ---------------------------------------------------------------------------
# headcount_capacity_incoherent. Il caso 1 sopra dimostra già il three-state
# di questa invariante: un progetto allo Stage 7 non ha
# team canonico e non deve mai fallire su di essa.
# ---------------------------------------------------------------------------

def unstaffed_lead_roles(hiring_plan=None):
    """ROLE-001 non è più una persona ma una posizione aperta: i processi core
    `make` che copre (OPS-001, OPS-004) restano senza headcount reale se il
    piano assunzioni non la finanzia."""
    roles = [
        {
            "id": "ROLE-001",
            "open_position": "Head of Operations",
            "responsibilities": ["Provisioning e onboarding dei clienti",
                                 "Erogazione del servizio e qualità"],
            "covers_processes": ["OPS-001", "OPS-004"],
            "fte_ref": m5.FTE_LEAD_ID,
        },
        {
            "id": "ROLE-002",
            "open_position": "Head of Partnerships",
            "responsibilities": ["Integrazione e gestione dei canali partner"],
            "covers_processes": ["OPS-005"],
            "fte_ref": m5.FTE_OPEN_ID,
        },
    ]
    if hiring_plan is None:
        hiring_plan = [{"role_ref": "ROLE-002", "period": "Y1H2",
                        "cost_driver_ref": m5.HEADCOUNT_COST_ID}]
    return m5.team_structured(roles=roles, hiring_plan=hiring_plan)


def canonical_unstaffed(**kwargs):
    """Lo stesso difetto, ma sul canonico dello Stage 8 (driver ASS-)."""
    doc = unstaffed_lead_roles(**kwargs)
    block = doc["team_governance"]
    for role in block["roles"]:
        role["fte_ref"] = m5.CANONICAL_TEAM_IDS.get(role["fte_ref"],
                                                    role["fte_ref"])
    for item in block["hiring_plan"]:
        item["cost_driver_ref"] = m5.CANONICAL_TEAM_IDS.get(
            item["cost_driver_ref"], item["cost_driver_ref"])
    return doc


def run_headcount(root, tmp):
    # 5. Happy path Stage 8: ROLE-001 è una persona e copre i due processi
    #    core `make` -> exit 0.
    p = m5.make_stage8_project(tmp, "cross-head-ok")
    c = kit.make_candidate(p, m5.S8, tx_id="tx-cross-head-ok",
                           structured=m5.team_structured(),
                           proposed=m5.team_proposed())
    exit_code, out, err = run_validator(root, p, c, stage=m5.S8)
    if exit_code != 0:
        raise TestFailure(f"team coerente: exit {exit_code} "
                          f"(out {out.strip()!r} err {err.strip()!r})")

    # 6. Processi core `make` coperti solo da una posizione aperta NON
    #    finanziata -> headcount_capacity_incoherent su entrambi.
    p = m5.make_stage8_project(tmp, "cross-head-bad")
    c = kit.make_candidate(p, m5.S8, tx_id="tx-cross-head-bad",
                           structured=unstaffed_lead_roles(),
                           proposed=m5.team_proposed())
    exit_code, out, err = run_validator(root, p, c, stage=m5.S8)
    if exit_code != 1:
        raise TestFailure(f"headcount incoerente: expected exit 1, got "
                          f"{exit_code} (out {out.strip()!r})")
    report = kit.parse_report(out, "headcount incoherent")
    refs = [e["ref"] for e in report["errors"]
            if e["code"] == "headcount_capacity_incoherent"]
    if refs != ["OPS-001", "OPS-004"]:
        raise TestFailure(
            "headcount_capacity_incoherent must anchor every uncovered `make` "
            f"core process, got {refs}")

    # 6b. Processi `buy`/`partner` senza alcun ruolo che li copra: la soglia è
    #     il make_buy_partner, non la copertura di ruolo. Se il filtro
    #     make-only si allargasse a buy/partner questi due processi
    #     verrebbero segnalati (nessun ruolo li copre) -> caso discriminante.
    p = m5.make_stage8_project(tmp, "cross-head-buy-partner",
                               operations=m5.operations_buy_partner_only())
    c = kit.make_candidate(p, m5.S8, tx_id="tx-cross-head-buy-partner",
                           structured=m5.team_structured(),
                           proposed=m5.team_proposed())
    exit_code, out, err = run_validator(root, p, c, stage=m5.S8)
    if exit_code != 0:
        raise TestFailure(
            "buy/partner core processes without headcount coverage must not "
            f"raise headcount_capacity_incoherent: exit {exit_code} "
            f"(out {out.strip()!r} err {err.strip()!r})")

    # 7. Le stesse posizioni aperte, ma finanziate nel piano assunzioni: il
    #    fabbisogno esiste come impegno strutturato -> exit 0. Senza questo
    #    caso il check sarebbe indistinguibile da «serve una persona oggi».
    p = m5.make_stage8_project(tmp, "cross-head-hired")
    plan = [
        {"role_ref": "ROLE-001", "period": "Y1H1",
         "cost_driver_ref": m5.HEADCOUNT_COST_ID},
        {"role_ref": "ROLE-002", "period": "Y1H2",
         "cost_driver_ref": m5.HEADCOUNT_COST_ID},
    ]
    c = kit.make_candidate(p, m5.S8, tx_id="tx-cross-head-hired",
                           structured=unstaffed_lead_roles(hiring_plan=plan),
                           proposed=m5.team_proposed())
    exit_code, out, err = run_validator(root, p, c, stage=m5.S8)
    if exit_code != 0:
        raise TestFailure(f"posizioni aperte finanziate: exit {exit_code} "
                          f"(out {out.strip()!r} err {err.strip()!r})")

    # 8. Stage 9 egress: il difetto vive nel canonico dello Stage 8 e deve
    #    continuare a bloccare (l'egress di validate_team_and_governance a
    #    Stage 9 è pass-through: senza il cross-stage nessuno lo vedrebbe).
    p = m5.make_stage9_project(tmp, "cross-head-stage9",
                               team=canonical_unstaffed())
    c = kit.make_candidate(p, m5.S9, tx_id="tx-cross-head-9",
                           structured=m5.milestone_structured(),
                           proposed=m5.milestone_proposed())
    exit_code, out, err = run_validator(root, p, c, stage=m5.S9)
    if exit_code != 1:
        raise TestFailure(f"headcount incoerente a Stage 9: expected exit 1, "
                          f"got {exit_code} (out {out.strip()!r})")
    report = kit.parse_report(out, "headcount incoherent at stage 9")
    if "headcount_capacity_incoherent" not in [e["code"]
                                               for e in report["errors"]]:
        raise TestFailure(f"stage 9 must keep detecting the defect: {report}")

    # 9. Lo stesso progetto con il team canonico coerente -> exit 0: le
    #    invarianti dello Stage 7 restano verdi e il caso 8 non è un falso positivo.
    p = m5.make_stage9_project(tmp, "cross-stage9-ok")
    c = kit.make_candidate(p, m5.S9, tx_id="tx-cross-9-ok",
                           structured=m5.milestone_structured(),
                           proposed=m5.milestone_proposed())
    exit_code, out, err = run_validator(root, p, c, stage=m5.S9)
    if exit_code != 0:
        raise TestFailure(f"catena 4-9 coerente: exit {exit_code} "
                          f"(out {out.strip()!r} err {err.strip()!r})")

    # 10. Fase impact sul canonico dello Stage 9: nessun candidate, il
    #     difetto di headcount resta visibile.
    p = m5.make_stage9_project(tmp, "cross-head-impact",
                               team=canonical_unstaffed())
    exit_code, out, err = kit.run_validator_cli(
        root, NAME, project=p, stage=m5.S9, phase="impact")
    if exit_code != 1:
        raise TestFailure(f"headcount incoerente in impact: expected exit 1, "
                          f"got {exit_code} (out {out.strip()!r})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-CROSS-EXT ops_capacity_below_gtm detect+block + "
          "ops_cost_divergence + headcount_capacity_incoherent + "
          "three-state")


if __name__ == "__main__":
    main()
