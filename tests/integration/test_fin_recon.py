#!/usr/bin/env python3
"""Riconciliazioni del motore finanziario -- `FE-C-13` ... `FE-C-19` e
`FS-C-11` ... `FS-C-14`.

Ogni contratto verifica UNA riconciliazione del payload intermedio prodotto
da `validate_financial_engine`: e' riportata sempre, anche quando passa, porta
formula, residuo e tolleranza APPLICATA, e fallisce sul PROPRIO `rec_id`.

UNDICI RICONCILIAZIONI, E SOLO UNDICI
------------------------------------
    moduli core                          REC-01  REC-02  REC-03  REC-04
                                         REC-05  REC-12  REC-14
    break-even, scenari e categorie      REC-06  REC-11  REC-13  REC-15

`REC-09` (copertura delle milestone) non e' prodotta dal motore: la pubblica
il costruttore canonico come `NOT_APPLICABLE`, e percio' non ha un contratto
qui. `REC-07` e `REC-08` sono opzionali e non prodotte; `REC-10` riguarda lo
Stage 11.

COSTRUZIONE DEL RED E DEL GREEN
-------------------------------
Ogni riconciliazione costruisce il RED **appena oltre** la tolleranza e il
GREEN **appena entro**: il test misura la TOLLERANZA, non il segno.

Il residuo e' prodotto da un DIFETTO NORMATIVO UNICO e dichiarato: un importo
che il modulo consuma ma che **nessuna categoria di fonti e usi dichiara**. Un
importo non categorizzabile non e' attribuibile ne' a una riga di dettaglio ne'
a una direzione di cassa: rompe percio' l'identita' dettaglio/totale del
proprio modulo **e** l'identita' di cassa. Ogni contratto asserisce il PROPRIO
`rec_id` in FAIL con il PROPRIO residuo attribuito: un `REC-*` diverso in FAIL
non soddisfa il contratto (attribuzione vietata).

I valori dei record canonici sono DATI DI CASO DI TEST dichiarati riga per
riga, scelti perche' producono identita' ESATTE in
`Decimal`: `churn = 0` rende la sopravvivenza pari a 1 in ogni periodo, cosi'
che il residuo coincida ESATTAMENTE con l'importo non categorizzato.
"""
import argparse
import copy
import decimal
import importlib.util
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

TESTKIT_REL = "tests/integration"
ENGINE_HARNESS = "test_fin_engine"

EXIT_OK = 0
EXIT_RED = 1
EXIT_USAGE = 2
EXIT_STATE = 3


