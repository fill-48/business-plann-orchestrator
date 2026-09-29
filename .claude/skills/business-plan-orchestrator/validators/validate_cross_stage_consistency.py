#!/usr/bin/env python3
"""validate_cross_stage_consistency — coerenza cross-stage (Stage 4-8).

Stage 5-6, fasi egress e impact. Verifica le invarianti cross-stage:

- il modello di mercato canonico di Stage 4 esiste e il SOM è risolvibile
  (dovuto dagli stage 5+);
- il business model (candidate a Stage 5 egress, canonico altrove) ha un
  pricing_ref risolvibile: un solo ASS- di prezzo per tutta la catena;
- il sales funnel (candidate a Stage 6 egress, canonico altrove — se non
  ancora dovuto: warning not_yet_required, mai FAIL) usa lo STESSO
  pricing_ref del business model (price_divergence: il prezzo divergente
  cross-stage è un conflitto, mai una media o una riscrittura);
- la capacità GTM (capacity_revenue_ref, EUR) sostiene il SOM canonico:
  capacità < SOM → gtm_capacity_below_som (detect del ciclo di conflitto
  cross-stage: BLOCK di
  Stage 6, conflitto esplicito sull'ASS- del SOM, conferma utente, update
  con history + DEC-, impact su Stage 4-6, resubmit — mai riscrittura
  silenziosa dello Stage 4).

Stage 5-9: la coerenza attraversa anche gli stage 7-8 —
ops_capacity_below_gtm, ops_cost_divergence e
headcount_capacity_incoherent. Questi check sono three-state: su un
progetto che non è ancora arrivato allo stage che ne porta il dato non
producono mai un FAIL.

Puro e read-only; exit 0/1/2/3.
"""
from decimal import Decimal

import _framework as fw

MARKET_STAGE = "04_market-and-competition"
BM_STAGE = "05_business-model"
GTM_STAGE = "06_go-to-market"
OPS_STAGE = "07_operations-and-ip"
TEAM_STAGE = "08_team-and-governance"


def _strict_decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value))


def _resolve(label, ref, overlay, report):
    if not isinstance(ref, str) or not fw.ANY_ASS_RE.match(ref):
        report.add_error(
            "missing_required", ref=ref if isinstance(ref, str) else None,
            message=f"{label} assente o non id ASS-*/P-ASS-*",
            expected="riferimento ASS-*/P-ASS-*",
            actual=repr(ref))
        return None
    entry = fw.resolve_ref(ref, overlay)
    if entry is None:
        report.add_error(
            "unresolved_ref", ref=ref,
            message=f"{label}: riferimento non risolvibile")
        return None
    return entry


def _canonical_doc(state, stage_rel, key, report, required, ref_label):
    path = state.project / stage_rel / "structured-output.json"
    if not path.exists():
        if required:
            report.add_error(
                "missing_required", ref=ref_label,
                message=(f"{stage_rel}/structured-output.json assente: "
                         "dovuto per la coerenza cross-stage"),
                expected=f"{stage_rel}/structured-output.json",
                actual="assente")
        else:
            report.add_warning(
                "not_yet_required", ref=ref_label,
                message=f"{key} canonico non ancora dovuto")
        return None
    doc = fw.read_canonical_json(path,
                                 f"{stage_rel}/structured-output.json")
    block = doc.get(key) if isinstance(doc, dict) else None
    if not isinstance(block, dict):
        report.add_error(
            "missing_required", ref=ref_label,
            message=f"{key} assente nello structured-output di {stage_rel}",
            expected=key,
            actual="assente")
        return None
    return block


def _candidate_doc(args, key, report):
    path = args.candidate / "structured-output.json"
    if not path.exists():
        report.add_error(
            "missing_required", ref=args.stage,
            message=("structured-output.json dovuto nel candidate in "
                     f"egress di {args.stage}"),
            expected="structured-output.json nel candidate",
            actual="assente")
        return None
    doc = fw.read_candidate_json(path, "structured-output.json")
    block = doc.get(key) if isinstance(doc, dict) else None
    if not isinstance(block, dict):
        report.add_error(
            "missing_required", ref=args.stage,
            message=f"{key} assente nello structured-output del candidate",
            expected=key,
            actual="assente")
        return None
    return block


