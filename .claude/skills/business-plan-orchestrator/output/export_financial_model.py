#!/usr/bin/env python3
"""Esportatore del WORKBOOK FINANZIARIO `financial-model.xlsx` dello Stage 10.

Scrive un pacchetto **OOXML**
valido usando la **SOLA libreria standard** di Python: `zipfile` e generazione
XML testuale. **Nessuna** dipendenza di terze parti — né `openpyxl`, né
`xlsxwriter`, né LibreOffice — è importata, richiesta o installata.

DISCIPLINA, CONDIVISA COL COSTRUTTORE CANONICO E COL CAPITOLO
------------------------------------------------------------
Il workbook è un **DERIVATO**: non è la verità canonica e non la può alterare.
Ne segue, senza eccezioni:

- **nessun ricalcolo di policy**: ogni valore ufficiale è una FOGLIA CANONICA
  copiata VERBATIM, con il proprio `canonical_ref`; questo modulo non contiene
  alcun operatore aritmetico e non chiama `sum`, `round`, `abs`, `pow`,
  `divmod`, `Decimal`, `float` o `int` su una grandezza economica;
- **nessun secondo registro di assunzioni**: l'unico registro è
  `driver_registry.drivers[]`, letto dal canonico, più gli ATTRIBUTI di input
  governato raggiunti per dereferenza secondo l'insieme di ingresso CHIUSO;
- **nessuna scrittura a monte**: il canonico non è mai aperto in scrittura;
- **nessuna scrittura dentro la skill**: un progetto il cui path cade nella
  directory della skill è RIFIUTATO prima di qualunque I/O
  (`real_project_write_forbidden`), con la stessa guardia del capitolo;
- **nessun colore inventato**: i cinque token ARGB vivono in
  `output/style_tokens.json`, sede unica, e sono un DATO, non una costante;
- **il colore non è mai l'unico portatore di significato**: ogni cella stilata
  porta l'ETICHETTA TESTUALE dello stato in colonna adiacente.

Le formule ammesse sono **soltanto** quelle dell'elenco CHIUSO
`workbook.allowed_formula_functions` di `style_tokens.json`, e **nessuna
formula porta un letterale numerico**: una soglia, una tolleranza o un fattore
sarebbero POLICY, e la policy vive nel motore. Ogni
grandezza che una formula confronta è raggiunta da una CELLA, mai scritta nella
formula.

USO
---
    python export_financial_model.py --canonical <structured-output.json>
                                     --project <directory di progetto>
                                     [--staging <directory>]
                                     [--inject-failure emit|publish]

Su `stdout` è emesso un REPORT JSON che dichiara fogli, named range, celle,
righe di Assumption Register, metriche di testata, insieme di lettura e
checksum canonico. Il report è la superficie che i test di
`tests/integration/test_fin_xlsx.py` misurano, insieme al pacchetto OOXML
stesso.

CODICI DI USCITA
----------------
    0   workbook prodotto e coerente
    1   rifiuto DICHIARATO (codice in `report.refusal.code`)
    2   errore d'uso
"""
import argparse
import datetime
import hashlib
import importlib.util
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

EXPORTER_NAME = "export_financial_model"

WORKBOOK_NAME = "financial-model.xlsx"
CANONICAL_NAME = "structured-output.json"
CHAPTER_NAME = "financial-plan.md"
STYLE_TOKENS_NAME = "style_tokens.json"
STAGE10 = "10_financial-plan"

SKILL_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = Path(__file__).resolve().parent
STYLE_TOKENS_PATH = OUTPUT_DIR.joinpath(STYLE_TOKENS_NAME)

#: L'insieme di ingresso CHIUSO NON è ridichiarato qui: vive in
#: `render_financial_plan.INPUT_SET`, sede unica, ed è raggiunto da
#: `input_set()`. Ridichiararlo permetterebbe ai due derivati di leggere
#: insiemi diversi, che è precisamente il difetto da escludere.

CODE_STALE = "derived_artifact_stale"
CODE_INCOMPLETE = "derived_artifact_incomplete"
CODE_MISMATCH = "derived_artifact_numeric_mismatch"
CODE_REAL_PROJECT = "real_project_write_forbidden"
CODE_INPUT_SET = "derived_input_set_violation"
CODE_CANONICAL = "canonical_document_invalid"

NOT_APPLICABLE = "NOT_APPLICABLE"
UNDECLARED = "NON DICHIARATA"
ALL_SCENARIOS = "tutti"

SCENARIO_IDS = ("base", "downside", "upside")

#: Le OTTO voci del set minimo di KPI, già `required` dallo schema.
KPI_IDS = ("gross_margin_pct", "monthly_burn", "runway", "cac", "ltv",
           "ltv_cac_ratio", "break_even_period", "milestone_coverage")

NUMERIC_RE = re.compile(r"^[+-]?(?:[0-9]+)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")

#: Chiavi di ordinamento PURAMENTE TESTUALI: nessuna aritmetica è eseguita su
#: un indice di periodo o su un valore. È la stessa disciplina del capitolo.
PERIOD_KEY_WIDTH = 8

TRACE_HEADER = ("Voce", "Valore", "Unita'", "Scenario",
                "Periodo / aggregazione", "Path canonico", "Stato / nota")


class ExportRefusal(Exception):
    """Rifiuto DICHIARATO, con codice e path. Non è un errore di programma."""

    def __init__(self, code, path, message):
        super().__init__(message)
        self.code = code
        self.path = path
        self.message = message


class ExportUsageError(Exception):
    """Errore d'uso (exit 2)."""


# --------------------------------------------------------------------------
# Primitive CONDIVISE — IMPORTATE, mai duplicate
# --------------------------------------------------------------------------
#
# `render_financial_plan.py` DICHIARA di essere la SEDE UNICA di
# `atomic_write`, `atomic_write_bytes`, `decimal_key`, `period_key`,
# `load_canonical`, `read_governed_inputs` e `INPUT_SET`, e che QUESTO modulo
# le IMPORTA da lì. La disciplina non è cosmetica:
#
#   - duplicare `read_governed_inputs` significherebbe creare un SECONDO
#     lettore dell'insieme di ingresso governato, cioè esattamente il «secondo
#     registro di assunzioni» che la disciplina dei derivati VIETA;
#   - duplicare `period_key` o `strip_period_suffix` significherebbe due
#     ordinamenti che possono divergere sullo stesso canonico.
#
# L'import è in SOLA LETTURA e non modifica il renderer.

RENDERER_PATH = OUTPUT_DIR.joinpath("render_financial_plan.py")
_RENDERER = None


