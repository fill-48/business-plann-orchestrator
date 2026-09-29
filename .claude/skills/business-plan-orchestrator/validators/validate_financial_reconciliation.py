#!/usr/bin/env python3
"""validate_financial_reconciliation — scenari e riconciliazione dello Stage 10.

Validator di pipeline interna dello Stage 10: lavora sul payload intermedio
del motore e non entra in `egress_required` (al confine di egress il
Transaction Manager invoca `validate_financial_output`).

CHE COSA VALIDA, E CHE COSA NON RICALCOLA
-----------------------------------------
Questo validator NON e' un secondo motore e NON produce numeri: la fonte dei
numeri resta UNA SOLA, ed e' il payload intermedio prodotto da
`validate_financial_engine`. Qui si VERIFICA che quel payload rispetti i
contratti di scenario e di riconciliazione:

    1  ogni riconciliazione DOVUTA e' RIPORTATA -- anche quando passa. Un
       controllo che non compare nel report equivale a un controllo non
       eseguito;
    2  ogni riconciliazione porta formula, stato, severita', tolleranza e
       unita' di tolleranza, e la soglia APPLICATA coincide con quella
       dichiarata in `config/enforcement-config.json`;
    3  una riconciliazione `FAIL` in fase `egress` produce exit != 0, quindi
       NESSUNA scrittura canonica;
    4  i tre scenari sono TRE MOTORI INDIPENDENTI, non tre etichette: i
       checksum degli scenari PRODOTTI sono DISTINTI, e con copertura NULLA
       `downside` e `upside` sono `NOT_APPLICABLE` -- non prodotti e non
       etichettati;
    5  la copertura e' riportata NOMINALMENTE, con l'elenco dei driver privi
       di terna, mai riassorbita in un rapporto numerico;
    6  nessuna chiave dello Stage 11 compare nell'output, e il fabbisogno
       resta un PROFILO TEMPORALE.

CHE COSA NON FA
---------------
Non scrive alcun path canonico, non crea alcuna cartella
`10_financial-plan/`, non muta alcun progetto, non esegue ne' innesca alcuna
ricerca esterna e non produce l'output canonico dello Stage 10 (che e'
composto dal costruttore canonico e validato da `validate_financial_output`).
Non canonicalizza alcuno stato propagato per modulo o per scenario.

SUPERFICIE CLI
--------------
    --project           directory del progetto, letta in SOLA LETTURA
    --stage             10_financial-plan
    --phase             egress | impact
    --candidate         workspace candidate (obbligatorio in fase egress)
    --engine-payload    <path>|-   payload intermedio prodotto dal motore

EXIT CODE — semantica di `_framework.py`, INVARIATA
---------------------------------------------------
    0  nessun errore        1  contratto violato
    2  errore d'uso         3  stato canonico non valido

DISCIPLINA DELLE COSTANTI
-------------------------
Nessun valore economico vive qui. Le soglie sono LETTE da
`config/enforcement-config.json`; la tassonomia dei codici, dei `rec_id` e
degli scenari e' importata dal motore, cosi' che una divergenza fra i due sia
impossibile per costruzione. Nessun codice di errore e' coniato qui.
"""
import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

import _framework as fw
import validate_financial_engine as engine

VALIDATOR_NAME = "validate_financial_reconciliation"

STAGE10 = engine.STAGE10
SUPPORTED_PHASES = engine.SUPPORTED_PHASES

#: Le UNDICI riconciliazioni che il motore deve riportare nel payload
#: intermedio. `REC-09` (copertura delle milestone) non e' prodotta dal motore:
#: la pubblica il costruttore canonico come `NOT_APPLICABLE`. `REC-07` e
#: `REC-08` sono opzionali e non prodotte; `REC-10` riguarda lo Stage 11 e non
#: e' rappresentata nel piano dello Stage 10.
REQUIRED_RECONCILIATIONS = (
    engine.REC_REVENUE_DETAIL, engine.REC_COGS_DETAIL,
    engine.REC_PAYROLL_IDENTITY, engine.REC_OPEX_DETAIL,
    engine.REC_CASH_ROLL_FORWARD, engine.REC_FLOW_QUOTA,
    engine.REC_STOCK_LEVEL, engine.REC_PNL_CASH_BRIDGE,
    engine.REC_SCENARIO_DETAIL, engine.REC_CATEGORY_TOTAL,
    engine.REC_BREAK_EVEN,
)

