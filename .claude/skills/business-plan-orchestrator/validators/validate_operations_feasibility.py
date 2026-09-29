#!/usr/bin/env python3
"""validate_operations_feasibility — operations & IP Stage 7.

Stage 7-9, fasi egress (overlay candidate ⊕ canonico allo Stage 7) e impact
(solo canonico). Verifica il modello operativo dello Stage 7:

- capacità operativa = un `ASS-` **derived** ricalcolabile dalla Formula DSL
  (`capacity_not_derived` / `value_mismatch`), con valore > 0 (`invalid`) e
  unità coerente con i volumi GTM canonici (`unit_mismatch`);
- ogni processo core con `make_buy_partner` ∈ {make, buy, partner}
  (`core_process_unsourced`);
- ogni costo operativo unitario è un **riferimento** a un `ASS-` esistente
  (dei COGS Stage 5), mai un letterale (`ops_cost_not_ref`);
- ogni dipendenza critica **valutata**: `mitigation`, oppure
  `none_identified` + `rationale` (pattern «valutato o escluso con
  motivazione») — altrimenti
  `dependency_category_not_assessed`;
- ogni requisito normativo valutato allo stesso modo
  (`regulatory_not_assessed`);
- ogni asset IP con `protection` dichiarata e strategia IP esplicita
  (`ip_protection_missing`);
- ogni `risk_ref` risolvibile nel `risk-register` (`unresolved_ref`).

La tipizzazione `entity_type` delle definizioni `OPS-` e la risoluzione dei
namespace tipizzati sono di `validate_referential_integrity`: qui non si
duplicano. Puro e read-only; exit 0/1/2/3. Three-state: per progetti a
stage < 7 i dati Stage 7 sono `not_yet_required`, mai FAIL (compatibilità
con i progetti che non hanno ancora raggiunto lo Stage 7).
"""
from decimal import Decimal

import _framework as fw
import validate_market_arithmetic as market

OPS_STAGE = "07_operations-and-ip"
GTM_STAGE = "06_go-to-market"
STRUCTURED_REL = f"{OPS_STAGE}/structured-output.json"
MAKE_BUY_PARTNER = ("make", "buy", "partner")


def _strict_decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value))


def _load_ops_doc(args, state, report, x_ordinal):
    """Structured output di Stage 7: dal candidate in egress dello Stage 7,
    dal canonico in impact (l'egress enforce solo allo Stage 7; agli Stage
    8-9
    la catena capacità gira in impact sul canonico). Se il canonico non
    esiste e lo Stage 7 non è ancora completato, il dato non è dovuto
    (`not_yet_required`), mai un FAIL (three-state)."""
    if args.phase == "egress":
        path = args.candidate / "structured-output.json"
        if not path.exists():
            report.add_error(
                "missing_required", ref=args.stage,
                message=("structured-output.json dovuto in egress di Stage 7: "
                         "operations model mancante"),
                expected="structured-output.json nel candidate",
                actual="assente")
            return None
        return fw.read_candidate_json(path, "structured-output.json")
    path = state.project / STRUCTURED_REL
    if not path.exists():
        completed = state.status.get("completed_stages", [])
        if isinstance(completed, list) and OPS_STAGE in completed:
            report.add_error(
                "missing_required", ref=OPS_STAGE,
                message=(f"{STRUCTURED_REL} assente ma lo Stage 7 risulta "
                         "completato: operations model canonico dovuto"),
                expected=STRUCTURED_REL,
                actual="assente")
        else:
            report.add_warning(
                "not_yet_required", ref=OPS_STAGE,
                message="operations model canonico non ancora dovuto")
        return None
    return fw.read_canonical_json(path, STRUCTURED_REL)


def _resolve_ass(name, ref, overlay, report):
    if not isinstance(ref, str) or not fw.ANY_ASS_RE.match(ref):
        report.add_error(
            "missing_required", ref=ref if isinstance(ref, str) else None,
            message=f"operations_model.{name} assente o non id ASS-*/P-ASS-*",
            expected="riferimento ASS-*/P-ASS-*",
            actual=repr(ref))
        return None
    entry = fw.resolve_ref(ref, overlay)
    if entry is None:
        report.add_error(
            "unresolved_ref", ref=ref,
            message=f"operations_model.{name}: riferimento non risolvibile")
        return None
    return entry


def _has_formula(entry):
    derivation = entry.get("derivation")
    if not isinstance(derivation, dict):
        return False
    variables = derivation.get("variables")
    return bool(derivation.get("formula")) and \
        isinstance(variables, dict) and bool(variables)


