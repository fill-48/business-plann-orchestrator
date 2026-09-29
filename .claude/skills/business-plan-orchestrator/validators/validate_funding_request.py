#!/usr/bin/env python3
"""Validator e PROIEZIONE canonica dello Stage 11 — `11_funding-request`.

Validator DICHIARATO in `config/enforcement-config.json` con `stages: [11]`
e `phases: ["egress","impact"]`, ed elencato in `egress_required`: e' un
validator reale e completo, non uno stub eseguibile.

LA FUNDING REQUEST E' UNA PROIEZIONE, NON UN SECONDO MOTORE
-----------------------------------------------------------
    LEGGE     10_financial-plan/structured-output.json   UNICA sorgente
    PRODUCE   11_funding-request/structured-output.json  CANONICO
              11_funding-request/handoff.md              CANONICO
              11_funding-request/funding-request.md       DERIVATO

Nessun ricalcolo silenzioso. Nessuna cifra manuale non supportata. Nessun
fallback nascosto.

PERCHE' PROIEZIONE, RENDERER E PUBLISHER VIVONO QUI
----------------------------------------------------
Questo modulo contiene, oltre ai controlli, la logica deterministica di
proiezione, quella di renderer e quella di pubblicazione atomica a due
livelli. Le tre convivono col validator a queste condizioni:

  - l'invocazione dal Transaction Manager resta di SOLA LETTURA: `--build`
    non e' mai passato da `run_egress_validators` ne' da
    `run_impact_validators`, e nessuna pubblicazione implicita avviene sul
    percorso di validazione;
  - egress resta compatibile con `--project --candidate --stage --phase egress`
    e impact con `--project --stage --phase impact`, SENZA alcun payload
    privato obbligatorio;
  - il Transaction Manager non contiene alcuna logica specifica di questo
    stage: lo invoca come ogni altro validator.

DIVIETO DI RICALCOLO, IN FORMA INVERTITA E NON VACUA
-----------------------------------------------------
Lo Stage 10 vieta OGNI aritmetica nel proprio costruttore canonico, che e'
una copia pura. Qui l'aritmetica esiste — le riconciliazioni la ESIGONO — ma
e' confinata a un ELENCO CHIUSO di funzioni di DERIVAZIONE, dichiarato in
`DERIVATION_FUNCTIONS`. Ogni altra funzione del modulo, e il livello di
modulo stesso, restano soggetti al divieto: una funzione «di aiuto» creata
fuori dall'elenco per aggirarlo sarebbe RILEVATA. La non-vacuita' del
rilevatore e' provata da un'AUTO-SONDA su sorgente sintetico che CONTIENE le
violazioni.

Il fronte COMPORTAMENTALE e' distinto e non sostituibile dal fronte statico:
ogni valore emesso che non sia dichiarato come DERIVAZIONE deve coincidere,
alla lettera, col valore che il proprio `canonical_path` porta nel canonico
dello Stage 10. E' cio' che rende la regola «la funding request e' una
proiezione» (`fr_non_canonical_arithmetic`) un contratto verificato e non una
proprieta' «per costruzione».

Exit code: 0 valido | 1 documento invalido o rifiuto di costruzione |
2 errore d'uso | 3 stato canonico corrotto.
"""
import argparse
import ast
import collections
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
from decimal import Decimal, InvalidOperation
from html.entities import html5 as HTML_ENTITIES
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _framework as fw  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT.joinpath("output")))

VALIDATOR_NAME = "validate_funding_request"
STAGE10 = "10_financial-plan"
STAGE11 = "11_funding-request"
STAGE9 = "09_roadmap-and-milestones"
SUPPORTED_PHASES = ("egress", "impact")

SCHEMA_VERSION = "1.0.0"
CANONICAL_NAME = "structured-output.json"
HANDOFF_NAME = "handoff.md"
REQUEST_NAME = "funding-request.md"
CHAPTER_NAME = "financial-plan.md"
WORKBOOK_NAME = "financial-model.xlsx"
WORKING_DIR = ".working"

SCHEMA_PATH = SKILL_ROOT.joinpath("schemas", "funding-request.schema.json")
PROFILE_REL = "shared/startup-profile.json"
ASSUMPTIONS_REL = "shared/assumptions-register.json"
EVIDENCE_REL = "shared/evidence-register.json"
SOURCE_REGISTER_REL = "shared/source-register.json"

#: Tassonomia CHIUSA dei codici di rilievo di questo stage: nessun altro
#: codice e' coniato. `derived_artifact_numeric_mismatch` e' il codice
#: condiviso con gli altri stage per i derivati, riusato VERBATIM.
CODE_NON_CANONICAL = "fr_non_canonical_arithmetic"
CODE_INPUT_INCOMPLETE = "fr_input_incomplete"
CODE_POLICY_UNDECLARED = "fr_policy_undeclared"
CODE_CAPITAL_RECON = "fr_capital_reconciliation_failed"
CODE_ALLOCATION_SUM = "fr_allocation_sum_mismatch"
CODE_PERCENTAGE_SUM = "fr_percentage_sum_mismatch"
CODE_CATEGORY = "fr_category_not_traceable"
CODE_HORIZON = "fr_horizon_mismatch"
CODE_RUNWAY_BEFORE = "fr_runway_before_mismatch"
CODE_RUNWAY_AFTER = "fr_runway_after_mismatch"
CODE_MILESTONE_COST = "fr_milestone_not_costed"
CODE_MILESTONE_ROADMAP = "fr_milestone_not_in_roadmap"
CODE_TRANCHE = "fr_tranche_unsupported"
CODE_SCENARIO_ID = "fr_scenario_id_mismatch"
CODE_SCENARIO_FABRICATED = "fr_scenario_fabricated"
CODE_RESIDUAL_GAP = "fr_residual_gap_hidden"
CODE_INVENTED_TERMS = "fr_invented_terms"
CODE_DECISION_NEEDED = "fr_decision_needed_missing"
CODE_ASSUMPTION_PROMOTED = "fr_assumption_promoted"
CODE_FALSE_PRECISION = "fr_false_precision"
CODE_PROVENANCE = "fr_provenance_missing"
CODE_UNRESOLVED_ITEMS = "fr_unresolved_items_suppressed"
CODE_NARRATIVE = "fr_narrative_untraced_value"
CODE_NONDETERMINISTIC = "fr_nondeterministic"
CODE_PARTIAL_OUTPUT = "fr_partial_output"
CODE_DERIVED_MISMATCH = "derived_artifact_numeric_mismatch"
CODE_SCHEMA = "fr_schema_invalid"

#: I SETTE termini che lo Stage 11 non INVENTA. Lo schema e' chiuso e li
#: respinge STRUTTURALMENTE; questo modulo li respinge anche per CONTRATTO,
#: perche' il solo fronte strutturale chiuderebbe il requisito «per
#: costruzione dello schema» e non «per contratto» (`fr_invented_terms`).
INVENTABLE_TERMS = ("funding_ask", "instrument", "valuation", "round_size",
                    "ownership", "dilution", "terms")

SCENARIO_IDS = ("base", "downside", "upside")

#: Base del capitale richiesto: PRIMARIA `funding_gap_to_buffer`, FALLBACK
#: `funding_gap_to_zero`. I DUE path canonici del fabbisogno, e nessun terzo.
NEED_PRIMARY = ("financial_plan.results.modules.funding_gap.metrics."
                "funding_gap_to_buffer")
NEED_FALLBACK = ("financial_plan.results.modules.funding_gap.metrics."
                 "funding_gap_to_zero")
NOT_APPLICABLE = "NOT_APPLICABLE"

#: Forma canonica degli id (`EVD-001`, `SRC-1000`: esattamente tre cifre,
#: oppure quattro o piu' senza zero iniziale) e forma LASCA. La seconda
#: esiste per INTERCETTARE gli alias non canonici invece di ignorarli,
#: esattamente come `LOOSE_ANY_ASS_RE` del framework.
CANONICAL_NUM = r"(?:[0-9]{3}|[1-9][0-9]{3,})"
EVD_RE = re.compile(rf"^EVD-{CANONICAL_NUM}$")
SRC_RE = re.compile(rf"^SRC-{CANONICAL_NUM}$")
LOOSE_EVD_RE = re.compile(r"^EVD-[0-9]+$")
LOOSE_SRC_RE = re.compile(r"^SRC-[0-9]+$")

#: I DUE registri condivisi di evidenze e fonti, con la forma canonica e la
#: forma lasca di ciascuno. Un id che non e' canonico non SPARISCE prima del
#: controllo: e' RICONOSCIUTO — alias se la forma lasca lo cattura, forma
#: libera altrimenti — e RESPINTO con codice attribuito.
EVIDENCE_REGISTERS = (
    ("evidence_refs", EVIDENCE_REL, EVD_RE, LOOSE_EVD_RE),
    ("source_refs", SOURCE_REGISTER_REL, SRC_RE, LOOSE_SRC_RE),
)

#: I termini finanziari che questo stage NON produce e che restano
#: DECISIONI APERTE dichiarate, mai valori (`fr_decision_needed_missing`). La
#: corrispondenza coi sette `INVENTABLE_TERMS` e' chiusa: `funding_ask` e'
#: portato da `requested_capital` e non e' un termine ignoto; `ownership` e
#: `dilution` sono la stessa decisione.
TERM_DECISIONS = (
    ("FR-TERM-INSTRUMENT", ("instrument",),
     "lo STRUMENTO del finanziamento (equity, strumento convertibile, "
     "prestito, contributo) NON e' prodotto da questo stage ne' desumibile dal "
     "canonico del piano finanziario. Quale strumento si propone"),
    ("FR-TERM-VALUATION", ("valuation",),
     "la VALUTAZIONE pre-money / post-money NON e' prodotta da questo stage "
     "e NON e' stimata. Se lo strumento scelto la richiede, qual e' e su quale "
     "base e' documentata"),
    ("FR-TERM-DILUTION", ("ownership", "dilution"),
     "la QUOTA ceduta e la DILUIZIONE dei soci NON sono prodotte da questo "
     "stage e NON sono stimate. Se lo strumento scelto le comporta, quali "
     "sono"),
    ("FR-TERM-ROUND-SIZE", ("round_size",),
     "la DIMENSIONE complessiva del round o dell'operazione NON e' prodotta "
     "da questo stage: il capitale richiesto e' il fabbisogno modellato, non "
     "la dimensione del round. Quale dimensione si intende"),
    ("FR-TERM-CONDITIONS", ("terms",),
     "le CONDIZIONI dell'operazione (term sheet, tasso e durata, garanzie, "
     "cofinanziamento) NON sono prodotte da questo stage. Quali condizioni "
     "si propongono"),
)
TERM_DECISION_CODES = tuple(code for code, _, _ in TERM_DECISIONS)

#: Il collegamento fra capitale e milestone che il canonico NON porta e' una
#: decisione DICHIARATA, mai un vuoto muto.
MILESTONE_DECISION = "FR-MILESTONE-FINANCING"

#: Quando scatta il fallback a `funding_gap_to_zero` il documento DICHIARA
#: che la richiesta e' costruita a cassa zero.
FALLBACK_DISCLOSURE = "a cassa zero"

#: Politica di capitalizzazione DICHIARATA, nominata nel documento stesso
#: (`policy_ref`) col proprio identificatore di prodotto `FR-CAPITAL-POLICY`:
#: base primaria `funding_gap_to_buffer` con fallback dichiarato a
#: `funding_gap_to_zero`; buffer gia' incluso nella base; nessuna
#: contingency; nessun arrotondamento. Non e' una scelta lasciata
#: all'implementazione. L'identificatore e' risolvibile (`resolvable_ids`):
#: la prosa puo' citarlo.
POLICY_REF = ("FR-CAPITAL-POLICY: base primaria funding_gap_to_buffer con "
              "fallback dichiarato a funding_gap_to_zero; buffer gia' "
              "incluso nella base; contingency ASSENTE; arrotondamento "
              "NESSUNO")

#: Regola di ALLOCAZIONE, dichiarata: il peso di una categoria eleggibile e'
#: il costo canonico che le righe di quella categoria portano nei moduli.
#: Nessuna allocazione e' inventata e nessun peso e' scelto a mano.
ALLOCATION_RULE = ("peso della categoria = somma delle righe di costo "
                   "canoniche con quella categoria, su tutti i moduli e tutti "
                   "i periodi (results.modules[*].lines[*])")

TOLERANCE_EUR = "0.01"
#: L'intervallo di esponenti in cui un importo e' un importo:
#: ben oltre ogni grandezza finanziaria, ben dentro il contesto `Decimal`.
MAX_EXPONENT = 9999
MIN_EXPONENT = -9999
TOLERANCE_RATIO = "1e-6"
TOLERANCE_COUNT = "0"

#: Variabile di ambiente del PUNTO DI FALLIMENTO INIETTATO, nello stesso
#: idioma del Transaction Manager (`BPO_TX_TEST_CRASH`). Serve ai test del
#: publisher atomico (`fr_partial_output`) per provare l'atomicita' con un
#: fallimento REALE.
FAIL_ENV = "BPO_FR_TEST_FAIL"
FAIL_POINTS = ("staging", "after_first_publish")

# --------------------------------------------------------------------------
# DIVIETO DI RICALCOLO — rilevatore statico INVERTITO e sua AUTO-SONDA
# --------------------------------------------------------------------------

FORBIDDEN_BINOPS = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
    ast.FloorDiv: "//", ast.Mod: "%", ast.Pow: "**", ast.MatMult: "@",
}
FORBIDDEN_CALLS = ("sum", "round", "abs", "pow", "divmod", "Decimal", "float",
                   "complex", "int")
FORBIDDEN_IMPORTS = ("validate_financial_engine", "formula_dsl")

#: ELENCO CHIUSO delle funzioni di DERIVAZIONE: le UNICHE in cui l'aritmetica
#: e' ammessa, e ciascuna opera SOLO su valori letti da path canonici
#: DICHIARATI. Ogni altra funzione del modulo — e il livello di modulo — resta
#: soggetta al divieto. Aggiungere qui una funzione e' un atto DICHIARATO e
#: visibile, non un aggiramento silenzioso.
DERIVATION_FUNCTIONS = (
    "as_decimal",
    "to_index",
    "amounts_within",
    "sum_amounts",
    "derive_allocation",
    "derive_capital_reconciliation",
    "derive_runway_after",
    "derive_residual_gap",
    "derive_unvalidated_count",
    "derive_period_end_date",
    "derive_line_weights",
    "recompute_check",
)

#: SORGENTE SINTETICO dell'AUTO-SONDA: CONTIENE le violazioni, e il rilevatore
#: DEVE rilevarle. E' cio' che rende la scansione NON VACUA PER COSTRUZIONE,
#: come in `validate_financial_output`. Non e' eseguito.
AST_SELF_PROBE_SOURCE = '''
import formula_dsl


def leak_projection(revenue_series, cogs_series):
    """Somma due serie di dominio in una funzione NON dichiarata come
    derivazione: e' il ricalcolo che il divieto intercetta."""
    return revenue_series["0"] + cogs_series["0"]


def leak_helper(series):
    total = 0
    for value in series.values():
        total += value
    return sum(series.values())
'''


def scan_forbidden_recomputation(source, label="<source>",
                                 allowed=DERIVATION_FUNCTIONS):
    """Scansione statica del divieto di ricalcolo, in forma INVERTITA.

    Tutto e' vietato tranne il corpo delle funzioni NOMINATE in `allowed`.
    Restituisce l'elenco dei rilievi, ciascuno con FILE e RIGA. Un elenco
    vuoto significa scansione PULITA; la sua non-vacuita' e' provata
    separatamente dall'AUTO-SONDA.
    """
    findings = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"{label}:{exc.lineno}: sorgente non parsabile: {exc.msg}"]
    skipped = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                node.name in allowed:
            for inner in ast.walk(node):
                skipped.add(id(inner))
    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        if isinstance(node, ast.BinOp):
            symbol = FORBIDDEN_BINOPS.get(type(node.op))
            if symbol:
                findings.append(
                    f"{label}:{node.lineno}: operatore aritmetico {symbol!r} "
                    "fuori dall'elenco chiuso delle funzioni di derivazione")
        elif isinstance(node, ast.AugAssign):
            symbol = FORBIDDEN_BINOPS.get(type(node.op))
            if symbol:
                findings.append(
                    f"{label}:{node.lineno}: assegnamento aritmetico "
                    f"{symbol!r}= fuori dall'elenco chiuso: e' un accumulatore "
                    "di dominio")
        elif isinstance(node, ast.UnaryOp) and isinstance(
                node.op, (ast.USub, ast.UAdd)):
            if not isinstance(node.operand, ast.Constant):
                findings.append(
                    f"{label}:{node.lineno}: segno unario su un'espressione "
                    "non costante fuori dall'elenco chiuso")
        elif isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in FORBIDDEN_CALLS:
                findings.append(
                    f"{label}:{node.lineno}: chiamata {name!r} di aggregazione "
                    "o conversione numerica fuori dall'elenco chiuso")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IMPORTS:
                    findings.append(
                        f"{label}:{node.lineno}: import VIETATO {alias.name!r}: "
                        "la funding request non riesegue il motore")
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module in FORBIDDEN_IMPORTS:
                findings.append(
                    f"{label}:{node.lineno}: import VIETATO da {module!r}")
    return findings


def self_probe_findings():
    """AUTO-SONDA: il rilevatore sul sorgente sintetico che CONTIENE la
    violazione. Un elenco vuoto significa rilevatore VACUO."""
    return scan_forbidden_recomputation(AST_SELF_PROBE_SOURCE,
                                        label="<auto-sonda AST>",
                                        allowed=())


# --------------------------------------------------------------------------
# Funzioni di DERIVAZIONE — l'ELENCO CHIUSO in cui l'aritmetica e' ammessa
# --------------------------------------------------------------------------


def as_decimal(value):
    """Un importo canonico arriva come NUMERO o come STRINGA (`$defs.amount`):
    la forma stringa preserva la precisione Decimal, e assumere `float` la
    romperebbe. `NOT_APPLICABLE` non e' un numero e resta `None`.

    Nemmeno `NaN`, `sNaN` o `Infinity` sono importi: sono
    `Decimal` validi ma non FINITI, e un confronto con essi fallirebbe con
    un'eccezione invece che con un rifiuto attribuito. Ne' lo e' un valore
    con un esponente fuori da `MIN_EXPONENT`...`MAX_EXPONENT`, su cui
    l'aritmetica del contesto andrebbe in overflow. Restano `None`."""
    if value is None or value == NOT_APPLICABLE:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not number.is_finite():
        return None
    if number.adjusted() > MAX_EXPONENT or number.adjusted() < MIN_EXPONENT:
        return None
    return number


def to_index(key):
    """Indice intero di un passo di path. Vive nell'elenco chiuso perche' la
    conversione numerica e' una delle chiamate che il divieto intercetta, e
    nasconderla in una funzione non dichiarata sarebbe un aggiramento."""
    return int(key)


def amounts_within(left, right, tolerance):
    """`True` se due importi coincidono entro la tolleranza DICHIARATA."""
    if left is None or right is None:
        return False
    return abs(left - right) <= Decimal(tolerance)


def sum_amounts(values):
    total = Decimal("0")
    for value in values:
        if value is not None:
            total = total + value
    return total


def derive_line_weights(modules):
    """Peso canonico per categoria di costo: somma delle righe con quella
    categoria, su tutti i moduli e tutti i periodi. E' la regola DICHIARATA in
    `ALLOCATION_RULE` e opera SOLO su valori letti dal canonico."""
    weights = {}
    paths = {}
    for module_id in sorted(modules):
        module = modules.get(module_id) or {}
        lines = module.get("lines") or []
        for position, line in enumerate(lines):
            category = line.get("category")
            if not category:
                continue
            series = line.get("series") or {}
            for key in sorted(series, key=lambda item: int(item)):
                value = as_decimal(series.get(key))
                if value is None:
                    continue
                weights[category] = weights.get(category, Decimal("0")) + value
            paths.setdefault(category, []).append(
                f"financial_plan.results.modules.{module_id}.lines[{position}]")
    return weights, paths


def derive_allocation(requested, categories, weights):
    """Ripartizione ESATTA del capitale richiesto sulle categorie eleggibili.

    L'ULTIMA categoria porta il residuo esatto, cosi' che la somma degli
    importi coincida col capitale richiesto SENZA residuo e la somma delle
    percentuali valga esattamente 100: non e' un arrotondamento, e' una
    ripartizione che chiude. Con UNA sola categoria eleggibile non esiste
    alcuna scelta di allocazione da compiere.
    """
    total_weight = Decimal("0")
    for category in categories:
        total_weight = total_weight + weights.get(category, Decimal("0"))
    amounts = []
    percentages = []
    allocated = Decimal("0")
    allocated_pct = Decimal("0")
    hundred = Decimal("100")
    for index, category in enumerate(categories):
        last = index == len(categories) - 1
        if last:
            amount = requested - allocated
            percentage = hundred - allocated_pct
        elif total_weight > Decimal("0"):
            amount = requested * weights.get(category, Decimal("0")) \
                / total_weight
            percentage = amount / requested * hundred \
                if requested != Decimal("0") else Decimal("0")
        else:
            amount = Decimal("0")
            percentage = Decimal("0")
        allocated = allocated + amount
        allocated_pct = allocated_pct + percentage
        amounts.append(amount)
        percentages.append(percentage)
    return amounts, percentages


def derive_capital_reconciliation(base, buffer_state, buffer_amount,
                                  contingency_amount, requested):
    """Scomposizione NOMINATA del capitale richiesto.

    Per la politica dichiarata il buffer e' GIA' INCLUSO nella base
    `funding_gap_to_buffer`: e' ESPOSTO come
    componente e NON e' un addendo. Un `buffer_component` numerico POSITIVO
    sommato alla base sarebbe un doppio conteggio, cioe' un FAIL.
    """
    addends = [{"name": "modeled_need", "amount": str(base), "role": "base"}]
    total = base
    if buffer_state == "included_in_base" and buffer_amount is not None:
        addends.append({"name": "buffer_component",
                        "amount": str(buffer_amount), "role": "exposure"})
    if contingency_amount is not None:
        addends.append({"name": "contingency_component",
                        "amount": str(contingency_amount), "role": "addend"})
        total = total + contingency_amount
    residual = requested - total
    return {"expected": str(total), "actual": str(requested),
            "residual": str(residual), "tolerance": TOLERANCE_EUR,
            "status": "PASS" if abs(residual) <= Decimal(TOLERANCE_EUR)
            else "FAIL", "addends": addends}


def derive_runway_after(series, horizon, injected, limit):
    """Runway POST-FINANZIAMENTO ricostruito dal flusso di cassa canonico,
    periodo per periodo, con la STESSA regola del motore dello Stage 10: il
    primo indice in cui il saldo scende sotto la soglia, altrimenti
    l'orizzonte."""
    for index in range(horizon):
        value = as_decimal(series.get(str(index)))
        if value is None:
            return None
        if value + injected < limit:
            return index
    return horizon


