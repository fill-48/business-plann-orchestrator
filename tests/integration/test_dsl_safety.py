#!/usr/bin/env python3
"""T-DSL-SAFETY — Formula DSL whitelist, safety and numeric contract.

Discriminating checks:
- whitelist respected: only + - * /, unary minus, parentheses, declared names
  and numeric literals; every other node -> FormulaError(code=invalid_formula)
  classified as a candidate fault (exit semantics 1, never 2);
- no eval/exec on the raw formula string; rejected formulas produce no side
  effects;
- Decimal arithmetic (no float artifacts), per-unit rounding/tolerance;
- division_by_zero / missing_required / unit_mismatch produce the exact codes
  of the DSL error contract;
- percentages are canonical as fractions in [0,1].
"""
import argparse
import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

VALIDATORS_REL = ".claude/skills/business-plan-orchestrator/validators"


class TestFailure(AssertionError):
    pass


def load_dsl(root):
    vdir = root / VALIDATORS_REL
    if not (vdir / "formula_dsl.py").exists():
        raise TestFailure(f"missing module: {VALIDATORS_REL}/formula_dsl.py")
    sys.path.insert(0, str(vdir))
    try:
        import formula_dsl
    except Exception as exc:  # noqa: BLE001
        raise TestFailure(f"formula_dsl not importable: {exc}")
    return formula_dsl


def expect_error(dsl, code, formula, values, label):
    try:
        dsl.evaluate(formula, values)
    except dsl.FormulaError as exc:
        if exc.code != code:
            raise TestFailure(f"{label}: expected code {code}, got {exc.code}")
        if getattr(exc, "exit_code", None) != 1:
            raise TestFailure(
                f"{label}: candidate fault must map to exit 1, "
                f"got {getattr(exc, 'exit_code', None)}")
        return exc
    raise TestFailure(f"{label}: expected FormulaError({code}), got a result")


