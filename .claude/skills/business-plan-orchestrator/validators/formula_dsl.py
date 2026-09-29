#!/usr/bin/env python3
"""Formula DSL deterministica e sicura.

Grammatica whitelist: identificatori dichiarati in `variables`, letterali
numerici, operatori binari + - * /, meno unario, parentesi. Qualsiasi altro
nodo AST è rifiutato con `invalid_formula`. La stringa della formula non è
mai eseguita: viene analizzata con `ast.parse` e valutata da un walker che
ammette esclusivamente i nodi della whitelist.

Numerica: `decimal.Decimal` per tutti i calcoli; percentuali canoniche come
frazione in [0,1] (`unit: "ratio"`); rounding ROUND_HALF_UP e tolleranza per
unità (EUR: 2 decimali / 0.01 assoluta; ratio: 6 / 1e-6; count: 0 / esatto).

Ogni FormulaError è un difetto del candidate (exit semantics 1, mai 2).
"""
import ast
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

DIMENSIONLESS_UNITS = {None, "", "ratio"}

# Limiti espliciti della DSL: lunghezza della formula, nodi e profondità AST.
MAX_FORMULA_LENGTH = 500
MAX_FORMULA_NODES = 200
MAX_FORMULA_DEPTH = 50

DEFAULT_DECIMALS = {"EUR": 2, "ratio": 6, "count": 0}
DEFAULT_TOLERANCES = {
    "EUR": Decimal("0.01"),
    "ratio": Decimal("1E-6"),
    "count": Decimal("0"),
}
FALLBACK_DECIMALS = 6
FALLBACK_TOLERANCE = Decimal("1E-6")

_ALLOWED_BINOPS = {
    ast.Add: "add",
    ast.Sub: "sub",
    ast.Mult: "mult",
    ast.Div: "div",
}
# l'unico operatore unario ammesso è il meno (niente unary plus)
_ALLOWED_UNARY = (ast.USub,)