def derive_residual_gap(series, horizon, injected, limit):
    """Gap residuo dopo il finanziamento: `max(0, soglia - minimo di cassa)`,
    la STESSA forma di `funding_gap_measure` del motore dello Stage 10."""
    worst = None
    for index in range(horizon):
        value = as_decimal(series.get(str(index)))
        if value is None:
            return None
        financed = value + injected
        if worst is None or financed < worst:
            worst = financed
    if worst is None:
        return None
    gap = limit - worst
    return gap if gap > Decimal("0") else Decimal("0")


def derive_unvalidated_count(register, refs):
    count = 0
    for entry in register:
        if entry.get("id") in refs and \
                entry.get("validation_status") != "validated":
            count = count + 1
    return count


def derive_period_end_date(periods, period_index):
    """PROIEZIONE DICHIARATA di una data di milestone da `period_index` e
    `results.calendar`: nessun path canonico e' inventato per ospitarla."""
    if period_index is None:
        return None
    for entry in periods:
        if entry.get("index") == period_index:
            return entry.get("end_date")
    return None


def recompute_check(expected, actual, tolerance):
    """Confronto NUMERICO fra un valore atteso e uno osservato, con il residuo
    riportato: e' la forma che ogni riconciliazione di questo modulo usa."""
    left = as_decimal(expected)
    right = as_decimal(actual)
    if left is None or right is None:
        return None, str(expected), str(actual)
    return abs(left - right) <= Decimal(tolerance), str(left), str(right)


# --------------------------------------------------------------------------
# Accessori di sola lettura — nessuna aritmetica
# --------------------------------------------------------------------------


PATH_STEP_RE = re.compile(r"^([^\[\]]*)((?:\[[^\[\]]+\])*)$")


def resolve_path(document, path):
    """Risolve un `canonical_path` DICHIARATO. Ritorna `(trovato, valore)`."""
    node = document
    for step in str(path).split("."):
        match = PATH_STEP_RE.match(step)
        if not match:
            return False, None
        name, indexes = match.group(1), match.group(2)
        if name:
            if not isinstance(node, dict) or name not in node:
                return False, None
            node = node[name]
        for raw in re.findall(r"\[([^\[\]]+)\]", indexes):
            key = raw.strip("'\"")
            if isinstance(node, list):
                try:
                    node = node[to_index(key)]
                except (ValueError, IndexError):
                    return False, None
            elif isinstance(node, dict):
                if key not in node:
                    return False, None
                node = node[key]
            else:
                return False, None
    return True, node


def canonical_json(document):
    """Forma canonica DETERMINISTICA — la STESSA usata dallo Stage 10:
    chiavi ordinate, indentazione 2, `ensure_ascii`, una newline finale."""
    return "".join([json.dumps(document, indent=2, ensure_ascii=True,
                               sort_keys=True), "\n"])


def load_json(path, label):
    target = Path(path)
    if not target.is_file():
        raise fw.CanonicalStateError(f"{label} assente: {target}")
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise fw.CanonicalStateError(f"{label} corrotto: {target}: {exc}")


def optional_json(path, default):
    target = Path(path)
    if not target.is_file():
        return default
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def load_register(project, rel):
    """Un registro condiviso, letto FAIL-CLOSED: ASSENTE vale
    elenco vuoto; PRESENTE ma corrotto, o non un elenco, e' stato canonico
    corrotto (exit 3) — mai un registro vuoto per default, che farebbe
    sparire le sue voci senza traccia."""
    target = Path(project).joinpath(rel)
    if not target.is_file():
        return []
    try:
        entries = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise fw.CanonicalStateError(f"registro {rel} corrotto: {exc}")
    if not isinstance(entries, list):
        raise fw.CanonicalStateError(
            f"registro {rel} non e' un elenco di voci: "
            f"{type(entries).__name__}")
    return entries


def register_ids(entries, rel, canonical_re, loose_re):
    """Gli id in forma CANONICA di un registro e, per OGNI voce che non lo
    e', un rilievo `(ref, messaggio)` ATTRIBUITO.

    Nessuna voce e' scartata in silenzio e nessun id e' normalizzato: un alias
    (`EVD-0021`) e' RICONOSCIUTO dalla forma lasca e respinto come tale; una
    forma libera o un id assente sono respinti come tali; un duplicato viola
    l'unicita' degli id: ciascuno compare al piu' una volta come definizione.
    """
    ids = []
    problems = []
    for position, entry in enumerate(entries):
        ref = entry.get("id") if isinstance(entry, dict) else None
        if isinstance(ref, str) and canonical_re.match(ref):
            if ref in ids:
                problems.append((ref, (
                    f"{rel}: identificatore {ref!r} DUPLICATO: ogni id compare "
                    "al piu' una volta come definizione")))
                continue
            ids.append(ref)
        elif isinstance(ref, str) and loose_re.match(ref):
            problems.append((ref, (
                f"{rel}: identificatore {ref!r} RICONOSCIUTO come alias NON "
                "canonico e RESPINTO: non e' normalizzato, "
                "troncato, riscritto ne' scartato in silenzio")))
        else:
            label = ref if isinstance(ref, str) and ref \
                else f"{rel}[{position}]"
            problems.append((label, (
                f"{rel}: voce {label!r} con identificatore in forma libera o "
                "assente: nessun id fuori dalla forma canonica e' "
                "ammesso, e la voce non e' scartata in silenzio")))
    return ids, problems


def plan_of(document):
    return (document or {}).get("financial_plan") or {}


def modules_of(document):
    return ((plan_of(document).get("results") or {}).get("modules")) or {}


def calendar_of(document):
    return ((plan_of(document).get("results") or {}).get("calendar")) or {}


def scenarios_of(document):
    return ((plan_of(document).get("results") or {}).get("scenarios")) or {}


def canonical_checksum(document):
    metadata = plan_of(document).get("calculation_metadata") or {}
    return str((metadata.get("output_checksums") or {}).get("base") or "")


def deep_items(node, path=""):
    """Ogni coppia `(path, chiave, valore)` del documento, a ogni profondita'."""
    items = []
    if isinstance(node, dict):
        for key in sorted(node):
            here = f"{path}.{key}" if path else str(key)
            items.append((here, str(key), node[key]))
            items.extend(deep_items(node[key], here))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            here = f"{path}[{index}]"
            items.extend(deep_items(value, here))
    return items


# --------------------------------------------------------------------------
# Gate di ingresso — ingresso incompleto respinto (`fr_input_incomplete`)
# --------------------------------------------------------------------------


