#!/usr/bin/env python3
"""validate_unit_economics — unit economics Stage 5.

Stage 5-6, fasi egress (overlay candidate ⊕ canonico a Stage 5) e impact
(solo canonico). Verifica sul business model: prezzo = un solo ASS- di
pricing con valore strettamente positivo (price_not_positive, scoped al
pricing come la positività stretta di validate_market_arithmetic lo è a
TAM/SAM/SOM); il prezzo eventualmente duplicato nello structured-output coincide con l'ASS-pricing (price_conflict — la
divergenza è un conflitto, mai una scrittura); ricavo come formula di
driver (revenue_not_derived); contribution margin derived con formula
prezzo − costi variabili unitari, con il prezzo tra le variables
(margin_not_derived / margin_missing_price) e ricalcolato dalla DSL
sull'intera catena. Un margine negativo ma coerente è un warning
metodologico (negative_margin), non un errore aritmetico.

Il CAC NON è verificato qui (appartiene a validate_funnel_arithmetic,
Stage 6): uno Stage 5 senza funnel non fallisce (not_yet_required).
Puro e read-only; exit 0/1/2/3.
"""
from decimal import Decimal

import _framework as fw
import formula_dsl as dsl
import validate_market_arithmetic as market

BM_STAGE = "05_business-model"
STRUCTURED_REL = f"{BM_STAGE}/structured-output.json"


def _load_business_doc(args, state, report, x_ordinal):
    """Structured output di Stage 5: dal candidate se è lo stage validato in
    egress, altrimenti dal canonico (Stage 6 e fase impact). Se il canonico
    non esiste e lo Stage 5 non è ancora completato, il dato non è dovuto
    (not_yet_required), mai un FAIL."""
    if args.phase == "egress" and x_ordinal == 5:
        path = args.candidate / "structured-output.json"
        if not path.exists():
            report.add_error(
                "missing_required", ref=args.stage,
                message=("structured-output.json dovuto in egress di "
                         "Stage 5: business model mancante"),
                expected="structured-output.json nel candidate",
                actual="assente")
            return None
        return fw.read_candidate_json(path, "structured-output.json")
    path = state.project / STRUCTURED_REL
    if not path.exists():
        completed = state.status.get("completed_stages", [])
        if isinstance(completed, list) and BM_STAGE in completed:
            report.add_error(
                "missing_required", ref=BM_STAGE,
                message=(f"{STRUCTURED_REL} assente ma lo Stage 5 risulta "
                         "completato: business model canonico dovuto"),
                expected=STRUCTURED_REL,
                actual="assente")
        else:
            report.add_warning(
                "not_yet_required", ref=BM_STAGE,
                message="business model canonico non ancora dovuto")
        return None
    return fw.read_canonical_json(path, STRUCTURED_REL)


def _resolve(name, ref, overlay, report):
    if not isinstance(ref, str) or not fw.ANY_ASS_RE.match(ref):
        report.add_error(
            "missing_required", ref=ref if isinstance(ref, str) else None,
            message=f"business_model.{name} assente o non id ASS-*/P-ASS-*",
            expected="riferimento ASS-*/P-ASS-*",
            actual=repr(ref))
        return None
    entry = fw.resolve_ref(ref, overlay)
    if entry is None:
        report.add_error(
            "unresolved_ref", ref=ref,
            message=f"business_model.{name}: riferimento non risolvibile")
        return None
    return entry


def _strict_decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value))


def _has_formula(entry):
    derivation = entry.get("derivation")
    if not isinstance(derivation, dict):
        return False
    variables = derivation.get("variables")
    return bool(derivation.get("formula")) and \
        isinstance(variables, dict) and bool(variables)