def _load_ops_model(args, state, x_ordinal):
    """Operations model dello Stage 7: dal candidate in egress dello Stage 7,
    dal canonico altrove. None se non ancora dovuto (progetti a stage < 7 o
    Stage 7 non ancora prodotto): three-state, mai FAIL."""
    if args.phase == "egress" and x_ordinal == 7:
        path = args.candidate / "structured-output.json"
        if not path.exists():
            return None
        doc = fw.read_candidate_json(path, "structured-output.json")
    else:
        path = state.project / OPS_STAGE / "structured-output.json"
        if not path.exists():
            return None
        doc = fw.read_canonical_json(
            path, f"{OPS_STAGE}/structured-output.json")
    return doc.get("operations_model") if isinstance(doc, dict) else None


def _load_team_model(args, state, x_ordinal):
    """Team model dello Stage 8: dal candidate in egress dello Stage 8, dal
    canonico altrove. None se non ancora dovuto (progetti a stage < 8 o
    Stage 8 non ancora prodotto): three-state, mai FAIL."""
    if args.phase == "egress" and x_ordinal == 8:
        path = args.candidate / "structured-output.json"
        if not path.exists():
            return None
        doc = fw.read_candidate_json(path, "structured-output.json")
    else:
        path = state.project / TEAM_STAGE / "structured-output.json"
        if not path.exists():
            return None
        doc = fw.read_canonical_json(
            path, f"{TEAM_STAGE}/structured-output.json")
    return doc.get("team_governance") if isinstance(doc, dict) else None


def _roles_with_headcount(team):
    """Mappa `ROLE-` → (porta headcount reale, processi coperti).

    Un ruolo porta headcount solo se è ricoperto da una **persona**, oppure se
    è una **posizione aperta** con la propria riga di `hiring_plan` e un
    driver di costo: una posizione aperta che nessuno ha budgetato non è
    capacità organizzativa, è un'intenzione. La forma del driver (risolvibilità
    dell'`ASS-`, unità, ricalcolo) resta di `validate_team_and_governance`:
    qui conta solo che il meccanismo di hiring esista."""
    budgeted = set()
    plan = team.get("hiring_plan")
    for item in plan if isinstance(plan, list) else []:
        if not isinstance(item, dict):
            continue
        role_ref = item.get("role_ref")
        driver = item.get("cost_driver_ref")
        if isinstance(role_ref, str) and isinstance(driver, str) and \
                fw.ANY_ASS_RE.match(driver):
            budgeted.add(role_ref)

    out = {}
    roles = team.get("roles")
    for role in roles if isinstance(roles, list) else []:
        if not isinstance(role, dict):
            continue
        rid = role.get("id")
        if not isinstance(rid, str):
            continue
        person = role.get("person")
        open_position = role.get("open_position")
        staffed = bool(isinstance(person, str) and person.strip())
        planned = bool(isinstance(open_position, str)
                       and open_position.strip() and rid in budgeted)
        covers = role.get("covers_processes")
        out[rid] = (staffed or planned,
                    covers if isinstance(covers, list) else [])
    return out


def _check_headcount_consistency(args, state, report, x_ordinal, ops):
    """headcount_capacity_incoherent.

    Gli FTE dichiarati allo Stage 8 devono sostenere i processi core che lo
    Stage 7 dichiara di fare **in casa**. La soglia è strutturale e non
    numerica: un processo core `make` che nessun
    ruolo copre con headcount reale — né una persona, né una posizione aperta
    finanziata — è un buco di esecuzione, non un arrotondamento di organico.
    Un processo `buy` o `partner` è esternalizzato per scelta dichiarata e non
    entra nel confronto.

    La direzione opposta e più debole — «esiste almeno un ruolo che lo copre»
    — è di `validate_team_and_governance` (`core_process_unowned`) e vive solo
    nell'egress dello Stage 8. Qui il controllo è più forte e resta attivo
    anche allo Stage 9 e in fase impact, dove quell'egress è pass-through."""
    team = _load_team_model(args, state, x_ordinal)
    if not isinstance(team, dict) or not isinstance(ops, dict):
        return  # three-state: manca l'uno o l'altro dato -> nessun check

    roles = _roles_with_headcount(team)
    processes = ops.get("core_processes")
    for proc in processes if isinstance(processes, list) else []:
        if not isinstance(proc, dict) or proc.get("make_buy_partner") != "make":
            continue
        pid = proc.get("id")
        covered = any(has_headcount and isinstance(pid, str) and pid in covers
                      for has_headcount, covers in roles.values())
        if covered:
            continue
        report.add_error(
            "headcount_capacity_incoherent", ref=pid,
            message=("processo core dichiarato `make` senza alcun ruolo che "
                     "lo copra con headcount reale: nessuna persona assegnata "
                     "e nessuna posizione aperta finanziata nel piano "
                     "assunzioni. Gli FTE dello Stage 8 non sostengono il "
                     "modello operativo dello Stage 7: o il processo "
                     "viene esternalizzato, o il team lo copre davvero"),
            expected="un ROLE- con persona, oppure una posizione aperta con "
                     "riga di hiring_plan e cost_driver_ref",
            actual="nessun headcount reale")


