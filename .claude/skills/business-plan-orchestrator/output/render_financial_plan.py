#!/usr/bin/env python3
"""Renderer del CAPITOLO `financial-plan.md` dello Stage 10.

Rende la verita' canonica al PRIMO dei due lettori umani — un lettore di
business plan — senza che possa alterarla. Il capitolo e' una RESA, non
un'analisi indipendente.

REGOLA STRUTTURALE — NESSUN RICALCOLO DI POLICY
-----------------------------------------------
Questo modulo NON implementa alcuna politica finanziaria: nessuna soglia,
nessuna conversione di frequenza, nessuna regola di timing, nessuna polarita'
di scenario, nessun arrotondamento, nessuna regola di copertura, di prontezza
o di mappatura di stato. Sono TUTTE policy e vivono TUTTE nel motore
finanziario.

La disciplina e' resa MISURABILE adottando alla lettera il precedente del
costruttore canonico (`build_canonical_output.py`): il sorgente NON contiene
alcun operatore
aritmetico (`+ - * / // % ** @`), a nessuna profondita', e nessuna delle
funzioni di aggregazione o conversione numerica `sum, round, abs, pow,
divmod, Decimal, float, complex, int`. Il prezzo DICHIARATO e' che le stringhe
si compongono con f-string e `str.join` e mai con `+`, e che l'ordinamento dei
valori decimali usa una CHIAVE PURAMENTE TESTUALE (`decimal_key`).

Ne segue la proprieta' che il capitolo deve avere: OGNI numero mostrato e' una
FOGLIA CANONICA copiata VERBATIM, mai un valore ricostruito. In particolare
NESSUN ARROTONDAMENTO e' applicato alla resa: l'arrotondamento e' una policy e
appartiene al motore. La colonna «Path canonico» rende la verifica puntuale.

INSIEME DI INGRESSO DICHIARATO E CHIUSO
---------------------------------------
AUTORITATIVO PER OGNI NUMERO CALCOLATO
    <project>/10_financial-plan/structured-output.json   e NIENT'ALTRO

IN SOLA LETTURA, SOLO per gli ATTRIBUTI DI INPUT GOVERNATO raggiungibili da
`driver_entry.source_ref` + `source_path`
    shared/assumptions-register.json
    shared/evidence-register.json
    shared/source-register.json

Ogni lettura e' VERIFICATA contro `driver_entry.source_record_hash`; una
divergenza e' `derived_artifact_stale` -> FAIL, MAI un valore usato. Nessun
calcolo e' eseguito su questi registri. Nessun valore letto qui compare in una
tabella di RISULTATO: compare SOLO nelle righe di ASSUNZIONE. L'insieme e'
CHIUSO: un QUARTO registro e' un FAIL, non un'estensione. Nessuna scrittura a
monte, di alcun tipo, in alcuna direzione.

CONFINE DI SCRITTURA
--------------------
Scrive ESCLUSIVAMENTE `<project>/10_financial-plan/financial-plan.md`. Un
progetto collocato dentro la directory della skill e' RESPINTO prima di ogni
I/O (`real_project_write_forbidden`), e NESSUN path canonico e' mai scritto:
il canonico resta BYTE-IDENTICO.

Exit code:  0 capitolo prodotto · 1 rifiuto attribuito · 2 errore d'uso.
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path

RENDERER_NAME = "render_financial_plan"
STAGE10 = "10_financial-plan"
CHAPTER_NAME = "financial-plan.md"
CANONICAL_NAME = "structured-output.json"
STYLE_TOKENS_NAME = "style_tokens.json"

SKILL_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = Path(__file__).resolve().parent
STYLE_TOKENS_PATH = OUTPUT_DIR.joinpath(STYLE_TOKENS_NAME)

#: INSIEME DI INGRESSO CHIUSO dei registri governati. TRE voci,
#: e nessuna quarta: aggiungerne una e' un FAIL, non un'estensione.
INPUT_SET = (
    "shared/assumptions-register.json",
    "shared/evidence-register.json",
    "shared/source-register.json",
)

#: I QUINDICI `module_id` e i TRE scenari, lo STESSO insieme del canonico.
MODULE_IDS = (
    "revenue", "cogs", "gross_margin", "headcount", "payroll", "opex", "pnl",
    "cash_flow", "balance_sheet", "runway", "cash_buffer", "break_even",
    "funding_gap", "milestone_coverage", "kpi",
)
SCENARIO_IDS = ("base", "downside", "upside")

#: Moduli le cui serie sono la proiezione dello scenario BASE. La coincidenza
#: e' VERIFICATA a ogni resa, non assunta: una divergenza e' un rifiuto
#: attribuito, mai un'etichetta di scenario sbagliata in silenzio.
BASE_PROJECTED_MODULES = ("revenue", "cogs", "gross_margin", "pnl",
                          "cash_flow", "funding_gap")

CODE_STALE = "derived_artifact_stale"
CODE_INCOMPLETE = "derived_artifact_incomplete"
CODE_MISMATCH = "derived_artifact_numeric_mismatch"
CODE_REAL_PROJECT = "real_project_write_forbidden"
CODE_INPUT_SET = "derived_input_set_violation"
CODE_CANONICAL = "canonical_document_invalid"

UNDECLARED = "NON DICHIARATA"
NOT_APPLICABLE = "NOT_APPLICABLE"
ALL_SCENARIOS = "tutti"

#: Complemento decimale usato dalla CHIAVE DI ORDINAMENTO puramente testuale.
DIGIT_COMPLEMENT = {"0": "9", "1": "8", "2": "7", "3": "6", "4": "5",
                    "5": "4", "6": "3", "7": "2", "8": "1", "9": "0",
                    ".": "."}
KEY_FRACTION_WIDTH = 48
KEY_LENGTH_WIDTH = 6
PERIOD_KEY_WIDTH = 8

NUMERIC_RE = re.compile(r"^[+-]?(?:[0-9]+)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")


class RenderRefusal(Exception):
    """Rifiuto ATTRIBUITO: codice, riferimento e messaggio (exit 1)."""

    def __init__(self, code, ref, message):
        super().__init__(message)
        self.code = code
        self.ref = ref
        self.message = message


class RenderUsageError(Exception):
    """Errore di invocazione del renderer (exit 2)."""


# --------------------------------------------------------------------------
# Primitive CONDIVISE — una sola sede, nessuna duplicazione
# --------------------------------------------------------------------------
#
# `export_financial_model.py` e `derived_consistency.py` importano
# da qui `atomic_write`, `decimal_key`, `period_key`, `load_canonical`,
# `read_governed_inputs` e `INPUT_SET`. La sede unica e' DICHIARATA: duplicare
# una primitiva creerebbe due comportamenti che possono divergere, che e'
# esattamente il difetto che la sede unica esiste per impedire.


def atomic_write(path, text):
    """Contenuto COSTRUITO IN MEMORIA, file TEMPORANEO nella STESSA directory,
    `flush` + `fsync`, `os.replace` ATOMICO sul nome finale. Un fallimento a
    QUALUNQUE punto lascia il file precedente INTATTO e non lascia alcun
    temporaneo orfano."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=str(target.parent),
        prefix=".chapter-", suffix=".part", delete=False)
    temporary = Path(handle.name)
    try:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(str(temporary), str(target))
    except BaseException:
        try:
            handle.close()
        except OSError:
            pass
        if temporary.exists():
            temporary.unlink()
        raise
    return target