def renderer():
    """Il renderer del capitolo, importato in SOLA LETTURA come SEDE UNICA
    delle primitive condivise."""
    global _RENDERER
    if _RENDERER is not None:
        return _RENDERER
    if not RENDERER_PATH.is_file():
        raise ExportRefusal(
            CODE_INCOMPLETE, str(RENDERER_PATH),
            "render_financial_plan.py ASSENTE: le primitive condivise hanno "
            "una SEDE UNICA e non sono duplicate qui")
    spec = importlib.util.spec_from_file_location("render_financial_plan",
                                                  RENDERER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("render_financial_plan", module)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:                         # pragma: no cover
        raise ExportRefusal(CODE_INCOMPLETE, str(RENDERER_PATH),
                            f"renderer non importabile in sola lettura: {exc}")
    _RENDERER = module
    return module


def _relay(action, *args):
    """Invoca una primitiva condivisa convertendo `RenderRefusal` in
    `ExportRefusal`: il CODICE e il riferimento sono PRESERVATI, così che
    l'attribuzione resti quella del difetto reale."""
    module = renderer()
    try:
        return action(module, *args)
    except module.RenderRefusal as exc:
        raise ExportRefusal(exc.code, exc.ref, exc.message)


def period_key(index):
    return renderer().period_key(index)


def is_numeric(text):
    return renderer().is_numeric(text)


def strip_period_suffix(name):
    return renderer().strip_period_suffix(name)


def unit_for_module(tokens, module_id):
    return renderer().unit_for_module(tokens, module_id)


def unit_for_metric(tokens, name):
    return renderer().unit_for_metric(tokens, name)


def input_set():
    return tuple(renderer().INPUT_SET)


def column_letter(index):
    """Lettera di colonna 1 -> A. Costruita per divisioni intere su un INDICE
    di colonna: è una coordinata, non una grandezza economica."""
    letters = []
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters.append(chr(ord("A") + remainder))
    return "".join(reversed(letters))


def sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def refuse_real_project(project):
    """Il progetto REALE è rifiutato PRIMA di ogni I/O, dalla stessa guardia
    che il capitolo già usa: una sola definizione di «progetto reale»."""
    return _relay(lambda module, target: module.refuse_real_project(target),
                  project)


def atomic_write_bytes(path, payload):
    """Scrittura atomica, dalla SEDE UNICA: contenuto costruito
    INTERAMENTE in memoria, temporaneo nella stessa directory, `os.replace`.
    Un `.xlsx` parziale non esiste MAI sotto il nome finale."""
    return _relay(
        lambda module, target, data: module.atomic_write_bytes(target, data),
        path, payload)


# --------------------------------------------------------------------------
# Ingresso: token di stile, canonico, registri governati
# --------------------------------------------------------------------------


def load_style_tokens():
    """I token di stile dalla SEDE UNICA `style_tokens.json`, con lo STESSO lettore
    del capitolo: una sola tabella di stili per i due derivati."""
    return _relay(lambda module: module.load_style_tokens())


def load_canonical(path):
    return _relay(lambda module, target: module.load_canonical(target), path)


def plan_of(document):
    return document.get("financial_plan") or {}


def results_of(document):
    return plan_of(document).get("results") or {}


def modules_of(document):
    return results_of(document).get("modules") or {}


def scenarios_of(document):
    return results_of(document).get("scenarios") or {}


def calendar_of(document):
    return results_of(document).get("calendar") or {}


def validation_of(document):
    return plan_of(document).get("validation") or {}


def metadata_of(document):
    return plan_of(document).get("calculation_metadata") or {}


def drivers_of(document):
    return (plan_of(document).get("driver_registry") or {}).get("drivers") or []


def reconciliations_of(document):
    return plan_of(document).get("reconciliations") or {}


def canonical_checksum(document):
    return _relay(lambda module, doc: module.canonical_checksum(doc), document)


def read_governed_inputs(project, drivers):
    """Insieme di ingresso CHIUSO, verificato per impronta.

    NON è implementato qui: è la primitiva CONDIVISA del renderer, invocata in
    sola lettura. Un secondo lettore sarebbe un SECONDO REGISTRO di assunzioni,
    che la disciplina dei derivati vieta, e potrebbe divergere dal primo proprio sul
    caso che conta — una divergenza di `source_record_hash`.

    Una divergenza di impronta è `derived_artifact_stale`: il valore NON è
    usato e il workbook NON è prodotto.
    """
    attributes, read_set, verifications = _relay(
        lambda module, target, entries: module.read_governed_inputs(target,
                                                                    entries),
        project, drivers)
    return {
        "attributes": attributes,
        "checks": verifications,
        "read_set": list(read_set),
        "input_set_declared": list(input_set()),
        "registers_present": list(read_set),
        "fingerprint_source": str(
            SKILL_ROOT.joinpath("transaction", "transaction_manager.py")),
    }


# --------------------------------------------------------------------------
# Modello di foglio — celle DICHIARATE, mai dedotte
# --------------------------------------------------------------------------


def cell(value, kind="s", style="calculated_locked", canonical_ref=None,
         name=None, block=None, note=None):
    """Una cella DICHIARATA.

    `kind`  's' testo · 'n' numero (foglia canonica VERBATIM) · 'f' formula
    `block` 'in' cella EDITABILE · 'out' output · None intestazione o nota
    """
    return {"value": value, "kind": kind, "style": style,
            "canonical_ref": canonical_ref, "name": name, "block": block,
            "note": note}


def header_cells(labels):
    return [cell(label, "s", "derived_neutral") for label in labels]


class SheetBuilder:
    """Costruttore di un foglio. Le righe sono DICHIARATE nell'ordine di
    emissione: nessuna riga è calcolata, nessun numero di riga è hardcodato in
    una formula — i riferimenti passano SEMPRE per named range o per una
    coordinata risolta a valle, mai scritta a mano."""

    def __init__(self, number, name, key, purpose, source):
        self.number = number
        self.name = name
        self.key = key
        self.purpose = purpose
        self.source = source
        self.rows = []

    def add(self, cells):
        self.rows.append(list(cells))
        return len(self.rows)

    def blank(self):
        return self.add([])

    def title_block(self, checksum):
        """INTESTAZIONE obbligatoria: scopo e fonte canonica."""
        self.add([cell(f"{self.number}. {self.name}", "s", "derived_neutral")])
        self.add([cell("Scopo", "s", "derived_neutral"),
                  cell(self.purpose, "s", "derived_neutral")])
        self.add([cell("Fonte canonica", "s", "derived_neutral"),
                  cell(self.source, "s", "derived_neutral")])
        self.add([cell("Checksum della generazione", "s", "derived_neutral"),
                  cell(checksum, "s", "derived_neutral",
                       canonical_ref="financial_plan.calculation_metadata."
                                     "output_checksums.base")])
        self.blank()


# --------------------------------------------------------------------------
# Costruzione dei DICIOTTO fogli
# --------------------------------------------------------------------------


def sheet_key(name):
    """Chiave utilizzabile in un named range: lettere, cifre e underscore."""
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_")
    if cleaned[:1].isdigit():
        cleaned = f"s_{cleaned}"
    return cleaned


def status_style(tokens, status):
    return (tokens.get("driver_status_style") or {}).get(
        str(status), "assumption_to_validate")


def status_label(tokens, status):
    return (tokens.get("driver_status_label") or {}).get(
        str(status), "ASSUNZIONE DA VALIDARE")


def value_row(label, value, unit, scenario, period, path, note=""):
    """Una riga di VALORE UFFICIALE: foglia canonica copiata VERBATIM, con il
    proprio `canonical_ref`. Mai una formula."""
    kind = "n" if is_numeric(value) else "s"
    return [
        cell(label, "s", "derived_neutral"),
        cell(value, kind, "calculated_locked", canonical_ref=path,
             block="out"),
        cell(unit, "s", "derived_neutral"),
        cell(scenario, "s", "derived_neutral"),
        cell(period, "s", "derived_neutral"),
        cell(path, "s", "derived_neutral"),
        cell(note or "valore ufficiale, copiato dal canonico", "s",
             "derived_neutral"),
    ]


def module_series_rows(document, tokens, module_id, scenario="base"):
    module = modules_of(document).get(module_id) or {}
    series = module.get("series") or {}
    unit = unit_for_module(tokens, module_id)
    rows = []
    for index in sorted(series, key=period_key):
        rows.append(value_row(
            f"{module_id} · periodo {index}", series[index], unit, scenario,
            f"periodo {index}",
            f"financial_plan.results.modules.{module_id}.series.{index}"))
    return rows


def module_metric_rows(document, tokens, module_id, scenario="base"):
    module = modules_of(document).get(module_id) or {}
    metrics = module.get("metrics") or {}
    rows = []
    for name in sorted(metrics, key=lambda key: (
            strip_period_suffix(key)[0],
            period_key(strip_period_suffix(key)[1] or ""))):
        prefix, index = strip_period_suffix(name)
        rows.append(value_row(
            f"{module_id}.{name}", metrics[name], unit_for_metric(tokens,
                                                                  prefix),
            scenario,
            f"periodo {index}" if index is not None else "scalare canonico",
            f"financial_plan.results.modules.{module_id}.metrics.{name}"))
    return rows


def module_line_rows(document, tokens, module_id, scenario="base"):
    module = modules_of(document).get(module_id) or {}
    unit = unit_for_module(tokens, module_id)
    rows = []
    for position, line in enumerate(module.get("lines") or []):
        for index in sorted(line.get("series") or {}, key=period_key):
            rows.append(value_row(
                " · ".join([str(line.get("category")), str(line.get("line_id")),
                            f"periodo {index}"]),
                (line.get("series") or {})[index], unit, scenario,
                f"periodo {index}",
                ".".join([f"financial_plan.results.modules.{module_id}",
                          f"lines[{position}]", "series", index])))
    return rows


def add_value_table(sheet, rows, empty_note):
    """Tabella di valori ufficiali con intestazioni TESTUALI di colonna, più —
    quando esiste almeno un valore numerico — un SUBTOTALE di presentazione e
    lo SCARTO rispetto alla somma delle foglie. Lo scarto è MOSTRATO, non
    giudicato: una soglia sarebbe POLICY e vive nel motore."""
    sheet.add(header_cells(TRACE_HEADER))
    first = None
    last = None
    for entry in rows:
        index = sheet.add(entry)
        if entry[1]["kind"] == "n":
            first = index if first is None else first
            last = index
    if not rows:
        sheet.add([cell(empty_note, "s", "derived_neutral"),
                   cell(NOT_APPLICABLE, "s", "derived_neutral")])
        return None
    if first is None:
        return None
    column = column_letter(2)
    sheet.blank()
    total_row = sheet.add([
        cell("Subtotale di presentazione (formula)", "s", "derived_neutral"),
        cell(f"SUM({column}{first}:{column}{last})", "f", "calculated_locked",
             block="out"),
        cell("come le righe", "s", "derived_neutral"),
        cell(ALL_SCENARIOS, "s", "derived_neutral"),
        cell("aggregazione di presentazione", "s", "derived_neutral"),
        cell("(nessun path: e' una SOMMA DI PRESENTAZIONE, non una foglia "
             "canonica)", "s", "derived_neutral"),
        cell("formula di presentazione su celle dello STESSO foglio", "s",
             "derived_neutral"),
    ])
    return {"first": first, "last": last, "total_row": total_row,
            "column": column}


def build_readme(document, tokens, checksum, generated_at, omitted, sheets):
    sheet = SheetBuilder(
        1, "README", "README",
        "natura NON canonica del workbook, versioni, checksum e legenda",
        "financial_plan.calculation_metadata + schema_version")
    sheet.title_block(checksum)
    sheet.add([cell("DICHIARAZIONE DI NON CANONICITA'", "s",
                    "derived_neutral")])
    sheet.add([cell(
        "Questo workbook e' un DERIVATO. La verita' numerica vive ESCLUSIVAMENTE "
        "in " + CANONICAL_NAME + ": il workbook non e' una fonte, non e' "
        "autoritativo e un suo edit NON rientra mai nel canonico.", "s",
        "derived_neutral")])
    sheet.blank()
    sheet.add([cell("schema_version", "s", "derived_neutral"),
               cell(str(document.get("schema_version")
                        or metadata_of(document).get("schema_version")
                        or UNDECLARED), "s", "derived_neutral",
                    canonical_ref="schema_version")])
    sheet.add([cell("canonical_source_checksum", "s", "derived_neutral"),
               cell(checksum, "s", "derived_neutral",
                    name="meta_canonical_checksum",
                    canonical_ref="financial_plan.calculation_metadata."
                                  "output_checksums.base")])
    sheet.add([cell("Generato il (metadato VOLATILE)", "s", "derived_neutral"),
               cell(generated_at, "s", "derived_neutral",
                    name=(tokens.get("workbook") or {}).get(
                        "volatile_named_cell") or "meta_generated_at")])
    sheet.blank()
    sheet.add([cell("MODULI NOT_APPLICABLE, NOMINATI", "s", "derived_neutral")])
    absent = [module_id for module_id in sorted(
        (tokens.get("units") or {}).get("by_module_series") or {})
        if not (modules_of(document).get(module_id) or {})]
    sheet.add([cell("; ".join(absent) or "(nessuno)", "s", "derived_neutral")])
    sheet.blank()
    sheet.add([cell("FOGLI OMESSI (Forma B), NOMINATI", "s",
                    "derived_neutral")])
    sheet.add([cell("; ".join(omitted) or "(nessuno)", "s",
                    "derived_neutral")])
    sheet.blank()
    legend_first = sheet.add([cell("LEGENDA DEGLI STILI", "s",
                                   "derived_neutral")])
    sheet.add(header_cells(("Token", "Etichetta testuale", "ARGB",
                            "Editabile", "Formula ammessa")))
    for token_id in sorted((tokens.get("styles") or {})):
        entry = (tokens.get("styles") or {})[token_id]
        sheet.add([
            cell(token_id, "s", token_id),
            cell(str(entry.get("label")), "s", "derived_neutral"),
            cell(str(entry.get("argb")), "s", "derived_neutral"),
            cell("si" if entry.get("editable") else "no", "s",
                 "derived_neutral"),
            cell("si" if entry.get("formula_allowed") else "no", "s",
                 "derived_neutral"),
        ])
    legend_last = len(sheet.rows)
    sheet.blank()
    sheet.add([cell(str(tokens.get("legend_note") or ""), "s",
                    "derived_neutral")])
    sheet.add([cell("Elenco dei fogli DICHIARATI", "s", "derived_neutral"),
               cell("; ".join(sheets), "s", "derived_neutral")])
    sheet.legend_range = (legend_first, legend_last)
    return sheet


def build_assumptions(document, tokens, checksum, attributes):
    sheet = SheetBuilder(
        2, "Assumptions",
        "Assumptions",
        "celle di assunzione EDITABILI, una per driver, con etichetta testuale",
        "financial_plan.driver_registry.drivers[] + registri governati "
        "(assunzioni, evidenze, fonti)")
    sheet.title_block(checksum)
    sheet.add(header_cells((
        "Driver", "Nome semantico", "Valore (EDITABILE)", "Stato (TESTO)",
        "Unita'", "Finestra / regola", "Applicabilita' di scenario",
        "Path canonico", "Named range")))
    assumption_cells = []
    for driver in sorted(drivers_of(document),
                         key=lambda entry: str(entry.get("driver_id"))):
        driver_id = str(driver.get("driver_id"))
        source_ref = str(driver.get("source_ref"))
        attribute = attributes.get(source_ref) or {}
        value = attribute.get("value")
        if value is None:
            value = NOT_APPLICABLE
        status = str(driver.get("status"))
        token = status_style(tokens, status)
        label = status_label(tokens, status)
        name = "ass_" + re.sub(r"[^0-9A-Za-z]+", "_", driver_id)
        canonical_ref = (
            f"financial_plan.driver_registry.drivers[{driver_id}] -> "
            f"{attribute.get('register') or input_set()[0]}#{source_ref}.value")
        row_index = sheet.add([
            cell(driver_id, "s", "derived_neutral"),
            cell(str(driver.get("semantic_name") or driver.get("role")), "s",
                 "derived_neutral"),
            cell(value, "n" if is_numeric(value) else "s", token,
                 canonical_ref=canonical_ref, name=name, block="in"),
            cell(label, "s", "derived_neutral"),
            cell(str(driver.get("unit") or UNDECLARED), "s", "derived_neutral"),
            cell("/".join([str(driver.get("start_period")),
                           str(driver.get("end_period"))]) +
                 f" · regola {driver.get('timing_rule')}", "s",
                 "derived_neutral"),
            cell(str(driver.get("scenario_coverage") or ALL_SCENARIOS), "s",
                 "derived_neutral"),
            cell(canonical_ref, "s", "derived_neutral"),
            cell(name, "s", "derived_neutral"),
        ])
        assumption_cells.append({
            "driver_id": driver_id, "source_ref": source_ref, "name": name,
            "row": row_index, "column": 3, "style": token, "label": label,
            "canonical_ref": canonical_ref, "value": value,
            "status": status, "driver": driver, "attribute": attribute,
        })
    if not assumption_cells:
        sheet.add([cell("nessun driver nel registro canonico", "s",
                        "derived_neutral")])
    sheet.assumption_cells = assumption_cells
    return sheet


def build_calendar(document, tokens, checksum):
    sheet = SheetBuilder(
        3, "Calendar", "Calendar",
        "periodi, frazioni e conversioni DICHIARATE dal canonico",
        "financial_plan.results.calendar")
    sheet.title_block(checksum)
    calendar = calendar_of(document)
    rows = []
    for key in sorted(calendar):
        value = calendar[key]
        if isinstance(value, (dict, list)):
            rows.append(value_row(
                f"calendar.{key}", json.dumps(value, sort_keys=True,
                                              ensure_ascii=True),
                UNDECLARED, ALL_SCENARIOS, "struttura canonica",
                f"financial_plan.results.calendar.{key}"))
            continue
        rows.append(value_row(
            f"calendar.{key}", value, UNDECLARED, ALL_SCENARIOS,
            "scalare canonico", f"financial_plan.results.calendar.{key}"))
    add_value_table(sheet, rows, "calendario non prodotto dal canonico")
    return sheet


def build_module_sheet(number, name, document, tokens, checksum, module_ids,
                       purpose, source, with_lines=False):
    sheet = SheetBuilder(number, name, sheet_key(name), purpose, source)
    sheet.title_block(checksum)
    rows = []
    for module_id in module_ids:
        rows.extend(module_series_rows(document, tokens, module_id))
        rows.extend(module_metric_rows(document, tokens, module_id))
        if with_lines:
            rows.extend(module_line_rows(document, tokens, module_id))
    add_value_table(sheet, rows, f"moduli {', '.join(module_ids)} non prodotti")
    return sheet


def build_scenarios(document, tokens, checksum):
    sheet = SheetBuilder(
        11, "Scenarios", "Scenarios",
        "selettore di scenario e confronto sui SOLI scenari PRODOTTI",
        "financial_plan.results.scenarios")
    sheet.title_block(checksum)
    scenarios = scenarios_of(document)
    produced = [name for name in SCENARIO_IDS
                if (scenarios.get(name) or {}).get("series")]
    coverage = scenarios.get("coverage") or {}
    level = str(coverage.get("level") or UNDECLARED)
    sheet.add([cell("Livello di copertura (canonico)", "s", "derived_neutral"),
               cell(level, "s", "calculated_locked",
                    canonical_ref="financial_plan.results.scenarios.coverage."
                                  "level", block="out")])
    sheet.add([cell("Scenari PRODOTTI (elenco CHIUSO del selettore)", "s",
                    "derived_neutral"),
               cell("; ".join(produced) or "(nessuno)", "s",
                    "derived_neutral")])
    # Il SELETTORE vive in una COLONNA DEDICATA: il blocco di INPUT e quello
    # di OUTPUT devono essere DISGIUNTI, e collocarlo nella colonna
    # dei valori ufficiali renderebbe i due blocchi sovrapposti.
    selector_row = sheet.add([
        cell("SELETTORE DI SCENARIO (unica cella editabile del foglio)", "s",
             "derived_neutral"),
        cell("il selettore governa la PRESENTAZIONE, non il calcolo: "
             "cambiarlo non cambia alcun numero", "s", "derived_neutral"),
        cell("INPUT CONFERMATO", "s", "derived_neutral"),
        cell(produced[0] if produced else NOT_APPLICABLE, "s",
             "confirmed_input", name="scenario_selector", block="in"),
    ])
    sheet.blank()
    for scenario_id in SCENARIO_IDS:
        if scenario_id in produced:
            continue
        entry = scenarios.get(scenario_id) or {}
        sheet.add([
            cell(f"scenario {scenario_id}", "s", "derived_neutral"),
            cell(NOT_APPLICABLE, "s", "unresolved_blocking", block="out"),
            cell("NOT_APPLICABLE DICHIARATO — non serie vuota, non copia del "
                 "Base", "s", "derived_neutral"),
            cell(str(entry.get("not_applicable_reason")
                     or "motivazione non dichiarata dal canonico"), "s",
                 "derived_neutral"),
        ])
    sheet.blank()
    rows = []
    for scenario_id in produced:
        entry = scenarios.get(scenario_id) or {}
        for module_id in sorted(entry.get("series") or {}):
            series = (entry.get("series") or {})[module_id]
            for index in sorted(series, key=period_key):
                rows.append(value_row(
                    f"{scenario_id} · {module_id} · periodo {index}",
                    series[index], unit_for_module(tokens, module_id),
                    scenario_id, f"periodo {index}",
                    ".".join([f"financial_plan.results.scenarios.{scenario_id}",
                              "series", module_id, index])))
    for field in ("ratio", "threshold"):
        if coverage.get(field) is not None:
            rows.append(value_row(
                f"copertura · {field}", coverage[field],
                ((tokens.get("units") or {}).get("coverage") or {}).get(
                    field, UNDECLARED), ALL_SCENARIOS, "scalare canonico",
                f"financial_plan.results.scenarios.coverage.{field}"))
    add_value_table(sheet, rows, "nessuno scenario prodotto")
    sheet.selector = {"row": selector_row, "column": 4, "produced": produced,
                      "level": level,
                      "uncovered": sorted(coverage.get("uncovered_driver_refs")
                                          or []),
                      "proposed_condition_ref":
                          coverage.get("proposed_condition_ref")}
    return sheet


def build_break_even(document, tokens, checksum):
    sheet = SheetBuilder(
        13, "Break-even", "Break_even",
        "volume, ricavo, primo periodo ed esito canonico del pareggio",
        "financial_plan.results.modules.break_even")
    sheet.title_block(checksum)
    module = modules_of(document).get("break_even") or {}
    table = (tokens.get("units") or {}).get("by_break_even_field") or {}
    rows = []
    for field in sorted(table):
        if field == "fixed_costs_per_period":
            continue
        value = module.get(field)
        rows.append(value_row(
            f"break_even.{field}",
            NOT_APPLICABLE if value is None else value,
            table[field], "base", "scalare canonico",
            f"financial_plan.results.modules.break_even.{field}"))
    outcome = module.get("outcome")
    rows.append(value_row(
        "break_even.outcome", NOT_APPLICABLE if outcome is None else outcome,
        UNDECLARED, "base", "esito canonico",
        "financial_plan.results.modules.break_even.outcome"))
    for index in sorted(module.get("fixed_costs_per_period") or {},
                        key=period_key):
        rows.append(value_row(
            f"break_even.fixed_costs_per_period · periodo {index}",
            (module.get("fixed_costs_per_period") or {})[index],
            table.get("fixed_costs_per_period", UNDECLARED), "base",
            f"periodo {index}",
            ".".join(["financial_plan.results.modules.break_even",
                      "fixed_costs_per_period", index])))
    add_value_table(sheet, rows, "break-even non prodotto")
    return sheet


def build_milestones(document, tokens, checksum):
    sheet = SheetBuilder(
        14, "Milestones", "Milestones",
        "stato di copertura per MIL-* e residuo non mappato",
        "financial_plan.results.modules.milestone_coverage")
    sheet.title_block(checksum)
    module = modules_of(document).get("milestone_coverage") or {}
    rows = []
    for position, entry in enumerate(module.get("milestones") or []):
        for field in sorted(entry):
            value = entry[field]
            if isinstance(value, (dict, list)):
                continue
            rows.append(value_row(
                " · ".join([str(entry.get("milestone_ref")), field]), value,
                UNDECLARED if not is_numeric(value) else "EUR", "base",
                "scalare canonico",
                ".".join(["financial_plan.results.modules.milestone_coverage",
                          f"milestones[{position}]", field])))
    residual = module.get("unmapped_residual")
    if residual is not None:
        rows.append(value_row(
            "milestone_coverage.unmapped_residual", residual, "EUR", "base",
            "scalare canonico",
            "financial_plan.results.modules.milestone_coverage."
            "unmapped_residual"))
    add_value_table(sheet, rows, "copertura milestone non prodotta")
    return sheet


def build_kpi(document, tokens, checksum):
    sheet = SheetBuilder(
        15, "KPI", "KPI",
        "gli OTTO indicatori, con i NOT_APPLICABLE NOMINATI",
        "financial_plan.results.modules.kpi.indicators")
    sheet.title_block(checksum)
    indicators = (modules_of(document).get("kpi") or {}).get(
        "indicators") or {}
    sheet.add(header_cells(TRACE_HEADER))
    for kpi_id in KPI_IDS:
        entry = indicators.get(kpi_id) or {}
        value = entry.get("value")
        unit = str(entry.get("unit") or UNDECLARED)
        path = ("financial_plan.results.modules.kpi.indicators."
                f"{kpi_id}.value")
        if value is None:
            # `NOT_APPLICABLE` resta VISIBILMENTE non applicabile, NOMINATO
            # con la propria motivazione: mai zero, mai una cella vuota.
            sheet.add([
                cell(kpi_id, "s", "derived_neutral"),
                cell(NOT_APPLICABLE, "s", "unresolved_blocking",
                     canonical_ref=path, block="out"),
                cell(unit, "s", "derived_neutral"),
                cell("base", "s", "derived_neutral"),
                cell("scalare canonico", "s", "derived_neutral"),
                cell(path, "s", "derived_neutral"),
                cell(str(entry.get("not_applicable_reason")
                         or "non calcolabile: driver assente"), "s",
                     "derived_neutral"),
            ])
            continue
        sheet.add(value_row(kpi_id, value, unit, "base", "scalare canonico",
                            path))
    return sheet


def build_reconciliation(document, tokens, checksum):
    sheet = SheetBuilder(
        16, "Reconciliation", "Reconciliation",
        "ogni REC-* del canonico, ANCHE quando passa, con la tolleranza "
        "PUBBLICATA",
        "financial_plan.reconciliations")
    sheet.title_block(checksum)
    sheet.add(header_cells(TRACE_HEADER))
    entries = reconciliations_of(document)
    for rec_id in sorted(entries):
        entry = entries[rec_id] or {}
        residual = entry.get("residual")
        tolerance = entry.get("tolerance")
        unit = str(entry.get("tolerance_unit") or UNDECLARED)
        status = str(entry.get("status") or UNDECLARED)
        base = f"financial_plan.reconciliations.{rec_id}"
        residual_row = sheet.add(value_row(
            f"{rec_id} · residuo", NOT_APPLICABLE if residual is None
            else residual, unit, "base", "scalare canonico",
            f"{base}.residual", note=f"esito canonico {status}"))
        sheet.add(value_row(
            f"{rec_id} · tolleranza PUBBLICATA",
            NOT_APPLICABLE if tolerance is None else tolerance, unit, "base",
            "scalare canonico", f"{base}.tolerance",
            note="tolleranza PUBBLICATA dal canonico, mai una diversa"))
        # CROSS-CHECK di presentazione: il residuo in valore assoluto, da
        # confrontare con la tolleranza PUBBLICATA nella riga precedente.
        #
        # La tolleranza e' pubblicata dal canonico CON la propria unita'
        # («EUR 0.01»). Decomporla per ricavarne la parte numerica
        # produrrebbe una cella il cui valore NON coincide piu' con la foglia
        # canonica che dichiara: sarebbe un valore RESO diverso dal canonico,
        # cioe' esattamente il difetto che `XREC-03` esiste per rilevare.
        # Il workbook percio' MOSTRA il residuo assoluto e la tolleranza
        # verbatim, e NON conia una soglia numerica propria.
        if is_numeric(residual):
            sheet.add([
                cell(f"{rec_id} · residuo in valore assoluto", "s",
                     "derived_neutral"),
                cell(f"ABS(B{residual_row})", "f", "calculated_locked",
                     block="out"),
                cell(unit, "s", "derived_neutral"),
                cell("base", "s", "derived_neutral"),
                cell("cross-check di presentazione", "s", "derived_neutral"),
                cell("(nessun path: e' un CROSS-CHECK di presentazione, non "
                     "una foglia canonica)", "s", "derived_neutral"),
                cell("da confrontare con la tolleranza PUBBLICATA della riga "
                     f"precedente; esito canonico gia' dichiarato: {status}",
                     "s", "derived_neutral"),
            ])
        else:
            sheet.add([
                cell(f"{rec_id} · residuo in valore assoluto", "s",
                     "derived_neutral"),
                cell(NOT_APPLICABLE, "s", "unresolved_blocking", block="out"),
                cell(unit, "s", "derived_neutral"),
                cell("base", "s", "derived_neutral"),
                cell("cross-check di presentazione", "s", "derived_neutral"),
                cell("(nessun path: e' un CROSS-CHECK di presentazione)", "s",
                     "derived_neutral"),
                cell("residuo non numerico: il cross-check e' NOT_APPLICABLE "
                     "DICHIARATO, mai zero", "s", "derived_neutral"),
            ])
    if not entries:
        sheet.add([cell("nessuna riconciliazione pubblicata dal canonico", "s",
                        "derived_neutral")])
    return sheet


def tolerance_amount(tolerance):
    """La parte NUMERICA di una tolleranza pubblicata come «EUR 0.01».

    E' una DECOMPOSIZIONE TESTUALE del valore canonico, non un calcolo e non
    una soglia coniata: se nessun token e' numerico la funzione restituisce
    `None` e la verifica resta `NOT_APPLICABLE` DICHIARATO.
    """
    if tolerance is None:
        return None
    for token in str(tolerance).replace(",", " ").split():
        if is_numeric(token):
            return token
    return None


def headline_metrics(document, tokens):
    """Le NOVE metriche di testata, DICHIARATE in `style_tokens.json`. Ogni
    metrica è una FOGLIA canonica raggiunta da un path: nessuna è ricalcolata,
    e una metrica non prodotta è `NOT_APPLICABLE` NOMINATO."""
    modules = modules_of(document)
    cash = (modules.get("cash_flow") or {}).get("metrics") or {}
    resolved = {}

    def last_series(module_id):
        series = (modules.get(module_id) or {}).get("series") or {}
        if not series:
            return None, None
        index = sorted(series, key=period_key)[-1]
        return series[index], (f"financial_plan.results.modules.{module_id}"
                               f".series.{index}")

    def last_metric(module_id, prefix):
        metrics = (modules.get(module_id) or {}).get("metrics") or {}
        names = [name for name in metrics
                 if strip_period_suffix(name)[0] == prefix]
        if not names:
            return None, None
        name = sorted(names, key=lambda key: period_key(
            strip_period_suffix(key)[1] or ""))[-1]
        return metrics[name], (f"financial_plan.results.modules.{module_id}"
                               f".metrics.{name}")

    resolved["revenue"] = last_series("revenue")
    resolved["gross_margin"] = last_series("gross_margin")
    resolved["ebitda"] = last_metric("pnl", "ebitda")
    resolved["ending_cash"] = last_metric("cash_flow", "ending")
    resolved["burn"] = last_metric("cash_flow", "burn")
    resolved["runway"] = last_metric("runway", "runway_to_zero")
    break_even = modules.get("break_even") or {}
    resolved["break_even"] = (
        break_even.get("first_break_even_period"),
        "financial_plan.results.modules.break_even.first_break_even_period")
    resolved["funding_gap"] = last_metric("funding_gap", "funding_gap_to_zero")
    coverage_indicator = ((modules.get("kpi") or {}).get("indicators")
                          or {}).get("milestone_coverage") or {}
    resolved["milestone_coverage"] = (
        coverage_indicator.get("value"),
        "financial_plan.results.modules.kpi.indicators."
        "milestone_coverage.value")
    if not cash:
        pass
    out = {}
    for entry in tokens.get("headline_metrics") or []:
        metric_id = entry["id"]
        value, path = resolved.get(metric_id, (None, None))
        out[metric_id] = {
            "label": entry["label"],
            "value": NOT_APPLICABLE if value is None else value,
            "canonical_ref": path or f"(nessun path: {metric_id} non prodotto)",
        }
    return out


def build_dashboard(document, tokens, checksum, metrics, omitted, selector):
    sheet = SheetBuilder(
        17, "Dashboard", "Dashboard",
        "le NOVE metriche di testata, lo stato delle riconciliazioni, i "
        "warning e gli input irrisolti",
        "metriche di testata + financial_plan.validation")
    sheet.title_block(checksum)
    sheet.add([cell("Scenario mostrato (segue il selettore)", "s",
                    "derived_neutral"),
               cell("scenario_selector", "f", "calculated_locked",
                    block="out")])
    sheet.blank()
    sheet.add(header_cells(TRACE_HEADER))
    for entry in tokens.get("headline_metrics") or []:
        metric = metrics[entry["id"]]
        value = metric["value"]
        if is_numeric(value):
            sheet.add(value_row(metric["label"], value, UNDECLARED, "base",
                                "metrica di testata",
                                metric["canonical_ref"]))
            continue
        sheet.add([
            cell(metric["label"], "s", "derived_neutral"),
            cell(NOT_APPLICABLE, "s", "unresolved_blocking",
                 canonical_ref=metric["canonical_ref"], block="out"),
            cell(UNDECLARED, "s", "derived_neutral"),
            cell("base", "s", "derived_neutral"),
            cell("metrica di testata", "s", "derived_neutral"),
            cell(metric["canonical_ref"], "s", "derived_neutral"),
            cell("metrica NON prodotta dal canonico: NOT_APPLICABLE "
                 "DICHIARATO, mai zero", "s", "derived_neutral"),
        ])
    sheet.blank()
    sheet.add([cell("FOGLI OMESSI (Forma B), NOMINATI", "s",
                    "derived_neutral"),
               cell("; ".join(omitted) or "(nessuno)", "s",
                    "derived_neutral")])
    sheet.blank()
    sheet.add([cell("STATO DELLE RICONCILIAZIONI", "s", "derived_neutral")])
    entries = reconciliations_of(document)
    for rec_id in sorted(entries):
        sheet.add([cell(rec_id, "s", "derived_neutral"),
                   cell(str((entries[rec_id] or {}).get("status")
                            or UNDECLARED), "s", "derived_neutral")])
    sheet.blank()
    validation = validation_of(document)
    readiness = validation.get("investor_readiness") or {}
    sheet.add([cell("investor_readiness.status", "s", "derived_neutral"),
               cell(str(readiness.get("status") or UNDECLARED), "s",
                    "calculated_locked",
                    canonical_ref="financial_plan.validation."
                                  "investor_readiness.status", block="out")])
    for reason in readiness.get("blocking_reasons") or []:
        sheet.add([cell("ragione di blocco", "s", "derived_neutral"),
                   cell(str(reason.get("code")), "s", "derived_neutral"),
                   cell(str(reason.get("message") or ""), "s",
                        "derived_neutral")])
    sheet.blank()
    sheet.add([cell("WARNING E INPUT IRRISOLTI", "s", "derived_neutral")])
    for check in validation.get("checks") or []:
        sheet.add([cell(str(check.get("check_id") or check.get("code")), "s",
                        "derived_neutral"),
                   cell(str(check.get("severity") or UNDECLARED), "s",
                        "derived_neutral"),
                   cell(str(check.get("message") or ""), "s",
                        "derived_neutral")])
    sheet.blank()
    sheet.add([cell("Copertura di scenario", "s", "derived_neutral"),
               cell(selector["level"], "s", "derived_neutral")])
    sheet.add([cell("Driver privi di terna, NOMINATI", "s", "derived_neutral"),
               cell("; ".join(selector["uncovered"]) or "(nessuno)", "s",
                    "derived_neutral")])
    sheet.add([cell("Condizione proposta dal canonico", "s",
                    "derived_neutral"),
               cell(str(selector["proposed_condition_ref"]
                        or "non dichiarata"), "s", "derived_neutral")])
    return sheet


def build_register(document, tokens, checksum, assumption_cells, attributes):
    fields = (tokens.get("workbook") or {}).get(
        "assumption_register_fields") or []
    sheet = SheetBuilder(
        18, "Assumption Register", "Assumption_Register",
        "i SEDICI campi del registro delle assunzioni, una riga per CELLA "
        "di assunzione, con workbook_location e canonical_ref",
        "financial_plan.driver_registry.drivers[] + registri governati "
        "(assunzioni, evidenze, fonti)")
    sheet.title_block(checksum)
    sheet.add(header_cells(fields))
    rows = []
    for entry in assumption_cells:
        driver = entry["driver"]
        attribute = entry["attribute"]
        location = f"Assumptions!{entry['name']}"
        values = {
            "assumption_id": entry["driver_id"],
            "driver_role": str(driver.get("role") or UNDECLARED),
            "description": " — ".join([
                str(driver.get("semantic_name") or driver.get("role")),
                str(driver.get("rationale") or "razionale non dichiarato")]),
            "value": entry["value"],
            "unit": str(driver.get("unit") or UNDECLARED),
            "period_or_effective_date": "/".join([
                str(driver.get("start_period")), str(driver.get("end_period")),
                str(driver.get("timing_rule"))]),
            "scenario_applicability": str(driver.get("scenario_coverage")
                                          or ALL_SCENARIOS),
            "source_status_and_provenance": " · ".join([
                f"stato {driver.get('status')}",
                f"source_type {driver.get('source_type') or UNDECLARED}",
                f"priorita' {driver.get('source_priority') or UNDECLARED}",
                f"binding {driver.get('binding_method') or UNDECLARED}",
                f"evidenza {attribute.get('evidence_classification') or UNDECLARED}"]),
            "rationale": str(driver.get("rationale")
                             or attribute.get("rationale")
                             or "razionale non dichiarato"),
            "owner": str(attribute.get("owner") or UNDECLARED),
            "validation_status": str(attribute.get("validation_status")
                                     or UNDECLARED),
            "workbook_location": location,
            "canonical_ref": entry["canonical_ref"],
            "materiality": str(driver.get("materiality") or UNDECLARED),
            "validation_action": str(attribute.get("validation_action")
                                     or UNDECLARED),
            "last_updated": str(attribute.get("last_updated") or UNDECLARED),
        }
        sheet.add([cell(values.get(field, UNDECLARED), "s", "derived_neutral")
                   for field in fields])
        values["style"] = entry["style"]
        values["status_label"] = entry["label"]
        rows.append(values)
    if not rows:
        sheet.add([cell("nessuna cella di assunzione", "s", "derived_neutral")])
    sheet.register_rows = rows
    return sheet


def build_sheets(document, tokens, checksum, generated_at, governed):
    declared = [entry["name"] for entry in
                (tokens.get("workbook") or {}).get("sheets") or []]
    attributes = governed["attributes"]
    assumptions = build_assumptions(document, tokens, checksum, attributes)
    scenarios = build_scenarios(document, tokens, checksum)
    metrics = headline_metrics(document, tokens)
    omitted = []
    register = build_register(document, tokens, checksum,
                              assumptions.assumption_cells, attributes)
    readme = build_readme(document, tokens, checksum, generated_at, omitted,
                          declared)
    sheets = [
        readme,
        assumptions,
        build_calendar(document, tokens, checksum),
        build_module_sheet(4, "Revenue", document, tokens, checksum,
                           ("revenue",), "serie e righe di ricavo",
                           "financial_plan.results.modules.revenue",
                           with_lines=True),
        build_module_sheet(5, "COGS", document, tokens, checksum,
                           ("cogs", "gross_margin"),
                           "costi variabili e margine lordo",
                           "financial_plan.results.modules.cogs + "
                           ".gross_margin", with_lines=True),
        build_module_sheet(6, "Headcount", document, tokens, checksum,
                           ("headcount",), "FTE come LIVELLI, mai come flussi",
                           "financial_plan.results.modules.headcount"),
        build_module_sheet(7, "Payroll", document, tokens, checksum,
                           ("payroll",), "costo del personale per periodo",
                           "financial_plan.results.modules.payroll",
                           with_lines=True),
        build_module_sheet(8, "Opex", document, tokens, checksum, ("opex",),
                           "costi operativi per categoria",
                           "financial_plan.results.modules.opex",
                           with_lines=True),
        build_module_sheet(9, "P&L", document, tokens, checksum, ("pnl",),
                           "conto economico previsionale",
                           "financial_plan.results.modules.pnl",
                           with_lines=True),
        build_module_sheet(10, "Cash Flow", document, tokens, checksum,
                           ("cash_flow",),
                           "roll-forward di cassa e burn",
                           "financial_plan.results.modules.cash_flow"),
        scenarios,
        build_module_sheet(12, "Runway & Funding Gap", document, tokens,
                           checksum, ("runway", "cash_buffer", "funding_gap"),
                           "le QUATTRO metriche di cassa, DISTINTE",
                           "financial_plan.results.modules.runway + "
                           ".cash_buffer + .funding_gap"),
        build_break_even(document, tokens, checksum),
        build_milestones(document, tokens, checksum),
        build_kpi(document, tokens, checksum),
        build_reconciliation(document, tokens, checksum),
        build_dashboard(document, tokens, checksum, metrics, omitted,
                        scenarios.selector),
        register,
    ]
    return sheets, metrics, omitted


# --------------------------------------------------------------------------
# Emissione OOXML — SOLA libreria standard
# --------------------------------------------------------------------------


STYLE_ORDER = ("calculated_locked", "derived_neutral", "assumption_to_validate",
               "confirmed_input", "unresolved_blocking")


def style_index(token_id):
    """Indice di `cellXfs`. 0 è il default; gli stili DICHIARATI seguono
    nell'ordine di `STYLE_ORDER`."""
    if token_id in STYLE_ORDER:
        return STYLE_ORDER.index(token_id) + 1
    return 0


def styles_xml(tokens):
    styles = tokens.get("styles") or {}
    fills = ['<fill><patternFill patternType="none"/></fill>',
             '<fill><patternFill patternType="gray125"/></fill>']
    for token_id in STYLE_ORDER:
        argb = str((styles.get(token_id) or {}).get("argb") or "FFFFFFFF")
        pattern = str((styles.get(token_id) or {}).get("pattern_fill")
                      or "solid")
        fills.append(
            f'<fill><patternFill patternType="{escape(pattern)}">'
            f'<fgColor rgb="{escape(argb)}"/><bgColor indexed="64"/>'
            f'</patternFill></fill>')
    xfs = ['<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>']
    for position, token_id in enumerate(STYLE_ORDER):
        editable = bool((styles.get(token_id) or {}).get("editable"))
        locked = "0" if editable else "1"
        xfs.append(
            f'<xf numFmtId="0" fontId="0" fillId="{position + 2}" '
            f'borderId="0" xfId="0" applyFill="1" applyProtection="1">'
            f'<protection locked="{locked}"/></xf>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font>'
        '</fonts>'
        f'<fills count="{len(fills)}">{"".join(fills)}</fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/>'
        '<diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" '
        'borderId="0"/></cellStyleXfs>'
        f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" '
        'builtinId="0"/></cellStyles>'
        '</styleSheet>')


def sheet_xml(sheet):
    lines = []
    for row_index, cells in enumerate(sheet.rows, start=1):
        if not cells:
            continue
        rendered = []
        for column_index, entry in enumerate(cells, start=1):
            ref = f"{column_letter(column_index)}{row_index}"
            index = style_index(entry["style"])
            if entry["kind"] == "f":
                rendered.append(
                    f'<c r="{ref}" s="{index}">'
                    f'<f>{escape(str(entry["value"]))}</f></c>')
            elif entry["kind"] == "n":
                rendered.append(
                    f'<c r="{ref}" s="{index}">'
                    f'<v>{escape(str(entry["value"]))}</v></c>')
            else:
                rendered.append(
                    f'<c r="{ref}" s="{index}" t="inlineStr"><is><t '
                    f'xml:space="preserve">{escape(str(entry["value"]))}'
                    f'</t></is></c>')
        lines.append(f'<row r="{row_index}">{"".join(rendered)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main">'
        f'<sheetData>{"".join(lines)}</sheetData>'
        '<sheetProtection sheet="1" objects="1" scenarios="1" '
        'selectLockedCells="1" selectUnlockedCells="1"/>'
        '</worksheet>')


def quote_sheet_name(name):
    """Nome di foglio dentro un riferimento: quotato quando necessario."""
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", name):
        return name
    return "'" + name.replace("'", "''") + "'"


def workbook_xml(sheets, defined_names):
    entries = []
    for position, sheet in enumerate(sheets, start=1):
        entries.append(
            f'<sheet name="{escape(sheet.name)}" sheetId="{position}" '
            f'r:id="rId{position}"/>')
    names = []
    for name in sorted(defined_names):
        names.append(f'<definedName name="{escape(name)}">'
                     f'{escape(defined_names[name])}</definedName>')
    defined = f'<definedNames>{"".join(names)}</definedNames>' if names else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships">'
        f'<sheets>{"".join(entries)}</sheets>'
        f'{defined}'
        '<calcPr calcId="0" fullCalcOnLoad="1"/>'
        '</workbook>')


