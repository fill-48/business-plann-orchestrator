#!/usr/bin/env python3
"""Stage 10, GATE 2: coerenza TRIANGOLARE dei derivati e ROLLBACK COORDINATO.

Due responsabilita', e una sola sede per ciascuna:

1. **Coerenza triangolare** `XREC-02 ... XREC-06` fra i tre artefatti

   ```text
   structured-output.json      <- SOLA autorita' numerica
   financial-plan.md
   financial-model.xlsx
   ```

   Il confronto e' **triangolare, non a due**: capitolo e workbook sono
   confrontati **ognuno col canonico E fra loro**. Un disaccordo
   capitolo-workbook con entrambi coerenti col canonico e' impossibile per
   costruzione; se si verificasse sarebbe un difetto del confronto stesso, ed e'
   comunque un **FAIL**.

2. **Atomicita' DI INSIEME** — la pubblicazione coordinata dei tre artefatti,
   con snapshot in memoria, staging, ordine deterministico e rollback
   byte-per-byte. Uno stato MISTO puo' esistere **durante** l'operazione; non
   puo' **sopravvivere al ritorno** dell'operazione.

I TRE CODICI, TUTTI `FAIL` AL GATE 2 — mai `WARNING`, in nessuna forma
--------------------------------------------------------------------
    derived_artifact_numeric_mismatch   divergenza numerica oltre tolleranza
    derived_artifact_incomplete         sezione/tabella/foglio obbligatorio
                                        mancante, o deliverable assente
    derived_artifact_stale              canonical_source_checksum divergente

Restano legittimi i **caveat propagati** — copertura parziale, placeholder su
ruolo opzionale, milestone fuori orizzonte, KPI `NOT_APPLICABLE` nominato,
`timing_window_empty` — che sono LIMITI DICHIARATI DEI DATI, non difetti del
deliverable.

PRIMITIVE CONDIVISE
-------------------
`render_financial_plan.py` e' la SEDE UNICA di `load_canonical`,
`read_governed_inputs`, `INPUT_SET`, `period_key` e della scrittura atomica.
Questo modulo le IMPORTA: non ne esiste una seconda copia, e il lettore
dell'insieme di ingresso governato e' **uno solo** in tutto il pacchetto.

USO
---
    python derived_consistency.py --project <dir> --canonical <path>
    python derived_consistency.py --project <dir> --canonical <nuovo canonico>
                                  --publish [--tx TX]
                                  [--inject-failure before-workbook]

CODICI DI USCITA
----------------
    0   coerenza triangolare superata / pubblicazione riuscita
    1   FAIL DICHIARATO di gate 2, oppure pubblicazione fallita con rollback
    2   errore d'uso
"""
import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree

GATE_NAME = "derived_consistency"

CANONICAL_NAME = "structured-output.json"
CHAPTER_NAME = "financial-plan.md"
WORKBOOK_NAME = "financial-model.xlsx"
STAGE10 = "10_financial-plan"

SKILL_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = Path(__file__).resolve().parent
RENDERER_PATH = OUTPUT_DIR.joinpath("render_financial_plan.py")
EXPORTER_PATH = OUTPUT_DIR.joinpath("export_financial_model.py")

CODE_MISMATCH = "derived_artifact_numeric_mismatch"
CODE_INCOMPLETE = "derived_artifact_incomplete"
CODE_STALE = "derived_artifact_stale"

NOT_APPLICABLE = "NOT_APPLICABLE"
UNDECLARED = "NON DICHIARATA"

#: Tolleranze DI REPOSITORY (`config/enforcement-config.json`):
#: `EUR 0.01` · `ratio 1e-6` · `count` esatto · `FTE` esatto.
EXACT_UNITS = ("count", "FTE", "period_index", "EUR/count", "EUR/FTE")

NUMERIC_RE = re.compile(r"^[+-]?(?:[0-9]+)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")
PATH_STEP_RE = re.compile(r"^([^\[\]]+)(?:\[([^\[\]]+)\])?$")
SECTION_RE = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$")
CAPTION_RE = re.compile(
    r"^\*\*Tabella\s+(\d+)\s+—\s+(.+?)\.\*\*\s+Fonte:\s+`([^`]+)`\s+·\s+"
    r"checksum\s+`([^`]*)`\.\s*$")

MAIN_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

_RENDERER = None


class GateUsageError(Exception):
    """Errore d'uso (exit 2)."""


class GateDefect(Exception):
    """Difetto di PREPARAZIONE o fallimento di pubblicazione."""