def _load_engine_harness(root):
    """Riusa i costruttori DICHIARATIVI di `test_fin_engine.py`.

    Nessuna duplicazione: i due moduli condividono un solo costruttore di
    ingresso e un solo invocatore del punto d'ingresso, cosi' che una
    divergenza fra loro sia impossibile per costruzione.
    """
    path = Path(root) / TESTKIT_REL / f"{ENGINE_HARNESS}.py"
    if not path.is_file():
        raise RuntimeError(f"harness del motore assente: {path}")
    spec = importlib.util.spec_from_file_location(ENGINE_HARNESS, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[ENGINE_HARNESS] = module
    spec.loader.exec_module(module)
    return module


ENG = None  # popolato da `main` (evita import circolari a tempo di modulo)

#: Tolleranze APPLICATE, lette da `enforcement-config.json` e mai reinventate.
TOLERANCE_KEYS = {"REC-01": "EUR", "REC-02": "EUR", "REC-03": "EUR",
                  "REC-04": "EUR", "REC-05": "EUR", "REC-12": "ratio",
                  "REC-14": "count",
                  # break-even, scenari e categorie: tutte e quattro in
                  # tolleranza `EUR`.
                  "REC-06": "EUR", "REC-11": "EUR", "REC-13": "EUR",
                  "REC-15": "EUR"}

#: Il residuo del RED e' APPENA OLTRE la tolleranza `EUR` 0.01; quello del
#: GREEN e' APPENA ENTRO. Sono DATI DI CASO DI TEST, non costanti del motore.
RED_RESIDUAL = "0.02"
GREEN_RESIDUAL = "0.005"


# --------------------------------------------------------------------------
# Fixture DICHIARATE delle riconciliazioni
# --------------------------------------------------------------------------


def flat_records(ctx, **over):
    """Record canonici a sopravvivenza UNITARIA (`churn = 0`).

    Con `churn = 0` la serie di ricavo e' costante e il residuo coincide
    esattamente con l'importo non categorizzato: il test misura la tolleranza
    e non l'aritmetica del churn, che e' materia di `FE-C-07`.
    """
    return ENG.base_records(
        ctx, price="1", volume="1", churn="0", variable_cost="0.04",
        headcount="2", payroll_unit="2", opex="12", opening_cash="50000",
        **over)


def flat_rows(ctx, records):
    rows = ENG.base_rows(ctx, records)
    for entry in rows:
        if entry["role"] in ("customer_volume", "variable_cost", "opex",
                             "headcount"):
            entry["cardinality"] = "many"
        if entry["role"] == "headcount":
            entry["cost_category"] = "operating_cost"
    return rows


def add_uncategorised(ctx, records, rows, role, idx, value, unit,
                      measure_kind, frequency, conversion_policy, timing_rule,
                      start_period=None, end_period=None, value_divisor="1"):
    """Aggiunge un importo che il modulo consuma e che NESSUNA categoria di
    fonti e usi dichiara: e' il difetto normativo unico da cui nasce il
    residuo."""
    ref = f"ASS-{idx:03d}"
    declared = Decimal(str(value)) / Decimal(str(value_divisor))
    records[ref] = ENG.record(ctx["testkit"], idx, float(declared), unit,
                              category="operations")
    rows.append(ENG.row(ctx, f"DRV-{idx:03d}", role, ref, unit, measure_kind,
                        frequency, conversion_policy, timing_rule, records,
                        start_period=start_period, end_period=end_period,
                        cardinality="many"))
    return ref


def run_case(ctx, base, name, records, rows, **over):
    project, _ = ENG.make_project(ctx, base, name=name)
    return ENG.run_engine(ctx, project,
                          ENG.engine_input(ctx, rows, records, **over))


def reconciliation(run, rec_id):
    plan = ENG.plan_of(run) or {}
    return ((plan.get("reconciliations") or {}).get(rec_id)) or {}


def check_reported(ctx, run, rec_id, findings):
    """Ogni riconciliazione e' riportata SEMPRE, anche se PASS."""
    entry = reconciliation(run, rec_id)
    if not entry:
        findings.append(f"{rec_id}: assente dal payload: un controllo che non "
                        "compare equivale a un controllo non eseguito")
        return None
    ENG.validate_ref(ctx, entry, "#/$defs/reconciliation", rec_id, findings)
    for field in ("formula", "status", "severity", "tolerance",
                  "tolerance_unit"):
        if not entry.get(field):
            findings.append(f"{rec_id}: campo {field!r} assente")
    if entry.get("rec_id") != rec_id:
        findings.append(
            f"{rec_id}: rec_id={entry.get('rec_id')!r} non attribuito")
    tolerances = ctx["enforcement"].get("tolerances") or {}
    key = TOLERANCE_KEYS[rec_id]
    expected = tolerances.get(key)
    # La soglia APPLICATA vive nel `tolerance_ledger` dell'envelope intermedio
    # NON canonico: `$defs.reconciliation` e' `additionalProperties: false` e
    # aggiungervi un campo violerebbe lo schema.
    applied = ((run.get("result") or {}).get("tolerance_ledger")
               or {}).get(rec_id)
    if applied is None:
        findings.append(
            f"{rec_id}: soglia APPLICATA non riportata (tolerance_value)")
    elif expected is None:
        findings.append(
            f"{rec_id}: nessuna soglia {key!r} in enforcement-config")
    elif Decimal(str(applied)) != Decimal(str(expected)):
        findings.append(
            f"{rec_id}: soglia applicata {applied!r} diversa da "
            f"enforcement-config.tolerances[{key!r}]={expected!r}")
    return entry


def assert_status(entry, rec_id, expected_status, findings, label):
    if entry is None:
        return
    if entry.get("status") != expected_status:
        findings.append(
            f"{label}: {rec_id} status={entry.get('status')!r} invece di "
            f"{expected_status!r}")
    if expected_status == "FAIL" and entry.get("severity") != "FAIL":
        findings.append(
            f"{label}: {rec_id} severity={entry.get('severity')!r} invece di "
            "FAIL: una riconciliazione che non torna e NON blocca e' la "
            "mutazione trasversale che ogni riconciliazione deve rilevare")


def assert_residual(entry, rec_id, expected, findings, label,
                    breakdown_required=True):
    if entry is None:
        return
    residual = entry.get("residual")
    if residual is None:
        findings.append(f"{label}: {rec_id} senza residual")
    else:
        observed = Decimal(str(residual)).copy_abs()
        if observed != Decimal(expected):
            findings.append(
                f"{label}: {rec_id} residual={residual!r} invece di "
                f"{expected}: il RED dev'essere APPENA OLTRE la tolleranza e "
                "il GREEN APPENA ENTRO")
    if breakdown_required and not entry.get("residual_breakdown"):
        findings.append(
            f"{label}: {rec_id} senza residual_breakdown: l'attribuzione "
            "manca anche quando la riconciliazione passa")


def _detail_contract(ctx, rec_id, role, idx, unit, measure_kind, frequency,
                     conversion_policy, timing_rule, start_period=None,
                     end_period=None, breakdown_key=None, value_divisor="1"):
    """Corpo comune di `REC-01`, `REC-02`, `REC-03` e `REC-04`.

    Un importo NON CATEGORIZZATO entra nel totale del modulo e non nel
    dettaglio: il residuo coincide esattamente con quell'importo.
    """
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix=f"fin_core_{rec_id.lower()}_") as base:
        base = Path(base)
        for label, amount, status in (("RED", RED_RESIDUAL, "FAIL"),
                                      ("GREEN", GREEN_RESIDUAL, "PASS")):
            records = flat_records(ctx)
            rows = flat_rows(ctx, records)
            add_uncategorised(ctx, records, rows, role, idx, amount, unit,
                              measure_kind, frequency, conversion_policy,
                              timing_rule, start_period=start_period,
                              end_period=end_period,
                              value_divisor=value_divisor)
            run = run_case(ctx, base, f"{rec_id.lower()}-{label.lower()}",
                           records, rows)
            runs.append(run)
            if not run["available"]:
                return [run["reason"]], runs
            entry = check_reported(ctx, run, rec_id, findings)
            assert_status(entry, rec_id, status, findings, label)
            assert_residual(entry, rec_id, amount, findings, label)
            if entry and breakdown_key:
                breakdown = entry.get("residual_breakdown") or {}
                if breakdown_key not in breakdown:
                    findings.append(
                        f"{label}: {rec_id} residual_breakdown privo della "
                        f"chiave {breakdown_key!r}: il residuo non e' "
                        f"attribuito; chiavi={sorted(breakdown)}")
            if entry and label == "RED":
                refs = entry.get("affected_refs") or []
                if f"DRV-{idx:03d}" not in refs:
                    findings.append(
                        f"RED: {rec_id} non attribuito a DRV-{idx:03d}; "
                        f"affected_refs={refs}")
        # Attribuzione VIETATA: un `REC-*` diverso in FAIL non soddisfa.
        other = [rid for rid in ENG.M3_REC_IDS if rid != rec_id]
        red_run = runs[0]
        failing = [rid for rid in other
                   if reconciliation(red_run, rid).get("status") == "FAIL"]
        if rec_id not in [rid for rid in ENG.M3_REC_IDS
                          if reconciliation(red_run, rid).get("status") == "FAIL"]:
            findings.append(
                f"RED: {rec_id} NON e' FAIL mentre lo sono {failing}: il "
                "contratto sarebbe soddisfatto da una riconciliazione diversa")
    return findings, runs