class BuildRefusal(Exception):
    """Rifiuto DICHIARATO della costruzione: exit 1, con codice attribuito.

    `details`, se presente, e' l'elenco `(ref, messaggio)` dei singoli
    rilievi: ciascuno diventa un errore ATTRIBUITO al proprio riferimento, cosi'
    che ogni alias respinto sia NOMINATO e nessuno sia riassunto in silenzio.
    """

    def __init__(self, code, message, ref=None, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.ref = ref
        self.details = list(details or [])


def stage10_inputs(project, canonical_override=None):
    """I TRE artefatti di ingresso. Un ingresso incompleto e' respinto PRIMA
    di qualunque scrittura: il rifiuto precede ogni I/O di uscita."""
    stage = Path(project).joinpath(STAGE10)
    canonical = Path(canonical_override) if canonical_override \
        else stage.joinpath(CANONICAL_NAME)
    chapter = stage.joinpath(CHAPTER_NAME)
    workbook = stage.joinpath(WORKBOOK_NAME)
    missing = []
    for label, path in (("canonico dello Stage 10", canonical),
                        (f"capitolo {CHAPTER_NAME}", chapter),
                        (f"workbook {WORKBOOK_NAME}", workbook)):
        if not path.is_file():
            missing.append(f"{label} ({path.name}): ASSENTE")
        elif path.stat().st_size == 0:
            missing.append(f"{label} ({path.name}): VUOTO")
    if missing:
        raise BuildRefusal(
            CODE_INPUT_INCOMPLETE,
            "ingresso incompleto: la funding request esige canonico, capitolo "
            f"e workbook presenti e validati; {'; '.join(missing)}")
    try:
        document = json.loads(canonical.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BuildRefusal(
            CODE_INPUT_INCOMPLETE,
            f"canonico dello Stage 10 non validato: JSON non parsabile: {exc}",
            ref=str(canonical))
    if not isinstance(document, dict) or "financial_plan" not in document:
        raise BuildRefusal(
            CODE_INPUT_INCOMPLETE,
            "canonico dello Stage 10 non validato: manca la radice "
            "financial_plan", ref=str(canonical))
    if workbook.read_bytes()[:2] != b"PK":
        raise BuildRefusal(
            CODE_INPUT_INCOMPLETE,
            f"workbook {WORKBOOK_NAME} non validato: non e' un pacchetto OOXML",
            ref=str(workbook))
    if not chapter.read_text(encoding="utf-8").strip():
        raise BuildRefusal(
            CODE_INPUT_INCOMPLETE,
            f"capitolo {CHAPTER_NAME} non validato: contenuto vuoto",
            ref=str(chapter))
    return {"canonical": canonical, "chapter": chapter, "workbook": workbook,
            "document": document}


# --------------------------------------------------------------------------
# PROIEZIONE — il canonico dello Stage 11 dal SOLO canonico dello Stage 10
# --------------------------------------------------------------------------


def select_need(document):
    """Base del fabbisogno: PRIMARIA `funding_gap_to_buffer`, FALLBACK
    `funding_gap_to_zero` SOLO E SOLTANTO su `NOT_APPLICABLE`. Unico ramo,
    unico predicato, nessuna euristica."""
    found, primary = resolve_path(document, NEED_PRIMARY)
    if found and primary != NOT_APPLICABLE:
        return NEED_PRIMARY, primary, "to_buffer"
    found, fallback = resolve_path(document, NEED_FALLBACK)
    if not found:
        raise BuildRefusal(
            CODE_INPUT_INCOMPLETE,
            "il canonico non porta alcuna delle DUE misure di fabbisogno "
            f"della politica di capitalizzazione: {NEED_PRIMARY} e "
            f"{NEED_FALLBACK} assenti")
    return NEED_FALLBACK, fallback, "to_zero"


def project_buffer(document, measure):
    """Componente di buffer: TRE stati chiusi e nessun quarto
    (`NOT_APPLICABLE`, `included_in_base`, `absent`). Il buffer e' gia'
    incluso nella base: e' esposto, mai sommato."""
    buffer_module = modules_of(document).get("cash_buffer") or {}
    threshold_path = ("financial_plan.results.modules.cash_buffer.metrics."
                      "threshold")
    if buffer_module.get("status") == NOT_APPLICABLE:
        return {"state": NOT_APPLICABLE,
                "reason": str(buffer_module.get("not_applicable_reason") or
                              "cash_buffer NOT_APPLICABLE nel canonico")}, None
    found, threshold = resolve_path(document, threshold_path)
    if measure == "to_buffer" and found:
        return {"state": "included_in_base", "amount": threshold,
                "source_path": threshold_path,
                "reason": "il buffer e' GIA' INCLUSO nella base "
                          "funding_gap_to_buffer: e' ESPOSTO, non sommato"}, \
            as_decimal(threshold)
    return {"state": "absent",
            "reason": "la base e' funding_gap_to_zero benche' la soglia "
                      "esista: il buffer resta fuori dalla base e non e' "
                      "sommato come componente addizionale"}, None


def project_reader_context(project):
    """Contesto del lettore: `funding_type`, `primary_reader` e
    `development_stage` si LEGGONO dal profilo, mai inferiti."""
    path = Path(project).joinpath(PROFILE_REL)
    decisions = []
    if not path.is_file():
        decisions.append({
            "code": "FR-PROFILE-UNAVAILABLE",
            "question": f"{PROFILE_REL} e' assente: funding_type, "
                        "primary_reader e development_stage non sono "
                        "disponibili e NON sono inferiti. Quali sono?",
            "blocking": True})
        return {"profile_ref": None, "funding_type": None,
                "primary_reader": None, "development_stage": None}, decisions
    profile = optional_json(path, {})
    return {"profile_ref": PROFILE_REL,
            "funding_type": profile.get("funding_type"),
            "primary_reader": profile.get("primary_reader"),
            "development_stage": profile.get("development_stage")}, decisions


def project_use_of_proceeds(document, requested):
    """Impiego dei fondi: ogni categoria risale a un candidato del
    canonico; importo e percentuale insieme, ridondanza VOLUTA
    (`fr_allocation_sum_mismatch`, `fr_percentage_sum_mismatch`,
    `fr_category_not_traceable`)."""
    funding_gap = modules_of(document).get("funding_gap") or {}
    candidates = funding_gap.get("use_of_proceeds_candidates") or []
    if not candidates:
        raise BuildRefusal(
            CODE_INPUT_INCOMPLETE,
            "il canonico non dichiara alcuna categoria eleggibile in "
            "funding_gap.use_of_proceeds_candidates: l'allocazione non ha "
            "portatore e non si inventa")
    ordered = sorted(candidates, key=lambda item: str(item.get("category_id")))
    weights, weight_paths = derive_line_weights(modules_of(document))
    names = [str(entry.get("category_id")) for entry in ordered]
    amounts, percentages = derive_allocation(requested, names, weights)
    entries = []
    for index, candidate in enumerate(ordered):
        entries.append({
            "category_id": names[index],
            "label": str(candidate.get("label") or names[index]),
            "amount": str(amounts[index]),
            "percentage": str(percentages[index]),
            "driver_refs": list(candidate.get("driver_refs") or []),
            "candidate_ref": names[index],
        })
    return entries, weight_paths


def project_milestones(document, project):
    """Ogni milestone finanziata mappa a un `MIL-*`
    DATATO e COSTATO; `out_of_horizon_milestones` e' LETTO e DICHIARATO."""
    coverage = modules_of(document).get("milestone_coverage") or {}
    calendar = calendar_of(document)
    out_of_horizon = list(calendar.get("out_of_horizon_milestones") or [])
    periods = calendar.get("periods") or []
    summary_path = ("financial_plan.results.modules.milestone_coverage."
                    "unmapped_residual")
    if coverage.get("status") == NOT_APPLICABLE:
        # Il modulo e' DICHIARATO non applicabile dal canonico: il residuo non
        # e' zero, e' NON APPLICABILE, e lo stato e' PROPAGATO tale e quale.
        summary = {
            "unmapped_residual": NOT_APPLICABLE,
            "out_of_horizon_count": len(out_of_horizon),
            "source_path": summary_path,
        }
        return [], summary
    entries = []
    seen = set()
    for item in coverage.get("milestones") or []:
        ref = item.get("milestone_ref")
        seen.add(ref)
        beyond = ref in out_of_horizon
        cost_refs = list(item.get("cost_driver_refs") or [])
        entries.append({
            "milestone_ref": ref,
            "target_date": None if beyond else derive_period_end_date(
                periods, item.get("period_index")),
            "cost_ref": cost_refs,
            "amount": None,
            "coverage_status": str(item.get("coverage_status") or "unfunded"),
            "financed_by": "requested_capital"
            if item.get("coverage_status") == "funded" else "not_financed",
            "out_of_horizon": beyond,
        })
    for ref in out_of_horizon:
        if ref in seen:
            continue
        entries.append({
            "milestone_ref": ref, "target_date": None, "cost_ref": [],
            "amount": None, "coverage_status": "unfunded",
            "financed_by": "not_financed", "out_of_horizon": True,
        })
    entries = sorted(entries, key=lambda item: str(item["milestone_ref"]))
    residual = coverage.get("unmapped_residual")
    summary = {
        "unmapped_residual": NOT_APPLICABLE if residual is None
        else str(residual),
        "out_of_horizon_count": len(out_of_horizon),
        "source_path": summary_path,
    }
    del project
    return entries, summary


def project_scenarios(document):
    """Scenari: gli id coincidono con l'enum canonico; con
    copertura `none` gli scenari avversi restano `NOT_APPLICABLE` con
    motivazione NOMINATA, NON prodotti e NON etichettati."""
    scenarios = scenarios_of(document)
    coverage = scenarios.get("coverage") or {}
    level = str(coverage.get("level") or "none")
    out = {"coverage_level": level}
    for name in SCENARIO_IDS:
        entry = scenarios.get(name) or {}
        projected = {"scenario": name,
                     "status": str(entry.get("status") or NOT_APPLICABLE),
                     "requested_capital_delta": None,
                     "source_path": f"financial_plan.results.scenarios.{name}"}
        reason = entry.get("not_applicable_reason")
        if reason:
            projected["not_applicable_reason"] = str(reason)
        out[name] = projected
    return out, coverage


def project_governance(document):
    validation = plan_of(document).get("validation") or {}
    readiness = (validation.get("investor_readiness") or {})
    result = str(validation.get("result") or "FAIL")
    propagated = str(validation.get("propagated_status") or "unresolved")
    ready = str(readiness.get("status") or "not_ready")
    if result == "FAIL":
        state = "not_approvable"
    elif result == "PASS" and propagated == "confirmed" and ready == "ready":
        state = "approved"
    else:
        state = "approved_with_conditions"
    return {"source_validation_result": result,
            "source_propagated_status": propagated,
            "source_investor_readiness": ready,
            "propagated_state": state}


def project_unresolved(document):
    """Voci di validazione irrisolte dello Stage 10: copia FEDELE, mai un
    filtro (`fr_unresolved_items_suppressed`)."""
    validation = plan_of(document).get("validation") or {}
    items = []
    for severity, key in (("ERROR", "errors"), ("WARNING", "warnings")):
        for entry in validation.get(key) or []:
            item = {"severity": severity,
                    "code": str(entry.get("code") or "unknown"),
                    "message": str(entry.get("message") or "")}
            refs = entry.get("affected_refs")
            if refs:
                item["affected_refs"] = list(refs)
            items.append(item)
    return items


def project_evidence_index(project, strict=True):
    """Indice delle evidenze: solo id in forma canonica, risolti contro i
    registri. Dove l'evidenza non esiste lo stato e' DICHIARATO `missing`.

    Un id NON canonico in un registro non e' filtrato via prima del
    controllo: la costruzione e' RESPINTA con un errore attribuito per
    ciascuno, e un registro di soli alias NON diventa `availability: missing`.
    Con `strict` falso — la sola proiezione AUTORITATIVA del validator, che
    non pubblica nulla — il rifiuto e' lasciato a `check_evidence_registers`,
    che lo attribuisce voce per voce.
    """
    index = {}
    problems = []
    for key, rel, canonical_re, loose_re in EVIDENCE_REGISTERS:
        ids, found = register_ids(load_register(project, rel), rel,
                                  canonical_re, loose_re)
        index[key] = sorted(ids)
        problems.extend(found)
    if problems and strict:
        raise BuildRefusal(
            CODE_PROVENANCE,
            "registri di evidenza o di fonte con identificatori NON canonici: "
            f"{[ref for ref, _ in problems]}", details=problems)
    index["availability"] = "available" \
        if index["evidence_refs"] or index["source_refs"] else "missing"
    return index


def provenance_entry(field, path, unit, currency=None, scenario=None,
                     period=None, checksum="", derivation=None,
                     derivation_paths=None):
    entry = {"field": field, "canonical_path": path, "scenario": scenario,
             "period": period, "unit": unit, "currency": currency,
             "canonical_source_checksum": checksum}
    if derivation:
        entry["derivation"] = derivation
        entry["derivation_paths"] = list(derivation_paths or [])
    return entry


def build_document(document, project, strict=True):
    """La PROIEZIONE completa. Ogni valore emesso e' letto da un path canonico
    DICHIARATO oppure e' una DERIVAZIONE nominata con i propri path.

    La STESSA funzione e' la proiezione
    AUTORITATIVA del validator (`authoritative_request`): cio' che il
    documento sotto validazione deve essere, ricostruito dal solo canonico
    dello Stage 10 e dai registri del progetto. Con `strict` falso i
    registri con identificatori non canonici non fermano la proiezione: il
    loro rifiuto resta ai controlli che li attribuiscono voce per voce."""
    checksum = canonical_checksum(document)
    calendar = calendar_of(document)
    modules = modules_of(document)
    currency = "EUR"

    need_path, need_value, measure = select_need(document)
    buffer_component, buffer_amount = project_buffer(document, measure)
    need_decimal = as_decimal(need_value)
    if need_decimal is None:
        raise BuildRefusal(
            CODE_INPUT_INCOMPLETE,
            f"la misura di fabbisogno {need_path} non e' un importo: "
            f"{need_value!r}")
    contingency = {"state": "absent",
                   "reason": "nessuna contingency dichiarata, default "
                             "ASSENTE: la contingency non e' stimata"}
    requested = need_decimal
    reconciliation = derive_capital_reconciliation(
        need_decimal, buffer_component["state"], buffer_amount, None, requested)

    use_entries, weight_paths = project_use_of_proceeds(document, requested)

    runway_metrics = (modules.get("runway") or {}).get("metrics") or {}
    cash_series = (modules.get("cash_flow") or {}).get("series") or {}
    horizon = calendar.get("horizon_periods")
    limit = as_decimal("0")
    if measure == "to_buffer":
        limit = as_decimal(
            ((modules.get("cash_buffer") or {}).get("metrics") or {})
            .get("threshold")) or as_decimal("0")
    after_periods = derive_runway_after(cash_series, horizon, requested, limit)
    residual_gap = derive_residual_gap(cash_series, horizon, requested, limit)
    if after_periods is None or residual_gap is None:
        raise BuildRefusal(
            CODE_INPUT_INCOMPLETE,
            "la serie di cassa canonica non copre l'orizzonte dichiarato: il "
            "runway finanziato non e' ricostruibile e non si stima")

    milestone_entries, milestone_summary = project_milestones(document, project)
    scenario_block, coverage = project_scenarios(document)
    reader_context, decisions = project_reader_context(project)

    condition_ref = coverage.get("proposed_condition_ref")
    if str(coverage.get("level")) == "none":
        decisions.append({
            "code": str(condition_ref or SCENARIO_CONDITION),
            "question": "la copertura di scenario del canonico e' NULLA: la "
                        "richiesta e' formulata sul SOLO scenario BASE e non "
                        "e' validata su scenari avversi. Si intende produrre "
                        "la terna di scenario per i driver richiesti?",
            "blocking": True})
    decisions.append({
        "code": "FR-SCENARIO-CAPITAL-DELTA",
        "question": "nessun portatore canonico espone un fabbisogno SCALARE "
                    "per scenario: requested_capital_delta resta non "
                    "valorizzato e non e' stimato. Si intende introdurne uno?",
        "blocking": False})
    decisions.append({
        "code": "FR-TRANCHE-SCHEDULE",
        "question": "nessun portatore canonico espone uno schedule di "
                    "finanziamento: le tranche restano not_supported. Si "
                    "intende dichiararne uno a monte?",
        "blocking": False})
    # I termini finanziari che questo stage NON possiede restano VISIBILI
    # come decisioni aperte, con il profilo LETTO (mai inferito) nominato
    # nella domanda. Non sono bloccanti: la richiesta
    # resta verificabile senza di essi, e nessuno e' valorizzato.
    funding_type = reader_context.get("funding_type") or "NON DICHIARATO"
    primary_reader = reader_context.get("primary_reader") or "NON DICHIARATO"
    for code, _, question in TERM_DECISIONS:
        decisions.append({
            "code": code,
            "question": f"{question}, per funding_type {funding_type} e "
                        f"lettore {primary_reader}?",
            "blocking": False})
    milestone_status = str((modules.get("milestone_coverage") or {})
                           .get("status") or NOT_APPLICABLE)
    if not milestone_entries:
        # Nessuna milestone e' collegata al capitale: il vuoto e'
        # DICHIARATO, non lasciato muto.
        decisions.append({
            "code": MILESTONE_DECISION,
            "question": "milestone_financing e' VUOTO: il modulo "
                        "milestone_coverage del piano finanziario e' "
                        f"{milestone_status} e nessuna milestone della roadmap "
                        "e' collegata al capitale richiesto; il collegamento "
                        "NON e' stimato. Si intende popolare la copertura "
                        "delle milestone a monte, nel piano finanziario?",
            "blocking": False})

    # Forma canonica degli id e framework (`LOOSE_ANY_ASS_RE`) — un alias nel
    # registro UFFICIALE non e' filtrato via: escluderlo da assumption_refs
    # abbasserebbe in silenzio unvalidated_count, cioe' un'assunzione
    # trattata come fatto.
    register = load_register(project, ASSUMPTIONS_REL)
    assumption_ids, assumption_problems = register_ids(
        register, ASSUMPTIONS_REL, fw.ASS_RE, fw.LOOSE_ANY_ASS_RE)
    if assumption_problems and strict:
        raise BuildRefusal(
            CODE_ASSUMPTION_PROMOTED,
            "registro ufficiale delle assunzioni con identificatori NON "
            f"canonici: {[ref for ref, _ in assumption_problems]}",
            details=assumption_problems)
    assumption_refs = sorted(assumption_ids)
    unvalidated = derive_unvalidated_count(register, set(assumption_refs))

    provenance = [
        provenance_entry("capital_requirement.modeled_need_amount", need_path,
                         currency, currency, "base", None, checksum),
        provenance_entry("requested_capital.amount", need_path, currency,
                         currency, "base", None, checksum),
        provenance_entry(
            "runway.before_financing.runway_to_zero",
            "financial_plan.results.modules.runway.metrics.runway_to_zero",
            "count", None, "base", None, checksum),
        provenance_entry(
            "runway.before_financing.runway_to_buffer",
            "financial_plan.results.modules.runway.metrics.runway_to_buffer",
            "count", None, "base", None, checksum),
        provenance_entry(
            "runway.after_financing.periods",
            "financial_plan.results.modules.cash_flow.series", "count", None,
            "base", None, checksum, "reconciliation",
            ["financial_plan.results.modules.cash_flow.series", need_path]),
        provenance_entry(
            "sufficiency.residual_gap",
            "financial_plan.results.modules.cash_flow.series", currency,
            currency, "base", None, checksum, "reconciliation",
            ["financial_plan.results.modules.cash_flow.series", need_path]),
        provenance_entry(
            "sufficiency.funded_horizon",
            "financial_plan.results.modules.cash_flow.series", "count", None,
            "base", None, checksum, "reconciliation",
            ["financial_plan.results.modules.cash_flow.series", need_path]),
        provenance_entry(
            "horizon.horizon_periods",
            "financial_plan.results.calendar.horizon_periods", "count", None,
            None, None, checksum),
        provenance_entry(
            "dependencies_and_assumptions.unvalidated_count", ASSUMPTIONS_REL,
            "count", None, None, None, checksum, "count", [ASSUMPTIONS_REL]),
    ]
    # Quando `milestone_coverage` e' DICHIARATO non applicabile, il path del
    # residuo non porta alcun valore: la voce e' percio' una PROIEZIONE
    # dichiarata dello stato NOT_APPLICABLE, non la copia di un numero, e lo
    # dichiara invece di fingere una lettura.
    residual_found, _ = resolve_path(document,
                                     milestone_summary["source_path"])
    provenance.append(provenance_entry(
        "milestone_financing_summary.unmapped_residual",
        milestone_summary["source_path"], currency, currency, None, None,
        checksum,
        None if residual_found else "projection",
        [] if residual_found
        else ["financial_plan.results.modules.milestone_coverage.status"]))
    if buffer_component["state"] == "included_in_base":
        provenance.append(provenance_entry(
            "capital_requirement.buffer_component.amount",
            buffer_component["source_path"], currency, currency, "base", None,
            checksum))
    for index, entry in enumerate(use_entries):
        category = entry["category_id"]
        provenance.append(provenance_entry(
            f"use_of_proceeds[{index}].amount",
            "financial_plan.results.modules.funding_gap."
            "use_of_proceeds_candidates", currency, currency, "base", None,
            checksum, "projection", weight_paths.get(category, [])))
        provenance.append(provenance_entry(
            f"use_of_proceeds[{index}].percentage",
            "financial_plan.results.modules.funding_gap."
            "use_of_proceeds_candidates", "ratio", None, "base", None,
            checksum, "projection", weight_paths.get(category, [])))
    for entry in milestone_entries:
        if entry["target_date"] is not None:
            provenance.append(provenance_entry(
                f"milestone_financing[{entry['milestone_ref']}].target_date",
                "financial_plan.results.modules.milestone_coverage.milestones",
                "date", None, None, None, checksum, "projection",
                ["financial_plan.results.modules.milestone_coverage."
                 "milestones", "financial_plan.results.calendar.periods"]))

    request = {
        "source": {
            "stage": STAGE10,
            "canonical_path": f"{STAGE10}/{CANONICAL_NAME}",
            "canonical_source_checksum": checksum,
            "canonical_schema_version": str(document.get("schema_version")),
        },
        "reader_context": reader_context,
        "horizon": {
            "anchor_date": calendar.get("anchor_date"),
            "frequency": calendar.get("frequency"),
            "horizon_periods": horizon,
            "source_path": "financial_plan.results.calendar",
        },
        "capital_requirement": {
            "modeled_need_ref": need_path,
            "modeled_need_amount": str(need_decimal),
            "buffer_component": buffer_component,
            "contingency_component": contingency,
            "timing_granularity": calendar.get("frequency"),
            "policy_ref": POLICY_REF,
            "reconciliation": reconciliation,
        },
        "requested_capital": {
            "amount": str(requested),
            "currency": currency,
            "rounding_applied": "none",
            "policy_ref": POLICY_REF,
        },
        "use_of_proceeds": use_entries,
        "runway": {
            "before_financing": {
                "runway_to_zero": runway_metrics.get("runway_to_zero"),
                "runway_to_buffer": runway_metrics.get("runway_to_buffer"),
            },
            "after_financing": {
                "periods": after_periods,
                "method": "ricostruzione periodo per periodo del flusso di "
                          "cassa canonico con il capitale richiesto iniettato "
                          "al periodo 0, stessa regola del motore "
                          "finanziario dello Stage 10",
                "source_path":
                    "financial_plan.results.modules.cash_flow.series",
                "tolerance": TOLERANCE_COUNT,
            },
            "measure": measure,
            "source_path": "financial_plan.results.modules.runway.metrics",
        },
        "sufficiency": {
            "funded_horizon": after_periods,
            "residual_gap": str(residual_gap),
            "residual_gap_disclosed": True,
            "basis": sufficiency_basis(measure),
        },
        "milestone_financing": milestone_entries,
        "milestone_financing_summary": milestone_summary,
        "tranches": [{
            "tranche_id": "TR-NOT-SUPPORTED",
            "support": "not_supported",
            "reason": "nessun portatore canonico a monte espone uno schedule "
                      "di finanziamento: uno schedule NON si inventa",
        }],
        "investment_requirement": {
            "status": "NOT_SUPPORTED",
            "reason": "capex, depreciation, working_capital, tax e financing "
                      "non sono moduli calcolati dal motore finanziario: "
                      "un requisito di investimento e' DICHIARATO, mai "
                      "stimato",
            "modules": ["capex", "depreciation", "working_capital", "tax",
                        "financing"],
        },
        "scenario_sensitivity": scenario_block,
        "dependencies_and_assumptions": {
            "assumption_refs": assumption_refs,
            "unvalidated_count": unvalidated,
            "decision_needed": sorted(decisions,
                                      key=lambda item: str(item["code"])),
        },
        "unresolved_validation_items": project_unresolved(document),
        "governance": project_governance(document),
        "provenance": sorted(provenance, key=lambda item: str(item["field"])),
        "narrative": {"sections": [], "numeric_refs": []},
        "evidence_index": project_evidence_index(project, strict),
    }
    request["narrative"] = build_narrative(request, milestone_status)
    return {"schema_version": SCHEMA_VERSION, "funding_request": request}


def sufficiency_basis(measure):
    """La base di sufficienza, con la DICHIARAZIONE del fallback a
    `funding_gap_to_zero` (richiesta costruita a cassa zero) quando la misura
    e' `to_zero`."""
    basis = (f"misura {measure}, coerente con la politica di "
             "capitalizzazione e con la base nominata da modeled_need_ref")
    if measure == "to_buffer":
        return basis
    return (f"{basis}; FALLBACK DICHIARATO: la richiesta e' costruita "
            f"{FALLBACK_DISCLOSURE} perche' funding_gap_to_buffer vale "
            "NOT_APPLICABLE, e nessuna soglia di buffer e' usata come base")


# --------------------------------------------------------------------------
# RENDERER — derivato `funding-request.md` e narrativa tracciata
# --------------------------------------------------------------------------


#: ESPRESSIONE NUMERICA della prosa (`fr_narrative_untraced_value` sul
#: fronte JSON, `derived_artifact_numeric_mismatch` sul derivato). Il
#: confronto con i letterali
#: dichiarati avviene per ESPRESSIONE COMPLETA, MAI per sottostringa ne' per
#: singolo gruppo di cifre: un `50` tracciato non autorizza un `5` inventato,
#: e i `7` e `100` dichiarati non autorizzano il numerale `7 100 100`.
#:
#: VISTA DEL LETTORE. La prosa e' Markdown, e si scandisce come
#: il lettore la vede, con la regola piu' piccola che non nasconde nulla, UNA
#: sola per il fronte JSON e per il derivato:
#:
#:   - i BLOCCHI sono quelli di CommonMark: righe vuote, intestazioni, voci di
#:     elenco. Dentro un paragrafo un a capo e' uno spazio, e un
#:     qualificatore dopo un a capo resta legato alle proprie cifre. Solo LF,
#:     CR e CRLF sono fine riga; ogni altro separatore di riga Unicode e' uno
#:     spazio;
#:   - commenti e tag HTML (nella grammatica di CommonMark), destinazioni di
#:     link ed etichette di riferimento sono RIMOSSI soltanto quando non
#:     portano alcun carattere numerico: un tag in linea unisce, un tag di
#:     blocco (`<br>`, `<p>`, `<td>`) vale uno spazio, e una marcatura FRA
#:     DUE CIFRE lascia un carattere di formato invisibile, cosi' che la
#:     rimozione non fabbrichi mai un letterale (`10<br>0` non e' `100`). Un
#:     autolink e il testo alternativo di un'immagine restano, perche' il
#:     lettore li vede; le cifre di un commento restano numeri. Le entita' con
#:     NOME sono decodificate (`&nbsp;` e' uno spazio); un riferimento
#:     numerico resta testo, e le sue cifre restano numeri;
#:   - i marcatori `*`, `_`, backtick, `~`, backslash, `[`, `]` e i caratteri
#:     di formato o combinanti (`Cf`, `Mn`, `Mc`, `Me`) non separano nulla:
#:     fra due gruppi di cifre li UNISCONO in un solo numerale, fra le cifre e
#:     un qualificatore li LEGANO.
#:
#: ESPRESSIONE COMPLETA. Un NUCLEO — segno eventuale, gruppi di cifre uniti da
#: un separatore di gruppo (`.`, `,`, `_`, apostrofi, separatori arabi), da
#: spazi o marcatori, o da un operatore (`x`, il segno di moltiplicazione,
#: `*`, `^`), ed esponente eventuale (`12e8`, `0E-31`) — con un
#: QUALIFICATORE eventuale PRIMA o DOPO:
#: una parola del VOCABOLARIO CHIUSO `MAGNITUDE_WORDS` anche incollata alla
#: valuta (`kEUR`, `k` + euro), raggiunta anche attraverso valute e
#: connettori (`EUR mln 12`, `mln di EUR 12`, `K EUR 100`, `100 k EUR`), un
#: moltiplicatore (`x3`), il per mille, lettere INCOLLATE alle cifre (`7M`,
#: `100mila`), o una parola in una scrittura NON LATINA: un qualificatore
#: confondibile (`M` cirillico, lettere a larghezza piena o matematiche)
#: fallisce CHIUSO invece di essere normalizzato. Nessun parsing del
#: linguaggio naturale: una parola latina fuori dal vocabolario (`12 periodi`,
#: `12 mesi`, `7 Milano`) non qualifica nulla, e tre numeri separati da `/`
#: restano tre numeri.
#:
#: CARATTERI NUMERICI. Una cifra e' ogni
#: carattere delle categorie Unicode `Nd`, `Nl` e `No`: cifre ASCII, a
#: larghezza piena e arabo-indiane, ma anche apici, pedici, cifre cerchiate,
#: numeri romani e frazioni. Nessuna normalizzazione: un nucleo con caratteri
#: non ASCII non e' la resa di alcun letterale ASCII, e fallisce chiuso.
#:
#: REGOLA CHIUSA DI TRACCIAMENTO: un'espressione e'
#: tracciata se e solo se NON e' qualificata e il suo nucleo e' IDENTICO,
#: carattere per carattere, alla RESA di un letterale dichiarato — la forma
#: `str` che il canonico emette e che il renderer scrive invariata. Nessuna
#: resa ALTERNATIVA e' ammessa, e l'uguaglianza di VALORE non traccia nulla:
#: `Decimal("100.000") == Decimal("100")`, ma nella prosa italiana `100.000`
#: e' centomila, e `12.0` non e' la resa di alcun campo che dichiari `12`.
#: La resa `0E-31` che il costruttore emette per una quota NULLA (categoria
#: a peso nullo) e' un nucleo UNICO, tracciato dalla sola resa dichiarata
#: `0E-31`.
#:
#: IDENTIFICATORI. Le cifre di un identificatore sono
#: sottratte alla scansione SOLO se l'identificatore RISOLVE: se e', carattere
#: per carattere, uno degli identificatori AUTORITATIVI del contesto di
#: validazione, calcolati UNA volta da `resolvable_ids` per entrambi i fronti.
#: La FORMA non basta: un id di un namespace approvato (`MIL-5000000`,
#: `FR-DILUIZIONE-20`) o con la forma di un nome di stage (`99_milioni`) che
#: non risolve resta TESTO, e le sue cifre sono token come ogni altra.
#:
#: NAMESPACE APPROVATI degli id tipizzati, ELENCO CHIUSO: quelli che gli schemi
#: della skill dichiarano (`schemas/*.schema.json`: `ASS`, `P-ASS`, `COND`,
#: `DEC`, `DRV`, `EVD`, `MIL`, `OPS`, `RISK`, `ROLE`, `SRC`) e `FR`, il
#: namespace dei codici di decisione e delle sezioni che questo stage conia.
#: Un id deve INIZIARE col namespace: un prefisso qualunque (`EUR-`, `tx-`)
#: non lo rende un identificatore. La forma di un nome di stage e' `NN_nome`
#: (`10_financial-plan`), ed e' un identificatore solo se e' ESATTAMENTE uno
#: stage di `stage_order`.
TYPED_ID_NAMESPACES = ("P-ASS", "ASS", "COND", "DEC", "DRV", "EVD", "FR",
                       "MIL", "OPS", "RISK", "ROLE", "SRC")
TYPED_ID_RE = re.compile(
    rf"(?<![0-9A-Za-z_-])(?:{'|'.join(TYPED_ID_NAMESPACES)})"
    r"(?:-[A-Z0-9]+)+(?![0-9A-Za-z_])")
STAGE_NAME_RE = re.compile(r"(?<![\w-])[0-9]{2}_[a-z]+(?:-[a-z]+)*(?![\w-])")

#: Un identificatore RISOLTO e' sostituito da questo segno: non e' una cifra,
#: non e' uno spazio e non e' una lettera, e percio' non unisce ne' qualifica
#: i numeri che lo circondano.
ID_MASK = "\u00a7"

#: VOCABOLARIO CHIUSO delle grandezze, senza distinzione di maiuscole: le
#: parole che MOLTIPLICANO le cifre a cui si legano: migliaia, milioni e
#: miliardi in italiano, le abbreviazioni d'uso e i simboli `k` / `M`; gli
#: altri nomi di grandezza italiani
#: (`decine`, `dozzine`, `centinaia`, `cento`, `mille`), le abbreviazioni
#: finanziarie `mgl` / `mn` / `bln` e le grandezze inglesi. Un numerale
#: italiano COMPOSTO che termina in una grandezza (`centomila`, `duemila`,
#: `tremilioni`) qualifica come la sua grandezza (`COMPOUND_MAGNITUDES`), e
#: `per mille` e' il per mille. `MM` non vi entra: senza distinzione di
#: maiuscole sarebbe il millimetro (`12 mm`); ne' `per cento`, che e' il `%`.
#: Valute e connettori non qualificano, ma non interrompono la catena fra le
#: cifre e una grandezza.
MAGNITUDE_WORDS = ("miliardi", "miliardo", "migliaia", "migliaio", "milioni",
                   "milione", "mila", "mln", "mld", "mrd", "mio", "bn", "k",
                   "m", "centinaia", "centinaio", "decine", "decina",
                   "dozzine", "dozzina", "cento", "mille", "mgl", "mn", "bln",
                   "hundreds", "hundred", "thousands", "thousand", "millions",
                   "million", "billions", "billion", "trillions", "trillion")
COMPOUND_MAGNITUDES = ("mila", "milioni", "milione", "miliardi", "miliardo")
CURRENCY_WORDS = ("euro", "eur", "usd", "gbp", "chf", "\u20ac", "$", "\u00a3")
CONNECTOR_WORDS = ("di", "de", "of", "in")
#: Le grandezze ABBREVIATE: il loro PROPRIO punto
#: (`mln.`, `Mio.`, `Mrd.`) fa parte del qualificatore e non chiude alcuna
#: frase (`EUR mln. 12`, `Mrd. EUR 12`).
ABBREVIATED_MAGNITUDES = ("mln", "mld", "mrd", "mio", "mgl", "bln", "mn",
                          "bn", "k", "m")

#: CLASSI DI CARATTERE della scansione. Ogni carattere del testo e' mappato,
#: UNO a UNO, sulla propria classe: le cifre di ogni categoria numerica, i
#: caratteri di formato o combinanti, gli spazi e le lettere NON latine
#: diventano un segno privato ciascuna; ogni altro carattere resta se'
#: stesso. L'espressione regolare opera sulla forma, e i suoi estremi
#: ritagliano il testo originale: nessuna aritmetica sugli indici.
#:
#: TEMPO LINEARE. I quantificatori sulle sequenze di giunzione e di cifre sono
#: POSSESSIVI, e ogni costrutto che scorre una sequenza di caratteri di
#: formato puo' cominciare SOLO al suo inizio: un testo avversario (migliaia
#: di caratteri invisibili dopo una grandezza) non costa un tempo quadratico.
#: La linearita' vale per OGNI passo della vista del lettore, compreso il
#: caso patologico di un `<img` mai chiuso con `alt=` ripetuti. Non e'
#: un'affermazione: i test la MISURANO come SCALA, T(4N) contro T(N), su
#: famiglie avversarie di ogni passo, sui due fronti della prosa.
NUMERIC_CATEGORIES = ("Nd", "Nl", "No")
FORMAT_CATEGORIES = ("Cf", "Mn", "Mc", "Me")
SHAPE_NUMERIC = "\ue000"
SHAPE_FORMAT = "\ue001"
SHAPE_SPACE = "\ue002"
SHAPE_FOREIGN = "\ue003"
SHAPE_OPAQUE = "\ufffd"


def shape_of(char):
    """La CLASSE di `char`. Un carattere a uso privato del testo diventa un
    segno opaco, cosi' che non possa mai fingersi una classe."""
    category = unicodedata.category(char)
    if category == "Co":
        return SHAPE_OPAQUE
    if category in NUMERIC_CATEGORIES:
        return SHAPE_NUMERIC
    if category in FORMAT_CATEGORIES:
        return SHAPE_FORMAT
    if char.isspace():
        return SHAPE_SPACE
    if category.startswith("L") and \
            not unicodedata.name(char, "").startswith("LATIN"):
        return SHAPE_FOREIGN
    return char


_N, _F, _S, _G = SHAPE_NUMERIC, SHAPE_FORMAT, SHAPE_SPACE, SHAPE_FOREIGN
_LETTER = rf"(?:[^\W\d_]|{_G})"
_SIGN = "[-+\u2212\ufe62\ufe63\uff0b\uff0d\u2795\u2796]"
_GROUP = "[.,_'\u2019\u066b\u066c]"
_MARK = r"[*_`~\\\[\]]"
#: La PRESENTAZIONE: marcatori Markdown (enfasi, codice,
#: parentesi di un link) e caratteri di formato. Il lettore non li vede, e
#: DENTRO un'espressione numerica non la spezzano: fra il segno e le cifre
#: (`-**12**`, `_-12_`), fra la mantissa e l'esponente (`**12**e8`,
#: `` `12`e8 ``, `[12](u)e8`), fra le lettere di una parola del vocabolario
#: (`12 **mil**ioni`, `100 mi&shy;la`, `12 cen&shy;tomila`). Possessivo, e
#: consumato solo DOPO un elemento gia' riconosciuto (segno, cifre, lettera,
#: abbreviazione), mai come inizio di una prova: nessun tempo quadratico.
_MK = rf"(?:[{_F}]|{_MARK})*+"
_OPERATOR = "[xX\u00d7*\u00b7\u22c5\u2219^]"
_RUN = rf"{_F}*+{_N}[{_N}{_F}]*+"
_LINK = (rf"(?:[{_F}]|{_MARK})*+{_GROUP}(?:[{_F}]|{_MARK})*+"
         rf"|(?:[{_S}{_F}]|{_MARK})++"
         rf"|[{_S}]*+{_OPERATOR}[{_S}]*+")
#: Il segno, o il separatore decimale iniziale, non segue una lettera o una
#: cifra; il trattino basso, che puo' essere enfasi (`_-12_`), non conta.
_LEAD = (rf"(?:(?<![^\W_])(?<![{_N}{_G}]){_SIGN}{_MK}"
         rf"(?:[.,](?={_MK}{_N}){_MK})?"
         rf"|(?<![^\W_])(?<![{_N}{_G}.,])[.,](?={_MK}{_N}){_MK})?")
_EXPONENT = rf"(?:{_MK}[eE]{_MK}(?:{_SIGN}{_MK})?{_RUN})?"
_CORE = (rf"(?<![{_F}])[{_F}]*+{_LEAD}{_RUN}(?:(?:{_LINK}){_RUN})*"
         rf"{_EXPONENT}")


def _spelled(word):
    """La parola `word` come la vede il lettore: ogni
    sequenza di presentazione (`_MK`) FRA due sue lettere e' trasparente."""
    return _MK.join(re.escape(char) for char in word)


_MAGNITUDE = "|".join(_spelled(word) for word in
                      sorted(MAGNITUDE_WORDS, key=len, reverse=True))
_ABBREVIATED = "|".join(_spelled(word) for word in
                        sorted(ABBREVIATED_MAGNITUDES, key=len, reverse=True))
_CURRENCY = "|".join(_spelled(word) for word in CURRENCY_WORDS)
_COMPOUND = "|".join(_spelled(word) for word in COMPOUND_MAGNITUDES)
_CONNECTOR = "|".join(_spelled(word) for word in CONNECTOR_WORDS)
_SYMBOL = "[\u00d7\u2030\u2031]"
#: La FINE di una FRASE: `.`, `!`, `?` o `…`, i segni che
#: la chiudono (enfasi, virgolette, parentesi: `12.** Migliaia`, `12.)`),
#: spazio, e una frase che comincia con la maiuscola o con una cifra (anche
#: dopo virgolette, parentesi o marcatori di apertura).
_UPPER = "A-Z\u00c0-\u00d6\u00d8-\u00de"
_OPENING = "[\u00ab\u201c\u2018\"'(\\[*_`~]*+"
_CLOSING = "[*_`~)\\]\u00bb\u201d\u2019\"']*+"
_SENTENCE_END = (rf"[.!?\u2026]{_CLOSING}[{_S}]++{_OPENING}"
                 rf"[{_UPPER}{_N}]")
#: Cio' che LEGA le cifre a un qualificatore vicino e'
#: OGNI carattere che non sia una lettera o una cifra: la regola e'
#: fail-CLOSED, e nessun elenco chiuso di separatori ne decide la sicurezza.
#: Il punto di un'abbreviazione (`EUR mln. 12`), `=`, `,`, `;`, `/`, `%`,
#: frecce, virgolette e caporali, la barra di una cella di tabella, spazi,
#: formato e marcatori legano tutti. NON legano, e chiudono la catena:
#:   - una lettera o una cifra: una parola che non e' una valuta o un
#:     connettore (`_CHAIN`) separa, come in `12 periodi, in milioni`;
#:   - la FINE di una FRASE (`_SENTENCE_END`): la relazione fra grandezza e
#:     cifre e' LOCALE alla frase (`12 EUR. Migliaia di PMI ...`), e la scala
#:     dichiarata in un'altra frase e' contesto di documento, fuori da
#:     questo controllo. Il punto PROPRIO di un'abbreviazione non chiude nulla
#:     (`_OWN_PERIOD`);
#:   - `ID_MASK`: sta al posto di un identificatore RISOLTO, cioe' di una
#:     parola;
#:   - `‰`, `‱` e il segno di moltiplicazione (`_SYMBOL`): sono essi stessi
#:     qualificatori, e la giunzione non deve consumarli.
#: Il `%` che segue SUBITO le cifre (spazi e presentazione a parte) e' l'unita'
#: della loro percentuale (`(20%)`), come la parola `per cento`: chiude
#: l'espressione, e nessuna grandezza la riscala (`_OWN_UNIT`). Altrove, per
#: esempio in un'etichetta a due unita' (`(EUR mln / %): 12`), lega.
_JOIN = (rf"(?:(?!{_SENTENCE_END})[^\w{_N}{_G}{ID_MASK}\u2030\u2031\u00d7]"
         rf"|_)")
_OWN_UNIT = rf"(?!(?:[{_S}{_F}]|{_MARK})*+%)"
#: Un CODICE di valuta per FORMA, non per elenco: fino a
#: tre maiuscole INCOLLATE a un simbolo di valuta (`US$`, `HK$`, `A$`); mai
#: una grandezza o il moltiplicatore (`M$`, `K€`, `X$` restano
#: qualificatori). Tre maiuscole sole NON bastano: sarebbero anche le sigle
#: d'uso (`PMI`, `KPI`, `IVA`).
_CURRENCY_CODE = (rf"(?!(?i:{_ABBREVIATED}|{_MAGNITUDE}|x)(?![^\W\d_]))"
                  rf"[A-Z]{{1,3}}(?=[$\u20ac\u00a3\u00a5])")
#: Il punto PROPRIO di un'abbreviazione (`mln.`, `Mio.`, `**Mrd**.`) e' parte
#: del qualificatore, salvo quando chiude la frase: seguito da spazio e da una
#: parola MAIUSCOLA che non e' una valuta (`e' mio. In 12 mesi`). Seguito da
#: cifre (`EUR mln. 12`) o da una valuta (`Mrd. EUR 12`) resta
#: nell'espressione.
_OWN_PERIOD = (rf"{_MK}\.(?!{_CLOSING}[{_S}]++{_OPENING}"
               rf"(?!(?i:{_CURRENCY})(?!{_LETTER})|{_CURRENCY_CODE})"
               rf"[{_UPPER}])")


def _qualifier(compound_prefix):
    """Il QUALIFICATORE: parole del vocabolario (con il punto proprio di
    un'abbreviazione), numerali composti, `per mille`, il moltiplicatore `x`,
    una parola in scrittura non latina; o un simbolo (`_SYMBOL`), che non
    chiede alcun confine di parola. `compound_prefix` e' la parte che
    precede la grandezza di un composto (`cento` in `centomila`)."""
    return (rf"(?:(?:(?i:(?:(?:{_CURRENCY}){_MK})?"
            rf"(?:(?:{_ABBREVIATED})(?:{_OWN_PERIOD})?|{_MAGNITUDE})"
            rf"(?:{_MK}(?:{_CURRENCY}))?)"
            rf"|(?i:(?:{compound_prefix})?(?:{_COMPOUND}))"
            rf"|(?i:{_spelled('per')}){_JOIN}*+(?i:{_spelled('mille')})"
            rf"|(?i:x)"
            rf"|(?=(?:[^\W\d_]|[{_F}])*+{_G})(?:{_LETTER}|[{_F}])++)"
            rf"(?!{_LETTER})|{_SYMBOL})")


#: Il composto PRIMA delle cifre: lettere, e la presentazione solo alla
#: giunzione con la grandezza. DOPO le cifre (un solo tentativo per nucleo)
#: la presentazione e' trasparente anche fra le lettere (`12 d**ue**mila`).
_QUALIFIER = _qualifier(rf"[^\W\d_]+?{_MK}")
_QUALIFIER_AFTER = _qualifier(rf"(?:[^\W\d_]{_MK})+?")
#: Valute e connettori non qualificano ma non spezzano la
#: catena, quanti che siano: anche nella forma ELISA (`milioni d'euro`,
#: `d'**euro**`) e nei codici di valuta incollati a un simbolo
#: (`_CURRENCY_CODE`). Una parola che CONTINUA dopo la presentazione non e'
#: una valuta o un connettore (`**de**cine` e' `decine`, non `de`).
_CHAIN = (rf"(?:(?i:{_CURRENCY}|{_CONNECTOR})(?!{_MK}{_LETTER})"
          rf"|(?i:d){_MK}['\u2019](?={_MK}{_LETTER})|{_CURRENCY_CODE})"
          rf"{_JOIN}*+")
#: Lettere INCOLLATE alle cifre, anche attraverso la
#: presentazione (`**12**abc`). Non il trattino basso: fra due caratteri
#: alfanumerici non e' mai enfasi in CommonMark, e resta VISIBILE
#: (`cassa_12_periodi.csv`).
_GLUED = (rf"(?:[{_F}]|[*`~\\\[\]])*+(?:{_LETTER}|[\u2030\u2031])"
          rf"(?:{_LETTER}|[{_F}{_N}\u2030\u2031])*+")
EXPRESSION_RE = re.compile(
    rf"(?P<prefix>(?:(?<![^\W\d_])(?<![{_G}{_F}])[{_F}]*+{_QUALIFIER}"
    rf"|{_SYMBOL}){_JOIN}*+(?:{_CHAIN})*+)?"
    rf"(?P<core>{_CORE})"
    rf"(?P<suffix>{_OWN_UNIT}(?:{_GLUED}"
    rf"|{_JOIN}*+(?:{_CHAIN})*+{_QUALIFIER_AFTER}))?")

#: Un nucleo ASCII con i soli separatori decimali: e' nominato com'e'.
PLAIN_CORE_RE = re.compile(r"[-+]?[0-9]+(?:[.,][0-9]+)*")

_WS = rf"[\s{_S}]"
#: Un tag HTML GREZZO secondo la grammatica di CommonMark 0.31 (nome, attributi
#: con valore facoltativo, chiusura): SOLO questi sono marcatura invisibile.
#: Ogni altra coppia di parentesi angolari (`<milioni di euro, stima>`) e'
#: testo che il lettore vede, e resta.
_TAG = (rf"<(?:[A-Za-z][A-Za-z0-9-]*(?:{_WS}++[A-Za-z_:][A-Za-z0-9_.:-]*"
        rf"(?:{_WS}*={_WS}*(?:[^\s{_S}\"'=<>`]+|'[^']*'|\"[^\"]*\"))?)*+"
        rf"{_WS}*/?|/[A-Za-z][A-Za-z0-9-]*{_WS}*)>")
HTML_TAG_RE = re.compile(_TAG)
HTML_TAG_NAME_RE = re.compile(r"</?([A-Za-z][A-Za-z0-9-]*)")
#: Un tag `<img>` COMPLETO, nella STESSA grammatica
#: lineare di `_TAG` (quantificatori possessivi): nessuna ricerca pigra che
#: riscandisca il resto del blocco a ogni `alt=`. I suoi attributi si leggono
#: poi UNO DOPO L'ALTRO dall'inizio del tag (`image_alt`), e un `alt=` dentro
#: il valore di un altro attributo non e' un attributo.
_ATTRIBUTE = (rf"{_WS}++([A-Za-z_:][A-Za-z0-9_.:-]*)"
              rf"(?:{_WS}*={_WS}*([^\s{_S}\"'=<>`]+|'[^']*'|\"[^\"]*\"))?")
HTML_IMAGE_TAG_RE = re.compile(
    rf"<(?i:img)(?![A-Za-z0-9{_N}-])(?:{_ATTRIBUTE})*+{_WS}*/?>")
HTML_ATTRIBUTE_RE = re.compile(_ATTRIBUTE)
HTML_IMAGE_NAME_RE = re.compile(r"<(?i:img)")
#: Un autolink (`<https://...>`, `<nome@dominio>`) e' TESTO VISIBILE per il
#: lettore: ne resta il contenuto, senza le parentesi angolari.
AUTOLINK_RE = re.compile(
    rf"<[A-Za-z][A-Za-z0-9+.-]{{1,31}}:[^\s{_S}<>]*>"
    r"|<[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*>")
#: I tag che il lettore vede come un a capo o un confine di blocco: tolti,
#: lasciano uno SPAZIO. Un tag in linea (`<b>`, `<span>`) non separa nulla.
BLOCK_TAGS = ("address", "article", "aside", "blockquote", "br", "caption",
              "dd", "details", "div", "dl", "dt", "fieldset", "figcaption",
              "figure", "footer", "form", "header", "hr", "li", "main", "nav",
              "ol", "p", "pre", "section", "summary", "table", "tbody", "td",
              "tfoot", "th", "thead", "tr", "ul")
#: Una sequenza di tag FRA DUE CIFRE (per i commenti: `strip_comments`), e
#: il carattere di formato invisibile (U+2063) che ne prende il posto.
BETWEEN_DIGITS_MARKUP_RE = re.compile(rf"(?<={_N})(?:{_TAG})++(?={_N})")
MARKUP_SEAM = "\u2063"
IMAGE_MARK_RE = re.compile(r"!(?=\[)")
#: La DESTINAZIONE e il TITOLO di un link in linea, come
#: li legge CommonMark 0.31 (par. 6.3), sul testo ORIGINALE: destinazione fra
#: parentesi angolari, o sequenza senza spazi ne' caratteri di controllo con
#: parentesi BILANCIATE (fino a `LINK_NESTING` livelli, il limite delle
#: implementazioni di riferimento) e con escape; titolo fra virgolette,
#: apici o parentesi, con escape. Nessun URL e' seguito ne' interpretato.
#: Il lettore NON vede destinazione e titolo come testo del paragrafo: tolti,
#: l'etichetta visibile resta legata a cio' che la segue
#: (`[12](https://it.wikipedia.org/wiki/Euro_\(valuta\)) milioni`). Una
#: destinazione o un titolo che porta cifre non sparisce: e' scandito come
#: BLOCCO PROPRIO (`strip_digit_free_markup`), e le sue cifre restano numeri.
#: Il riconoscimento e' LESSICALE: un `](...)` che per CommonMark non e' un
#: link (parentesi con escape, span di codice, nessuna apertura) e' testo
#: visibile, e la lettura che lo lascia al suo posto e' scandita ANCH'ESSA
#: (`prose_blocks`): nessuna rimozione nasconde al controllo una cifra o un
#: qualificatore che il lettore vede.
#: Ogni quantificatore e' possessivo: una prova fallita si ferma al primo
#: spazio, alla prima parentesi non bilanciata o al `LINK_NESTING`-esimo
#: livello, e i titoli di prove diverse non si sovrappongono.
LINK_NESTING = 32
_LINK_ESCAPE = r"\\[!-/:-@\[-`{-~]"
_LINK_PLAIN = rf"(?:{_LINK_ESCAPE}|\\|[^\x00-\x20\x7f()\\])"


def _nested_parentheses(depth):
    """Una sequenza di `_LINK_PLAIN` con parentesi bilanciate fino a `depth`
    livelli, costruita dall'interno: nessuna ricorsione nella regex."""
    group = rf"{_LINK_PLAIN}*+"
    for _ in range(depth):
        group = rf"(?:{_LINK_PLAIN}|\({group}\))*+"
    return group


_LINK_DESTINATION = (rf"<(?:{_LINK_ESCAPE}|\\|[^<>\n\\])*+>"
                     rf"|(?!<){_nested_parentheses(LINK_NESTING)}")
_LINK_TITLE = (rf"\"(?:{_LINK_ESCAPE}|\\|[^\"\\])*+\""
               rf"|'(?:{_LINK_ESCAPE}|\\|[^'\\])*+'"
               rf"|\((?:{_LINK_ESCAPE}|\\|[^()\\])*+\)")
LINK_TARGET_RE = re.compile(
    rf"\](?P<target>\([ \t\n]*+(?:(?:{_LINK_DESTINATION})"
    rf"(?:[ \t\n]++(?:{_LINK_TITLE}))?)?[ \t\n]*+\))")
LINK_LABEL_RE = re.compile(r"\]\[[^\[\]]*\]")
#: Le ALTRE due letture della sintassi dei link, scandite accanto a quella
#: di CommonMark (`prose_blocks`): la lettura LESSICALE (una destinazione
#: senza parentesi e senza cifre e' tolta, ogni altra resta al suo posto), e
#: la lettura LETTERALE (nessun link: la sintassi resta testo, e le parentesi
#: quadre sono punteggiatura VISIBILE, non presentazione). Un'espressione
#: respinta in UNA delle letture resta respinta: nessuna lettura ne
#: allenta un'altra.
LEXICAL_LINK_TARGET_RE = re.compile(r"\]\([^()]*\)")
LITERAL_BRACKETS = str.maketrans("[]", "()")
#: Il solo riferimento a carattere che la vista del lettore DECODIFICA: quello
#: con NOME e punto e virgola (`&nbsp;` e' uno spazio). Un riferimento
#: NUMERICO resta testo: le sue cifre restano numeri per la scansione, e un
#: riferimento che CommonMark mostrerebbe alla lettera non sparisce mai.
NAMED_REFERENCE_RE = re.compile(r"&([A-Za-z][A-Za-z0-9]{0,31});")
LINE_END_RE = re.compile(r"\r\n|\r|\n")
BLOCKQUOTE_RE = re.compile(r"^ {0,3}(?:> ?)+")
#: Le sole righe che INTERROMPONO un paragrafo, come in CommonMark: una
#: intestazione ATX, una voce di elenco puntato non vuota, una voce
#: numerata che parte da 1, un recinto di codice (il recinto di backtick non
#: porta backtick nella stringa informativa). Una voce numerata da un altro
#: numero continua il paragrafo, e apre un blocco solo dentro un elenco.
BLOCK_START_RE = re.compile(
    r"^ {0,3}(?:#{1,6}(?:[ \t]|$)|[-+*][ \t]+\S|0*1[.)][ \t]+\S"
    r"|`{3,}[^`]*$|~{3,})")
#: Una voce di elenco: il marcatore (puntato o numerato,
#: col suo delimitatore) e la colonna del contenuto (fine della spaziatura,
#: al piu' quattro).
LIST_ITEM_RE = re.compile(
    r"^ {0,3}(?P<marker>(?P<bullet>[-+*])|[0-9]{1,9}(?P<delimiter>[.)]))"
    r"[ \t]{1,4}")
HEADING_RE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
#: Un confine che il lettore VEDE: una linea orizzontale, o la sottolineatura
#: di un'intestazione, chiude il blocco. Le righe di una tabella o di un
#: recinto di codice restano nel paragrafo come in CommonMark: nessuna
#: separazione in piu', perche' separare e' la direzione che puo' staccare
#: un qualificatore dalle proprie cifre.
THEMATIC_BREAK_RE = re.compile(
    r"^ {0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,}|=+[ \t]*)$")

#: Un'espressione della prosa: il NUCLEO numerico, il QUALIFICATORE (o
#: `None`) e la resa che il lettore vede, come il rifiuto la nomina.
NumericExpression = collections.namedtuple(
    "NumericExpression", ("core", "qualifier", "display"))

#: Gli identificatori con cui QUESTO stage conia la propria
#: prosa, ELENCO CHIUSO: le sezioni di `build_narrative`, la condizione di
#: copertura di default e i codici di decisione. Un id fuori da questo elenco,
#: e da ogni altra sorgente di `resolvable_ids`, non risolve.
NARRATIVE_SECTION_IDS = ("FR-S1", "FR-S2", "FR-S3", "FR-S4", "FR-S5", "FR-S6")
SCENARIO_CONDITION = "COND-S10-SCENARIO-COVERAGE"
COINED_IDS = (*NARRATIVE_SECTION_IDS, SCENARIO_CONDITION, MILESTONE_DECISION,
              *TERM_DECISION_CODES)


def has_numeric(text):
    return any(unicodedata.category(char) in NUMERIC_CATEGORIES
               for char in text)


def splice(text, regex, replace):
    """`text` con ogni corrispondenza di `regex` sulla FORMA di `text`
    sostituita da `replace(testo originale della corrispondenza)`. I confini
    vengono dalla forma, che e' allineata carattere per carattere al testo:
    nessuna aritmetica sugli indici."""
    shape = "".join(map(shape_of, text))
    pieces = []
    cursor = 0
    for match in regex.finditer(shape):
        pieces.append(text[cursor:match.start()])
        pieces.append(replace(text[match.start():match.end()]))
        cursor = match.end()
    pieces.append(text[cursor:])
    return "".join(pieces)


def strip_comments(text):
    """I commenti HTML come in CommonMark 0.31: `<!-->`,
    `<!--->`, o `<!--` seguito dal primo `-->`; un `<!--` mai chiuso resta
    testo. Un commento privo di cifre e' rimosso, e FRA DUE CIFRE lascia
    `MARKUP_SEAM`; uno con cifre resta testo e le sue cifre restano numeri.
    Un solo passaggio da sinistra a destra, in tempo lineare anche su
    migliaia di aperture senza chiusura."""
    pieces = text.split("<!--")
    out = [pieces[0]]
    last = pieces[0][-1:]
    opened = None
    for piece in pieces[1:]:
        if opened is None and piece.startswith(">"):
            inner, rest = "", piece[1:]
        elif opened is None and piece.startswith("->"):
            inner, rest = "", piece[2:]
        else:
            if opened is None:
                opened = []
            else:
                opened.append("<!--")
            body, close, rest = piece.partition("-->")
            if not close:
                opened.append(piece)
                continue
            inner = "".join([*opened, body])
            opened = None
        if has_numeric(inner):
            # Le cifre di un commento restano numeri per la scansione, fra
            # spazi: non si incollano alle cifre visibili e non spezzano la
            # catena fra le cifre e una grandezza.
            replacement = f" {inner} "
        elif has_numeric(last) and has_numeric(rest[:1]):
            replacement = MARKUP_SEAM
        else:
            replacement = ""
        out.extend((replacement, rest))
        last = rest[-1:] or replacement[-1:] or last
    if opened is not None:
        out.append("<!--")
        out.extend(opened)
    return "".join(out)


def strip_digit_free_markup(text):
    """Rimuove commenti e tag HTML ed etichette di
    riferimento, ma SOLO dove non portano alcun carattere numerico: la
    rimozione unisce, e non nasconde mai una cifra. Il testo alternativo di
    un'immagine, che il lettore puo' vedere, RESTA. La
    destinazione e il titolo di un link in linea (`LINK_TARGET_RE`) escono
    SEMPRE dal testo visibile, cosi' che l'etichetta resti legata a cio' che
    la segue; se portano cifre, sono restituiti a parte (`targets`) e
    scanditi come blocchi propri. Le etichette di riferimento si tolgono
    PRIMA delle destinazioni: due link adiacenti (`[12](a)[ milioni](b)`)
    restano due etichette visibili, `[12][ milioni]`. Ritorna
    `(testo, targets, letture)`: `letture` sono lo stesso testo nella
    lettura LETTERALE e in quella LESSICALE
    (`LITERAL_BRACKETS`, `LEXICAL_LINK_TARGET_RE`).

    Un tag e' marcatura solo nella grammatica di CommonMark; un autolink
    resta come testo visibile. Un tag di BLOCCO (`BLOCK_TAGS`) vale uno
    spazio: per il lettore e' un a capo. Una sequenza di tag FRA DUE CIFRE
    non si rimuove: un `<br>`, una cella di tabella o un apice separano per
    il lettore cio' che la rimozione unirebbe in un letterale magari
    dichiarato (`10<br>0` non e' `100`). Vi resta uno spazio (tag di blocco)
    o un carattere di formato invisibile (tag in linea): le cifre formano
    ancora un'espressione, ma nessun letterale dichiarato la rende."""
    def drop(replacement):
        def apply(original):
            return original if has_numeric(original) else replacement
        return apply

    def alt_text(original):
        if has_numeric(original):
            return original
        alt = image_alt(original)
        return original if alt is None else f" {alt} "

    def is_block(original):
        return any(name.lower() in BLOCK_TAGS
                   for name in HTML_TAG_NAME_RE.findall(original))

    def between_digits(original):
        if has_numeric(original):
            return original
        return " " if is_block(original) else MARKUP_SEAM

    def tag(original):
        if has_numeric(original):
            return original
        return " " if is_block(original) else ""
    targets = []

    def link_target(match):
        if has_numeric(match.group("target")):
            targets.append(match.group("target"))
        return "]"
    text = strip_comments(text)
    text = splice(text, AUTOLINK_RE, lambda original: original[1:-1])
    text = splice(text, BETWEEN_DIGITS_MARKUP_RE, between_digits)
    text = splice(text, HTML_IMAGE_TAG_RE, alt_text)
    text = splice(text, HTML_TAG_RE, tag)
    text = IMAGE_MARK_RE.sub("", text)
    readings = (text.translate(LITERAL_BRACKETS),
                splice(splice(text, LEXICAL_LINK_TARGET_RE, drop("]")),
                       LINK_LABEL_RE, drop("]")))
    text = splice(text, LINK_LABEL_RE, drop("]"))
    return LINK_TARGET_RE.sub(link_target, text), targets, readings


def image_alt(original):
    """Il valore dell'attributo `alt` del tag `<img>`
    `original` (senza virgolette), letto attributo per attributo dall'inizio
    del tag; `None` se il tag non ne porta."""
    shape = "".join(map(shape_of, original))
    found = HTML_ATTRIBUTE_RE.match(
        shape, HTML_IMAGE_NAME_RE.match(shape).end())
    while found is not None:
        if found.group(1).lower() == "alt":
            value = original[found.start(2):found.end(2)] \
                if found.group(2) is not None else ""
            return value[1:-1] if value[:1] in ("'", '"') else value
        found = HTML_ATTRIBUTE_RE.match(shape, found.end())
    return None


def decode_named_references(text):
    """I riferimenti a carattere con NOME, come li decodifica CommonMark."""
    def decode(match):
        return HTML_ENTITIES.get(f"{match.group(1)};", match.group(0))
    return NAMED_REFERENCE_RE.sub(decode, text)


def markdown_blocks(text):
    """I BLOCCHI di CommonMark che il lettore vede: una riga
    vuota chiude il blocco; un'intestazione e' un blocco di una riga; una
    riga che interrompe un paragrafo (`BLOCK_START_RE`), o una voce dentro
    un elenco, apre un blocco; ogni altra riga continua il blocco
    corrente, e il suo a capo e' uno spazio. I marcatori di citazione sono
    trasparenti. Nel dubbio le righe restano UNITE: unire non nasconde mai
    un qualificatore."""
    blocks = []
    current = None
    for raw in LINE_END_RE.split(text):
        line = BLOCKQUOTE_RE.sub("", raw)
        if not line.strip(" \t") or THEMATIC_BREAK_RE.match(line):
            current = None
            continue
        if current is None or BLOCK_START_RE.match(line) or \
                sibling_item(line, current[0]):
            current = [line]
            blocks.append(current)
            if HEADING_RE.match(line):
                current = None
            continue
        current.append(line)
    return [" ".join(block) for block in blocks]


def sibling_item(line, first):
    """`line` e' una voce di elenco FUORI dal contenuto
    della voce che apre il blocco corrente (`first`): il suo marcatore sta
    a sinistra della colonna del contenuto di `first`, e CommonMark vi apre
    una voce nuova, di qualunque tipo. Una voce numerata da un numero
    diverso da 1 DENTRO il contenuto di una voce, o dopo un paragrafo che
    non sta in un elenco, non interrompe il paragrafo: la riga continua il
    blocco (`- Importi in EUR mln` / `  12. capitale richiesto`)."""
    item = LIST_ITEM_RE.match(line)
    opener = LIST_ITEM_RE.match(first)
    if item is None or opener is None:
        return False
    return item.start("marker") < opener.end()


def prose_blocks(text, heading=False):
    """I blocchi di `text` nella vista del lettore; con `heading` il testo e'
    un titolo di sezione, reso come intestazione (`## titolo`). La struttura
    dei blocchi si legge sulle righe ORIGINALI, come in CommonMark: una riga
    che porta un solo tag in linea non e' una riga vuota, e il paragrafo
    continua. La marcatura priva di cifre e' rimossa poi, blocco per blocco.
    La destinazione o il titolo di un link che porta
    cifre segue il proprio blocco come blocco PROPRIO: non spezza il testo
    visibile, e le sue cifre restano numeri. La sintassi dei link e'
    riconosciuta per via lessicale, e le sue letture possibili sono
    scandite tutte: link di CommonMark tolti, sintassi letterale, lettura
    lessicale; un'espressione non tracciata in UNA di esse e' respinta."""
    source = f"## {text}" if heading else text
    blocks = []
    for block in markdown_blocks(source):
        visible, targets, readings = strip_digit_free_markup(block)
        blocks.append(visible)
        blocks.extend(targets)
        for reading in dict.fromkeys(readings):
            if reading != visible:
                blocks.append(reading)
    return blocks


def normalized(text):
    return " ".join(text.split())


def mask_resolved(text, resolved):
    """Sottrae alla scansione SOLO gli identificatori che
    RISOLVONO in `resolved`. Un id della sola FORMA resta testo, e le sue
    cifre restano token."""
    def keep_or_mask(match):
        return ID_MASK if match.group(0) in resolved else match.group(0)
    return STAGE_NAME_RE.sub(keep_or_mask, TYPED_ID_RE.sub(keep_or_mask, text))


def numeric_expressions(block, resolved=frozenset()):
    """Le espressioni numeriche COMPLETE di un blocco, identificatori RISOLTI
    esclusi. Senza `resolved` nessun identificatore e' escluso:
    fail-closed."""
    text = mask_resolved(decode_named_references(block), resolved)
    shape = "".join(map(shape_of, text))
    expressions = []
    for match in EXPRESSION_RE.finditer(shape):
        core = text[match.start("core"):match.end("core")]
        if match.group("prefix") is not None:
            expressions.append(NumericExpression(
                core, text[match.start("prefix"):match.end("prefix")].strip(),
                text[match.start("prefix"):match.end("core")]))
        elif match.group("suffix") is not None:
            expressions.append(NumericExpression(
                core, text[match.start("suffix"):match.end("suffix")].strip(),
                text[match.start("core"):match.end("suffix")]))
        else:
            expressions.append(NumericExpression(core, None, core))
    return expressions


def prose_expressions(text, resolved=frozenset(), heading=False):
    """Le espressioni numeriche di una prosa Markdown, blocco per blocco."""
    expressions = []
    for block in prose_blocks(text, heading):
        expressions.extend(numeric_expressions(block, resolved))
    return expressions


def untraced(expressions, literals):
    """Le espressioni che NON sono la RESA di un letterale in `literals`
    (regola chiusa di tracciamento): qualificate, o con un nucleo che nessun
    letterale rende carattere per carattere."""
    return [expression for expression in expressions
            if expression.qualifier is not None
            or expression.core not in literals]


def token_label(expression):
    """L'espressione come il rifiuto la NOMINA: intera, e con essa le cifre
    che la compongono."""
    if expression.qualifier is not None:
        return (f"{expression.display!r} (cifre {expression.core!r} "
                f"qualificate da {expression.qualifier!r}: una resa DISTINTA, "
                "che le sole cifre non tracciano)")
    if PLAIN_CORE_RE.fullmatch(expression.core):
        return repr(expression.core)
    return (f"{expression.core!r} (numerale che nessun letterale dichiarato "
            "rende: ne' i suoi gruppi di cifre ne' il suo valore lo "
            "tracciano)")


def roadmap_ids(project):
    """Gli id del registro REALE della roadmap (`STAGE9`): la sorgente contro
    cui risolve ogni `MIL-*` (`fr_milestone_not_in_roadmap`)."""
    roadmap = optional_json(
        Path(project).joinpath(STAGE9, CANONICAL_NAME), None)
    known = set()
    if isinstance(roadmap, dict):
        for item in ((roadmap.get("milestone_plan") or {})
                     .get("milestones") or []):
            known.add(str(item.get("id")))
    return known


def resolvable_ids(canonical, project, stage_order):
    """Gli identificatori AUTORITATIVI del contesto di
    validazione dello Stage 11: i SOLI le cui cifre la scansione numerica
    esclude. Una sola risoluzione, per `check_narrative` e `check_derived`.

    Il canonico dello Stage 11 SOTTO VALIDAZIONE non e' autorita' di se'
    stesso: e' proprio il documento che l'exploit manomette. Ogni campo con
    cui dichiara identificatori risolve percio' contro la propria AUTORITA':

      - `milestone_financing[].milestone_ref` contro la roadmap REALE (la
        stessa di `fr_milestone_not_in_roadmap`);
      - `evidence_index` e `assumption_refs` contro i registri di evidenza,
        di fonte e ufficiale delle assunzioni, nelle sole forme canoniche
        degli id (gli stessi registri di `check_evidence_registers` e del
        conteggio delle assunzioni non validate);
      - `use_of_proceeds[].driver_refs` e `milestone_financing[].cost_ref`
        contro i driver che il canonico dello Stage 10 riferisce dai
        candidati d'impiego (`fr_category_not_traceable`) e dalle milestone;
      - `unresolved_validation_items[]` contro codici e riferimenti delle
        voci di validazione dello Stage 10
        (`fr_unresolved_items_suppressed`);
      - `decision_needed[].code` contro la condizione di copertura proposta
        dallo Stage 10 e i codici che questo stage conia (`COINED_IDS`);
      - `narrative.sections[].section_id` contro le sezioni coniate;
      - `policy_ref` contro gli identificatori che `POLICY_REF` nomina;
      - i nomi di stage contro `stage_order` della configurazione.

    Un id che nessuna autorita' dichiara non risolve, anche se il canonico
    sotto validazione lo porta in un proprio campo.
    """
    known = set(stage_order)
    known.update(roadmap_ids(project))
    registers = [(rel, canonical_re, loose_re)
                 for _, rel, canonical_re, loose_re in EVIDENCE_REGISTERS]
    registers.append((ASSUMPTIONS_REL, fw.ASS_RE, fw.LOOSE_ANY_ASS_RE))
    for rel, canonical_re, loose_re in registers:
        ids, _ = register_ids(load_register(project, rel), rel, canonical_re,
                              loose_re)
        known.update(ids)
    modules = modules_of(canonical)
    for candidate in ((modules.get("funding_gap") or {})
                      .get("use_of_proceeds_candidates") or []):
        known.update(str(ref) for ref in candidate.get("driver_refs") or [])
    for item in ((modules.get("milestone_coverage") or {})
                 .get("milestones") or []):
        known.update(str(ref) for ref in item.get("cost_driver_refs") or [])
    validation = plan_of(canonical).get("validation") or {}
    for key in ("errors", "warnings"):
        for entry in validation.get(key) or []:
            known.add(str(entry.get("code")))
            known.update(str(ref) for ref in entry.get("affected_refs") or [])
    condition = (scenarios_of(canonical).get("coverage") or {}) \
        .get("proposed_condition_ref")
    if condition:
        known.add(str(condition))
    known.update(COINED_IDS)
    known.update(TYPED_ID_RE.findall(POLICY_REF))
    return frozenset(known)


def declared_literals(request):
    """I letterali numerici che la prosa PUO' citare: ciascuno e' un valore
    emesso dal documento e tracciato da `provenance[]`."""
    declared = []
    declared.append((str(request["requested_capital"]["amount"]),
                     "requested_capital.amount"))
    declared.append((str(request["capital_requirement"]["modeled_need_amount"]),
                     "capital_requirement.modeled_need_amount"))
    declared.append((str(request["sufficiency"]["residual_gap"]),
                     "sufficiency.residual_gap"))
    declared.append((str(request["runway"]["after_financing"]["periods"]),
                     "runway.after_financing.periods"))
    declared.append((str(request["horizon"]["horizon_periods"]),
                     "horizon.horizon_periods"))
    before = request["runway"]["before_financing"]
    if before.get("runway_to_zero") is not None:
        declared.append((str(before["runway_to_zero"]),
                         "runway.before_financing.runway_to_zero"))
    # Sul ramo PRIMARIO il runway ante-finanziamento e' citato
    # ALLA MISURA SELEZIONATA, `runway_to_buffer`, oltre che a cassa esaurita.
    if request["runway"].get("measure") == "to_buffer" and \
            before.get("runway_to_buffer") not in (None, NOT_APPLICABLE):
        declared.append((str(before["runway_to_buffer"]),
                         "runway.before_financing.runway_to_buffer"))
    for index, entry in enumerate(request["use_of_proceeds"]):
        declared.append((str(entry["amount"]),
                         f"use_of_proceeds[{index}].amount"))
        declared.append((str(entry["percentage"]),
                         f"use_of_proceeds[{index}].percentage"))
    declared.append((str(
        request["dependencies_and_assumptions"]["unvalidated_count"]),
        "dependencies_and_assumptions.unvalidated_count"))
    return declared


def unresolved_line(item):
    """La riga di elenco con cui `render_request` rende una voce irrisolta."""
    return f"- `{item['severity']}` `{item['code']}`: {item['message']}"


def authoritative_verbatim(canonical):
    """La SOLA prosa copiata verbatim che la
    scansione del derivato puo' esentare: le voci di validazione irrisolte
    dello Stage 10, lette dal canonico dello STAGE 10, cioe' dall'autorita',
    e MAI dal documento sotto validazione. Portano le cifre di chi le ha
    scritte a monte (un rimando, una data), e riportarle fedelmente non e'
    emettere un numero.

    Ciascuna e' esente solo come BLOCCO INTERO, la propria riga di elenco
    identica alla resa di `render_request`: un messaggio riscritto, una
    domanda di decisione o un codice che il candidate possiede non sottraggono
    nulla, ne' alla propria riga ne' ad alcun paragrafo. Le domande di
    decisione che questo stage scrive non portano cifre, e non hanno bisogno
    di alcuna esenzione."""
    exempt = set()
    for item in project_unresolved(canonical):
        for block in prose_blocks(unresolved_line(item)):
            exempt.add(normalized(block))
    return frozenset(exempt)


def authoritative_request(canonical, project, report):
    """La proiezione AUTORITATIVA: la STESSA
    `build_document` del costruttore, sul SOLO canonico dello Stage 10 e sui
    registri del progetto, mai sul documento sotto validazione. E' cio' che
    il documento DEVE essere: i suoi letterali numerici sono gli unici che la
    prosa puo' citare, e i suoi valori sono quelli contro cui ogni campo
    numerico emesso e' confrontato (`check_entries`, `check_projection`,
    `check_declared_literals`).

    Se il canonico dello Stage 10 non porta una proiezione, il rifiuto e'
    ATTRIBUITO e nessun letterale e' autoritativo: fail-closed."""
    try:
        return build_document(canonical, project,
                              strict=False)["funding_request"]
    except BuildRefusal as exc:
        report.add_error(
            exc.code, ref=exc.ref or "funding_request",
            message="la proiezione AUTORITATIVA della funding request non e' "
                    "ricostruibile dal canonico dello Stage 10, quindi nessun "
                    f"valore emesso e' verificabile: {exc.message}")
        return None


def runway_prose(request):
    """Runway e sufficienza ALLA MISURA SELEZIONATA dalla politica di
    capitalizzazione (`funding_gap_to_buffer`, oppure il fallback
    `funding_gap_to_zero`): sul ramo primario il runway ante-finanziamento
    e' citato a `to_buffer`; sul fallback il lettore legge che la richiesta
    e' costruita a cassa zero e che nessuna soglia di buffer e' la base."""
    runway = request["runway"]
    before = runway["before_financing"]
    measure = runway["measure"]
    buffer_state = request["capital_requirement"]["buffer_component"]["state"]
    if measure == "to_buffer":
        opening = (f"Il runway ante-finanziamento vale "
                   f"{before['runway_to_buffer']} periodi alla misura "
                   "to_buffer, cioe' rispettando la soglia di cassa "
                   f"dichiarata, e {before['runway_to_zero']} periodi prima "
                   "dell'esaurimento della cassa (to_zero).")
    elif buffer_state == NOT_APPLICABLE:
        opening = (f"Il runway ante-finanziamento vale "
                   f"{before['runway_to_zero']} periodi alla misura to_zero. "
                   f"La richiesta e' costruita {FALLBACK_DISCLOSURE}: la "
                   "misura primaria funding_gap_to_buffer non e' applicabile, "
                   "nessuna soglia di buffer era disponibile nel canonico "
                   "(buffer_component NOT_APPLICABLE) e il fallback dichiarato "
                   "e' funding_gap_to_zero.")
    else:
        opening = (f"Il runway ante-finanziamento vale "
                   f"{before['runway_to_zero']} periodi alla misura to_zero. "
                   f"La richiesta e' costruita {FALLBACK_DISCLOSURE}: la "
                   "soglia di buffer non e' usata come base (buffer_component "
                   f"{buffer_state}) e il fallback dichiarato e' "
                   "funding_gap_to_zero.")
    return (f"{opening} Con il capitale richiesto il runway finanziato, alla "
            f"misura {measure}, raggiunge {runway['after_financing']['periods']}"
            f" periodi su un orizzonte di "
            f"{request['horizon']['horizon_periods']} periodi. Il gap residuo "
            f"e' di {request['sufficiency']['residual_gap']} "
            f"{request['requested_capital']['currency']} ed e' esposto, mai "
            "nascosto.")


def milestone_prose(request, milestone_status):
    """Il collegamento fra capitale e milestone, o la sua ASSENZA
    dichiarata. Nessuna data e nessun importo sono citati: una milestone
    non riceve una cifra che il canonico non porta."""
    entries = request["milestone_financing"]
    if not entries:
        return ("Nessuna milestone della roadmap e' collegata al capitale "
                "richiesto: il modulo milestone_coverage del piano "
                f"finanziario e' {milestone_status} e il collegamento non e' "
                f"stimato (decisione {MILESTONE_DECISION}).")
    funded = [str(entry["milestone_ref"]) for entry in entries
              if entry["financed_by"] == "requested_capital"]
    unfunded = [str(entry["milestone_ref"]) for entry in entries
                if entry["financed_by"] != "requested_capital"]
    beyond = [str(entry["milestone_ref"]) for entry in entries
              if entry["out_of_horizon"]]
    return (f"Milestone finanziate dal capitale richiesto: "
            f"{', '.join(funded) or 'nessuna'}. Milestone NON finanziate: "
            f"{', '.join(unfunded) or 'nessuna'}. Fuori orizzonte, senza data "
            f"e con costo fuori dai totali: {', '.join(beyond) or 'nessuna'}.")


def build_narrative(request, milestone_status=NOT_APPLICABLE):
    """La narrativa NON calcola: cita solo letterali gia' emessi, e ciascuno e'
    dichiarato in `numeric_refs[]`."""
    capital = request["capital_requirement"]
    requested = request["requested_capital"]
    governance = request["governance"]
    coverage = request["scenario_sensitivity"]["coverage_level"]
    scenario_prose = (
        "La copertura di scenario del canonico e' NULLA: la richiesta e' "
        "formulata sul SOLO scenario BASE e non e' validata su scenari "
        "avversi. Non abbiamo dati per testare il peggio; questo non "
        "significa che il peggio non cambi nulla."
        if coverage == "none" else
        f"La copertura di scenario del canonico e' {coverage}: gli scenari "
        "avversi esistono, ma nessun portatore canonico espone un fabbisogno "
        "SCALARE per scenario, e non ne viene stimato alcuno.")
    sections = [
        {"section_id": "FR-S1", "title": "Capitale richiesto",
         "body": f"Il capitale richiesto e' di {requested['amount']} "
                 f"{requested['currency']}, pari al fabbisogno modellato di "
                 f"{capital['modeled_need_amount']} {requested['currency']} "
                 f"letto dal path canonico {capital['modeled_need_ref']}. "
                 f"L'arrotondamento applicato e' {requested['rounding_applied']}"
                 f" e la politica di capitalizzazione e' dichiarata in "
                 f"capital_requirement.policy_ref."},
        {"section_id": "FR-S2", "title": "Impiego dei proventi",
         "body": "".join([
             "L'impiego dei proventi e' ripartito sulle sole categorie "
             "eleggibili dichiarate dal canonico. ",
             " ".join(
                 f"{entry['label']}: {entry['amount']} "
                 f"{requested['currency']} ({entry['percentage']}%)."
                 for entry in request["use_of_proceeds"])])},
        {"section_id": "FR-S3", "title": "Runway e sufficienza",
         "body": runway_prose(request)},
        {"section_id": "FR-S4", "title": "Scenari", "body": scenario_prose},
        {"section_id": "FR-S5", "title": "Dipendenze e assunzioni",
         "body": f"Le assunzioni non validate a supporto della richiesta sono "
                 f"{request['dependencies_and_assumptions']['unvalidated_count']}"
                 f". Lo stato propagato dal piano finanziario e' "
                 f"{governance['propagated_state']}: il documento lo PROPAGA e "
                 f"non lo lava. Strumento, valutazione, diluizione, dimensione "
                 f"del round e condizioni NON sono prodotti qui e restano "
                 f"decisioni aperte dichiarate."},
        {"section_id": "FR-S6", "title": "Milestone",
         "body": milestone_prose(request, milestone_status)},
    ]
    numeric_refs = [{"literal": literal, "field": field}
                    for literal, field in declared_literals(request)]
    return {"sections": sections, "numeric_refs": numeric_refs}


def render_request(document):
    """`funding-request.md` — DERIVATO. Ogni numero e' un letterale gia'
    emesso dal canonico dello Stage 11, mai una cifra calcolata qui."""
    request = document["funding_request"]
    lines = ["# Funding request", "",
             f"- Stage sorgente: `{request['source']['stage']}`",
             f"- Documento canonico: `{request['source']['canonical_path']}`",
             "- `canonical_source_checksum`: "
             f"`{request['source']['canonical_source_checksum']}`",
             f"- Stato propagato: `{request['governance']['propagated_state']}`",
             ""]
    for section in request["narrative"]["sections"]:
        lines.append(f"## {section['title']}")
        lines.append("")
        lines.append(section["body"])
        lines.append("")
    lines.append("## Voci di validazione irrisolte")
    lines.append("")
    if not request["unresolved_validation_items"]:
        lines.append("Nessuna voce irrisolta e' riportata dal canonico.")
    for item in request["unresolved_validation_items"]:
        lines.append(unresolved_line(item))
    lines.append("")
    lines.append("## Decisioni richieste")
    lines.append("")
    for item in request["dependencies_and_assumptions"]["decision_needed"]:
        blocking = "bloccante" if item["blocking"] else "non bloccante"
        lines.append(f"- `{item['code']}` ({blocking}): {item['question']}")
    lines.append("")
    return "\n".join(lines)


def build_handoff(document):
    request = document["funding_request"]
    lines = ["# Handoff — Stage 11 Funding request", "",
             f"next_action: revisione della funding request da parte del "
             f"lettore dichiarato in reader_context.",
             "",
             f"- Capitale richiesto: {request['requested_capital']['amount']} "
             f"{request['requested_capital']['currency']}",
             f"- Misura di base: `{request['capital_requirement']['modeled_need_ref']}`",
             f"- Stato propagato: `{request['governance']['propagated_state']}`",
             f"- Gap residuo dichiarato: "
             f"{request['sufficiency']['residual_gap']}",
             "",
             "Nessuna valutazione, diluizione, strumento, prezzo o termine e' "
             "prodotto da questo stage: i termini ignoti sono dichiarati in "
             "dependencies_and_assumptions.decision_needed.",
             "",
             "Decisioni aperte dichiarate:",
             ""]
    for item in request["dependencies_and_assumptions"]["decision_needed"]:
        blocking = "bloccante" if item["blocking"] else "non bloccante"
        lines.append(f"- `{item['code']}` ({blocking})")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# PUBLISHER ATOMICO A DUE LIVELLI — nessun output parziale
# --------------------------------------------------------------------------


def fail_point():
    return os.environ.get(FAIL_ENV, "")


def publish(targets):
    """ATOMICITA' D'INSIEME in DUE livelli.

    Livello 1 — STAGING: ogni contenuto e' costruito IN MEMORIA e scritto in un
    file temporaneo NELLA STESSA directory del bersaglio, con `flush` +
    `fsync`. Nessun bersaglio finale e' toccato.
    Livello 2 — PUBBLICAZIONE: i temporanei sono portati sul nome finale con
    `os.replace`, ATOMICO per singolo file.

    Un fallimento a QUALUNQUE punto lascia lo stato precedente INTATTO: i
    bersagli gia' pubblicati sono RIPRISTINATI dai byte di backup, quelli che
    non esistevano sono rimossi, e nessun temporaneo orfano sopravvive. Non e'
    MAI ammesso aprire un bersaglio finale in scrittura e riempirlo
    progressivamente.
    """
    injected = fail_point()
    staged = []
    backups = {}
    published = []
    try:
        for path, text in targets:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            backups[target] = target.read_bytes() if target.is_file() else None
            handle = tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n",
                dir=str(target.parent), prefix=".fr-", suffix=".part",
                delete=False)
            temporary = Path(handle.name)
            staged.append((temporary, target))
            try:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                handle.close()
            if injected == "staging" and len(staged) == 1:
                raise BuildRefusal(
                    CODE_PARTIAL_OUTPUT,
                    "fallimento INIETTATO durante lo staging: nessun bersaglio "
                    "finale e' stato toccato")
        for temporary, target in staged:
            os.replace(str(temporary), str(target))
            published.append(target)
            if injected == "after_first_publish" and len(published) == 1:
                raise BuildRefusal(
                    CODE_PARTIAL_OUTPUT,
                    "fallimento INIETTATO dopo la pubblicazione del primo "
                    "file: lo stato precedente e' ripristinato integralmente e "
                    "nessun output parziale sopravvive")
    except BaseException:
        for target in published:
            original = backups.get(target)
            if original is None:
                if target.is_file():
                    target.unlink()
            else:
                target.write_bytes(original)
        for temporary, _ in staged:
            if temporary.exists():
                temporary.unlink()
        raise
    return [str(target) for _, target in staged]


def resolve_candidate(project, tx):
    if not tx or "/" in tx or "\\" in tx or tx in (".", ".."):
        raise fw.ValidatorUsageError(
            f"--tx deve essere un singolo segmento di path: {tx!r}")
    return Path(project).joinpath(STAGE11, WORKING_DIR, tx)


def run_build(args):
    """Modalita' COSTRUZIONE. NON e' il percorso del Transaction Manager."""
    report = fw.Report(VALIDATOR_NAME, STAGE11, "build")
    project = Path(args.project)
    if not project.is_dir():
        raise fw.ValidatorUsageError(f"project dir inesistente: {args.project}")
    candidate = resolve_candidate(project, args.tx)
    try:
        inputs = stage10_inputs(project, args.canonical_input)
        document = build_document(inputs["document"], project)
        targets = [
            (candidate.joinpath(CANONICAL_NAME), canonical_json(document)),
            (candidate.joinpath(HANDOFF_NAME), build_handoff(document)),
            (project.joinpath(STAGE11, REQUEST_NAME),
             render_request(document)),
        ]
        written = publish(targets)
    except BuildRefusal as exc:
        if exc.details:
            for ref, message in exc.details:
                report.add_error(exc.code, ref=ref, message=message)
        else:
            report.add_error(exc.code, ref=exc.ref, message=exc.message)
        print(report.to_json())
        return fw.EXIT_CANDIDATE_INVALID
    except fw.CanonicalStateError as exc:
        report.add_error("corrupted_state", message=str(exc))
        print(report.to_json())
        return fw.EXIT_STATE
    report.add_check("funding_request_built", "PASS",
                     message=f"artefatti pubblicati: {', '.join(written)}")
    print(report.to_json())
    return fw.EXIT_OK


# --------------------------------------------------------------------------
# VALIDAZIONE — egress e impact
# --------------------------------------------------------------------------


def check_schema(document, report):
    try:
        import jsonschema
    except ImportError as exc:
        raise fw.ValidatorUsageError(
            f"jsonschema non importabile: la validazione a schema della "
            f"funding request non e' eseguibile ({exc})")
    schema = load_json(SCHEMA_PATH, "schema della funding request")
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document),
                    key=lambda err: (list(map(str, err.absolute_path)),
                                     err.message))
    for error in errors[:20]:
        pointer = "/".join(map(str, error.absolute_path)) or "<root>"
        report.add_error(CODE_SCHEMA, ref=pointer, message=error.message)
    return not errors


