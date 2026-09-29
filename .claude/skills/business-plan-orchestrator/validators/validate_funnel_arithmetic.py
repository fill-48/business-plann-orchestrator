#!/usr/bin/env python3
"""validate_funnel_arithmetic — funnel e CAC Stage 6.

Stage 6, fasi egress (candidate) e impact (canonico). Verifica sul sales
funnel: leads numerici e positivi; ogni tasso di conversione è un
riferimento ASS-/P-ASS- con unit ratio e valore in [0,1]
(rate_out_of_bounds); customers_out è derived e coincide col prodotto
leads × Π(tassi) ricalcolato indipendentemente dal validator
(funnel_product_mismatch, non un semplice recompute della formula
dichiarata); coerenza CAC = spend / customers_out con unità EUR/count
(cac_mismatch / unit_mismatch); churn esplicito dovuto a Stage 6
(missing_required); ricalcolo DSL dell'intera catena raggiungibile. In fase impact senza funnel canonico e con lo Stage 6 non ancora
completato il dato non è dovuto (not_yet_required). Puro e read-only;
exit 0/1/2/3.
"""
from decimal import Decimal

import _framework as fw
import formula_dsl as dsl
import validate_market_arithmetic as market

GTM_STAGE = "06_go-to-market"
STRUCTURED_REL = f"{GTM_STAGE}/structured-output.json"

CAC_UNIT = {"EUR": 1, "count": -1}


def _load_funnel_doc(args, state, report, x_ordinal):
    if args.phase == "egress" and x_ordinal == 6:
        path = args.candidate / "structured-output.json"
        if not path.exists():
            report.add_error(
                "missing_required", ref=args.stage,
                message=("structured-output.json dovuto in egress di "
                         "Stage 6: sales funnel mancante"),
                expected="structured-output.json nel candidate",
                actual="assente")
            return None
        return fw.read_candidate_json(path, "structured-output.json")
    path = state.project / STRUCTURED_REL
    if not path.exists():
        completed = state.status.get("completed_stages", [])
        if isinstance(completed, list) and GTM_STAGE in completed:
            report.add_error(
                "missing_required", ref=GTM_STAGE,
                message=(f"{STRUCTURED_REL} assente ma lo Stage 6 risulta "
                         "completato: sales funnel canonico dovuto"),
                expected=STRUCTURED_REL,
                actual="assente")
        else:
            report.add_warning(
                "not_yet_required", ref=GTM_STAGE,
                message="sales funnel canonico non ancora dovuto")
        return None
    return fw.read_canonical_json(path, STRUCTURED_REL)


def _resolve(name, ref, overlay, report):
    if not isinstance(ref, str) or not fw.ANY_ASS_RE.match(ref):
        report.add_error(
            "missing_required", ref=ref if isinstance(ref, str) else None,
            message=f"sales_funnel.{name} assente o non id ASS-*/P-ASS-*",
            expected="riferimento ASS-*/P-ASS-*",
            actual=repr(ref))
        return None
    entry = fw.resolve_ref(ref, overlay)
    if entry is None:
        report.add_error(
            "unresolved_ref", ref=ref,
            message=f"sales_funnel.{name}: riferimento non risolvibile")
        return None
    return entry


def _strict_decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value))


def _check_ratio(name, entry, ref, report):
    """Tasso canonico: unit ratio, valore numerico in [0,1]."""
    if entry.get("unit") != "ratio":
        report.add_error(
            "unit_mismatch", ref=ref,
            message=f"{name}: un tasso di conversione ha unit ratio, "
                    f"trovato {entry.get('unit')!r}",
            expected="ratio",
            actual=str(entry.get("unit")))
        return None
    value = _strict_decimal(entry.get("value"))
    if value is None or value < 0 or value > 1:
        report.add_error(
            "rate_out_of_bounds", ref=ref,
            message=(f"{name}: tasso fuori dall'intervallo canonico [0,1]: "
                     f"{entry.get('value')!r} (frazione decimale, mai %)"),
            expected="0 <= value <= 1",
            actual=repr(entry.get("value")))
        return None
    return value