def atomic_write_bytes(path, payload):
    """La stessa disciplina di `atomic_write`, per un artefatto BINARIO: il
    pacchetto OOXML e' costruito INTERAMENTE in memoria e scritto con un solo
    `os.replace`, cosi' che un `.xlsx` parziale non esista MAI col nome
    finale."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", dir=str(target.parent), prefix=".workbook-",
        suffix=".part", delete=False)
    temporary = Path(handle.name)
    try:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(str(temporary), str(target))
    except BaseException:
        try:
            handle.close()
        except OSError:
            pass
        if temporary.exists():
            temporary.unlink()
        raise
    return target


def decimal_key(text):
    """CHIAVE DI ORDINAMENTO totale sui decimali canonici, PURAMENTE TESTUALE.

    Non converte, non somma e non arrotonda: normalizza segno, parte intera e
    parte frazionaria come STRINGHE e restituisce una chiave la cui
    comparazione lessicografica coincide con l'ordine numerico. E' cio' che
    consente di NOMINARE il periodo di cassa minima senza che il renderer
    esegua una sola operazione aritmetica.

    Il valore EMESSO nel capitolo resta comunque la stringa canonica VERBATIM:
    questa chiave non entra mai nel documento.
    """
    raw = str(text).strip()
    negative = raw.startswith("-")
    if negative or raw.startswith("+"):
        raw = raw[1:]
    if "." in raw:
        whole, fraction = raw.split(".", 1)
    else:
        whole, fraction = raw, ""
    whole = whole.lstrip("0") or "0"
    fraction = fraction.rstrip("0")
    if whole == "0" and not fraction:
        negative = False
    magnitude = "".join([
        str(len(whole)).zfill(KEY_LENGTH_WIDTH), whole, ".",
        fraction.ljust(KEY_FRACTION_WIDTH, "0")])
    if not negative:
        return (1, magnitude)
    return (0, "".join([DIGIT_COMPLEMENT.get(ch, ch) for ch in magnitude]))


def period_key(index):
    """Ordinamento dei periodi per chiave TESTUALE zero-riempita: le chiavi di
    serie sono stringhe (`"0"`...`"11"`) e l'ordinamento lessicografico nudo
    metterebbe `"10"` prima di `"2"`."""
    return str(index).zfill(PERIOD_KEY_WIDTH)


def is_numeric(text):
    """`True` se la stringa e' un decimale canonico. Non converte il valore:
    lo RICONOSCE."""
    if isinstance(text, bool):
        return False
    if isinstance(text, (int, float)):
        return True
    return bool(NUMERIC_RE.match(str(text).strip()))


def refuse_real_project(project):
    """Rifiuta, prima di ogni I/O, un progetto il cui path risolto cade dentro
    la directory della skill (`real_project_write_forbidden`); altrimenti
    restituisce il path risolto. E' la sola definizione di questa guardia:
    l'esportatore del workbook la riusa."""
    target = Path(project).resolve()
    projects = SKILL_ROOT
    try:
        target.relative_to(projects)
    except ValueError:
        return target
    raise RenderRefusal(
        CODE_REAL_PROJECT, target.as_posix(),
        "i derivati dello Stage 10 non sono mai prodotti dentro la "
        "directory della skill: un progetto il cui path cade nel pacchetto "
        "e' rifiutato prima di ogni I/O e il pacchetto resta BYTE-IDENTICO")


def load_style_tokens():
    """La tabella DICHIARATA degli stili e dei lessici. E' un DATO: il
    renderer non porta alcun colore, alcun titolo e alcun termine di lessico
    come costante di codice."""
    if not STYLE_TOKENS_PATH.is_file():
        raise RenderRefusal(
            CODE_INCOMPLETE, STYLE_TOKENS_NAME,
            f"{STYLE_TOKENS_NAME} assente: la tabella degli stili e dei "
            "lessici e' un DATO DICHIARATO e senza di essa la "
            "resa non e' deterministica")
    return json.loads(STYLE_TOKENS_PATH.read_text(encoding="utf-8"))


def load_canonical(path):
    """Il documento canonico, unica verita' PUBBLICATA. E' letto, mai
    riscritto."""
    source = Path(path)
    if not source.is_file():
        raise RenderRefusal(
            CODE_INCOMPLETE, str(source),
            f"documento canonico assente: {source}. Il capitolo e' una RESA e "
            "non esiste senza la sua fonte")
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RenderRefusal(CODE_CANONICAL, str(source),
                            f"documento canonico non e' JSON: {exc}")
    if not isinstance(document, dict) or "financial_plan" not in document:
        raise RenderRefusal(
            CODE_CANONICAL, str(source),
            "il documento non porta `financial_plan`: non e' il canonico "
            "dello Stage 10")
    return document


def canonical_checksum(document):
    metadata = (document.get("financial_plan") or {}).get(
        "calculation_metadata") or {}
    checksum = (metadata.get("output_checksums") or {}).get("base")
    if not checksum:
        raise RenderRefusal(
            CODE_STALE, "calculation_metadata.output_checksums.base",
            "il canonico non porta `output_checksums.base`: il derivato non "
            "puo' dichiarare la generazione da cui proviene")
    return checksum