class FormulaError(ValueError):
    """Candidate-fault DSL error (codici machine-readable)."""

    def __init__(self, code, message, ref=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.ref = ref
        self.exit_code = 1


def parse_unit(unit_str):
    """'EUR/count' -> {'EUR': 1, 'count': -1}; ratio/None/'' -> {} (adimensionale)."""
    if unit_str in DIMENSIONLESS_UNITS:
        return {}
    parts = [p.strip() for p in str(unit_str).split("/")]
    unit = {}
    for i, token in enumerate(parts):
        if not token:
            raise FormulaError("unit_mismatch", f"unità malformata: {unit_str!r}")
        if token in DIMENSIONLESS_UNITS:
            continue
        unit[token] = unit.get(token, 0) + (1 if i == 0 else -1)
    return {k: v for k, v in unit.items() if v != 0}


def unit_to_str(unit):
    if not unit:
        return "ratio"
    num = []
    den = []
    for token in sorted(unit):
        exp = unit[token]
        (num if exp > 0 else den).extend([token] * abs(exp))
    text = "*".join(num) if num else "1"
    for token in den:
        text += f"/{token}"
    return text


def _units_multiply(a, b, invert_b=False):
    out = dict(a)
    for token, exp in b.items():
        if invert_b:
            exp = -exp
        out[token] = out.get(token, 0) + exp
        if out[token] == 0:
            del out[token]
    return out


def _ast_depth(tree):
    """Profondità dell'AST calcolata iterativamente (nessuna ricorsione)."""
    deepest = 0
    stack = [(tree, 1)]
    while stack:
        node, depth = stack.pop()
        deepest = max(deepest, depth)
        for child in ast.iter_child_nodes(node):
            stack.append((child, depth + 1))
    return deepest


def _literal_decimal(formula, node):
    """Decimal costruito dal literal SORGENTE esatto: nessuna perdita
    di cifre attraverso il float intermedio del parser.

    Il fallback non passa MAI da un float AST. Se il segmento
    sorgente non è disponibile, un intero resta esatto (Decimal(int)) mentre
    un float è rifiutato — `Decimal(str(float))` reintrodurrebbe la perdita di
    precisione del parser che il contratto vuole escludere."""
    try:
        segment = ast.get_source_segment(formula, node)
    except Exception:  # noqa: BLE001
        segment = None
    if segment:
        try:
            return Decimal(segment.strip().replace("_", ""))
        except InvalidOperation:
            pass
    value = node.value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FormulaError(
            "invalid_formula", f"letterale non numerico: {value!r}")
    if isinstance(value, int):
        return Decimal(value)
    raise FormulaError(
        "invalid_formula",
        "letterale float senza segmento sorgente: impossibile ricostruire il "
        "Decimal esatto senza passare dal float AST")


def parse_formula(formula):
    """Ritorna l'AST validato contro la whitelist (senza valutare)."""
    if not isinstance(formula, str) or not formula.strip():
        raise FormulaError("invalid_formula", "formula vuota o non stringa")
    if len(formula) > MAX_FORMULA_LENGTH:
        raise FormulaError(
            "invalid_formula",
            f"formula troppo lunga ({len(formula)} > {MAX_FORMULA_LENGTH})")
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise FormulaError("invalid_formula", f"sintassi non valida: {exc.msg}")
    except (RecursionError, MemoryError):
        raise FormulaError(
            "invalid_formula", "formula troppo complessa per il parser")
    # RecursionError e MemoryError sono normalizzati anche nella fase
    # di analisi (walk, profondità, whitelist), non solo attorno ad ast.parse.
    try:
        nodes = list(ast.walk(tree))
        if len(nodes) > MAX_FORMULA_NODES:
            raise FormulaError(
                "invalid_formula",
                f"troppi nodi AST ({len(nodes)} > {MAX_FORMULA_NODES})")
        depth = _ast_depth(tree)
    except (RecursionError, MemoryError):
        raise FormulaError(
            "invalid_formula", "formula troppo complessa per l'analisi")
    if depth > MAX_FORMULA_DEPTH:
        raise FormulaError(
            "invalid_formula",
            f"AST troppo profondo ({depth} > {MAX_FORMULA_DEPTH})")
    for node in nodes:
        if isinstance(node, ast.Expression):
            continue
        if isinstance(node, ast.BinOp):
            if type(node.op) not in _ALLOWED_BINOPS:
                raise FormulaError(
                    "invalid_formula",
                    f"operatore non ammesso: {type(node.op).__name__}")
            continue
        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, _ALLOWED_UNARY):
                raise FormulaError(
                    "invalid_formula",
                    f"operatore unario non ammesso: {type(node.op).__name__}")
            continue
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(
                    node.value, (int, float)):
                raise FormulaError(
                    "invalid_formula",
                    f"letterale non numerico: {node.value!r}")
            continue
        if isinstance(node, ast.Name):
            if not isinstance(node.ctx, ast.Load):
                raise FormulaError("invalid_formula", "contesto nome non ammesso")
            continue
        if isinstance(node, (ast.Add, ast.Sub, ast.Mult, ast.Div,
                             ast.USub, ast.Load)):
            continue
        raise FormulaError(
            "invalid_formula", f"nodo non ammesso: {type(node).__name__}")
    return tree


def formula_names(formula):
    """Insieme degli identificatori usati dalla formula (whitelist inclusa)."""
    tree = parse_formula(formula)
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def evaluate(formula, values):
    """Valuta la formula. `values`: nome -> (Decimal|None, unit_str).

    Ritorna (Decimal, unit_dict). Solleva FormulaError con codice machine-readable:
    invalid_formula, missing_required, division_by_zero, unit_mismatch.
    """
    tree = parse_formula(formula)

    def resolve(name):
        if name not in values:
            raise FormulaError(
                "invalid_formula",
                f"identificatore non dichiarato in variables: {name}", ref=name)
        raw, unit_str = values[name]
        if raw is None:
            raise FormulaError(
                "missing_required", f"variabile dovuta senza valore: {name}",
                ref=name)
        if not isinstance(raw, Decimal):
            # un valore non convertibile (bool, stringa non numerica, …) è
            # un difetto del candidate: report machine-readable, mai un
            # traceback grezzo (contratto degli exit code)
            try:
                raw = Decimal(str(raw))
            except InvalidOperation:
                raise FormulaError(
                    "invalid",
                    f"variabile con valore non numerico: {name}", ref=name)
        return raw, parse_unit(unit_str)

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            return _literal_decimal(formula, node), {}
        if isinstance(node, ast.Name):
            return resolve(node.id)
        if isinstance(node, ast.UnaryOp):
            value, unit = walk(node.operand)
            return (-value if isinstance(node.op, ast.USub) else value), unit
        if isinstance(node, ast.BinOp):
            left, lu = walk(node.left)
            right, ru = walk(node.right)
            op = _ALLOWED_BINOPS[type(node.op)]
            if op in ("add", "sub"):
                if lu != ru:
                    raise FormulaError(
                        "unit_mismatch",
                        "addizione/sottrazione tra unità diverse: "
                        f"{unit_to_str(lu)} vs {unit_to_str(ru)}")
                return (left + right if op == "add" else left - right), lu
            if op == "mult":
                return left * right, _units_multiply(lu, ru)
            if right == 0:
                raise FormulaError("division_by_zero", "divisione per zero")
            return left / right, _units_multiply(lu, ru, invert_b=True)
        raise FormulaError(
            "invalid_formula", f"nodo non ammesso: {type(node).__name__}")

    try:
        return walk(tree)
    except (RecursionError, MemoryError):
        # normalizzazione degli errori: mai RecursionError né
        # MemoryError grezzo dalla valutazione
        raise FormulaError(
            "invalid_formula", "formula troppo profonda per la valutazione")


