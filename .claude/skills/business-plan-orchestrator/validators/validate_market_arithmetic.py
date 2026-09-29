#!/usr/bin/env python3
"""validate_market_arithmetic — aritmetica di mercato Stage 4.

Stage 4-6, fasi egress (overlay candidate ⊕ canonico) e impact (solo
canonico). Verifica: SOM derived con method bottom_up e ricalcolato dalla
DSL; ordinamento SOM ≤ SAM ≤ TAM sui valori canonici riconciliati (unità
omogenee); TAM/SAM con almeno una stima top-down o triangolazione
indipendente; riconciliazione obbligatoria quando ≥2 metodi (
weighted_average con pesi ratio che sommano a 1, selected_ref con
rationale, decision_ref DEC- e valore coerente con la stima selezionata);
ricalcolo di tutti i derivati raggiungibili dalla catena TAM/SAM/SOM;
competitive landscape con tutte le categorie valutate (none_identified solo
con research_notes e rationale). Puro e read-only; exit 0/1/2/3;
invalid_formula è sempre un difetto del candidate (exit 1), mai exit 2.
"""
from decimal import Decimal

import _framework as fw
import formula_dsl as dsl

MARKET_STAGE = "04_market-and-competition"
STRUCTURED_REL = f"{MARKET_STAGE}/structured-output.json"

CATEGORIES = ("direct", "indirect", "substitutes", "internal",
              "non_consumption", "status_quo")
INDEPENDENT_METHODS = ("top_down", "triangulation")
RECONCILIATION_STRATEGIES = ("weighted_average", "selected_ref")


def _load_market_doc(args, state, report, x_ordinal):
    """Structured output di Stage 4: dal candidate se è lo stage validato in
    egress, altrimenti dal canonico (stage 5-6 e fase impact)."""
    if args.phase == "egress" and x_ordinal == 4:
        path = args.candidate / "structured-output.json"
        if not path.exists():
            report.add_error(
                "missing_required", ref=args.stage,
                message=("structured-output.json dovuto in egress di "
                         "Stage 4: market model e landscape mancanti"),
                expected="structured-output.json nel candidate",
                actual="assente")
            return None
        return fw.read_candidate_json(path, "structured-output.json")
    path = state.project / STRUCTURED_REL
    if not path.exists():
        report.add_error(
            "missing_required", ref=MARKET_STAGE,
            message=(f"{STRUCTURED_REL} assente: il modello di mercato "
                     "canonico è dovuto dagli stage 4+"),
            expected=STRUCTURED_REL,
            actual="assente")
        return None
    return fw.read_canonical_json(path, STRUCTURED_REL)


def _entry_value(entry):
    value = entry.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return Decimal(str(value))
    except ArithmeticError:
        return None


def _derivation(entry):
    derivation = entry.get("derivation")
    return derivation if isinstance(derivation, dict) else None


def _is_reconciliation(entry):
    derivation = _derivation(entry)
    return bool(derivation) and derivation.get("method") == "reconciliation"


def _resolve_market_ref(name, ref, overlay, report):
    if not isinstance(ref, str) or not fw.ANY_ASS_RE.match(ref):
        report.add_error(
            "missing_required", ref=ref if isinstance(ref, str) else None,
            message=f"market_model.{name} assente o non id ASS-*/P-ASS-*",
            expected="riferimento ASS-*/P-ASS-*",
            actual=repr(ref))
        return None
    entry = fw.resolve_ref(ref, overlay)
    if entry is None:
        report.add_error(
            "unresolved_ref", ref=ref,
            message=f"market_model.{name}: riferimento non risolvibile")
        return None
    return entry


def _check_positive_market_value(name, entry, ref, report):
    """TAM/SAM/SOM sono numeri strettamente positivi.

    Il vincolo è scoped alle grandezze di mercato (non a tutte le
    assumptions EUR/count): bool, string, null, zero e negativi sono
    difetti del candidate e vanno respinti prima di ogni mutazione
    canonica."""
    value = entry.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        report.add_error(
            "market_value_not_positive", ref=ref,
            message=(f"{name}: valore non numerico "
                     f"({type(value).__name__}): le grandezze di mercato "
                     "richiedono un numero > 0"),
            expected="numero strettamente positivo",
            actual=repr(value))
        return
    if Decimal(str(value)) <= 0:
        report.add_error(
            "market_value_not_positive", ref=ref,
            message=(f"{name}: valore non positivo ({value}): TAM/SAM/SOM "
                     "devono essere > 0"),
            expected="valore > 0",
            actual=str(value))


