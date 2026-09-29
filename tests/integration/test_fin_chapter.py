#!/usr/bin/env python3
"""T-FIN-CHAPTER — i cinque contratti del CAPITOLO `financial-plan.md`.

Il capitolo e' il derivato Markdown dello Stage 10, reso dal solo documento
canonico da `output/render_financial_plan.py`. Il modulo entra nel glob di
ENTRAMBI i runner (`tests/run-tests.ps1` e `tests/run-tests.sh` globano
`tests/integration/test_*.py`).

CINQUE CONTRATTI OSPITATI QUI
-----------------------------
    FD-C-11  T-FIN-CHAPTER-NUMERIC-CONSISTENCY
    FD-C-16  T-FIN-CHAPTER-COMPLETENESS
    FD-C-17  T-FIN-CHAPTER-NO-UNTRACED-VALUES
    FD-C-18  T-FIN-CHAPTER-STATUS-FIDELITY
    FD-C-19  T-FIN-CHAPTER-PARTIAL-COVERAGE

I RESTANTI DICIASSETTE contratti dei derivati dello Stage 10 vivono in
`tests/integration/test_fin_xlsx.py`: il capitolo e' verificabile da solo,
senza dipendere dall'exporter del workbook.

DISCIPLINA
----------
Ogni contratto e' INDIPENDENTE e riporta la PROPRIA constatazione e il PROPRIO
codice atteso. Il registro delle fixture `F-1`...`F-13` di `bpo_testkit.py`
resta CHIUSO: le varianti usate qui sono DERIVATE IN-MODULO.

SEMANTICA DEGLI EXIT CODE
-------------------------
    0   tutti i contratti soddisfatti
    1   almeno un contratto RED
    2   errore d'uso
    3   stato del repository inutilizzabile (difetto di harness)
"""
import argparse
import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

SKILL_REL = ".claude/skills/business-plan-orchestrator"
TESTKIT_REL = "tests/integration"
M5A_HARNESS = "test_fin_output"

RENDERER_REL = f"{SKILL_REL}/output/render_financial_plan.py"
STYLE_TOKENS_REL = f"{SKILL_REL}/output/style_tokens.json"
CHAPTER_NAME = "financial-plan.md"
STAGE10 = "10_financial-plan"

EXIT_OK = 0
EXIT_RED = 1
EXIT_USAGE = 2
EXIT_STATE = 3

CODE_INCOMPLETE = "derived_artifact_incomplete"
CODE_MISMATCH = "derived_artifact_numeric_mismatch"
CODE_STALE = "derived_artifact_stale"

#: Tolleranze DI REPOSITORY, lette da `config/enforcement-config.json`:
#: `EUR 0.01`, `ratio 1e-6`, `count` esatto. Gli stock in `FTE` sono
#: confrontati per uguaglianza esatta, come gia' nelle riconciliazioni.
EXACT_UNITS = ("count", "FTE", "period_index", "EUR/count", "EUR/FTE")

#: I CINQUE elementi di traccia che ogni numero mostrato deve portare.
#: Quattro sono colonne di riga, il quinto e' il
#: `canonical_source_checksum` portato dalla DIDASCALIA della tabella.
TRACE_ELEMENTS = ("path", "scenario", "period", "unit", "checksum")

SECTION_RE = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$")
CAPTION_RE = re.compile(
    r"^\*\*Tabella\s+(\d+)\s+—\s+(.+?)\.\*\*\s+Fonte:\s+`([^`]+)`\s+·\s+"
    r"checksum\s+`([^`]*)`\.\s*$")
NUMERIC_RE = re.compile(r"^[+-]?(?:[0-9]+)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")

M5A = None  # popolato da `main`


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


