#!/usr/bin/env python3
"""validate_milestone_chain — roadmap e milestone Stage 9.

Stage 9, fasi egress (overlay candidate ⊕ canonico) e impact (solo canonico).
Verifica che la roadmap sia davvero **eseguibile**, non un calendario in prosa:

- `depends_on` forma un **DAG**: nessun riferimento irrisolto
  (`milestone_dependency_unresolved`), nessun ciclo — auto-dipendenza inclusa
  (`milestone_cycle_detected`);
- le date sono ISO-8601 (`invalid` altrimenti), `target_date >= start_date` e
  `start_date >= max(target_date delle dipendenze)`: nessuna milestone chiude
  prima del proprio prerequisito e il confine incluso (start = target della
  dipendenza) è ammesso (`milestone_date_incoherent`);
- ogni milestone ha un owner che risolve a un `ROLE-` **canonico dello
  Stage 8** (`milestone_owner_unresolved`), un costo che è un **riferimento**
  ad `ASS-`/`P-ASS-` esistente e mai un importo inline
  (`milestone_cost_unresolved`), criteri di successo non vuoti, una regola
  go/no-go e un exit criterion (`milestone_criteria_missing`);
- ogni categoria del vocabolario canonico (technical, commercial,
  operational, organizational) è **valutata** con almeno una milestone
  (`milestone_category_not_assessed`);
- `financial_plan_inputs` (interfaccia verso lo Stage 10) è completo e risolvibile
  (`financial_input_unresolved`): sole referenze verso i driver che lo
  Stage 10 dovrà leggere, mai valori duplicati e mai proiezioni.

Warning: `milestone_target_above_capacity` (i volumi dichiarati
nell'interfaccia superano la capacità operativa canonica — è il **segnale**
del ciclo capacità ↔ volumi, il detect bloccante resta di `validate_cross_stage_consistency`
con `ops_capacity_below_gtm`) e `long_gap_between_milestones` (buco superiore
a `LONG_GAP_DAYS` fra la chiusura di una dipendenza e l'avvio di chi ne
dipende).

La risoluzione dei namespace tipizzati — unicità delle definizioni `MIL-`,
forma canonica degli id, forward reference intra-array, divieto di
riferimenti a namespace di stage futuri — è di
`validate_referential_integrity`: qui non si duplica. La sovrapposizione
è deliberata e **narrow** su due punti soltanto: (a) `depends_on` viene
risolto anche qui, perché un arco silenziosamente scartato renderebbe il
rilevamento dei cicli non fail-closed; (b) `owner_ref` viene risolto contro i
`ROLE-` **canonici dello Stage 8**, che è semantica di dominio dello Stage 9 e
non risoluzione di namespace.

Nessun calcolo finanziario: i costi restano driver, l'interfaccia verso lo
Stage 10 resta refs-only: il calcolo finanziario è dello Stage 10. Puro e
read-only; exit 0/1/2/3. Three-state: per progetti a stage < 9 i dati
Stage 9 sono `not_yet_required`, mai FAIL.
"""
import re
from datetime import date
from decimal import Decimal

import _framework as fw

MIL_STAGE = "09_roadmap-and-milestones"
TEAM_STAGE = "08_team-and-governance"
STRUCTURED_REL = f"{MIL_STAGE}/structured-output.json"
TEAM_STRUCTURED_REL = f"{TEAM_STAGE}/structured-output.json"

# Vocabolario canonico delle categorie (schema milestone-plan). Lo
# schema non prevede alcun meccanismo `none_identified` per le categorie:
# «valutata» significa quindi «almeno una milestone» e non esiste una forma
# rappresentabile di categoria dichiarata assente con motivazione.
CATEGORIES = ("technical", "commercial", "operational", "organizational")

MIL_RE = re.compile(rf"^MIL-{fw.CANONICAL_NUM}$")
ROLE_RE = re.compile(rf"^ROLE-{fw.CANONICAL_NUM}$")
# Forma ISO-8601 estesa, la sola ammessa dallo schema: nessun timestamp,
# nessun formato locale, nessuna forma compatta. Il confronto avviene su
# oggetti `date`, mai lessicograficamente e mai con l'orologio di sistema:
# l'esito è deterministico e indipendente dal fuso.
ISO_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