def _rules_key(unit_str, table):
    if unit_str in table:
        return unit_str
    head = str(unit_str).split("/", 1)[0].strip()
    if head in table:
        return head
    return None


def decimals_for_unit(unit_str, decimals=None):
    table = dict(DEFAULT_DECIMALS)
    if decimals:
        table.update(decimals)
    key = _rules_key(unit_str, table)
    return table[key] if key is not None else FALLBACK_DECIMALS


def tolerance_for_unit(unit_str, tolerances=None):
    table = dict(DEFAULT_TOLERANCES)
    if tolerances:
        table.update({k: Decimal(str(v)) for k, v in tolerances.items()})
    key = _rules_key(unit_str, table)
    return table[key] if key is not None else FALLBACK_TOLERANCE


def round_to_unit(value, unit_str, decimals=None):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    digits = decimals_for_unit(unit_str, decimals)
    return value.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def is_canonical_ratio(value):
    """Percentuale canonica: frazione decimale in [0,1]."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return Decimal(0) <= value <= Decimal(1)


def recompute_check(formula, values, expected_value, expected_unit,
                    decimals=None, tolerances=None):
    """Ricalcola la formula e confronta con il valore canonico dichiarato.

    Unità risultante != unità dichiarata -> unit_mismatch; divergenza oltre
    la tolleranza (sui valori arrotondati ROUND_HALF_UP) -> value_mismatch.
    Ritorna il valore ricalcolato e arrotondato.
    """
    computed, unit = evaluate(formula, values)
    declared = parse_unit(expected_unit)
    if unit != declared:
        raise FormulaError(
            "unit_mismatch",
            f"unità risultante {unit_to_str(unit)} diversa dalla dichiarata "
            f"{unit_to_str(declared)}")
    try:
        expected_dec = expected_value if isinstance(expected_value, Decimal) \
            else Decimal(str(expected_value))
    except (InvalidOperation, ValueError, TypeError):
        raise FormulaError(
            "value_mismatch",
            f"valore dichiarato non numerico: {expected_value!r}")
    unit_label = str(expected_unit).strip() if expected_unit else ""
    if unit_label == "count":
        # sia il valore ricalcolato sia quello DICHIARATO devono
        # essere matematicamente interi PRIMA del confronto e del rounding
        # (niente falsi match per arrotondamento: declared 4.5 -> 5 vietato).
        if computed != computed.to_integral_value():
            raise FormulaError(
                "value_mismatch", f"risultato count non intero: {computed}")
        if expected_dec != expected_dec.to_integral_value():
            raise FormulaError(
                "value_mismatch",
                f"count dichiarato non intero: {expected_dec}")
    if unit_label == "ratio" and not is_canonical_ratio(computed):
        # nessun ratio fuori [0,1] persiste nel percorso generico
        raise FormulaError(
            "ratio_out_of_bounds",
            f"ratio fuori dall'intervallo canonico [0,1]: {computed}")
    try:
        computed_r = round_to_unit(computed, expected_unit, decimals)
        expected_r = round_to_unit(expected_dec, expected_unit, decimals)
    except (RecursionError, MemoryError):
        # MemoryError normalizzato anche in fase di rounding/quantize
        raise FormulaError(
            "invalid_formula", "ricalcolo troppo complesso per la valutazione")
    tol = tolerance_for_unit(expected_unit, tolerances)
    if abs(computed_r - expected_r) > tol:
        raise FormulaError(
            "value_mismatch",
            f"valore dichiarato {expected_r} diverge dal ricalcolo "
            f"{computed_r} oltre tolleranza {tol}")
    return computed_r