def c13(ctx):
    """`FE-C-13` `REC-01` -- Sigma dettaglio ricavi = totale ricavi."""
    return _detail_contract(ctx, "REC-01", "customer_volume", 50, "count",
                            "stock", "monthly", "carry_level", "constant",
                            start_period=0, end_period=11, breakdown_key="0")


def c14(ctx):
    """`FE-C-14` `REC-02` -- Sigma dettaglio COGS = totale COGS."""
    return _detail_contract(ctx, "REC-02", "variable_cost", 51, "EUR/count",
                            "per_unit", "per_unit", "preserve_rate",
                            "NOT_APPLICABLE", breakdown_key="0")


def c15(ctx):
    """`FE-C-15` `REC-03` -- Sigma (FTE x costo unitario) = payroll."""
    # Il driver del residuo e' un LIVELLO FTE: il residuo in EUR e'
    # FTE x costo unitario, e il divisore lo riporta APPENA OLTRE / APPENA
    # ENTRO la tolleranza EUR. Ignorare il costo unitario cambia il residuo:
    # e' la mutazione che questo contratto deve rilevare.
    return _detail_contract(ctx, "REC-03", "headcount", 52, "FTE", "stock",
                            "monthly", "carry_level", "constant",
                            start_period=0, end_period=11,
                            breakdown_key="DRV-052", value_divisor="2")


def c16(ctx):
    """`FE-C-16` `REC-04` -- Sigma dettaglio opex = totale opex."""
    return _detail_contract(ctx, "REC-04", "opex", 53, "EUR", "flow",
                            "annual", "allocate", "one_off",
                            start_period=0, end_period=0,
                            breakdown_key="uncategorised")


def c17(ctx):
    """`FE-C-17` `REC-05` -- `opening + in - out = ending`, per periodo."""
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_core_rec05_") as base:
        base = Path(base)
        for label, amount, status in (("RED", RED_RESIDUAL, "FAIL"),
                                      ("GREEN", GREEN_RESIDUAL, "PASS")):
            records = flat_records(ctx)
            rows = flat_rows(ctx, records)
            add_uncategorised(ctx, records, rows, "opex", 54, amount, "EUR",
                              "flow", "annual", "allocate", "one_off",
                              start_period=0, end_period=0)
            run = run_case(ctx, base, f"rec05-{label.lower()}", records, rows)
            runs.append(run)
            if not run["available"]:
                return [run["reason"]], runs
            entry = check_reported(ctx, run, "REC-05", findings)
            assert_status(entry, "REC-05", status, findings, label)
            assert_residual(entry, "REC-05", amount, findings, label)
            if entry:
                breakdown = entry.get("residual_breakdown") or {}
                if "0" not in breakdown:
                    findings.append(
                        f"{label}: REC-05 residual_breakdown senza il PERIODO "
                        f"0; chiavi={sorted(breakdown)}")
        # Caso POSITIVO puro: senza alcun importo non categorizzato
        # l'identita' e' esatta e il residuo e' ZERO.
        records = flat_records(ctx)
        rows = flat_rows(ctx, records)
        clean = run_case(ctx, base, "rec05-clean", records, rows)
        runs.append(clean)
        entry = check_reported(ctx, clean, "REC-05", findings)
        assert_status(entry, "REC-05", "PASS", findings, "CLEAN")
        assert_residual(entry, "REC-05", "0", findings, "CLEAN")
        cash = ENG.modules_of(clean).get("cash_flow") or {}
        opening = ENG.dec(ENG.metric_of(cash, "opening_0"))
        if opening != Decimal(str(records["ASS-008"]["value"])):
            findings.append(
                f"CLEAN: opening_0={opening} diverso dal saldo di apertura "
                f"dichiarato {records['ASS-008']['value']}")
    return findings, runs