def run(root):
    dsl = load_dsl(root)

    # --- source hygiene: no eval/exec on the formula string -----------------
    src = (root / VALIDATORS_REL / "formula_dsl.py").read_text(encoding="utf-8")
    for token in ("eval(", "exec(", "os.system"):
        if token in src:
            raise TestFailure(f"formula_dsl.py must not contain '{token}'")

    # --- correct arithmetic, Decimal precision ------------------------------
    value, unit = dsl.evaluate(
        "eligible_customers * reachable_share * arpa_year",
        {
            "eligible_customers": (Decimal("5000"), "count"),
            "reachable_share": (Decimal("0.1"), "ratio"),
            "arpa_year": (Decimal("250"), "EUR/count"),
        },
    )
    if value != Decimal("125000"):
        raise TestFailure(f"bottom-up product wrong: {value}")
    if dsl.unit_to_str(unit) != "EUR":
        raise TestFailure(f"unit algebra wrong: {dsl.unit_to_str(unit)}")

    value, _ = dsl.evaluate(
        "a + b", {"a": (Decimal("0.1"), "ratio"), "b": (Decimal("0.2"), "ratio")})
    if value != Decimal("0.3"):
        raise TestFailure(f"Decimal contract violated: 0.1 + 0.2 = {value}")

    value, unit = dsl.evaluate(
        "-(price - cost) / price",
        {"price": (Decimal("100"), "EUR"), "cost": (Decimal("120"), "EUR")})
    if value != Decimal("0.2") or dsl.unit_to_str(unit) != "ratio":
        raise TestFailure("unary minus / parentheses / EUR÷EUR ratio failed")

    # --- whitelist: every non-whitelisted construct is invalid_formula ------
    two = {"a": (Decimal("2"), "ratio"), "b": (Decimal("3"), "ratio")}
    for bad in (
        "min(a, b)",
        "a ** b",
        "a.__class__",
        "__import__('os').system('echo pwned')",
        "a[0]",
        "(lambda: 1)()",
        "a if a else b",
        "{1: 2}",
        "a; b",
        "a * undeclared_name",
        "import os",
        "",
    ):
        expect_error(dsl, "invalid_formula", bad, two, f"whitelist: {bad!r}")

    # --- rejected formulas must have no side effects -------------------------
    with tempfile.TemporaryDirectory(prefix="bpo-dsl-") as tmp:
        marker = Path(tmp) / "pwned.txt"
        evil = (
            f"__import__('pathlib').Path({json.dumps(str(marker))})"
            ".write_text('x')"
        )
        expect_error(dsl, "invalid_formula", evil, two, "side-effect formula")
        if marker.exists():
            raise TestFailure("rejected formula produced a side effect")

    # --- DSL edge-case codes -------------------------------------------------
    expect_error(
        dsl, "division_by_zero", "a / b",
        {"a": (Decimal("1"), "EUR"), "b": (Decimal("0"), "ratio")},
        "division by zero")
    expect_error(
        dsl, "missing_required", "a + b",
        {"a": (Decimal("1"), "EUR"), "b": (None, "EUR")},
        "null due variable")
    expect_error(
        dsl, "unit_mismatch", "a + b",
        {"a": (Decimal("1"), "EUR"), "b": (Decimal("1"), "count")},
        "EUR + count")

    # --- expected-unit control in recompute ----------------------------------
    values = {"spend": (Decimal("1000"), "EUR"),
              "customers": (Decimal("40"), "count")}
    dsl.recompute_check("spend / customers", values,
                        Decimal("25"), "EUR/count")
    try:
        dsl.recompute_check("spend / customers", values, Decimal("25"), "EUR")
    except dsl.FormulaError as exc:
        if exc.code != "unit_mismatch":
            raise TestFailure(f"result-unit control: got {exc.code}")
    else:
        raise TestFailure("result-unit control did not fire")

    # --- rounding ROUND_HALF_UP and per-unit tolerance ------------------------
    if dsl.round_to_unit(Decimal("100.005"), "EUR") != Decimal("100.01"):
        raise TestFailure("EUR rounding is not ROUND_HALF_UP to 2 decimals")
    if dsl.round_to_unit(Decimal("0.1234565"), "ratio") != Decimal("0.123457"):
        raise TestFailure("ratio rounding is not ROUND_HALF_UP to 6 decimals")
    ok = {"a": (Decimal("100.004"), "EUR")}
    dsl.recompute_check("a", ok, Decimal("100.00"), "EUR")  # within 0.01
    try:
        dsl.recompute_check("a", {"a": (Decimal("100.03"), "EUR")},
                            Decimal("100.00"), "EUR")
    except dsl.FormulaError as exc:
        if exc.code != "value_mismatch":
            raise TestFailure(f"tolerance breach code: {exc.code}")
    else:
        raise TestFailure("EUR tolerance breach not detected")
    counts = {"a": (Decimal("10"), "count"), "b": (Decimal("3"), "count")}
    dsl.recompute_check("a - b", counts, Decimal("7"), "count")
    try:
        dsl.recompute_check("a - b", counts, Decimal("7.5"), "count")
    except dsl.FormulaError as exc:
        if exc.code != "value_mismatch":
            raise TestFailure(f"count exactness code: {exc.code}")
    else:
        raise TestFailure("count must be exact (integer, zero tolerance)")

    # --- percentages canonical in [0,1] --------------------------------------
    if not dsl.is_canonical_ratio(Decimal("0")):
        raise TestFailure("0 is a canonical ratio")
    if not dsl.is_canonical_ratio(Decimal("1")):
        raise TestFailure("1 is a canonical ratio")
    if dsl.is_canonical_ratio(Decimal("1.5")):
        raise TestFailure("1.5 must not be a canonical ratio")
    if dsl.is_canonical_ratio(Decimal("-0.1")):
        raise TestFailure("-0.1 must not be a canonical ratio")

    # ----------------------------------------------------------- unary plus
    # unary plus non è nel contratto della DSL (solo il meno unario)
    expect_error(dsl, "invalid_formula", "+a", two, "unary plus")
    expect_error(dsl, "invalid_formula", "a * +b", two, "embedded unary plus")

    # literal decimale ad alta precisione: Decimal dal sorgente esatto,
    # nessun passaggio intermedio attraverso float
    value, _ = dsl.evaluate("0.30000000000000000000000004", {})
    if value != Decimal("0.30000000000000000000000004"):
        raise TestFailure(
            f"high-precision literal lost digits through float: {value}")
    value, _ = dsl.evaluate(
        "a * 1.000000000000000000000001",
        {"a": (Decimal("1"), "ratio")})
    if value != Decimal("1.000000000000000000000001"):
        raise TestFailure(
            f"literal multiplier collapsed through float: {value}")

    # limiti espliciti: lunghezza, numero nodi, profondità AST
    expect_error(dsl, "invalid_formula", "a + " * 400 + "a", two,
                 "formula too long")
    expect_error(dsl, "invalid_formula", " + ".join(["a"] * 120), two,
                 "too many AST nodes")
    deep = "-" * 120 + "a"
    expect_error(dsl, "invalid_formula", deep, two, "AST too deep")
    for limit in ("MAX_FORMULA_LENGTH", "MAX_FORMULA_NODES",
                  "MAX_FORMULA_DEPTH"):
        if not isinstance(getattr(dsl, limit, None), int):
            raise TestFailure(f"explicit DSL limit missing: {limit}")

    # normalizzazione degli errori: mai RecursionError grezzo dal modulo
    try:
        dsl.parse_formula("(" * 900 + "a" + ")" * 900)
    except dsl.FormulaError:
        pass
    except RecursionError:
        raise TestFailure("RecursionError leaked instead of FormulaError")
    else:
        raise TestFailure("oversized nesting must raise FormulaError")

    # count: risultato matematicamente intero richiesto prima del rounding
    near = {"a": (Decimal("10"), "count"), "b": (Decimal("3"), "ratio")}
    try:
        dsl.recompute_check("a / b", near, Decimal("3"), "count")
    except dsl.FormulaError as exc:
        if exc.code != "value_mismatch":
            raise TestFailure(f"non-integer count code: {exc.code}")
    else:
        raise TestFailure(
            "count result 3.33… was rounded into a false match")
    exact = {"a": (Decimal("10"), "count"), "b": (Decimal("2"), "ratio")}
    dsl.recompute_check("a / b", exact, Decimal("5"), "count")

    # ------------------------------------------------ count non intero
    # Un count DICHIARATO non intero non deve collassare in un falso match per
    # rounding: computed 10/2=5 è intero, ma declared 4.5 (arrotondato a 5)
    # deve essere rifiutato — computed E declared devono essere entrambi interi.
    half = {"a": (Decimal("10"), "count"), "b": (Decimal("2"), "ratio")}
    try:
        dsl.recompute_check("a / b", half, Decimal("4.5"), "count")
    except dsl.FormulaError as exc:
        if exc.code != "value_mismatch":
            raise TestFailure(f"non-integer declared count code: {exc.code}")
    else:
        raise TestFailure(
            "declared count 4.5 was rounded into a false integer match")
    # anche declared 7.5 vs computed 7 resta rifiutato
    counts2 = {"a": (Decimal("10"), "count"), "b": (Decimal("3"), "count")}
    try:
        dsl.recompute_check("a - b", counts2, Decimal("7.5"), "count")
    except dsl.FormulaError as exc:
        if exc.code != "value_mismatch":
            raise TestFailure(f"declared count 7.5 code: {exc.code}")
    else:
        raise TestFailure("declared non-integer count 7.5 must be rejected")

    # Il fallback di _literal_decimal NON deve mai passare da un float AST: un
    # letterale float senza segmento sorgente disponibile è rifiutato, non
    # ricostruito (con perdita) da str(node.value).
    import ast as _ast
    float_node = _ast.Constant(value=0.1)  # nessuna posizione sorgente
    try:
        dsl._literal_decimal("", float_node)
    except dsl.FormulaError:
        pass
    else:
        raise TestFailure(
            "float literal without source segment fell back through float AST")
    int_node = _ast.Constant(value=7)  # gli interi restano esatti anche senza
    if dsl._literal_decimal("", int_node) != Decimal("7"):
        raise TestFailure("integer literal fallback must stay exact")

    # MemoryError normalizzato in OGNI fase della DSL (parse, evaluate,
    # recompute): mai un MemoryError grezzo che sfugge dal modulo.
    def _raise_memory(*_a, **_k):
        raise MemoryError("simulated")

    orig_depth = dsl._ast_depth
    dsl._ast_depth = _raise_memory
    try:
        dsl.parse_formula("a + b")
    except dsl.FormulaError:
        pass
    except MemoryError:
        raise TestFailure("MemoryError leaked from the parse phase")
    else:
        raise TestFailure("simulated MemoryError in parse must raise FormulaError")
    finally:
        dsl._ast_depth = orig_depth

    orig_lit = dsl._literal_decimal
    dsl._literal_decimal = _raise_memory
    try:
        dsl.evaluate("1 + 2", {})
    except dsl.FormulaError:
        pass
    except MemoryError:
        raise TestFailure("MemoryError leaked from the evaluate phase")
    else:
        raise TestFailure("simulated MemoryError in evaluate must raise FormulaError")
    finally:
        dsl._literal_decimal = orig_lit

    orig_round = dsl.round_to_unit
    dsl.round_to_unit = _raise_memory
    try:
        dsl.recompute_check("a", {"a": (Decimal("1"), "EUR")},
                            Decimal("1"), "EUR")
    except dsl.FormulaError:
        pass
    except MemoryError:
        raise TestFailure("MemoryError leaked from the recompute phase")
    else:
        raise TestFailure("simulated MemoryError in recompute must raise FormulaError")
    finally:
        dsl.round_to_unit = orig_round

    # ratio dichiarato fuori [0,1] nel percorso generico di ricalcolo
    ratios = {"a": (Decimal("0.2"), "ratio"), "b": (Decimal("0.5"), "ratio")}
    try:
        dsl.recompute_check("a - b", ratios, Decimal("-0.3"), "ratio")
    except dsl.FormulaError as exc:
        if exc.code != "ratio_out_of_bounds":
            raise TestFailure(f"negative ratio code: {exc.code}")
    else:
        raise TestFailure("negative declared ratio must not persist")
    big = {"a": (Decimal("1.2"), "ratio"), "b": (Decimal("0.5"), "ratio")}
    try:
        dsl.recompute_check("a + b", big, Decimal("1.7"), "ratio")
    except dsl.FormulaError as exc:
        if exc.code != "ratio_out_of_bounds":
            raise TestFailure(f"ratio above one code: {exc.code}")
    else:
        raise TestFailure("ratio above 1 must not persist")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        run(Path(args.root).resolve())
    except TestFailure as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    print("PASS: T-DSL-SAFETY formula DSL safety contract")


if __name__ == "__main__":
    main()
