#!/usr/bin/env python3
"""T-FIN-XLSX — i DICIASSETTE contratti del WORKBOOK `financial-model.xlsx`.

Il workbook e' il derivato Excel dello Stage 10, esportato dal solo documento
canonico da `output/export_financial_model.py` e verificato, insieme al
capitolo, dal gate di coerenza `output/derived_consistency.py`. Il modulo
entra nel glob di ENTRAMBI i runner (`tests/run-tests.ps1` e
`tests/run-tests.sh` globano `tests/integration/test_*.py`).

I DICIASSETTE CONTRATTI OSPITATI QUI
------------------------------------
    FD-C-01  T-FIN-XLSX-STRUCTURE                        MUT-3-23
    FD-C-02  T-FIN-XLSX-SHEETS                           MUT-3-24
    FD-C-03  T-FIN-XLSX-NUMERIC-CONSISTENCY              MUT-3-25
    FD-C-04  T-FIN-XLSX-ASSUMPTION-ORANGE                MUT-3-26
    FD-C-05  T-FIN-XLSX-NO-ORANGE-ON-OUTPUT              MUT-3-27
    FD-C-06  T-FIN-XLSX-STATIC-QA                        MUT-3-28
    FD-C-07  T-FIN-XLSX-SCENARIO-CONTROLS                MUT-3-29
    FD-C-08  T-FIN-XLSX-FORMULA-ROUNDTRIP                MUT-3-30
    FD-C-09  T-FIN-XLSX-NO-ECONOMIC-HARDCODES            MUT-3-31
    FD-C-10  T-FIN-XLSX-TEXT-LABELS                      MUT-3-32
    FD-C-12  T-FIN-DERIVED-CROSS-CONSISTENCY             MUT-3-34
    FD-C-13  T-FIN-XLSX-RENDER-DETERMINISM               MUT-3-35
    FD-C-14  T-FIN-XLSX-NOT-A-SOURCE                     MUT-3-36
    FD-C-15  T-FIN-DERIVED-ATOMIC                        MUT-3-37
    FD-C-20  T-FIN-DERIVED-INPUT-SET                     MUT-3-42
    FD-C-21  T-FIN-XLSX-ASSUMPTION-REGISTER              MUT-3-43
    FD-C-22  T-FIN-XLSX-INPUT-OUTPUT-SEPARATION          MUT-3-44

I CINQUE contratti del CAPITOLO — `C-11`, `C-16` … `C-19` — vivono in
`tests/integration/test_fin_chapter.py`.

DISCIPLINA
----------
Ogni contratto e' INDIPENDENTE: un contratto RED riporta la PROPRIA
constatazione. Nessun contratto fallisce per un errore globale non pertinente,
e NESSUNA mutazione e' uccisa PER ECCEZIONE: ogni sotto-esecuzione di mutazione
verifica che il difetto sia RILEVATO e NOMINATO.

Il registro delle fixture `F-1`…`F-13` di `bpo_testkit.py` resta CHIUSO:
le varianti usate qui sono DERIVATE IN-MODULO.

SEMANTICA DEGLI EXIT CODE
-------------------------
    0   tutti i contratti soddisfatti
    1   almeno un contratto RED
    2   errore d'uso
    3   difetto di PREPARAZIONE (non e' un esito RED)
"""
import argparse
import copy
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SKILL_REL = ".claude/skills/business-plan-orchestrator"
TESTKIT_REL = "tests/integration"
CHAPTER_HARNESS = "test_fin_chapter"

EXPORTER_REL = f"{SKILL_REL}/output/export_financial_model.py"
GATE_REL = f"{SKILL_REL}/output/derived_consistency.py"
RENDERER_REL = f"{SKILL_REL}/output/render_financial_plan.py"
STYLE_TOKENS_REL = f"{SKILL_REL}/output/style_tokens.json"

WORKBOOK_NAME = "financial-model.xlsx"
CHAPTER_NAME = "financial-plan.md"
STAGE10 = "10_financial-plan"

EXIT_OK = 0
EXIT_RED = 1
EXIT_USAGE = 2
EXIT_STATE = 3

CODE_INCOMPLETE = "derived_artifact_incomplete"
CODE_MISMATCH = "derived_artifact_numeric_mismatch"
CODE_STALE = "derived_artifact_stale"

NOT_APPLICABLE = "NOT_APPLICABLE"
NUMERIC_RE = re.compile(r"^[+-]?(?:[0-9]+)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")

#: Le PARTI OOXML obbligatorie: senza una sola di queste il pacchetto non e'
#: apribile come workbook, e l'estensione del file non basta.
REQUIRED_PARTS = ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
                  "xl/_rels/workbook.xml.rels", "xl/styles.xml")

#: Token VIETATI dentro una formula: riferimenti diretti agli id di
#: assunzione (`P-ASS-`) e l'operatore di intersezione implicita (`@`).
FORBIDDEN_FORMULA_TOKENS = ("P-ASS-", "@")

#: Un letterale numerico dentro una formula sarebbe una SOGLIA, una TOLLERANZA
#: o un FATTORE, cioe' POLICY: la policy vive nel motore, mai nel workbook.
FORMULA_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_$])[0-9]+(?:\.[0-9]+)?")
FORMULA_FUNCTION_RE = re.compile(r"([A-Za-z][A-Za-z0-9_.]*)\s*\(")
FORMULA_REF_RE = re.compile(r"\$?([A-Z]{1,3})\$?([0-9]+)")

CHAPTER = None  # popolato da `main`
GATE = None     # popolato da `main`


class HarnessUsageError(Exception):
    """Errore d'uso dell'harness (exit 2)."""


class HarnessDefect(Exception):
    """Difetto di PREPARAZIONE (exit 3). Non e' un esito RED."""


# --------------------------------------------------------------------------
# Preparazione
# --------------------------------------------------------------------------


def resolve_root(raw):
    if not raw:
        raise HarnessUsageError("--root obbligatorio")
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise HarnessUsageError(f"--root non e' una directory: {root}")
    for probe in (SKILL_REL, TESTKIT_REL):
        if not (root / probe).is_dir():
            raise HarnessUsageError(
                f"--root non sembra la radice del repository: {probe} assente "
                f"sotto {root}")
    return root


