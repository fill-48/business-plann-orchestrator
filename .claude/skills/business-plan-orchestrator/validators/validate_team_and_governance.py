#!/usr/bin/env python3
"""validate_team_and_governance — team e governance Stage 8.

Stage 8-9, fasi egress (overlay candidate ⊕ canonico allo Stage 8) e impact
(solo canonico). Verifica che il modello organizzativo regga davvero
l'esecuzione del modello operativo dello Stage 7:

- ogni processo core (`OPS-` con `entity_type: core_process` dello Stage 7)
  è coperto da almeno un `ROLE-` (`core_process_unowned`);
- ogni `capability_gap` ha un `addressed_by` che risolve a un **meccanismo
  reale** — una `COND-` esistente, un'assunzione pianificata (ruolo aperto
  con la sua riga di `hiring_plan`) o un advisor dichiarato — mai una frase
  rassicurante (`capability_gap_unaddressed`);
- ogni area di `decision_rights` ha **esattamente un** owner: nessun owner o
  due owner diversi sulla stessa area sono ambiguità (`decision_right_ambiguous`);
- le quote di `equity_split` sono ratio in [0,1] e sommano ≤ 1 in Decimal, con
  la tolleranza ratio di config (`equity_sum_exceeds_one`); la somma esatta a
  1 è ammessa (confine incluso);
- `fte_ref` e `cost_driver_ref` sono **riferimenti** ad `ASS-`/`P-ASS-`
  esistenti (driver, mai proiezioni e mai letterali) — `fte_not_ref`;
- i driver derivati sono ricalcolabili dalla Formula DSL (`value_mismatch`);
- le unità degli `fte_ref` sono omogenee fra i ruoli, altrimenti il totale
  headcount non è sommabile (`unit_mismatch`);
- ogni `risk_ref` risolve nel `risk-register` (`unresolved_ref`).

Warning: `key_person_dependency` (un solo `ROLE-` copre ≥
`KEY_PERSON_PROCESS_THRESHOLD` processi core) e `open_position_unbudgeted`
(posizione aperta senza `cost_driver_ref` nel piano assunzioni). Il secondo
**diventa error in egress** quando lo stage può chiudere solo `approved`
pieno: il percorso `approved_with_conditions` richiede una `COND-` —
canonica aperta oppure proposta nel candidate (il transaction manager
respinge `--gate-result approved_with_conditions` senza
`proposed-conditions.json`); senza alcuna condizione l'unico esito possibile
è `approved` pieno, e una posizione aperta non finanziata non può passare.
L'escalation è una regola di gate: in fase `impact` lo stage è già chiuso e
il segnale resta un warning.

La risoluzione dei namespace tipizzati (`covers_processes` verso `OPS-` di
tipo `core_process`, `owner_ref`/`role_ref` verso `ROLE-` esistenti, id
duplicati o non canonici) è di `validate_referential_integrity`: qui non si
duplica. Puro e read-only; exit 0/1/2/3. Three-state: per progetti a
stage < 8 i dati Stage 8 sono `not_yet_required`, mai FAIL.
"""
import re
from decimal import Decimal

import _framework as fw
import validate_market_arithmetic as market

TEAM_STAGE = "08_team-and-governance"
OPS_STAGE = "07_operations-and-ip"
STRUCTURED_REL = f"{TEAM_STAGE}/structured-output.json"
OPS_STRUCTURED_REL = f"{OPS_STAGE}/structured-output.json"

# Un solo ruolo che copre almeno questo numero di processi core è una
# concentrazione da segnalare («un solo ROLE- copre >= N processi core»).
KEY_PERSON_PROCESS_THRESHOLD = 3

# Forma lasca: intercetta qualunque token che pretende di essere una COND-.
COND_RE = re.compile(r"COND-[0-9]+")
# Idem per i ROLE- citati in `addressed_by`: un token che pretende di essere
# un ruolo va risolto, non ignorato.
ROLE_RE = re.compile(r"ROLE-[0-9]+")
# Etichetta facoltativa davanti al nome di un advisor: «advisor: Nome»,
# «advisor - Nome», «advisor Nome». Si applica alla stringa già normalizzata.
ADVISOR_LABEL_RE = re.compile(r"^advisor\s*[:-]?\s*")