def c18(ctx):
    """`FE-C-18` `REC-12` -- Sigma quote = 1, SOLO per `measure_kind: flow`.

    RED-1: `custom_schedule` che somma 0.9 su un driver `flow` (fixture F-5).
    RED-2: CASO NEGATIVO DI AMBITO -- `REC-12` applicata a un driver `stock`
    e' un errore di APPLICAZIONE della regola, non un piano invalido.
    """
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_core_rec12_") as base:
        base = Path(base)
        # RED-1 -- schedule che perde massa.
        records = flat_records(ctx)
        rows = flat_rows(ctx, records)
        for entry in rows:
            if entry["role"] == "opex":
                entry["timing_rule"] = "custom_schedule"
                entry["timing_schedule"] = {str(i): 0.075 for i in range(12)}
        red = run_case(ctx, base, "rec12-red", records, rows)
        runs.append(red)
        if not red["available"]:
            return [red["reason"]], runs
        entry = check_reported(ctx, red, "REC-12", findings)
        assert_status(entry, "REC-12", "FAIL", findings, "RED-1")
        if entry:
            residual = entry.get("residual")
            if residual is None or \
                    abs(Decimal(str(residual)) + Decimal("0.1")) > Decimal("1e-9"):
                findings.append(
                    f"RED-1: REC-12 residual={residual!r} invece di -0.1 "
                    "(0.9 - 1)")
            if "DRV-007" not in (entry.get("affected_refs") or []):
                findings.append(
                    "RED-1: REC-12 non attribuita al DRV-* flow (DRV-007); "
                    f"affected_refs={entry.get('affected_refs')}")
        # GREEN -- la stessa schedule che somma ESATTAMENTE 1.
        records = flat_records(ctx)
        rows = flat_rows(ctx, records)
        for entry_row in rows:
            if entry_row["role"] == "opex":
                entry_row["timing_rule"] = "custom_schedule"
                schedule = {str(i): "0.08" for i in range(12)}
                schedule["11"] = "0.12"
                entry_row["timing_schedule"] = schedule
        green = run_case(ctx, base, "rec12-green", records, rows)
        runs.append(green)
        entry = check_reported(ctx, green, "REC-12", findings)
        assert_status(entry, "REC-12", "PASS", findings, "GREEN")
        if entry and entry.get("residual") is not None and \
                Decimal(str(entry["residual"])).copy_abs() > Decimal("1e-6"):
            findings.append(
                f"GREEN: REC-12 residual={entry['residual']!r} oltre la "
                "tolleranza ratio 1e-6")
        # RED-2 -- caso negativo di AMBITO: gli `stock` sono ESENTI.
        breakdown = (entry or {}).get("residual_breakdown") or {}
        for driver_id in ("DRV-002", "DRV-005"):
            if driver_id in breakdown:
                findings.append(
                    f"RED-2: REC-12 e' applicata al driver STOCK {driver_id}: "
                    "e' un errore di APPLICAZIONE della regola")
        scope = (entry or {}).get("affected_refs") or []
        for driver_id in ("DRV-001", "DRV-002", "DRV-003", "DRV-005",
                          "DRV-006"):
            if driver_id in scope:
                findings.append(
                    f"RED-2: REC-12 nomina il driver non-flow {driver_id}")
        # Il piano NON e' invalido per il solo fatto dell'ambito.
        plan = ENG.plan_of(green) or {}
        if (plan.get("validation") or {}).get("result") == "FAIL":
            findings.append(
                "RED-2: il piano e' FAIL sul caso GREEN: l'ambito di REC-12 "
                "non deve produrre un piano invalido")
    return findings, runs


def c19(ctx):
    """`FE-C-19` `REC-14` -- livello per periodo = serie dichiarata.

    RED: una variazione di livello fra periodi consecutivi NON spiegata da un
    evento dichiarato. GREEN: ogni variazione spiegata da `step_level` o da
    `from_schedule` con copertura COMPLETA della finestra.
    """
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_core_rec14_") as base:
        base = Path(base)
        # GREEN -- `step_level` con gli eventi DICHIARATI.
        records = flat_records(ctx)
        rows = flat_rows(ctx, records)
        for entry_row in rows:
            if entry_row["role"] == "headcount":
                entry_row["timing_rule"] = "step_level"
                entry_row["timing_schedule"] = {"0": 1.0, "6": 2.0}
        green = run_case(ctx, base, "rec14-green", records, rows)
        runs.append(green)
        if not green["available"]:
            return [green["reason"]], runs
        entry = check_reported(ctx, green, "REC-14", findings)
        assert_status(entry, "REC-14", "PASS", findings, "GREEN")
        headcount = ENG.modules_of(green).get("headcount") or {}
        for index, expected in ((0, "1"), (5, "1"), (6, "2"), (11, "2")):
            observed = ENG.series_of(headcount, index)
            if observed != Decimal(expected):
                findings.append(
                    f"GREEN: livello FTE al periodo {index} = {observed} "
                    f"invece di {expected}: il livello non e' PORTATO fino al "
                    "gradino successivo")
        # RED -- `from_schedule` con copertura INCOMPLETA della finestra.
        records = flat_records(ctx)
        rows = flat_rows(ctx, records)
        for entry_row in rows:
            if entry_row["role"] == "headcount":
                entry_row["timing_rule"] = "from_schedule"
                entry_row["timing_schedule"] = {"0": 1.0, "6": 2.0}
        red = run_case(ctx, base, "rec14-red", records, rows)
        runs.append(red)
        entry = check_reported(ctx, red, "REC-14", findings)
        assert_status(entry, "REC-14", "FAIL", findings, "RED")
        if entry:
            breakdown = entry.get("residual_breakdown") or {}
            if not breakdown:
                findings.append(
                    "RED: REC-14 senza residual_breakdown: la variazione non "
                    "spiegata non e' attribuita al PERIODO")
            elif not any(key.isdigit() for key in breakdown):
                findings.append(
                    f"RED: REC-14 residual_breakdown senza indice di periodo; "
                    f"chiavi={sorted(breakdown)}")
            if "DRV-005" not in (entry.get("affected_refs") or []):
                findings.append(
                    "RED: REC-14 non attribuita a DRV-005; affected_refs="
                    f"{entry.get('affected_refs')}")
            if entry.get("tolerance_unit") not in ("FTE", "count"):
                findings.append(
                    f"RED: REC-14 tolerance_unit="
                    f"{entry.get('tolerance_unit')!r}: la tolleranza di "
                    "REC-14 e' nell'unita' del driver")
        # Attribuzione VIETATA: `REC-12` in FAIL non soddisfa `REC-14`.
        if reconciliation(red, "REC-14").get("status") != "FAIL":
            findings.append(
                "RED: REC-14 non e' FAIL: il contratto sarebbe soddisfatto da "
                "REC-12")
        # Esclusione di falso positivo: il contratto fallisce con `REC-03`
        # VERDE.
        if reconciliation(red, "REC-03").get("status") != "PASS":
            findings.append(
                "esclusione di falso positivo: REC-03 non e' PASS sul caso "
                "RED di REC-14: il contratto perderebbe la propria "
                "specificita'")
    return findings, runs