def _recompute_chain(roots, overlay, config, report):
    """Ricalcola ogni derivato raggiungibile dalla catena."""
    decimals = config.get("decimals")
    tolerances = config.get("tolerances")
    visited = set()
    stack = [ref for ref in roots if isinstance(ref, str)]
    while stack:
        ref = stack.pop()
        if ref in visited:
            continue
        visited.add(ref)
        entry = fw.resolve_ref(ref, overlay)
        if not isinstance(entry, dict):
            continue
        derivation = _derivation(entry)
        if not derivation:
            continue
        variables = derivation.get("variables")
        if isinstance(variables, dict):
            stack.extend(v for v in variables.values()
                         if isinstance(v, str))
        selected = derivation.get("selected_ref")
        if isinstance(selected, str):
            stack.append(selected)
        formula = derivation.get("formula")
        if formula is None:
            continue
        if not isinstance(variables, dict) or not variables:
            report.add_error(
                "invalid", ref=ref,
                message="derivation con formula senza mappa variables")
            continue
        values = {}
        unresolved = False
        for var_name, var_ref in variables.items():
            member = fw.resolve_ref(var_ref, overlay) \
                if isinstance(var_ref, str) else None
            if not isinstance(member, dict):
                # riferimento rotto: già FAIL di referential integrity;
                # qui si salta il ricalcolo per non duplicare il rumore
                unresolved = True
                break
            values[var_name] = (member.get("value"), member.get("unit"))
        if unresolved:
            continue
        try:
            dsl.recompute_check(formula, values, entry.get("value"),
                                entry.get("unit"), decimals=decimals,
                                tolerances=tolerances)
        except dsl.FormulaError as exc:
            report.add_error(
                exc.code, ref=ref,
                message=f"ricalcolo di {ref} fallito: {exc.message}")


def _estimates(overlay, prefix):
    """Stime per una grandezza: variable ^<prefix>_ escluse le
    riconciliazioni."""
    out = []
    for entry in overlay.values():
        if not isinstance(entry, dict):
            continue
        variable = entry.get("variable")
        if not isinstance(variable, str) or \
                not variable.startswith(f"{prefix}_"):
            continue
        if _is_reconciliation(entry):
            continue
        out.append(entry)
    return out


def _check_reconciliation(name, ref_entry, ref, estimates, overlay, config,
                          report):
    """Con ≥2 stime la variabile canonica è una riconciliazione con
    strategia ammessa; pesi a somma 1 o selected_ref motivato e tracciato."""
    if len(estimates) >= 2 and not _is_reconciliation(ref_entry):
        report.add_error(
            "reconciliation_missing", ref=ref,
            message=(f"{name}: {len(estimates)} stime multi-metodo senza "
                     "variabile di riconciliazione canonica"),
            expected="derivation.method == reconciliation sul valore "
                     "canonico",
            actual=str(_derivation(ref_entry) and
                       _derivation(ref_entry).get("method")))
        return
    if not _is_reconciliation(ref_entry):
        return
    derivation = _derivation(ref_entry)
    strategy = derivation.get("strategy")
    if strategy not in RECONCILIATION_STRATEGIES:
        report.add_error(
            "reconciliation_invalid", ref=ref,
            message=(f"{name}: strategia di riconciliazione non ammessa: "
                     f"{strategy!r} (riconciliazione dei metodi di sizing)"),
            expected=" | ".join(RECONCILIATION_STRATEGIES),
            actual=str(strategy))
        return
    variables = derivation.get("variables")
    if not isinstance(variables, dict) or not variables:
        report.add_error(
            "reconciliation_invalid", ref=ref,
            message=f"{name}: riconciliazione senza mappa variables")
        return
    if strategy == "weighted_average":
        weight_sum = Decimal(0)
        weights_found = False
        for var_ref in variables.values():
            member = fw.resolve_ref(var_ref, overlay) \
                if isinstance(var_ref, str) else None
            if not isinstance(member, dict) or member.get("unit") != "ratio":
                continue
            value = _entry_value(member)
            if value is None:
                continue
            weights_found = True
            weight_sum += value
        tolerance = dsl.tolerance_for_unit("ratio",
                                           config.get("tolerances"))
        if not weights_found or abs(weight_sum - Decimal(1)) > tolerance:
            report.add_error(
                "reconciliation_invalid", ref=ref,
                message=(f"{name}: i pesi della weighted_average devono "
                         f"sommare a 1 (somma: {weight_sum})"),
                expected="somma pesi == 1",
                actual=str(weight_sum))
        return
    # selected_ref
    selected = derivation.get("selected_ref")
    if not isinstance(selected, str) or selected not in variables.values():
        report.add_error(
            "reconciliation_invalid", ref=ref,
            message=(f"{name}: selected_ref assente o non tra le stime "
                     "valutate in variables"),
            expected="selected_ref in variables",
            actual=repr(selected))
        return
    rationale = ref_entry.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        report.add_error(
            "reconciliation_invalid", ref=ref,
            message=f"{name}: selected_ref senza rationale")
    decision_ref = ref_entry.get("decision_ref")
    if not isinstance(decision_ref, str) or \
            not decision_ref.startswith("DEC-"):
        report.add_error(
            "reconciliation_invalid", ref=ref,
            message=(f"{name}: selected_ref richiede decision_ref DEC- "
                     "obbligatorio"),
            expected="decision_ref ^DEC-",
            actual=repr(decision_ref))
    selected_entry = fw.resolve_ref(selected, overlay)
    if isinstance(selected_entry, dict):
        own = _entry_value(ref_entry)
        chosen = _entry_value(selected_entry)
        if own is not None and chosen is not None:
            tolerance = dsl.tolerance_for_unit(ref_entry.get("unit"),
                                               config.get("tolerances"))
            if abs(own - chosen) > tolerance:
                report.add_error(
                    "value_mismatch", ref=ref,
                    message=(f"{name}: valore riconciliato {own} diverso "
                             f"dalla stima selezionata {chosen} "
                             "(riconciliazione dei metodi di sizing)"),
                    expected=str(chosen),
                    actual=str(own))