def load_record_fingerprint():
    """`record_fingerprint` del Transaction Manager, importato in SOLA
    LETTURA: riusa il CAS gia' esistente invece di coniare una convenzione di
    impronta nuova. L'import NON modifica il Transaction Manager."""
    path = SKILL_ROOT.joinpath("transaction", "transaction_manager.py")
    if not path.is_file():
        raise RenderRefusal(
            CODE_STALE, path.as_posix(),
            "transaction_manager assente: `source_record_hash` non e' "
            "verificabile e nessun attributo di input governato puo' essere "
            "letto (verifica di freschezza degli input governati)")
    spec = importlib.util.spec_from_file_location("transaction_manager", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("transaction_manager", module)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise RenderRefusal(
            CODE_STALE, path.as_posix(),
            f"transaction_manager non importabile in sola lettura: {exc}")
    fingerprint = getattr(module, "record_fingerprint", None)
    if not callable(fingerprint):
        raise RenderRefusal(
            CODE_STALE, path.as_posix(),
            "transaction_manager senza `record_fingerprint`: il CAS esistente "
            "non e' riusabile")
    return fingerprint


def read_governed_inputs(project, drivers):
    """Legge gli ATTRIBUTI DI INPUT GOVERNATO dall'insieme CHIUSO di tre
    registri, verificando OGNI record contro `driver_entry.source_record_hash`.

    Ritorna `(attributes, read_set, verifications)`:
      - `attributes` mappa `source_ref` -> attributi dell'input governato;
      - `read_set` e' l'elenco ORDINATO dei registri REALMENTE letti, che il
        report pubblica: un quarto registro sarebbe VISIBILE qui;
      - `verifications` e' l'esito della verifica di impronta, driver per
        driver.

    Una divergenza di impronta e' `derived_artifact_stale`: il valore NON e'
    usato, e il capitolo NON e' prodotto.
    """
    base = Path(project)
    fingerprint = load_record_fingerprint()
    read_set = []
    registers = {}
    for relative in INPUT_SET:
        path = base.joinpath(*relative.split("/"))
        if not path.is_file():
            registers[relative] = None
            continue
        try:
            registers[relative] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RenderRefusal(
                CODE_STALE, relative,
                f"registro governato non e' JSON: {relative}: {exc}")
        read_set.append(relative)
    by_ref = {}
    for relative in INPUT_SET:
        content = registers.get(relative)
        entries = content if isinstance(content, list) else (
            (content or {}).get("records")
            or (content or {}).get("assumptions")
            or (content or {}).get("entries") or [])
        for record in entries or []:
            if isinstance(record, dict) and record.get("id"):
                by_ref.setdefault(str(record["id"]), (relative, record))
    attributes = {}
    verifications = []
    for driver in drivers or []:
        source_ref = driver.get("source_ref")
        if not source_ref:
            continue
        found = by_ref.get(str(source_ref))
        if found is None:
            verifications.append({
                "driver_id": driver.get("driver_id"), "source_ref": source_ref,
                "register": None, "verified": False,
                "reason": "record non presente nell'insieme di ingresso"})
            continue
        relative, record = found
        current = fingerprint(record)
        bound = driver.get("source_record_hash")
        if bound and current != bound:
            raise RenderRefusal(
                CODE_STALE, str(driver.get("driver_id")),
                f"source_record_hash del driver {driver.get('driver_id')} "
                f"({bound}) DIVERGE dall'impronta corrente del record "
                f"{source_ref} ({current}) letto in {relative}: il valore NON "
                "e' usato e il capitolo NON e' prodotto (verifica di "
                "freschezza degli input governati)")
        verifications.append({
            "driver_id": driver.get("driver_id"), "source_ref": source_ref,
            "register": relative, "verified": True,
            "record_hash": current})
        attributes[str(source_ref)] = {
            "register": relative,
            "value": record.get("value"),
            "display_value": record.get("display_value"),
            "unit": record.get("unit"),
            "owner": record.get("owner"),
            "validation_status": record.get("validation_status"),
            "evidence_classification": record.get("evidence_classification"),
            "evidence_refs": record.get("evidence_refs") or [],
            "validation_action": record.get("validation_action"),
            "rationale": record.get("rationale") or record.get("statement"),
            "source": record.get("source"),
            "last_updated": record.get("last_updated"),
            "record_hash": fingerprint(record),
        }
    return attributes, sorted(read_set), verifications


# --------------------------------------------------------------------------
# Lettura DICHIARATA del canonico
# --------------------------------------------------------------------------


def plan_of(document):
    return document.get("financial_plan") or {}


def modules_of(document):
    return (plan_of(document).get("results") or {}).get("modules") or {}


def scenarios_of(document):
    return (plan_of(document).get("results") or {}).get("scenarios") or {}


def calendar_of(document):
    return (plan_of(document).get("results") or {}).get("calendar") or {}


def declared_currency(document):
    """La valuta e' LETTA dai driver e VERIFICATA come singola. Dove non e'
    unica la resa e' «NON DICHIARATA», mai dedotta."""
    values = sorted({str(entry.get("currency"))
                     for entry in (plan_of(document).get("driver_registry")
                                   or {}).get("drivers") or []
                     if entry.get("currency")})
    if len(values) == 1:
        return values[0]
    return UNDECLARED


def period_indexes(document):
    periods = calendar_of(document).get("periods") or []
    return [str(entry.get("index")) for entry in periods]


def check_base_projection(document):
    """La coincidenza fra `results.modules.<m>.series` e
    `results.scenarios.base.series.<m>` e' VERIFICATA, non assunta: e' cio'
    che autorizza il capitolo a etichettare `base` lo scenario dei valori di
    modulo. Una divergenza e' un rifiuto attribuito."""
    modules = modules_of(document)
    base = (scenarios_of(document).get("base") or {}).get("series") or {}
    for module_id in BASE_PROJECTED_MODULES:
        series = (modules.get(module_id) or {}).get("series")
        projected = base.get(module_id)
        if series is None or projected is None:
            continue
        if series != projected:
            raise RenderRefusal(
                CODE_MISMATCH, f"results.modules.{module_id}.series",
                f"la serie del modulo {module_id} DIVERGE da "
                f"results.scenarios.base.series.{module_id}: il capitolo non "
                "puo' etichettare `base` lo scenario dei valori di modulo "
                "senza che la coincidenza sia VERIFICATA")


# --------------------------------------------------------------------------
# Righe di traccia — i CINQUE elementi, su ogni numero mostrato
# --------------------------------------------------------------------------


def row(label, value, unit, scenario, period, path):
    """Una riga di tabella con i CINQUE elementi di traccia: il quinto — il
    `canonical_source_checksum` — e' portato dalla DIDASCALIA della tabella,
    che ogni riga eredita.

    Un valore privo anche di UNO solo dei cinque elementi e' un NUMERO
    INVENTATO.
    """
    return {"label": label, "value": value, "unit": unit,
            "scenario": scenario, "period": period, "path": path}


def escape_cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_table(tokens, table_id, checksum, rows, empty_note=None):
    """Una tabella con didascalia, checksum e le SEI colonne dichiarate."""
    declared = None
    for entry in (tokens.get("chapter") or {}).get("tables") or []:
        if entry.get("id") == table_id:
            declared = entry
    if declared is None:
        raise RenderRefusal(
            CODE_INCOMPLETE, table_id,
            f"tabella non DICHIARATA in {STYLE_TOKENS_NAME}: {table_id!r}")
    columns = (tokens.get("chapter") or {}).get("trace_columns") or []
    lines = [
        "",
        f"**Tabella {declared['number']} — {declared['title']}.** "
        f"Fonte: `{CANONICAL_NAME}` · checksum `{checksum}`.",
        "",
        "".join(["| ", " | ".join(columns), " |"]),
        "".join(["|", "|".join(["---" for _ in columns]), "|"]),
    ]
    for entry in rows:
        lines.append("".join([
            "| ", " | ".join([
                escape_cell(entry["label"]), escape_cell(entry["value"]),
                escape_cell(entry["unit"]), escape_cell(entry["scenario"]),
                escape_cell(entry["period"]), f"`{escape_cell(entry['path'])}`",
            ]), " |"]))
    if not rows:
        lines.append("".join([
            "| ", " | ".join([escape_cell(empty_note or NOT_APPLICABLE),
                              NOT_APPLICABLE, NOT_APPLICABLE, NOT_APPLICABLE,
                              NOT_APPLICABLE, "`(nessun path canonico)`"]),
            " |"]))
    lines.append("")
    return lines


def unit_for_module(tokens, module_id):
    return ((tokens.get("units") or {}).get("by_module_series") or {}).get(
        module_id, UNDECLARED)


def unit_for_metric(tokens, name):
    table = (tokens.get("units") or {}).get("by_metric_prefix") or {}
    if name in table:
        return table[name]
    for prefix in sorted(table, key=lambda key: str(len(key)).zfill(4),
                         reverse=True):
        if name.startswith("".join([prefix, "_"])):
            return table[prefix]
    return UNDECLARED


def strip_period_suffix(name):
    """`burn_11` -> `("burn", "11")`. E' una scomposizione TESTUALE: nessun
    indice e' calcolato."""
    parts = name.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], parts[1]
    return name, None


# --------------------------------------------------------------------------
# Le dodici tabelle
# --------------------------------------------------------------------------


def assumption_rows(document, tokens, attributes):
    """Tabella 1 — le ASSUNZIONI. E' l'UNICA sede in cui compare un valore
    letto dai registri governati: la regola dell'insieme di ingresso chiuso lo
    ammette nelle sole righe di assunzione e lo VIETA in ogni tabella di
    RISULTATO."""
    rows = []
    for driver in sorted((plan_of(document).get("driver_registry") or {}).get(
            "drivers") or [], key=lambda entry: str(entry.get("driver_id"))):
        source_ref = str(driver.get("source_ref"))
        attribute = attributes.get(source_ref) or {}
        value = attribute.get("value")
        if value is None:
            value = NOT_APPLICABLE
        label = " — ".join([
            str(driver.get("driver_id")),
            str(driver.get("semantic_name") or driver.get("role")),
            f"stato {driver.get('status')}",
        ])
        window = "/".join([str(driver.get("start_period")),
                           str(driver.get("end_period"))])
        rows.append(row(
            label, value, driver.get("unit") or UNDECLARED, ALL_SCENARIOS,
            f"finestra {window} · regola {driver.get('timing_rule')}",
            " -> ".join([
                f"financial_plan.driver_registry.drivers[{driver.get('driver_id')}]",
                f"{attribute.get('register') or INPUT_SET[0]}#{source_ref}.value",
            ])))
    return rows