#: Le SETTE chiavi che lo Stage 11 possiede e lo Stage 10 no.
STAGE11_FORBIDDEN_KEYS = ("funding_ask", "instrument", "valuation",
                          "round_size", "ownership", "dilution", "terms")

#: Chiave che il payload intermedio del motore non deve mai portare: le
#: categorie candidate di uso dei proventi sono composte soltanto dal
#: costruttore canonico, nel documento `structured-output.json`.
DEFERRED_KEY = "use_of_proceeds_candidates"

#: `check_id` strutturali di questo validator. La regola vieta di coniare
#: nuovi CODICI DI ERRORE, non identificatori di check.
CHECK_PAYLOAD = "financial_reconciliation_input"
CHECK_REPORTED = "reconciliation_reported"
CHECK_SCENARIO_ISOLATION = "scenario_isolation"
CHECK_COVERAGE = "scenario_coverage"
CHECK_STAGE11 = "stage11_boundary"


def read_payload(args, raw):
    """Legge il payload intermedio del motore. Non lo ricalcola."""
    if raw in (None, ""):
        raise fw.ValidatorUsageError(
            "--engine-payload obbligatorio: questo validator VERIFICA il "
            "payload del motore e non lo ricalcola")
    if raw == "-":
        text = sys.stdin.read()
        label = "<stdin>"
    else:
        path = Path(raw).expanduser()
        if not path.is_file():
            raise fw.ValidatorUsageError(
                f"--engine-payload non e' un file leggibile: {path}")
        text = path.read_text(encoding="utf-8")
        label = str(path)
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise fw.ValidatorUsageError(
            f"--engine-payload non e' JSON valido ({label}): {exc}")
    if not isinstance(doc, dict):
        raise fw.ValidatorUsageError(
            f"--engine-payload non e' un oggetto JSON ({label})")
    doc["_source_label"] = label
    return doc


def collect_keys(node, found):
    if isinstance(node, dict):
        found.update(node.keys())
        for value in node.values():
            collect_keys(value, found)
    elif isinstance(node, list):
        for value in node:
            collect_keys(value, found)
    return found