def _check_independent_method(name, ref_entry, ref, estimates, report):
    """TAM/SAM richiedono top-down o triangolazione indipendente."""
    pool = list(estimates)
    if not _is_reconciliation(ref_entry) and ref_entry not in pool:
        pool.append(ref_entry)
    for entry in pool:
        derivation = _derivation(entry)
        if derivation is None:
            return  # stima primaria: fonte indipendente dal modello
        if derivation.get("method") in INDEPENDENT_METHODS:
            return
    report.add_error(
        "triangulation_missing", ref=ref,
        message=(f"{name}: nessuna stima top-down o triangolazione "
                 "indipendente (obbligatoria per TAM/SAM)"),
        expected="≥1 stima primaria o con method top_down/triangulation",
        actual="solo stime bottom_up/derivate dal modello")


def _check_landscape(doc, report):
    landscape = doc.get("competitive_landscape") \
        if isinstance(doc, dict) else None
    categories = landscape.get("categories") \
        if isinstance(landscape, dict) else None
    if not isinstance(categories, dict):
        report.add_error(
            "category_not_evaluated", ref=MARKET_STAGE,
            message=("competitive_landscape.categories assente: ogni "
                     "categoria va valutata"),
            expected=", ".join(CATEGORIES),
            actual="assente")
        return
    for category in CATEGORIES:
        block = categories.get(category)
        if not isinstance(block, dict):
            report.add_error(
                "category_not_evaluated", ref=category,
                message=(f"categoria competitor non valutata: {category} "
                         "(la categoria assente è FAIL)"),
                expected="competitors[] oppure none_identified motivato",
                actual="assente")
            continue
        competitors = block.get("competitors")
        if isinstance(competitors, list) and competitors:
            for i, competitor in enumerate(competitors):
                if not isinstance(competitor, dict) or \
                        not str(competitor.get("name", "")).strip() or \
                        not str(competitor.get("assessment", "")).strip():
                    report.add_error(
                        "invalid", ref=category,
                        message=(f"{category}.competitors[{i}]: ogni "
                                 "competitor richiede name e assessment "
                                 "(categoria valutata)"))
            continue
        if block.get("result") == "none_identified":
            for field in ("research_notes", "rationale"):
                value = block.get(field)
                if not isinstance(value, str) or not value.strip():
                    report.add_error(
                        "none_identified_unmotivated", ref=category,
                        message=(f"{category}: none_identified senza "
                                 f"{field} obbligatorio"),
                        expected=f"{field} non vuoto",
                        actual="assente o vuoto")
            continue
        report.add_error(
            "category_not_evaluated", ref=category,
            message=(f"categoria {category} presente ma non valutata: "
                     "né competitors né none_identified"),
            expected="competitors[] oppure none_identified motivato",
            actual=str(sorted(block.keys())))