def _check_operations_consistency(args, state, overlay, report, x_ordinal,
                                  funnel, ops):
    """Invarianti cross-stage introdotte dallo Stage 7:

    - ops_capacity_below_gtm: la capacità operativa canonica (Stage 7) deve
      sostenere i volumi GTM (customers_out dello Stage 6) — simmetrico a
      gtm_capacity_below_som (stesso ciclo di conflitto cross-stage);
    - ops_cost_divergence: un costo operativo unitario che duplica una
      variabile di costo esistente con valore diverso è un conflitto (una
      variabile, un solo ASS-), mai una seconda fonte di verità."""
    if not isinstance(ops, dict):
        return  # three-state: nessun dato Stage 7 -> nessun check

    # ops_capacity_below_gtm: capacità operativa vs volumi GTM (customers_out)
    capacity_ref = ops.get("capacity_ref")
    capacity = fw.resolve_ref(capacity_ref, overlay) \
        if isinstance(capacity_ref, str) else None
    customers = None
    if isinstance(funnel, dict):
        customers_ref = funnel.get("customers_out_ref")
        customers = fw.resolve_ref(customers_ref, overlay) \
            if isinstance(customers_ref, str) else None
    if isinstance(capacity, dict) and isinstance(customers, dict) and \
            capacity.get("unit") == customers.get("unit"):
        cap_value = _strict_decimal(capacity.get("value"))
        cust_value = _strict_decimal(customers.get("value"))
        if cap_value is not None and cust_value is not None and \
                cap_value < cust_value:
            report.add_error(
                "ops_capacity_below_gtm", ref=capacity_ref,
                message=("capacità operativa insufficiente a servire i volumi "
                         f"GTM: {cap_value} < {cust_value}. Ciclo di "
                         "capacità operativa: BLOCK "
                         "Stage 7, conflitto sull'ASS- di capacità o dei "
                         "volumi, conferma utente, update con history, impact "
                         "— mai riscrittura silenziosa dei volumi GTM"),
                expected=f"capacità >= {cust_value}",
                actual=str(cap_value))

    # ops_cost_divergence: costo operativo che duplica una variabile di costo
    # esistente con valore diverso (stessa semantica di price_divergence)
    cost_refs = ops.get("unit_ops_cost_refs")
    if not isinstance(cost_refs, list):
        return
    by_variable = {}
    for entry in overlay.values():
        if not isinstance(entry, dict):
            continue
        variable = entry.get("variable")
        if isinstance(variable, str):
            by_variable.setdefault(variable, []).append(entry)
    for ref in cost_refs:
        cost = fw.resolve_ref(ref, overlay) if isinstance(ref, str) else None
        if not isinstance(cost, dict):
            continue
        variable = cost.get("variable")
        cost_value = _strict_decimal(cost.get("value"))
        if not isinstance(variable, str) or cost_value is None:
            continue
        for sibling in by_variable.get(variable, []):
            if sibling.get("id") == cost.get("id"):
                continue
            sibling_value = _strict_decimal(sibling.get("value"))
            if sibling_value is not None and sibling_value != cost_value:
                report.add_error(
                    "ops_cost_divergence", ref=ref,
                    message=("INCOERENZA: il costo operativo "
                             f"{variable!r} ({cost_value}) duplica "
                             f"{sibling.get('id')} ({sibling_value}) con "
                             "valore diverso: una variabile, un solo "
                             "ASS-"),
                    expected=str(sibling_value),
                    actual=str(cost_value))
                break