def check_no_recompute(report):
    """Fronte STATICO del divieto di ricalcolo, con AUTO-SONDA."""
    source = Path(__file__).read_text(encoding="utf-8")
    findings = scan_forbidden_recomputation(source, label=Path(__file__).name)
    for finding in findings:
        report.add_error(CODE_NON_CANONICAL, message=finding)
    if not self_probe_findings():
        report.add_error(
            CODE_NON_CANONICAL,
            message="AUTO-SONDA FALLITA: il rilevatore statico non rileva le "
                    "violazioni del sorgente sintetico — e' VACUO, e una "
                    "scansione pulita non proverebbe nulla")
    report.add_check("no_recompute_scan",
                     "FAIL" if findings else "PASS",
                     actual=str(len(findings)),
                     message="scansione del divieto di ricalcolo fuori "
                             "dall'elenco chiuso delle derivazioni")


def check_canonical_only(request, canonical, report, authority=None):
    """Fronte COMPORTAMENTALE della regola «la funding request e' una
    proiezione»: ogni valore emesso che NON sia una DERIVAZIONE dichiarata
    coincide col valore del proprio path.

    QUALI campi siano derivazioni, e da quale
    path ciascuno si legga, lo fissa la proiezione AUTORITATIVA, non il
    documento sotto validazione: una `derivation` AUTO-dichiarata non esenta
    un campo dal confronto col proprio path, e un `canonical_path` scelto dal
    documento non ne sposta la sorgente. Ogni voce e' quella AUTORITATIVA
    del proprio campo — path, derivazione, path di derivazione, periodo,
    checksum — salvo le etichette descrittive `unit`, `scenario`, `currency`
    (`PROVENANCE_DESCRIPTIVE`); e nessuna voce autoritativa manca."""
    authorized = {str(entry.get("field")): entry for entry in
                  ((authority or {}).get("provenance") or [])}
    emitted_fields = {str(entry.get("field") or "") for entry in
                      request.get("provenance") or []}
    for field in sorted(authorized):
        if field not in emitted_fields:
            report.add_error(
                CODE_PROVENANCE, ref=field,
                message="la voce di provenance che la proiezione AUTORITATIVA "
                        "emette per questo campo e' ASSENTE")
    for entry in request.get("provenance") or []:
        field = str(entry.get("field") or "")
        path = str(entry.get("canonical_path") or "")
        derivation = entry.get("derivation")
        if authority is not None:
            declared = authorized.get(field)
            if declared is None:
                report.add_error(
                    CODE_NON_CANONICAL, ref=field,
                    message="voce di provenance per un campo che la "
                            "proiezione AUTORITATIVA non emette")
                continue
            differing = sorted(
                key for key in set(entry) | set(declared)
                if key not in PROVENANCE_DESCRIPTIVE and json.dumps(
                    entry.get(key), sort_keys=True) != json.dumps(
                    declared.get(key), sort_keys=True))
            if differing:
                report.add_error(
                    CODE_NON_CANONICAL, ref=field,
                    message="provenienza AUTO-dichiarata: il documento sotto "
                            "validazione non stabilisce da se' quali valori "
                            "siano derivazioni, da quale path si leggano, ne' "
                            f"con quali metadati ({', '.join(differing)})",
                    expected=json.dumps(declared, sort_keys=True),
                    actual=json.dumps(entry, sort_keys=True))
            derivation = declared.get("derivation")
            path = str(declared.get("canonical_path") or "")
        if derivation:
            continue
        if not path:
            report.add_error(
                CODE_PROVENANCE, ref=field,
                message="voce di provenance senza canonical_path")
            continue
        found, expected = resolve_path(canonical, path)
        if not found:
            report.add_error(
                CODE_NON_CANONICAL, ref=field,
                message=f"il path canonico dichiarato {path} NON risolve nel "
                        "canonico dello Stage 10")
            continue
        found_emitted, emitted = resolve_path({"funding_request": request},
                                              f"funding_request.{field}")
        if not found_emitted:
            continue
        if str(emitted) != str(expected):
            report.add_error(
                CODE_NON_CANONICAL, ref=field,
                message=f"il valore emesso {emitted!r} non coincide col valore "
                        f"{expected!r} del path canonico dichiarato {path}: e' "
                        "un ricalcolo, non una proiezione",
                expected=str(expected), actual=str(emitted))