def series_rows(document, tokens, module_id, scenario="base"):
    module = modules_of(document).get(module_id) or {}
    series = module.get("series") or {}
    unit = unit_for_module(tokens, module_id)
    rows = []
    for index in sorted(series, key=period_key):
        rows.append(row(
            f"{module_id} · periodo {index}", series[index], unit, scenario,
            f"periodo {index}",
            f"financial_plan.results.modules.{module_id}.series.{index}"))
    return rows


def metric_rows(document, tokens, module_id, scenario="base", names=None):
    module = modules_of(document).get(module_id) or {}
    metrics = module.get("metrics") or {}
    rows = []
    for name in sorted(metrics, key=lambda key: (
            strip_period_suffix(key)[0], period_key(
                strip_period_suffix(key)[1] or ""))):
        prefix, index = strip_period_suffix(name)
        if names is not None and prefix not in names:
            continue
        rows.append(row(
            f"{module_id}.{name}", metrics[name],
            unit_for_metric(tokens, prefix), scenario,
            f"periodo {index}" if index is not None
            else (tokens.get("chapter") or {}).get("aggregation_rule"),
            f"financial_plan.results.modules.{module_id}.metrics.{name}"))
    return rows


def pnl_rows(document, tokens):
    """Il conto economico porta le serie di TUTTI i moduli economici
    DICHIARATI — ricavi, costi variabili, margine lordo, personale, costi
    operativi e il modulo `pnl` — piu' le metriche di `pnl`. Nessuna riga e'
    sommata: ogni valore e' una foglia canonica."""
    rows = []
    for module_id in tokens.get("pnl_modules") or ("pnl",):
        rows.extend(series_rows(document, tokens, module_id))
    rows.extend(metric_rows(document, tokens, "pnl"))
    return rows


def cash_rows(document, tokens):
    rows = series_rows(document, tokens, "cash_flow")
    rows.extend(metric_rows(document, tokens, "cash_flow"))
    return rows


def headcount_payroll_rows(document, tokens):
    rows = series_rows(document, tokens, "headcount")
    rows.extend(series_rows(document, tokens, "payroll"))
    return rows


def cost_category_rows(document, tokens):
    """Costi per categoria, dalla TASSONOMIA gia' dichiarata dalle righe di
    costo canoniche. Nessuna riga e' sommata: ogni periodo di ogni riga e' una
    foglia canonica."""
    rows = []
    uses = (tokens.get("taxonomy") or {}).get("use_categories") or ()
    for module_id in ("cogs", "payroll", "opex", "pnl"):
        module = modules_of(document).get(module_id) or {}
        for position, line in enumerate(module.get("lines") or []):
            if line.get("category") not in uses:
                continue
            for index in sorted(line.get("series") or {}, key=period_key):
                rows.append(row(
                    " · ".join([str(line.get("category")),
                                str(line.get("line_id")),
                                f"periodo {index}"]),
                    (line.get("series") or {})[index],
                    unit_for_module(tokens, module_id), "base",
                    f"periodo {index}",
                    ".".join([
                        f"financial_plan.results.modules.{module_id}",
                        f"lines[{position}]", "series", index])))
    return rows


def scenario_rows(document, tokens):
    """Confronto di scenario: SOLO gli scenari PRODOTTI. Uno scenario non
    prodotto NON riceve una colonna, e la sua assenza e' DICHIARATA nella
    prosa con la propria motivazione."""
    rows = []
    scenarios = scenarios_of(document)
    for scenario_id in SCENARIO_IDS:
        entry = scenarios.get(scenario_id) or {}
        if not entry.get("series"):
            continue
        for module_id in sorted(entry.get("series") or {}):
            series = (entry.get("series") or {})[module_id]
            for index in sorted(series, key=period_key):
                rows.append(row(
                    f"{scenario_id} · {module_id} · periodo {index}",
                    series[index], unit_for_module(tokens, module_id),
                    scenario_id, f"periodo {index}",
                    ".".join([
                        f"financial_plan.results.scenarios.{scenario_id}",
                        "series", module_id, index])))
    coverage = scenarios.get("coverage") or {}
    for field in ("ratio", "threshold"):
        if coverage.get(field) is not None:
            rows.append(row(
                f"copertura di scenario · {field}", coverage[field],
                ((tokens.get("units") or {}).get("coverage") or {}).get(
                    field, UNDECLARED), ALL_SCENARIOS,
                (tokens.get("chapter") or {}).get("aggregation_rule"),
                f"financial_plan.results.scenarios.coverage.{field}"))
    return rows


def burn_runway_rows(document, tokens):
    rows = metric_rows(document, tokens, "cash_flow", names=("burn",))
    rows.extend(metric_rows(document, tokens, "runway"))
    buffer_module = modules_of(document).get("cash_buffer") or {}
    for name in sorted(buffer_module.get("metrics") or {}):
        rows.append(row(
            f"cash_buffer.{name}", (buffer_module.get("metrics") or {})[name],
            unit_for_metric(tokens, strip_period_suffix(name)[0]), "base",
            (tokens.get("chapter") or {}).get("aggregation_rule"),
            f"financial_plan.results.modules.cash_buffer.metrics.{name}"))
    return rows


def break_even_rows(document, tokens):
    module = modules_of(document).get("break_even") or {}
    table = (tokens.get("units") or {}).get("by_break_even_field") or {}
    rows = []
    for field in sorted(table):
        if field == "fixed_costs_per_period":
            continue
        value = module.get(field)
        if value is None:
            value = NOT_APPLICABLE
        rows.append(row(
            f"break_even.{field}", value, table[field], "base",
            (tokens.get("chapter") or {}).get("aggregation_rule"),
            f"financial_plan.results.modules.break_even.{field}"))
    fixed = module.get("fixed_costs_per_period") or {}
    for index in sorted(fixed, key=period_key):
        rows.append(row(
            f"break_even.fixed_costs_per_period · periodo {index}",
            fixed[index], table.get("fixed_costs_per_period", UNDECLARED),
            "base", f"periodo {index}",
            ".".join(["financial_plan.results.modules.break_even",
                      "fixed_costs_per_period", index])))
    return rows


def milestone_rows(document, tokens):
    module = modules_of(document).get("milestone_coverage") or {}
    rows = []
    for position, entry in enumerate(module.get("milestones") or []):
        for field in sorted(entry):
            value = entry[field]
            if not is_numeric(value):
                continue
            rows.append(row(
                " · ".join([str(entry.get("milestone_ref")), field]), value,
                unit_for_metric(tokens, field), "base",
                (tokens.get("chapter") or {}).get("aggregation_rule"),
                ".".join([
                    "financial_plan.results.modules.milestone_coverage",
                    f"milestones[{position}]", field])))
    residual = module.get("unmapped_residual")
    if residual is not None:
        rows.append(row(
            "milestone_coverage.unmapped_residual", residual,
            unit_for_metric(tokens, "unmapped_residual"), "base",
            (tokens.get("chapter") or {}).get("aggregation_rule"),
            "financial_plan.results.modules.milestone_coverage"
            ".unmapped_residual"))
    return rows


def funding_rows(document, tokens):
    rows = metric_rows(document, tokens, "funding_gap")
    rows.extend(series_rows(document, tokens, "funding_gap"))
    return rows