# --------------------------------------------------------------------------
# Riconciliazioni di break-even, scenari e categorie -- `FS-C-11` ... `FS-C-14`
# --------------------------------------------------------------------------


def add_interest_line(ctx, records, rows, idx, value):
    """Una VOCE DI RACCORDO reale: un costo in categoria `interest`.

    Senza di essa il ponte P&L -> cassa sarebbe un'identita' banale fra
    grandezze gia' uguali -- e un test che passa sempre non misura nulla.
    E' il ruolo della fixture `F-10`.
    """
    ref = f"ASS-{idx:03d}"
    records[ref] = ENG.record(ctx["testkit"], idx, float(value), "EUR",
                              category="finance")
    rows.append(ENG.row(ctx, f"DRV-{idx:03d}", "opex", ref, "EUR", "flow",
                        "annual", "allocate", "one_off", records,
                        start_period=0, end_period=0, cardinality="many",
                        cost_category="interest"))
    return ref


def c_m4_11(ctx):
    """`FS-C-11` `REC-06` -- ponte P&L -> cassa (fixture `F-10`).

    `NOT_APPLICABLE` NON e' ammesso qui: su `F-10` la riconciliazione e'
    DISCRIMINANTE, e dichiararla non applicabile sarebbe fingerla.
    """
    findings = []
    runs = []
    rec_id = "REC-06"
    with tempfile.TemporaryDirectory(prefix="fin_ext_rec06_") as base:
        base = Path(base)
        for label, residual, status in (("RED", RED_RESIDUAL, "FAIL"),
                                        ("GREEN", GREEN_RESIDUAL, "PASS")):
            records = flat_records(ctx)
            rows = flat_rows(ctx, records)
            # La voce di raccordo che rende il ponte NON banale.
            add_interest_line(ctx, records, rows, 60, "500")
            # Il difetto normativo unico: un'uscita che NESSUNA categoria di
            # fonti e usi dichiara resta fuori dal ponte.
            add_uncategorised(ctx, records, rows, "opex", 61, residual, "EUR",
                              "flow", "annual", "allocate", "one_off",
                              start_period=0, end_period=0)
            run = run_case(ctx, base, f"rec06-{label.lower()}", records, rows)
            runs.append(run)
            if not run["available"]:
                return [run["reason"]], runs
            entry = check_reported(ctx, run, rec_id, findings)
            assert_status(entry, rec_id, status, findings, label)
            assert_residual(entry, rec_id, residual, findings, label)
            if entry and entry.get("status") == "NOT_APPLICABLE":
                findings.append(
                    f"{label}: {rec_id} dichiarata NOT_APPLICABLE su una "
                    "fixture con voce di raccordo: e' vietato, perche' "
                    "li' la riconciliazione e' DISCRIMINANTE")
            if entry and label == "RED":
                refs = entry.get("affected_refs") or []
                if "interest" not in refs:
                    findings.append(
                        f"RED: {rec_id} non nomina la voce di raccordo; "
                        f"affected_refs={refs}")
        # Attribuzione: il PROPRIO rec_id e' FAIL sul caso RED.
        if reconciliation(runs[0], rec_id).get("status") != "FAIL":
            findings.append(
                f"RED: {rec_id} non e' FAIL: il contratto sarebbe soddisfatto "
                "da una riconciliazione diversa")
    return findings, runs