def check_policy(request, report):
    capital = request.get("capital_requirement") or {}
    for key in ("modeled_need_ref", "buffer_component",
                "contingency_component", "timing_granularity", "policy_ref"):
        if not capital.get(key):
            report.add_error(
                CODE_POLICY_UNDECLARED, ref=f"capital_requirement.{key}",
                message=f"la politica di capitalizzazione non dichiara {key}: "
                        "un importo senza politica dichiarata e' irricevibile")
    requested = request.get("requested_capital") or {}
    if not requested.get("policy_ref"):
        report.add_error(
            CODE_POLICY_UNDECLARED, ref="requested_capital.policy_ref",
            message="il capitale richiesto non dichiara la propria politica")
    if requested.get("rounding_applied") is None:
        report.add_error(
            CODE_POLICY_UNDECLARED, ref="requested_capital.rounding_applied",
            message="l'arrotondamento e' il quinto componente della politica e "
                    "va DICHIARATO")
    buffer_component = capital.get("buffer_component") or {}
    if buffer_component.get("state") not in ("included_in_base",
                                             NOT_APPLICABLE, "absent"):
        report.add_error(
            CODE_POLICY_UNDECLARED, ref="capital_requirement.buffer_component",
            message="buffer_component ammette TRE stati chiusi e "
                    f"nessun quarto: {buffer_component.get('state')!r}")