def _strict_decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value))


def _load_team_doc(args, state, report):
    """Structured output di Stage 8: dal candidate in egress dello Stage 8,
    dal canonico in impact. Se il canonico non esiste e lo Stage 8 non è
    ancora completato, il dato non è dovuto (`not_yet_required`), mai un FAIL
    (three-state)."""
    if args.phase == "egress":
        path = args.candidate / "structured-output.json"
        if not path.exists():
            report.add_error(
                "missing_required", ref=args.stage,
                message=("structured-output.json dovuto in egress di Stage 8: "
                         "team & governance mancante"),
                expected="structured-output.json nel candidate",
                actual="assente")
            return None
        return fw.read_candidate_json(path, "structured-output.json")
    path = state.project / STRUCTURED_REL
    if not path.exists():
        completed = state.status.get("completed_stages", [])
        if isinstance(completed, list) and TEAM_STAGE in completed:
            report.add_error(
                "missing_required", ref=TEAM_STAGE,
                message=(f"{STRUCTURED_REL} assente ma lo Stage 8 risulta "
                         "completato: team & governance canonico dovuto"),
                expected=STRUCTURED_REL,
                actual="assente")
        else:
            report.add_warning(
                "not_yet_required", ref=TEAM_STAGE,
                message="team & governance canonico non ancora dovuto")
        return None
    return fw.read_canonical_json(path, STRUCTURED_REL)


def _core_process_ids(args, state, report):
    """Id dei processi core canonici dello Stage 7, in ordine di documento.

    None quando lo Stage 7 non ha prodotto il proprio structured output. In
    egress di Stage 8 quel dato è sempre dovuto (`missing_required`); in
    impact lo è solo se lo Stage 7 risulta completato — su progetti pre-7 la
    copertura non è verificabile e non si inventa un FAIL."""
    path = state.project / OPS_STRUCTURED_REL
    if not path.exists():
        completed = state.status.get("completed_stages", [])
        due = args.phase == "egress" or (
            isinstance(completed, list) and OPS_STAGE in completed)
        if due:
            report.add_error(
                "missing_required", ref=OPS_STAGE,
                message=(f"{OPS_STRUCTURED_REL} assente: senza i processi "
                         "core canonici dello Stage 7 la copertura dei ruoli "
                         "non è verificabile"),
                expected=OPS_STRUCTURED_REL,
                actual="assente")
        return None
    doc = fw.read_canonical_json(path, OPS_STRUCTURED_REL)
    model = doc.get("operations_model") if isinstance(doc, dict) else None
    processes = model.get("core_processes") if isinstance(model, dict) else None
    if not isinstance(processes, list):
        report.add_error(
            "missing_required", ref=OPS_STAGE,
            message=("operations_model.core_processes assente nel canonico "
                     "dello Stage 7: copertura dei ruoli non verificabile"),
            expected="core_processes[]",
            actual="assente")
        return None
    out = []
    for proc in processes:
        pid = proc.get("id") if isinstance(proc, dict) else None
        if isinstance(pid, str) and pid not in out:
            out.append(pid)
    return out


def _load_risk_ids(state):
    path = state.project / "shared" / "risk-register.json"
    if not path.exists():
        return set()
    register = fw.read_canonical_json(path, "shared/risk-register.json")
    if not isinstance(register, list):
        raise fw.CanonicalStateError("risk-register.json non è una lista")
    return {entry.get("id") for entry in register if isinstance(entry, dict)}


def _known_condition_ids(args, state):
    """COND- note: canoniche più quelle proposte nel candidate."""
    ids = {cond.get("id") for cond in state.conditions
           if isinstance(cond, dict)}
    for cond in _candidate_conditions(args):
        ids.add(cond.get("id"))
    return {cid for cid in ids if isinstance(cid, str)}


def _candidate_conditions(args):
    if args.candidate is None:
        return []
    path = args.candidate / "proposed-conditions.json"
    if not path.exists():
        return []
    doc = fw.read_candidate_json(path, "proposed-conditions.json")
    if not isinstance(doc, list):
        raise fw.CandidateError(
            "invalid", "proposed-conditions.json non è una lista")
    return [entry for entry in doc if isinstance(entry, dict)]