def content_types_xml(sheets):
    overrides = [
        '<Override PartName="/xl/workbook.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        '<Override PartName="/docProps/core.xml" ContentType="application/'
        'vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    for position in range(1, len(sheets) + 1):
        overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{position}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.worksheet+xml"/>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
        'content-types">'
        '<Default Extension="rels" ContentType="application/vnd.'
        'openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'{"".join(overrides)}'
        '</Types>')


def root_rels_xml():
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
        '2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/'
        'package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/extended-properties" '
        'Target="docProps/app.xml"/>'
        '</Relationships>')


def workbook_rels_xml(sheets):
    entries = []
    for position in range(1, len(sheets) + 1):
        entries.append(
            f'<Relationship Id="rId{position}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            f'relationships/worksheet" Target="worksheets/sheet{position}.xml"/>')
    entries.append(
        f'<Relationship Id="rId{len(sheets) + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/styles" Target="styles.xml"/>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
        f'2006/relationships">{"".join(entries)}</Relationships>')


def core_xml(checksum):
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
        'package/2006/metadata/core-properties" xmlns:dc="http://purl.org/'
        'dc/elements/1.1/">'
        '<dc:title>financial-model</dc:title>'
        f'<dc:description>derivato NON canonico · checksum {escape(checksum)}'
        '</dc:description>'
        '</cp:coreProperties>')