def load_module(path, name):
    path = Path(path)
    if not path.is_file():
        raise HarnessDefect(f"modulo assente: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_chapter_harness(root):
    """Riusa i costruttori del capitolo, che a loro volta riusano quelli
    dell'output canonico e del motore: una sola catena di costruzione
    dell'ingresso, e nessuna duplicazione della fixture."""
    module = load_module(root / TESTKIT_REL / f"{CHAPTER_HARNESS}.py",
                         CHAPTER_HARNESS)
    module.M5A = module.load_m5a_harness(root)
    return module


def load_gate(root):
    """Il GATE di produzione: il lettore OOXML e le `XREC-*` hanno una SEDE
    UNICA, e i contratti la ESEGUONO invece di duplicarla.

    Se il gate e' ASSENTE il modulo NON solleva un difetto di harness: ogni
    contratto diventa RED riportando la propria constatazione di componente
    mancante: senza l'exporter o il gate i DICIASSETTE contratti sono ROSSI,
    non ineseguibili.
    """
    path = root / GATE_REL
    if not path.is_file():
        return None
    return load_module(path, "derived_consistency")


def build_context(root):
    ctx = CHAPTER.build_context(root)
    ctx["exporter"] = root / EXPORTER_REL
    ctx["gate_path"] = root / GATE_REL
    ctx["renderer"] = root / RENDERER_REL
    return ctx


MISSING_EXPORTER = (
    "output/export_financial_model.py ASSENTE: l'exporter del workbook e' "
    "obbligatorio e nessun contratto del workbook e' misurabile senza "
    "di esso")
MISSING_GATE = (
    "output/derived_consistency.py ASSENTE: il gate di coerenza triangolare e "
    "il rollback coordinato sono obbligatori e nessun "
    "contratto cross-artefatto e' misurabile senza di esso")


def missing_surfaces(ctx, findings):
    missing = False
    if not ctx["exporter"].is_file():
        findings.append(MISSING_EXPORTER)
        missing = True
    if not ctx["gate_path"].is_file():
        findings.append(MISSING_GATE)
        missing = True
    if ctx["style_tokens"] is None:
        findings.append(CHAPTER.MISSING_TOKENS)
        missing = True
    return missing


def run_exporter(ctx, canonical, project, extra=()):
    """Invoca l'EXPORTER DI PRODUZIONE, mai una copia."""
    command = [sys.executable, str(ctx["exporter"]), "--canonical",
               str(canonical), "--project", str(project)]
    command.extend(extra)
    proc = subprocess.run(command, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          cwd=str(ctx["root"]),
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    report = None
    if proc.stdout.strip().startswith("{"):
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            report = None
    return {"exit_code": proc.returncode, "report": report,
            "stdout": proc.stdout, "stderr": proc.stderr,
            "command": " ".join(command)}


def prepare(ctx, base, name="xlsx", level="full", tx="tx-m5b-001"):
    """Progetto TEMPORANEO di fixture con canonico, capitolo E workbook."""
    case = CHAPTER.prepare(ctx, base, name=name, level=level, tx=tx)
    case["export"] = run_exporter(ctx, case["canonical"], case["project"])
    workbook = Path(case["project"], STAGE10, WORKBOOK_NAME)
    case["workbook"] = workbook
    case["package"] = None
    if workbook.is_file():
        case["package"] = GATE.read_package(workbook)
    return case


def not_exported(case, findings):
    export = case.get("export") or {}
    if export.get("exit_code") != 0:
        findings.append(
            f"l'exporter NON ha prodotto il workbook (exit "
            f"{export.get('exit_code')}): "
            f"{(export.get('stdout') or export.get('stderr') or '')[:300]}")
        return True
    if case.get("package") is None:
        findings.append(f"{WORKBOOK_NAME} ASSENTE dopo un'esecuzione riuscita")
        return True
    return False


# --------------------------------------------------------------------------
# Utilità di lettura e di MUTAZIONE — le mutazioni agiscono su COPIE
# --------------------------------------------------------------------------


def column_of(ref):
    return "".join(item for item in str(ref) if item.isalpha())


def row_of(ref):
    digits = "".join(item for item in str(ref) if item.isdigit())
    return int(digits) if digits else 0


def rows_of(package, sheet):
    return GATE.rows_of_sheet(package, sheet)


def assumption_argb(tokens):
    return GATE.assumption_argb(tokens)


def style_argb(package, entry):
    return package["fills"].get(entry.get("style"))


def drop_part(workbook_path, part):
    """Mutazione strutturale: rimuove una PARTE dal pacchetto OOXML. Il file
    reale non e' toccato: la copia mutata vive in una directory temporanea."""
    target = Path(tempfile.mkdtemp(prefix="mut_part_")) / WORKBOOK_NAME
    with zipfile.ZipFile(workbook_path) as source:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as sink:
            for info in source.infolist():
                if info.filename == part:
                    continue
                sink.writestr(info, source.read(info.filename))
    return target


def corrupt_zip(workbook_path):
    target = Path(tempfile.mkdtemp(prefix="mut_zip_")) / WORKBOOK_NAME
    payload = bytearray(workbook_path.read_bytes())
    for position in range(0, min(len(payload), 512)):
        payload[position] = 0
    target.write_bytes(bytes(payload))
    return target


def mutated(package):
    """Copia PROFONDA del pacchetto letto: ogni mutazione agisce qui, e il
    workbook reale resta INTATTO."""
    return copy.deepcopy(package)


# --------------------------------------------------------------------------
# Rilevatori — un rilevatore per contratto, riusabile dalla mutazione
# --------------------------------------------------------------------------


def structure_findings(package):
    """`FD-C-01` — pacchetto OOXML valido e parti obbligatorie."""
    findings = []
    if not package.get("valid_zip"):
        findings.append(
            f"il pacchetto NON si apre come ZIP valido: l'estensione "
            f"{WORKBOOK_NAME!r} non basta [{CODE_INCOMPLETE}]")
        return findings
    for part in REQUIRED_PARTS:
        if part not in package["parts"]:
            findings.append(
                f"parte OOXML obbligatoria ASSENTE: {part!r} "
                f"[{CODE_INCOMPLETE}]")
    if not package["order"]:
        findings.append(
            f"il pacchetto non dichiara alcun foglio [{CODE_INCOMPLETE}]")
    for position in range(1, len(package["order"]) + 1):
        part = f"xl/worksheets/sheet{position}.xml"
        if part not in package["parts"]:
            findings.append(
                f"parte di foglio ASSENTE: {part!r} [{CODE_INCOMPLETE}]")
    return findings


def sheet_findings(package, tokens, readme_text=""):
    """`FD-C-02` — i DICIOTTO fogli, ESATTAMENTE una volta ciascuno,
    oppure omissione in FORMA B NOMINATA in `README` E `Dashboard`."""
    findings = []
    declared = [entry["name"] for entry in
                (tokens.get("workbook") or {}).get("sheets") or []]
    present = list(package["order"])
    for name in declared:
        if name in present:
            continue
        if name in readme_text:
            continue
        findings.append(
            f"foglio obbligatorio ASSENTE e NON NOMINATO in README/Dashboard: "
            f"«{name}» [{CODE_INCOMPLETE}]")
    for name in sorted(set(present)):
        if present.count(name) != 1:
            findings.append(
                f"foglio DUPLICATO: «{name}» compare {present.count(name)} "
                f"volte invece di ESATTAMENTE UNA [{CODE_INCOMPLETE}]")
    for name in present:
        cells = package["sheets"].get(name) or {}
        if not cells:
            findings.append(
                f"foglio «{name}» PRESENTE ma VUOTO: un foglio vuoto non "
                f"soddisfa il requisito [{CODE_INCOMPLETE}]")
    return findings


def omission_text(package):
    """Il testo di `README` e `Dashboard`, dove un'omissione di FORMA B deve
    essere NOMINATA."""
    chunks = []
    for sheet in ("README", "Dashboard"):
        for entry in (package["sheets"].get(sheet) or {}).values():
            if entry.get("value"):
                chunks.append(str(entry["value"]))
    return "\n".join(chunks)


def orange_findings(package, tokens):
    """`FD-C-04` — ogni cella di assunzione ARANCIONE e REGISTRATA."""
    findings = []
    argb = assumption_argb(tokens)
    orange = ((tokens.get("styles") or {}).get(
        tokens.get("orange_style")) or {}).get("argb")
    register_rows = rows_of(package, "Assumption Register")
    fields = (tokens.get("workbook") or {}).get(
        "assumption_register_fields") or []
    location_column = chr(ord("A") + fields.index("workbook_location"))
    registered = set()
    for row_index, columns in register_rows.items():
        location = str((columns.get(location_column) or {}).get("value") or "")
        if "!" in location:
            registered.add(location.partition("!")[2])
    named_by_ref = {}
    for name, reference in package["defined_names"].items():
        sheet, cell_ref = GATE.split_ref(reference)
        if sheet == "Assumptions" and ":" not in reference:
            named_by_ref[cell_ref] = name
    by_row = rows_of(package, "Assumptions")
    seen = 0
    for row_index in sorted(by_row):
        columns = by_row[row_index]
        driver_cell = columns.get("A")
        value_cell = columns.get("C")
        if not driver_cell or not value_cell:
            continue
        driver_id = str(driver_cell.get("value") or "")
        if not driver_id.startswith("DRV-"):
            continue
        seen += 1
        fill = style_argb(package, value_cell)
        if fill not in argb:
            findings.append(
                f"cella di assunzione C{row_index} ({driver_id}) SENZA "
                f"riempimento di assunzione: fill={fill!r} non e' fra "
                f"{sorted(argb)} [{CODE_INCOMPLETE}]")
        name = named_by_ref.get(f"C{row_index}")
        if name is None or name not in registered:
            findings.append(
                f"cella di assunzione C{row_index} ({driver_id}) senza voce di "
                f"Assumption Register [{CODE_INCOMPLETE}]")
    if seen and orange is None:
        findings.append(
            f"il token ARANCIONE non e' dichiarato in style_tokens.json "
            f"[{CODE_INCOMPLETE}]")
    return findings


def legend_cells(package):
    """Le celle della LEGENDA, che per costruzione MOSTRANO ogni token di
    stile — arancione compreso — e non sono output calcolati. L'esenzione e'
    DELIMITATA dal named range `legend_styles`, non concessa a un foglio
    intero."""
    reference = package["defined_names"].get("legend_styles")
    return expand_range(package, reference) if reference else set()


def orange_on_output_findings(package, tokens):
    """`FD-C-05` — NESSUNO stile di assunzione su un OUTPUT calcolato."""
    findings = []
    argb = assumption_argb(tokens)
    legend = legend_cells(package)
    for sheet_name in package["sheets"]:
        by_row = rows_of(package, sheet_name)
        for row_index in sorted(by_row):
            columns = by_row[row_index]
            for column, entry in sorted(columns.items()):
                if style_argb(package, entry) not in argb:
                    continue
                ref = f"{column}{row_index}"
                if (sheet_name, ref) in legend:
                    continue
                # Le DUE sole celle EDITABILI dichiarate: il valore di
                # assunzione e il selettore di scenario.
                if sheet_name == "Assumptions" and column == "C":
                    continue
                if sheet_name == "Scenarios" and column == "D" and \
                        str((columns.get("A") or {}).get("value") or
                            "").startswith("SELETTORE"):
                    continue
                path = str((columns.get("F") or {}).get("value") or "")
                findings.append(
                    f"OUTPUT calcolato con stile di ASSUNZIONE: "
                    f"{sheet_name}!{ref} "
                    f"(canonical_ref={path or 'assente'}) [{CODE_INCOMPLETE}]")
    return findings


def formulas_of(package):
    formulas = []
    for sheet_name, cells in package["sheets"].items():
        for ref, entry in cells.items():
            if entry.get("formula"):
                formulas.append((sheet_name, ref, entry["formula"]))
    return sorted(formulas)


def static_qa_findings(package, tokens):
    """`FD-C-06` — nessun riferimento rotto, nessun costrutto vietato."""
    findings = []
    allowed = set((tokens.get("workbook") or {}).get(
        "allowed_formula_functions") or [])
    # named range ORFANI
    for name, reference in sorted(package["defined_names"].items()):
        sheet, _ = GATE.split_ref(reference)
        if sheet not in package["sheets"]:
            findings.append(
                f"named range ORFANO: {name!r} punta al foglio {sheet!r} che "
                f"non esiste [{CODE_INCOMPLETE}]")
            continue
        if ":" in reference:
            continue
        if GATE.cell_at(package, reference) is None:
            findings.append(
                f"named range ORFANO: {name!r} punta a {reference!r}, cella "
                f"INESISTENTE [{CODE_INCOMPLETE}]")
    # formule
    for sheet_name, ref, formula in formulas_of(package):
        for token in FORBIDDEN_FORMULA_TOKENS:
            if token in formula:
                findings.append(
                    f"costrutto VIETATO {token!r} nella formula "
                    f"{sheet_name}!{ref}: {formula!r} [{CODE_INCOMPLETE}]")
        for function in FORMULA_FUNCTION_RE.findall(formula):
            if function not in allowed:
                findings.append(
                    f"funzione FUORI dall'elenco CHIUSO in {sheet_name}!{ref}: "
                    f"{function!r} non e' fra {sorted(allowed)} "
                    f"[{CODE_INCOMPLETE}]")
        for column, row in FORMULA_REF_RE.findall(formula):
            target = f"{column}{row}"
            if target in (package["sheets"].get(sheet_name) or {}):
                continue
            if target in package["defined_names"]:
                continue
            findings.append(
                f"riferimento ROTTO in {sheet_name}!{ref}: {target!r} non "
                f"esiste nel foglio [{CODE_INCOMPLETE}]")
        for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", formula):
            if word in allowed or FORMULA_REF_RE.fullmatch(word):
                continue
            if word in package["defined_names"]:
                continue
            if re.fullmatch(r"[A-Z]{1,3}[0-9]+", word):
                continue
            findings.append(
                f"identificatore NON RISOLVIBILE in {sheet_name}!{ref}: "
                f"{word!r} non e' ne' funzione ammessa ne' named range "
                f"[{CODE_INCOMPLETE}]")
    return findings


def hardcode_findings(package, tokens):
    """`FD-C-09` — nessun valore economico CONGELATO in una cella di
    RISULTATO, e nessuna POLICY dentro una formula.

    Una costante editabile in una cella di ASSUNZIONE e' CONFORME e non
    conta come difetto.
    """
    findings = []
    argb = assumption_argb(tokens)
    for sheet_name in package["sheets"]:
        by_row = rows_of(package, sheet_name)
        for row_index in sorted(by_row):
            columns = by_row[row_index]
            entry = columns.get("B")
            if entry is None or entry.get("formula"):
                continue
            value = entry.get("value")
            if value is None or not NUMERIC_RE.match(str(value).strip()):
                continue
            if style_argb(package, entry) in argb:
                continue
            path = str((columns.get("F") or {}).get("value") or "")
            if path.startswith("financial_plan."):
                continue
            findings.append(
                f"valore economico CONGELATO in una cella di RISULTATO: "
                f"{sheet_name}!B{row_index} = {value!r} senza alcun "
                f"canonical_ref [{CODE_MISMATCH}]")
    for sheet_name, ref, formula in formulas_of(package):
        literals = FORMULA_NUMBER_RE.findall(formula)
        if literals:
            findings.append(
                f"POLICY dentro una formula: {sheet_name}!{ref} porta i "
                f"letterali numerici {literals} — una soglia, una tolleranza o "
                f"un fattore appartengono al MOTORE [{CODE_MISMATCH}]")
    return findings


def label_findings(package, tokens):
    """`FD-C-10` — ETICHETTA TESTUALE oltre al colore, e LEGENDA raggiunta
    da un named range. Letto dal SOLO XML, senza rendering."""
    findings = []
    argb = assumption_argb(tokens)
    labels = set((tokens.get("driver_status_label") or {}).values())
    by_row = rows_of(package, "Assumptions")
    for row_index in sorted(by_row):
        columns = by_row[row_index]
        entry = columns.get("C")
        if entry is None or style_argb(package, entry) not in argb:
            continue
        text = str((columns.get("D") or {}).get("value") or "")
        if not text:
            findings.append(
                f"cella stilata Assumptions!C{row_index} PRIVA di etichetta "
                f"testuale: il colore sarebbe l'unico portatore di significato "
                f"[{CODE_INCOMPLETE}]")
        elif text not in labels:
            findings.append(
                f"etichetta NON DICHIARATA su Assumptions!C{row_index}: "
                f"{text!r} non e' fra {sorted(labels)} [{CODE_INCOMPLETE}]")
    if "legend_styles" not in package["defined_names"]:
        findings.append(
            f"LEGENDA non raggiunta da alcun named range `legend_styles` "
            f"[{CODE_INCOMPLETE}]")
    else:
        sheet, _ = GATE.split_ref(package["defined_names"]["legend_styles"])
        if sheet not in package["sheets"]:
            findings.append(
                f"il named range `legend_styles` punta a un foglio "
                f"INESISTENTE {sheet!r} [{CODE_INCOMPLETE}]")
    register_rows = rows_of(package, "Assumption Register")
    if not register_rows:
        findings.append(
            f"Assumption Register senza alcuna riga: l'etichetta testuale "
            f"dovuta a OGNI riga di Register non e' verificabile "
            f"[{CODE_INCOMPLETE}]")
    return findings


def scenario_findings(package, document, tokens):
    """`FD-C-07` — selettore VALIDO e coerente con la COPERTURA."""
    findings = []
    scenarios = (((document.get("financial_plan") or {}).get("results") or {})
                 .get("scenarios") or {})
    produced = [name for name in ("base", "downside", "upside")
                if (scenarios.get(name) or {}).get("series")]
    coverage = scenarios.get("coverage") or {}
    level = str(coverage.get("level") or "")
    by_row = rows_of(package, "Scenarios")
    allowed = None
    selector_ref = None
    for row_index in sorted(by_row):
        columns = by_row[row_index]
        label = str((columns.get("A") or {}).get("value") or "")
        if label.startswith("Scenari PRODOTTI"):
            allowed = [item.strip() for item in
                       str((columns.get("B") or {}).get("value") or "").split(
                           ";") if item.strip()]
        if label.startswith("SELETTORE"):
            selector_ref = f"D{row_index}"
    if selector_ref is None:
        findings.append(
            f"SELETTORE DI SCENARIO ASSENTE dal foglio Scenarios "
            f"[{CODE_INCOMPLETE}]")
        return findings
    if allowed is None:
        findings.append(
            f"elenco CHIUSO degli scenari ammessi ASSENTE [{CODE_INCOMPLETE}]")
        return findings
    extra = sorted(set(allowed) - set(produced) - {"(nessuno)"})
    if extra:
        findings.append(
            f"il selettore AMMETTE uno scenario NON PRODOTTO: {extra} — "
            f"prodotti dal canonico: {produced} [{CODE_INCOMPLETE}]")
    if level == "none":
        for scenario_id in ("downside", "upside"):
            for sheet_name in package["sheets"]:
                for row_index, columns in rows_of(package, sheet_name).items():
                    scenario_cell = str((columns.get("D") or {}).get("value")
                                        or "")
                    if scenario_cell == scenario_id:
                        findings.append(
                            f"con copertura NULLA il workbook porta una "
                            f"colonna/riga per lo scenario NON PRODOTTO "
                            f"{scenario_id!r}: {sheet_name}!{row_index} "
                            f"[{CODE_INCOMPLETE}]")
                        break
    return findings


def roundtrip_findings(package, report):
    """`FD-C-08` — le formule RILETTE coincidono con quelle SCRITTE."""
    findings = []
    written = {}
    for entry in (report or {}).get("cells") or []:
        if entry.get("formula"):
            written[(entry["sheet"], entry["ref"])] = entry["formula"]
    read = {(sheet, ref): formula
            for sheet, ref, formula in formulas_of(package)}
    for key in sorted(set(written) | set(read)):
        left = written.get(key)
        right = read.get(key)
        if left is None:
            findings.append(
                f"formula PRESENTE nel file ma non DICHIARATA dall'exporter: "
                f"{key[0]}!{key[1]} = {right!r} [{CODE_INCOMPLETE}]")
        elif right is None:
            findings.append(
                f"formula DICHIARATA ma ASSENTE dal file: {key[0]}!{key[1]} = "
                f"{left!r} [{CODE_INCOMPLETE}]")
        elif left != right:
            findings.append(
                f"formula RILETTA diversa da quella SCRITTA in "
                f"{key[0]}!{key[1]}: scritta {left!r}, riletta {right!r} "
                f"[{CODE_INCOMPLETE}]")
    return findings


def separation_findings(package, tokens):
    """`FD-C-22` — blocchi `in_`/`out_` DISGIUNTI e NOMINATI, e nessuna
    formula dentro una cella di assunzione."""
    findings = []
    argb = assumption_argb(tokens)
    blocks = {name: reference for name, reference
              in package["defined_names"].items()
              if name.startswith(("in_", "out_"))}
    if not any(name.startswith("in_") for name in blocks):
        findings.append(
            f"nessun blocco di INPUT nominato `in_<sheet>` [{CODE_INCOMPLETE}]")
    if not any(name.startswith("out_") for name in blocks):
        findings.append(
            f"nessun blocco di OUTPUT nominato `out_<sheet>` "
            f"[{CODE_INCOMPLETE}]")
    for name, reference in sorted(blocks.items()):
        if not name.startswith("in_"):
            continue
        counterpart = "out_" + name[len("in_"):]
        if counterpart not in blocks:
            continue
        left = expand_range(package, reference)
        right = expand_range(package, blocks[counterpart])
        overlap = sorted(left & right)
        if overlap:
            findings.append(
                f"blocchi NON DISGIUNTI: {name} e {counterpart} condividono "
                f"{overlap[:5]} [{CODE_INCOMPLETE}]")
    for sheet_name, cells in package["sheets"].items():
        for ref, entry in sorted(cells.items()):
            if style_argb(package, entry) in argb and entry.get("formula"):
                findings.append(
                    f"FORMULA dentro una cella di ASSUNZIONE: "
                    f"{sheet_name}!{ref} = {entry['formula']!r} — l'invariante "
                    f"4 la vieta anche se producesse il valore giusto "
                    f"[{CODE_INCOMPLETE}]")
    return findings


def expand_range(package, reference):
    """Le celle coperte da un named range, come insieme di `(foglio, ref)`."""
    sheet, _ = GATE.split_ref(reference)
    _, _, span = str(reference).rpartition("!")
    span = span.replace("$", "")
    if ":" not in span:
        return {(sheet, span)}
    start, _, end = span.partition(":")
    columns = (column_of(start), column_of(end))
    rows = (row_of(start), row_of(end))
    cells = set()
    for row_index in range(min(rows), max(rows) + 1):
        for offset in range(ord(columns[0]), ord(columns[1]) + 1):
            cells.add((sheet, f"{chr(offset)}{row_index}"))
    return cells


# --------------------------------------------------------------------------
# I DICIASSETTE contratti
# --------------------------------------------------------------------------


def c01(ctx, base):
    """`FD-C-01` `T-FIN-XLSX-STRUCTURE` — pacchetto OOXML valido."""
    findings = []
    if missing_surfaces(ctx, findings):
        return findings
    case = prepare(ctx, base, name="c01")
    if not_exported(case, findings):
        return findings
    findings.extend(structure_findings(case["package"]))
    # RED — `MUT-3-23`: il pacchetto perde `[Content_Types].xml`.
    stripped = drop_part(case["workbook"], "[Content_Types].xml")
    detected = structure_findings(GATE.read_package(stripped))
    if not any("[Content_Types].xml" in item for item in detected):
        findings.append(
            "la rimozione di `[Content_Types].xml` NON e' rilevata, o la parte "
            f"mancante NON e' NOMINATA: {detected} [{CODE_INCOMPLETE}]")
    # ESCLUSIONE DI FALSO POSITIVO — la sola ESTENSIONE non basta.
    fake = Path(tempfile.mkdtemp(prefix="mut_ext_")) / WORKBOOK_NAME
    fake.write_bytes(b"non e' un pacchetto OOXML")
    if not structure_findings(GATE.read_package(fake)):
        findings.append(
            "un file con la sola ESTENSIONE .xlsx e' accettato come pacchetto "
            f"valido: il contratto non discrimina [{CODE_INCOMPLETE}]")
    return findings


def c02(ctx, base):
    """`FD-C-02` `T-FIN-XLSX-SHEETS` — i DICIOTTO fogli."""
    findings = []
    if missing_surfaces(ctx, findings):
        return findings
    case = prepare(ctx, base, name="c02")
    if not_exported(case, findings):
        return findings
    tokens = ctx["style_tokens"]
    package = case["package"]
    declared = [entry["name"] for entry in
                (tokens.get("workbook") or {}).get("sheets") or []]
    if len(declared) != 18:
        findings.append(
            f"style_tokens.json dichiara {len(declared)} fogli invece dei "
            f"DICIOTTO attesi [{CODE_INCOMPLETE}]")
    findings.extend(sheet_findings(package, tokens, omission_text(package)))
    # RED — `MUT-3-24`: `Reconciliation` omesso e NON nominato.
    mutant = mutated(package)
    mutant["order"] = [name for name in mutant["order"]
                       if name != "Reconciliation"]
    mutant["sheets"].pop("Reconciliation", None)
    for sheet in ("README", "Dashboard"):
        for ref, entry in (mutant["sheets"].get(sheet) or {}).items():
            if entry.get("value") and "Reconciliation" in str(entry["value"]):
                entry["value"] = str(entry["value"]).replace("Reconciliation",
                                                             "")
    detected = sheet_findings(mutant, tokens, omission_text(mutant))
    if not any("Reconciliation" in item for item in detected):
        findings.append(
            "l'omissione NON NOMINATA del foglio «Reconciliation» non e' "
            f"rilevata, o il foglio non e' NOMINATO: {detected} "
            f"[{CODE_INCOMPLETE}]")
    # ESCLUSIONE — un foglio PRESENTE ma VUOTO non soddisfa.
    empty = mutated(package)
    empty["sheets"]["Reconciliation"] = {}
    if not any("VUOTO" in item for item in
               sheet_findings(empty, tokens, omission_text(empty))):
        findings.append(
            "un foglio PRESENTE ma VUOTO e' accettato: il contratto non "
            f"discrimina [{CODE_INCOMPLETE}]")
    return findings


def c03(ctx, base):
    """`FD-C-03` `T-FIN-XLSX-NUMERIC-CONSISTENCY` — valori ufficiali =
    canonico ENTRO TOLLERANZA. Misura la TOLLERANZA, non il solo segno."""
    findings = []
    if missing_surfaces(ctx, findings):
        return findings
    case = prepare(ctx, base, name="c03")
    if not_exported(case, findings):
        return findings
    document = case["document"]
    package = case["package"]
    findings.extend(f"{item['where']}: {item['message']}"
                    for item in GATE.xrec_03(document, package))
    target = None
    for entry in GATE.workbook_value_rows(package):
        if entry["unit"] == "EUR":
            target = entry
            break
    if target is None:
        findings.append(
            f"nessun valore ufficiale in EUR: la tolleranza non e' misurabile "
            f"[{CODE_MISMATCH}]")
        return findings
    # RED — `MUT-3-25`: un valore ufficiale alterato di `0.02 EUR`.
    outside = mutated(package)
    outside["sheets"][target["sheet"]][target["ref"]]["value"] = shift(
        target["value"], "0.02")
    detected = GATE.xrec_03(document, outside)
    if not any(target["ref"] in item["where"] for item in detected):
        findings.append(
            f"un valore ufficiale alterato di 0.02 EUR "
            f"({target['sheet']}!{target['ref']}) NON e' rilevato, o la CELLA "
            f"non e' NOMINATA [{CODE_MISMATCH}]")
    # ESCLUSIONE DI FALSO POSITIVO — `0.005 EUR` resta ENTRO tolleranza.
    inside = mutated(package)
    inside["sheets"][target["sheet"]][target["ref"]]["value"] = shift(
        target["value"], "0.005")
    survivors = [item for item in GATE.xrec_03(document, inside)
                 if target["ref"] in item["where"]]
    if survivors:
        findings.append(
            "uno scarto di 0.005 EUR, ENTRO la tolleranza dichiarata, e' "
            f"segnalato: il confronto misura il segno e non la tolleranza: "
            f"{survivors[0]['message'][:160]}")
    return findings


def shift(value, delta):
    """Sposta un valore di `delta` restando nel dominio DECIMALE del test.
    E' una MUTAZIONE dell'artefatto, non una resa: vive solo qui."""
    from decimal import Decimal
    return str(Decimal(str(value)) + Decimal(delta))


def c04(ctx, base):
    """`FD-C-04` `T-FIN-XLSX-ASSUMPTION-ORANGE`."""
    findings = []
    if missing_surfaces(ctx, findings):
        return findings
    case = prepare(ctx, base, name="c04")
    if not_exported(case, findings):
        return findings
    tokens = ctx["style_tokens"]
    package = case["package"]
    orange = ((tokens.get("styles") or {}).get(
        tokens.get("orange_style")) or {}).get("argb")
    if orange != "FFF4B183":
        findings.append(
            f"il token ARANCIONE NORMATIVO e' {orange!r} invece "
            f"di 'FFF4B183' [{CODE_INCOMPLETE}]")
    findings.extend(orange_findings(package, tokens))
    # RED — `MUT-3-26`: una cella di assunzione perde il riempimento.
    target = first_assumption_ref(package, tokens)
    if target is None:
        findings.append(
            f"nessuna cella di assunzione: il contratto non e' misurabile "
            f"[{CODE_INCOMPLETE}]")
        return findings
    mutant = mutated(package)
    mutant["sheets"]["Assumptions"][target]["style"] = 0
    detected = orange_findings(mutant, tokens)
    if not any(target in item for item in detected):
        findings.append(
            f"una cella di assunzione SENZA riempimento ({target}) NON e' "
            f"rilevata, o la CELLA non e' NOMINATA [{CODE_INCOMPLETE}]")
    # RED — una cella senza voce di Register.
    without = mutated(package)
    fields = (tokens.get("workbook") or {}).get(
        "assumption_register_fields") or []
    location_column = chr(ord("A") + fields.index("workbook_location"))
    register = without["sheets"].get("Assumption Register") or {}
    for ref in sorted(register):
        if column_of(ref) == location_column:
            register[ref]["value"] = ""
            break
    if not orange_findings(without, tokens):
        findings.append(
            "una cella di assunzione priva di voce di Assumption Register NON "
            f"e' rilevata [{CODE_INCOMPLETE}]")
    return findings


def first_assumption_ref(package, tokens):
    argb = assumption_argb(tokens)
    for ref in sorted((package["sheets"].get("Assumptions") or {}),
                      key=lambda item: (row_of(item), column_of(item))):
        entry = package["sheets"]["Assumptions"][ref]
        if style_argb(package, entry) in argb:
            return ref
    return None


def c05(ctx, base):
    """`FD-C-05` `T-FIN-XLSX-NO-ORANGE-ON-OUTPUT`."""
    findings = []
    if missing_surfaces(ctx, findings):
        return findings
    case = prepare(ctx, base, name="c05")
    if not_exported(case, findings):
        return findings
    tokens = ctx["style_tokens"]
    package = case["package"]
    findings.extend(orange_on_output_findings(package, tokens))
    # RED — `MUT-3-27`: un TOTALE calcolato e' reso arancione.
    orange_index = None
    for index, argb in package["fills"].items():
        if argb == ((tokens.get("styles") or {}).get(
                tokens.get("orange_style")) or {}).get("argb"):
            orange_index = index
            break
    if orange_index is None:
        findings.append(
            f"nessun indice di stile porta l'ARGB arancione [{CODE_INCOMPLETE}]")
        return findings
    target = None
    for sheet_name, ref, _ in formulas_of(package):
        if sheet_name != "Assumptions":
            target = (sheet_name, ref)
            break
    if target is None:
        findings.append(
            f"nessun totale calcolato: il contratto non e' misurabile "
            f"[{CODE_INCOMPLETE}]")
        return findings
    mutant = mutated(package)
    mutant["sheets"][target[0]][target[1]]["style"] = orange_index
    detected = orange_on_output_findings(mutant, tokens)
    if not any(target[1] in item and target[0] in item for item in detected):
        findings.append(
            f"un totale calcolato reso ARANCIONE ({target[0]}!{target[1]}) NON "
            f"e' rilevato, o la CELLA non e' NOMINATA [{CODE_INCOMPLETE}]")
    return findings


def c06(ctx, base):
    """`FD-C-06` `T-FIN-XLSX-STATIC-QA`."""
    findings = []
    if missing_surfaces(ctx, findings):
        return findings
    case = prepare(ctx, base, name="c06")
    if not_exported(case, findings):
        return findings
    tokens = ctx["style_tokens"]
    package = case["package"]
    findings.extend(static_qa_findings(package, tokens))
    # RED — `MUT-3-28`: un named range diventa ORFANO.
    mutant = mutated(package)
    name = sorted(item for item in mutant["defined_names"]
                  if item.startswith("ass_"))[0]
    mutant["defined_names"][name] = "Assumptions!$Z$9999"
    detected = static_qa_findings(mutant, tokens)
    if not any(name in item and "ORFANO" in item for item in detected):
        findings.append(
            f"un named range ORFANO ({name}) NON e' rilevato, o il "
            f"RIFERIMENTO non e' NOMINATO [{CODE_INCOMPLETE}]")
    # RED — un token VIETATO in una formula.
    forbidden = mutated(package)
    sheet_name, ref, formula = formulas_of(forbidden)[0]
    forbidden["sheets"][sheet_name][ref]["formula"] = "SUM(P-ASS-001)"
    detected = static_qa_findings(forbidden, tokens)
    if not any("P-ASS-" in item for item in detected):
        findings.append(
            "un riferimento VIETATO `P-ASS-` in una formula NON e' rilevato "
            f"[{CODE_INCOMPLETE}]")
    # RED — intersezione implicita.
    implicit = mutated(package)
    implicit["sheets"][sheet_name][ref]["formula"] = "SUM(@B1)"
    if not any("'@'" in item or "@" in item for item in
               static_qa_findings(implicit, tokens)):
        findings.append(
            "un operatore di INTERSEZIONE IMPLICITA non e' rilevato "
            f"[{CODE_INCOMPLETE}]")
    return findings


def c07(ctx, base):
    """`FD-C-07` `T-FIN-XLSX-SCENARIO-CONTROLS` — su copertura PIENA e
    NULLA, non su una sola."""
    findings = []
    if missing_surfaces(ctx, findings):
        return findings
    tokens = ctx["style_tokens"]
    cases = {}
    for level in ("full", "none"):
        case = prepare(ctx, base, name=f"c07-{level}", level=level)
        if not_exported(case, findings):
            return findings
        cases[level] = case
        findings.extend(f"[{level}] {item}" for item in scenario_findings(
            case["package"], case["document"], tokens))
    # RED — `MUT-3-29`: il selettore AMMETTE uno scenario NON prodotto.
    none_case = cases["none"]
    mutant = mutated(none_case["package"])
    for row_index, columns in rows_of(mutant, "Scenarios").items():
        label = str((columns.get("A") or {}).get("value") or "")
        if label.startswith("Scenari PRODOTTI"):
            columns["B"]["value"] = "base; downside; upside"
            break
    detected = scenario_findings(mutant, none_case["document"], tokens)
    if not any("downside" in item for item in detected):
        findings.append(
            "un selettore che AMMETTE uno scenario NON PRODOTTO non e' "
            f"rilevato, o lo SCENARIO non e' NOMINATO [{CODE_INCOMPLETE}]")
    # RED — con copertura NULLA una riga di scenario Downside.
    injected = mutated(none_case["package"])
    injected["sheets"]["Scenarios"]["D9000"] = {
        "value": "downside", "formula": None, "style": 0}
    if not any("downside" in item for item in scenario_findings(
            injected, none_case["document"], tokens)):
        findings.append(
            "con copertura NULLA una riga etichettata `downside` NON e' "
            f"rilevata [{CODE_INCOMPLETE}]")
    return findings


def c08(ctx, base):
    """`FD-C-08` `T-FIN-XLSX-FORMULA-ROUNDTRIP`."""
    findings = []
    if missing_surfaces(ctx, findings):
        return findings
    case = prepare(ctx, base, name="c08")
    if not_exported(case, findings):
        return findings
    package = case["package"]
    report = (case["export"] or {}).get("report") or {}
    if not formulas_of(package):
        findings.append(
            f"il workbook non porta alcuna formula: il round-trip non e' "
            f"misurabile [{CODE_INCOMPLETE}]")
        return findings
    findings.extend(roundtrip_findings(package, report))
    # RED — `MUT-3-30`: la formula RILETTA differisce da quella SCRITTA.
    mutant = mutated(package)
    sheet_name, ref, formula = formulas_of(mutant)[0]
    mutant["sheets"][sheet_name][ref]["formula"] = f"SUM({formula})"
    detected = roundtrip_findings(mutant, report)
    if not any(ref in item and sheet_name in item for item in detected):
        findings.append(
            f"una formula RILETTA diversa da quella SCRITTA "
            f"({sheet_name}!{ref}) NON e' rilevata, o la CELLA e le DUE "
            f"formule non sono NOMINATE [{CODE_INCOMPLETE}]")
    return findings


def c09(ctx, base):
    """`FD-C-09` `T-FIN-XLSX-NO-ECONOMIC-HARDCODES`."""
    findings = []
    if missing_surfaces(ctx, findings):
        return findings
    case = prepare(ctx, base, name="c09")
    if not_exported(case, findings):
        return findings
    tokens = ctx["style_tokens"]
    package = case["package"]
    findings.extend(hardcode_findings(package, tokens))
    # RED — `MUT-3-31`: un letterale economico in una cella di RISULTATO.
    mutant = mutated(package)
    target = GATE.workbook_value_rows(package)[0]
    mutant["sheets"][target["sheet"]][f"F{row_of(target['ref'])}"]["value"] = ""
    detected = hardcode_findings(mutant, tokens)
    if not any(target["ref"] in item and target["sheet"] in item
               for item in detected):
        findings.append(
            f"un valore economico CONGELATO in una cella di RISULTATO "
            f"({target['sheet']}!{target['ref']}) NON e' rilevato "
            f"[{CODE_MISMATCH}]")
    # RED — una formula che implementa una SOGLIA.
    policy = mutated(package)
    sheet_name, ref, _ = formulas_of(policy)[0]
    policy["sheets"][sheet_name][ref]["formula"] = "IF(B7>1000,B7,B8)"
    if not any("letterali numerici" in item for item in
               hardcode_findings(policy, tokens)):
        findings.append(
            "una formula che implementa una SOGLIA di buffer NON e' rilevata "
            f"[{CODE_MISMATCH}]")
    # ESCLUSIONE — una costante editabile in una cella di ASSUNZIONE e'
    # CONFORME e NON conta come difetto.
    conform = [item for item in hardcode_findings(package, tokens)
               if "Assumptions!" in item]
    if conform:
        findings.append(
            "una costante editabile in una cella di ASSUNZIONE e' segnalata "
            f"come difetto, mentre e' CONFORME: {conform[0]}")
    return findings


def c10(ctx, base):
    """`FD-C-10` `T-FIN-XLSX-TEXT-LABELS`."""
    findings = []
    if missing_surfaces(ctx, findings):
        return findings
    case = prepare(ctx, base, name="c10")
    if not_exported(case, findings):
        return findings
    tokens = ctx["style_tokens"]
    package = case["package"]
    findings.extend(label_findings(package, tokens))
    # RED — `MUT-3-32`: lo stato e' portato SOLO dal riempimento.
    mutant = mutated(package)
    target = first_assumption_ref(package, tokens)
    mutant["sheets"]["Assumptions"][f"D{row_of(target)}"]["value"] = ""
    detected = label_findings(mutant, tokens)
    if not any(f"C{row_of(target)}" in item for item in detected):
        findings.append(
            "una cella stilata PRIVA di etichetta testuale NON e' rilevata, o "
            f"la CELLA non e' NOMINATA [{CODE_INCOMPLETE}]")
    # RED — legenda ASSENTE.
    without = mutated(package)
    without["defined_names"].pop("legend_styles", None)
    if not any("legend_styles" in item for item in
               label_findings(without, tokens)):
        findings.append(
            f"l'assenza della LEGENDA non e' rilevata [{CODE_INCOMPLETE}]")
    return findings


def c12(ctx, base):
    """`FD-C-12` `T-FIN-DERIVED-CROSS-CONSISTENCY` — le NOVE metriche di
    testata coincidono TRIANGOLARMENTE, un caso per CIASCUNA."""
    findings = []
    if missing_surfaces(ctx, findings):
        return findings
    case = prepare(ctx, base, name="c12")
    if not_exported(case, findings):
        return findings
    tokens = ctx["style_tokens"]
    package = case["package"]
    document = case["document"]
    chapter_text = case["text"]
    metrics = tokens.get("headline_metrics") or []
    if len(metrics) != 9:
        findings.append(
            f"le metriche di testata DICHIARATE sono {len(metrics)} invece di "
            f"NOVE [{CODE_INCOMPLETE}]")
    findings.extend(f"{item['where']}: {item['message']}" for item in
                    GATE.xrec_04(document, package, chapter_text, tokens))
    # RED — `MUT-3-34`: una metrica divergente, un caso per CIASCUNA delle nove.
    workbook_metrics = GATE.headline_from_workbook(package, tokens)
    measured = 0
    for entry in metrics:
        metric_id = entry["id"]
        found = workbook_metrics.get(metric_id)
        if found is None or str(found["value"]) == NOT_APPLICABLE:
            continue
        measured += 1
        mutant = mutated(package)
        mutant["sheets"]["Dashboard"][found["ref"]]["value"] = shift(
            found["value"], "1")
        detected = GATE.xrec_04(document, mutant, chapter_text, tokens)
        if not any(metric_id in item["message"] for item in detected):
            findings.append(
                f"la divergenza della metrica di testata {metric_id!r} NON e' "
                f"rilevata, o la METRICA non e' NOMINATA [{CODE_MISMATCH}]")
    if measured == 0:
        findings.append(
            f"nessuna metrica di testata e' prodotta: il confronto triangolare "
            f"non e' misurabile [{CODE_INCOMPLETE}]")
    return findings


def c13(ctx, base):
    """`FD-C-13` `T-FIN-XLSX-RENDER-DETERMINISM` — due render, contenuti
    EQUIVALENTI esclusi i SOLI metadati volatili permessi."""
    findings = []
    if missing_surfaces(ctx, findings):
        return findings
    case = prepare(ctx, base, name="c13")
    if not_exported(case, findings):
        return findings
    tokens = ctx["style_tokens"]
    volatile = (tokens.get("workbook") or {}).get("volatile_named_cell")
    first = case["package"]
    second_run = run_exporter(ctx, case["canonical"], case["project"])
    if second_run["exit_code"] != 0:
        findings.append(
            f"la seconda esecuzione dell'exporter fallisce (exit "
            f"{second_run['exit_code']}) [{CODE_INCOMPLETE}]")
        return findings
    second = GATE.read_package(case["workbook"])
    differences = package_differences(first, second, volatile)
    if differences:
        findings.append(
            f"due render dallo stesso canonico NON sono equivalenti: "
            f"{differences[:3]} [{CODE_INCOMPLETE}]")
    # NON VACUITA' — il metadato volatile e' DAVVERO cambiato.
    reference = first["defined_names"].get(volatile)
    if reference is None:
        findings.append(
            f"il metadato volatile {volatile!r} non e' un named range: "
            f"l'esclusione non e' DICHIARATA [{CODE_INCOMPLETE}]")
    elif GATE.named_value(first, volatile) == GATE.named_value(second,
                                                               volatile):
        findings.append(
            f"il metadato dichiarato VOLATILE {volatile!r} non cambia fra due "
            f"render: l'esclusione sarebbe VACUA [{CODE_INCOMPLETE}]")
    # RED — `MUT-3-35`: differenza in una cella NON volatile.
    mutant = mutated(second)
    target = GATE.workbook_value_rows(mutant)[0]
    mutant["sheets"][target["sheet"]][target["ref"]]["value"] = shift(
        target["value"], "1")
    if not package_differences(first, mutant, volatile):
        findings.append(
            f"una differenza in una cella NON volatile "
            f"({target['sheet']}!{target['ref']}) NON e' rilevata "
            f"[{CODE_INCOMPLETE}]")
    # RED — il timestamp usato come INPUT di una formula.
    as_input = mutated(second)
    sheet_name, ref, _ = formulas_of(as_input)[0]
    as_input["sheets"][sheet_name][ref]["formula"] = f"SUM({volatile})"
    if not any(volatile in (entry[2] or "") for entry in
               formulas_of(as_input)):
        findings.append(
            "il timestamp usato come INPUT di una formula non e' osservabile "
            f"[{CODE_INCOMPLETE}]")
    elif not timestamp_as_input_findings(as_input, volatile):
        findings.append(
            f"il timestamp {volatile!r} usato come INPUT di una formula NON e' "
            f"rilevato: e' ammesso SOLO come metadato [{CODE_INCOMPLETE}]")
    if timestamp_as_input_findings(second, volatile):
        findings.append(
            "il workbook reale usa il timestamp come INPUT di una formula "
            f"[{CODE_INCOMPLETE}]")
    return findings


def timestamp_as_input_findings(package, volatile):
    return [f"{sheet}!{ref}" for sheet, ref, formula in formulas_of(package)
            if volatile and volatile in (formula or "")]


def package_differences(left, right, volatile):
    """Differenze fra due pacchetti, ESCLUSI i soli metadati volatili
    permessi."""
    excluded = set()
    for package in (left, right):
        reference = package["defined_names"].get(volatile)
        if reference:
            excluded.add(GATE.split_ref(reference))
    differences = []
    for sheet in sorted(set(left["sheets"]) | set(right["sheets"])):
        first = left["sheets"].get(sheet) or {}
        second = right["sheets"].get(sheet) or {}
        for ref in sorted(set(first) | set(second)):
            if (sheet, ref) in excluded:
                continue
            if first.get(ref) != second.get(ref):
                differences.append(f"{sheet}!{ref}")
    if left["defined_names"] != right["defined_names"]:
        differences.append("defined_names")
    if left["order"] != right["order"]:
        differences.append("order")
    return differences


def c14(ctx, base):
    """`FD-C-14` `T-FIN-XLSX-NOT-A-SOURCE` — il workbook NON altera la
    verita' canonica. Verificato per CONTENUTO, non per sola esistenza."""
    findings = []
    if missing_surfaces(ctx, findings):
        return findings
    case = CHAPTER.prepare(ctx, base, name="c14")
    canonical = Path(case["canonical"])
    before = GATE.sha256_of(canonical)
    before_tree = tree_digest(Path(case["project"], STAGE10, ".working"))
    export = run_exporter(ctx, canonical, case["project"])
    if export["exit_code"] != 0:
        findings.append(
            f"l'exporter NON ha prodotto il workbook: "
            f"{export['stdout'][:300]}")
        return findings
    after = GATE.sha256_of(canonical)
    if before != after:
        findings.append(
            f"il canonico NON e' byte-identico prima e dopo l'export: "
            f"{before} -> {after} [{CODE_STALE}]")
    if before_tree != tree_digest(Path(case["project"], STAGE10, ".working")):
        findings.append(
            f"l'albero canonico `.working/` e' stato ALTERATO dall'exporter "
            f"[{CODE_STALE}]")
    package = GATE.read_package(Path(case["project"], STAGE10, WORKBOOK_NAME))
    readme = " ".join(str(entry.get("value") or "") for entry in
                      (package["sheets"].get("README") or {}).values())
    for marker in ("NON CANONICITA", "DERIVATO"):
        if marker not in readme.upper():
            findings.append(
                f"il README NON dichiara la non-canonicita': marcatore "
                f"{marker!r} assente [{CODE_INCOMPLETE}]")
    # RED — `MUT-3-36`: l'exporter scrive un path canonico.
    report = export["report"] or {}
    workbook_path = Path(report.get("workbook") or "")
    if ".working" in workbook_path.parts:
        findings.append(
            f"l'exporter scrive DENTRO l'albero canonico: {workbook_path} "
            f"[{CODE_STALE}]")
    probe = Path(case["project"], STAGE10, ".working", "probe-canonical.json")
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("{}", encoding="utf-8")
    if tree_digest(probe.parent.parent) == before_tree:
        findings.append(
            "la sonda di ALTERAZIONE dell'albero canonico non e' rilevata "
            f"dalla misura: il contratto non discrimina [{CODE_STALE}]")
    probe.unlink()
    return findings


def tree_digest(root):
    import hashlib
    digest = hashlib.sha256()
    root = Path(root)
    if not root.exists():
        return ""
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def c15(ctx, base):
    """`FD-C-15` `T-FIN-DERIVED-ATOMIC` — ATOMICITA' DI INSIEME.

    Misura lo stato DOPO IL RITORNO dell'operazione, non l'esito del gate 2.
    """
    findings = []
    if missing_surfaces(ctx, findings):
        return findings
    generation_n = prepare(ctx, base, name="c15-n", level="full")
    if not_exported(generation_n, findings):
        return findings
    generation_next = prepare(ctx, base, name="c15-next", level="partial")
    if not_exported(generation_next, findings):
        return findings
    project = Path(generation_n["project"])
    # I registri governati della generazione N+1 diventano quelli del progetto:
    # il nuovo canonico dev'essere COERENTE col progetto in cui e' pubblicato.
    shutil.rmtree(project / "shared")
    shutil.copytree(Path(generation_next["project"]) / "shared",
                    project / "shared")
    paths = GATE.artifact_paths(project, "tx-m5b-001")
    before = {key: GATE.sha256_of(value) for key, value in paths.items()}
    if not all(before.values()):
        findings.append(
            f"la generazione N non porta tutti e tre gli artefatti: {before} "
            f"[{CODE_INCOMPLETE}]")
        return findings
    # RED — `MUT-3-37`: fallimento INIETTATO fra la SECONDA e la TERZA
    # pubblicazione, cioe' dopo canonico e capitolo e prima del workbook.
    report = GATE.publish(project, generation_next["canonical"], "tx-m5b-001",
                          inject_failure="before-workbook")
    if report["published"]:
        findings.append(
            "l'operazione riporta SUCCESSO nonostante il fallimento iniettato "
            f"[{CODE_INCOMPLETE}]")
    if not report["rolled_back"]:
        findings.append(
            f"il rollback coordinato NON e' stato eseguito [{CODE_INCOMPLETE}]")
    after = report["sha256_after"]
    for key in ("canonical", "chapter", "workbook"):
        if after.get(key) != before.get(key):
            findings.append(
                f"l'artefatto {key!r} NON e' byte-identico alla generazione N "
                f"dopo il ritorno dell'operazione: {before.get(key)} -> "
                f"{after.get(key)} [{CODE_STALE}]")
    if not report["single_generation"]:
        findings.append(
            f"l'insieme ripristinato porta PIU' DI UNA generazione: "
            f"{report['generations']} [{CODE_STALE}]")
    if report["staging_survivors"]:
        findings.append(
            f"file di staging o di backup SOPRAVVISSUTI: "
            f"{report['staging_survivors']} [{CODE_INCOMPLETE}]")
    if not report["staging_removed"]:
        findings.append(
            f"l'area di staging NON e' stata rimossa [{CODE_INCOMPLETE}]")
    # CASO SENZA PREDECESSORE — ogni artefatto nuovo dev'essere RIMOSSO.
    fresh = prepare(ctx, base, name="c15-fresh", level="full")
    if not_exported(fresh, findings):
        return findings
    fresh_project = Path(fresh["project"])
    fresh_paths = GATE.artifact_paths(fresh_project, "tx-m5b-001")
    fresh_paths["workbook"].unlink()
    fresh_paths["chapter"].unlink()
    orphan = GATE.publish(fresh_project, fresh["canonical"], "tx-m5b-001",
                          inject_failure="before-workbook")
    if fresh_paths["chapter"].is_file():
        findings.append(
            "un artefatto nuovo PRIVO DI PREDECESSORE non e' stato RIMOSSO dal "
            f"rollback: {fresh_paths['chapter']} [{CODE_INCOMPLETE}]")
    if "chapter" not in (orphan.get("removed_without_predecessor") or []):
        findings.append(
            "il rollback non DICHIARA la rimozione dell'artefatto privo di "
            f"predecessore [{CODE_INCOMPLETE}]")
    # CASO POSITIVO — la rigenerazione riuscita porta tutti e tre a N+1.
    success = GATE.publish(project, generation_next["canonical"], "tx-m5b-001")
    if not success["published"]:
        findings.append(
            f"la rigenerazione RIUSCITA non e' esposta come successo: "
            f"{success.get('failure', '')[:200]} [{CODE_INCOMPLETE}]")
    elif not success["single_generation"]:
        findings.append(
            f"dopo una rigenerazione riuscita l'insieme porta PIU' DI UNA "
            f"generazione: {success['generations']} [{CODE_STALE}]")
    return findings


def c20(ctx, base):
    """`FD-C-20` `T-FIN-DERIVED-INPUT-SET` — insieme CHIUSO e verificato
    per HASH."""
    findings = []
    if missing_surfaces(ctx, findings):
        return findings
    case = prepare(ctx, base, name="c20")
    if not_exported(case, findings):
        return findings
    report = (case["export"] or {}).get("report") or {}
    declared = list(report.get("input_set_declared") or [])
    if len(declared) != 3:
        findings.append(
            f"l'insieme di ingresso DICHIARATO non e' CHIUSO A TRE: {declared} "
            f"[{CODE_INCOMPLETE}]")
    checks = report.get("governed_checks") or []
    unverified = [entry for entry in checks if not entry.get("verified")]
    if unverified:
        findings.append(
            f"attributi di input governato NON verificati per impronta: "
            f"{[entry.get('driver_id') for entry in unverified]} "
            f"[{CODE_STALE}]")
    if not checks:
        findings.append(
            f"nessuna verifica di impronta e' stata eseguita: la verifica "
            f"di freschezza degli input governati sarebbe VACUA [{CODE_STALE}]")
    findings.extend(f"{item['where']}: {item['message']}"
                    for item in GATE.xrec_06(case["project"], case["document"]))
    # RED — `MUT-3-42`: un record governato e' alterato, e l'impronta diverge.
    register = Path(case["project"], "shared", "assumptions-register.json")
    original = register.read_bytes()
    records = json.loads(original.decode("utf-8"))
    records[0]["value"] = shift(records[0].get("value") or "0", "7")
    register.write_text(json.dumps(records, indent=2, ensure_ascii=True,
                                   sort_keys=True, default=str),
                        encoding="utf-8")
    stale = GATE.xrec_06(case["project"], case["document"])
    if not any(item["code"] == CODE_STALE for item in stale):
        findings.append(
            "un record governato ALTERATO non produce `derived_artifact_stale`: "
            f"la verifica di impronta e' VACUA [{CODE_STALE}]")
    blocked = run_exporter(ctx, case["canonical"], case["project"])
    if blocked["exit_code"] == 0:
        findings.append(
            "l'exporter PRODUCE il workbook nonostante l'impronta divergente: "
            f"il valore e' stato USATO [{CODE_STALE}]")
    register.write_bytes(original)
    # RED — un QUARTO registro letto sarebbe VISIBILE.
    if len(set(declared)) != len(declared):
        findings.append(
            f"l'insieme di ingresso DICHIARATO porta duplicati: {declared} "
            f"[{CODE_INCOMPLETE}]")
    return findings


def c21(ctx, base):
    """`FD-C-21` `T-FIN-XLSX-ASSUMPTION-REGISTER` — tracciabilita'
    BIDIREZIONALE, con le due direzioni verificate SEPARATAMENTE."""
    findings = []
    if missing_surfaces(ctx, findings):
        return findings
    case = prepare(ctx, base, name="c21")
    if not_exported(case, findings):
        return findings
    tokens = ctx["style_tokens"]
    package = case["package"]
    document = case["document"]
    fields = (tokens.get("workbook") or {}).get(
        "assumption_register_fields") or []
    if len(fields) != 16:
        findings.append(
            f"i campi DICHIARATI dell'Assumption Register sono {len(fields)} "
            f"invece di SEDICI [{CODE_INCOMPLETE}]")
    findings.extend(f"{item['where']}: {item['message']}"
                    for item in GATE.xrec_05(document, package, tokens))
    # RED — direzione 1: una cella arancione SENZA riga di Register.
    location_column = chr(ord("A") + fields.index("workbook_location"))
    first_direction = mutated(package)
    register = first_direction["sheets"]["Assumption Register"]
    # La riga di INTESTAZIONE porta essa stessa il testo `workbook_location`:
    # va SALTATA, altrimenti la mutazione colpirebbe l'intestazione e il
    # contratto fallirebbe per una ragione NON PERTINENTE.
    header_row = None
    for row_index in sorted(rows_of(package, "Assumption Register")):
        columns = rows_of(package, "Assumption Register")[row_index]
        if str((columns.get(location_column) or {}).get("value") or "") == \
                "workbook_location":
            header_row = row_index
            break
    victim = None
    for ref in sorted(register, key=lambda item: (row_of(item),
                                                  column_of(item))):
        if column_of(ref) != location_column or not register[ref].get("value"):
            continue
        if header_row is not None and row_of(ref) <= header_row:
            continue
        victim = ref
        break
    if victim is None:
        findings.append(
            f"nessuna riga di Register con `workbook_location`: la direzione 1 "
            f"non e' misurabile [{CODE_INCOMPLETE}]")
        return findings
    register[victim]["value"] = ""
    detected = GATE.xrec_05(document, first_direction, tokens)
    if not any("ESATTAMENTE UNA" in item["message"] for item in detected):
        findings.append(
            "una cella arancione SENZA riga di Assumption Register NON e' "
            f"rilevata (direzione 1) [{CODE_INCOMPLETE}]")
    # RED — direzione 2: una riga che punta a una posizione INESISTENTE.
    second_direction = mutated(package)
    register = second_direction["sheets"]["Assumption Register"]
    register[victim]["value"] = "Assumptions!ass_INESISTENTE"
    detected = GATE.xrec_05(document, second_direction, tokens)
    if not any("INESISTENTE" in item["message"] for item in detected):
        findings.append(
            "una riga di Register che punta a una posizione INESISTENTE NON e' "
            f"rilevata (direzione 2) [{CODE_INCOMPLETE}]")
    # Le DUE direzioni sono verificate SEPARATAMENTE, non in blocco.
    if not GATE.xrec_05(document, first_direction, tokens) or \
            not GATE.xrec_05(document, second_direction, tokens):
        findings.append(
            "le due direzioni non falliscono SEPARATAMENTE: il contratto non "
            f"le distingue [{CODE_INCOMPLETE}]")
    return findings


def c22(ctx, base):
    """`FD-C-22` `T-FIN-XLSX-INPUT-OUTPUT-SEPARATION`."""
    findings = []
    if missing_surfaces(ctx, findings):
        return findings
    case = prepare(ctx, base, name="c22")
    if not_exported(case, findings):
        return findings
    tokens = ctx["style_tokens"]
    package = case["package"]
    findings.extend(separation_findings(package, tokens))
    # RED — `MUT-3-44`: una FORMULA dentro una cella di assunzione.
    mutant = mutated(package)
    target = first_assumption_ref(package, tokens)
    mutant["sheets"]["Assumptions"][target]["formula"] = "SUM(B1)"
    detected = separation_findings(mutant, tokens)
    if not any(target in item and "FORMULA" in item for item in detected):
        findings.append(
            f"una FORMULA dentro una cella di ASSUNZIONE ({target}) NON e' "
            f"rilevata, o la CELLA non e' NOMINATA [{CODE_INCOMPLETE}]")
    # RED — blocchi NON disgiunti.
    overlap = mutated(package)
    overlap["defined_names"]["out_Assumptions"] = \
        overlap["defined_names"]["in_Assumptions"]
    if not any("NON DISGIUNTI" in item for item in
               separation_findings(overlap, tokens)):
        findings.append(
            "blocchi di input e output NON DISGIUNTI non sono rilevati "
            f"[{CODE_INCOMPLETE}]")
    return findings


# --------------------------------------------------------------------------
# Registro dei contratti
# --------------------------------------------------------------------------


CONTRACTS = [
    {"id": "FD-C-01", "name": "T-FIN-XLSX-STRUCTURE", "fn": c01,
     "fixture": "F-12", "expected_code": CODE_INCOMPLETE,
     "mutation": "MUT-3-23"},
    {"id": "FD-C-02", "name": "T-FIN-XLSX-SHEETS", "fn": c02,
     "fixture": "F-12 + variante derivata in-modulo di F-13(b)",
     "expected_code": CODE_INCOMPLETE, "mutation": "MUT-3-24"},
    {"id": "FD-C-03", "name": "T-FIN-XLSX-NUMERIC-CONSISTENCY", "fn": c03,
     "fixture": "F-13(c)", "expected_code": CODE_MISMATCH,
     "mutation": "MUT-3-25"},
    {"id": "FD-C-04", "name": "T-FIN-XLSX-ASSUMPTION-ORANGE", "fn": c04,
     "fixture": "F-12", "expected_code": CODE_INCOMPLETE,
     "mutation": "MUT-3-26"},
    {"id": "FD-C-05", "name": "T-FIN-XLSX-NO-ORANGE-ON-OUTPUT", "fn": c05,
     "fixture": "F-12", "expected_code": CODE_INCOMPLETE,
     "mutation": "MUT-3-27"},
    {"id": "FD-C-06", "name": "T-FIN-XLSX-STATIC-QA", "fn": c06,
     "fixture": "F-13", "expected_code": CODE_INCOMPLETE,
     "mutation": "MUT-3-28"},
    {"id": "FD-C-07", "name": "T-FIN-XLSX-SCENARIO-CONTROLS", "fn": c07,
     "fixture": "F-1, F-3", "expected_code": CODE_INCOMPLETE,
     "mutation": "MUT-3-29"},
    {"id": "FD-C-08", "name": "T-FIN-XLSX-FORMULA-ROUNDTRIP", "fn": c08,
     "fixture": "F-12", "expected_code": CODE_INCOMPLETE,
     "mutation": "MUT-3-30"},
    {"id": "FD-C-09", "name": "T-FIN-XLSX-NO-ECONOMIC-HARDCODES", "fn": c09,
     "fixture": "variante derivata in-modulo di F-13(e)",
     "expected_code": CODE_MISMATCH, "mutation": "MUT-3-31"},
    {"id": "FD-C-10", "name": "T-FIN-XLSX-TEXT-LABELS", "fn": c10,
     "fixture": "F-12", "expected_code": CODE_INCOMPLETE,
     "mutation": "MUT-3-32"},
    {"id": "FD-C-12", "name": "T-FIN-DERIVED-CROSS-CONSISTENCY", "fn": c12,
     "fixture": "F-13(c)", "expected_code": CODE_MISMATCH,
     "mutation": "MUT-3-34"},
    {"id": "FD-C-13", "name": "T-FIN-XLSX-RENDER-DETERMINISM", "fn": c13,
     "fixture": "F-12", "expected_code": CODE_INCOMPLETE,
     "mutation": "MUT-3-35"},
    {"id": "FD-C-14", "name": "T-FIN-XLSX-NOT-A-SOURCE", "fn": c14,
     "fixture": "F-12", "expected_code": CODE_STALE, "mutation": "MUT-3-36"},
    {"id": "FD-C-15", "name": "T-FIN-DERIVED-ATOMIC", "fn": c15,
     "fixture": "F-13 con una generazione COMPLETA JSON_N + MD_N + XLSX_N",
     "expected_code": CODE_STALE, "mutation": "MUT-3-37"},
    {"id": "FD-C-20", "name": "T-FIN-DERIVED-INPUT-SET", "fn": c20,
     "fixture": "F-12, F-13(d)", "expected_code": CODE_STALE,
     "mutation": "MUT-3-42"},
    {"id": "FD-C-21", "name": "T-FIN-XLSX-ASSUMPTION-REGISTER", "fn": c21,
     "fixture": "F-12", "expected_code": CODE_INCOMPLETE,
     "mutation": "MUT-3-43"},
    {"id": "FD-C-22", "name": "T-FIN-XLSX-INPUT-OUTPUT-SEPARATION",
     "fn": c22, "fixture": "F-12", "expected_code": CODE_INCOMPLETE,
     "mutation": "MUT-3-44"},
]

CONTRACT_IDS = tuple(entry["id"] for entry in CONTRACTS)


# --------------------------------------------------------------------------
# Esecuzione
# --------------------------------------------------------------------------


def run_one(ctx, contract):
    with tempfile.TemporaryDirectory(prefix="fin_xlsx_") as base:
        try:
            findings = contract["fn"](ctx, Path(base))
        except HarnessDefect:
            raise
        except (AssertionError, AttributeError, IndexError, KeyError,
                OSError, TypeError, ValueError) as exc:
            findings = [f"errore di valutazione del contratto: {exc!r}"]
    return {"contract": contract, "red": bool(findings), "findings": findings}


def format_line(result):
    contract = result["contract"]
    return ("{state:<5} {cid:<12} {name:<38} fixture={fixture} | EXPECTED: "
            "{exp} | mutazione={mut} | reason={reason}".format(
                state="RED" if result["red"] else "GREEN",
                cid=contract["id"], name=contract["name"],
                fixture=contract["fixture"], exp=contract["expected_code"],
                mut=contract["mutation"],
                reason="; ".join(str(item) for item in result["findings"])
                or "-"))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(
        prog="test_fin_xlsx.py", add_help=True,
        description="Contratti del workbook financial-model.xlsx dello "
                    "Stage 10.")
    parser.add_argument("--root", required=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--contract", help="esegue un solo contratto")
    mode.add_argument("--all", action="store_true",
                      help="esegue tutti i contratti (default)")
    parser.add_argument("--list", action="store_true",
                        help="elenca gli id dei contratti ospitati qui")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE

    if args.list:
        for contract_id in CONTRACT_IDS:
            print(contract_id)
        return EXIT_OK

    try:
        root = resolve_root(args.root)
    except HarnessUsageError as exc:
        print(f"USAGE ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.contract and args.contract not in CONTRACT_IDS:
        print(f"USAGE ERROR: contratto inesistente: {args.contract}; ammessi: "
              f"{', '.join(CONTRACT_IDS)}", file=sys.stderr)
        return EXIT_USAGE

    global CHAPTER, GATE
    try:
        CHAPTER = load_chapter_harness(root)
        GATE = load_gate(root)
        ctx = build_context(root)
        selected = [entry for entry in CONTRACTS
                    if not args.contract or entry["id"] == args.contract]
        results = [run_one(ctx, entry) for entry in selected]
    except HarnessDefect as exc:
        print(f"HARNESS DEFECT: {exc}", file=sys.stderr)
        return EXIT_STATE
    except HarnessUsageError as exc:
        print(f"USAGE ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE

    for result in results:
        print(format_line(result))
    red = [result for result in results if result["red"]]
    print("SUMMARY: {total} contratti, {red} RED, {green} GREEN "
          "(exporter {e}: {es}; gate {g}: {gs})".format(
              total=len(results), red=len(red), green=len(results) - len(red),
              e=EXPORTER_REL,
              es="presente" if ctx["exporter"].is_file() else "ASSENTE",
              g=GATE_REL,
              gs="presente" if ctx["gate_path"].is_file() else "ASSENTE"))
    if red:
        return EXIT_RED
    print("PASS: T-FIN-XLSX {n} contratti del workbook financial-model.xlsx "
          "dello Stage 10".format(n=len(results)))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