def kpi_rows(document, tokens):
    """KPI: OGNI indicatore compare, anche `NOT_APPLICABLE`. Un KPI non
    calcolabile e' NOMINATO con il ruolo di driver mancante, mai omesso e mai
    presentato come «non rilevante»."""
    indicators = (modules_of(document).get("kpi") or {}).get(
        "indicators") or {}
    rows = []
    for kpi_id in sorted(indicators):
        entry = indicators[kpi_id] or {}
        unit = entry.get("unit") or UNDECLARED
        if entry.get("value") is not None:
            rows.append(row(
                f"KPI {kpi_id}", entry["value"], unit, "base",
                (tokens.get("chapter") or {}).get("aggregation_rule"),
                f"financial_plan.results.modules.kpi.indicators.{kpi_id}"
                ".value"))
        for index in sorted(entry.get("series") or {}, key=period_key):
            rows.append(row(
                f"KPI {kpi_id} · periodo {index}",
                (entry.get("series") or {})[index], unit, "base",
                f"periodo {index}",
                ".".join([
                    f"financial_plan.results.modules.kpi.indicators.{kpi_id}",
                    "series", index])))
        if entry.get("value") is None and not entry.get("series"):
            missing = ", ".join(sorted(entry.get("missing_driver_roles")
                                       or [])) or "(nessun ruolo nominato)"
            rows.append(row(
                f"KPI {kpi_id} — {entry.get('status')}: non calcolabile per "
                f"assenza dei ruoli di driver {missing}",
                NOT_APPLICABLE, unit, "base",
                (tokens.get("chapter") or {}).get("aggregation_rule"),
                f"financial_plan.results.modules.kpi.indicators.{kpi_id}"
                ".status"))
    return rows


def caveat_rows(document, tokens):
    """Input non risolti, riconciliazioni e caveat. OGNI `REC-*` compare anche
    quando PASSA: un controllo che non compare equivale a un controllo non
    eseguito."""
    plan = plan_of(document)
    rows = []
    for rec_id in sorted(plan.get("reconciliations") or {}):
        entry = (plan.get("reconciliations") or {})[rec_id] or {}
        unit = entry.get("tolerance_unit") or UNDECLARED
        for field in ("expected", "actual", "residual"):
            if entry.get(field) is None:
                continue
            rows.append(row(
                " · ".join([rec_id, f"stato {entry.get('status')}", field]),
                entry[field], unit, "base",
                (tokens.get("chapter") or {}).get("aggregation_rule"),
                f"financial_plan.reconciliations.{rec_id}.{field}"))
        if entry.get("expected") is None and entry.get("actual") is None:
            rows.append(row(
                " · ".join([rec_id, f"stato {entry.get('status')}",
                            str(entry.get("not_applicable_reason")
                                or entry.get("formula"))]),
                NOT_APPLICABLE, unit, "base",
                (tokens.get("chapter") or {}).get("aggregation_rule"),
                f"financial_plan.reconciliations.{rec_id}.status"))
    for role in sorted((plan.get("driver_registry") or {}).get(
            "unbound_required_roles") or []):
        rows.append(row(
            f"ruolo RICHIESTO non legato · {role}", NOT_APPLICABLE,
            UNDECLARED, ALL_SCENARIOS,
            (tokens.get("chapter") or {}).get("aggregation_rule"),
            "financial_plan.driver_registry.unbound_required_roles"))
    for position, warning in enumerate((plan.get("validation") or {}).get(
            "warnings") or []):
        rows.append(row(
            " · ".join([str(warning.get("code")),
                        ", ".join(warning.get("affected_refs") or []),
                        str(warning.get("message"))]),
            NOT_APPLICABLE, UNDECLARED, ALL_SCENARIOS,
            (tokens.get("chapter") or {}).get("aggregation_rule"),
            f"financial_plan.validation.warnings[{position}]"))
    return rows


TABLE_BUILDERS = {
    "assumptions": None,
    "pnl": pnl_rows,
    "cash_plan": cash_rows,
    "headcount_payroll": headcount_payroll_rows,
    "cost_categories": cost_category_rows,
    "scenario_comparison": scenario_rows,
    "burn_runway_buffer": burn_runway_rows,
    "break_even": break_even_rows,
    "milestone_coverage": milestone_rows,
    "funding_need": funding_rows,
    "kpi": kpi_rows,
    "unresolved_caveats": caveat_rows,
}


# --------------------------------------------------------------------------
# Periodi critici — NOMINATI, mai taciuti
# --------------------------------------------------------------------------


def critical_periods(document, tokens):
    """I periodi CRITICI: cassa minima, cassa zero se
    raggiunta, break-even o la dichiarazione che non e' raggiunto, periodi
    delle milestone finanziariamente critiche.

    La cassa minima e' SELEZIONATA dalla serie PUBBLICATA con la chiave
    testuale di ordinamento: nessuna grandezza nuova e' prodotta e il valore
    NOMINATO e' la stringa canonica VERBATIM.
    """
    modules = modules_of(document)
    series = (modules.get("cash_flow") or {}).get("series") or {}
    minimum = None
    if series:
        index = min(sorted(series, key=period_key),
                    key=lambda key: decimal_key(series[key]))
        minimum = {"period": index, "value": series[index],
                   "path": f"financial_plan.results.modules.cash_flow.series"
                           f".{index}"}
    runway = (modules.get("runway") or {}).get("metrics") or {}
    zero = runway.get("first_period_below_zero")
    buffer_period = runway.get("first_period_below_buffer")
    break_even = modules.get("break_even") or {}
    milestones = []
    for entry in (modules.get("milestone_coverage") or {}).get(
            "milestones") or []:
        milestones.append({
            "milestone_ref": entry.get("milestone_ref"),
            "period": entry.get("period"),
            "status": entry.get("status")})
    return {
        "minimum_cash": minimum,
        "zero_cash_period": zero,
        "below_buffer_period": buffer_period,
        "break_even_period": break_even.get("first_break_even_period"),
        "break_even_outcome": break_even.get("outcome"),
        "milestone_periods": milestones,
    }


# --------------------------------------------------------------------------
# Prosa — GENERATA, e mai promotiva
# --------------------------------------------------------------------------


def status_of(document, module_id):
    return (modules_of(document).get(module_id) or {}).get("status")


def reason_of(document, module_id):
    module = modules_of(document).get(module_id) or {}
    return module.get("not_applicable_reason") or module.get("reason") or ""


def coverage_level(document):
    return ((scenarios_of(document).get("coverage") or {}).get("level")
            or "unknown")


def readiness_of(document):
    return (plan_of(document).get("validation") or {}).get(
        "investor_readiness") or {}


def not_applicable_roster(document):
    """Ogni modulo `NOT_APPLICABLE`, NOMINATO con la propria motivazione
    canonica. L'elenco copre i QUINDICI `module_id`, cosi' che nessuna
    omissione possa passare per non pertinenza."""
    roster = []
    for module_id in MODULE_IDS:
        module = modules_of(document).get(module_id) or {}
        if module.get("status") != NOT_APPLICABLE:
            continue
        roster.append(
            f"`{module_id}` — «{reason_of(document, module_id) or 'motivazione non dichiarata dal canonico'}»")
    return roster


def module_paragraph(document, module_id, produced_text):
    """Una sola forma di paragrafo per modulo: se il modulo e' PRODOTTO si
    descrive quello che porta; se e' `NOT_APPLICABLE` si NOMINA la motivazione
    canonica, mai si tace la riga."""
    status = status_of(document, module_id)
    if status == NOT_APPLICABLE:
        return (f"Il modulo `{module_id}` porta stato `{NOT_APPLICABLE}` con "
                f"la motivazione canonica: «{reason_of(document, module_id)}». "
                "La riga NON e' omessa: un modulo assente da un capitolo si "
                "leggerebbe come non pertinente, mentre la verita' e' che non "
                "e' stato calcolato.")
    return produced_text