def app_xml():
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/'
        'officeDocument/2006/extended-properties">'
        f'<Application>{EXPORTER_NAME}</Application></Properties>')


def collect_defined_names(sheets):
    """Named range: le celle nominate e i BLOCCHI `in_`/`out_` di ogni foglio.

    Nessun numero di riga è mai hardcodato fra fogli: ogni riferimento
    inter-foglio passa da qui.
    """
    names = {}
    for sheet in sheets:
        quoted = quote_sheet_name(sheet.name)
        blocks = {"in": [], "out": []}
        for row_index, cells in enumerate(sheet.rows, start=1):
            for column_index, entry in enumerate(cells, start=1):
                ref = f"${column_letter(column_index)}${row_index}"
                if entry.get("name"):
                    names[entry["name"]] = f"{quoted}!{ref}"
                if entry.get("block") in blocks:
                    blocks[entry["block"]].append((row_index, column_index))
        for kind, positions in blocks.items():
            if not positions:
                continue
            rows = [item[0] for item in positions]
            columns = [item[1] for item in positions]
            top = min(rows)
            bottom = max(rows)
            left = min(columns)
            right = max(columns)
            names[f"{kind}_{sheet.key}"] = (
                f"{quoted}!${column_letter(left)}${top}:"
                f"${column_letter(right)}${bottom}")
        legend = getattr(sheet, "legend_range", None)
        if legend:
            names["legend_styles"] = (
                f"{quoted}!$A${legend[0]}:$E${legend[1]}")
    return names