def check_capital(request, canonical, report, authority=None):
    capital = request.get("capital_requirement") or {}
    requested = request.get("requested_capital") or {}
    # La scomposizione e' quella che la politica DICHIARATA produce,
    # ricostruita dal validator: il buffer gia' incluso nella base e'
    # esposto senza essere sommato, la contingency e' ASSENTE e nessuna
    # regola ne ammette un'altra. Addendi, atteso, osservato e residuo
    # dichiarati dal documento sotto validazione non riconciliano nulla da se'.
    # Buffer e contingency sono vincolati da `check_projection`.
    if authority is not None:
        policy = authority.get("capital_requirement") or {}
        if json.dumps(capital.get("reconciliation"), sort_keys=True) != \
                json.dumps(policy.get("reconciliation"), sort_keys=True):
            report.add_error(
                CODE_CAPITAL_RECON, ref="capital_requirement.reconciliation",
                message="la riconciliazione dichiarata non e' quella della "
                        "politica di capitalizzazione DICHIARATA sul "
                        "fabbisogno modellato: addendi, atteso, osservato e "
                        "residuo sono ricostruiti dal validator",
                expected=json.dumps(policy.get("reconciliation"),
                                    sort_keys=True),
                actual=json.dumps(capital.get("reconciliation"),
                                  sort_keys=True))
    need_ref = str(capital.get("modeled_need_ref") or "")
    if need_ref not in (NEED_PRIMARY, NEED_FALLBACK):
        report.add_error(
            CODE_CAPITAL_RECON, ref="capital_requirement.modeled_need_ref",
            message=f"modeled_need_ref deve NOMINARE uno dei DUE path della "
                    f"politica di capitalizzazione: {need_ref!r}")
    else:
        found, primary = resolve_path(canonical, NEED_PRIMARY)
        if need_ref == NEED_FALLBACK and found and primary != NOT_APPLICABLE:
            report.add_error(
                CODE_CAPITAL_RECON, ref="capital_requirement.modeled_need_ref",
                message="il FALLBACK e' ammesso SOLO E SOLTANTO quando "
                        "funding_gap_to_buffer vale NOT_APPLICABLE")
    recon = capital.get("reconciliation") or {}
    for key in ("expected", "actual", "residual", "tolerance", "status"):
        if key not in recon:
            report.add_error(
                CODE_CAPITAL_RECON, ref="capital_requirement.reconciliation",
                message=f"la riconciliazione non riporta {key}")
    addends = recon.get("addends") or []
    # Il buffer GIA' INCLUSO nella base e' un'ESPOSIZIONE:
    # comparire fra gli addendi SOMMATI sarebbe un DOPPIO CONTEGGIO, cioe' un
    # FAIL, non un arrotondamento.
    if (capital.get("buffer_component") or {}).get("state") == \
            "included_in_base":
        for item in addends:
            if item.get("name") != "buffer_component":
                continue
            if item.get("role") == "exposure":
                continue
            report.add_error(
                CODE_CAPITAL_RECON, ref="capital_requirement.reconciliation",
                message="il buffer e' GIA' INCLUSO nella base e compare fra "
                        "gli addendi SOMMATI: e' un doppio conteggio",
                actual=str(item.get("amount")))
    total = sum_amounts([as_decimal(item.get("amount")) for item in addends
                         if item.get("role") in ("base", "addend")])
    actual = as_decimal(requested.get("amount"))
    if actual is None:
        report.add_error(
            CODE_CAPITAL_RECON, ref="requested_capital.amount",
            message="il capitale richiesto non e' un importo")
        return
    if not amounts_within(total, actual, TOLERANCE_EUR):
        report.add_error(
            CODE_CAPITAL_RECON, ref="requested_capital.amount",
            message="la scomposizione NOMINATA non quadra col capitale "
                    f"richiesto entro {TOLERANCE_EUR} EUR",
            expected=str(total), actual=str(actual))
    declared_expected = as_decimal(recon.get("expected"))
    if declared_expected is not None and \
            not amounts_within(declared_expected, total, TOLERANCE_EUR):
        report.add_error(
            CODE_CAPITAL_RECON, ref="capital_requirement.reconciliation",
            message="l'atteso dichiarato diverge dalla somma degli addendi "
                    "NOMINATI",
            expected=str(total), actual=str(declared_expected))
    report.add_check("capital_reconciliation",
                     "PASS" if amounts_within(total, actual, TOLERANCE_EUR)
                     else "FAIL", expected=str(total), actual=str(actual),
                     residual=str(recon.get("residual")),
                     tolerance=TOLERANCE_EUR)


def check_entries(entries, authority, report):
    """Una voce d'impiego sostiene la tracciabilita'
    SOLO se e' essa stessa valida: la riconciliazione degli aggregati e'
    necessaria ma NON sufficiente. Ogni voce porta un importo FINITO e non
    negativo e una quota FINITA in `[0, 100]`, entro le tolleranze dichiarate
    (`EUR 0.01`, `ratio 1e-6`): lo zero resta lecito, ed e' la quota di una
    categoria a peso nullo, e il residuo di arrotondamento che l'ultima
    categoria della ripartizione esatta porta (`-1E-23`) non e' un
    prelievo; ogni candidato e' allocato UNA volta sola, con la categoria e
    l'etichetta del candidato stesso (`fr_category_not_traceable`); e
    importo e quota sono, nella loro resa, quelli che la regola DICHIARATA
    (`ALLOCATION_RULE`) assegna al candidato nella proiezione
    AUTORITATIVA. Una voce negativa compensata da una positiva, una
    voce non numerica che la somma ignora, o una ripartizione deviata a somma
    invariata sono percio' respinte, e i loro numeri non diventano letterali
    dichiarati."""
    expected = {str(entry.get("candidate_ref")): entry for entry in
                ((authority or {}).get("use_of_proceeds") or [])}
    zero = as_decimal("0")
    hundred = as_decimal("100")
    seen = set()
    for index, entry in enumerate(entries):
        ref = f"use_of_proceeds[{index}]"
        amount = as_decimal(entry.get("amount"))
        if amount is None:
            report.add_error(
                CODE_ALLOCATION_SUM, ref=ref,
                message="l'importo della voce non e' un importo finito: una "
                        "voce che la somma ignora non e' lecita per questo",
                actual=str(entry.get("amount")))
        elif amount < 0 and not amounts_within(amount, zero, TOLERANCE_EUR):
            report.add_error(
                CODE_ALLOCATION_SUM, ref=ref,
                message="voce d'impiego NEGATIVA: un impiego non e' un "
                        "prelievo, e una voce compensata da un'altra non "
                        "diventa lecita perche' la somma quadra",
                actual=str(entry.get("amount")))
        share = as_decimal(entry.get("percentage"))
        if share is None:
            report.add_error(
                CODE_PERCENTAGE_SUM, ref=ref,
                message="la quota della voce non e' un numero finito",
                actual=str(entry.get("percentage")))
        elif (share < 0 and not amounts_within(share, zero,
                                               TOLERANCE_RATIO)) or \
                (share > 100 and not amounts_within(share, hundred,
                                                    TOLERANCE_RATIO)):
            report.add_error(
                CODE_PERCENTAGE_SUM, ref=ref,
                message="quota d'impiego fuori da [0, 100]: una quota "
                        "compensata da un'altra non diventa lecita perche' la "
                        "somma vale 100",
                actual=str(entry.get("percentage")))
        candidate_ref = str(entry.get("candidate_ref") or "")
        if candidate_ref in seen:
            report.add_error(
                CODE_CATEGORY, ref=ref,
                message=f"il candidato {candidate_ref!r} e' allocato piu' "
                        "volte: ogni categoria eleggibile ha UNA sola voce")
        seen.add(candidate_ref)
        target = expected.get(candidate_ref)
        if target is None:
            continue
        for key in ("category_id", "label"):
            if str(entry.get(key)) != str(target.get(key)):
                report.add_error(
                    CODE_CATEGORY, ref=ref,
                    message=f"la voce allocata al candidato {candidate_ref!r} "
                            f"dichiara un altro {key}: categoria ed etichetta "
                            "di una voce sono quelle del candidato che la "
                            "sostiene, e l'importo non si attribuisce ad altro",
                    expected=str(target.get(key)), actual=str(entry.get(key)))
        if str(entry.get("amount")) != str(target.get("amount")):
            report.add_error(
                CODE_ALLOCATION_SUM, ref=ref,
                message=f"l'importo di {candidate_ref!r} non e' la quota che "
                        "la regola DICHIARATA assegna al candidato sul "
                        "capitale che la politica fissa",
                expected=str(target.get("amount")),
                actual=str(entry.get("amount")))
        if str(entry.get("percentage")) != str(target.get("percentage")):
            report.add_error(
                CODE_PERCENTAGE_SUM, ref=ref,
                message=f"la quota di {candidate_ref!r} non e' quella che la "
                        "regola DICHIARATA assegna al candidato",
                expected=str(target.get("percentage")),
                actual=str(entry.get("percentage")))
    for candidate_ref in sorted(expected):
        if candidate_ref not in seen:
            report.add_error(
                CODE_CATEGORY, ref="use_of_proceeds",
                message=f"il candidato canonico {candidate_ref!r} non ha "
                        "alcuna voce d'impiego")


def check_allocation(request, canonical, report, authority=None):
    entries = request.get("use_of_proceeds") or []
    check_entries(entries, authority, report)
    requested = as_decimal((request.get("requested_capital") or {})
                           .get("amount"))
    amounts = [as_decimal(entry.get("amount")) for entry in entries]
    total = sum_amounts(amounts)
    if requested is not None and not amounts_within(total, requested,
                                                    TOLERANCE_EUR):
        report.add_error(
            CODE_ALLOCATION_SUM, ref="use_of_proceeds",
            message="la somma degli impieghi non coincide col capitale "
                    f"richiesto entro {TOLERANCE_EUR} EUR",
            expected=str(requested), actual=str(total))
    percentages = sum_amounts([as_decimal(entry.get("percentage"))
                               for entry in entries])
    if not amounts_within(percentages, as_decimal("100"), TOLERANCE_RATIO):
        report.add_error(
            CODE_PERCENTAGE_SUM, ref="use_of_proceeds",
            message="la somma delle percentuali di impiego non vale 100 entro "
                    f"{TOLERANCE_RATIO}",
            expected="100", actual=str(percentages))
    candidates = {str(item.get("category_id")) for item in
                  ((modules_of(canonical).get("funding_gap") or {})
                   .get("use_of_proceeds_candidates") or [])}
    driver_refs = {str(item.get("category_id")): set(item.get("driver_refs")
                                                     or [])
                   for item in ((modules_of(canonical).get("funding_gap") or {})
                                .get("use_of_proceeds_candidates") or [])}
    for index, entry in enumerate(entries):
        candidate_ref = str(entry.get("candidate_ref") or "")
        if candidate_ref not in candidates:
            report.add_error(
                CODE_CATEGORY, ref=f"use_of_proceeds[{index}]",
                message=f"la categoria {candidate_ref!r} non risale ad alcun "
                        "category_id di use_of_proceeds_candidates")
            continue
        declared = set(entry.get("driver_refs") or [])
        if declared != driver_refs.get(candidate_ref, set()):
            report.add_error(
                CODE_CATEGORY, ref=f"use_of_proceeds[{index}]",
                message=f"i driver_refs della categoria {candidate_ref} non "
                        "coincidono con quelli del candidato canonico",
                expected=str(sorted(driver_refs.get(candidate_ref, set()))),
                actual=str(sorted(declared)))
    report.add_check("allocation_sum", "PASS" if amounts_within(
        total, requested, TOLERANCE_EUR) else "FAIL",
        expected=str(requested), actual=str(total), tolerance=TOLERANCE_EUR)


def check_horizon(request, canonical, report):
    calendar = calendar_of(canonical)
    horizon = request.get("horizon") or {}
    for key in ("anchor_date", "frequency", "horizon_periods"):
        if horizon.get(key) != calendar.get(key):
            report.add_error(
                CODE_HORIZON, ref=f"horizon.{key}",
                message=f"l'orizzonte dichiarato diverge da results.calendar "
                        f"sul campo {key}",
                expected=str(calendar.get(key)), actual=str(horizon.get(key)))