def _assessed(item, value_field, none_field="none_identified",
              rationale_field="rationale"):
    """Pattern «valutato o escluso»: valutato (campo di valutazione non
    vuoto) oppure
    none_identified esplicito con rationale. Il silenzio non è valutazione."""
    if not isinstance(item, dict):
        return False
    value = item.get(value_field)
    if isinstance(value, str) and value.strip():
        return True
    if item.get(none_field) is True:
        rationale = item.get(rationale_field)
        return isinstance(rationale, str) and bool(rationale.strip())
    return False


def _gtm_volume_unit(state, overlay):
    """Unità dei volumi GTM canonici (customers_out dello Stage 6), per il
    confronto di coerenza con la capacità operativa."""
    path = state.project / GTM_STAGE / "structured-output.json"
    if not path.exists():
        return None
    doc = fw.read_canonical_json(path, f"{GTM_STAGE}/structured-output.json")
    funnel = doc.get("sales_funnel") if isinstance(doc, dict) else None
    if not isinstance(funnel, dict):
        return None
    ref = funnel.get("customers_out_ref")
    entry = fw.resolve_ref(ref, overlay) if isinstance(ref, str) else None
    return entry.get("unit") if isinstance(entry, dict) else None


def _load_risk_ids(state):
    path = state.project / "shared" / "risk-register.json"
    if not path.exists():
        return set()
    register = fw.read_canonical_json(path, "shared/risk-register.json")
    if not isinstance(register, list):
        raise fw.CanonicalStateError("risk-register.json non è una lista")
    return {entry.get("id") for entry in register if isinstance(entry, dict)}


def _check_core_processes(model, report):
    core = model.get("core_processes")
    if not isinstance(core, list) or not core:
        report.add_error(
            "missing_required", ref="operations_model.core_processes",
            message=("processi core assenti o vuoti: l'operating model "
                     "richiede almeno un processo core"),
            expected="core_processes[] non vuoto",
            actual="assente" if core is None else str(core))
        return
    for proc in core:
        pid = proc.get("id") if isinstance(proc, dict) else None
        mbp = proc.get("make_buy_partner") if isinstance(proc, dict) else None
        if mbp not in MAKE_BUY_PARTNER:
            report.add_error(
                "core_process_unsourced", ref=pid,
                message=("processo core senza make/buy/partner valorizzato: "
                         "ogni processo dichiara come è coperto"),
                expected="make | buy | partner",
                actual=repr(mbp))
        if isinstance(proc, dict) and proc.get("bottleneck") is True:
            report.add_warning(
                "bottleneck_unmitigated_low", ref=pid,
                message=("processo core dichiarato collo di bottiglia: "
                         "verificare capacità e mitigazione"))


def _check_capacity(model, overlay, state, config, report):
    capacity_ref = model.get("capacity_ref")
    capacity = _resolve_ass("capacity_ref", capacity_ref, overlay, report)
    if capacity is None:
        return
    if not _has_formula(capacity):
        report.add_error(
            "capacity_not_derived", ref=capacity_ref,
            message=("capacità operativa non derivata: dev'essere un ASS- "
                     "derived ricalcolabile dai driver, mai un "
                     "letterale"),
            expected="derivation.formula + variables",
            actual=str(capacity.get("kind")))
    else:
        market._recompute_chain([capacity_ref], overlay, config, report)
    cap_value = _strict_decimal(capacity.get("value"))
    if cap_value is None or cap_value <= 0:
        report.add_error(
            "invalid", ref=capacity_ref,
            message=(f"capacità operativa non positiva o non numerica "
                     f"({capacity.get('value')!r}): serve una capacità > 0"),
            expected="valore > 0",
            actual=repr(capacity.get("value")))
        return
    gtm_unit = _gtm_volume_unit(state, overlay)
    if gtm_unit is not None and capacity.get("unit") != gtm_unit:
        report.add_error(
            "unit_mismatch", ref=capacity_ref,
            message=(f"unità della capacità ({capacity.get('unit')!r}) "
                     f"incompatibile con i volumi GTM ({gtm_unit!r}): "
                     "confronto capacità/domanda impossibile"),
            expected=str(gtm_unit),
            actual=str(capacity.get("unit")))


def _check_ops_costs(model, overlay, report):
    costs = model.get("unit_ops_cost_refs")
    if costs is None:
        report.add_error(
            "missing_required", ref="operations_model.unit_ops_cost_refs",
            message="unit_ops_cost_refs assente: i costi operativi unitari "
                    "vanno referenziati agli ASS- COGS dello Stage 5",
            expected="array di riferimenti ASS-*",
            actual="assente")
        return
    if not isinstance(costs, list):
        return
    for ref in costs:
        if not isinstance(ref, str) or not fw.ANY_ASS_RE.match(ref):
            report.add_error(
                "ops_cost_not_ref", ref=ref if isinstance(ref, str) else None,
                message=("costo operativo unitario letterale invece di un "
                         "riferimento ASS-: il dato vive una sola "
                         "volta"),
                expected="riferimento ASS-*",
                actual=repr(ref))
        elif fw.resolve_ref(ref, overlay) is None:
            report.add_error(
                "ops_cost_not_ref", ref=ref,
                message=("riferimento del costo operativo non risolvibile: "
                         "ASS- COGS Stage 5 inesistente"))