def _escalates_open_position(args, state):
    """True se `open_position_unbudgeted` va emesso come error e non warning.

    L'escalation è una regola di **gate**, quindi vive solo in egress: in
    impact lo stage è già chiuso e il suo esito non è più in discussione.
    In egress il transaction manager ammette
    `--gate-result approved_with_conditions` solo con un
    `proposed-conditions.json` non vuoto; una `COND-` canonica ancora aperta
    ha lo stesso effetto. Senza né l'una né l'altra l'unico esito possibile è
    `approved` pieno, e una posizione aperta non finanziata non può passare."""
    if args.phase != "egress":
        return False
    if any(cond.get("resolution_status") == "open"
           for cond in state.conditions if isinstance(cond, dict)):
        return False
    return not _candidate_conditions(args)


def _resolve_driver(label, ref, overlay, report):
    """Un driver è un riferimento ad ASS-/P-ASS- esistente, mai un letterale."""
    if not isinstance(ref, str) or not fw.ANY_ASS_RE.match(ref):
        report.add_error(
            "fte_not_ref", ref=ref if isinstance(ref, str) else None,
            message=(f"{label}: driver letterale o non canonico invece di un "
                     "riferimento ASS-/P-ASS- (FTE e costi headcount vivono "
                     "una sola volta)"),
            expected="riferimento ASS-*/P-ASS-*",
            actual=repr(ref))
        return None
    entry = fw.resolve_ref(ref, overlay)
    if entry is None:
        report.add_error(
            "fte_not_ref", ref=ref,
            message=f"{label}: riferimento del driver non risolvibile")
        return None
    return entry


def _check_roles(model, overlay, core_ids, report):
    """Ruoli, driver FTE e copertura dei processi core."""
    roles = model.get("roles")
    if not isinstance(roles, list) or not roles:
        report.add_error(
            "missing_required", ref="team_governance.roles",
            message=("roles[] assente o vuoto: senza ruoli non esiste "
                     "accountability dichiarata"),
            expected="roles[] non vuoto",
            actual="assente" if roles is None else str(roles))
        return [], set()

    driver_refs = []
    covered = set()
    fte_unit = None
    fte_unit_ref = None
    for role in roles:
        if not isinstance(role, dict):
            report.add_error(
                "invalid", ref=None,
                message="voce di roles[] non oggetto")
            continue
        rid = role.get("id")
        has_person = isinstance(role.get("person"), str) and \
            role["person"].strip()
        has_open = isinstance(role.get("open_position"), str) and \
            role["open_position"].strip()
        if not has_person and not has_open:
            report.add_error(
                "invalid", ref=rid,
                message=("ruolo senza persona e senza open_position: un ruolo "
                         "è ricoperto da qualcuno o è una posizione aperta "
                         "dichiarata"),
                expected="person | open_position",
                actual="nessuno dei due")

        entry = _resolve_driver(f"roles[{rid}].fte_ref", role.get("fte_ref"),
                               overlay, report)
        if entry is not None:
            driver_refs.append(role.get("fte_ref"))
            unit = entry.get("unit")
            if fte_unit is None:
                fte_unit, fte_unit_ref = unit, role.get("fte_ref")
            elif unit != fte_unit:
                report.add_error(
                    "unit_mismatch", ref=role.get("fte_ref"),
                    message=(f"unità FTE {unit!r} incompatibile con "
                             f"{fte_unit!r} di {fte_unit_ref}: il totale "
                             "headcount non è sommabile"),
                    expected=str(fte_unit),
                    actual=str(unit))

        processes = role.get("covers_processes")
        own = [p for p in processes if isinstance(p, str) and p in core_ids] \
            if isinstance(processes, list) else []
        covered.update(own)
        if len(set(own)) >= KEY_PERSON_PROCESS_THRESHOLD:
            report.add_warning(
                "key_person_dependency", ref=rid,
                message=(f"un solo ruolo copre {len(set(own))} processi core: "
                         "concentrazione da mitigare (backup, deleghe, "
                         "documentazione del know-how)"))

    for core_id in core_ids:
        if core_id not in covered:
            report.add_error(
                "core_process_unowned", ref=core_id,
                message=("processo core dello Stage 7 senza alcun ROLE- che "
                         "lo copra: l'esecuzione non ha un "
                         "responsabile"),
                expected="almeno un ROLE- con covers_processes",
                actual="nessun ruolo")
    return driver_refs, covered