def check_runway(request, canonical, report):
    runway = request.get("runway") or {}
    metrics = (modules_of(canonical).get("runway") or {}).get("metrics") or {}
    before = runway.get("before_financing") or {}
    for key in ("runway_to_zero", "runway_to_buffer"):
        if key not in before:
            report.add_error(
                CODE_RUNWAY_BEFORE, ref=f"runway.before_financing.{key}",
                message=f"{key} assente: runway_to_zero e runway_to_buffer "
                        "restano DUE grandezze distinte, e collassarle e' un "
                        "difetto, non una semplificazione")
            continue
        if str(before.get(key)) != str(metrics.get(key)):
            report.add_error(
                CODE_RUNWAY_BEFORE, ref=f"runway.before_financing.{key}",
                message=f"{key} non coincide con la metrica canonica",
                expected=str(metrics.get(key)), actual=str(before.get(key)))
    measure = str(runway.get("measure") or "")
    need_ref = str((request.get("capital_requirement") or {})
                   .get("modeled_need_ref") or "")
    expected_measure = "to_buffer" if need_ref == NEED_PRIMARY else "to_zero"
    if measure != expected_measure:
        report.add_error(
            CODE_RUNWAY_BEFORE, ref="runway.measure",
            message="runway.measure deve essere COERENTE con la misura di base "
                    "selezionata dalla politica di capitalizzazione",
            expected=expected_measure, actual=measure)
    if expected_measure == "to_zero":
        # Quando scatta il fallback a `funding_gap_to_zero`, `sufficiency` e
        # la prosa per il lettore DICHIARANO che la richiesta e' costruita a
        # cassa zero; nasconderlo e' un gap nascosto
        # (`fr_residual_gap_hidden`).
        basis = str((request.get("sufficiency") or {}).get("basis") or "")
        bodies = [str(section.get("body") or "") for section in
                  ((request.get("narrative") or {}).get("sections") or [])]
        if FALLBACK_DISCLOSURE not in basis or \
                not any(FALLBACK_DISCLOSURE in body for body in bodies):
            report.add_error(
                CODE_RESIDUAL_GAP, ref="sufficiency.basis",
                message="il fallback a funding_gap_to_zero e' scattato ma "
                        "sufficiency e "
                        "la narrativa non dichiarano che la richiesta e' "
                        f"costruita {FALLBACK_DISCLOSURE} e che nessuna soglia "
                        "di buffer e' la base: e' informazione materiale per "
                        "il lettore, e nasconderla e' un gap residuo "
                        "nascosto")

    series = (modules_of(canonical).get("cash_flow") or {}).get("series") or {}
    horizon = calendar_of(canonical).get("horizon_periods")
    # DUE relazioni, entrambe necessarie. Qui il
    # runway finanziato e il gap residuo sono ricostruiti al capitale che il
    # documento DICHIARA: un gap nullo su un capitale che non copre il
    # fabbisogno e' un gap NASCOSTO (`fr_residual_gap_hidden`). Che quel
    # capitale sia quello della politica, e che runway e gap siano quelli
    # della proiezione AUTORITATIVA, lo misura `check_declared_literals`
    # (`fr_capital_reconciliation_failed`): un capitale
    # parziale reso coerente con un gap onesto non ha portatore canonico.
    requested = as_decimal((request.get("requested_capital") or {})
                           .get("amount"))
    limit = as_decimal("0")
    if expected_measure == "to_buffer":
        limit = as_decimal(
            ((modules_of(canonical).get("cash_buffer") or {}).get("metrics")
             or {}).get("threshold")) or as_decimal("0")
    if requested is None or horizon is None:
        return
    expected_after = derive_runway_after(series, horizon, requested, limit)
    after = runway.get("after_financing") or {}
    if expected_after is not None and after.get("periods") != expected_after:
        report.add_error(
            CODE_RUNWAY_AFTER, ref="runway.after_financing.periods",
            message="il runway finanziato non riconcilia al flusso di cassa "
                    "canonico, periodo per periodo, con tolleranza count "
                    "ESATTA",
            expected=str(expected_after), actual=str(after.get("periods")))
    report.add_check("runway_after_financing",
                     "PASS" if after.get("periods") == expected_after
                     else "FAIL", expected=str(expected_after),
                     actual=str(after.get("periods")),
                     tolerance=TOLERANCE_COUNT)

    expected_gap = derive_residual_gap(series, horizon, requested, limit)
    sufficiency = request.get("sufficiency") or {}
    if sufficiency.get("residual_gap_disclosed") is not True:
        report.add_error(
            CODE_RESIDUAL_GAP, ref="sufficiency.residual_gap_disclosed",
            message="residual_gap_disclosed e' obbligatorio e puo' valere SOLO "
                    "true: emettere nascondendo un gap residuo e' "
                    "strutturalmente impossibile")
    declared_gap = as_decimal(sufficiency.get("residual_gap"))
    if declared_gap is None:
        # Un gap NON numerico non salta il confronto: e' un gap non
        # dichiarato, cioe' `fr_residual_gap_hidden`.
        report.add_error(
            CODE_RESIDUAL_GAP, ref="sufficiency.residual_gap",
            message="il gap residuo dichiarato non e' un importo finito: un "
                    "gap che non si confronta e' un gap nascosto",
            expected=str(expected_gap),
            actual=str(sufficiency.get("residual_gap")))
    elif expected_gap is not None and \
            not amounts_within(declared_gap, expected_gap, TOLERANCE_EUR):
        report.add_error(
            CODE_RESIDUAL_GAP, ref="sufficiency.residual_gap",
            message="il gap residuo dichiarato non coincide con quello "
                    "ricostruito dal flusso di cassa canonico",
            expected=str(expected_gap), actual=str(declared_gap))
    if sufficiency.get("funded_horizon") != expected_after:
        report.add_error(
            CODE_RUNWAY_AFTER, ref="sufficiency.funded_horizon",
            message="l'orizzonte finanziato non coincide col runway finanziato",
            expected=str(expected_after),
            actual=str(sufficiency.get("funded_horizon")))


def check_milestones(request, canonical, project, report):
    coverage = modules_of(canonical).get("milestone_coverage") or {}
    calendar = calendar_of(canonical)
    out_of_horizon = set(calendar.get("out_of_horizon_milestones") or [])
    entries = {str(item.get("milestone_ref")): item
               for item in request.get("milestone_financing") or []}
    canonical_refs = {str(item.get("milestone_ref"))
                      for item in coverage.get("milestones") or []}
    for ref in sorted(canonical_refs | out_of_horizon):
        if ref not in entries:
            report.add_error(
                CODE_MILESTONE_COST, ref=ref,
                message="la milestone del canonico non compare in "
                        "milestone_financing: ignorarla sottostimerebbe in "
                        "silenzio il fabbisogno")
    for ref in sorted(out_of_horizon):
        entry = entries.get(ref)
        if entry is None:
            continue
        if not entry.get("out_of_horizon"):
            report.add_error(
                CODE_MILESTONE_COST, ref=ref,
                message="la milestone e' in out_of_horizon_milestones e non e' "
                        "DICHIARATA tale")
        if entry.get("target_date") is not None:
            report.add_error(
                CODE_MILESTONE_COST, ref=ref,
                message="una milestone fuori orizzonte non riceve una "
                        "target_date plausibile")
    for ref in sorted(entries):
        entry = entries[ref]
        if entry.get("coverage_status") == "funded" and \
                not entry.get("cost_ref"):
            report.add_error(
                CODE_MILESTONE_COST, ref=ref,
                message="una milestone finanziata deve mappare a un MIL-* "
                        "DATATO e COSTATO: cost_ref e' vuoto")
    if not entries:
        # «Milestone prima del funding»: un capitale che non
        # risale ad alcuna milestone e' un GAP, e il gap e' DICHIARATO.
        decisions = [str(item.get("code")) for item in
                     ((request.get("dependencies_and_assumptions") or {})
                      .get("decision_needed") or [])]
        if MILESTONE_DECISION not in decisions:
            report.add_error(
                CODE_MILESTONE_COST, ref=MILESTONE_DECISION,
                message="milestone_financing e' VUOTO e nessuna decisione "
                        f"{MILESTONE_DECISION} lo dichiara: il collegamento "
                        "mancante fra capitale e milestone e' ESPOSTO, mai "
                        "lasciato muto")
    summary = request.get("milestone_financing_summary") or {}
    declared_residual = str(summary.get("unmapped_residual"))
    canonical_residual = coverage.get("unmapped_residual")
    expected_residual = NOT_APPLICABLE if canonical_residual is None \
        else str(canonical_residual)
    if declared_residual != expected_residual:
        report.add_error(
            CODE_MILESTONE_COST, ref="milestone_financing_summary",
            message="il residuo non mappato dichiarato non coincide con quello "
                    "del canonico: il residuo e' ESPOSTO, mai assorbito",
            expected=expected_residual, actual=declared_residual)
    if summary.get("out_of_horizon_count") != len(out_of_horizon):
        report.add_error(
            CODE_MILESTONE_COST, ref="milestone_financing_summary",
            message="il conteggio delle milestone fuori orizzonte non coincide "
                    "con quello del canonico",
            expected=str(len(out_of_horizon)),
            actual=str(summary.get("out_of_horizon_count")))

    known = roadmap_ids(project)
    for ref in sorted(entries):
        if ref not in known:
            report.add_error(
                CODE_MILESTONE_ROADMAP, ref=ref,
                message="il riferimento di milestone non risolve nel registro "
                        f"REALE della roadmap ({STAGE9}/{CANONICAL_NAME}): un "
                        "claim di milestone non risalente alla roadmap non e' "
                        "ammesso")


def check_tranches(request, report):
    for index, entry in enumerate(request.get("tranches") or []):
        support = str(entry.get("support") or "")
        if support not in ("supported", "not_supported"):
            report.add_error(
                CODE_TRANCHE, ref=f"tranches[{index}]",
                message=f"support fuori dall'enum chiuso: {support!r}")
            continue
        if support == "not_supported" and (entry.get("amount") is not None or
                                           entry.get("target_date")
                                           is not None):
            report.add_error(
                CODE_TRANCHE, ref=f"tranches[{index}]",
                message="una tranche not_supported non porta importi ne' date: "
                        "uno schedule di finanziamento NON si inventa")
        if support == "supported" and not entry.get("source_path"):
            report.add_error(
                CODE_TRANCHE, ref=f"tranches[{index}]",
                message="una tranche supported deve NOMINARE il portatore "
                        "canonico che la sostiene")


def check_scenarios(request, canonical, report):
    block = request.get("scenario_sensitivity") or {}
    scenarios = scenarios_of(canonical)
    coverage = scenarios.get("coverage") or {}
    level = str(coverage.get("level") or "none")
    if str(block.get("coverage_level")) != level:
        report.add_error(
            CODE_SCENARIO_ID, ref="scenario_sensitivity.coverage_level",
            message="il livello di copertura dichiarato diverge da quello "
                    "canonico",
            expected=level, actual=str(block.get("coverage_level")))
    declared = sorted(key for key in block if key != "coverage_level")
    if declared != sorted(SCENARIO_IDS):
        report.add_error(
            CODE_SCENARIO_ID, ref="scenario_sensitivity",
            message="gli id di scenario devono coincidere con l'enum canonico "
                    f"{sorted(SCENARIO_IDS)}: trovati {declared}")
    for name in SCENARIO_IDS:
        entry = block.get(name) or {}
        if str(entry.get("scenario")) != name:
            report.add_error(
                CODE_SCENARIO_ID, ref=f"scenario_sensitivity.{name}",
                message="l'id di scenario non coincide con l'enum canonico "
                        "minuscolo",
                expected=name, actual=str(entry.get("scenario")))
        if str(entry.get("source_path") or "").endswith(name) is False and \
                entry.get("source_path") is not None:
            report.add_error(
                CODE_SCENARIO_FABRICATED, ref=f"scenario_sensitivity.{name}",
                message="il source_path dello scenario NOMINA un altro "
                        "scenario: e' un valore preso in prestito",
                expected=f"financial_plan.results.scenarios.{name}",
                actual=str(entry.get("source_path")))
        canonical_entry = scenarios.get(name) or {}
        if str(entry.get("status")) != str(canonical_entry.get("status")):
            report.add_error(
                CODE_SCENARIO_FABRICATED, ref=f"scenario_sensitivity.{name}",
                message="lo stato dello scenario non e' quello del canonico",
                expected=str(canonical_entry.get("status")),
                actual=str(entry.get("status")))
        if level == "none" and name in ("downside", "upside"):
            if str(entry.get("status")) != NOT_APPLICABLE:
                report.add_error(
                    CODE_SCENARIO_FABRICATED,
                    ref=f"scenario_sensitivity.{name}",
                    message="con coverage.level == none gli scenari avversi "
                            "restano NOT_APPLICABLE: non sono prodotti e non "
                            "sono etichettati")
            if not str(entry.get("not_applicable_reason") or "").strip():
                report.add_error(
                    CODE_SCENARIO_FABRICATED,
                    ref=f"scenario_sensitivity.{name}",
                    message="uno scenario NOT_APPLICABLE senza motivazione "
                            "NOMINATA")
            if entry.get("requested_capital_delta") is not None:
                report.add_error(
                    CODE_SCENARIO_FABRICATED,
                    ref=f"scenario_sensitivity.{name}",
                    message="uno scenario NOT_APPLICABLE non porta alcun "
                            "delta di capitale")
    if level == "none":
        decisions = [str(item.get("code")) for item in
                     ((request.get("dependencies_and_assumptions") or {})
                      .get("decision_needed") or [])]
        if not any("SCENARIO-COVERAGE" in code.upper() for code in decisions):
            report.add_error(
                CODE_SCENARIO_FABRICATED, ref="dependencies_and_assumptions",
                message="con copertura NULLA il documento deve NOMINARE "
                        "COND-S10-SCENARIO-COVERAGE fra le decisioni richieste")


def check_invented_terms(document, report):
    for path, key, value in deep_items(document):
        if key in INVENTABLE_TERMS:
            report.add_error(
                CODE_INVENTED_TERMS, ref=path,
                message=f"termine finanziario INVENTATO {key!r} presente nel "
                        f"documento con valore {value!r}: nessuna valutazione, "
                        "diluizione, strumento, prezzo o termine e' prodotto "
                        "da questo stage")


def check_reader_context(request, project, report):
    reader = request.get("reader_context") or {}
    decisions = [str(item.get("code") or "") for item in
                 ((request.get("dependencies_and_assumptions") or {})
                  .get("decision_needed") or [])]
    if not decisions:
        report.add_error(
            CODE_DECISION_NEEDED, ref="dependencies_and_assumptions",
            message="un termine ignoto assume lo stato DICHIARATO "
                    "decision_needed, MAI un valore plausibile: l'elenco e' "
                    "vuoto")
    # OGNI termine finanziario che questo stage non possiede
    # e' una decisione DICHIARATA, nominata per codice.
    for code, terms, _ in TERM_DECISIONS:
        if code not in decisions:
            report.add_error(
                CODE_DECISION_NEEDED, ref=code,
                message=f"il termine finanziario ignoto {'/'.join(terms)} non "
                        f"e' dichiarato come decisione {code}: un termine "
                        "ignoto assume lo stato DICHIARATO decision_needed, e "
                        "la sua assenza deve essere VISIBILE")
    path = Path(project).joinpath(PROFILE_REL)
    if path.is_file():
        profile = optional_json(path, {})
        for key in ("funding_type", "primary_reader", "development_stage"):
            if reader.get(key) != profile.get(key):
                report.add_error(
                    CODE_DECISION_NEEDED, ref=f"reader_context.{key}",
                    message="il profilo si LEGGE da shared/startup-profile.json"
                            " e non si inferisce MAI",
                    expected=str(profile.get(key)),
                    actual=str(reader.get(key)))
        if reader.get("profile_ref") != PROFILE_REL:
            report.add_error(
                CODE_DECISION_NEEDED, ref="reader_context.profile_ref",
                message="profile_ref deve NOMINARE il file del profilo letto",
                expected=PROFILE_REL, actual=str(reader.get("profile_ref")))
        return
    for key in ("funding_type", "primary_reader", "development_stage"):
        if reader.get(key) is not None:
            report.add_error(
                CODE_DECISION_NEEDED, ref=f"reader_context.{key}",
                message=f"{PROFILE_REL} e' ASSENTE: il valore {reader.get(key)!r}"
                        " sarebbe un'inferenza silenziosa")
    if reader.get("profile_ref") is not None:
        report.add_error(
            CODE_DECISION_NEEDED, ref="reader_context.profile_ref",
            message=f"{PROFILE_REL} e' ASSENTE ma profile_ref e' valorizzato")
    if not any("PROFILE" in code.upper() for code in decisions):
        report.add_error(
            CODE_DECISION_NEEDED, ref="dependencies_and_assumptions",
            message="profilo assente e nessuna decisione lo DICHIARA")


def check_assumptions(request, project, report):
    register = load_register(project, ASSUMPTIONS_REL)
    # Fronte delle assunzioni — un alias nel registro ufficiale
    # e' RESPINTO con codice attribuito, mai escluso in silenzio dal conteggio.
    _, problems = register_ids(register, ASSUMPTIONS_REL, fw.ASS_RE,
                               fw.LOOSE_ANY_ASS_RE)
    for ref, message in problems:
        report.add_error(
            CODE_ASSUMPTION_PROMOTED, ref=ref,
            message=f"{message}: escluderlo da assumption_refs abbasserebbe "
                    "in silenzio unvalidated_count")
    block = request.get("dependencies_and_assumptions") or {}
    refs = set(block.get("assumption_refs") or [])
    known = {str(entry.get("id")) for entry in register
             if isinstance(entry, dict)}
    unknown = sorted(item for item in refs if item not in known)
    if unknown:
        report.add_error(
            CODE_ASSUMPTION_PROMOTED, ref="assumption_refs",
            message=f"riferimenti di assunzione che non risolvono nel registro "
                    f"UFFICIALE: {unknown}")
    expected = derive_unvalidated_count(register, refs)
    if block.get("unvalidated_count") != expected:
        report.add_error(
            CODE_ASSUMPTION_PROMOTED, ref="unvalidated_count",
            message="il conteggio delle assunzioni non validate diverge dal "
                    "registro ufficiale: un'assunzione non diventa un fatto in "
                    "silenzio",
            expected=str(expected), actual=str(block.get("unvalidated_count")))


def check_precision(request, canonical, report):
    requested = request.get("requested_capital") or {}
    rounding = str(requested.get("rounding_applied") or "")
    if rounding != "none":
        report.add_error(
            CODE_FALSE_PRECISION, ref="requested_capital.rounding_applied",
            message="la politica di capitalizzazione non applica alcun "
                    "arrotondamento (rounding_applied = 'none'):"
                    f" {rounding!r} non e' ammesso")
        return
    capital = request.get("capital_requirement") or {}
    need_ref = str(capital.get("modeled_need_ref") or "")
    found, canonical_need = resolve_path(canonical, need_ref)
    if found and str(capital.get("modeled_need_amount")) != \
            str(canonical_need):
        report.add_error(
            CODE_FALSE_PRECISION, ref="capital_requirement.modeled_need_amount",
            message="con arrotondamento `none` la cifra emessa deve essere il "
                    "letterale canonico VERBATIM: ripresentarla con una "
                    "precisione diversa e' falsa precisione",
            expected=str(canonical_need),
            actual=str(capital.get("modeled_need_amount")))


def check_provenance(request, report):
    provenance = request.get("provenance") or []
    fields = {str(entry.get("field")) for entry in provenance}
    for entry in provenance:
        for key in ("field", "canonical_path", "unit",
                    "canonical_source_checksum"):
            if not entry.get(key):
                report.add_error(
                    CODE_PROVENANCE, ref=str(entry.get("field")),
                    message=f"voce di provenance senza {key}")
        for key in ("scenario", "period", "currency"):
            if key not in entry:
                report.add_error(
                    CODE_PROVENANCE, ref=str(entry.get("field")),
                    message=f"voce di provenance senza la chiave {key}")
    required_fields = [
        "requested_capital.amount",
        "capital_requirement.modeled_need_amount",
        "runway.after_financing.periods",
        "sufficiency.residual_gap",
        "horizon.horizon_periods",
        "dependencies_and_assumptions.unvalidated_count",
    ]
    for index in range(len(request.get("use_of_proceeds") or [])):
        required_fields.append(f"use_of_proceeds[{index}].amount")
        required_fields.append(f"use_of_proceeds[{index}].percentage")
    missing = [field for field in required_fields if field not in fields]
    if missing:
        report.add_error(
            CODE_PROVENANCE, ref="provenance",
            message="campi numerici emessi SENZA voce di provenienza: il join "
                    f"campi x provenienza ha residuo {missing}")
    report.add_check("provenance_join", "FAIL" if missing else "PASS",
                     expected=str(len(required_fields)),
                     actual=str(len(fields)),
                     message="copertura totale dei campi numerici emessi")

    index_block = request.get("evidence_index") or {}
    for key, canonical_re, loose_re in (
            ("evidence_refs", EVD_RE, LOOSE_EVD_RE),
            ("source_refs", SRC_RE, LOOSE_SRC_RE)):
        for ref in index_block.get(key) or []:
            text = str(ref)
            if canonical_re.match(text):
                continue
            if loose_re.match(text):
                report.add_error(
                    CODE_PROVENANCE, ref=text,
                    message=f"identificatore {text!r} RICONOSCIUTO come alias "
                            "NON canonico e RESPINTO: non e' "
                            "normalizzato, troncato o riscritto")
            else:
                report.add_error(
                    CODE_PROVENANCE, ref=text,
                    message=f"identificatore {text!r} in forma libera: nessun "
                            "id fuori dalla forma canonica e' ammesso")


def check_evidence_registers(request, project, report):
    """Forma canonica degli id sul percorso dei REGISTRI di evidenze e fonti.

    Il Transaction Manager non passa MAI `--build`: il rifiuto degli alias non
    puo' vivere solo nel costruttore. Qui, in egress e in impact:

      - ogni voce NON canonica di un registro e' RESPINTA con codice
        attribuito che la NOMINA;
      - ogni voce canonica del registro compare nell'indice: una voce OMESSA
        e' un FAIL, mai uno scarto silenzioso;
      - ogni riferimento canonico dell'indice RISOLVE nel registro;
      - `availability` e' coerente con i registri: `missing` solo dove
        l'evidenza davvero non esiste.
    """
    index_block = request.get("evidence_index") or {}
    registered = False
    for key, rel, canonical_re, loose_re in EVIDENCE_REGISTERS:
        ids, problems = register_ids(load_register(project, rel), rel,
                                     canonical_re, loose_re)
        for ref, message in problems:
            report.add_error(CODE_PROVENANCE, ref=ref, message=message)
        emitted = [str(item) for item in index_block.get(key) or []]
        for ref in ids:
            if ref not in emitted:
                report.add_error(
                    CODE_PROVENANCE, ref=ref,
                    message=f"la voce {ref!r} di {rel} e' OMESSA da "
                            f"evidence_index.{key}: nessuna voce e' scartata "
                            "in silenzio")
        for ref in emitted:
            if canonical_re.match(ref) and ref not in ids:
                report.add_error(
                    CODE_PROVENANCE, ref=ref,
                    message=f"il riferimento {ref!r} di evidence_index.{key} "
                            f"NON risolve in {rel}: un riferimento che non "
                            "risolve e' un FAIL attribuito")
        if ids:
            registered = True
    expected = "available" if registered else "missing"
    if index_block.get("availability") != expected:
        report.add_error(
            CODE_PROVENANCE, ref="evidence_index.availability",
            message="availability non coerente con i registri di evidenza e "
                    "di fonte",
            expected=expected, actual=str(index_block.get("availability")))