def emit_package(sheets, tokens, checksum, defined_names):
    """Pacchetto OOXML DETERMINISTICO: nessun timestamp di ZIP variabile, così
    che due esecuzioni differiscano SOLTANTO per i metadati DICHIARATI come
    volatili."""
    parts = [
        ("[Content_Types].xml", content_types_xml(sheets)),
        ("_rels/.rels", root_rels_xml()),
        ("docProps/core.xml", core_xml(checksum)),
        ("docProps/app.xml", app_xml()),
        ("xl/workbook.xml", workbook_xml(sheets, defined_names)),
        ("xl/_rels/workbook.xml.rels", workbook_rels_xml(sheets)),
        ("xl/styles.xml", styles_xml(tokens)),
    ]
    for position, sheet in enumerate(sheets, start=1):
        parts.append((f"xl/worksheets/sheet{position}.xml", sheet_xml(sheet)))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in parts:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, payload.encode("utf-8"))
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def build_report(sheets, tokens, checksum, metrics, omitted, governed,
                 defined_names, generated_at, workbook_path, payload):
    cells = []
    for sheet in sheets:
        for row_index, entries in enumerate(sheet.rows, start=1):
            for column_index, entry in enumerate(entries, start=1):
                cells.append({
                    "sheet": sheet.name,
                    "ref": f"{column_letter(column_index)}{row_index}",
                    "kind": entry["kind"],
                    "style": entry["style"],
                    "value": None if entry["kind"] == "f" else
                             str(entry["value"]),
                    "formula": str(entry["value"]) if entry["kind"] == "f"
                               else None,
                    "canonical_ref": entry["canonical_ref"],
                    "name": entry["name"],
                    "block": entry["block"],
                })
    assumptions = [sheet for sheet in sheets if sheet.name == "Assumptions"][0]
    register = [sheet for sheet in sheets
                if sheet.name == "Assumption Register"][0]
    selector_sheet = [sheet for sheet in sheets if sheet.name == "Scenarios"][0]
    return {
        "exporter": EXPORTER_NAME,
        "workbook": str(workbook_path),
        "workbook_sha256": sha256_bytes(payload),
        "canonical_source_checksum": checksum,
        "generated_at": generated_at,
        "volatile_named_cell": (tokens.get("workbook") or {}).get(
            "volatile_named_cell"),
        "read_set": governed["read_set"],
        "input_set_declared": governed["input_set_declared"],
        "registers_present": governed["registers_present"],
        "governed_checks": governed["checks"],
        "fingerprint_source": governed["fingerprint_source"],
        "sheets": [{"number": sheet.number, "name": sheet.name,
                    "key": sheet.key, "rows": len(sheet.rows)}
                   for sheet in sheets],
        "declared_sheets": [entry["name"] for entry in
                            (tokens.get("workbook") or {}).get("sheets") or []],
        "omitted_sheets": omitted,
        "named_ranges": defined_names,
        "cells": cells,
        "assumption_cells": [
            {"driver_id": entry["driver_id"], "name": entry["name"],
             "ref": f"{column_letter(entry['column'])}{entry['row']}",
             "sheet": "Assumptions", "style": entry["style"],
             "label": entry["label"], "canonical_ref": entry["canonical_ref"],
             "status": entry["status"], "value": str(entry["value"])}
            for entry in assumptions.assumption_cells],
        "register_rows": register.register_rows,
        "register_fields": (tokens.get("workbook") or {}).get(
            "assumption_register_fields") or [],
        "headline_metrics": metrics,
        "scenario_selector": {
            "named_range": "scenario_selector",
            "produced": selector_sheet.selector["produced"],
            "level": selector_sheet.selector["level"],
            "allowed": selector_sheet.selector["produced"],
        },
        "allowed_formula_functions": (tokens.get("workbook") or {}).get(
            "allowed_formula_functions") or [],
        "refusal": None,
    }