# --------------------------------------------------------------------------
# Composizione del capitolo
# --------------------------------------------------------------------------


def render_chapter(document, tokens, attributes, read_set):
    check_base_projection(document)
    checksum = canonical_checksum(document)
    plan = plan_of(document)
    sections = (tokens.get("chapter") or {}).get("sections") or []
    titles = {entry["id"]: entry for entry in sections}
    currency = declared_currency(document)
    calendar = calendar_of(document)
    critical = critical_periods(document, tokens)
    readiness = readiness_of(document)
    level = coverage_level(document)
    drivers = (plan.get("driver_registry") or {}).get("drivers") or []
    metadata = plan.get("calculation_metadata") or {}
    lines = [
        "# Piano finanziario",
        "",
        "> Capitolo GENERATO da `output/render_financial_plan.py` "
        "come RESA del solo documento canonico. Non e' una fonte: non porta "
        "alcuna autorita' e non puo' alterare alcun numero. Ogni valore "
        "mostrato e' una foglia canonica copiata VERBATIM, con il proprio "
        "path, scenario, periodo e unita'; il checksum della generazione e' "
        "nella didascalia di ogni tabella.",
        "",
        f"- **Fonte canonica** — `{STAGE10}/{CANONICAL_NAME}`",
        f"- **Checksum canonico di origine** "
        f"(`calculation_metadata.output_checksums.base`) — `{checksum}`",
        f"- **Versione di schema** — `{document.get('schema_version')}`",
        f"- **Versione della policy di calcolo** — "
        f"`{metadata.get('calculation_policy_version')}`",
        f"- **Versione del motore** — `{metadata.get('engine_version')}`",
        f"- **Valuta dichiarata** — `{currency}`",
        f"- **Frequenza e orizzonte** — `{calendar.get('frequency')}`, "
        f"`{calendar.get('horizon_periods')}` periodi, ancoraggio "
        f"`{calendar.get('anchor_date')}`",
        f"- **Insieme di ingresso letto** — "
        f"{', '.join([f'`{name}`' for name in read_set]) or '(nessun registro governato presente)'}",
        f"- **Arrotondamento** — "
        f"{(tokens.get('chapter') or {}).get('no_rounding_note')}",
        "",
    ]

    # 1 — Perimetro e approccio
    lines.extend([f"## {titles['scope']['number']}. "
                  f"{titles['scope']['title']}", ""])
    lines.extend([
        "Il perimetro e' quello dello Stage 10: il piano finanziario "
        "deterministico calcolato dal motore finanziario e pubblicato dal "
        "documento canonico. L'orizzonte e' di "
        f"`{calendar.get('horizon_periods')}` periodi a frequenza "
        f"`{calendar.get('frequency')}`, ancorati a "
        f"`{calendar.get('anchor_date')}`.",
        "",
        "L'approccio di modellazione e' dichiarato e non negoziabile: i "
        "numeri sono calcolati UNA SOLA VOLTA dal motore, pubblicati dal "
        "canonico e qui soltanto SELEZIONATI e FORMATTATI. Questo capitolo "
        "non somma, non arrotonda, non converte e non applica alcuna soglia. "
        "Dove un valore non esiste, la riga resta presente e porta "
        f"`{NOT_APPLICABLE}` con la motivazione canonica NOMINATA.",
        "",
        "Lo Stage 10 non produce, e questo capitolo non contiene, alcuna "
        "richiesta di finanziamento, alcuno strumento, alcuna valutazione e "
        "alcuna allocazione dei proventi: appartengono allo Stage 11.",
        "",
        "".join([
            "**Moduli non applicabili, NOMINATI uno per uno.** ",
            "; ".join(not_applicable_roster(document))
            or "nessun modulo porta stato NOT_APPLICABLE",
            ". ",
        ]),
        "Nessuno di questi e' omesso dal capitolo: un modulo assente si "
        "leggerebbe come non pertinente, mentre la verita' e' che non e' "
        "stato calcolato, e la motivazione canonica lo dice.",
        "",
    ])

    # 2 — Assunzioni
    lines.extend([f"## {titles['assumptions']['number']}. "
                  f"{titles['assumptions']['title']}", ""])
    counts = {}
    for driver in drivers:
        key = str(driver.get("status"))
        counts[key] = sorted([*(counts.get(key) or []),
                              str(driver.get("driver_id"))])
    summary = "; ".join([f"`{key}`: {', '.join(counts[key])}"
                         for key in sorted(counts)]) or "(nessun driver)"
    lines.extend([
        "Le assunzioni sono gli INPUT GOVERNATI da cui il piano dipende. Il "
        "loro valore NON vive nel canonico — duplicarlo creerebbe un secondo "
        "numero autoritativo — ed e' letto in sola lettura dai registri "
        "governati, con l'impronta del record CONTROLLATA contro "
        "`driver_entry.source_record_hash` di ogni driver.",
        "",
        f"Stato dei driver, come il canonico lo porta: {summary}.",
        "",
        "Nessuno stato e' promosso: un driver `inferred` resta `inferred` e "
        "un `placeholder` resta `placeholder`, in questo capitolo come nel "
        "canonico.",
        "",
    ])
    lines.extend(render_table(tokens, "assumptions", checksum,
                              assumption_rows(document, tokens, attributes),
                              empty_note="nessun driver nel registro"))

    # 3 — Modello di ricavo
    lines.extend([f"## {titles['revenue_model']['number']}. "
                  f"{titles['revenue_model']['title']}", ""])
    revenue = modules_of(document).get("revenue") or {}
    lines.extend([
        module_paragraph(
            document, "revenue",
            "Il ricavo e' generato dai driver "
            f"{', '.join(sorted(revenue.get('input_driver_refs') or [])) or '(nessuno)'} "
            "secondo la semantica dichiarata dal motore: "
            f"«{revenue.get('notes') or '(nessuna nota canonica)'}». Le righe "
            "di dettaglio sono quelle canoniche, categoria per categoria, e "
            "compaiono per periodo nella tabella dei costi per categoria."),
        "",
        "I valori per periodo del modulo `revenue` sono riportati nella "
        "tabella del conto economico e nel confronto di scenario, con lo "
        "stesso path canonico e senza alcuna rielaborazione.",
        "",
    ])

    # 4 — Struttura dei costi
    lines.extend([f"## {titles['cost_structure']['number']}. "
                  f"{titles['cost_structure']['title']}", ""])
    lines.extend([
        "La struttura dei costi segue la TASSONOMIA canonica delle righe di "
        "costo: ogni riga porta la propria categoria e i propri "
        "`driver_refs`, e nessuna categoria e' introdotta qui. I costi "
        "variabili vivono in `cogs`, il costo del personale in `payroll`, i "
        "costi operativi in `opex`.",
        "",
    ])
    lines.extend(render_table(tokens, "cost_categories", checksum,
                              cost_category_rows(document, tokens),
                              empty_note="nessuna riga di costo canonica"))

    # 5 — Organico
    lines.extend([f"## {titles['headcount']['number']}. "
                  f"{titles['headcount']['title']}", ""])
    lines.extend([
        module_paragraph(
            document, "headcount",
            "L'organico e' espresso in LIVELLI di FTE per periodo, non in "
            "flussi: e' la semantica `stock` dichiarata dal motore. Il costo "
            "del personale che ne discende e' il modulo `payroll`, i cui "
            "valori per periodo compaiono qui accanto."),
        "",
    ])
    lines.extend(render_table(tokens, "headcount_payroll", checksum,
                              headcount_payroll_rows(document, tokens),
                              empty_note="nessuna serie di organico"))

    # 6 — Conto economico
    lines.extend([f"## {titles['pnl']['number']}. {titles['pnl']['title']}",
                  ""])
    lines.extend([
        module_paragraph(
            document, "pnl",
            "Il conto economico e' pubblicato per periodo. Nessun totale di "
            "esercizio e' calcolato qui: sommare sarebbe un ricalcolo, e la "
            "regola di aggregazione dichiarata di questo capitolo e' che "
            "NESSUNA aggregazione viene eseguita."),
        "",
    ])
    lines.extend(render_table(tokens, "pnl", checksum,
                              pnl_rows(document, tokens),
                              empty_note="conto economico non prodotto"))

    # 7 — Piano di cassa
    lines.extend([f"## {titles['cash_plan']['number']}. "
                  f"{titles['cash_plan']['title']}", ""])
    minimum = critical.get("minimum_cash")
    zero = critical.get("zero_cash_period")
    lines.extend([
        module_paragraph(
            document, "cash_flow",
            "Il piano di cassa espone, periodo per periodo, apertura, "
            "entrate, uscite e chiusura, piu' il burn. L'identita' "
            "`apertura + entrate - uscite = chiusura` e' quella che il motore "
            "ha gia' riconciliato: il capitolo la pubblica, non la ricalcola."),
        "",
        "".join([
            "**Periodi critici, NOMINATI.** ",
            ("La cassa minima e' al periodo "
             f"`{minimum['period']}` con valore `{minimum['value']}` "
             f"(`{minimum['path']}`). " if minimum
             else "Nessuna serie di cassa e' pubblicata, quindi nessun "
                  "periodo di cassa minima e' nominabile. "),
            (f"La cassa scende sotto zero al periodo `{zero}` "
             "(`financial_plan.results.modules.runway.metrics"
             ".first_period_below_zero`). "
             if zero is not None and zero != NOT_APPLICABLE
             else "La cassa non raggiunge lo zero entro l'orizzonte "
                  "dichiarato, secondo "
                  "`runway.metrics.first_period_below_zero`. "),
            (f"Il buffer operativo e' violato al periodo "
             f"`{critical.get('below_buffer_period')}`."
             if critical.get("below_buffer_period") not in (None,
                                                            NOT_APPLICABLE)
             else "La soglia di buffer non e' dichiarata in "
                  "`financial_config`: la violazione del buffer non e' "
                  "`zero`, e' NON APPLICABILE."),
        ]),
        "",
    ])
    lines.extend(render_table(tokens, "cash_plan", checksum,
                              cash_rows(document, tokens),
                              empty_note="piano di cassa non prodotto"))

    # 8 — Burn e runway
    lines.extend([f"## {titles['burn_runway']['number']}. "
                  f"{titles['burn_runway']['title']}", ""])
    lines.extend([
        "Le QUATTRO metriche di cassa restano DISTINTE e non si collassano: "
        "`runway_to_zero` e `runway_to_buffer` sono due grandezze diverse, "
        "ciascuna col proprio periodo di prima violazione, e cosi' i due "
        "`funding_gap`. Dove la soglia di buffer non e' dichiarata la metrica "
        f"corrispondente e' `{NOT_APPLICABLE}`, mai zero.",
        "",
    ])
    lines.extend(render_table(tokens, "burn_runway_buffer", checksum,
                              burn_runway_rows(document, tokens),
                              empty_note="nessuna metrica di burn o runway"))

    # 9 — Break-even
    lines.extend([f"## {titles['break_even']['number']}. "
                  f"{titles['break_even']['title']}", ""])
    outcome = critical.get("break_even_outcome")
    period = critical.get("break_even_period")
    lines.extend([
        (f"Il pareggio e' raggiunto al periodo `{period}`."
         if period is not None
         else f"Il pareggio NON e' raggiunto entro l'orizzonte dichiarato: "
              f"l'esito canonico e' `{outcome}`, con la motivazione "
              f"«{reason_of(document, 'break_even')}». La dichiarazione e' "
              "esplicita: il capitolo non tace un pareggio mancato."),
        "",
    ])
    lines.extend(render_table(tokens, "break_even", checksum,
                              break_even_rows(document, tokens),
                              empty_note="break-even non prodotto"))

    # 10 — Scenari
    lines.extend([f"## {titles['scenarios']['number']}. "
                  f"{titles['scenarios']['title']}", ""])
    produced = [name for name in SCENARIO_IDS
                if (scenarios_of(document).get(name) or {}).get("series")]
    uncovered = sorted((scenarios_of(document).get("coverage") or {}).get(
        "uncovered_driver_refs") or [])
    coverage = scenarios_of(document).get("coverage") or {}
    if level == "none":
        missing = []
        for scenario_id in SCENARIO_IDS:
            entry = scenarios_of(document).get(scenario_id) or {}
            if entry.get("series"):
                continue
            missing.append(
                f"`{scenario_id}`: stato `{entry.get('status') or NOT_APPLICABLE}`"
                f", motivazione «{entry.get('not_applicable_reason') or 'non dichiarata dal canonico'}»")
        lines.extend([
            "La copertura di scenario e' NULLA. Il piano e' quindi "
            "**base-only** e questo capitolo NON contiene alcuna sezione "
            "Downside o Upside etichettata come tale: gli scenari non "
            f"prodotti sono `{NOT_APPLICABLE}` DICHIARATO, non serie vuote e "
            "non copie del Base.",
            "",
            "Scenari non prodotti, NOMINATI con il proprio stato canonico: "
            f"{'; '.join(missing) or '(nessuno)'}.",
            "",
            "I driver privi di terna di scenario sono NOMINATI uno per uno: "
            f"{', '.join(uncovered) or '(nessun driver nominato dal canonico)'}.",
            "",
            "La condizione proposta dal canonico e' "
            f"`{coverage.get('proposed_condition_ref') or 'non dichiarata'}`, "
            "dovuta prima dello Stage 11: senza terne di scenario non esiste "
            "una base per una discussione di rischio.",
            "",
        ])
    elif level == "partial":
        lines.extend([
            "La copertura di scenario e' `partial_coverage`. Le tre serie "
            f"sono mostrate CON lo stato `{level}` e con l'elenco NOMINATIVO "
            "dei driver privi di terna: "
            f"{', '.join(uncovered) or '(nessun driver nominato dal canonico)'}. "
            "Il caveat e' nel CORPO del capitolo, non in nota: una copertura "
            "parziale cambia il significato del confronto, e taccerlo "
            "renderebbe il piano piu' robusto di quanto sia.",
            "",
        ])
    else:
        lines.extend([
            f"La copertura di scenario e' `{level}`: gli scenari prodotti "
            f"sono {', '.join(produced) or '(nessuno)'}, ciascuno letto dal "
            "proprio blocco canonico. Il confronto che segue mostra una "
            "colonna per ogni scenario PRODOTTO e nessuna colonna per uno "
            "scenario non prodotto.",
            "",
        ])
    lines.extend(render_table(tokens, "scenario_comparison", checksum,
                              scenario_rows(document, tokens),
                              empty_note="nessuno scenario prodotto"))

    # 11 — Milestone
    lines.extend([f"## {titles['milestones']['number']}. "
                  f"{titles['milestones']['title']}", ""])
    lines.extend([
        module_paragraph(
            document, "milestone_coverage",
            "La copertura finanziaria delle milestone confronta il costo di "
            "ciascuna `MIL-*` con le risorse correnti e gia' acquisite. Lo "
            "stato per milestone e il residuo non mappato sono quelli "
            "canonici."),
        "",
    ])
    lines.extend(render_table(tokens, "milestone_coverage", checksum,
                              milestone_rows(document, tokens),
                              empty_note=(
                                  "nessuna milestone mappata: il modulo "
                                  f"`milestone_coverage` e' {NOT_APPLICABLE} "
                                  "con motivazione canonica NOMINATA")))

    # 12 — Fabbisogno
    lines.extend([f"## {titles['funding_need']['number']}. "
                  f"{titles['funding_need']['title']}", ""])
    funding = modules_of(document).get("funding_gap") or {}
    candidates = funding.get("use_of_proceeds_candidates") or []
    lines.extend([
        module_paragraph(
            document, "funding_gap",
            "Il fabbisogno finanziario e' il PROFILO TEMPORALE del residuo, e "
            "i due `funding_gap` ne sono i riassunti scalari. Il gap e' un "
            "RESIDUO, mai una fonte: nessuna riga di questo capitolo lo "
            "tratta come denaro disponibile."),
        "",
        "".join([
            "**Categorie eleggibili di impiego, senza importi.** ",
            ("; ".join([f"`{entry.get('category_id')}` "
                        f"({entry.get('label')}), driver "
                        f"{', '.join(entry.get('driver_refs') or [])}"
                        for entry in candidates])
             if candidates else "nessuna categoria eleggibile e' dichiarata "
                                "dal canonico"),
            ". Sono CATEGORIE, non un'allocazione: nessun importo e' "
            "associato a una categoria e la loro somma non e' una richiesta "
            "di funding, che appartiene allo Stage 11.",
        ]),
        "",
    ])
    lines.extend(render_table(tokens, "funding_need", checksum,
                              funding_rows(document, tokens),
                              empty_note="fabbisogno non prodotto"))

    # 13 — KPI
    lines.extend([f"## {titles['kpi']['number']}. {titles['kpi']['title']}",
                  ""])
    lines.extend([
        "Ogni indicatore compare, anche quando non e' calcolabile. Un KPI "
        f"`{NOT_APPLICABLE}` e' NOMINATO con i ruoli di driver mancanti: non "
        "e' omesso e non e' presentato come privo di interesse.",
        "",
    ])
    lines.extend(render_table(tokens, "kpi", checksum,
                              kpi_rows(document, tokens),
                              empty_note="nessun indicatore pubblicato"))

    # 14 — Caveat
    lines.extend([f"## {titles['caveats']['number']}. "
                  f"{titles['caveats']['title']}", ""])
    warnings = (plan.get("validation") or {}).get("warnings") or []
    errors = (plan.get("validation") or {}).get("errors") or []
    lines.extend([
        f"Lo stato di validazione canonico e' "
        f"`{(plan.get('validation') or {}).get('result')}` con stato "
        f"propagato `{(plan.get('validation') or {}).get('propagated_status')}`. "
        f"I warning canonici sono {len(warnings)} e gli errori {len(errors)}: "
        "ciascuno e' riportato nella tabella con il proprio codice e i propri "
        "riferimenti attribuiti.",
        "",
        "OGNI riconciliazione `REC-*` compare nella tabella anche quando "
        "PASSA: un controllo che non compare equivale a un controllo non "
        "eseguito.",
        "",
        "**Analisi di sensitivita'.** Il canonico non porta un blocco di "
        "sensitivity: in questa versione l'analisi di sensitivita' non fa "
        "parte del documento canonico (OMISSIONE DICHIARATA), e questo "
        "capitolo non produce quella sezione ne' la simula.",
        "",
    ])
    lines.extend(render_table(tokens, "unresolved_caveats", checksum,
                              caveat_rows(document, tokens),
                              empty_note="nessun caveat canonico"))

    # 15 — Conclusioni
    lines.extend([f"## {titles['conclusions']['number']}. "
                  f"{titles['conclusions']['title']}", ""])
    reasons = readiness.get("blocking_reasons") or []
    pending = sorted([str(entry.get("driver_id")) for entry in drivers
                      if entry.get("status") in ("inferred", "placeholder")])
    lines.extend([
        f"**Dichiarazione di prontezza.** `investor_readiness.status` e' "
        f"`{readiness.get('status')}`, come il canonico lo pubblica in "
        "`financial_plan.validation.investor_readiness`.",
        "",
    ])
    if reasons:
        lines.append("Le ragioni di blocco, TIPIZZATE e ATTRIBUITE, sono:")
        lines.append("")
        for entry in reasons:
            lines.append(
                f"- `{entry.get('code')}` — «{entry.get('message')}» "
                f"(riferimenti: "
                f"{', '.join(entry.get('affected_refs') or []) or '(nessuno)'})")
        lines.append("")
    lines.extend([
        f"**Assunzioni in attesa di validazione: {len(pending)}** — "
        f"{', '.join(pending) or '(nessuna)'}. Il conteggio e' esplicito "
        "perche' e' la misura di quanto il piano dipenda da input non ancora "
        "governati come fatti.",
        "",
        ("Con `investor_readiness.status` diverso da `ready`, queste "
         "conclusioni NON dichiarano il piano adatto a essere portato a un "
         "investitore o a un finanziatore: la decisione richiede prima la "
         "rimozione delle ragioni di blocco elencate sopra."
         if readiness.get("status") != "ready"
         else "Con `investor_readiness.status` uguale a `ready` e nessuna "
              "ragione di blocco, il piano soddisfa la regola conservativa di "
              "prontezza pubblicata dal canonico."),
        "",
        "Questo capitolo non risolve alcuna questione aperta, non promuove "
        "alcuno stato e "
        "non anticipa alcuna decisione di finanziamento.",
        "",
    ])
    return "".join(["\n".join(lines), "\n"])


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def chapter_path(project):
    return Path(project).joinpath(STAGE10, CHAPTER_NAME)