def check_unresolved(request, canonical, report):
    validation = plan_of(canonical).get("validation") or {}
    upstream = []
    for severity, key in (("ERROR", "errors"), ("WARNING", "warnings")):
        for entry in validation.get(key) or []:
            upstream.append((severity, str(entry.get("code"))))
    downstream = [(str(item.get("severity")), str(item.get("code")))
                  for item in request.get("unresolved_validation_items") or []]
    if sorted(upstream) != sorted(downstream):
        report.add_error(
            CODE_UNRESOLVED_ITEMS, ref="unresolved_validation_items",
            message="le voci di validazione irrisolte sono ESPOSTE, mai "
                    "soppresse: il conteggio a valle deve essere IDENTICO a "
                    "quello a monte",
            expected=str(sorted(upstream)), actual=str(sorted(downstream)))


#: Il codice con cui un letterale dichiarato
#: DIVERSO dalla derivazione autoritativa e' respinto, per campo: quello del
#: contratto che fissa la relazione del campo col canonico dello Stage 10.
#: Le voci d'impiego sono confrontate per candidato da `check_entries`.
DECLARED_LITERAL_CODES = {
    "requested_capital.amount": CODE_CAPITAL_RECON,
    "capital_requirement.modeled_need_amount": CODE_CAPITAL_RECON,
    "sufficiency.residual_gap": CODE_RESIDUAL_GAP,
    "runway.after_financing.periods": CODE_RUNWAY_AFTER,
    "horizon.horizon_periods": CODE_HORIZON,
    "runway.before_financing.runway_to_zero": CODE_RUNWAY_BEFORE,
    "runway.before_financing.runway_to_buffer": CODE_RUNWAY_BEFORE,
    "dependencies_and_assumptions.unvalidated_count":
        CODE_ASSUMPTION_PROMOTED,
}


#: I portatori che `check_projection` NON vincola alla proiezione
#: autoritativa, ciascuno con la ragione:
#:   - la PROSA della narrativa, tracciata espressione per espressione
#:     (`check_narrative`, `fr_narrative_untraced_value`);
#:   - le domande di decisione e le voci irrisolte, che restano FUORI dal
#:     confronto di proiezione per scelta di progetto; le voci irrisolte
#:     restano confrontate con lo Stage 10 per severita' e codice
#:     (`fr_unresolved_items_suppressed`);
#:   - impieghi, provenance, indice delle evidenze e contesto del lettore, che
#:     hanno un controllo dedicato (`check_entries`, `check_canonical_only`,
#:     `check_evidence_registers`, `check_reader_context`).
PROJECTION_UNBOUND = ("narrative", "dependencies_and_assumptions.decision_needed",
                      "unresolved_validation_items", "use_of_proceeds",
                      "provenance", "evidence_index", "reader_context")
#: Il testo DESCRITTIVO libero: motivazioni, metodi, basi,
#: riferimenti di politica. Non e' un valore della proiezione.
PROJECTION_DESCRIPTIVE = ("reason", "method", "basis", "policy_ref",
                          "not_applicable_reason")
PROVENANCE_DESCRIPTIVE = ("unit", "scenario", "currency")
#: Il codice di ogni valore strutturato, per prefisso del path: quello del
#: contratto che ne fissa la relazione col canonico dello Stage 10.
PROJECTION_CODES = (
    ("capital_requirement.timing_granularity", CODE_POLICY_UNDECLARED),
    ("capital_requirement", CODE_CAPITAL_RECON),
    ("requested_capital", CODE_CAPITAL_RECON),
    ("runway.before_financing", CODE_RUNWAY_BEFORE),
    ("runway", CODE_RUNWAY_AFTER),
    ("sufficiency.funded_horizon", CODE_RUNWAY_AFTER),
    ("sufficiency", CODE_RESIDUAL_GAP),
    ("horizon", CODE_HORIZON),
    ("milestone_financing", CODE_MILESTONE_COST),
    ("tranches", CODE_TRANCHE),
    ("scenario_sensitivity", CODE_SCENARIO_FABRICATED),
    ("dependencies_and_assumptions", CODE_ASSUMPTION_PROMOTED),
)
_ABSENT = object()


def projection_differences(actual, expected, path, skip):
    """Le coppie `(path, emesso, atteso)` in cui il documento diverge dalla
    proiezione autoritativa, fuori dai path in `skip` e dal testo
    descrittivo. Il confronto e' per RESA JSON: `12.0` non e' `12`."""
    if path in skip or path.rpartition(".")[2] in PROJECTION_DESCRIPTIVE:
        return []
    if isinstance(actual, dict) and isinstance(expected, dict):
        differences = []
        for key in sorted(set(actual) | set(expected)):
            differences.extend(projection_differences(
                actual.get(key, _ABSENT), expected.get(key, _ABSENT),
                f"{path}.{key}" if path else key, skip))
        return differences
    if isinstance(actual, list) and isinstance(expected, list) and \
            len(actual) == len(expected):
        differences = []
        for index, pair in enumerate(zip(actual, expected)):
            differences.extend(projection_differences(
                pair[0], pair[1], f"{path}[{index}]", skip))
        return differences
    if actual is _ABSENT or expected is _ABSENT:
        return [(path, actual, expected)]
    if json.dumps(actual, sort_keys=True) == json.dumps(expected,
                                                        sort_keys=True):
        return []
    return [(path, actual, expected)]


def check_projection(request, authority, report):
    """LA FUNDING REQUEST E' UNA PROIEZIONE. Ogni
    valore STRUTTURATO che la proiezione autoritativa fissa — tranche,
    delta di scenario, finanziamento delle milestone, componenti di buffer e
    di contingency, granularita', valuta del capitale, stato di governance
    propagato, orizzonte finanziato, sorgente — coincide, nella sua resa, con
    quello del validator: il documento sotto validazione non dichiara da se'
    cio' che il canonico dello Stage 10 e i registri fissano (codici per
    prefisso di path in `PROJECTION_CODES`; buffer esposto e non sommato,
    contingency assente; workflow Passo 2: lo stato propagato si PROPAGA e
    non si lava). Restano fuori i portatori di
    `PROJECTION_UNBOUND` e il testo descrittivo; i letterali dichiarati e la
    riconciliazione hanno i propri messaggi (`check_declared_literals`,
    `check_capital`)."""
    if authority is None:
        return
    skip = set(PROJECTION_UNBOUND)
    skip.update(field for _, field in declared_literals(authority))
    skip.update(("capital_requirement.reconciliation",
                 "capital_requirement.modeled_need_ref"))
    for path, actual, expected in projection_differences(request, authority,
                                                         "", skip):
        code = next((candidate for prefix, candidate in PROJECTION_CODES
                     if path.startswith(prefix)), CODE_NON_CANONICAL)
        report.add_error(
            code, ref=path,
            message="il valore emesso non e' quello della proiezione "
                    "AUTORITATIVA del canonico dello Stage 10: il documento "
                    "sotto validazione non lo dichiara da se'",
            expected="assente" if expected is _ABSENT
            else json.dumps(expected, sort_keys=True),
            actual="assente" if actual is _ABSENT
            else json.dumps(actual, sort_keys=True))


def check_declared_literals(request, authority, report):
    """Il documento sotto validazione e' INPUT
    NON FIDATO, e non allarga l'insieme delle rese numeriche autoritative
    dichiarandole in un proprio campo. Ogni valore emesso che diventa un
    letterale dichiarato e' confrontato, NELLA SUA RESA, con quello della
    proiezione AUTORITATIVA: il capitale richiesto con la misura di
    fabbisogno che la politica fissa (`fr_capital_reconciliation_failed`),
    il gap residuo e il runway finanziato con quelli ricostruiti a quel
    capitale (`fr_residual_gap_hidden`, `fr_runway_after_mismatch`), il
    conteggio delle assunzioni non validate con l'intero registro ufficiale
    (`fr_assumption_promoted`). Una derivazione o un path AUTO-dichiarati
    non esentano nulla."""
    if authority is None:
        return
    expected = {field: literal for literal, field in declared_literals(
        authority)}
    emitted = {field: literal for literal, field in declared_literals(request)}
    for field in sorted(set(expected) | set(emitted)):
        if field.startswith("use_of_proceeds["):
            continue
        if emitted.get(field) == expected.get(field):
            continue
        if field == "requested_capital.amount":
            reason = ("il capitale richiesto non e' quello che la politica "
                      "DICHIARATA produce dal fabbisogno modellato: misura "
                      "selezionata dalla politica, buffer esposto e non "
                      "sommato, contingency ASSENTE, nessun arrotondamento. "
                      "Nessun portatore di "
                      "finanziamento parziale esiste, e il documento sotto "
                      "validazione non fissa da se' il proprio capitale")
        else:
            reason = ("il valore emesso non e' la resa che il validator "
                      "ricostruisce dal canonico dello Stage 10: un letterale "
                      "dichiarato e' la derivazione AUTORITATIVA, mai una "
                      "dichiarazione del documento sotto validazione")
        report.add_error(
            DECLARED_LITERAL_CODES.get(field, CODE_NARRATIVE), ref=field,
            message=reason, expected=str(expected.get(field)),
            actual=str(emitted.get(field)))


def check_narrative(request, report, resolved=frozenset(), trusted=None):
    """La narrativa NON calcola (`fr_narrative_untraced_value`): ogni numero
    citato e' in `narrative.numeric_refs[]` e risolve in `provenance[]`.

    `trusted` e' l'insieme dei letterali AUTORITATIVI, derivato
    dal validator e MAI letto dal documento sotto validazione: un numero e'
    tracciato solo se e' dichiarato in `numeric_refs[]` E autoritativo. Senza
    `trusted` nessun letterale e' tracciato: fail-closed. Il TITOLO di ogni
    sezione fa parte della narrativa controllata ed e' scandito come il
    corpo, come l'intestazione che il derivato ne fa."""
    narrative = request.get("narrative") or {}
    declared = {str(item.get("literal")) for item in
                narrative.get("numeric_refs") or []}
    emitted = {literal for literal, _ in declared_literals(request)}
    undeclared = sorted(item for item in declared if item not in emitted)
    if undeclared:
        report.add_error(
            CODE_NARRATIVE, ref="narrative.numeric_refs",
            message=f"letterali dichiarati che nessun campo emette: "
                    f"{undeclared}")
    authoritative = frozenset(trusted or ())
    forged = sorted(item for item in declared if item not in authoritative)
    if forged:
        report.add_error(
            CODE_NARRATIVE, ref="narrative.numeric_refs",
            message=f"letterali dichiarati che la proiezione AUTORITATIVA non "
                    f"emette: {forged}")
    literals = declared & authoritative
    # Confronto per ESPRESSIONE: un letterale dichiarato non autorizza i
    # numeri che ne sono SOTTOSTRINGA. E per RESA dichiarata, non per
    # valore: il `100` non traccia il `100.000`, ne' il `100 mila`, il
    # `k EUR 100`, il `100 **mila**` o il `7 100 100`; e solo un id che
    # RISOLVE in `resolved` sottrae le proprie cifre.
    for section in narrative.get("sections") or []:
        for part, text, heading in (
                ("titolo", section.get("title"), True),
                ("corpo", section.get("body"), False)):
            for expression in untraced(
                    prose_expressions(str(text or ""), resolved, heading),
                    literals):
                report.add_error(
                    CODE_NARRATIVE, ref=str(section.get("section_id")),
                    message=f"la narrativa cita nel {part} il numero "
                            f"{token_label(expression)} che non e' in "
                            "narrative.numeric_refs[] e non risolve in "
                            "provenance[]: la narrativa NON calcola")


def check_determinism(document, path, report):
    expected = canonical_json(document)
    actual = Path(path).read_text(encoding="utf-8")
    if expected != actual:
        report.add_error(
            CODE_NONDETERMINISTIC, ref=str(path),
            message="il documento sul disco non e' nella forma canonica "
                    "DETERMINISTICA (chiavi ordinate, indentazione 2, "
                    "ensure_ascii, newline finale): due esecuzioni non "
                    "produrrebbero byte identici")


def check_derived(document, project, report, phase="egress",
                  resolved=frozenset(), trusted=None, verbatim=frozenset()):
    """Confronto TRIANGOLARE (`derived_artifact_numeric_mismatch`): canonico,
    capitolo, workbook e
    funding request portano UNA SOLA generazione, e ogni numero della funding
    request compare nel proprio derivato, per TOKEN e per RESA dichiarata
    (l'uguaglianza di valore non traccia).

    FASE IMPACT. Il Transaction Manager valida l'impact sulla
    validation view di `build_validation_view`, che per costruzione porta
    SOLTANTO `shared/` e i `NN_*/structured-output.json`: i derivati non ne
    fanno parte. In impact il derivato ASSENTE e' percio' NON APPLICABILE — la
    fase misura la superficie CANONICA che il Transaction Manager fornisce —
    e resta dichiarato in `checks[]`; un derivato PRESENTE e' comunque
    confrontato. In egress il derivato resta OBBLIGATORIO.

    Il derivato si scandisce con la STESSA vista del
    lettore e la STESSA espressione del fronte JSON (`prose_expressions`),
    blocco per blocco, contro i letterali AUTORITATIVI `trusted`. Il checksum
    rimosso e' la generazione degli artefatti dello Stage 10, non quella che
    il documento dichiara; e la sola prosa esente e' `verbatim`, le voci
    irrisolte dello Stage 10 lette dal canonico dello Stage 10, ciascuna
    nella SOLA propria riga di elenco. Nulla che il documento sotto
    validazione dichiari in un proprio campo sottrae un numero o un
    identificatore alla scansione.
    """
    request = document["funding_request"]
    declared_checksum = str((request.get("source") or {})
                            .get("canonical_source_checksum") or "")
    generations = {"funding_request": declared_checksum}
    try:
        import derived_consistency as gate
    except ImportError as exc:                       # pragma: no cover
        raise fw.ValidatorUsageError(
            f"gate dei derivati non importabile: {exc}")
    paths = gate.artifact_paths(Path(project))
    restored = gate.restored_generations(paths)
    for name in ("canonical", "chapter", "workbook"):
        generations[name] = restored.get(name)
    values = {value for value in generations.values() if value}
    if len(values) > 1:
        report.add_error(
            CODE_DERIVED_MISMATCH, ref="canonical_source_checksum",
            message="canonico, capitolo, workbook e funding request non "
                    f"portano UNA SOLA generazione: {generations}")
    request_path = Path(project).joinpath(STAGE11, REQUEST_NAME)
    if not request_path.is_file():
        if phase == "impact":
            report.add_check(
                "derived_request_markdown", NOT_APPLICABLE,
                message=f"{REQUEST_NAME} non fa parte della superficie "
                        "canonica che il Transaction Manager fornisce in fase "
                        "impact (validation view: shared/ e "
                        "NN_*/structured-output.json): il confronto del "
                        "derivato e' OBBLIGATORIO in egress")
            return
        report.add_error(
            CODE_DERIVED_MISMATCH, ref=str(request_path),
            message=f"{REQUEST_NAME} ASSENTE: il derivato obbligatorio della "
                    "funding request non esiste")
        return
    text = request_path.read_text(encoding="utf-8")
    # Nessuna riga e' saltata per la sua FORMA: e' rimosso il solo
    # checksum, e ogni altra cifra della riga resta un numero. Il checksum
    # rimosso e' la generazione AUTORITATIVA degli artefatti dello Stage 10,
    # non quella che il documento dichiara.
    for name, value in sorted(generations.items()):
        if name != "funding_request" and value:
            text = text.replace(value, ID_MASK)
    literals = frozenset(trusted or ())
    present = set()
    for block in prose_blocks(text):
        if normalized(block) in verbatim:
            continue
        expressions = numeric_expressions(block, resolved)
        present.update(expression.core for expression in expressions
                       if expression.qualifier is None)
        # Confronto per ESPRESSIONE, mai per sottostringa: il `5` non e'
        # tracciato dal `50`. E per RESA dichiarata, non per valore: il
        # `12.000` non e' tracciato dal `12`, ne' il `12 mila`. La STESSA
        # risoluzione degli id della narrativa e la STESSA espressione
        # completa del fronte JSON; un a capo dentro un paragrafo non separa
        # le cifre dal loro qualificatore.
        for expression in untraced(expressions, literals):
            report.add_error(
                CODE_DERIVED_MISMATCH, ref=REQUEST_NAME,
                message=f"{REQUEST_NAME} porta il numero "
                        f"{token_label(expression)} che il canonico della "
                        "funding request non emette")
    for literal, field in declared_literals(request):
        found = literal in text if as_decimal(literal) is None \
            else literal in present
        if not found:
            report.add_error(
                CODE_DERIVED_MISMATCH, ref=field,
                message=f"il valore {literal!r} del campo {field} NON compare "
                        f"in {REQUEST_NAME}: il derivato racconta una storia "
                        "diversa dal canonico",
                expected=literal, actual="assente")


def check_request(args, report, canonical_arg, canonical_input_arg,
                  stage_order):
    project = args.project
    if canonical_arg:
        target = Path(canonical_arg)
    elif args.candidate:
        target = Path(args.candidate).joinpath(CANONICAL_NAME)
    else:
        target = project.joinpath(STAGE11, CANONICAL_NAME)
    document = load_json(target, "documento canonico della funding request")
    canonical_path = Path(canonical_input_arg) if canonical_input_arg \
        else project.joinpath(STAGE10, CANONICAL_NAME)
    canonical = load_json(canonical_path, "canonico dello Stage 10")

    check_no_recompute(report)
    schema_valid = check_schema(document, report)
    check_invented_terms(document, report)
    check_determinism(document, target, report)
    try:
        request = (document or {}).get("funding_request") or {}
        if not request:
            report.add_error(
                CODE_SCHEMA, ref=str(target),
                message="il documento non porta la radice funding_request")
            return
        # La proiezione AUTORITATIVA, UNA sola
        # volta, dal SOLO canonico dello Stage 10 e dai registri: e' cio' che
        # il documento sotto validazione deve essere, e la sorgente dei
        # letterali che la prosa puo' citare.
        authority = authoritative_request(canonical, project, report)
        check_canonical_only(request, canonical, report, authority)
        check_policy(request, report)
        check_capital(request, canonical, report, authority)
        check_allocation(request, canonical, report, authority)
        check_horizon(request, canonical, report)
        check_runway(request, canonical, report)
        check_milestones(request, canonical, project, report)
        check_tranches(request, report)
        check_scenarios(request, canonical, report)
        check_reader_context(request, project, report)
        check_assumptions(request, project, report)
        check_precision(request, canonical, report)
        check_provenance(request, report)
        check_evidence_registers(request, project, report)
        check_unresolved(request, canonical, report)
        check_declared_literals(request, authority, report)
        check_projection(request, authority, report)
        # UNA sola risoluzione degli identificatori, contro le autorita' del
        # contesto di validazione, per ENTRAMBI i fronti della prosa; e UN
        # solo insieme di letterali
        # autoritativi, dalla proiezione del validator: nessuna regola
        # diverge fra JSON e Markdown, e nessuna fiducia viene dal documento
        # sotto validazione.
        resolved = resolvable_ids(canonical, project, stage_order)
        trusted = frozenset(literal for literal, _ in declared_literals(
            authority)) if authority is not None else frozenset()
        check_narrative(request, report, resolved, trusted)
        check_derived(document, project, report, args.phase, resolved,
                      trusted, authoritative_verbatim(canonical))
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        # I controlli semantici presuppongono la struttura
        # dello schema. Su un documento che lo schema ha GIA' respinto, una
        # voce obbligatoria assente e' un rifiuto di SCHEMA ATTRIBUITO, nel
        # report, e non un traceback. Su un documento conforme lo stesso
        # errore e' un difetto del validator, e resta non gestito.
        if schema_valid:
            raise
        report.add_error(
            CODE_SCHEMA, ref=str(target),
            message="il documento non e' conforme allo schema e i controlli "
                    "semantici non sono eseguibili sulla sua struttura "
                    f"({type(exc).__name__}: {exc}): respinto, fail-closed")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    pre = argparse.ArgumentParser(prog=VALIDATOR_NAME, add_help=False)
    pre.add_argument("--build", action="store_true")
    pre.add_argument("--tx")
    pre.add_argument("--canonical")
    pre.add_argument("--canonical-input")
    try:
        known, rest = pre.parse_known_args(argv)
    except SystemExit:
        print(f"{VALIDATOR_NAME}: argomenti CLI non validi", file=sys.stderr)
        return fw.EXIT_USAGE

    if known.build:
        build = argparse.ArgumentParser(prog=VALIDATOR_NAME, add_help=False)
        build.add_argument("--project")
        try:
            args, unknown = build.parse_known_args(rest)
        except SystemExit:
            print(f"{VALIDATOR_NAME}: argomenti CLI non validi",
                  file=sys.stderr)
            return fw.EXIT_USAGE
        if unknown:
            print(f"{VALIDATOR_NAME}: argomenti non riconosciuti: {unknown}",
                  file=sys.stderr)
            return fw.EXIT_USAGE
        if not args.project:
            print(f"{VALIDATOR_NAME}: --project obbligatorio in modalita' "
                  "--build", file=sys.stderr)
            return fw.EXIT_USAGE
        args.tx = known.tx
        args.canonical_input = known.canonical_input
        try:
            return run_build(args)
        except fw.ValidatorUsageError as exc:
            print(f"{VALIDATOR_NAME}: {exc}", file=sys.stderr)
            return fw.EXIT_USAGE

    def check_fn(args, config, state, report):
        del state
        if args.stage != STAGE11:
            raise fw.ValidatorUsageError(
                f"stage non pertinente a {VALIDATOR_NAME}: {args.stage} "
                f"(atteso {STAGE11})")
        if args.phase not in SUPPORTED_PHASES:
            raise fw.ValidatorUsageError(
                f"--phase non ammessa per {VALIDATOR_NAME}: {args.phase} "
                f"(ammesse: {SUPPORTED_PHASES})")
        check_request(args, report, known.canonical, known.canonical_input,
                      config["stage_order"])

    fw.run_validator(VALIDATOR_NAME, check_fn, rest)
    return fw.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