# --------------------------------------------------------------------------
# Esecuzione
# --------------------------------------------------------------------------


def export(canonical_path, project, inject_failure=None):
    refuse_real_project(project)
    tokens = load_style_tokens()
    document = load_canonical(canonical_path)
    checksum = canonical_checksum(document)
    governed = read_governed_inputs(project, drivers_of(document))
    # METADATO VOLATILE, e l'UNICO permesso. E' reso in forma
    # TESTUALE ISO-8601, mai numerica: un timestamp numerico in una cella di
    # valore sarebbe indistinguibile da una grandezza economica congelata, ed
    # e' ammesso SOLO come metadato, mai come input di una formula.
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    sheets, metrics, omitted = build_sheets(document, tokens, checksum,
                                            generated_at, governed)
    declared = [entry["name"] for entry in
                (tokens.get("workbook") or {}).get("sheets") or []]
    produced = [sheet.name for sheet in sheets]
    missing = [name for name in declared if name not in produced]
    if missing:
        raise ExportRefusal(
            CODE_INCOMPLETE, WORKBOOK_NAME,
            f"fogli obbligatori ASSENTI e non nominati: {missing}")
    defined_names = collect_defined_names(sheets)
    if inject_failure == "emit":
        raise ExportRefusal(CODE_INCOMPLETE, WORKBOOK_NAME,
                            "fallimento INIETTATO in emissione (sonda)")
    payload = emit_package(sheets, tokens, checksum, defined_names)
    workbook_path = Path(project, STAGE10, WORKBOOK_NAME)
    if inject_failure == "publish":
        raise ExportRefusal(CODE_INCOMPLETE, str(workbook_path),
                            "fallimento INIETTATO in pubblicazione (sonda)")
    atomic_write_bytes(workbook_path, payload)
    return build_report(sheets, tokens, checksum, metrics, omitted, governed,
                        defined_names, generated_at, workbook_path, payload)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(
        prog="export_financial_model.py", add_help=True,
        description="Esporta financial-model.xlsx dal documento canonico "
                    "dello Stage 10.")
    parser.add_argument("--canonical", required=False)
    parser.add_argument("--project", required=False)
    parser.add_argument("--inject-failure", choices=("emit", "publish"),
                        default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    if not args.canonical or not args.project:
        print("USAGE ERROR: --canonical e --project sono obbligatori",
              file=sys.stderr)
        return 2
    try:
        report = export(args.canonical, args.project, args.inject_failure)
    except ExportRefusal as exc:
        print(json.dumps({"exporter": EXPORTER_NAME, "workbook": None,
                          "refusal": {"code": exc.code, "path": exc.path,
                                      "message": exc.message}},
                         indent=2, ensure_ascii=True, sort_keys=True))
        return 1
    except ExportUsageError as exc:                  # pragma: no cover
        print(f"USAGE ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