def c_m4_12(ctx):
    """`FS-C-12` `REC-11` -- sintesi di scenario = dettaglio DI QUELLO
    SCENARIO, con riconciliazione INDIPENDENTE per ciascuno."""
    findings = []
    runs = []
    rec_id = "REC-11"
    with tempfile.TemporaryDirectory(prefix="fin_ext_rec11_") as base:
        base = Path(base)
        # Terna DIFFERENZIATA: senza input differenziati la coincidenza
        # sarebbe vacua e il contratto non misurerebbe nulla.
        records = ENG.triplet_records(ctx)
        rows = ENG.base_rows(ctx, records)
        run = run_case(ctx, base, "rec11-green", records, rows)
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        entry = check_reported(ctx, run, rec_id, findings)
        assert_status(entry, rec_id, "PASS", findings, "GREEN")
        plan = ENG.plan_of(run) or {}
        scenarios = ((plan.get("results") or {}).get("scenarios")) or {}
        produced = [sid for sid in ENG.SCENARIO_IDS
                    if (scenarios.get(sid) or {}).get("status") == "PASS"]
        if len(produced) != len(ENG.SCENARIO_IDS):
            findings.append(
                f"scenari prodotti {produced} invece dei tre scenari su "
                "copertura PIENA")
        # La coincidenza sul SOLO base non soddisfa: il breakdown porta una
        # voce per CIASCUNO scenario prodotto.
        breakdown = (entry or {}).get("residual_breakdown") or {}
        for scenario_id in produced:
            if not any(key.startswith(f"{scenario_id}.") for key in breakdown):
                findings.append(
                    f"{rec_id}: nessuna voce di residuo per lo scenario "
                    f"{scenario_id!r}: la riconciliazione del solo base non "
                    "soddisfa il contratto (attribuzione vietata)")
        refs = (entry or {}).get("affected_refs") or []
        if sorted(refs) != sorted(produced):
            findings.append(
                f"{rec_id}: affected_refs={refs} non nomina i tre scenari "
                f"riconciliati {produced}")
        # RED -- la sintesi di uno scenario RIUSATA da un altro. Il difetto e'
        # costruito sul PAYLOAD, non sul motore: e' la mutazione della
        # sintesi di scenario riusata.
        red_payload = copy.deepcopy(run["result"])
        target = ((red_payload.get("financial_payload") or {}).get("results")
                  or {}).get("scenarios") or {}
        if "base" in target and "downside" in target:
            target["downside"]["summary"] = copy.deepcopy(
                target["base"]["summary"])
            recomputed = _recompute_rec11(target)
            if recomputed == "PASS":
                findings.append(
                    "RED: la sintesi del base RIUSATA su downside NON produce "
                    f"{rec_id} FAIL: la riconciliazione non e' indipendente "
                    "per scenario")
        else:
            findings.append(
                "RED non costruibile: scenari assenti dal payload")
    return findings, runs


def _recompute_rec11(scenarios):
    """Ricalcolo INDIPENDENTE dell'identita' di `REC-11`, qui nell'harness.

    Non chiama il motore: confronta la sintesi DICHIARATA col dettaglio
    DICHIARATO, scenario per scenario. E' la misura del contratto, non una
    copia della sua implementazione.
    """
    eur = Decimal("0.01")
    for scenario_id, entry in sorted(scenarios.items()):
        if not isinstance(entry, dict) or entry.get("status") != "PASS":
            continue
        for key, block in sorted((entry.get("series") or {}).items()):
            total = sum((Decimal(str(value)) for value in block.values()),
                        Decimal(0))
            declared = (entry.get("summary") or {}).get(f"{key}_total")
            if declared is None:
                return "FAIL"
            if (Decimal(str(declared)) - total).copy_abs() > eur:
                return "FAIL"
    return "PASS"


def c_m4_13(ctx):
    """`FS-C-13` `REC-13` -- categorie MUTUAMENTE ESCLUSIVE, riga `other`
    verso zero (fixture `F-7`: lo stesso costo in DUE categorie)."""
    findings = []
    runs = []
    rec_id = "REC-13"
    with tempfile.TemporaryDirectory(prefix="fin_ext_rec13_") as base:
        base = Path(base)
        for label, residual, status in (("RED", RED_RESIDUAL, "FAIL"),
                                        ("GREEN", GREEN_RESIDUAL, "PASS")):
            records = flat_records(ctx)
            rows = flat_rows(ctx, records)
            # Lo STESSO record canonico legato DUE volte, in DUE categorie:
            # e' la doppia categorizzazione, e il totale autoritativo lo conta
            # UNA volta mentre la somma per categoria lo conta DUE.
            ref = f"ASS-{70:03d}"
            records[ref] = ENG.record(ctx["testkit"], 70, float(residual),
                                      "EUR", category="operations")
            for suffix, category in (("A", "operating_cost"),
                                     ("B", "interest")):
                rows.append(ENG.row(
                    ctx, f"DRV-07{suffix}", "opex", ref, "EUR", "flow",
                    "annual", "allocate", "one_off", records,
                    start_period=0, end_period=0, cardinality="many",
                    cost_category=category))
            run = run_case(ctx, base, f"rec13-{label.lower()}", records, rows)
            runs.append(run)
            if not run["available"]:
                return [run["reason"]], runs
            entry = check_reported(ctx, run, rec_id, findings)
            assert_status(entry, rec_id, status, findings, label)
            assert_residual(entry, rec_id, residual, findings, label)
            if entry and label == "RED":
                breakdown = entry.get("residual_breakdown") or {}
                if ref not in breakdown:
                    findings.append(
                        f"RED: {rec_id} non nomina il record {ref} contato "
                        f"due volte; chiavi={sorted(breakdown)}")
                elif "operating_cost" not in str(breakdown.get(ref)) or \
                        "interest" not in str(breakdown.get(ref)):
                    findings.append(
                        f"RED: {rec_id}: le DUE categorie non sono NOMINATE "
                        f"nel residuo di {ref}: {breakdown.get(ref)!r}")
        # Attribuzione VIETATA: `REC-04` FAIL non soddisfa `REC-13`.
        if reconciliation(runs[0], rec_id).get("status") != "FAIL":
            findings.append(
                f"RED: {rec_id} non e' FAIL: il contratto sarebbe soddisfatto "
                "da REC-04")
    return findings, runs