def _unique(items):
    """Dedup che conserva l'ordine di comparsa: l'output resta deterministico."""
    out = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


def _normalize_name(text):
    """Normalizzazione documentata dei nomi: trim, collasso degli spazi
    interni, case-fold. Nessun fuzzy matching: o il nome coincide dopo la
    normalizzazione, o non coincide."""
    return " ".join(text.split()).casefold()


def _hiring_mechanisms(model):
    """`ROLE-` che rappresentano un'assunzione davvero strutturata.

    Un meccanismo di hiring esiste solo se il ruolo è una **posizione
    aperta**, il piano assunzioni ha una riga intestata a quel ruolo e quella
    riga porta un `cost_driver_ref` in forma di riferimento `ASS-`/`P-ASS-`.
    La risoluzione finale dell'identificatore resta di `_resolve_driver` e di
    refint: qui si verifica che il meccanismo esista, non che il
    driver sia risolvibile — quel difetto ha già il suo codice (`fte_not_ref`)."""
    roles = model.get("roles")
    open_roles = set()
    for role in roles if isinstance(roles, list) else []:
        if not isinstance(role, dict):
            continue
        rid = role.get("id")
        position = role.get("open_position")
        if isinstance(rid, str) and isinstance(position, str) \
                and position.strip():
            open_roles.add(rid)

    plan = model.get("hiring_plan")
    out = set()
    for item in plan if isinstance(plan, list) else []:
        if not isinstance(item, dict):
            continue
        role_ref = item.get("role_ref")
        driver = item.get("cost_driver_ref")
        if role_ref in open_roles and isinstance(driver, str) \
                and fw.ANY_ASS_RE.match(driver):
            out.add(role_ref)
    return out


def _advisor_names(model):
    """Nomi normalizzati degli advisor dichiarati in `advisors[]`."""
    advisors = model.get("advisors")
    out = set()
    for advisor in advisors if isinstance(advisors, list) else []:
        if not isinstance(advisor, dict):
            continue
        name = advisor.get("name")
        if isinstance(name, str) and _normalize_name(name):
            out.add(_normalize_name(name))
    return out


def _matches_advisor(addressed, advisor_names):
    """True se `addressed_by` è il nome esatto di un advisor dichiarato,
    con o senza l'etichetta «advisor:» davanti."""
    if not advisor_names:
        return False
    normalized = _normalize_name(addressed)
    forms = {normalized, ADVISOR_LABEL_RE.sub("", normalized, count=1)}
    return bool(forms & advisor_names)