# Un buco più lungo di così fra una dipendenza e chi ne dipende è un segnale
# di roadmap non continua (warning, mai un blocco).
LONG_GAP_DAYS = 180

# Interfaccia `financial_plan_inputs`: chiavi scalari e chiavi che portano una classe di
# riferimenti. Una classe obbligatoria dichiarata vuota non porta alcun
# riferimento e non è quindi risolvibile dallo Stage 10.
FINANCIAL_INPUT_SCALARS = ("pricing_ref", "funnel_customers_ref", "churn_ref",
                           "ops_capacity_ref", "som_ref")
FINANCIAL_INPUT_ARRAYS = ("cogs_refs", "headcount_driver_refs",
                          "milestone_cost_refs")
FINANCIAL_INPUTS_PATH = "milestone_plan.financial_plan_inputs"


def _strict_decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value))


def _parse_date(value):
    """`date` per una stringa ISO-8601 estesa; None per qualunque altra forma."""
    if not isinstance(value, str) or not ISO_DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _load_plan_doc(args, state, report):
    """Structured output di Stage 9: dal candidate in egress, dal canonico in
    impact. Se il canonico non esiste e lo Stage 9 non è ancora completato, il
    dato non è dovuto (`not_yet_required`), mai un FAIL (three-state)."""
    if args.phase == "egress":
        path = args.candidate / "structured-output.json"
        if not path.exists():
            report.add_error(
                "missing_required", ref=args.stage,
                message=("structured-output.json dovuto in egress di Stage 9: "
                         "piano delle milestone mancante"),
                expected="structured-output.json nel candidate",
                actual="assente")
            return None
        return fw.read_candidate_json(path, "structured-output.json")
    path = state.project / STRUCTURED_REL
    if not path.exists():
        completed = state.status.get("completed_stages", [])
        if isinstance(completed, list) and MIL_STAGE in completed:
            report.add_error(
                "missing_required", ref=MIL_STAGE,
                message=(f"{STRUCTURED_REL} assente ma lo Stage 9 risulta "
                         "completato: piano delle milestone canonico dovuto"),
                expected=STRUCTURED_REL,
                actual="assente")
        else:
            report.add_warning(
                "not_yet_required", ref=MIL_STAGE,
                message="piano delle milestone canonico non ancora dovuto")
        return None
    return fw.read_canonical_json(path, STRUCTURED_REL)


def _role_ids(args, state, report):
    """Id dei `ROLE-` canonici dello Stage 8, in ordine di documento.

    None quando lo Stage 8 non ha prodotto il proprio structured output. In
    egress di Stage 9 quel dato è sempre dovuto (`missing_required`); in
    impact lo è solo se lo Stage 8 risulta completato — su progetti pre-8 la
    proprietà delle milestone non è verificabile e non si inventa un FAIL.
    Restituire None (e non un insieme vuoto) evita di trasformare un upstream
    assente in un difetto di owner su ogni milestone."""
    path = state.project / TEAM_STRUCTURED_REL
    if not path.exists():
        completed = state.status.get("completed_stages", [])
        due = args.phase == "egress" or (
            isinstance(completed, list) and TEAM_STAGE in completed)
        if due:
            report.add_error(
                "missing_required", ref=TEAM_STAGE,
                message=(f"{TEAM_STRUCTURED_REL} assente: senza i ROLE- "
                         "canonici dello Stage 8 la proprietà delle milestone "
                         "non è verificabile"),
                expected=TEAM_STRUCTURED_REL,
                actual="assente")
        return None
    doc = fw.read_canonical_json(path, TEAM_STRUCTURED_REL)
    model = doc.get("team_governance") if isinstance(doc, dict) else None
    roles = model.get("roles") if isinstance(model, dict) else None
    if not isinstance(roles, list):
        report.add_error(
            "missing_required", ref=TEAM_STAGE,
            message=("team_governance.roles assente nel canonico dello "
                     "Stage 8: owner delle milestone non verificabile"),
            expected="roles[]",
            actual="assente")
        return None
    out = []
    for role in roles:
        rid = role.get("id") if isinstance(role, dict) else None
        if isinstance(rid, str) and rid not in out:
            out.append(rid)
    return out