def c_m4_14(ctx):
    """`FS-C-14` `REC-15` -- identita' del pareggio coi costi fissi."""
    findings = []
    runs = []
    rec_id = "REC-15"
    with tempfile.TemporaryDirectory(prefix="fin_ext_rec15_") as base:
        base = Path(base)
        for label, residual, status in (("RED", RED_RESIDUAL, "FAIL"),
                                        ("GREEN", GREEN_RESIDUAL, "PASS")):
            records = flat_records(ctx)
            rows = flat_rows(ctx, records)
            # Un costo di PERSONALE che nessuna categoria dichiara: entra nei
            # costi fissi del pareggio e non nei costi fissi CATEGORIZZATI.
            # Il carrier e' DIVERSO da quello di `REC-06` (opex), cosi' che i
            # due contratti restino distinguibili.
            add_uncategorised(ctx, records, rows, "headcount", 80, residual,
                              "FTE", "stock", "monthly", "carry_level",
                              "constant", start_period=0, end_period=11,
                              value_divisor="2")
            run = run_case(ctx, base, f"rec15-{label.lower()}", records, rows)
            runs.append(run)
            if not run["available"]:
                return [run["reason"]], runs
            entry = check_reported(ctx, run, rec_id, findings)
            assert_status(entry, rec_id, status, findings, label)
            assert_residual(entry, rec_id, residual, findings, label,
                            breakdown_required=False)
            if entry and entry.get("expected") is None:
                findings.append(
                    f"{label}: {rec_id} senza `expected`: lo SCARTO non e' "
                    "nominato contro i costi fissi del periodo")
        # Esclusione di falso positivo: il contratto fallisce ANCHE con un
        # `outcome` dichiarato. `outcome: REACHED` senza identita' non
        # soddisfa (attribuzione vietata).
        red = runs[0]
        module = (((ENG.plan_of(red) or {}).get("results") or {})
                  .get("modules") or {}).get("break_even") or {}
        if module.get("outcome") not in ("REACHED", "NOT_REACHED",
                                         "NOT_REACHABLE"):
            findings.append(
                f"break_even.outcome={module.get('outcome')!r} non dichiarato "
                "sul caso RED di REC-15")
        if reconciliation(red, rec_id).get("status") != "FAIL":
            findings.append(
                f"RED: {rec_id} non e' FAIL benche' l'identita' del pareggio "
                "sia rotta oltre la tolleranza")
    return findings, runs


# --------------------------------------------------------------------------
# Registro dei contratti
# --------------------------------------------------------------------------

CONTRACTS = [
    {"id": "FE-C-13", "rec": "REC-01", "fn": c13,
     "rule": "dettaglio ricavi = totale ricavi entro la tolleranza EUR",
     "fixture": "F-1",
     "red": "riga di dettaglio ricavi omessa dal totale, scarto 0.02 EUR",
     "green": "scarto 0.005 EUR, status PASS",
     "attribution": "rec_id REC-01, residual_breakdown per PERIODO",
     "mutation": "totale ricavi calcolato senza una riga di dettaglio"},
    {"id": "FE-C-14", "rec": "REC-02", "fn": c14,
     "rule": "dettaglio COGS = totale COGS entro la tolleranza EUR",
     "fixture": "F-1",
     "red": "idem su COGS", "green": "idem",
     "attribution": "rec_id REC-02",
     "mutation": "totale COGS calcolato senza una riga di dettaglio"},
    {"id": "FE-C-15", "rec": "REC-03", "fn": c15,
     "rule": "payroll = Sigma (FTE x costo unitario) entro la tolleranza "
             "EUR",
     "fixture": "F-4",
     "red": "payroll != Sigma (FTE x costo)", "green": "identita' entro 0.01",
     "attribution": "rec_id REC-03, residuo per RUOLO",
     "mutation": "ignorare il costo unitario"},
    {"id": "FE-C-16", "rec": "REC-04", "fn": c16,
     "rule": "dettaglio opex per categoria = totale opex entro la "
             "tolleranza EUR",
     "fixture": "F-7",
     "red": "una categoria omessa dal totale", "green": "tutte mappate",
     "attribution": "rec_id REC-04, residuo per CATEGORIA",
     "mutation": "totale opex calcolato senza una categoria"},
    {"id": "FE-C-17", "rec": "REC-05", "fn": c17,
     "rule": "roll-forward di cassa: opening + cash_in - cash_out = ending",
     "fixture": "F-1",
     "red": "opening + in - out != ending", "green": "identita' esatta",
     "attribution": "rec_id REC-05, residuo per PERIODO",
     "mutation": "saldo finale che perde un movimento di cassa"},
    {"id": "FE-C-18", "rec": "REC-12", "fn": c18,
     "rule": "Sigma quote di ogni timing_rule = 1, SOLO per i flow",
     "fixture": "F-5",
     "red": "RED-1 custom_schedule che somma 0.9; RED-2 REC-12 applicata a "
            "un driver stock",
     "green": "Sigma quote = 1 +- ratio 1e-6 SOLO per flow; stock esente",
     "attribution": "rec_id REC-12 attribuito al DRV-* flow",
     "mutation": "schedule di ripartizione che perde massa"},
    {"id": "FE-C-19", "rec": "REC-14", "fn": c19,
     "rule": "livello per periodo = serie dichiarata, SOLO per gli stock",
     "fixture": "F-4, F-5",
     "red": "livello che varia fra periodi consecutivi senza evento dichiarato",
     "green": "ogni variazione spiegata da step_level / from_schedule",
     "attribution": "rec_id REC-14, variazione non spiegata col PERIODO",
     "mutation": "livello che cambia senza evento dichiarato"},
    # ---- break-even, scenari e categorie ------------------------------------
    {"id": "FS-C-11", "rec": "REC-06", "fn": c_m4_11,
     "rule": "ponte P&L -> cassa con voce di raccordo reale",
     "fixture": "F-10",
     "red": "ponte P&L->cassa che perde una voce di raccordo",
     "green": "ponte completo entro EUR 0.01; NOT_APPLICABLE VIETATO su F-10",
     "attribution": "rec_id REC-06, voce di raccordo NOMINATA",
     "mutation": "ponte che ignora la voce di raccordo"},
    {"id": "FS-C-12", "rec": "REC-11", "fn": c_m4_12,
     "rule": "sintesi di scenario = dettaglio dello stesso scenario",
     "fixture": "F-1",
     "red": "sintesi di scenario che non coincide col dettaglio di quello "
            "scenario",
     "green": "coincidenza per TUTTI gli scenari prodotti",
     "attribution": "rec_id REC-11 + scenario",
     "mutation": "sintesi di uno scenario riusata da un altro"},
    {"id": "FS-C-13", "rec": "REC-13", "fn": c_m4_13,
     "rule": "categorie di costo mutuamente esclusive, riga other -> 0",
     "fixture": "F-7 (costo in DUE categorie)",
     "red": "stesso costo mappato in due categorie: riga other != 0",
     "green": "categorie mutuamente esclusive, other -> 0",
     "attribution": "rec_id REC-13, riga other col residuo e le DUE categorie",
     "mutation": "stesso costo contato in due categorie"},
    {"id": "FS-C-14", "rec": "REC-15", "fn": c_m4_14,
     "rule": "ricavo di pareggio x (margine unitario / prezzo) = costi "
             "fissi",
     "fixture": "F-1",
     "red": "ricavo di pareggio che non soddisfa l'identita' coi costi fissi",
     "green": "identita' entro EUR 0.01",
     "attribution": "rec_id REC-15, scarto NOMINATO",
     "mutation": "pareggio che non soddisfa l'identita' coi costi fissi"},
]