def render(canonical_path, project, out=None):
    """Costruisce il capitolo IN MEMORIA e lo scrive ATOMICAMENTE."""
    target_project = refuse_real_project(project)
    document = load_canonical(canonical_path)
    tokens = load_style_tokens()
    drivers = (plan_of(document).get("driver_registry") or {}).get(
        "drivers") or []
    attributes, read_set, verifications = read_governed_inputs(
        target_project, drivers)
    text = render_chapter(document, tokens, attributes, read_set)
    target = Path(out) if out else chapter_path(target_project)
    atomic_write(target, text)
    sections = [entry["id"] for entry
                in (tokens.get("chapter") or {}).get("sections") or []]
    tables = [entry["id"] for entry
              in (tokens.get("chapter") or {}).get("tables") or []]
    return {
        "result": "PASS",
        "renderer": RENDERER_NAME,
        "stage": STAGE10,
        "errors": [],
        "warnings": [],
        "written": [target.as_posix()],
        "canonical_source_checksum": canonical_checksum(document),
        "read_set": read_set,
        "input_set": list(INPUT_SET),
        "hash_verifications": verifications,
        "sections": sections,
        "tables": tables,
        "critical_periods": critical_periods(document, tokens),
    }


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(
        prog=RENDERER_NAME, add_help=True,
        description="Renderer del capitolo financial-plan.md dello Stage 10.")
    parser.add_argument("--canonical", required=True,
                        help="documento canonico structured-output.json")
    parser.add_argument("--project", required=True,
                        help="directory del progetto (fuori da projects/ del checkout)")
    parser.add_argument("--out", required=False,
                        help="path di destinazione alternativo (staging)")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    try:
        report = render(args.canonical, args.project, out=args.out)
    except RenderUsageError as exc:
        print(f"{RENDERER_NAME}: {exc}", file=sys.stderr)
        return 2
    except RenderRefusal as exc:
        print(json.dumps({
            "result": "FAIL", "renderer": RENDERER_NAME, "stage": STAGE10,
            "errors": [{"code": exc.code, "ref": exc.ref,
                        "message": exc.message}],
            "warnings": [], "written": [],
            "canonical_source_checksum": None,
        }, indent=2, ensure_ascii=True, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