def _milestone_entries(model, report):
    """Milestone in ordine di documento come triple (ref, id, item).

    `ref` è l'ancora stabile del report: l'id `MIL-` quando c'è, altrimenti il
    path strutturale — un difetto va sempre localizzato, anche quando è l'id
    stesso a mancare."""
    milestones = model.get("milestones")
    if not isinstance(milestones, list) or not milestones:
        report.add_error(
            "missing_required", ref="milestone_plan.milestones",
            message=("milestones[] assente o vuoto: una roadmap senza "
                     "milestone non è un impegno verificabile"),
            expected="milestones[] non vuoto",
            actual="assente" if milestones is None else str(milestones))
        return None
    out = []
    for index, item in enumerate(milestones):
        path = f"milestone_plan.milestones[{index}]"
        if not isinstance(item, dict):
            report.add_error(
                "invalid", ref=path,
                message="voce di milestones[] non oggetto")
            continue
        mid = item.get("id")
        mid = mid if isinstance(mid, str) and MIL_RE.match(mid) else None
        out.append((mid or path, mid, item))
    return out


def _check_fields(entries, role_ids, overlay, report):
    """Owner, costo e criteri: ciò che rende una milestone eseguibile."""
    for ref, _mid, item in entries:
        owner = item.get("owner_ref")
        if not isinstance(owner, str) or not ROLE_RE.match(owner):
            report.add_error(
                "milestone_owner_unresolved", ref=ref,
                message=("milestone senza owner in forma di ROLE-: ogni "
                         "milestone ha un solo responsabile dichiarato allo "
                         "Stage 8"),
                expected="owner_ref ROLE-*",
                actual=repr(owner))
        elif role_ids is not None and owner not in role_ids:
            report.add_error(
                "milestone_owner_unresolved", ref=owner,
                message=(f"owner della milestone {ref} non presente fra i "
                         "ROLE- canonici dello Stage 8: un responsabile che "
                         "non esiste non è accountability"),
                expected="ROLE- dichiarato in team_governance.roles",
                actual="inesistente")

        cost = item.get("cost_ref")
        if not isinstance(cost, str) or not fw.ANY_ASS_RE.match(cost):
            report.add_error(
                "milestone_cost_unresolved", ref=ref,
                message=("costo della milestone letterale o non canonico "
                         "invece di un riferimento ASS-/P-ASS-: il costo vive "
                         "una sola volta nel registro"),
                expected="cost_ref ASS-*/P-ASS-*",
                actual=repr(cost))
        elif fw.resolve_ref(cost, overlay) is None:
            report.add_error(
                "milestone_cost_unresolved", ref=cost,
                message=(f"costo della milestone {ref} non risolvibile nel "
                         "registro delle assunzioni"))

        criteria = item.get("success_criteria")
        usable = isinstance(criteria, list) and criteria and all(
            isinstance(c, str) and c.strip() for c in criteria)
        if not usable:
            report.add_error(
                "milestone_criteria_missing", ref=ref,
                message=("success_criteria assenti o vuoti: senza un criterio "
                         "misurabile la milestone non è verificabile"),
                expected="success_criteria[] con almeno un criterio non vuoto",
                actual=repr(criteria))
        for field, label in (("go_no_go_rule", "regola go/no-go"),
                             ("exit_criteria", "exit criterion")):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                report.add_error(
                    "milestone_criteria_missing", ref=ref,
                    message=(f"{label} assente: una milestone senza {field} "
                             "non ha uno stage gate decidibile"),
                    expected=f"{field} non vuoto",
                    actual=repr(value))