def check(args, config, state, report):
    name = "validate_market_arithmetic"
    x_ordinal = fw.stage_ordinal(args.stage, config)
    applicable = config["validators"][name]
    if x_ordinal not in applicable["stages"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile allo stage {args.stage}")
    if args.phase not in applicable["phases"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile alla fase {args.phase}")

    doc = _load_market_doc(args, state, report, x_ordinal)
    if doc is None:
        return
    overlay = fw.build_overlay(state, args.candidate)

    market_model = doc.get("market_model") if isinstance(doc, dict) else None
    if not isinstance(market_model, dict):
        report.add_error(
            "missing_required", ref=args.stage,
            message="market_model assente nello structured-output",
            expected="market_model con tam_ref/sam_ref/som_ref",
            actual="assente")
        _check_landscape(doc if isinstance(doc, dict) else {}, report)
        return

    refs = {}
    entries = {}
    for key in ("tam_ref", "sam_ref", "som_ref"):
        refs[key] = market_model.get(key)
        entries[key] = _resolve_market_ref(key, refs[key], overlay, report)

    # positività stretta delle grandezze di mercato, prima di ogni
    # altro controllo aritmetico (il TM respinge su FAIL senza mutazioni)
    for label, key in (("TAM", "tam_ref"), ("SAM", "sam_ref"),
                       ("SOM", "som_ref")):
        if entries[key] is not None:
            _check_positive_market_value(label, entries[key], refs[key],
                                         report)

    # SOM: sempre derived bottom_up
    som = entries["som_ref"]
    if som is not None:
        derivation = _derivation(som)
        if derivation is None or derivation.get("method") != "bottom_up":
            report.add_error(
                "som_not_bottom_up", ref=refs["som_ref"],
                message=("SOM senza derivazione bottom-up: il driver-based "
                         "bottom-up è obbligatorio"),
                expected="derivation.method == bottom_up",
                actual=str(derivation and derivation.get("method")))

    # Ricalcolo dell'intera catena raggiungibile
    _recompute_chain([r for r in refs.values() if isinstance(r, str)],
                     overlay, config, report)

    # Riconciliazione multi-metodo e triangolazione indipendente
    for label, key, prefix in (("TAM", "tam_ref", "tam"),
                               ("SAM", "sam_ref", "sam")):
        entry = entries[key]
        if entry is None:
            continue
        estimates = _estimates(overlay, prefix)
        _check_reconciliation(label, entry, refs[key], estimates, overlay,
                              config, report)
        _check_independent_method(label, entry, refs[key], estimates, report)

    # Ordinamento SOM ≤ SAM ≤ TAM sui valori canonici
    values = {}
    units = set()
    for key in ("tam_ref", "sam_ref", "som_ref"):
        entry = entries[key]
        if entry is None:
            continue
        value = _entry_value(entry)
        if value is None:
            report.add_error(
                "invalid", ref=refs[key],
                message=f"market_model.{key}: valore non numerico")
            continue
        values[key] = value
        units.add(entry.get("unit"))
    if len(values) == 3:
        if len(units) != 1:
            report.add_error(
                "unit_mismatch", ref=refs["som_ref"],
                message=("TAM/SAM/SOM con unità disomogenee: "
                         f"{sorted(str(u) for u in units)}"),
                expected="stessa unità sulle tre grandezze",
                actual=str(sorted(str(u) for u in units)))
        elif not (values["som_ref"] <= values["sam_ref"]
                  <= values["tam_ref"]):
            report.add_error(
                "market_ordering", ref=refs["som_ref"],
                message=("ordinamento violato: richiesto SOM ≤ SAM ≤ TAM "
                         f"(SOM={values['som_ref']}, SAM={values['sam_ref']},"
                         f" TAM={values['tam_ref']})"),
                expected="SOM <= SAM <= TAM",
                actual=(f"{values['som_ref']} / {values['sam_ref']} / "
                        f"{values['tam_ref']}"))

    _check_landscape(doc, report)


if __name__ == "__main__":
    fw.run_validator("validate_market_arithmetic", check)