def check(args, config, state, report):
    name = "validate_unit_economics"
    x_ordinal = fw.stage_ordinal(args.stage, config)
    applicable = config["validators"][name]
    if x_ordinal not in applicable["stages"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile allo stage {args.stage}")
    if args.phase not in applicable["phases"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile alla fase {args.phase}")

    doc = _load_business_doc(args, state, report, x_ordinal)
    if doc is None:
        return
    overlay = fw.build_overlay(state, args.candidate)

    model = doc.get("business_model") if isinstance(doc, dict) else None
    if not isinstance(model, dict):
        report.add_error(
            "missing_required", ref=args.stage,
            message="business_model assente nello structured-output",
            expected="business_model con pricing_ref/revenue_ref/"
                     "contribution_margin_ref",
            actual="assente")
        return

    refs = {}
    entries = {}
    for key in ("pricing_ref", "revenue_ref", "contribution_margin_ref"):
        refs[key] = model.get(key)
        entries[key] = _resolve(key, refs[key], overlay, report)

    # Prezzo: un solo ASS-, strettamente positivo (scope: pricing)
    pricing = entries["pricing_ref"]
    price_value = None
    if pricing is not None:
        price_value = _strict_decimal(pricing.get("value"))
        if price_value is None or price_value <= 0:
            report.add_error(
                "price_not_positive", ref=refs["pricing_ref"],
                message=("prezzo non numerico o non positivo: il pricing "
                         f"richiede un numero > 0 "
                         f"({pricing.get('value')!r})"),
                expected="valore > 0",
                actual=repr(pricing.get("value")))
            price_value = None

    # T-PRICE: il prezzo duplicato nel business model coincide con
    # l'ASS-pricing, altrimenti conflitto (mai scrittura canonica)
    literal = model.get("price")
    if literal is not None and pricing is not None:
        literal_dec = _strict_decimal(literal)
        if literal_dec is None:
            report.add_error(
                "price_conflict", ref=refs["pricing_ref"],
                message=f"business_model.price non numerico: {literal!r}",
                expected="numero uguale all'ASS-pricing",
                actual=repr(literal))
        elif price_value is not None:
            tolerance = dsl.tolerance_for_unit(pricing.get("unit"),
                                               config.get("tolerances"))
            if abs(literal_dec - price_value) > tolerance:
                report.add_error(
                    "price_conflict", ref=refs["pricing_ref"],
                    message=("INCOERENZA: business_model.price "
                             f"({literal_dec}) diverge dall'ASS-pricing "
                             f"({price_value}): stessa variabile, un solo "
                             "valore"),
                    expected=str(price_value),
                    actual=str(literal_dec))

    # Ricavo come formula di driver (mai un numero a mano)
    revenue = entries["revenue_ref"]
    if revenue is not None and not _has_formula(revenue):
        report.add_error(
            "revenue_not_derived", ref=refs["revenue_ref"],
            message=("revenue senza derivation.formula/variables: il ricavo "
                     "è una formula di driver, non un numero"),
            expected="kind derived con formula e variables",
            actual=str(revenue.get("kind")))

    # Contribution margin: derived, prezzo tra le variables, ricalcolato
    margin = entries["contribution_margin_ref"]
    if margin is not None:
        if not _has_formula(margin):
            report.add_error(
                "margin_not_derived", ref=refs["contribution_margin_ref"],
                message=("contribution margin senza derivation: 'margine a "
                         "parole' o numero a mano non ammessi"),
                expected="kind derived con formula e variables",
                actual=str(margin.get("kind")))
        else:
            variables = margin["derivation"]["variables"].values()
            if refs["pricing_ref"] not in variables:
                report.add_error(
                    "margin_missing_price",
                    ref=refs["contribution_margin_ref"],
                    message=("contribution margin che non referenzia il "
                             "pricing_ref tra le variables: la formula è "
                             "prezzo − costi variabili unitari"),
                    expected=f"{refs['pricing_ref']} in derivation.variables",
                    actual=str(sorted(variables)))
            margin_value = _strict_decimal(margin.get("value"))
            if margin_value is not None and margin_value < 0:
                report.add_warning(
                    "negative_margin", ref=refs["contribution_margin_ref"],
                    message=("contribution margin negativo: unit economics "
                             "strutturalmente in perdita (rosso "
                             "metodologico, da motivare al gate)"))

    # Ricalcolo DSL dell'intera catena raggiungibile
    market._recompute_chain(
        [r for r in refs.values() if isinstance(r, str)],
        overlay, config, report)


if __name__ == "__main__":
    fw.run_validator("validate_unit_economics", check)
