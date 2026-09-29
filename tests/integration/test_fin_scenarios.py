#!/usr/bin/env python3
"""Contratti di SCENARIO del motore finanziario.

Verificano che Base, Downside e Upside siano tre calcoli INDIPENDENTI, che la
polarita' e la copertura di scenario siano applicate come dichiarato, che la
sensitivity muova un driver per volta e che la proiezione di governance NON
canonica porti uno stato per scenario.

OTTO CONTRATTI OSPITATI QUI
---------------------------
    FS-C-01  T-FIN-SCENARIO-ISOLATION
    FS-C-02  T-FIN-NO-CROSS-LEAK
    FS-C-03  T-FIN-SCENARIO-POLARITY
    FS-C-04  T-FIN-SCENARIO-RECON
    FS-C-05  T-FIN-SCENARIO-COVERAGE
    FS-C-06  T-FIN-SCENARIO-COVERAGE-GATE
    FS-C-07  T-FIN-SENSITIVITY
    FS-C-19  T-FIN-ASSUMPTION-STATE-SCENARIOS

Gli altri contratti `FS-C-*` vivono in `test_fin_engine.py`
(`FS-C-08` ... `FS-C-10`, `FS-C-15` ... `FS-C-18`, `FS-C-20`) e in
`test_fin_recon.py` (`FS-C-11` ... `FS-C-14`).

PERCHE' LA FIXTURE DEMO NON E' USABILE QUI
------------------------------------------
Con input IDENTICI nei tre scenari un cross-leak e' per costruzione INVISIBILE
e una polarita' invertita non cambia nulla: `T-FIN-SCENARIO-ISOLATION`,
`T-FIN-NO-CROSS-LEAK` e `T-FIN-SCENARIO-POLARITY` sono esercitabili SOLO sulle
fixture sintetiche di scenario. Ogni terna usata qui e' quindi
DELIBERATAMENTE differenziata.

SEMANTICA DEGLI EXIT CODE
-------------------------
    0   tutti i contratti soddisfatti
    1   almeno un contratto RED
    2   errore d'uso
    3   stato del repository inutilizzabile (difetto di harness)
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

#: I DUE codici di errore degli scenari emessi dal motore. Nessuno e'
#: inventato qui.
AMB_W2_05 = "sensitivity_multi_driver"
AMB_W2_06 = "scenario_series_identical"

#: Enumerazione CHIUSA di `driver_status`, dal piu' basso al piu' alto.
STATUS_ORDER = ("unresolved", "placeholder", "inferred", "confirmed")

ENG = None  # popolato da `main` (evita import circolari a tempo di modulo)


def _load_engine_harness(root):
    """Riusa i costruttori DICHIARATIVI di `test_fin_engine.py`.

    Nessuna duplicazione: le suite del motore condividono un solo
    costruttore di ingresso e un solo invocatore del punto d'ingresso, cosi'
    che una divergenza fra loro sia impossibile per costruzione.
    """
    path = Path(root) / TESTKIT_REL / f"{ENGINE_HARNESS}.py"
    if not path.is_file():
        raise RuntimeError(f"harness del motore assente: {path}")
    spec = importlib.util.spec_from_file_location(ENGINE_HARNESS, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[ENGINE_HARNESS] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# Accessori di lettura del payload
# --------------------------------------------------------------------------


def scenarios_of(run):
    plan = ENG.plan_of(run) or {}
    return ((plan.get("results") or {}).get("scenarios")) or {}


def coverage_of(run):
    return scenarios_of(run).get("coverage") or {}


def produced_ids(run):
    block = scenarios_of(run)
    return [sid for sid in ENG.SCENARIO_IDS
            if (block.get(sid) or {}).get("status") == "PASS"]


def checksums_of(run):
    plan = ENG.plan_of(run) or {}
    return ((plan.get("calculation_metadata") or {}).get("output_checksums")
            or {})


def series_total(entry, key):
    block = (entry.get("series") or {}).get(key) or {}
    return sum((Decimal(str(value)) for value in block.values()), Decimal(0))


def run_full(ctx, base, name, **over):
    """Caso a copertura PIENA: ogni ruolo richiesto porta la terna."""
    records = ENG.triplet_records(ctx, **over)
    rows = ENG.base_rows(ctx, records)
    project, _ = ENG.make_project(ctx, base, fixture_id="F-1", name=name)
    return ENG.run_engine(ctx, project, ENG.engine_input(ctx, rows, records)), \
        records, rows


def strip_triplet(records, refs):
    """Toglie la terna ai record NOMINATI: quei driver restano SCOPERTI.

    Nessun valore e' inventato al loro posto e nessun moltiplicatore di
    default e' applicato.
    """
    for ref in refs:
        for key in ("base_case", "downside_case", "upside_case"):
            records[ref].pop(key, None)
    return records


# --------------------------------------------------------------------------
# `FS-C-01` ... `FS-C-07`
# --------------------------------------------------------------------------


def c01(ctx):
    """`FS-C-01` `T-FIN-SCENARIO-ISOLATION` -- tre scenari indipendenti.

    Il selettore di scenario governa la PRESENTAZIONE, mai il calcolo degli
    altri due. Tre risultati INVARIANTI rispetto al selettore.
    """
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_scen_c01_") as base:
        base = Path(base)
        run, records, rows = run_full(ctx, base, "c01-a")
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        first = checksums_of(run)
        produced = produced_ids(run)
        if sorted(produced) != sorted(ENG.SCENARIO_IDS):
            findings.append(
                f"scenari prodotti {produced} invece dei tre scenari su "
                "copertura PIENA")
        # Il SELETTORE cambia -- i risultati NO. Il selettore e' dichiarato
        # nell'ingresso e non deve entrare in alcun ramo di calcolo.
        for selector in ("downside", "upside"):
            project, _ = ENG.make_project(ctx, base, fixture_id="F-1",
                                          name=f"c01-{selector}")
            other = ENG.run_engine(
                ctx, project,
                ENG.engine_input(ctx, rows, records,
                                 active_scenario=selector))
            runs.append(other)
            second = checksums_of(other)
            for scenario_id in ENG.SCENARIO_IDS:
                if first.get(scenario_id) != second.get(scenario_id):
                    findings.append(
                        f"selettore={selector!r}: output_checksums"
                        f"[{scenario_id!r}] cambia da "
                        f"{first.get(scenario_id)!r} a "
                        f"{second.get(scenario_id)!r}: il selettore GOVERNA il "
                        "calcolo")
        # La sola PRESENZA dei tre scenari non soddisfa il contratto: cio' che
        # lo soddisfa e' l'INVARIANZA dei tre checksum al variare del selettore.
        if len({first.get(sid) for sid in produced}) != len(produced):
            findings.append(
                f"i checksum dei tre scenari non sono DISTINTI: {first}")
    return findings, runs


def c02(ctx):
    """`FS-C-02` `T-FIN-NO-CROSS-LEAK` -- ogni scenario sul proprio set.

    Ogni scenario legge SOLO il proprio set risolto. Il contratto NON e'
    soddisfatto da `T-FIN-SCENARIO-ISOLATION` verde: due scenari possono
    essere invarianti rispetto al selettore e leggere comunque il valore
    sbagliato.
    """
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_scen_c02_") as base:
        base = Path(base)
        run, records, rows = run_full(ctx, base, "c02")
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        block = scenarios_of(run)
        # Ricalcolo INDIPENDENTE del ricavo atteso PER SCENARIO, dai record
        # DICHIARATI: se il motore downside leggesse un valore base, il totale
        # coinciderebbe con quello del base ed e' esattamente cio' che si
        # misura qui.
        totals = {}
        for scenario_id in ENG.SCENARIO_IDS:
            entry = block.get(scenario_id) or {}
            if entry.get("status") != "PASS":
                continue
            totals[scenario_id] = series_total(entry, "revenue")
        if len(totals) != len(ENG.SCENARIO_IDS):
            findings.append(
                f"scenari con serie di ricavo: {sorted(totals)}; attesi i tre "
                "scenari")
        if len(set(totals.values())) != len(totals):
            findings.append(
                f"totali di ricavo COINCIDENTI fra scenari: {totals}: almeno "
                "un motore legge un valore che non e' il proprio")
        # Il ricavo del downside e' MINORE di quello del base, e l'upside
        # MAGGIORE: prezzo e volume sono `revenue_like`.
        if "base" in totals and "downside" in totals and \
                not totals["downside"] < totals["base"]:
            findings.append(
                f"ricavo downside {totals['downside']} non minore del base "
                f"{totals['base']}: il motore downside legge un valore base")
        if "base" in totals and "upside" in totals and \
                not totals["upside"] > totals["base"]:
            findings.append(
                f"ricavo upside {totals['upside']} non maggiore del base "
                f"{totals['base']}")
        # I `driver_refs` di ciascuno scenario sono i PROPRI.
        for scenario_id in produced_ids(run):
            refs = (block.get(scenario_id) or {}).get("driver_refs") or []
            if not refs:
                findings.append(
                    f"scenario {scenario_id!r} senza driver_refs: la lettura "
                    "non e' attribuibile ad alcun DRV-*")
    return findings, runs


def c03(ctx):
    """`FS-C-03` `T-FIN-SCENARIO-POLARITY` -- polarita' di scenario.

    `cost_like`: downside = valore ALTO. `revenue_like`: downside = valore
    BASSO. Applicare `Downside = High` a tutto e' esplicitamente vietato, e il
    profilo `subscription_saas` annota che leggere `churn_rate` e
    `retention_rate` allo stesso modo sarebbe un errore.
    """
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_scen_c03_") as base:
        base = Path(base)
        records = ENG.triplet_records(ctx)
        rows = ENG.base_rows(ctx, records)
        # `retention_rate` -- ruolo OPZIONALE, polarita' `revenue_like` -- e'
        # aggiunto proprio per dimostrare che le due polarita' NON sono lette
        # allo stesso modo.
        records["ASS-030"] = ENG.record(ctx["testkit"], 30, 0.9, "ratio",
                                        category="retention")
        ENG.with_triplet(records, "ASS-030", "0.80", "0.90", "0.95")
        rows.append(ENG.row(ctx, "DRV-030", "retention_rate", "ASS-030",
                            "ratio", "rate", "annual", "compound",
                            "NOT_APPLICABLE", records,
                            scenario_polarity="revenue_like"))
        project, _ = ENG.make_project(ctx, base, fixture_id="F-1", name="c03")
        run = ENG.run_engine(ctx, project,
                             ENG.engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        churn = next(b for b in rows if b["role"] == "churn_rate")
        if churn.get("scenario_polarity") != "cost_like":
            findings.append(
                f"la fixture dichiara churn_rate con polarita' "
                f"{churn.get('scenario_polarity')!r}: il GREEN del contratto "
                "e' `cost_like`")
        if len(produced_ids(run)) != len(ENG.SCENARIO_IDS):
            findings.append(
                "i tre scenari non sono prodotti: la polarita' non sarebbe "
                "misurabile e il contratto sarebbe vacuo")
            return findings, runs
        # RED -- LA STESSA fixture con `churn` dichiarato `revenue_like`. La
        # misura e' sull'EFFETTO prodotto dal motore, non su un ricalcolo
        # dell'harness: con polarita' `cost_like` il downside prende il churn
        # ALTO e il ricavo SCENDE; con `revenue_like` prende il churn BASSO e
        # il ricavo e' PIU' ALTO. Se i due esiti coincidessero, la polarita'
        # non sarebbe applicata affatto.
        flipped = copy.deepcopy(rows)
        for binding in flipped:
            if binding["role"] == "churn_rate":
                binding["scenario_polarity"] = "revenue_like"
        project2, _ = ENG.make_project(ctx, base, fixture_id="F-1",
                                       name="c03-flipped")
        red = ENG.run_engine(ctx, project2,
                             ENG.engine_input(ctx, flipped, records))
        runs.append(red)
        correct = series_total(scenarios_of(run).get("downside") or {},
                               "revenue")
        inverted = series_total(scenarios_of(red).get("downside") or {},
                                "revenue")
        if correct == inverted:
            findings.append(
                f"il ricavo downside NON cambia invertendo la polarita' di "
                f"{churn['driver_id']} ({correct}): la polarita' non e' "
                "applicata")
        elif correct > inverted:
            findings.append(
                f"con churn `cost_like` il ricavo downside e' {correct}, "
                f"MAGGIORE del {inverted} ottenuto con `revenue_like`: per un "
                "driver di COSTO il caso avverso e' il valore ALTO, quindi "
                "piu' attrito e MENO ricavo")
        # `retention_rate` resta `revenue_like`: le due polarita' NON sono
        # lette allo stesso modo, ed e' l'errore che il profilo annota.
        retention = next(b for b in rows if b["role"] == "retention_rate")
        if retention.get("scenario_polarity") != "revenue_like":
            findings.append(
                f"retention_rate dichiarato "
                f"{retention.get('scenario_polarity')!r}: applicare "
                "`Downside = High` anche a retention_rate e' l'errore di "
                "lettura che il profilo subscription_saas annota")
        # Esclusione di falso positivo: il contratto fallisce ANCHE con i tre
        # scenari differenziati, cioe' con `T-FIN-SCENARIO-ISOLATION` verde.
        if len({checksums_of(run).get(sid)
                for sid in produced_ids(run)}) != len(produced_ids(run)):
            findings.append(
                "i tre scenari non sono differenziati: il contratto sarebbe "
                "soddisfatto senza misurare la polarita'")
        # ---- `timing_like`: DOWNSIDE RITARDATO, UPSIDE ANTICIPATO ---------
        # La tavola di polarita' ammette esplicitamente una terza riga,
        # `timing_like`. Per un driver di TIMING la terna dichiara PERIODI -- date
        # di milestone, ramp, ingressi in organico -- e a muoversi e' la
        # FINESTRA, non l'importo. Trattarlo come invariante ignorerebbe in
        # SILENZIO gli estremi che il record DICHIARA, continuando a contare il
        # driver come COPERTO.
        timing_records = ENG.triplet_records(ctx)
        # L'ingresso in organico e' al periodo 2 nel Base, RITARDATO al 4 nel
        # Downside e ANTICIPATO allo 0 nell'Upside. I tre valori sono quelli
        # DICHIARATI dal record: nessun ritardo di default e' inventato.
        ENG.with_triplet(timing_records, "ASS-005", "0", "2", "4")
        timing_rows = ENG.base_rows(ctx, timing_records)
        for binding in timing_rows:
            if binding["role"] == "headcount":
                binding["scenario_polarity"] = "timing_like"
                binding["start_period"] = 2
                binding["polarity_override_rationale"] = (
                    "ingresso in organico: la terna dichiara PERIODI, non "
                    "importi")
        project3, _ = ENG.make_project(ctx, base, fixture_id="F-1",
                                       name="c03-timing")
        timing = ENG.run_engine(ctx, project3,
                                ENG.engine_input(ctx, timing_rows,
                                                 timing_records))
        runs.append(timing)
        timing_block = scenarios_of(timing)
        coverage = coverage_of(timing)
        if coverage.get("level") != "full" or \
                coverage.get("uncovered_driver_refs"):
            findings.append(
                f"timing_like: copertura {coverage.get('level')!r} con "
                f"{coverage.get('uncovered_driver_refs')} scoperti: un driver "
                "di timing con estremi USABILI e' COPERTO come ogni altro")
        if len(produced_ids(timing)) != len(ENG.SCENARIO_IDS):
            findings.append(
                f"timing_like: scenari prodotti {produced_ids(timing)}: la "
                "regola timing_like non sarebbe misurabile")
        else:
            payroll = {sid: series_total(timing_block.get(sid) or {}, "pnl")
                       for sid in ENG.SCENARIO_IDS}
            # BASE INVARIATO: il piano di scenario base coincide con il piano
            # non-scenario, che consuma la finestra DICHIARATA dal binding.
            plan_pnl = ENG.plan_of(timing) or {}
            plan_series = (((plan_pnl.get("results") or {}).get("modules")
                            or {}).get("pnl") or {}).get("series") or {}
            plan_total = sum((Decimal(str(value))
                              for value in plan_series.values()), Decimal(0))
            if payroll["base"] != plan_total:
                findings.append(
                    f"timing_like: il Base di scenario ({payroll['base']}) "
                    f"differisce dal piano ({plan_total}): la polarita' NON "
                    "deve mai mutare il valore base")
            # DOWNSIDE RITARDATO e UPSIDE ANTICIPATO: l'ingresso in organico
            # posticipato costa MENO payroll, quello anticipato ne costa DI
            # PIU'. E' la direzione DICHIARATA dalla terna, non un giudizio di
            # avversita' inventato dall'implementazione.
            if payroll["downside"] == payroll["base"] or \
                    payroll["upside"] == payroll["base"]:
                findings.append(
                    f"timing_like: l'output finanziario NON cambia "
                    f"({payroll}): gli estremi DICHIARATI dal record sono "
                    "SILENZIOSAMENTE IGNORATI mentre il driver conta come "
                    "coperto")
            elif not payroll["downside"] > payroll["base"] > payroll["upside"]:
                findings.append(
                    f"timing_like: {payroll}: il Downside deve consumare "
                    "l'estremo RITARDATO e l'Upside quello ANTICIPATO")
            if len({checksums_of(timing).get(sid)
                    for sid in ENG.SCENARIO_IDS}) != len(ENG.SCENARIO_IDS):
                findings.append(
                    "timing_like: i tre checksum non sono DISTINTI: la "
                    "finestra non e' mossa da alcuno scenario")
        # ---- estremi di timing NON USABILI => driver NON coperto -----------
        # Un estremo fuori orizzonte non e' consumabile come periodo. Il driver
        # NON puo' contare come coperto mentre si comporta da invariante, e non
        # puo' comparire fra i passi di `sensitivity` come driver «mosso».
        unusable_records = ENG.triplet_records(ctx)
        ENG.with_triplet(unusable_records, "ASS-005", "0", "2", "99")
        unusable_rows = ENG.base_rows(ctx, unusable_records)
        for binding in unusable_rows:
            if binding["role"] == "headcount":
                binding["scenario_polarity"] = "timing_like"
                binding["start_period"] = 2
                binding["polarity_override_rationale"] = (
                    "sonda: estremo di timing fuori orizzonte")
        project4, _ = ENG.make_project(ctx, base, fixture_id="F-1",
                                       name="c03-timing-unusable")
        unusable = ENG.run_engine(ctx, project4,
                                  ENG.engine_input(ctx, unusable_rows,
                                                   unusable_records))
        runs.append(unusable)
        unusable_coverage = coverage_of(unusable)
        if "DRV-005" not in (unusable_coverage.get("uncovered_driver_refs")
                             or []):
            findings.append(
                "estremi di timing INUTILIZZABILI: DRV-005 non compare fra gli "
                f"scoperti ({unusable_coverage.get('uncovered_driver_refs')}): "
                "un driver i cui estremi non sono consumabili conta come "
                "COPERTO mentre resta invariante")
        steps = (ENG.plan_of(unusable) or {}).get("sensitivity") or []
        if [step for step in steps if step.get("driver_id") == "DRV-005"]:
            findings.append(
                "estremi di timing INUTILIZZABILI: DRV-005 compare fra i passi "
                "di sensitivity come driver «mosso», mentre il suo valore non "
                "si muove affatto")
    return findings, runs


def c04(ctx):
    """`FS-C-04` `T-FIN-SCENARIO-RECON` -- riconciliazione per scenario.

    TRE riconciliazioni INDIPENDENTI, una per scenario. Tre esiti identici
    COPIATI non soddisfano il contratto.
    """
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_scen_c04_") as base:
        base = Path(base)
        run, _, _ = run_full(ctx, base, "c04")
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        plan = ENG.plan_of(run) or {}
        entry = (plan.get("reconciliations") or {}).get("REC-11") or {}
        if entry.get("status") != "PASS":
            findings.append(
                f"REC-11 status={entry.get('status')!r} su copertura piena")
        breakdown = entry.get("residual_breakdown") or {}
        produced = produced_ids(run)
        for scenario_id in produced:
            own = [key for key in breakdown
                   if key.startswith(f"{scenario_id}.")]
            if not own:
                findings.append(
                    f"REC-11: nessun residuo attribuito allo scenario "
                    f"{scenario_id!r}: la riconciliazione non e' INDIPENDENTE "
                    f"per scenario; chiavi={sorted(breakdown)}")
        refs = entry.get("affected_refs") or []
        if sorted(refs) != sorted(produced):
            findings.append(
                f"REC-11: affected_refs={refs} non nomina i tre scenari "
                f"riconciliati {produced}")
        # Il contratto fallisce ANCHE con `REC-11` verde su un solo scenario:
        # cio' che lo soddisfa e' che ciascuno scenario porti il PROPRIO
        # residuo, non che il totale torni.
        block = scenarios_of(run)
        summaries = {sid: (block.get(sid) or {}).get("summary")
                     for sid in produced}
        distinct = {ENG.json.dumps(value, sort_keys=True)
                    for value in summaries.values() if value is not None}
        if len(distinct) != len(produced):
            findings.append(
                f"le sintesi di scenario non sono DISTINTE ({len(distinct)} su "
                f"{len(produced)}): un esito e' stato COPIATO da un "
                "altro")
    return findings, runs


def c05(ctx):
    """`FS-C-05` `T-FIN-SCENARIO-COVERAGE` -- copertura parziale (fixture
    `F-2`).

    Copertura PARZIALE dichiarata come tale, con l'ELENCO NOMINATIVO dei
    driver privi di terna. `level: partial` con elenco VUOTO non soddisfa.
    """
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_scen_c05_") as base:
        base = Path(base)
        records = ENG.triplet_records(ctx)
        # Meta' dei ruoli richiesti perde la terna: e' la forma di `F-2`.
        stripped = ["ASS-002", "ASS-004", "ASS-006"]
        strip_triplet(records, stripped)
        rows = ENG.base_rows(ctx, records)
        project, _ = ENG.make_project(ctx, base, fixture_id="F-2", name="c05")
        run = ENG.run_engine(ctx, project,
                             ENG.engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        coverage = coverage_of(run)
        if coverage.get("level") != "partial":
            findings.append(
                f"coverage.level={coverage.get('level')!r} invece di "
                "'partial' con meta' dei driver richiesti privi di terna")
        uncovered = coverage.get("uncovered_driver_refs") or []
        if not uncovered:
            findings.append(
                "coverage.uncovered_driver_refs VUOTO su copertura parziale: "
                "`level: partial` con elenco vuoto NON soddisfa il contratto "
                "(attribuzione vietata)")
        expected = sorted(binding["driver_id"] for binding in rows
                          if binding["source_ref"] in stripped)
        if sorted(uncovered) != expected:
            findings.append(
                f"uncovered_driver_refs={sorted(uncovered)} invece di "
                f"{expected}: ogni DRV-* privo di terna dev'essere NOMINATO")
        # Il rapporto NUMERICO corretto non basta: il contratto fallisce anche
        # quando il rapporto e' giusto ma l'elenco manca (verificato sopra).
        ratio = coverage.get("ratio")
        if ratio is None:
            findings.append("coverage.ratio assente")
        else:
            covered = len(expected)
            total = len([b for b in rows if b["role"] in
                         (ctx["profile"].get("required_driver_roles") or [])])
            wanted = Decimal(total - covered) / Decimal(total)
            if Decimal(str(ratio)) != wanted:
                findings.append(
                    f"coverage.ratio={ratio!r} invece di {wanted}: la "
                    "copertura e' misurata sui SOLI ruoli richiesti")
        # I tre scenari SONO prodotti su copertura parziale, con lo stato
        # esplicito propagato e non riassorbibile in un PASS.
        if len(produced_ids(run)) != len(ENG.SCENARIO_IDS):
            findings.append(
                f"scenari prodotti {produced_ids(run)}: su copertura PARZIALE "
                "i tre scenari sono prodotti, con WARNING dichiarato")
        warnings = {entry.get("code") for entry in
                    (run.get("report") or {}).get("warnings") or []}
        if "scenario_coverage" not in warnings:
            findings.append(
                f"nessun WARNING di copertura parziale dichiarato; "
                f"warning osservati={sorted(warnings)}")
    return findings, runs


def c06(ctx):
    """`FS-C-06` `T-FIN-SCENARIO-COVERAGE-GATE` -- copertura nulla, esito
    `approved_with_conditions`, codice `scenario_series_identical` (fixture
    `F-3`).

    Copertura 0 => Downside e Upside `NOT_APPLICABLE`, NON PRODOTTI e NON
    ETICHETTATI. La mutazione da rilevare: tre serie identiche pubblicate come
    tre scenari.
    """
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_scen_c06_") as base:
        base = Path(base)
        # `F-3`: NESSUN driver richiesto porta la terna. E' la forma della
        # fixture demo, dove 0 driver su 8 legati dalla FPI ne hanno una.
        records = ENG.base_records(ctx)
        rows = ENG.base_rows(ctx, records)
        project, _ = ENG.make_project(ctx, base, fixture_id="F-3", name="c06")
        run = ENG.run_engine(ctx, project,
                             ENG.engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        coverage = coverage_of(run)
        if coverage.get("level") != "none":
            findings.append(
                f"coverage.level={coverage.get('level')!r} invece di 'none' "
                "con ZERO driver richiesti coperti")
        block = scenarios_of(run)
        for scenario_id in ("downside", "upside"):
            entry = block.get(scenario_id) or {}
            if entry.get("status") != "NOT_APPLICABLE":
                findings.append(
                    f"scenario {scenario_id!r}: status="
                    f"{entry.get('status')!r} invece di NOT_APPLICABLE con "
                    "copertura 0: non esiste percorso che lo produca")
            if not entry.get("not_applicable_reason"):
                findings.append(
                    f"scenario {scenario_id!r}: NOT_APPLICABLE senza "
                    "not_applicable_reason: l'omissione dev'essere DICHIARATA")
            for forbidden in ("series", "summary", "output_checksum"):
                if entry.get(forbidden) is not None:
                    findings.append(
                        f"scenario {scenario_id!r} porta {forbidden!r} pur "
                        "essendo NOT_APPLICABLE: e' ETICHETTATO senza input "
                        "differenziati, che e' una conformita' solo "
                        "nominale")
        if (block.get("base") or {}).get("status") != "PASS":
            findings.append(
                f"scenario 'base': status="
                f"{(block.get('base') or {}).get('status')!r} invece di PASS: "
                "l'output contiene il SOLO Base")
        # La `COND-*` PROPOSTA, con lo stage entro cui va chiusa.
        condition = coverage.get("proposed_condition_ref")
        if not condition:
            findings.append(
                "nessuna COND-* proposta con copertura 0: il debito non e' "
                "tracciato e lo Stage 11 potrebbe formulare una richiesta di "
                "funding su un downside inesistente")
        checks = {entry.get("check_id"): entry for entry in
                  (run.get("report") or {}).get("checks") or []}
        gate = checks.get("scenario_coverage") or {}
        if "11_funding-request" not in str(gate.get("message")):
            findings.append(
                "il check di copertura non nomina due_before_stage "
                f"'11_funding-request'; messaggio={gate.get('message')!r}")
        # Un `WARNING` di copertura NON soddisfa il contratto: cio' che lo
        # soddisfa e' lo stato `NOT_APPLICABLE` dei due scenari.
        if AMB_W2_06 in run["observed"]:
            findings.append(
                f"{AMB_W2_06} emesso benche' Downside e Upside NON siano "
                "prodotti: il codice presidia le serie IDENTICHE ETICHETTATE, "
                "non l'astensione corretta")
        # ---- `base_only` NON e' un'approvazione piena ---------------------
        # Il RISULTATO DI VALIDAZIONE e' il portatore dell'esito: un lettore a
        # valle che vi legga `PASS` vede un piano pienamente approvato. Con
        # copertura NULLA l'esito previsto e' `approved_with_conditions`, che
        # nel report vale almeno `WARNING` con la condizione NOMINATA.
        result = ((ENG.plan_of(run) or {}).get("validation") or {}).get("result")
        if result == "PASS":
            findings.append(
                "copertura NULLA con validation.result=PASS: il piano PEGGIORE "
                "-- nessuno scenario differenziato -- esce PIENAMENTE "
                "APPROVATO. L'esito previsto e' approved_with_conditions, e "
                "la condizione dev'essere RIFLESSA nel risultato")
        elif result not in ("WARNING", "FAIL"):
            findings.append(
                f"copertura NULLA con validation.result={result!r}: l'esito "
                "atteso e' almeno WARNING")
        warnings = {entry.get("code") for entry in
                    (run.get("report") or {}).get("warnings") or []}
        if "scenario_coverage" not in warnings:
            findings.append(
                "copertura NULLA senza alcun WARNING di copertura in "
                f"warnings[]: osservati={sorted(warnings)}. Un check WARNING "
                "che non entra in warnings[] non muove il risultato")
        condition_warnings = [
            entry for entry in (run.get("report") or {}).get("warnings") or []
            if entry.get("code") == "scenario_coverage"]
        for entry in condition_warnings:
            message = str(entry.get("message") or "")
            if "11_funding-request" not in message:
                findings.append(
                    "il WARNING di copertura NULLA non nomina il confine "
                    f"due_before_stage '11_funding-request': {message!r}")
            if str(entry.get("ref") or "") != condition and \
                    str(condition) not in message:
                findings.append(
                    f"il WARNING di copertura NULLA non nomina la condizione "
                    f"{condition!r}: ref={entry.get('ref')!r}")
        # Nessun numero di Downside o di Upside e' pubblicato, e nessuna
        # prontezza piena di scenario e' dichiarata.
        for scenario_id in ("downside", "upside"):
            entry = block.get(scenario_id) or {}
            if entry.get("summary") or entry.get("series"):
                findings.append(
                    f"copertura NULLA: lo scenario {scenario_id!r} pubblica "
                    "numeri pur non essendo prodotto")
        # ---- SEVERITA' MONOTONA rispetto alla copertura PARZIALE ----------
        # La copertura PARZIALE e' il caso PIU' LIEVE: base-only non puo'
        # risultare MENO severo di essa.
        partial_records = ENG.triplet_records(ctx)
        strip_triplet(partial_records, ["ASS-002", "ASS-004"])
        partial_rows = ENG.base_rows(ctx, partial_records)
        project_p, _ = ENG.make_project(ctx, base, fixture_id="F-2",
                                        name="c06-partial")
        partial = ENG.run_engine(ctx, project_p,
                                 ENG.engine_input(ctx, partial_rows,
                                                  partial_records))
        runs.append(partial)
        severity = {"PASS": 0, "WARNING": 1, "FAIL": 2}
        partial_result = ((ENG.plan_of(partial) or {}).get("validation")
                          or {}).get("result")
        if severity.get(result, -1) < severity.get(partial_result, -1):
            findings.append(
                f"severita' INCOERENTE: base-only risulta {result!r} mentre la "
                f"copertura PARZIALE -- caso piu' LIEVE -- risulta "
                f"{partial_result!r}: il caso peggiore legge piu' pulito del "
                "piu' lieve")
        # ---- `base_only_approvable` e' LETTA -------------------------------
        # La chiave e' DICHIARATA dallo schema di `financial_config`.
        # Cambiarne il valore deve cambiare l'esito: se non lo
        # cambia, la policy non e' letta affatto.
        outcomes = {}
        for approvable in (True, False):
            policy_records = ENG.base_records(ctx)
            policy_rows = ENG.base_rows(ctx, policy_records)
            config = ENG.financial_config(
                ctx, scenario_coverage_policy={"threshold": 0.8,
                                               "base_only_approvable":
                                                   approvable})
            project_x, _ = ENG.make_project(
                ctx, base, fixture_id="F-3", name=f"c06-policy-{approvable}")
            policy_run = ENG.run_engine(
                ctx, project_x,
                ENG.engine_input(ctx, policy_rows, policy_records,
                                 config=config))
            runs.append(policy_run)
            outcomes[approvable] = (
                ((ENG.plan_of(policy_run) or {}).get("validation")
                 or {}).get("result"), policy_run.get("exit_code"))
        if outcomes[True] == outcomes[False]:
            findings.append(
                f"scenario_coverage_policy.base_only_approvable NON e' LETTA: "
                f"true e false producono lo stesso esito {outcomes[True]!r}. "
                "La chiave e' dichiarata dallo schema di financial_config")
        if outcomes[True][0] == "FAIL":
            findings.append(
                f"base_only_approvable=true produce {outcomes[True]!r}: "
                "l'esito previsto e' approved_with_conditions, non un FAIL")
        if outcomes[False][0] != "FAIL" or outcomes[False][1] == 0:
            findings.append(
                f"base_only_approvable=false produce {outcomes[False]!r}: la "
                "policy dichiarata non ammette un piano base_only e il piano "
                "deve FALLIRE CHIUSO")
        # NEGATIVO -- con copertura PIENA i tre scenari SONO prodotti, e
        # nessuno di essi e' NOT_APPLICABLE.
        positive, _, _ = run_full(ctx, base, "c06-full")
        runs.append(positive)
        if len(produced_ids(positive)) != len(ENG.SCENARIO_IDS):
            findings.append(
                "caso POSITIVO: con copertura PIENA i tre scenari devono "
                f"essere prodotti; prodotti={produced_ids(positive)}")
        full_result = ((ENG.plan_of(positive) or {}).get("validation")
                       or {}).get("result")
        if severity.get(full_result, -1) > severity.get(result, -1):
            findings.append(
                f"severita' INCOERENTE: la copertura PIENA risulta "
                f"{full_result!r}, piu' severa della copertura NULLA "
                f"({result!r})")
        findings.extend(_base_only_metadata_claims(ctx, run))
    return findings, runs


#: L'affermazione FALSA da impedire: che la policy
#: `base_only_approvable` sia RIPORTATA in `calculation_metadata`. Non lo e', e
#: non deve diventarlo: la policy e' osservabile dal proprio EFFETTO. Il
#: presidio e' DELIMITATO -- una parola chiave e un vicinato di poche righe --
#: e NON un confronto sul testo integrale di un commento, che sarebbe fragile
#: a ogni riformulazione.
METADATA_CLAIM_KEY = "calculation_metadata"
METADATA_CLAIM_SUBJECTS = ("base_only", "policy LETTA")
METADATA_CLAIM_WINDOW = 3


def _base_only_metadata_claims(ctx, run):
    """L'affermazione «la policy e' riportata in `calculation_metadata`».

    Misura DUE fatti che devono restare coerenti fra loro:

    1.  `calculation_metadata` NON porta `base_only_approvable` -- e non deve
        portarla: aggiungere il campo renderebbe VERA l'affermazione invece di
        CORREGGERLA, e lo schema non prevede quel campo;
    2.  nessun COMMENTO del motore afferma il contrario.

    Il secondo e' un'asserzione di SORGENTE deliberatamente DELIMITATA: cerca
    la parola chiave `calculation_metadata` dentro un commento e, solo li',
    verifica che il vicinato non parli della policy `base_only`. Non confronta
    testi integrali di commento, cosi' che una riformulazione legittima non lo
    rompa e una riaffermazione del falso non gli sfugga.
    """
    findings = []
    metadata = ((ENG.plan_of(run) or {}).get("calculation_metadata")) or {}
    if "base_only_approvable" in metadata:
        findings.append(
            "calculation_metadata porta 'base_only_approvable': il campo NON "
            "e' previsto dallo schema, e aggiungerlo renderebbe "
            "vera un'affermazione invece di correggerla; chiavi="
            f"{sorted(metadata)}")
    source = Path(ctx["entry_point"]).read_text(encoding="utf-8")
    lines = source.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#") or METADATA_CLAIM_KEY not in stripped:
            continue
        window = " ".join(lines[max(0, index - METADATA_CLAIM_WINDOW):
                                index + METADATA_CLAIM_WINDOW + 1])
        subjects = [subject for subject in METADATA_CLAIM_SUBJECTS
                    if subject in window]
        if not subjects:
            continue
        if "NON e' riportat" in window or "neppure in" in window or \
                "NEPPURE in" in window:
            continue
        findings.append(
            f"validate_financial_engine.py:{index + 1}: un commento associa "
            f"la policy base_only a {METADATA_CLAIM_KEY!r} "
            f"(soggetti={subjects}) mentre calculation_metadata NON la porta: "
            f"e' un'inesattezza documentale; commento={stripped!r}")
    return findings


def c07(ctx):
    """`FS-C-07` `T-FIN-SENSITIVITY` -- un driver per volta, codice
    `sensitivity_multi_driver`.

    UN driver per volta, effetto ISOLATO e ATTRIBUIBILE. Un tornado
    multi-driver non soddisfa il contratto.
    """
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_scen_c07_") as base:
        base = Path(base)
        run, records, rows = run_full(ctx, base, "c07")
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        plan = ENG.plan_of(run) or {}
        steps = plan.get("sensitivity")
        if not steps:
            findings.append(
                "nessun passo di sensitivity emesso su copertura piena")
            return findings, runs
        for step in steps:
            moved = step.get("driver_id")
            if not moved:
                findings.append(f"passo di sensitivity senza driver_id: {step}")
                continue
            if isinstance(moved, (list, tuple)):
                findings.append(
                    f"passo di sensitivity che muove {len(moved)} driver "
                    f"({moved}): la sensitivity muove UN driver "
                    f"per volta, e il codice dovuto e' {AMB_W2_05}")
            if not step.get("scenario"):
                findings.append(
                    f"passo di sensitivity senza scenario: {step}: l'effetto "
                    "non e' attribuibile")
            if step.get("polarity") is None:
                findings.append(
                    f"passo di sensitivity senza polarita' per {moved}: il "
                    "delta non e' interpretabile")
        # Ogni passo nomina UN SOLO driver: la somma dei driver mossi per
        # scenario non supera il numero dei passi.
        for scenario_id in produced_ids(run):
            own = [step for step in steps if step.get("scenario") == scenario_id]
            names = [step.get("driver_id") for step in own]
            if len(names) != len(set(names)):
                findings.append(
                    f"scenario {scenario_id!r}: lo stesso driver compare in "
                    f"piu' passi: {names}")
        # Il caso nominale NON emette il codice: e' esercitato dal RED sotto.
        if AMB_W2_05 in run["observed"]:
            findings.append(
                f"{AMB_W2_05} presente sul caso nominale, dove ogni passo "
                "muove un solo driver")
        # Esclusione di falso positivo: il contratto fallisce anche se il
        # delta TOTALE fosse corretto -- cio' che si misura e' l'ATTRIBUZIONE.
        attributed = {step.get("driver_id") for step in steps}
        covered = {binding["driver_id"] for binding in rows
                   if binding["source_ref"] in records
                   and records[binding["source_ref"]].get("base_case")
                   is not None}
        if not attributed <= covered:
            findings.append(
                f"passi di sensitivity su driver privi di terna: "
                f"{sorted(attributed - covered)}")
    return findings, runs


def c19(ctx):
    """`FS-C-19` `T-FIN-ASSUMPTION-STATE-SCENARIOS` -- stato delle
    assunzioni propagato PER SCENARIO nella proiezione di governance.

    RED-1  uno scenario emette uno stato PIU' ALTO del minimo dei propri refs
    RED-2  gli scenari CONDIVIDONO un unico stato calcolato una volta sul base
    RED-3  uno scenario prodotto MANCA dalla proiezione, o un NOT_APPLICABLE
           porta uno stato PRESO IN PRESTITO
    RED-4  un campo di stato propagato e' INSERITO dentro `scenario_result`
    """
    findings = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="fin_scen_c19_") as base:
        base = Path(base)
        # La fixture porta stati DIVERSI per driver, altrimenti «minimo dei
        # propri refs» e «stato del base copiato» sarebbero indistinguibili.
        records = ENG.triplet_records(ctx)
        rows = ENG.base_rows(ctx, records)
        rows[1]["status"] = "confirmed"
        project, _ = ENG.make_project(ctx, base, fixture_id="F-1", name="c19")
        run = ENG.run_engine(ctx, project,
                             ENG.engine_input(ctx, rows, records))
        runs.append(run)
        if not run["available"]:
            return [run["reason"]], runs
        projection = ENG.projection_of(run) or {}
        scenarios = projection.get("scenarios")
        block = scenarios_of(run)
        produced = produced_ids(run)
        if not isinstance(scenarios, dict):
            return ["governance_projection.scenarios assente"], runs
        # RED-3 -- ogni scenario PRODOTTO ha la propria voce.
        missing = [sid for sid in produced if sid not in scenarios]
        if missing:
            findings.append(
                f"RED-3: scenari PRODOTTI e OMESSI dalla proiezione: {missing}")
        orphan = [sid for sid in scenarios if sid not in ENG.SCENARIO_IDS]
        if orphan:
            findings.append(
                f"RED-3: voci di proiezione prive dello scenario "
                f"corrispondente: {orphan}")
        status_by_driver = {}
        for driver in ((ENG.plan_of(run) or {}).get("driver_registry")
                       or {}).get("drivers") or []:
            status_by_driver[driver["driver_id"]] = driver["status"]
        seen = {}
        for scenario_id in sorted(scenarios):
            entry = scenarios[scenario_id]
            declared = entry.get("propagated_status")
            refs = entry.get("driver_refs") or []
            if declared not in STATUS_ORDER:
                findings.append(
                    f"scenarios[{scenario_id}]: propagated_status="
                    f"{declared!r} fuori dall'enumerazione chiusa")
                continue
            if scenario_id not in produced:
                # RED-3 -- uno scenario NOT_APPLICABLE non prende in prestito
                # lo stato di un altro: porta il FONDO dell'enumerazione.
                if refs:
                    findings.append(
                        f"RED-3: scenario {scenario_id!r} NOT_APPLICABLE con "
                        f"driver_refs={refs}: lo stato e' PRESO IN PRESTITO")
                if declared != "unresolved":
                    findings.append(
                        f"RED-3: scenario {scenario_id!r} NOT_APPLICABLE con "
                        f"propagated_status={declared!r}: la politica "
                        "dichiarata e' il fondo dell'enumerazione chiusa")
                continue
            # RED-1 -- il minimo dei PROPRI riferimenti, mai uno stato piu'
            # alto.
            minimum = min((status_by_driver.get(ref, "unresolved")
                           for ref in refs), key=STATUS_ORDER.index) \
                if refs else "unresolved"
            if declared != minimum:
                lowering = [ref for ref in refs
                            if status_by_driver.get(ref) == minimum]
                findings.append(
                    f"RED-1: scenario {scenario_id!r}: propagated_status="
                    f"{declared!r} invece del MINIMO {minimum!r} dei PROPRI "
                    f"driver_refs; i DRV che lo abbassano sono {lowering}")
            own = (block.get(scenario_id) or {}).get("driver_refs") or []
            if sorted(refs) != sorted(own):
                findings.append(
                    f"scenario {scenario_id!r}: driver_refs della proiezione "
                    f"{sorted(refs)} diversi da quelli dello scenario "
                    f"{sorted(own)}")
            seen[scenario_id] = (declared, tuple(sorted(refs)))
        # Il contratto fallisce ANCHE con i tre `output_checksums` DISTINTI:
        # uno scenario puo' essere numericamente isolato e governativamente
        # copiato. La distinzione numerica e' quindi verificata, ma NON e'
        # cio' che soddisfa il contratto.
        if len(seen) > 1:
            checksums = {checksums_of(run).get(sid) for sid in seen}
            if len(checksums) != len(seen):
                findings.append(
                    f"i checksum degli scenari prodotti non sono distinti: "
                    f"{checksums}")
        # RED-4 -- nessun campo di stato propagato dentro `scenario_result`.
        for scenario_id in ENG.SCENARIO_IDS:
            entry = block.get(scenario_id) or {}
            ENG.validate_ref(ctx, entry, "#/$defs/scenario_result",
                             f"scenario_result[{scenario_id}]", findings)
            for key in ("propagated_status", "driver_status",
                        "assumption_status"):
                if key in entry:
                    findings.append(
                        f"RED-4: scenario {scenario_id!r}: il campo {key!r} e' "
                        "stato INSERITO dentro scenario_result: e' un delta di "
                        "schema mascherato. Il RED vale "
                        "ANCHE se il valore scritto e' corretto")
        # ---- VARIANTE A COPERTURA 0 ----------------------------------------
        #
        # E' il caso che DISCRIMINA lo stato copiato dal base. Con copertura
        # NULLA solo `base` e' prodotto: un'implementazione che calcolasse lo
        # stato UNA VOLTA sul base e lo COPIASSE darebbe a `downside` e
        # `upside` lo stato del base, mentre uno scenario NOT_APPLICABLE porta
        # il fondo dell'enumerazione e nessun riferimento preso in prestito. Su copertura PIENA i tre scenari
        # condividono lo stesso insieme di driver e i due comportamenti sono
        # OSSERVAZIONALMENTE IDENTICI: senza questa variante il contratto non
        # potrebbe distinguerli.
        bare = ENG.base_records(ctx)
        bare_rows = ENG.base_rows(ctx, bare)
        project2, _ = ENG.make_project(ctx, base, fixture_id="F-3",
                                       name="c19-nocover")
        zero = ENG.run_engine(ctx, project2,
                              ENG.engine_input(ctx, bare_rows, bare))
        runs.append(zero)
        zero_projection = (ENG.projection_of(zero) or {}).get("scenarios") or {}
        zero_produced = produced_ids(zero)
        if zero_produced != ["base"]:
            findings.append(
                f"variante a copertura 0: scenari prodotti {zero_produced} "
                "invece del solo 'base'")
        base_status = (zero_projection.get("base") or {}).get(
            "propagated_status")
        for scenario_id in ("downside", "upside"):
            entry = zero_projection.get(scenario_id)
            if entry is None:
                findings.append(
                    f"RED-3: variante a copertura 0: scenario {scenario_id!r} "
                    "OMESSO dalla proiezione: gli scenari NOT_APPLICABLE sono "
                    "trattati in modo DETERMINISTICO e DICHIARATO, mai omessi "
                    "in silenzio")
                continue
            if entry.get("driver_refs"):
                findings.append(
                    f"RED-2/RED-3: variante a copertura 0: {scenario_id!r} "
                    f"porta driver_refs={entry.get('driver_refs')} pur non "
                    "essendo prodotto: i riferimenti sono PRESI IN PRESTITO "
                    "dal base")
            if entry.get("propagated_status") == base_status and \
                    base_status != "unresolved":
                findings.append(
                    f"RED-2: variante a copertura 0: {scenario_id!r} porta lo "
                    f"stato del base ({base_status!r}) pur non essendo "
                    "prodotto: lo stato e' stato calcolato UNA VOLTA sul base "
                    "e COPIATO")
    return findings, runs


# --------------------------------------------------------------------------
# Registro dei contratti
# --------------------------------------------------------------------------

CONTRACTS = [
    {"id": "FS-C-01", "name": "T-FIN-SCENARIO-ISOLATION", "fn": c01,
     "rule": "il selettore di scenario governa la presentazione, mai il "
             "calcolo",
     "fixture": "F-1",
     "red": "il selettore attivo cambia i risultati degli altri due scenari",
     "expected_codes": (),
     "attribution": "output_checksums dei tre scenari INVARIANTI al variare "
                    "del selettore",
     "mutation": "selettore di scenario che entra nel calcolo"},
    {"id": "FS-C-02", "name": "T-FIN-NO-CROSS-LEAK", "fn": c02,
     "rule": "ogni scenario legge SOLO il proprio set risolto",
     "fixture": "F-1",
     "red": "il motore downside legge un valore base",
     "expected_codes": (),
     "attribution": "DRV-* e scenario della lettura errata NOMINATI",
     "mutation": "scenario che legge il valore di un altro scenario"},
    {"id": "FS-C-03", "name": "T-FIN-SCENARIO-POLARITY", "fn": c03,
     "rule": "cost_like: downside ALTO; revenue_like: downside BASSO; "
             "timing_like: downside RITARDATO",
     "fixture": "F-1; F-1 con headcount timing_like (terna di PERIODI); F-1 "
                "con estremo di timing FUORI ORIZZONTE",
     "red": "churn con polarita' revenue_like; timing_like trattato come "
            "INVARIANTE mentre il driver conta come coperto",
     "expected_codes": (),
     "attribution": "DRV-* del churn e polarita' applicata NOMINATI; per il "
                    "timing, i tre totali di scenario e il DRV-* scoperto",
     "mutation": "polarita' ignorata o applicata a rovescio"},
    {"id": "FS-C-04", "name": "T-FIN-SCENARIO-RECON", "fn": c04,
     "rule": "una riconciliazione INDIPENDENTE per ogni scenario prodotto",
     "fixture": "F-1",
     "red": "riconciliazione eseguita solo sul base",
     "expected_codes": (),
     "attribution": "rec_id + scenario per CIASCUNA",
     "mutation": "esito di scenario copiato da un altro"},
    {"id": "FS-C-05", "name": "T-FIN-SCENARIO-COVERAGE", "fn": c05,
     "rule": "copertura parziale dichiarata con i driver scoperti NOMINATI",
     "fixture": "F-2",
     "red": "copertura parziale dichiarata PIENA",
     "expected_codes": (),
     "attribution": "ogni DRV-* privo di terna NOMINATO",
     "mutation": "copertura parziale riportata come piena"},
    {"id": "FS-C-06", "name": "T-FIN-SCENARIO-COVERAGE-GATE", "fn": c06,
     "rule": "copertura nulla: solo Base, esito approved_with_conditions o "
             "FAIL secondo base_only_approvable",
     "fixture": "F-3; F-2 (parziale); F-3 con base_only_approvable true e "
                "false",
     "red": "tre serie identiche emesse con etichette Downside/Upside "
            "differenziate; base_only che esce PASS; base_only meno severo "
            "della copertura parziale; base_only_approvable NON letta",
     "expected_codes": (),
     "attribution": "scenario_result.status NOT_APPLICABLE con "
                    "not_applicable_reason; COND-* proposta con "
                    "due_before_stage; validation.result confrontato fra "
                    "copertura piena, parziale e nulla",
     "mutation": "tre serie identiche pubblicate come tre scenari"},
    {"id": "FS-C-07", "name": "T-FIN-SENSITIVITY", "fn": c07,
     "rule": "sensitivity: UN driver per volta, effetto attribuibile",
     "fixture": "F-1",
     "red": "sensitivity che muove PIU' driver insieme",
     "expected_codes": (),
     "attribution": "DRV-* mosso e delta risultante NOMINATI",
     "mutation": "passo di sensitivity che muove piu' driver"},
    {"id": "FS-C-19", "name": "T-FIN-ASSUMPTION-STATE-SCENARIOS",
     "fn": c19,
     "rule": "stato propagato per scenario = minimo dei PROPRI driver_refs",
     "fixture": "F-1 + variante a copertura 0",
     "red": "RED-1 stato piu' alto del minimo; RED-2 stato del base COPIATO; "
            "RED-3 scenario mancante o stato PRESO IN PRESTITO; RED-4 campo "
            "di stato dentro scenario_result",
     "expected_codes": (),
     "attribution": "scenario + stato propagato + i driver_refs che lo "
                    "determinano, per CIASCUNO scenario prodotto",
     "mutation": "stato calcolato una volta sul base e copiato"},
]

CONTRACT_IDS = tuple(entry["id"] for entry in CONTRACTS)


# --------------------------------------------------------------------------
# Esecuzione
# --------------------------------------------------------------------------


def run_one(ctx, contract):
    try:
        findings, runs = contract["fn"](ctx)
    except (KeyError, TypeError, ValueError, IndexError, StopIteration,
            decimal.InvalidOperation) as exc:
        findings = [f"errore di valutazione del contratto: {exc!r}"]
        runs = []
    observed = set()
    for run in runs or ():
        observed |= set(run.get("observed") or ())
    return {"contract": contract, "red": bool(findings), "findings": findings,
            "observed": sorted(observed), "runs": runs or []}


def specificity(results):
    """Misura di specificita': su quanti report osservati l'insieme
    atteso di ciascun contratto sarebbe soddisfatto."""
    reports = []
    for result in results:
        for run in result["runs"]:
            if run.get("report") is not None:
                reports.append(set(run.get("observed") or ()))
    measures = {}
    for result in results:
        expected = set(result["contract"]["expected_codes"])
        if not expected:
            measures[result["contract"]["id"]] = (0, len(reports))
            continue
        count = sum(1 for observed in reports if expected <= observed)
        measures[result["contract"]["id"]] = (count, len(reports))
    return measures


def format_line(result, measure):
    contract = result["contract"]
    count, total = measure
    return (
        "{state:<5} {cid:<12} {name:<38} observed={observed} "
        "specificity={count}/{total} attribution={attr} | reason={reason}"
        .format(state="RED" if result["red"] else "GREEN",
                cid=contract["id"], name=contract["name"],
                observed=result["observed"] or "-", count=count, total=total,
                attr=contract["attribution"],
                reason="; ".join(result["findings"]) or "-"))


def main(argv=None):
    global ENG
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(
        prog="test_fin_scenarios.py", add_help=True,
        description="Contratti di scenario del motore finanziario.")
    parser.add_argument("--root", required=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--contract", help="esegue un solo contratto")
    mode.add_argument("--all", action="store_true",
                      help="esegue tutti i contratti (default)")
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
    print("SUMMARY: {total} contratti di scenario, {red} RED, {green} GREEN"
          .format(total=len(results), red=len(red),
                  green=len(results) - len(red)))
    if red:
        return EXIT_RED
    print("PASS: T-FIN-SCENARIOS otto contratti di scenario del motore "
          "finanziario")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