def _check_categories(entries, report):
    """Ogni categoria del vocabolario canonico è valutata."""
    seen = set()
    for ref, _mid, item in entries:
        category = item.get("category")
        normalized = category.strip() if isinstance(category, str) else None
        if normalized not in CATEGORIES:
            report.add_error(
                "milestone_category_not_assessed", ref=ref,
                message=("categoria della milestone assente, in bianco o "
                         "fuori dal vocabolario canonico: una milestone non "
                         "classificata non è valutabile"),
                expected=" | ".join(CATEGORIES),
                actual=repr(category))
            continue
        seen.add(normalized)
    for category in CATEGORIES:
        if category not in seen:
            report.add_error(
                "milestone_category_not_assessed",
                ref=f"milestone_plan.categories.{category}",
                message=(f"categoria {category!r} non valutata: la roadmap "
                         "dichiara almeno una milestone per ogni categoria; "
                         "lo schema non prevede alcuna forma di "
                         "categoria dichiarata assente"),
                expected=f"almeno una milestone di categoria {category}",
                actual="nessuna milestone")


def _dependency_map(entries, report):
    """Archi risolti del grafo, in ordine di documento.

    Un `depends_on` che non risolve è riportato qui e **non** entra nel grafo:
    un arco silenziosamente scartato renderebbe il rilevamento dei cicli non
    fail-closed."""
    known = [mid for _ref, mid, _item in entries if mid]
    deps = {}
    for ref, mid, item in entries:
        resolved = []
        raw = item.get("depends_on")
        for dep in raw if isinstance(raw, list) else []:
            if isinstance(dep, str) and MIL_RE.match(dep) and dep in known:
                if dep not in resolved:
                    resolved.append(dep)
                continue
            report.add_error(
                "milestone_dependency_unresolved",
                ref=dep if isinstance(dep, str) else ref,
                message=(f"dipendenza della milestone {ref} non risolvibile "
                         "fra le MIL- del piano: una dipendenza fantasma non "
                         "è una sequenza"),
                expected="MIL-* definita in milestone_plan.milestones",
                actual=repr(dep))
        if mid:
            deps[mid] = resolved
    return deps


def _cycle_nodes(order, deps):
    """Nodi che appartengono a un ciclo, in ordine di documento.

    Per ciascun nodo si risale iterativamente le proprie dipendenze (BFS con
    set di visitati): se il nodo è raggiungibile da sé stesso, sta su un
    ciclo. L'auto-dipendenza è il caso a un nodo. Nessuna ricorsione, nessuna
    profondità di stack proporzionale al grafo, ordine di visita fissato
    dall'ordine di documento: il report è deterministico."""
    cycled = []
    for node in order:
        seen = set()
        queue = list(deps.get(node, ()))
        while queue:
            current = queue.pop(0)
            if current == node:
                cycled.append(node)
                break
            if current in seen:
                continue
            seen.add(current)
            queue.extend(deps.get(current, ()))
    return cycled


def _check_graph(entries, deps, report):
    order = [mid for _ref, mid, _item in entries if mid]
    cycled = _cycle_nodes(order, deps)
    if not cycled:
        return
    involved = ", ".join(cycled)
    for node in cycled:
        report.add_error(
            "milestone_cycle_detected", ref=node,
            message=(f"dipendenza ciclica fra le milestone ({involved}): il "
                     "grafo delle dipendenze dev'essere aciclico, altrimenti "
                     "nessuna delle milestone coinvolte può iniziare"),
            expected="grafo aciclico (DAG)",
            actual=f"ciclo su {involved}")