def _check_capability_gaps(model, known_conditions, report):
    """Un gap è indirizzato solo da un meccanismo che esiste davvero.

    `addressed_by` non è prosa: porta il **meccanismo**, mentre la
    spiegazione discorsiva sta in `notes`. Le forme ammesse sono un id
    (`COND-012`, `ROLE-004`), lo stesso id con un verbo davanti
    (`hire ROLE-004`) oppure il nome esatto di un advisor dichiarato
    (`Studio Legale Esempio`, `advisor: Studio Legale Esempio`).

    La risoluzione è per token e non fa inferenza semantica: **ogni** id
    citato deve risolvere — un id fantasma accanto a uno buono resta una
    promessa, non un piano — e una stringa senza alcun id può valere solo
    come nome di advisor. Così «will hire someone later» o «future CTO» non
    indirizzano nulla."""
    gaps = model.get("capability_gaps")
    if not isinstance(gaps, list):
        return
    hiring = _hiring_mechanisms(model)
    advisor_names = _advisor_names(model)

    for index, gap in enumerate(gaps):
        if not isinstance(gap, dict):
            continue
        label = gap.get("gap")
        path = f"team_governance.capability_gaps[{index}]"
        addressed = gap.get("addressed_by")

        if not isinstance(addressed, str) or not addressed.strip():
            report.add_error(
                "capability_gap_unaddressed", ref=path,
                message=(f"capability gap senza piano: {label!r} richiede "
                         "un hiring pianificato, un advisor dichiarato o una "
                         "COND-"),
                expected="addressed_by non vuoto",
                actual=repr(addressed))
            continue

        cond_ids = _unique(COND_RE.findall(addressed))
        role_ids = _unique(ROLE_RE.findall(addressed))

        if not cond_ids and not role_ids:
            if not _matches_advisor(addressed, advisor_names):
                report.add_error(
                    "capability_gap_unaddressed", ref=path,
                    message=(f"capability gap {label!r} indirizzato da un "
                             "testo che non risolve ad alcun meccanismo: "
                             "addressed_by porta una COND-, il ROLE- da "
                             "assumere o il nome di un advisor dichiarato, "
                             "la spiegazione va in notes"),
                    expected="COND-*, ROLE-* con riga di hiring_plan, "
                             "o nome esatto di un advisor in advisors[]",
                    actual=repr(addressed))
            continue

        for cond_id in cond_ids:
            if cond_id not in known_conditions:
                report.add_error(
                    "capability_gap_unaddressed", ref=cond_id,
                    message=(f"capability gap {label!r} indirizzato a una "
                             "condizione inesistente: un gap coperto da una "
                             "COND- che non esiste resta scoperto"),
                    expected="COND- presente nel conditions-register o "
                             "proposta nel candidate",
                    actual="inesistente")
        for role_id in role_ids:
            if role_id not in hiring:
                report.add_error(
                    "capability_gap_unaddressed", ref=role_id,
                    message=(f"capability gap {label!r} indirizzato a "
                             "un'assunzione che non esiste nel piano: senza "
                             "una posizione aperta e una riga di hiring_plan "
                             "con cost_driver_ref è una promessa, non un "
                             "meccanismo"),
                    expected="ROLE- con open_position e riga di hiring_plan "
                             "con cost_driver_ref ASS-/P-ASS-",
                    actual="nessun meccanismo di hiring")


def _check_decision_rights(model, report):
    rights = model.get("decision_rights")
    if not isinstance(rights, list) or not rights:
        report.add_error(
            "missing_required", ref="team_governance.decision_rights",
            message=("decision_rights[] assente o vuoto: senza diritti di "
                     "decisione la governance non è definita"),
            expected="decision_rights[] non vuoto",
            actual="assente" if rights is None else str(rights))
        return
    owners_by_area = {}
    for right in rights:
        if not isinstance(right, dict):
            continue
        area = right.get("area")
        owner = right.get("owner_ref")
        if not isinstance(owner, str) or not owner.strip():
            report.add_error(
                "decision_right_ambiguous", ref=None,
                message=(f"area decisionale {area!r} senza owner: ogni area "
                         "ha esattamente un ROLE- responsabile"),
                expected="un solo owner_ref ROLE-",
                actual="nessun owner")
            continue
        key = area.strip().casefold() if isinstance(area, str) else area
        previous = owners_by_area.get(key)
        if previous is None:
            owners_by_area[key] = owner
        elif previous != owner:
            report.add_error(
                "decision_right_ambiguous", ref=owner,
                message=(f"area decisionale {area!r} con due owner diversi "
                         f"({previous} e {owner}): la responsabilità di "
                         "decisione non è divisibile"),
                expected=f"un solo owner_ref ({previous})",
                actual=owner)


def _check_governance(model, config, report):
    governance = model.get("governance")
    if not isinstance(governance, dict):
        report.add_error(
            "missing_required", ref="team_governance.governance",
            message=("governance assente: assetto societario ed equity sono "
                     "parte del contratto di Stage 8"),
            expected="governance con structure ed equity_split",
            actual="assente")
        return
    shares = governance.get("equity_split")
    if not isinstance(shares, list):
        return
    total = Decimal("0")
    for item in shares:
        if not isinstance(item, dict):
            continue
        value = _strict_decimal(item.get("share"))
        if value is None or value < 0 or value > 1:
            report.add_error(
                "invalid", ref=None,
                message=(f"quota di {item.get('holder')!r} non è un ratio in "
                         f"[0,1]: {item.get('share')!r}"),
                expected="ratio in [0,1]",
                actual=repr(item.get("share")))
            continue
        total += value
    tolerance = Decimal(str(config.get("tolerances", {}).get("ratio", "1e-6")))
    if total > Decimal("1") + tolerance:
        report.add_error(
            "equity_sum_exceeds_one", ref="team_governance.governance",
            message=(f"le quote di equity sommano a {total}: oltre il 100% "
                     "del capitale non è distribuibile"),
            expected="somma <= 1",
            actual=str(total))