def check_reconciliations(payload, ledger, tolerances, report):
    """Ogni riconciliazione dovuta e' RIPORTATA, sempre, anche quando passa."""
    recon = payload.get("reconciliations") or {}
    for rec_id in REQUIRED_RECONCILIATIONS:
        entry = recon.get(rec_id)
        if not isinstance(entry, dict):
            report.add_error(
                rec_id, ref=rec_id,
                message=(f"{rec_id} ASSENTE dal payload: un controllo "
                         "che non compare nel report equivale a un controllo "
                         "NON ESEGUITO"),
                expected="la riconciliazione riportata anche quando passa",
                actual="assente")
            continue
        missing = [field for field in
                   ("rec_id", "formula", "status", "severity", "tolerance",
                    "tolerance_unit") if not entry.get(field)]
        if missing:
            report.add_error(
                rec_id, ref=rec_id,
                message=(f"{rec_id}: campi obbligatori assenti {missing}: la "
                         "riconciliazione va riportata con formula, valori, "
                         "residuo e tolleranza APPLICATA"),
                expected="rec_id, formula, status, severity, tolerance, "
                         "tolerance_unit",
                actual=f"mancanti: {missing}")
            continue
        if entry.get("rec_id") != rec_id:
            report.add_error(
                rec_id, ref=rec_id,
                message=(f"{rec_id}: rec_id={entry.get('rec_id')!r} non "
                         "attribuito alla propria chiave"),
                expected=rec_id, actual=entry.get("rec_id"))
        unit = entry.get("tolerance_unit")
        key = "count" if unit == "FTE" else unit
        declared = tolerances.get(key)
        applied = (ledger or {}).get(rec_id)
        if declared is None:
            report.add_error(
                rec_id, ref=rec_id,
                message=(f"{rec_id}: nessuna soglia {key!r} in "
                         "enforcement-config.json: la tolleranza non e' "
                         "reinventata qui"),
                expected="una soglia dichiarata", actual=repr(unit))
        elif applied is None:
            report.add_error(
                rec_id, ref=rec_id,
                message=(f"{rec_id}: soglia APPLICATA non riportata: la sola "
                         "presenza della stringa `tolerance` non dimostra che "
                         "lo stesso valore parsato sia quello usato dal "
                         "confronto bersaglio"),
                expected="la soglia applicata nel tolerance_ledger",
                actual="assente")
        elif Decimal(str(applied)) != Decimal(str(declared)):
            report.add_error(
                rec_id, ref=rec_id,
                message=(f"{rec_id}: soglia applicata {applied!r} diversa da "
                         f"enforcement-config.tolerances[{key!r}]="
                         f"{declared!r}"),
                expected=str(declared), actual=str(applied))
        status = entry.get("status")
        report.add_check(
            CHECK_REPORTED, "PASS" if status != "FAIL" else "FAIL",
            affected_refs=[rec_id], expected=entry.get("expected"),
            actual=entry.get("actual"), residual=entry.get("residual"),
            tolerance=entry.get("tolerance"), message=entry.get("formula"))
        if status == "FAIL":
            report.add_error(
                rec_id, ref=rec_id,
                message=(f"{rec_id} violata: {entry.get('formula')}; "
                         f"residuo {entry.get('residual')} oltre la tolleranza "
                         f"{entry.get('tolerance')}"),
                expected=entry.get("expected"), actual=entry.get("actual"))