def renderer():
    """Le primitive condivise, in SOLA LETTURA."""
    global _RENDERER
    if _RENDERER is not None:
        return _RENDERER
    if not RENDERER_PATH.is_file():
        raise GateDefect(f"renderer assente: {RENDERER_PATH}")
    spec = importlib.util.spec_from_file_location("render_financial_plan",
                                                  RENDERER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("render_financial_plan", module)
    spec.loader.exec_module(module)
    _RENDERER = module
    return module


# --------------------------------------------------------------------------
# Lettura dei tre artefatti
# --------------------------------------------------------------------------


def sha256_of(path):
    path = Path(path)
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_paths(project, tx=None):
    """I tre artefatti dell'insieme. Il canonico vive sotto `.working/<tx>/`
    quando la transazione e' nominata."""
    stage = Path(project, STAGE10)
    if tx:
        canonical = stage.joinpath(".working", tx, CANONICAL_NAME)
    else:
        candidates = sorted(stage.glob(f".working/*/{CANONICAL_NAME}"))
        canonical = candidates[-1] if candidates else stage.joinpath(
            CANONICAL_NAME)
    return {"canonical": canonical,
            "chapter": stage.joinpath(CHAPTER_NAME),
            "workbook": stage.joinpath(WORKBOOK_NAME)}


def canonical_checksum(document):
    metadata = ((document.get("financial_plan") or {}).get(
        "calculation_metadata") or {})
    return str((metadata.get("output_checksums") or {}).get("base") or "")


def resolve_canonical(document, path):
    """Risolve un path canonico DICHIARATO. Ritorna `(trovato, valore)`."""
    node = document
    for step in str(path).split("."):
        match = PATH_STEP_RE.match(step)
        if match is None:
            return False, None
        name, index = match.group(1), match.group(2)
        if not isinstance(node, dict) or name not in node:
            return False, None
        node = node[name]
        if index is not None:
            if not isinstance(node, list) or not index.lstrip("-").isdigit():
                return False, None
            position = int(index)
            if position >= len(node):
                return False, None
            node = node[position]
    return True, node


def resolve_governed(project, reference):
    """Risolve un attributo di INPUT GOVERNATO nella forma
    `<registro>#<REF>.<campo>`.

    E' l'UNICA classe di riferimento non canonico ammessa, e la regola
    dell'insieme di ingresso chiuso la ammette nelle SOLE righe di ASSUNZIONE: un valore letto
    qui non puo' comparire in alcuna tabella di RISULTATO. Il riferimento
    composito `<path canonico> -> <registro>#<REF>.<campo>` dichiara ENTRAMBI
    i capi della dereferenza, ed e' per questo verificabile.
    """
    register, _, rest = str(reference).partition("#")
    ref, _, field = rest.partition(".")
    path = Path(project).joinpath(*register.strip().split("/"))
    if not path.is_file():
        return False, None
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, None
    entries = content if isinstance(content, list) else (
        content.get("records") or content.get("assumptions") or [])
    for record in entries or []:
        if isinstance(record, dict) and str(record.get("id")) == ref:
            if field not in record:
                return False, None
            return True, record[field]
    return False, None


def resolve_shown(document, project, path):
    """Risolve il riferimento DICHIARATO da una riga mostrata.

    Due forme, entrambe DICHIARATE dal renderer:
      - `financial_plan....`                      -> foglia CANONICA;
      - `financial_plan....[DRV] -> reg#REF.campo` -> ATTRIBUTO GOVERNATO,
        ammesso nelle sole righe di assunzione.
    """
    text = str(path)
    if " -> " in text:
        _, _, governed = text.partition(" -> ")
        return resolve_governed(project, governed)
    return resolve_canonical(document, text)


def parse_chapter(text):
    """Sezioni, tabelle e righe di valore del capitolo, nella forma DICHIARATA
    dal renderer."""
    sections = []
    tables = []
    current_section = None
    current_table = None
    header_seen = False
    for number, raw in enumerate(str(text).split("\n"), 1):
        line = raw.rstrip()
        match = SECTION_RE.match(line)
        if match:
            current_section = {"number": match.group(1),
                               "title": match.group(2), "line": number}
            sections.append(current_section)
            current_table = None
            header_seen = False
            continue
        caption = CAPTION_RE.match(line)
        if caption:
            current_table = {"number": caption.group(1),
                             "title": caption.group(2),
                             "checksum": caption.group(4),
                             "line": number, "rows": []}
            tables.append(current_table)
            header_seen = False
            continue
        if line.startswith("|") and current_table is not None:
            cells = [item.strip() for item in line.strip("|").split("|")]
            if not header_seen:
                header_seen = True
                continue
            if all(set(item) <= set("- ") for item in cells):
                continue
            if len(cells) < 6:
                continue
            current_table["rows"].append({
                "label": cells[0], "value": cells[1], "unit": cells[2],
                "scenario": cells[3], "period": cells[4],
                "path": cells[5].strip("`"), "line": number,
                "checksum": current_table["checksum"],
                "table": current_table["title"],
                "section": (current_section or {}).get("title")})
    return {"sections": sections, "tables": tables}


def chapter_value_rows(parsed):
    rows = []
    for table in parsed["tables"]:
        for entry in table["rows"]:
            if NUMERIC_RE.match(str(entry.get("value", "")).strip()):
                rows.append(entry)
    return rows


def read_package(path):
    """Lettore OOXML — **SEDE UNICA**, usata dal gate e dai contratti.

    Restituisce fogli, celle (valore, formula, indice di stile), named range e
    l'elenco delle parti. Legge il **solo XML**: nessun rendering, nessun
    motore di calcolo, nessuna dipendenza di terze parti.
    """
    path = Path(path)
    if not path.is_file():
        raise GateDefect(f"workbook assente: {path}")
    empty = {"valid_zip": False, "parts": [], "sheets": {}, "order": [],
             "defined_names": {}, "fills": {}, "locked": {},
             "full_calc_on_load": False}
    if not zipfile.is_zipfile(path):
        return empty
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:            # pragma: no cover
            return dict(empty, parts=archive.namelist())
        parts = archive.namelist()
        if "xl/workbook.xml" not in parts:
            return dict(empty, valid_zip=True, parts=parts)
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        order = [node.attrib.get("name")
                 for node in workbook.iter(f"{MAIN_NS}sheet")]
        defined_names = {node.attrib.get("name"): (node.text or "").strip()
                         for node in workbook.iter(f"{MAIN_NS}definedName")}
        fullcalc = any(node.attrib.get("fullCalcOnLoad") == "1"
                       for node in workbook.iter(f"{MAIN_NS}calcPr"))
        fills = {}
        locked = {}
        if "xl/styles.xml" in parts:
            styles = ElementTree.fromstring(archive.read("xl/styles.xml"))
            palette = []
            for fill in styles.iter(f"{MAIN_NS}fill"):
                pattern = fill.find(f"{MAIN_NS}patternFill")
                argb = None
                if pattern is not None:
                    colour = pattern.find(f"{MAIN_NS}fgColor")
                    if colour is not None:
                        argb = colour.attrib.get("rgb")
                palette.append(argb)
            container = styles.find(f"{MAIN_NS}cellXfs")
            for index, node in enumerate(
                    list(container) if container is not None else []):
                fill_id = node.attrib.get("fillId")
                fills[index] = palette[int(fill_id)] if (
                    fill_id is not None and int(fill_id) < len(palette)) \
                    else None
                protection = node.find(f"{MAIN_NS}protection")
                locked[index] = (protection is None or
                                 protection.attrib.get("locked") != "0")
        sheets = {}
        for position, name in enumerate(order, start=1):
            part = f"xl/worksheets/sheet{position}.xml"
            if part not in parts:
                continue
            root = ElementTree.fromstring(archive.read(part))
            cells = {}
            for node in root.iter(f"{MAIN_NS}c"):
                ref = node.attrib.get("r")
                style = node.attrib.get("s")
                formula = node.find(f"{MAIN_NS}f")
                value = node.find(f"{MAIN_NS}v")
                inline = node.find(f"{MAIN_NS}is")
                text = None
                if inline is not None:
                    text = "".join(item.text or "" for item in
                                   inline.iter(f"{MAIN_NS}t"))
                elif value is not None:
                    text = value.text
                cells[ref] = {
                    "value": text,
                    "formula": formula.text if formula is not None else None,
                    "style": int(style) if style is not None else 0}
            sheets[name] = cells
    return {"valid_zip": True, "parts": parts, "sheets": sheets,
            "order": order, "defined_names": defined_names, "fills": fills,
            "locked": locked, "full_calc_on_load": fullcalc}


def split_ref(reference):
    """`'P&L'!$B$7` -> `("P&L", "B7")`; un intervallo restituisce la prima
    cella."""
    text = str(reference)
    sheet, _, cell_ref = text.rpartition("!")
    sheet = sheet.strip()
    if sheet.startswith("'") and sheet.endswith("'"):
        sheet = sheet[1:-1].replace("''", "'")
    first = cell_ref.split(":")[0].replace("$", "")
    return sheet, first


def cell_at(package, reference):
    sheet, ref = split_ref(reference)
    return (package["sheets"].get(sheet) or {}).get(ref)


def named_value(package, name):
    reference = package["defined_names"].get(name)
    if not reference:
        return None
    entry = cell_at(package, reference)
    return None if entry is None else entry.get("value")


def column_of(ref):
    return "".join(item for item in str(ref) if item.isalpha())


def row_of(ref):
    digits = "".join(item for item in str(ref) if item.isdigit())
    return int(digits) if digits else 0


def rows_of_sheet(package, sheet_name):
    by_row = {}
    for ref, entry in (package["sheets"].get(sheet_name) or {}).items():
        by_row.setdefault(row_of(ref), {})[column_of(ref)] = entry
    return by_row


def workbook_value_rows(package):
    """Le righe di VALORE UFFICIALE del workbook: quelle in cui la colonna del
    path canonico porta un path `financial_plan.*` e la colonna del valore
    porta un numero. La coppia e' leggibile dal SOLO file."""
    rows = []
    for sheet_name in package["sheets"]:
        by_row = rows_of_sheet(package, sheet_name)
        for row_index in sorted(by_row):
            columns = by_row[row_index]
            path_cell = columns.get("F")
            value_cell = columns.get("B")
            if not path_cell or not value_cell:
                continue
            path = str(path_cell.get("value") or "")
            if not path.startswith("financial_plan."):
                continue
            value = value_cell.get("value")
            if value is None or not NUMERIC_RE.match(str(value).strip()):
                continue
            rows.append({
                "sheet": sheet_name, "ref": f"B{row_index}", "value": value,
                "path": path,
                "unit": str((columns.get("C") or {}).get("value")
                            or UNDECLARED),
                "label": str((columns.get("A") or {}).get("value") or ""),
                "style": value_cell.get("style")})
    return rows


# --------------------------------------------------------------------------
# Tolleranze — confronto per TIPO E VALORE, mai per stringa localizzata
# --------------------------------------------------------------------------


def tolerance_for(unit):
    if unit in EXACT_UNITS or unit == UNDECLARED:
        return Decimal("0")
    if unit == "ratio":
        return Decimal("1e-6")
    return Decimal("0.01")


def within_tolerance(left, right, unit):
    try:
        first = Decimal(str(left).strip())
        second = Decimal(str(right).strip())
    except (InvalidOperation, ValueError):
        return str(left).strip() == str(right).strip()
    return abs(first - second) <= tolerance_for(unit)


# --------------------------------------------------------------------------
# XREC-02 ... XREC-06
# --------------------------------------------------------------------------


def xrec_02(document, chapter_text, project):
    """canonico -> `financial-plan.md`: ogni valore MOSTRATO."""
    findings = []
    parsed = parse_chapter(chapter_text)
    for entry in chapter_value_rows(parsed):
        path = entry["path"]
        if not path.startswith("financial_plan."):
            continue
        found, value = resolve_shown(document, project, path)
        if not found:
            findings.append({
                "xrec": "XREC-02", "code": CODE_MISMATCH,
                "where": f"capitolo · sezione «{entry['section']}» riga "
                         f"{entry['line']}",
                "message": f"path canonico IRRISOLVIBILE {path!r}"})
            continue
        if not within_tolerance(entry["value"], value, entry["unit"]):
            findings.append({
                "xrec": "XREC-02", "code": CODE_MISMATCH,
                "where": f"capitolo · sezione «{entry['section']}» riga "
                         f"{entry['line']}",
                "message": f"valore mostrato {entry['value']!r} contro "
                           f"canonico {value!r} ({path}), oltre la tolleranza "
                           f"{tolerance_for(entry['unit'])} {entry['unit']}"})
    return findings


def xrec_03(document, package):
    """canonico -> `financial-model.xlsx`: ogni valore UFFICIALE."""
    findings = []
    for entry in workbook_value_rows(package):
        found, value = resolve_canonical(document, entry["path"])
        if not found:
            findings.append({
                "xrec": "XREC-03", "code": CODE_MISMATCH,
                "where": f"workbook · {entry['sheet']}!{entry['ref']}",
                "message": f"path canonico IRRISOLVIBILE {entry['path']!r}"})
            continue
        if not within_tolerance(entry["value"], value, entry["unit"]):
            findings.append({
                "xrec": "XREC-03", "code": CODE_MISMATCH,
                "where": f"workbook · {entry['sheet']}!{entry['ref']}",
                "message": f"valore ufficiale {entry['value']!r} contro "
                           f"canonico {value!r} ({entry['path']}), oltre la "
                           f"tolleranza {tolerance_for(entry['unit'])} "
                           f"{entry['unit']}"})
    return findings


def headline_from_workbook(package, tokens):
    """Le NOVE metriche di testata lette dal foglio `Dashboard`, per ETICHETTA
    DICHIARATA: nessun numero di riga e' hardcodato."""
    labels = {entry["label"]: entry["id"]
              for entry in tokens.get("headline_metrics") or []}
    by_row = rows_of_sheet(package, "Dashboard")
    found = {}
    for row_index in sorted(by_row):
        columns = by_row[row_index]
        label = str((columns.get("A") or {}).get("value") or "")
        if label in labels:
            found[labels[label]] = {
                "value": (columns.get("B") or {}).get("value"),
                "path": str((columns.get("F") or {}).get("value") or ""),
                "ref": f"B{row_index}"}
    return found


def xrec_04(document, package, chapter_text, tokens):
    """`.md` -> `.xlsx`: le NOVE metriche di testata, TRIANGOLARMENTE."""
    findings = []
    workbook_metrics = headline_from_workbook(package, tokens)
    parsed = parse_chapter(chapter_text)
    chapter_by_path = {}
    for entry in chapter_value_rows(parsed):
        chapter_by_path.setdefault(entry["path"], entry)
    for entry in tokens.get("headline_metrics") or []:
        metric_id = entry["id"]
        found = workbook_metrics.get(metric_id)
        if found is None:
            findings.append({
                "xrec": "XREC-04", "code": CODE_INCOMPLETE,
                "where": f"workbook · Dashboard · metrica {metric_id}",
                "message": f"metrica di testata «{entry['label']}» ASSENTE dal "
                           "Dashboard"})
            continue
        value = found["value"]
        path = found["path"]
        if str(value) == NOT_APPLICABLE:
            # CAVEAT PROPAGATO, non difetto: la metrica non e' prodotta dal
            # canonico e il workbook lo DICHIARA visibilmente.
            continue
        resolved, canonical_value = resolve_canonical(document, path)
        if not resolved:
            findings.append({
                "xrec": "XREC-04", "code": CODE_MISMATCH,
                "where": f"workbook · Dashboard!{found['ref']}",
                "message": f"metrica {metric_id}: path IRRISOLVIBILE {path!r}"})
            continue
        chapter_entry = chapter_by_path.get(path)
        unit = chapter_entry["unit"] if chapter_entry else UNDECLARED
        if not within_tolerance(value, canonical_value, unit):
            findings.append({
                "xrec": "XREC-04", "code": CODE_MISMATCH,
                "where": f"workbook · Dashboard!{found['ref']}",
                "message": f"metrica {metric_id}: workbook {value!r} contro "
                           f"canonico {canonical_value!r} ({path})"})
            continue
        if chapter_entry is not None and not within_tolerance(
                chapter_entry["value"], value, unit):
            findings.append({
                "xrec": "XREC-04", "code": CODE_MISMATCH,
                "where": f"metrica {metric_id}",
                "message": f"capitolo {chapter_entry['value']!r} contro "
                           f"workbook {value!r}, pur essendo entrambi "
                           "confrontati col canonico: il confronto e' a TRE"})
    return findings


def assumption_argb(tokens):
    """Gli ARGB che marcano una CELLA DI ASSUNZIONE editabile."""
    styles = tokens.get("styles") or {}
    values = set()
    for token_id in tokens.get("assumption_styles") or []:
        argb = (styles.get(token_id) or {}).get("argb")
        if argb:
            values.add(argb)
    orange = (styles.get(tokens.get("orange_style")
                         or "assumption_to_validate") or {}).get("argb")
    if orange:
        values.add(orange)
    return values


def xrec_05(document, package, tokens):
    """`driver_registry` -> Assumption Register: corrispondenza BIUNIVOCA
    cella <-> riga <-> `DRV-*`. Le DUE direzioni sono verificate
    SEPARATAMENTE."""
    findings = []
    fields = (tokens.get("workbook") or {}).get(
        "assumption_register_fields") or []
    by_row = rows_of_sheet(package, "Assumption Register")
    header_row = None
    for row_index in sorted(by_row):
        values = [str((by_row[row_index].get(chr(ord("A") + offset)) or {}).get(
            "value") or "") for offset in range(len(fields))]
        if values == list(fields):
            header_row = row_index
            break
    if header_row is None:
        return [{"xrec": "XREC-05", "code": CODE_INCOMPLETE,
                 "where": "workbook · Assumption Register",
                 "message": "intestazione dei SEDICI campi ASSENTE: il "
                            "Register non e' leggibile"}]
    location_column = chr(ord("A") + fields.index("workbook_location"))
    rows = {}
    for row_index in sorted(by_row):
        if row_index <= header_row:
            continue
        columns = by_row[row_index]
        assumption_id = str((columns.get("A") or {}).get("value") or "")
        if not assumption_id:
            continue
        rows[assumption_id] = {
            "row": row_index,
            "location": str((columns.get(location_column) or {}).get("value")
                            or "")}
    # ---- DIREZIONE 1 — ogni CELLA di assunzione ha UNA riga di Register ----
    argb = assumption_argb(tokens)
    fills = package["fills"]
    named_by_ref = {}
    for name, reference in package["defined_names"].items():
        sheet, cell_ref = split_ref(reference)
        if sheet == "Assumptions" and ":" not in reference:
            named_by_ref[cell_ref] = name
    orange_cells = sorted(
        ref for ref, entry in (package["sheets"].get("Assumptions")
                               or {}).items()
        if fills.get(entry.get("style")) in argb)
    for ref in orange_cells:
        name = named_by_ref.get(ref)
        if name is None:
            findings.append({
                "xrec": "XREC-05", "code": CODE_INCOMPLETE,
                "where": f"workbook · Assumptions!{ref}",
                "message": "cella di assunzione priva di NAMED RANGE: nessuna "
                           "riga di Register puo' puntarla stabilmente"})
            continue
        matching = [key for key, entry in rows.items()
                    if entry["location"].endswith(f"!{name}")]
        if len(matching) != 1:
            findings.append({
                "xrec": "XREC-05", "code": CODE_INCOMPLETE,
                "where": f"workbook · Assumptions!{ref} ({name})",
                "message": f"la cella di assunzione ha {len(matching)} righe "
                           "di Assumption Register invece di ESATTAMENTE UNA"})
    # ---- DIREZIONE 2 — ogni RIGA punta a una cella ESISTENTE --------------
    for assumption_id, entry in sorted(rows.items()):
        _, _, name = entry["location"].partition("!")
        reference = package["defined_names"].get(name)
        if not reference:
            findings.append({
                "xrec": "XREC-05", "code": CODE_INCOMPLETE,
                "where": f"workbook · Assumption Register riga {entry['row']}",
                "message": f"workbook_location {entry['location']!r} punta a "
                           "un named range INESISTENTE"})
            continue
        if cell_at(package, reference) is None:
            findings.append({
                "xrec": "XREC-05", "code": CODE_INCOMPLETE,
                "where": f"workbook · Assumption Register riga {entry['row']}",
                "message": f"workbook_location {entry['location']!r} punta a "
                           "una posizione INESISTENTE del workbook"})
    # ---- CARDINALITA' esatta contro il registro canonico ------------------
    drivers = ((document.get("financial_plan") or {}).get("driver_registry")
               or {}).get("drivers") or []
    declared = {str(driver.get("driver_id")) for driver in drivers}
    if declared != set(rows):
        findings.append({
            "xrec": "XREC-05", "code": CODE_INCOMPLETE,
            "where": "workbook · Assumption Register",
            "message": f"cardinalita' NON esatta: driver canonici "
                       f"{sorted(declared)} contro righe {sorted(rows)}"})
    return findings


def xrec_06(project, document):
    """registri governati -> `source_record_hash`: freschezza degli attributi
    letti in sola lettura, con il lettore CONDIVISO."""
    findings = []
    module = renderer()
    drivers = ((document.get("financial_plan") or {}).get("driver_registry")
               or {}).get("drivers") or []
    try:
        _, read_set, verifications = module.read_governed_inputs(project,
                                                                 drivers)
    except module.RenderRefusal as exc:
        return [{"xrec": "XREC-06", "code": exc.code,
                 "where": str(exc.ref), "message": exc.message}]
    extra = sorted(set(read_set) - set(module.INPUT_SET))
    if extra:
        findings.append({
            "xrec": "XREC-06", "code": CODE_STALE,
            "where": "insieme di ingresso",
            "message": f"registro FUORI dall'insieme CHIUSO letto: {extra}"})
    for entry in verifications:
        if not entry.get("verified"):
            findings.append({
                "xrec": "XREC-06", "code": CODE_STALE,
                "where": f"driver {entry.get('driver_id')}",
                "message": "attributo di input governato NON verificato per "
                           f"impronta: {entry.get('reason')}"})
    return findings


def triangular_checksums(document, chapter_text, package):
    """I TRE `canonical_source_checksum`. Una divergenza e'
    `derived_artifact_stale` -> FAIL, MAI un WARNING."""
    canonical = canonical_checksum(document)
    parsed = parse_chapter(chapter_text)
    chapter_values = sorted({table["checksum"] for table in parsed["tables"]})
    workbook_value = named_value(package, "meta_canonical_checksum")
    findings = []
    if len(chapter_values) != 1:
        findings.append({
            "xrec": "XREC-02", "code": CODE_STALE, "where": "capitolo",
            "message": f"il capitolo porta {len(chapter_values)} checksum "
                       f"distinti {chapter_values}: una sola generazione e' "
                       "ammessa"})
    elif chapter_values[0] != canonical:
        findings.append({
            "xrec": "XREC-02", "code": CODE_STALE, "where": "capitolo",
            "message": f"canonical_source_checksum del capitolo "
                       f"{chapter_values[0]!r} != canonico {canonical!r}"})
    if workbook_value != canonical:
        findings.append({
            "xrec": "XREC-03", "code": CODE_STALE,
            "where": "workbook · README!meta_canonical_checksum",
            "message": f"canonical_source_checksum del workbook "
                       f"{workbook_value!r} != canonico {canonical!r}"})
    return findings, {
        "canonical": canonical,
        "chapter": chapter_values[0] if len(chapter_values) == 1
        else chapter_values,
        "workbook": workbook_value}


def check(project, canonical_path=None, tx=None):
    """Gate 2 completo: i tre checksum piu' `XREC-02 ... XREC-06`."""
    module = renderer()
    tokens = module.load_style_tokens()
    paths = artifact_paths(project, tx)
    if canonical_path:
        paths["canonical"] = Path(canonical_path)
    findings = []
    for key in ("canonical", "chapter", "workbook"):
        if not paths[key].is_file():
            findings.append({
                "xrec": "-", "code": CODE_INCOMPLETE, "where": key,
                "message": f"deliverable obbligatorio ASSENTE: {paths[key]}"})
    if findings:
        return {"gate": GATE_NAME, "passed": False, "findings": findings,
                "checksums": {},
                "artifacts": {k: str(v) for k, v in paths.items()}}
    document = json.loads(paths["canonical"].read_text(encoding="utf-8"))
    chapter_text = paths["chapter"].read_text(encoding="utf-8")
    package = read_package(paths["workbook"])
    checksum_findings, checksums = triangular_checksums(document, chapter_text,
                                                        package)
    findings.extend(checksum_findings)
    findings.extend(xrec_02(document, chapter_text, project))
    findings.extend(xrec_03(document, package))
    findings.extend(xrec_04(document, package, chapter_text, tokens))
    findings.extend(xrec_05(document, package, tokens))
    findings.extend(xrec_06(project, document))
    return {"gate": GATE_NAME, "passed": not findings, "findings": findings,
            "checksums": checksums,
            "artifacts": {k: str(v) for k, v in paths.items()},
            "sha256": {k: sha256_of(v) for k, v in paths.items()}}


# --------------------------------------------------------------------------
# Atomicita' DI INSIEME — pubblicazione coordinata e rollback
# --------------------------------------------------------------------------


def run_generator(script, canonical, project):
    return subprocess.run(
        [sys.executable, str(script), "--canonical", str(canonical),
         "--project", str(project)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")


def restored_generations(paths):
    """Il `canonical_source_checksum` di ciascuno dei tre artefatti: l'insieme
    ne deve portare UNO SOLO."""
    generations = {"canonical": None, "chapter": None, "workbook": None}
    if paths["canonical"].is_file():
        try:
            generations["canonical"] = canonical_checksum(json.loads(
                paths["canonical"].read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):      # pragma: no cover
            generations["canonical"] = None
    if paths["chapter"].is_file():
        parsed = parse_chapter(paths["chapter"].read_text(encoding="utf-8"))
        values = sorted({table["checksum"] for table in parsed["tables"]})
        generations["chapter"] = values[0] if len(values) == 1 else None
    if paths["workbook"].is_file():
        try:
            generations["workbook"] = named_value(
                read_package(paths["workbook"]), "meta_canonical_checksum")
        except GateDefect:                           # pragma: no cover
            generations["workbook"] = None
    return generations


def survivors_under(paths):
    """NESSUN file di staging e NESSUN file di backup puo' sopravvivere."""
    survivors = []
    for directory in {paths["chapter"].parent, paths["canonical"].parent}:
        if not directory.is_dir():
            continue
        for entry in sorted(directory.iterdir()):
            name = entry.name
            if ".tmp-" in name or name.endswith((".bak", ".backup", ".orig")):
                survivors.append(str(entry))
    return survivors


def publish(project, canonical_source, tx=None, inject_failure=None):
    """ATOMICITA' DI INSIEME, nei sei passi dichiarati.

    1  SNAPSHOT dei byte precedenti e dello STATO DI ESISTENZA di TUTTI E TRE,
       IN MEMORIA: nessun file di backup e' mai creato sul disco;
    2  STAGING: i tre nuovi artefatti sono COSTRUITI e VALIDATI in un'area di
       staging, e la coerenza triangolare dei tre checksum e' verificata IN
       STAGING, PRIMA che uno solo di essi diventi visibile;
    3  PUBBLICAZIONE in ordine DETERMINISTICO: canonico -> capitolo -> workbook;
    4  ROLLBACK: ogni artefatto precedente RIPRISTINATO BYTE PER BYTE, ogni
       artefatto nuovo PRIVO DI PREDECESSORE RIMOSSO, si VERIFICA che l'insieme
       porti UNA SOLA generazione, e lo staging e' rimosso;
    5  SUCCESSO ESPOSTO SOLO ALLA FINE: non esiste un successo parziale;
    6  solo allora `XREC-02 ... XREC-06`.
    """
    module = renderer()
    paths = artifact_paths(project, tx)
    order = ("canonical", "chapter", "workbook")

    # ---- 1  SNAPSHOT, IN MEMORIA -----------------------------------------
    snapshot = {key: {"existed": paths[key].is_file(),
                      "bytes": paths[key].read_bytes()
                      if paths[key].is_file() else None}
                for key in order}
    before = {key: sha256_of(paths[key]) for key in order}

    staging = Path(tempfile.mkdtemp(prefix="derived-staging-"))
    report = {"gate": GATE_NAME, "operation": "publish", "published": False,
              "rolled_back": False, "inject_failure": inject_failure,
              "sha256_before": before, "staging": str(staging),
              "findings": [], "publish_order": list(order)}
    try:
        # ---- 2  STAGING --------------------------------------------------
        staging_project = staging.joinpath("project")
        shared = Path(project, "shared")
        if shared.is_dir():
            shutil.copytree(shared, staging_project.joinpath("shared"))
        staged_canonical = staging_project.joinpath(
            STAGE10, ".working", tx or "staging", CANONICAL_NAME)
        staged_canonical.parent.mkdir(parents=True, exist_ok=True)
        staged_canonical.write_bytes(Path(canonical_source).read_bytes())

        rendered = run_generator(RENDERER_PATH, staged_canonical,
                                 staging_project)
        if rendered.returncode != 0:
            raise GateDefect("capitolo NON costruibile in staging: "
                             f"{rendered.stdout[:400]}")
        exported = run_generator(EXPORTER_PATH, staged_canonical,
                                 staging_project)
        if exported.returncode != 0:
            raise GateDefect("workbook NON costruibile in staging: "
                             f"{exported.stdout[:400]}")

        staged = {"canonical": staged_canonical,
                  "chapter": staging_project.joinpath(STAGE10, CHAPTER_NAME),
                  "workbook": staging_project.joinpath(STAGE10,
                                                       WORKBOOK_NAME)}
        for key in order:
            if not staged[key].is_file():
                raise GateDefect(f"artefatto di staging ASSENTE: {key}")
        staging_findings, staged_checksums = triangular_checksums(
            json.loads(staged["canonical"].read_text(encoding="utf-8")),
            staged["chapter"].read_text(encoding="utf-8"),
            read_package(staged["workbook"]))
        report["staging_checksums"] = staged_checksums
        if staging_findings:
            report["findings"].extend(staging_findings)
            raise GateDefect("coerenza triangolare NON verificata IN STAGING: "
                             "nessun artefatto e' stato reso visibile")

        payloads = {key: staged[key].read_bytes() for key in order}

        # ---- 3  PUBBLICAZIONE in ordine DETERMINISTICO -------------------
        for key in order:
            if inject_failure == "before-workbook" and key == "workbook":
                raise GateDefect(
                    "fallimento INIETTATO fra la SECONDA e la TERZA "
                    "pubblicazione: canonico e capitolo sono alla generazione "
                    "N+1 e il workbook e' ancora alla N")
            if inject_failure == "before-chapter" and key == "chapter":
                raise GateDefect("fallimento INIETTATO fra la PRIMA e la "
                                 "SECONDA pubblicazione")
            module.atomic_write_bytes(paths[key], payloads[key])

        # ---- 5/6  SUCCESSO SOLO ALLA FINE --------------------------------
        verdict = check(project, paths["canonical"], tx)
        report["check"] = verdict
        if not verdict["passed"]:
            report["findings"].extend(verdict["findings"])
            raise GateDefect("coerenza triangolare POST-PUBBLICAZIONE fallita")
        report["published"] = True
    except (GateDefect, OSError, ValueError, json.JSONDecodeError) as exc:
        # ---- 4  ROLLBACK -------------------------------------------------
        report["failure"] = str(exc)
        restored = []
        removed = []
        for key in order:
            path = paths[key]
            state = snapshot[key]
            if state["existed"]:
                module.atomic_write_bytes(path, state["bytes"])
                restored.append(key)
            elif path.is_file():
                path.unlink()
                removed.append(key)
        report["rolled_back"] = True
        report["restored"] = restored
        report["removed_without_predecessor"] = removed
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        report["staging_removed"] = not staging.exists()
        report["sha256_after"] = {key: sha256_of(paths[key]) for key in order}
        report["byte_identical_to_previous"] = all(
            report["sha256_after"][key] == before[key] for key in order)
        report["generations"] = restored_generations(paths)
        report["single_generation"] = len(
            {value for value in report["generations"].values()
             if value is not None}) <= 1
        report["staging_survivors"] = survivors_under(paths)
    return report


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(
        prog="derived_consistency.py", add_help=True,
        description="Gate 2: coerenza triangolare dei derivati e "
                    "pubblicazione coordinata.")
    parser.add_argument("--project", required=False)
    parser.add_argument("--canonical", required=False)
    parser.add_argument("--tx", default=None)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--inject-failure",
                        choices=("before-chapter", "before-workbook"),
                        default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    if not args.project:
        print("USAGE ERROR: --project e' obbligatorio", file=sys.stderr)
        return 2
    try:
        if args.publish:
            if not args.canonical:
                print("USAGE ERROR: --publish richiede --canonical",
                      file=sys.stderr)
                return 2
            report = publish(args.project, args.canonical, args.tx,
                             args.inject_failure)
            print(json.dumps(report, indent=2, ensure_ascii=True,
                             sort_keys=True))
            return 0 if report.get("published") else 1
        report = check(args.project, args.canonical, args.tx)
    except GateDefect as exc:
        print(json.dumps({"gate": GATE_NAME, "passed": False,
                          "defect": str(exc)}, indent=2, ensure_ascii=True,
                         sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