def check(args, config, state, report):
    name = "validate_cross_stage_consistency"
    x_ordinal = fw.stage_ordinal(args.stage, config)
    applicable = config["validators"][name]
    if x_ordinal not in applicable["stages"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile allo stage {args.stage}")
    if args.phase not in applicable["phases"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile alla fase {args.phase}")

    overlay = fw.build_overlay(state, args.candidate)
    completed = state.status.get("completed_stages", [])
    if not isinstance(completed, list):
        raise fw.CanonicalStateError("completed_stages non è una lista")

    # Stage 4 canonico: sempre dovuto dagli stage 5+
    market = _canonical_doc(state, MARKET_STAGE, "market_model", report,
                            required=True, ref_label=MARKET_STAGE)
    som = None
    if market is not None:
        som = _resolve("market_model.som_ref", market.get("som_ref"),
                       overlay, report)

    # Business model: candidate a Stage 5 egress, canonico altrove
    if args.phase == "egress" and x_ordinal == 5:
        business = _candidate_doc(args, "business_model", report)
    else:
        business = _canonical_doc(
            state, BM_STAGE, "business_model", report,
            required=BM_STAGE in completed, ref_label=BM_STAGE)
    business_pricing = None
    if business is not None:
        business_pricing = business.get("pricing_ref")
        _resolve("business_model.pricing_ref", business_pricing, overlay,
                 report)

    # Sales funnel: candidate a Stage 6 egress; canonico altrove; se non
    # ancora dovuto -> not_yet_required (three-state)
    if args.phase == "egress" and x_ordinal == 6:
        funnel = _candidate_doc(args, "sales_funnel", report)
    else:
        funnel = _canonical_doc(
            state, GTM_STAGE, "sales_funnel", report,
            required=GTM_STAGE in completed, ref_label=GTM_STAGE)

    # Coerenza organico ↔ modello operativo. Non dipende dal
    # funnel: si valuta anche quando il GTM canonico manca, altrimenti un
    # difetto upstream nasconderebbe un buco di esecuzione a valle.
    ops = _load_ops_model(args, state, x_ordinal)
    _check_headcount_consistency(args, state, report, x_ordinal, ops)

    if funnel is None:
        return

    # Prezzo unico cross-stage: stesso ASS- del business model
    funnel_pricing = funnel.get("pricing_ref")
    _resolve("sales_funnel.pricing_ref", funnel_pricing, overlay, report)
    if isinstance(funnel_pricing, str) and \
            isinstance(business_pricing, str) and \
            funnel_pricing != business_pricing:
        report.add_error(
            "price_divergence", ref=funnel_pricing,
            message=("INCOERENZA: il funnel referenzia un prezzo "
                     f"({funnel_pricing}) diverso dal pricing del business "
                     f"model ({business_pricing}): una variabile, un solo "
                     "ASS-"),
            expected=str(business_pricing),
            actual=str(funnel_pricing))

    # Capacità GTM vs SOM canonico (detect del ciclo di conflitto cross-stage)
    capacity = _resolve("sales_funnel.capacity_revenue_ref",
                        funnel.get("capacity_revenue_ref"), overlay, report)
    if capacity is not None and som is not None:
        cap_unit = capacity.get("unit")
        som_unit = som.get("unit")
        if cap_unit != som_unit:
            report.add_error(
                "unit_mismatch", ref=funnel.get("capacity_revenue_ref"),
                message=(f"capacità GTM ({cap_unit!r}) e SOM "
                         f"({som_unit!r}) con unità diverse: confronto "
                         "impossibile"),
                expected=str(som_unit),
                actual=str(cap_unit))
        else:
            cap_value = _strict_decimal(capacity.get("value"))
            som_value = _strict_decimal(som.get("value"))
            if cap_value is not None and som_value is not None and \
                    cap_value < som_value:
                report.add_error(
                    "gtm_capacity_below_som",
                    ref=market.get("som_ref"),
                    message=("capacità GTM insufficiente a sostenere il SOM "
                             f"canonico: {cap_value} < {som_value}. Ciclo "
                             "di conflitto: BLOCK Stage 6, conflitto "
                             "esplicito "
                             "sull'ASS- del SOM, conferma utente, update "
                             "con history, impact Stage 4-6 — mai "
                             "riscrittura silenziosa dello Stage 4"),
                    expected=f"capacità >= {som_value}",
                    actual=str(cap_value))

    # Invarianti cross-stage dello Stage 7: capacità operativa vs
    # volumi GTM e costi operativi non divergenti. Three-state per i progetti
    # a stage < 7 (nessun dato Stage 7 -> nessun check).
    _check_operations_consistency(args, state, overlay, report, x_ordinal,
                                  funnel, ops)


if __name__ == "__main__":
    fw.run_validator("validate_cross_stage_consistency", check)