def load_m5a_harness(root):
    """Riusa i costruttori DICHIARATIVI di `tests/integration/test_fin_output.py`.

    Nessuna duplicazione dell'ingresso: il capitolo consuma il canonico
    prodotto da `output/build_canonical_output.py`, costruito con il SOLO
    costruttore gia' esistente, invocato attraverso l'harness dell'output
    canonico. E' lo stesso riuso con cui `test_fin_output.py` consuma
    `test_fin_engine.py`.
    """
    path = root / TESTKIT_REL / f"{M5A_HARNESS}.py"
    if not path.is_file():
        raise HarnessDefect(f"harness dell'output canonico assente: {path}")
    spec = importlib.util.spec_from_file_location(M5A_HARNESS, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[M5A_HARNESS] = module
    spec.loader.exec_module(module)
    module.ENG = module.load_engine_harness(root)
    return module


def build_context(root):
    ctx = M5A.build_context(root)
    ctx["renderer"] = root / RENDERER_REL
    ctx["style_tokens_path"] = root / STYLE_TOKENS_REL
    ctx["style_tokens"] = None
    if ctx["style_tokens_path"].is_file():
        try:
            ctx["style_tokens"] = json.loads(
                ctx["style_tokens_path"].read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HarnessDefect(f"style_tokens.json corrotto: {exc}")
    return ctx


MISSING_RENDERER = (
    "output/render_financial_plan.py ASSENTE: il renderer del capitolo e' "
    "obbligatorio e nessun contratto del capitolo e' misurabile "
    "senza di esso")
MISSING_TOKENS = (
    "output/style_tokens.json ASSENTE: la tabella dei cinque token di stile e "
    "il LESSICO CHIUSO di promozione sono un DATO DICHIARATO e "
    "senza di essi la resa non e' deterministica ne' misurabile")


# --------------------------------------------------------------------------
# Varianti DERIVATE IN-MODULO — il registro F-1...F-13 resta CHIUSO
# --------------------------------------------------------------------------


#: La terna DICHIARATA di ciascun record, nella stessa forma che
#: `test_fin_engine.triplet_records` usa per la fixture `F-1`.
TRIPLET_SPREAD = {
    "ASS-001": ("90", "100", "110"),
    "ASS-002": ("8", "10", "12"),
    "ASS-003": ("0.10", "0.16", "0.24"),
    "ASS-004": ("36", "40", "44"),
    "ASS-005": ("2", "2", "2"),
    "ASS-006": ("2700", "3000", "3300"),
    "ASS-007": ("10800", "12000", "13200"),
}

#: Sottoinsieme che produce copertura PARZIALE: quattro ruoli su sette, sotto
#: la soglia dichiarata `0.8`, con Downside e Upside comunque PRODOTTI.
PARTIAL_REFS = ("ASS-001", "ASS-002", "ASS-004", "ASS-005")


def coverage_records(ctx, level):
    """`F-1` (piena), variante PARZIALE derivata in-modulo, `F-3` (nulla)."""
    records = M5A.ENG.base_records(ctx["eng"])
    if level == "full":
        refs = tuple(sorted(TRIPLET_SPREAD))
    elif level == "partial":
        refs = PARTIAL_REFS
    else:
        refs = ()
    for ref in refs:
        low, mid, high = TRIPLET_SPREAD[ref]
        M5A.ENG.with_triplet(records, ref, low, mid, high)
    return records


def prepare(ctx, base, name="chapter", level="full", tx="tx-m5b-001"):
    """Progetto TEMPORANEO di fixture COERENTE, canonico e capitolo.

    Il progetto e' COERENTE nel senso che la verifica di freschezza degli
    input governati esige: i record canonici
    che il motore ha legato SONO il registro governato del progetto, e le
    impronte `source_record_hash` dei driver coincidono con i record letti in
    sola lettura. Un progetto incoerente farebbe fallire il renderer per
    `derived_artifact_stale`, cioe' per una ragione NON PERTINENTE al
    contratto misurato.
    """
    records = coverage_records(ctx, level)
    rows = M5A.ENG.base_rows(ctx["eng"], records)
    _, run = M5A.engine_run(ctx, base, rows, records, name=f"{name}-engine")
    payload = run["result"]
    project = M5A.fixture_project(ctx, base, name)
    Path(project, "shared", "assumptions-register.json").write_text(
        json.dumps(list(records.values()), indent=2, ensure_ascii=True,
                   sort_keys=True, default=str), encoding="utf-8")
    payload_path = M5A.write_payload(base, payload, name=f"{name}-payload.json")
    built = M5A.run_builder(ctx, payload_path, project, tx=tx)
    canonical = M5A.canonical_path(project, tx)
    document = None
    if canonical.is_file():
        document = json.loads(canonical.read_text(encoding="utf-8"))
    rendered = run_renderer(ctx, canonical, project)
    chapter = Path(project, STAGE10, CHAPTER_NAME)
    text = chapter.read_text(encoding="utf-8") if chapter.is_file() else None
    return {"project": project, "payload_path": payload_path, "built": built,
            "canonical": canonical, "document": document,
            "rendered": rendered, "chapter": chapter, "text": text,
            "records": records}


def run_renderer(ctx, canonical, project, extra=()):
    """Invoca il RENDERER DI PRODUZIONE, mai una copia."""
    renderer = ctx["renderer"]
    if not renderer.is_file():
        return {"available": False, "reason": MISSING_RENDERER,
                "exit_code": None, "report": None, "stdout": "", "stderr": ""}
    command = [sys.executable, str(renderer), "--canonical", str(canonical),
               "--project", str(project)]
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
    return {"available": True, "reason": "", "exit_code": proc.returncode,
            "report": report, "stdout": proc.stdout, "stderr": proc.stderr,
            "command": " ".join(command)}


def unavailable(state, findings):
    if not state.get("available", True):
        findings.append(state["reason"])
        return True
    return False


def not_rendered(case, findings):
    """`True` quando il capitolo NON e' stato prodotto, con la PROPRIA
    constatazione registrata: nessun contratto e' GREEN per silenzio."""
    if unavailable(case["rendered"], findings):
        return True
    if case["text"] is None:
        findings.append(
            f"nessun capitolo prodotto (exit "
            f"{case['rendered'].get('exit_code')}): "
            f"{(case['rendered'].get('stderr') or '')[:200]}"
            f"{json.dumps(((case['rendered'].get('report') or {}).get('errors') or []))[:300]}")
        return True
    return False


def missing_tokens(ctx, findings):
    if ctx.get("style_tokens") is None:
        findings.append(MISSING_TOKENS)
        return True
    return False


# --------------------------------------------------------------------------
# Lettura del capitolo — sezioni, tabelle, righe e i cinque elementi
# --------------------------------------------------------------------------


def parse_chapter(text):
    """Scompone il capitolo in SEZIONI, TABELLE e RIGHE DI VALORE.

    Il formato e' quello DICHIARATO dal renderer: un titolo `## <n>. <titolo>`
    apre una sezione; una didascalia `**Tabella <n> — <titolo>.** Fonte:
    `<file>` · checksum `<sha>`.` apre una tabella; le righe che seguono la
    riga di intestazione portano le SEI colonne dichiarate.
    """
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
                               "title": match.group(2), "line": number,
                               "body": [], "tables": []}
            sections.append(current_section)
            current_table = None
            header_seen = False
            continue
        caption = CAPTION_RE.match(line)
        if caption:
            current_table = {"number": caption.group(1),
                             "title": caption.group(2),
                             "source": caption.group(3),
                             "checksum": caption.group(4),
                             "line": number, "rows": [],
                             "section": current_section}
            tables.append(current_table)
            if current_section is not None:
                current_section["tables"].append(current_table)
            header_seen = False
            continue
        if line.startswith("|") and current_table is not None:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if not header_seen:
                current_table["columns"] = cells
                header_seen = True
                continue
            if all(set(cell) <= set("- ") for cell in cells):
                continue
            if len(cells) < 6:
                current_table["rows"].append({"malformed": line,
                                              "line": number})
                continue
            current_table["rows"].append({
                "label": cells[0], "value": cells[1], "unit": cells[2],
                "scenario": cells[3], "period": cells[4],
                "path": cells[5].strip("`"), "line": number,
                "checksum": current_table["checksum"],
                "table": current_table["title"],
                "section": (current_section or {}).get("title"),
            })
            continue
        if current_section is not None and line.strip():
            current_section["body"].append({"line": number, "text": line})
    return {"sections": sections, "tables": tables}


def value_rows(parsed):
    """Le sole righe che mostrano un NUMERO: sono quelle su cui i cinque
    elementi di traccia sono dovuti."""
    rows = []
    for table in parsed["tables"]:
        for entry in table["rows"]:
            if entry.get("malformed"):
                continue
            if NUMERIC_RE.match(str(entry.get("value", "")).strip()):
                rows.append(entry)
    return rows


def trace_gaps(entry):
    """Gli elementi di traccia MANCANTI su una riga, NOMINATI uno per uno."""
    gaps = []
    if not entry.get("path") or entry["path"] in ("", "-"):
        gaps.append("path")
    if not entry.get("scenario") or entry["scenario"] in ("", "-"):
        gaps.append("scenario")
    if not entry.get("period") or entry["period"] in ("", "-"):
        gaps.append("period")
    if not entry.get("unit") or entry["unit"] in ("", "-"):
        gaps.append("unit")
    if not entry.get("checksum"):
        gaps.append("checksum")
    return gaps


# --------------------------------------------------------------------------
# Risoluzione dei path e confronto entro tolleranza
# --------------------------------------------------------------------------


PATH_STEP_RE = re.compile(r"^([^\[\]]+)(?:\[([^\]]+)\])?$")


def resolve_canonical(document, path):
    """Risolve un path canonico DICHIARATO. Ritorna `(trovato, valore)`."""
    node = document
    for step in str(path).split("."):
        match = PATH_STEP_RE.match(step)
        if match is None:
            return False, None
        name, index = match.group(1), match.group(2)
        if isinstance(node, dict):
            if name not in node:
                return False, None
            node = node[name]
        else:
            return False, None
        if index is not None:
            if not isinstance(node, list):
                return False, None
            if not index.lstrip("-").isdigit():
                return False, None
            position = int(index)
            if position >= len(node):
                return False, None
            node = node[position]
    return True, node


def resolve_governed(project, reference):
    """Risolve un attributo di INPUT GOVERNATO, nella forma
    `<registro>#<REF>.<campo>`. E' l'unica sede in cui un valore non canonico
    compare, ed e' ammessa per le sole righe di ASSUNZIONE."""
    register, _, rest = str(reference).partition("#")
    ref, _, field = rest.partition(".")
    path = Path(project).joinpath(*register.split("/"))
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


def tolerance_for(unit):
    if unit in EXACT_UNITS or unit == "NON DICHIARATA":
        return Decimal("0")
    if unit == "ratio":
        return Decimal("1e-6")
    return Decimal("0.01")


def within_tolerance(shown, canonical, unit):
    """Confronto per TIPO E VALORE entro la tolleranza di repository, mai per
    stringa localizzata."""
    try:
        left = Decimal(str(shown).strip())
        right = Decimal(str(canonical).strip())
    except Exception:
        return str(shown).strip() == str(canonical).strip()
    return abs(left - right) <= tolerance_for(unit)


def numeric_findings(document, project, parsed, label="capitolo"):
    """Confronta OGNI numero mostrato con la propria fonte dichiarata."""
    findings = []
    for entry in value_rows(parsed):
        path = entry["path"]
        if " -> " in path:
            _, _, governed = path.partition(" -> ")
            found, value = resolve_governed(project, governed)
            origin = governed
        else:
            found, value = resolve_canonical(document, path)
            origin = path
        if not found:
            findings.append(
                f"{label}: riga {entry['line']} ({entry['label']}): il path "
                f"dichiarato NON risolve nella fonte: {origin}")
            continue
        if isinstance(value, (dict, list)):
            findings.append(
                f"{label}: riga {entry['line']} ({entry['label']}): il path "
                f"{origin} non punta a una foglia")
            continue
        if not within_tolerance(entry["value"], value, entry["unit"]):
            findings.append(
                f"{label}: sezione «{entry['section']}» riga {entry['line']} "
                f"({entry['label']}): valore mostrato {entry['value']!r} "
                f"contro valore canonico {value!r} ({origin}), oltre la "
                f"tolleranza {tolerance_for(entry['unit'])} "
                f"[{CODE_MISMATCH}]")
    return findings


def shift_value(text, row, delta):
    """Sostituisce, nella riga NOMINATA, il valore mostrato con il valore
    alterato di `delta`. E' la variante DERIVATA IN-MODULO di `F-13(c)`."""
    lines = str(text).split("\n")
    index = row["line"] - 1
    altered = str(Decimal(row["value"]) + Decimal(delta))
    cells = lines[index].split("|")
    for position, cell in enumerate(cells):
        if cell.strip() == row["value"]:
            cells[position] = f" {altered} "
            break
    lines[index] = "|".join(cells)
    return "\n".join(lines), altered


def first_eur_row(parsed):
    for entry in value_rows(parsed):
        if entry["unit"] == "EUR" and " -> " not in entry["path"]:
            return entry
    return None


# --------------------------------------------------------------------------
# Lessico CHIUSO di promozione
# --------------------------------------------------------------------------


CITATION_RE = re.compile(r"«[^»]*»")


def promotion_findings(tokens, document, text, label="capitolo"):
    """Scansione del LESSICO CHIUSO su PROSA GENERATA, con attribuzione di
    SEZIONE e TERMINE. Sono escluse le righe di tabella e le CITAZIONI
    VERBATIM del canonico, delimitate da caporali."""
    lexicon = (tokens or {}).get("promotion_lexicon") or {}
    plan = (document or {}).get("financial_plan") or {}
    readiness = (plan.get("validation") or {}).get("investor_readiness") or {}
    drivers = (plan.get("driver_registry") or {}).get("drivers") or []
    coverage = ((plan.get("results") or {}).get("scenarios") or {}).get(
        "coverage") or {}
    allowed = {
        "investor_readiness_ready": readiness.get("status") == "ready",
        "all_drivers_confirmed": bool(drivers) and all(
            entry.get("status") == "confirmed" for entry in drivers),
        "all_scenarios_produced": coverage.get("level") == "full",
        "never": False,
    }
    findings = []
    section = None
    for number, raw in enumerate(str(text).split("\n"), 1):
        heading = SECTION_RE.match(raw.rstrip())
        if heading:
            section = heading.group(2)
            continue
        if raw.strip().startswith("|"):
            continue
        body = CITATION_RE.sub("", raw)
        for term in lexicon.get("terms") or []:
            if allowed.get(term.get("allowed_when"), False):
                continue
            for form in term.get("forms") or []:
                pattern = re.compile(
                    "".join([r"(?<![\w-])", re.escape(form), r"(?![\w-])"]),
                    re.IGNORECASE)
                if pattern.search(body):
                    findings.append(
                        f"{label}: sezione «{section}» riga {number}: il "
                        f"termine di promozione «{term.get('term')}» "
                        f"(forma «{form}») e' usato nella PROSA GENERATA "
                        f"mentre la condizione canonica "
                        f"«{term.get('allowed_when')}» NON e' soddisfatta")
    return findings


# --------------------------------------------------------------------------
# I cinque contratti
# --------------------------------------------------------------------------


def c11(ctx, base):
    """`FD-C-11` `T-FIN-CHAPTER-NUMERIC-CONSISTENCY` — ogni valore del
    capitolo coincide col canonico ENTRO TOLLERANZA. Il contratto misura la
    TOLLERANZA, non il solo segno: `0.02 EUR` e' RED, `0.005 EUR` e' GREEN."""
    findings = []
    if missing_tokens(ctx, findings):
        return findings
    case = prepare(ctx, base, name="c11")
    if not_rendered(case, findings):
        return findings
    parsed = parse_chapter(case["text"])
    findings.extend(numeric_findings(case["document"], case["project"],
                                     parsed))
    target = first_eur_row(parsed)
    if target is None:
        findings.append(
            "nessun valore in EUR con path canonico: la tolleranza non e' "
            "misurabile")
        return findings
    # RED — variante derivata in-modulo di `F-13(c)`: `0.02 EUR` oltre la
    # tolleranza dichiarata `EUR 0.01`.
    altered, shown = shift_value(case["text"], target, "0.02")
    detected = numeric_findings(case["document"], case["project"],
                                parse_chapter(altered), label="alterato")
    if not detected:
        findings.append(
            f"un valore alterato di 0.02 EUR ({target['label']}: "
            f"{target['value']} -> {shown}) NON e' rilevato: la tolleranza "
            f"dichiarata EUR 0.01 non e' applicata [{CODE_MISMATCH}]")
    # ESCLUSIONE DI FALSO POSITIVO — `0.005 EUR` resta ENTRO tolleranza.
    inside, _ = shift_value(case["text"], target, "0.005")
    survivors = numeric_findings(case["document"], case["project"],
                                 parse_chapter(inside), label="entro")
    if survivors:
        findings.append(
            "uno scarto di 0.005 EUR, ENTRO la tolleranza dichiarata, e' "
            f"segnalato come divergenza: il confronto misura il segno e non "
            f"la tolleranza: {survivors[0]}")
    return findings


def c16(ctx, base):
    """`FD-C-16` `T-FIN-CHAPTER-COMPLETENESS` — quindici sezioni, dodici
    tabelle e PERIODI CRITICI NOMINATI. Una sezione presente ma VUOTA non
    soddisfa."""
    findings = []
    if missing_tokens(ctx, findings):
        return findings
    case = prepare(ctx, base, name="c16")
    if not_rendered(case, findings):
        return findings
    tokens = ctx["style_tokens"]
    parsed = parse_chapter(case["text"])
    declared_sections = (tokens.get("chapter") or {}).get("sections") or []
    declared_tables = (tokens.get("chapter") or {}).get("tables") or []
    titles = [entry["title"] for entry in parsed["sections"]]
    for entry in declared_sections:
        if entry["title"] not in titles:
            findings.append(
                f"sezione obbligatoria ASSENTE: «{entry['title']}» "
                f"(§{entry['number']}) [{CODE_INCOMPLETE}]")
    if len(parsed["sections"]) != len(declared_sections):
        findings.append(
            f"il capitolo porta {len(parsed['sections'])} sezioni invece "
            f"delle {len(declared_sections)} dichiarate [{CODE_INCOMPLETE}]")
    for section in parsed["sections"]:
        if not section["body"] and not section["tables"]:
            findings.append(
                f"sezione «{section['title']}» PRESENTE ma VUOTA: una sezione "
                f"vuota non soddisfa il requisito [{CODE_INCOMPLETE}]")
    rendered_tables = [entry["title"] for entry in parsed["tables"]]
    for entry in declared_tables:
        if entry["title"] not in rendered_tables:
            findings.append(
                f"tabella obbligatoria ASSENTE: «{entry['title']}» "
                f"(tabella {entry['number']}) [{CODE_INCOMPLETE}]")
    if len(parsed["tables"]) != len(declared_tables):
        findings.append(
            f"il capitolo porta {len(parsed['tables'])} tabelle invece delle "
            f"{len(declared_tables)} dichiarate [{CODE_INCOMPLETE}]")
    for table in parsed["tables"]:
        if not table["rows"]:
            findings.append(
                f"tabella «{table['title']}» PRESENTE ma senza alcuna riga "
                f"[{CODE_INCOMPLETE}]")
    # PERIODI CRITICI — nominati, mai taciuti.
    report = case["rendered"].get("report") or {}
    critical = report.get("critical_periods") or {}
    minimum = critical.get("minimum_cash") or {}
    if minimum.get("period") is None:
        findings.append(
            f"periodo di CASSA MINIMA non nominato dal renderer "
            f"[{CODE_INCOMPLETE}]")
    elif f"`{minimum['period']}`" not in case["text"]:
        findings.append(
            f"il periodo di CASSA MINIMA {minimum['period']!r} non compare "
            f"nel capitolo: una sintesi che tace un periodo critico e' "
            f"{CODE_INCOMPLETE}")
    for name, key in (("cassa zero", "zero_cash_period"),
                      ("break-even", "break_even_outcome")):
        value = critical.get(key)
        if value is None:
            continue
        if str(value) not in case["text"]:
            findings.append(
                f"il periodo critico «{name}» ({value!r}) non e' NOMINATO nel "
                f"capitolo [{CODE_INCOMPLETE}]")
    # RED — variante derivata in-modulo di `F-13(a)`: la sezione «Analisi di
    # break-even» e' una delle quindici che il capitolo PRODUCE DAVVERO, mentre
    # il caso letterale della fixture nomina una sezione di sensitivita' che
    # il capitolo non produce (la sensitivity non fa parte del canonico).
    removed = drop_section(case["text"], "Analisi di break-even")
    detected = missing_section_findings(tokens, parse_chapter(removed))
    if not any("Analisi di break-even" in item for item in detected):
        findings.append(
            "la rimozione della sezione «Analisi di break-even» NON e' "
            f"rilevata: il contratto non discrimina [{CODE_INCOMPLETE}]")
    dropped_table = drop_table(case["text"], "Copertura delle milestone")
    detected_table = missing_table_findings(tokens,
                                            parse_chapter(dropped_table))
    if not any("Copertura delle milestone" in item
               for item in detected_table):
        findings.append(
            "la rimozione della tabella «Copertura delle milestone» NON e' "
            f"rilevata [{CODE_INCOMPLETE}]")
    silent = case["text"].replace(f"`{minimum.get('period')}` con valore",
                                  "(non dichiarato) con valore")
    if minimum.get("period") is not None and (
            f"`{minimum['period']}`" not in silent.split(
                "**Periodi critici, NOMINATI.**")[-1].split("\n")[0]):
        pass
    return findings


def drop_section(text, title):
    """Rimuove una SEZIONE per titolo, con il suo corpo, fino alla successiva
    intestazione di pari livello."""
    lines = str(text).split("\n")
    kept = []
    skipping = False
    for line in lines:
        heading = SECTION_RE.match(line.rstrip())
        if heading:
            skipping = heading.group(2) == title
        if not skipping:
            kept.append(line)
    return "\n".join(kept)


def drop_table(text, title):
    """Rimuove una TABELLA per titolo: didascalia, intestazione e righe."""
    lines = str(text).split("\n")
    kept = []
    skipping = False
    for line in lines:
        caption = CAPTION_RE.match(line.rstrip())
        if caption:
            skipping = caption.group(2) == title
            if skipping:
                continue
        if skipping:
            if line.strip().startswith("|") or not line.strip():
                if line.strip().startswith("|"):
                    continue
                skipping = False
            else:
                skipping = False
        kept.append(line)
    return "\n".join(kept)


def missing_section_findings(tokens, parsed):
    titles = [entry["title"] for entry in parsed["sections"]]
    return [f"sezione obbligatoria ASSENTE: «{entry['title']}»"
            for entry in (tokens.get("chapter") or {}).get("sections") or []
            if entry["title"] not in titles]


def missing_table_findings(tokens, parsed):
    titles = [entry["title"] for entry in parsed["tables"]]
    return [f"tabella obbligatoria ASSENTE: «{entry['title']}»"
            for entry in (tokens.get("chapter") or {}).get("tables") or []
            if entry["title"] not in titles]


def c17(ctx, base):
    """`FD-C-17` `T-FIN-CHAPTER-NO-UNTRACED-VALUES` — i CINQUE elementi di
    traccia su OGNI numero. CINQUE RED distinti, uno per elemento: la presenza
    di QUATTRO su cinque NON soddisfa."""
    findings = []
    if missing_tokens(ctx, findings):
        return findings
    case = prepare(ctx, base, name="c17")
    if not_rendered(case, findings):
        return findings
    parsed = parse_chapter(case["text"])
    rows = value_rows(parsed)
    if not rows:
        findings.append(
            "il capitolo non mostra alcun valore numerico: un capitolo che "
            "descrive la metodologia senza i numeri non soddisfa il requisito")
        return findings
    for entry in rows:
        gaps = trace_gaps(entry)
        if gaps:
            findings.append(
                f"riga {entry['line']} ({entry['label']}): elementi di "
                f"traccia MANCANTI {gaps} — un valore privo anche di UNO solo "
                "dei cinque elementi e' un NUMERO INVENTATO")
    # CINQUE RED distinti, uno per elemento.
    for element in TRACE_ELEMENTS:
        stripped = strip_trace(case["text"], rows[0], element)
        detected = [item for item in
                    [trace_gaps(row) for row in
                     value_rows(parse_chapter(stripped))] if item]
        named = [gap for item in detected for gap in item]
        if element not in named:
            findings.append(
                f"la rimozione dell'elemento di traccia «{element}» NON e' "
                f"rilevata: il contratto non nomina l'elemento mancante")
    return findings


def strip_trace(text, row, element):
    """Toglie UNO dei cinque elementi di traccia dalla riga nominata, o dalla
    didascalia della sua tabella per il `checksum`."""
    lines = str(text).split("\n")
    if element == "checksum":
        for index, line in enumerate(lines):
            caption = CAPTION_RE.match(line.rstrip())
            if caption and caption.group(2) == row["table"]:
                lines[index] = line.replace(f"`{caption.group(4)}`", "``")
                break
        return "\n".join(lines)
    position = {"unit": 3, "scenario": 4, "period": 5, "path": 6}[element]
    index = row["line"] - 1
    cells = lines[index].split("|")
    if position < len(cells):
        cells[position] = "  "
    lines[index] = "|".join(cells)
    return "\n".join(lines)


def c18(ctx, base):
    """`FD-C-18` `T-FIN-CHAPTER-STATUS-FIDELITY` — la prosa NON promuove
    alcuno stato. Il contratto fallisce ANCHE se ogni numero e' corretto:
    misura la RAPPRESENTAZIONE, non l'esito."""
    findings = []
    if missing_tokens(ctx, findings):
        return findings
    tokens = ctx["style_tokens"]
    nominal = prepare(ctx, base, name="c18-full")
    if not_rendered(nominal, findings):
        return findings
    none_case = prepare(ctx, base, name="c18-none", level="none")
    if not_rendered(none_case, findings):
        return findings
    for case, label in ((nominal, "F-12 copertura piena"),
                        (none_case, "F-3 copertura nulla")):
        findings.extend(promotion_findings(tokens, case["document"],
                                           case["text"], label=label))
    readiness = ((none_case["document"].get("financial_plan") or {}).get(
        "validation") or {}).get("investor_readiness") or {}
    if readiness.get("status") == "ready":
        findings.append(
            "la fixture a copertura nulla non e' `not_ready`: il RED di "
            "promozione della prontezza non sarebbe discriminante")
    # RED — tre iniezioni distinte, ciascuna attribuita.
    injections = (
        ("investor-ready",
         "Il piano e' investor-ready e puo' essere portato in banca.",
         "15. Conclusioni finanziarie"),
        ("confermato",
         "Ogni valore qui riportato e' confermato e validato.",
         "2. Assunzioni finanziarie principali"),
        ("testato",
         "Lo scenario Downside e' stato testato e stressato.",
         "10. Scenari Base, Downside e Upside"),
    )
    for term, sentence, heading in injections:
        injected = inject_after_heading(none_case["text"], heading, sentence)
        detected = promotion_findings(tokens, none_case["document"], injected,
                                      label="iniettato")
        if not any(term in item for item in detected):
            findings.append(
                f"il termine di promozione «{term}» iniettato nella sezione "
                f"«{heading}» NON e' rilevato: la scansione del lessico "
                "chiuso e' VACUA")
    # ESCLUSIONE DI FALSO POSITIVO — una CITAZIONE VERBATIM del canonico, fra
    # caporali, NON e' un'affermazione del capitolo.
    quoted = inject_after_heading(
        none_case["text"], "14. Rischi, caveat e input non risolti",
        "Il canonico riporta: «lo stato propagato canonico non e' confermato».")
    if promotion_findings(tokens, none_case["document"], quoted,
                          label="citazione"):
        findings.append(
            "una CITAZIONE VERBATIM del canonico, delimitata da caporali, e' "
            "trattata come prosa promotiva: la scansione produce falsi "
            "positivi sulle citazioni")
    return findings


def inject_after_heading(text, heading, sentence):
    lines = str(text).split("\n")
    for index, line in enumerate(lines):
        if line.strip() == f"## {heading}":
            return "\n".join([*lines[:index + 1], "", sentence,
                              *lines[index + 1:]])
    raise HarnessDefect(f"intestazione non trovata nel capitolo: {heading!r}")


def c19(ctx, base):
    """`FD-C-19` `T-FIN-CHAPTER-PARTIAL-COVERAGE` — i SETTE casi di
    frontiera della copertura di scenario, verificati su TRE livelli di
    copertura e non su
    uno."""
    findings = []
    if missing_tokens(ctx, findings):
        return findings
    cases = {}
    for level in ("full", "partial", "none"):
        case = prepare(ctx, base, name=f"c19-{level}", level=level)
        if not_rendered(case, findings):
            return findings
        cases[level] = case
        observed = (((case["document"].get("financial_plan") or {}).get(
            "results") or {}).get("scenarios") or {}).get("coverage") or {}
        if observed.get("level") != level:
            raise HarnessDefect(
                f"la variante derivata in-modulo per la copertura {level!r} "
                f"ha prodotto {observed.get('level')!r}")
    # Caso 2 — copertura NULLA: nessuna sezione Downside o Upside etichettata.
    none_text = cases["none"]["text"]
    parsed_none = parse_chapter(none_text)
    for section in parsed_none["sections"]:
        for forbidden in ("Downside", "Upside"):
            if re.search("".join([r"(?<![\w-])", forbidden, r"(?![\w-])"]),
                         section["title"]) and section["title"] != (
                             "Scenari Base, Downside e Upside"):
                findings.append(
                    f"con copertura NULLA il capitolo porta la sezione "
                    f"«{section['title']}» etichettata {forbidden}")
    for row in value_rows(parsed_none):
        if row["scenario"] in ("downside", "upside"):
            findings.append(
                f"con copertura NULLA il capitolo mostra un valore dello "
                f"scenario {row['scenario']!r} (riga {row['line']}): gli "
                "scenari non prodotti non hanno serie")
    coverage_none = (((cases["none"]["document"].get("financial_plan") or {})
                      .get("results") or {}).get("scenarios") or {}).get(
                          "coverage") or {}
    condition = coverage_none.get("proposed_condition_ref")
    if condition and condition not in none_text:
        findings.append(
            f"con copertura NULLA la condizione proposta {condition!r} non e' "
            f"NOMINATA nel capitolo [{CODE_INCOMPLETE}]")
    if f"`{None if not coverage_none else 'NOT_APPLICABLE'}`" not in none_text:
        findings.append(
            "con copertura NULLA il capitolo non dichiara NOT_APPLICABLE gli "
            "scenari non prodotti")
    # Caso 1 — copertura PARZIALE: stato e driver NOMINATI, nel CORPO.
    partial_text = cases["partial"]["text"]
    if "partial_coverage" not in partial_text:
        findings.append(
            "con copertura PARZIALE lo stato `partial_coverage` non compare "
            f"nel capitolo [{CODE_INCOMPLETE}]")
    uncovered = sorted((((cases["partial"]["document"].get("financial_plan")
                          or {}).get("results") or {}).get("scenarios")
                        or {}).get("coverage", {}).get(
                            "uncovered_driver_refs") or [])
    for ref in uncovered:
        if ref not in partial_text:
            findings.append(
                f"con copertura PARZIALE il driver privo di terna {ref} non e' "
                f"NOMINATO nel capitolo [{CODE_INCOMPLETE}]")
    # Caso 3 — metrica non disponibile: riga PRESENTE con NOT_APPLICABLE.
    for level, case in cases.items():
        modules = (((case["document"].get("financial_plan") or {}).get(
            "results") or {}).get("modules") or {})
        indicators = (modules.get("kpi") or {}).get("indicators") or {}
        for kpi_id, entry in sorted(indicators.items()):
            if entry.get("status") != "NOT_APPLICABLE":
                continue
            if kpi_id not in case["text"]:
                findings.append(
                    f"[{level}] il KPI {kpi_id} in stato NOT_APPLICABLE e' "
                    f"OMESSO dal capitolo: mai una riga omessa "
                    f"[{CODE_INCOMPLETE}]")
        for module_id in sorted(modules):
            if (modules[module_id] or {}).get("status") != "NOT_APPLICABLE":
                continue
            if module_id not in case["text"]:
                findings.append(
                    f"[{level}] il modulo {module_id} in stato "
                    f"NOT_APPLICABLE non e' NOMINATO nel capitolo "
                    f"[{CODE_INCOMPLETE}]")
    # Caso 4 — assunzioni in attesa: conteggio ESPLICITO nelle conclusioni.
    for level, case in cases.items():
        drivers = ((case["document"].get("financial_plan") or {}).get(
            "driver_registry") or {}).get("drivers") or []
        pending = [entry for entry in drivers
                   if entry.get("status") in ("inferred", "placeholder")]
        marker = f"Assunzioni in attesa di validazione: {len(pending)}"
        if marker not in case["text"]:
            findings.append(
                f"[{level}] il conteggio esplicito delle assunzioni in attesa "
                f"({len(pending)}) non compare nelle conclusioni")
    # Caso 5 — caveat materiali: OGNI warning riportato e attribuito.
    for level, case in cases.items():
        warnings = (((case["document"].get("financial_plan") or {}).get(
            "validation") or {}).get("warnings") or [])
        for warning in warnings:
            if str(warning.get("code")) not in case["text"]:
                findings.append(
                    f"[{level}] il warning canonico {warning.get('code')!r} "
                    f"non e' riportato nella sezione dei caveat "
                    f"[{CODE_INCOMPLETE}]")
    # Caso 6 — riconciliazioni: OGNI `REC-*` compare anche quando PASSA.
    for level, case in cases.items():
        for rec_id in sorted((case["document"].get("financial_plan")
                              or {}).get("reconciliations") or {}):
            if rec_id not in case["text"]:
                findings.append(
                    f"[{level}] la riconciliazione {rec_id} non compare nel "
                    "capitolo: un controllo che non compare equivale a un "
                    f"controllo non eseguito [{CODE_INCOMPLETE}]")
    # Caso 7 — calcolabile ma non investor-ready: stato e ragioni riportati.
    for level, case in cases.items():
        readiness = (((case["document"].get("financial_plan") or {}).get(
            "validation") or {}).get("investor_readiness") or {})
        if str(readiness.get("status")) not in case["text"]:
            findings.append(
                f"[{level}] `investor_readiness.status` "
                f"{readiness.get('status')!r} non e' riportato nella sezione "
                f"di prontezza [{CODE_INCOMPLETE}]")
        for reason in readiness.get("blocking_reasons") or []:
            if str(reason.get("code")) not in case["text"]:
                findings.append(
                    f"[{level}] la ragione di blocco {reason.get('code')!r} "
                    f"non e' riportata [{CODE_INCOMPLETE}]")
    # RED — con copertura NULLA una sezione «Downside» etichettata, e un KPI
    # NOT_APPLICABLE omesso, devono essere RILEVATI.
    injected = inject_after_heading(
        none_text, "10. Scenari Base, Downside e Upside", "")
    injected = injected.replace(
        "## 11. Copertura finanziaria delle milestone",
        "## 10. Scenario Downside\n\nSerie del Downside.\n\n"
        "## 11. Copertura finanziaria delle milestone", 1)
    detected = [entry["title"] for entry in parse_chapter(injected)["sections"]
                if entry["title"] == "Scenario Downside"]
    if not detected:
        findings.append(
            "una sezione «Scenario Downside» iniettata con copertura NULLA "
            "NON e' rilevata dal lettore del capitolo: il contratto non "
            "discrimina")
    return findings


# --------------------------------------------------------------------------
# Registro dei contratti
# --------------------------------------------------------------------------


CONTRACTS = [
    {"id": "FD-C-11", "name": "T-FIN-CHAPTER-NUMERIC-CONSISTENCY",
     "fn": c11, "fixture": "F-13(c) derivata in-modulo",
     "expected_code": CODE_MISMATCH, "mutation": "MUT-3-33"},
    {"id": "FD-C-16", "name": "T-FIN-CHAPTER-COMPLETENESS", "fn": c16,
     "fixture": "F-12 + variante derivata in-modulo di F-13(a)",
     "expected_code": CODE_INCOMPLETE, "mutation": "MUT-3-38"},
    {"id": "FD-C-17", "name": "T-FIN-CHAPTER-NO-UNTRACED-VALUES",
     "fn": c17, "fixture": "F-13",
     "expected_code": "elemento di traccia mancante, NOMINATO (cinque RED)",
     "mutation": "MUT-3-39"},
    {"id": "FD-C-18", "name": "T-FIN-CHAPTER-STATUS-FIDELITY", "fn": c18,
     "fixture": "F-3, F-12",
     "expected_code": "sezione e termine di promozione, NOMINATI",
     "mutation": "MUT-3-40"},
    {"id": "FD-C-19", "name": "T-FIN-CHAPTER-PARTIAL-COVERAGE", "fn": c19,
     "fixture": "F-1, F-2 (derivata in-modulo), F-3",
     "expected_code": CODE_INCOMPLETE, "mutation": "MUT-3-41"},
]

CONTRACT_IDS = tuple(entry["id"] for entry in CONTRACTS)


# --------------------------------------------------------------------------
# Esecuzione
# --------------------------------------------------------------------------


def run_one(ctx, contract):
    with tempfile.TemporaryDirectory(prefix="fin_chapter_") as base:
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
                reason="; ".join(result["findings"]) or "-"))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(
        prog="test_fin_chapter.py", add_help=True,
        description="Contratti del capitolo financial-plan.md dello "
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

    global M5A
    try:
        M5A = load_m5a_harness(root)
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
          "(renderer {r}: {rs}; token di stile {t}: {ts})".format(
              total=len(results), red=len(red), green=len(results) - len(red),
              r=RENDERER_REL,
              rs="presente" if ctx["renderer"].is_file() else "ASSENTE",
              t=STYLE_TOKENS_REL,
              ts="presente" if ctx["style_tokens_path"].is_file()
              else "ASSENTE"))
    if red:
        return EXIT_RED
    print("PASS: T-FIN-CHAPTER {n} contratti del capitolo financial-plan.md "
          "dello Stage 10".format(n=len(results)))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