def _check_dependencies(model, report):
    deps = model.get("critical_dependencies")
    if not isinstance(deps, list):
        return
    for dep in deps:
        did = dep.get("id") if isinstance(dep, dict) else None
        if not _assessed(dep, "mitigation"):
            report.add_error(
                "dependency_category_not_assessed", ref=did,
                message=("dipendenza critica non valutata: serve una "
                         "mitigation, oppure none_identified + rationale "
                         "(categoria valutata)"),
                expected="mitigation | none_identified+rationale",
                actual="non valutata")
        elif isinstance(dep, dict) and dep.get("single_source") is True and \
                isinstance(dep.get("mitigation"), str):
            report.add_warning(
                "single_source_dependency", ref=did,
                message=("dipendenza critica single-source con mitigazione "
                         "dichiarata: rischio di concentrazione da monitorare"))


def _check_regulatory(model, report):
    regs = model.get("regulatory_requirements")
    if not isinstance(regs, list):
        return
    for reg in regs:
        req = reg.get("requirement") if isinstance(reg, dict) else None
        if not _assessed(reg, "assessment"):
            report.add_error(
                "regulatory_not_assessed", ref=None,
                message=(f"requisito regolatorio senza valutazione: {req!r} "
                         "richiede assessment, oppure none_identified + "
                         "rationale (categoria valutata)"),
                expected="assessment | none_identified+rationale",
                actual="non valutato")


def _check_ip(model, report):
    ip = model.get("ip_strategy")
    if not isinstance(ip, dict):
        report.add_error(
            "ip_protection_missing", ref="operations_model.ip_strategy",
            message=("ip_strategy assente: la strategia IP dev'essere "
                     "esplicita (asset e protezione del know-how)"),
            expected="ip_strategy con assets[]",
            actual="assente")
        return
    assets = ip.get("assets")
    if not isinstance(assets, list):
        return
    for asset in assets:
        aid = asset.get("id") if isinstance(asset, dict) else None
        protection = asset.get("protection") if isinstance(asset, dict) \
            else None
        if not isinstance(protection, str) or not protection.strip():
            report.add_error(
                "ip_protection_missing", ref=aid,
                message=("asset IP senza protection dichiarata: ogni asset "
                         "core dichiara la propria protezione"),
                expected="protection non vuota",
                actual=repr(protection))


def _check_risk_refs(model, state, report):
    risks = model.get("risk_refs")
    if not isinstance(risks, list):
        return
    risk_ids = _load_risk_ids(state)
    for ref in risks:
        if isinstance(ref, str) and ref not in risk_ids:
            report.add_error(
                "unresolved_ref", ref=ref,
                message=("risk_ref non presente nel risk-register: ogni "
                         "rischio operativo referenziato dev'essere "
                         "registrato (RISK-*)"))


def check(args, config, state, report):
    name = "validate_operations_feasibility"
    x_ordinal = fw.stage_ordinal(args.stage, config)
    applicable = config["validators"][name]
    if x_ordinal not in applicable["stages"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile allo stage {args.stage}")
    if args.phase not in applicable["phases"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile alla fase {args.phase}")

    # l'egress dell'operations model enforce SOLO allo Stage 7. Agli
    # Stage 8-9 l'egress è un pass-through — la coerenza della catena capacità
    # sul canonico Stage 7 è verificata in fase impact, non ri-enforced qui.
    if args.phase == "egress" and x_ordinal != 7:
        return

    doc = _load_ops_doc(args, state, report, x_ordinal)
    if doc is None:
        return
    model = doc.get("operations_model") if isinstance(doc, dict) else None
    if not isinstance(model, dict):
        report.add_error(
            "missing_required", ref=args.stage,
            message="operations_model assente nello structured-output",
            expected="operations_model con core_processes/capacity_ref/…",
            actual="assente")
        return
    overlay = fw.build_overlay(state, args.candidate)

    _check_core_processes(model, report)
    _check_capacity(model, overlay, state, config, report)
    _check_ops_costs(model, overlay, report)
    _check_dependencies(model, report)
    _check_regulatory(model, report)
    _check_ip(model, report)
    _check_risk_refs(model, state, report)


if __name__ == "__main__":
    fw.run_validator("validate_operations_feasibility", check)