def _check_dates(entries, deps, report):
    """Parseabilità, ordinamento interno e cronologia delle dipendenze."""
    parsed = {}
    for ref, mid, item in entries:
        window = {}
        for field in ("start_date", "target_date"):
            value = item.get(field)
            parsed_value = _parse_date(value)
            if parsed_value is None:
                report.add_error(
                    "invalid", ref=ref,
                    message=(f"{field} non in forma ISO-8601 estesa "
                             "(YYYY-MM-DD): una data non interpretabile non è "
                             "una data"),
                    expected="YYYY-MM-DD",
                    actual=repr(value))
            window[field] = parsed_value
        start, target = window["start_date"], window["target_date"]
        if start is not None and target is not None and target < start:
            report.add_error(
                "milestone_date_incoherent", ref=ref,
                message=("target_date precede start_date: la milestone "
                         "chiuderebbe prima di iniziare"),
                expected=f">= {start.isoformat()}",
                actual=target.isoformat())
        if mid:
            parsed[mid] = (start, target)

    for ref, mid, _item in entries:
        if not mid:
            continue
        start = parsed.get(mid, (None, None))[0]
        if start is None:
            continue
        for dep in deps.get(mid, ()):
            dep_target = parsed.get(dep, (None, None))[1]
            if dep_target is None:
                continue
            if start < dep_target:
                report.add_error(
                    "milestone_date_incoherent", ref=ref,
                    message=(f"la milestone parte il {start.isoformat()} ma "
                             f"la dipendenza {dep} chiude il "
                             f"{dep_target.isoformat()}: nessuna milestone "
                             "può iniziare prima che il proprio prerequisito "
                             "sia chiuso (confine incluso ammesso)"),
                    expected=f">= {dep_target.isoformat()}",
                    actual=start.isoformat())
            elif (start - dep_target).days > LONG_GAP_DAYS:
                report.add_warning(
                    "long_gap_between_milestones", ref=ref,
                    message=(f"{(start - dep_target).days} giorni fra la "
                             f"chiusura di {dep} e l'avvio di questa "
                             "milestone: verificare che il piano sia continuo "
                             "e che la sequenza regga il fabbisogno di cassa"))


def _resolve_input(key, ref, overlay, report):
    """Un input dell'interfaccia `financial_plan_inputs` è una referenza risolvibile, mai un
    valore: un numero qui sarebbe un dato che vive due volte."""
    if not isinstance(ref, str) or not fw.ANY_ASS_RE.match(ref):
        report.add_error(
            "financial_input_unresolved", ref=f"{FINANCIAL_INPUTS_PATH}.{key}",
            message=(f"{key}: input del financial plan assente o non in forma "
                     "di riferimento ASS-/P-ASS-. L'interfaccia verso lo "
                     "Stage 10 porta referenze, mai valori duplicati né "
                     "calcoli (contratto financial_plan_inputs)"),
            expected="riferimento ASS-*/P-ASS-*",
            actual=repr(ref))
        return
    if fw.resolve_ref(ref, overlay) is None:
        report.add_error(
            "financial_input_unresolved", ref=ref,
            message=(f"{key}: riferimento non risolvibile nel registro delle "
                     "assunzioni; lo Stage 10 non troverebbe il driver"))


def _check_financial_inputs(model, entries, overlay, report):
    inputs = model.get("financial_plan_inputs")
    if not isinstance(inputs, dict):
        report.add_error(
            "financial_input_unresolved", ref=FINANCIAL_INPUTS_PATH,
            message=("financial_plan_inputs assente: senza questa interfaccia "
                     "contrattuale lo Stage 10 non avrebbe alcun driver "
                     "risolvibile"),
            expected=("financial_plan_inputs con le chiavi del contratto "
                      "financial_plan_inputs"),
            actual="assente")
        return

    for key in FINANCIAL_INPUT_SCALARS:
        _resolve_input(key, inputs.get(key), overlay, report)

    for key in FINANCIAL_INPUT_ARRAYS:
        refs = inputs.get(key)
        if not isinstance(refs, list) or not refs:
            report.add_error(
                "financial_input_unresolved",
                ref=f"{FINANCIAL_INPUTS_PATH}.{key}",
                message=(f"{key}: classe di riferimenti obbligatoria assente o "
                         "dichiarata vuota. Una classe senza alcun "
                         "riferimento non è risolvibile dallo Stage 10"),
                expected="array non vuoto di riferimenti ASS-*/P-ASS-*",
                actual=repr(refs))
            continue
        for ref in refs:
            _resolve_input(key, ref, overlay, report)

    # Completezza dell'interfaccia («financial_plan_inputs completo»):
    # ogni costo di milestone dichiarato nel piano compare fra i
    # milestone_cost_refs, altrimenti resterebbe invisibile allo Stage 10.
    declared = inputs.get("milestone_cost_refs")
    declared = set(declared) if isinstance(declared, list) else set()
    for ref, _mid, item in entries:
        cost = item.get("cost_ref")
        if isinstance(cost, str) and fw.ANY_ASS_RE.match(cost) and \
                cost not in declared:
            report.add_error(
                "financial_input_unresolved", ref=cost,
                message=(f"il costo della milestone {ref} non compare in "
                         "milestone_cost_refs: l'interfaccia verso lo Stage 10 "
                         "sarebbe incompleta e il costo invisibile al piano "
                         "finanziario"),
                expected="cost_ref presente in "
                         f"{FINANCIAL_INPUTS_PATH}.milestone_cost_refs",
                actual="assente dall'interfaccia")

    _check_capacity_signal(inputs, overlay, report)