def _check_hiring_plan(model, overlay, args, state, report):
    """Piano assunzioni: ogni posizione aperta ha un driver di costo."""
    plan = model.get("hiring_plan")
    entries = plan if isinstance(plan, list) else []
    driver_refs = []
    budgeted = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        role_ref = item.get("role_ref")
        entry = _resolve_driver(f"hiring_plan[{role_ref}].cost_driver_ref",
                                item.get("cost_driver_ref"), overlay, report)
        if entry is not None:
            driver_refs.append(item.get("cost_driver_ref"))
            if isinstance(role_ref, str):
                budgeted.add(role_ref)

    roles = model.get("roles")
    if not isinstance(roles, list):
        return driver_refs
    escalate = _escalates_open_position(args, state)
    for role in roles:
        if not isinstance(role, dict):
            continue
        open_position = role.get("open_position")
        rid = role.get("id")
        if not isinstance(open_position, str) or not open_position.strip():
            continue
        if rid in budgeted:
            continue
        message = (f"posizione aperta {open_position!r} senza cost_driver_ref "
                   "nel piano assunzioni: un ruolo da assumere ha un costo")
        if escalate:
            report.add_error(
                "open_position_unbudgeted", ref=rid,
                message=(message + "; senza alcuna COND- aperta lo stage può "
                         "chiudere solo `approved` pieno, e un gap non "
                         "indirizzato lo vieta"),
                expected="cost_driver_ref nel hiring_plan, oppure una COND-",
                actual="nessun driver di costo e nessuna condizione")
        else:
            report.add_warning(
                "open_position_unbudgeted", ref=rid,
                message=(message + "; percorso ammesso solo come "
                         "approved_with_conditions"))
    return driver_refs


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
                         "rischio organizzativo referenziato dev'essere "
                         "registrato (RISK-*)"))


def check(args, config, state, report):
    name = "validate_team_and_governance"
    x_ordinal = fw.stage_ordinal(args.stage, config)
    applicable = config["validators"][name]
    if x_ordinal not in applicable["stages"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile allo stage {args.stage}")
    if args.phase not in applicable["phases"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile alla fase {args.phase}")

    # l'egress del team model enforce SOLO allo Stage 8. Allo Stage 9
    # l'egress è un pass-through — la coerenza del canonico Stage 8 è
    # verificata in fase impact, non ri-enforced qui.
    if args.phase == "egress" and x_ordinal != 8:
        return

    doc = _load_team_doc(args, state, report)
    if doc is None:
        return
    model = doc.get("team_governance") if isinstance(doc, dict) else None
    if not isinstance(model, dict):
        report.add_error(
            "missing_required", ref=args.stage,
            message="team_governance assente nello structured-output",
            expected="team_governance con roles/decision_rights/governance/…",
            actual="assente")
        return

    overlay = fw.build_overlay(state, args.candidate)
    core_ids = _core_process_ids(args, state, report)

    driver_refs, _covered = _check_roles(model, overlay, core_ids or [], report)
    _check_capability_gaps(model, _known_condition_ids(args, state), report)
    _check_decision_rights(model, report)
    _check_governance(model, config, report)
    driver_refs += _check_hiring_plan(model, overlay, args, state, report)
    _check_risk_refs(model, state, report)

    # I driver headcount derivati sono ricalcolabili dai propri driver: un
    # costo «derivato» che non torna è un value_mismatch, non un arrotondamento.
    market._recompute_chain(driver_refs, overlay, config, report)


if __name__ == "__main__":
    fw.run_validator("validate_team_and_governance", check)