def check_scenarios(payload, report):
    """Scenari: tre motori INDIPENDENTI, non tre etichette."""
    results = payload.get("results") or {}
    scenarios = results.get("scenarios") or {}
    if not scenarios:
        report.add_error(
            engine.CODE_SCENARIO_IDENTICAL, ref="results.scenarios",
            message=("results.scenarios assente: i tre scenari sono contenuto "
                     "obbligatorio dello Stage 10 e la loro assenza non e' una "
                     "semplificazione"),
            expected="coverage, base, downside, upside", actual="assente")
        return
    coverage = scenarios.get("coverage") or {}
    level = coverage.get("level")
    uncovered = coverage.get("uncovered_driver_refs")
    if level not in (engine.COVERAGE_FULL, engine.COVERAGE_PARTIAL,
                     engine.COVERAGE_NONE):
        report.add_error(
            engine.CODE_SCENARIO_IDENTICAL, ref="results.scenarios.coverage",
            message=(f"coverage.level={level!r} fuori dai tre livelli di "
                     "copertura di scenario"),
            expected="full | partial | none", actual=repr(level))
    if uncovered is None:
        report.add_error(
            engine.CODE_SCENARIO_IDENTICAL, ref="results.scenarios.coverage",
            message=("coverage.uncovered_driver_refs assente: la copertura e' "
                     "riportata NOMINALMENTE e non e' mai riassorbita in un "
                     "rapporto numerico"),
            expected="l'elenco dei DRV-* privi di terna", actual="assente")
    elif level == engine.COVERAGE_PARTIAL and not uncovered:
        report.add_error(
            engine.CODE_SCENARIO_IDENTICAL, ref="results.scenarios.coverage",
            message=("copertura PARZIALE con elenco VUOTO: `level: partial` "
                     "senza i driver NOMINATI non e' una copertura riportata"),
            expected="almeno un DRV-* nominato", actual="[]")
    report.add_check(
        CHECK_COVERAGE,
        "PASS" if level == engine.COVERAGE_FULL else "WARNING",
        affected_refs=uncovered or [], expected=coverage.get("threshold"),
        actual=coverage.get("ratio"),
        message=(f"copertura di scenario {level!r} misurata sui SOLI ruoli "
                 "richiesti dal profilo attivo"))

    produced, checksums = [], {}
    for scenario_id in engine.SCENARIO_IDS:
        entry = scenarios.get(scenario_id)
        if not isinstance(entry, dict):
            report.add_error(
                engine.CODE_SCENARIO_IDENTICAL, ref=scenario_id,
                message=(f"scenario {scenario_id!r} assente da "
                         "results.scenarios: uno scenario non prodotto e' "
                         "DICHIARATO NOT_APPLICABLE, mai omesso in silenzio"),
                expected="uno scenario_result", actual="assente")
            continue
        if entry.get("status") == "NOT_APPLICABLE":
            if not entry.get("not_applicable_reason"):
                report.add_error(
                    engine.CODE_SCENARIO_IDENTICAL, ref=scenario_id,
                    message=(f"scenario {scenario_id!r} NOT_APPLICABLE senza "
                             "not_applicable_reason: l'omissione dev'essere "
                             "DICHIARATA e VISIBILE"),
                    expected="una motivazione nominata", actual="assente")
            for forbidden in ("series", "summary", "output_checksum"):
                if entry.get(forbidden) is not None:
                    report.add_error(
                        engine.CODE_SCENARIO_IDENTICAL, ref=scenario_id,
                        message=(f"scenario {scenario_id!r} porta "
                                 f"{forbidden!r} pur essendo NOT_APPLICABLE: "
                                 "e' ETICHETTATO senza input differenziati, "
                                 "che e' una conformita' solo nominale"),
                        expected="nessuna serie ne' sintesi ne' checksum",
                        actual=forbidden)
            continue
        produced.append(scenario_id)
        checksums[scenario_id] = entry.get("output_checksum")

    if level == engine.COVERAGE_NONE and produced != ["base"]:
        report.add_error(
            engine.CODE_SCENARIO_IDENTICAL, ref=",".join(produced),
            message=("con copertura NULLA l'output contiene il SOLO Base: "
                     "Downside e Upside non sono prodotti ne' etichettati, "
                     "perche' tre serie identiche con tre etichette diverse "
                     "sono un difetto, non una semplificazione"),
            expected="['base']", actual=str(produced))
    if len(produced) > 1 and len(set(checksums.values())) != len(produced):
        report.add_error(
            engine.CODE_SCENARIO_IDENTICAL, ref=",".join(produced),
            message=("gli scenari prodotti portano lo STESSO checksum: sono "
                     "tre etichette, non tre motori indipendenti"),
            expected="un checksum DISTINTO per scenario prodotto",
            actual=str(sorted({value for value in checksums.values()})))
    report.add_check(
        CHECK_SCENARIO_ISOLATION,
        "PASS" if len(set(checksums.values())) == len(produced) else "FAIL",
        affected_refs=produced,
        message=("ogni scenario prodotto porta il PROPRIO risultato, "
                 "calcolato sul PROPRIO set risolto"))

    # Sensitivity: UN driver per volta, altrimenti l'effetto non e'
    # attribuibile.
    for step in payload.get("sensitivity") or []:
        moved = step.get("driver_id")
        if isinstance(moved, (list, tuple)) and len(moved) != 1:
            report.add_error(
                engine.CODE_SENSITIVITY_MULTI, ref=str(moved),
                message=("un passo di sensitivity muove piu' di un driver: "
                         "l'effetto non e' attribuibile al singolo driver"),
                expected="un driver per volta", actual=str(moved))