def check(args, config, state, report):
    name = "validate_funnel_arithmetic"
    x_ordinal = fw.stage_ordinal(args.stage, config)
    applicable = config["validators"][name]
    if x_ordinal not in applicable["stages"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile allo stage {args.stage}")
    if args.phase not in applicable["phases"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile alla fase {args.phase}")

    doc = _load_funnel_doc(args, state, report, x_ordinal)
    if doc is None:
        return
    overlay = fw.build_overlay(state, args.candidate)

    funnel = doc.get("sales_funnel") if isinstance(doc, dict) else None
    if not isinstance(funnel, dict):
        report.add_error(
            "missing_required", ref=args.stage,
            message="sales_funnel assente nello structured-output",
            expected="sales_funnel con leads/stages/customers_out/cac/churn",
            actual="assente")
        return

    leads = _resolve("leads_ref", funnel.get("leads_ref"), overlay, report)
    leads_value = None
    if leads is not None:
        leads_value = _strict_decimal(leads.get("value"))
        if leads_value is None or leads_value <= 0:
            report.add_error(
                "invalid", ref=funnel.get("leads_ref"),
                message=("leads non numerici o non positivi: il funnel "
                         f"parte da un volume reale ({leads.get('value')!r})"),
                expected="valore > 0",
                actual=repr(leads.get("value")))
            leads_value = None

    stages = funnel.get("stages")
    rates = []
    if not isinstance(stages, list) or not stages:
        report.add_error(
            "missing_required", ref=args.stage,
            message=("sales_funnel.stages assente o vuoto: ogni tasso di "
                     "conversione è un ASS- referenziato"),
            expected="stages[] con rate_ref",
            actual="assente o vuoto")
    else:
        for i, step in enumerate(stages):
            label = f"stages[{i}]"
            if not isinstance(step, dict):
                report.add_error(
                    "invalid", ref=args.stage,
                    message=f"{label}: voce del funnel non oggetto")
                continue
            entry = _resolve(f"{label}.rate_ref", step.get("rate_ref"),
                             overlay, report)
            if entry is None:
                continue
            value = _check_ratio(label, entry, step.get("rate_ref"), report)
            if value is not None:
                rates.append(value)

    # customers_out = leads * Π(tassi): ricalcolo INDIPENDENTE dal validator
    customers = _resolve("customers_out_ref",
                         funnel.get("customers_out_ref"), overlay, report)
    customers_value = None
    if customers is not None:
        if not isinstance(customers.get("derivation"), dict):
            report.add_error(
                "invalid", ref=funnel.get("customers_out_ref"),
                message="customers_out senza derivation: è un derivato",
                expected="kind derived",
                actual=str(customers.get("kind")))
        customers_value = _strict_decimal(customers.get("value"))
        if customers_value is not None and leads_value is not None and \
                isinstance(stages, list) and stages and \
                len(rates) == len(stages):
            product = leads_value
            for rate in rates:
                product *= rate
            unit = customers.get("unit")
            product_r = dsl.round_to_unit(product, unit,
                                          config.get("decimals"))
            declared_r = dsl.round_to_unit(customers_value, unit,
                                           config.get("decimals"))
            tolerance = dsl.tolerance_for_unit(unit,
                                               config.get("tolerances"))
            if abs(product_r - declared_r) > tolerance:
                report.add_error(
                    "funnel_product_mismatch",
                    ref=funnel.get("customers_out_ref"),
                    message=("customers_out dichiarato "
                             f"({declared_r}) diverso dal prodotto del "
                             f"funnel leads × Π(tassi) = {product_r} "
                             "(ricalcolo dai driver)"),
                    expected=str(product_r),
                    actual=str(declared_r))

    # CAC = spend / customers_out, unità EUR/count
    spend = _resolve("spend_ref", funnel.get("spend_ref"), overlay, report)
    cac = _resolve("cac_ref", funnel.get("cac_ref"), overlay, report)
    if cac is not None:
        cac_unit = cac.get("unit")
        if dsl.parse_unit(cac_unit) != CAC_UNIT:
            report.add_error(
                "unit_mismatch", ref=funnel.get("cac_ref"),
                message=(f"CAC con unità {cac_unit!r}: atteso EUR/count "
                         "(spesa per cliente acquisito)"),
                expected="EUR/count",
                actual=str(cac_unit))
        elif spend is not None and customers_value is not None:
            spend_value = _strict_decimal(spend.get("value"))
            cac_value = _strict_decimal(cac.get("value"))
            if spend_value is not None and cac_value is not None:
                if customers_value == 0:
                    report.add_error(
                        "cac_mismatch", ref=funnel.get("cac_ref"),
                        message=("customers_out = 0: il CAC non è "
                                 "calcolabile (divisione per zero)"),
                        expected="customers_out > 0",
                        actual="0")
                else:
                    computed = dsl.round_to_unit(
                        spend_value / customers_value, cac_unit,
                        config.get("decimals"))
                    declared = dsl.round_to_unit(cac_value, cac_unit,
                                                 config.get("decimals"))
                    tolerance = dsl.tolerance_for_unit(
                        cac_unit, config.get("tolerances"))
                    if abs(computed - declared) > tolerance:
                        report.add_error(
                            "cac_mismatch", ref=funnel.get("cac_ref"),
                            message=(f"CAC dichiarato ({declared}) diverso "
                                     f"da spend / customers_out = {computed} "
                                     "(ricalcolo dai driver)"),
                            expected=str(computed),
                            actual=str(declared))

    # churn esplicito dovuto a Stage 6
    churn_ref = funnel.get("churn_ref")
    if churn_ref is None:
        report.add_error(
            "missing_required", ref=args.stage,
            message=("sales_funnel.churn_ref assente: il churn è dovuto a "
                     "Stage 6, ignorarlo falsa la retention"),
            expected="churn_ref verso un ASS- ratio",
            actual="assente")
    else:
        churn = _resolve("churn_ref", churn_ref, overlay, report)
        if churn is not None:
            _check_ratio("churn", churn, churn_ref, report)

    # Ricalcolo DSL dell'intera catena raggiungibile
    roots = [funnel.get(k) for k in ("customers_out_ref", "cac_ref",
                                     "capacity_revenue_ref")]
    market._recompute_chain([r for r in roots if isinstance(r, str)],
                            overlay, config, report)


if __name__ == "__main__":
    fw.run_validator("validate_funnel_arithmetic", check)