CONTRACT_IDS = tuple(entry["id"] for entry in CONTRACTS)


def run_one(ctx, contract):
    try:
        findings, runs = contract["fn"](ctx)
    except (KeyError, TypeError, ValueError, decimal.InvalidOperation) as exc:
        findings = [f"errore di valutazione del contratto: {exc!r}"]
        runs = []
    observed = set()
    for run in runs or ():
        observed |= set(run.get("observed") or ())
    return {"contract": contract, "red": bool(findings), "findings": findings,
            "observed": sorted(observed), "runs": runs or []}


def format_line(result, measure):
    contract = result["contract"]
    count, total = measure
    return (
        "{state:<5} {cid:<12} {rec:<7} observed={observed} "
        "specificity={count}/{total} attribution={attr} | reason={reason}"
        .format(state="RED" if result["red"] else "GREEN",
                cid=contract["id"], rec=contract["rec"],
                observed=result["observed"] or "-", count=count, total=total,
                attr=contract["attribution"],
                reason="; ".join(result["findings"]) or "-"))


def specificity(results):
    """Misura di specificita' sui `rec_id` in FAIL osservati."""
    observations = []
    for result in results:
        for run in result["runs"]:
            plan = ENG.plan_of(run) or {}
            failing = {rec for rec, entry in
                       (plan.get("reconciliations") or {}).items()
                       if entry.get("status") == "FAIL"}
            observations.append(failing)
    measures = {}
    for result in results:
        target = {result["contract"]["rec"]}
        count = sum(1 for failing in observations if target <= failing)
        measures[result["contract"]["id"]] = (count, len(observations))
    return measures


def main(argv=None):
    global ENG
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(
        prog="test_fin_recon.py", add_help=True,
        description="Riconciliazioni del motore finanziario.")
    parser.add_argument("--root", required=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--contract", help="esegue una sola riconciliazione")
    mode.add_argument("--all", action="store_true",
                      help="esegue tutte le riconciliazioni (default)")
    parser.add_argument("--list", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE

    if args.list:
        for contract_id in CONTRACT_IDS:
            print(contract_id)
        return EXIT_OK

    if not args.root:
        print("USAGE ERROR: --root obbligatorio", file=sys.stderr)
        return EXIT_USAGE
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"USAGE ERROR: --root non e' una directory: {root}",
              file=sys.stderr)
        return EXIT_USAGE

    if args.contract and args.contract not in CONTRACT_IDS:
        print(f"USAGE ERROR: contratto inesistente: {args.contract}; ammessi: "
              f"{', '.join(CONTRACT_IDS)}", file=sys.stderr)
        return EXIT_USAGE

    try:
        ENG = _load_engine_harness(root)
    except RuntimeError as exc:
        print(f"HARNESS DEFECT: {exc}", file=sys.stderr)
        return EXIT_STATE
    try:
        ctx = ENG.build_context(ENG.resolve_root(str(root)))
    except ENG.HarnessUsageError as exc:
        print(f"USAGE ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except ENG.HarnessDefect as exc:
        print(f"HARNESS DEFECT: {exc}", file=sys.stderr)
        return EXIT_STATE
    try:
        selected = [entry for entry in CONTRACTS
                    if not args.contract or entry["id"] == args.contract]
        results = [run_one(ctx, entry) for entry in selected]
    except ENG.HarnessDefect as exc:
        print(f"HARNESS DEFECT: {exc}", file=sys.stderr)
        return EXIT_STATE

    measures = specificity(results)
    for result in results:
        print(format_line(result, measures[result["contract"]["id"]]))
    red = [result for result in results if result["red"]]
    print("SUMMARY: {total} riconciliazioni, {red} RED, {green} GREEN".format(
        total=len(results), red=len(red), green=len(results) - len(red)))
    if red:
        return EXIT_RED
    print("PASS: T-FIN-RECON undici riconciliazioni del motore "
          "finanziario")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