def check_stage11_boundary(envelope, payload, report):
    """Confine con lo Stage 11: lo Stage 10 si ferma al FABBISOGNO."""
    keys = collect_keys(envelope, set())
    offenders = [key for key in STAGE11_FORBIDDEN_KEYS if key in keys]
    for key in offenders:
        report.add_error(
            engine.CODE_GAP_AS_SOURCE, ref=key,
            message=(f"chiave di Stage 11 {key!r} presente nell'output dello "
                     "Stage 10: valutazione, strumento, termini e importo "
                     "richiesto restano fuori senza eccezioni"),
            expected="nessuna chiave di Stage 11", actual=key)
    if DEFERRED_KEY in keys:
        report.add_error(
            engine.CODE_GAP_AS_SOURCE, ref=DEFERRED_KEY,
            message=(f"{DEFERRED_KEY} presente nel payload intermedio del "
                     "motore: e' composto soltanto dal costruttore canonico, "
                     "e le categorie candidate non sono "
                     "mai allocate ne' sommate a un importo richiesto"),
            expected="nessuna candidatura di impiego", actual=DEFERRED_KEY)
    gap = ((payload.get("results") or {}).get("modules") or {}).get(
        "funding_gap") or {}
    need = gap.get("series") or {}
    if gap and len(need) <= 1:
        report.add_error(
            engine.CODE_GAP_AS_SOURCE, ref="funding_gap",
            message=("financial_need e' collassato in uno scalare: e' "
                     "definito come PROFILO TEMPORALE del fabbisogno residuo, e "
                     "un fabbisogno non definito e' il punto naturale in cui "
                     "una richiesta di funding si insinua"),
            expected="una serie per periodo", actual=f"{len(need)} valori")
    report.add_check(
        CHECK_STAGE11, "FAIL" if offenders else "PASS",
        affected_refs=offenders,
        message=("confine con lo Stage 11: lo Stage 10 produce il PROFILO "
                 "TEMPORALE del fabbisogno, mai una richiesta di funding"))


def check_reconciliation(args, config, state, report, envelope):
    payload = envelope.get("financial_payload")
    if not isinstance(payload, dict):
        raise fw.ValidatorUsageError(
            "--engine-payload privo di `financial_payload`: non e' il payload "
            "intermedio prodotto da validate_financial_engine")
    ledger = envelope.get("tolerance_ledger") or {}
    # Le soglie sono LETTE da `config/enforcement-config.json` attraverso lo
    # STESSO accessore del motore: due letture divergenti sarebbero due
    # verita' sulla stessa soglia.
    tolerances = engine.tolerance_table()
    report.add_check(
        CHECK_PAYLOAD, "PASS",
        expected="il payload intermedio di validate_financial_engine",
        actual=f"milestone {envelope.get('milestone')!r} da "
               f"{envelope.get('_source_label')}",
        message=(f"payload ricevuto in fase {args.phase}; questo validator "
                 "VERIFICA e non ricalcola"))
    check_reconciliations(payload, ledger, tolerances, report)
    check_scenarios(payload, report)
    check_stage11_boundary(envelope, payload, report)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    pre = argparse.ArgumentParser(prog=VALIDATOR_NAME, add_help=False)
    pre.add_argument("--engine-payload")
    try:
        known, rest = pre.parse_known_args(argv)
    except SystemExit:
        print(f"{VALIDATOR_NAME}: argomenti CLI non validi", file=sys.stderr)
        return fw.EXIT_USAGE
    engine_payload = known.engine_payload

    def check_fn(args, config, state, report):
        if args.stage != STAGE10:
            raise fw.ValidatorUsageError(
                f"stage non pertinente a {VALIDATOR_NAME}: {args.stage} "
                f"(atteso {STAGE10})")
        if args.phase not in SUPPORTED_PHASES:
            raise fw.ValidatorUsageError(
                f"--phase non ammessa per {VALIDATOR_NAME}: {args.phase} "
                f"(ammesse: {SUPPORTED_PHASES})")
        envelope = read_payload(args, engine_payload)
        check_reconciliation(args, config, state, report, envelope)

    fw.run_validator(VALIDATOR_NAME, check_fn, rest)
    return fw.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