def _check_capacity_signal(inputs, overlay, report):
    """Segnale (non bloccante) del ciclo capacità ↔ volumi: i volumi che la roadmap porta
    allo Stage 10 superano la capacità operativa canonica. Il detect bloccante
    è di `validate_cross_stage_consistency` (`ops_capacity_below_gtm`): qui il
    duplicato sarebbe una seconda fonte di verità, non un secondo controllo."""
    customers_ref = inputs.get("funnel_customers_ref")
    capacity_ref = inputs.get("ops_capacity_ref")
    customers = fw.resolve_ref(customers_ref, overlay) \
        if isinstance(customers_ref, str) else None
    capacity = fw.resolve_ref(capacity_ref, overlay) \
        if isinstance(capacity_ref, str) else None
    if not isinstance(customers, dict) or not isinstance(capacity, dict):
        return
    if customers.get("unit") != capacity.get("unit"):
        return  # unità incomparabili: il confronto è del cross-stage
    volume = _strict_decimal(customers.get("value"))
    ceiling = _strict_decimal(capacity.get("value"))
    if volume is None or ceiling is None or volume <= ceiling:
        return
    report.add_warning(
        "milestone_target_above_capacity", ref=customers_ref,
        message=(f"i volumi portati al financial plan ({volume}) superano la "
                 f"capacità operativa canonica ({ceiling}): segnale del ciclo "
                 "di capacità operativa — la roadmap promette più di quanto "
                 "le operations "
                 "sostengano"))


def check(args, config, state, report):
    name = "validate_milestone_chain"
    x_ordinal = fw.stage_ordinal(args.stage, config)
    applicable = config["validators"][name]
    if x_ordinal not in applicable["stages"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile allo stage {args.stage}")
    if args.phase not in applicable["phases"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile alla fase {args.phase}")

    doc = _load_plan_doc(args, state, report)
    if doc is None:
        return
    model = doc.get("milestone_plan") if isinstance(doc, dict) else None
    if not isinstance(model, dict):
        report.add_error(
            "missing_required", ref=args.stage,
            message="milestone_plan assente nello structured-output",
            expected="milestone_plan con milestones e financial_plan_inputs",
            actual="assente")
        return

    overlay = fw.build_overlay(state, args.candidate)
    entries = _milestone_entries(model, report)
    if entries is None:
        # Senza milestone non c'è grafo da verificare, ma l'interfaccia verso
        # lo Stage 10 resta dovuta: il difetto è già riportato.
        return

    role_ids = _role_ids(args, state, report)
    deps = _dependency_map(entries, report)

    _check_fields(entries, role_ids, overlay, report)
    _check_categories(entries, report)
    _check_graph(entries, deps, report)
    _check_dates(entries, deps, report)
    _check_financial_inputs(model, entries, overlay, report)


if __name__ == "__main__":
    fw.run_validator("validate_milestone_chain", check)
