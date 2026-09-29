#!/usr/bin/env python3
"""validate_referential_integrity — integrità referenziale sull'overlay.

Fasi: candidate, egress. Risolve ASS-*/EVD-* dal canonico e P-ASS-* dal
candidate corrente; un P-ASS-* non risolvibile è un errore di referential
integrity, non un dato canonico mancante. Verifica inoltre: nessun duplicato
numerico (candidato -> exit 1; canonico -> exit 3), nessun P-ASS-* nei file
canonici, derivation proposte con formula whitelist e identificatori
dichiarati in variables (invalid_formula -> exit 1, mai 2). Puro e read-only.

Namespace tipizzati OPS-/ROLE-/MIL- (Stage 7-9) con modello
definizione/riferimento field-aware. Le definizioni vivono in un solo file
canonico per namespace e sono raccolte dai soli siti di definizione
dichiarati; i riferimenti sono risolti dai soli campi-riferimento
dichiarati, in una seconda passata. Una definizione non è mai trattata come
un riferimento (nessuna auto-risoluzione fittizia), la forward reference
dentro lo stesso array è quindi legittima, e le definizioni del candidate
dello stage validato sostituiscono in blocco quelle canoniche dello stesso
stage. Le `phases` sono ("candidate", "egress"): refint non gira in fase
`impact`.
"""
import re

import _framework as fw
import formula_dsl as dsl

EVD_RE = re.compile(r"^EVD-[0-9]{3,}$")

# --------------------------------------------------------------------------
# Namespace tipizzati degli Stage 7-9
#
# Un namespace = un prefisso, un unico stage di definizione, un unico file
# canonico. OPS- resta un namespace unico con unicità numerica sull'intero
# progetto: la distinzione fra processi core, dipendenze e asset IP passa da
# `entity_type`, non da prefissi aggiuntivi.
NAMESPACE_STAGE = {
    "OPS": "07_operations-and-ip",
    "ROLE": "08_team-and-governance",
    "MIL": "09_roadmap-and-milestones",
}

OPS_ENTITY_TYPES = ("core_process", "dependency", "ip_asset")

# (namespace, path del contenitore di definizioni, entity_type imposto dal
# sito di definizione; None per i namespace non tipizzati)
DEFINITION_SITES = (
    ("OPS", "operations_model.core_processes[]", "core_process"),
    ("OPS", "operations_model.critical_dependencies[]", "dependency"),
    ("OPS", "operations_model.ip_strategy.assets[]", "ip_asset"),
    ("ROLE", "team_governance.roles[]", None),
    ("MIL", "milestone_plan.milestones[]", None),
)

# (namespace, path del campo-riferimento, entity_type ammessi o None,
# error code se il tipo non corrisponde)
#
# Ogni futuro campo-riferimento verso OPS- deve dichiarare esplicitamente il
# proprio insieme di tipi ammessi: un riferimento senza tipo dichiarato è un
# difetto di specifica, non un permesso implicito a risolvere verso
# qualunque OPS-.
REFERENCE_SITES = (
    ("OPS", "team_governance.roles[].covers_processes[]",
     ("core_process",), "covers_non_process"),
    ("ROLE", "team_governance.decision_rights[].owner_ref", None, None),
    ("ROLE", "team_governance.hiring_plan[].role_ref", None, None),
    ("ROLE", "milestone_plan.milestones[].owner_ref", None, None),
    ("MIL", "milestone_plan.milestones[].depends_on[]", None, None),
)

NAMESPACE_RE = {
    prefix: (re.compile(rf"^{prefix}-{fw.CANONICAL_NUM}$"),
             re.compile(rf"^{prefix}-[0-9]+$"))
    for prefix in NAMESPACE_STAGE
}


def select_path(doc, path):
    """(json_path, nodo) per un path dichiarato: `a.b[].c`, `[]` = array.

    Field-aware: naviga solo i campi nominati. Un path che non esiste nel
    documento non produce nulla — non è un errore, è un documento che non
    definisce (o non referenzia) quel namespace."""
    def walk(node, segments, prefix):
        if not segments:
            yield prefix, node
            return
        segment, rest = segments[0], segments[1:]
        is_array = segment.endswith("[]")
        key = segment[:-2] if is_array else segment
        if not isinstance(node, dict) or key not in node:
            return
        value = node[key]
        here = f"{prefix}.{key}" if prefix else key
        if is_array:
            if not isinstance(value, list):
                return
            for index, item in enumerate(value):
                yield from walk(item, rest, f"{here}[{index}]")
        else:
            yield from walk(value, rest, here)

    yield from walk(doc, path.split("."), "")


def stage_documents(args, config, state):
    """Structured output degli stage fino a quello validato (compreso).

    Il candidate dello stage validato sostituisce IN BLOCCO il canonico
    dello stesso stage: mai un merge fra i due. Se il candidate non
    porta uno structured-output.json non c'è nulla da sostituire e vale il
    canonico."""
    current = fw.stage_ordinal(args.stage, config)
    documents = []
    for stage, ordinal in sorted(config["stage_order"].items(),
                                 key=lambda item: int(item[1])):
        ordinal = int(ordinal)
        if ordinal > current:
            continue
        doc = None
        label = None
        if stage == args.stage and args.candidate is not None:
            candidate_path = args.candidate / "structured-output.json"
            if candidate_path.exists():
                doc = fw.read_candidate_json(candidate_path,
                                             "structured-output.json")
                label = "structured-output.json (candidate)"
        if doc is None:
            canonical_path = state.project / stage / "structured-output.json"
            if canonical_path.exists():
                rel = f"{stage}/structured-output.json"
                doc = fw.read_canonical_json(canonical_path, rel)
                label = rel
        if isinstance(doc, dict):
            documents.append((stage, ordinal, doc, label))
    return documents


def collect_definitions(documents, report):
    """Passata 1: raccolta field-aware delle definizioni per namespace.

    Ritorna (defined, entity_types): `defined[ns]` è l'insieme degli id
    canonici definiti; `entity_types[id]` è l'entity_type di una definizione
    OPS- valida, oppure None se la definizione è untyped/mistyped — nel qual
    caso il difetto è già segnalato qui, sul sito di definizione."""
    defined = {prefix: set() for prefix in NAMESPACE_STAGE}
    numeric_seen = {prefix: {} for prefix in NAMESPACE_STAGE}
    entity_types = {}
    for stage, _ordinal, doc, label in documents:
        for prefix, path, expected_type in DEFINITION_SITES:
            if stage != NAMESPACE_STAGE[prefix]:
                continue
            canonical_re, loose_re = NAMESPACE_RE[prefix]
            for json_path, node in select_path(doc, path):
                if not isinstance(node, dict):
                    continue
                raw_id = node.get("id")
                if not isinstance(raw_id, str) or not loose_re.match(raw_id):
                    continue
                site = f"{label}:{json_path}"
                if not canonical_re.match(raw_id):
                    report.add_error(
                        "non_canonical_id", ref=raw_id,
                        message=f"definizione {prefix} non in forma canonica "
                                f"({site})",
                        expected=f"{prefix}-001 … {prefix}-999, "
                                 f"{prefix}-1000 … (senza zeri iniziali)",
                        actual=raw_id)
                    continue
                number = int(raw_id.split("-", 1)[1])
                if number in numeric_seen[prefix]:
                    report.add_error(
                        "duplicate_definition", ref=raw_id,
                        message=f"definizione {prefix} duplicata: {raw_id} "
                                f"già definito in "
                                f"{numeric_seen[prefix][number]} ({site})")
                    continue
                numeric_seen[prefix][number] = site
                defined[prefix].add(raw_id)
                if expected_type is None:
                    continue
                # entity_type assente, fuori enum o incompatibile con
                # il sito di definizione è un difetto DELLA DEFINIZIONE,
                # ancorato al suo id e non al riferimento downstream. La
                # definizione resta registrata come untyped, così nessun
                # riferimento verso di essa può risultare valido.
                declared = node.get("entity_type")
                if declared == expected_type:
                    entity_types[raw_id] = declared
                    continue
                if not isinstance(declared, str):
                    detail = "entity_type assente"
                elif declared not in OPS_ENTITY_TYPES:
                    detail = f"entity_type fuori enum: {declared!r}"
                else:
                    detail = (f"entity_type {declared!r} incompatibile con il "
                              f"sito di definizione")
                entity_types[raw_id] = None
                report.add_error(
                    "untyped_definition", ref=raw_id,
                    message=f"definizione {prefix} non tipizzata: {detail} "
                            f"({site})",
                    expected=expected_type,
                    actual=declared if isinstance(declared, str) else None)
    return defined, entity_types


def resolve_typed_references(documents, defined, entity_types, current_ordinal,
                             config, report):
    """Passata 2: risoluzione dei soli campi-riferimento dichiarati."""
    for stage, _ordinal, doc, label in documents:
        for prefix, path, allowed_types, mismatch_code in REFERENCE_SITES:
            canonical_re, loose_re = NAMESPACE_RE[prefix]
            definition_ordinal = fw.data_stage_ordinal(
                NAMESPACE_STAGE[prefix], config)
            for json_path, node in select_path(doc, path):
                if not isinstance(node, str):
                    continue
                site = f"{label}:{json_path}"
                if not loose_re.match(node):
                    report.add_error(
                        "unresolved_ref", ref=node,
                        message=f"campo-riferimento {prefix} con un valore "
                                f"che non è un id {prefix}-* ({site})")
                    continue
                if not canonical_re.match(node):
                    report.add_error(
                        "non_canonical_id", ref=node,
                        message=f"riferimento {prefix} non in forma canonica "
                                f"({site})",
                        expected=f"{prefix}-001 … {prefix}-999, "
                                 f"{prefix}-1000 … (senza zeri iniziali)",
                        actual=node)
                    continue
                if definition_ordinal is not None and \
                        definition_ordinal > current_ordinal:
                    report.add_error(
                        "future_namespace_ref", ref=node,
                        message=f"riferimento a un namespace di stage futuro "
                                f"({NAMESPACE_STAGE[prefix]}) rispetto allo "
                                f"stage validato ({site})")
                    continue
                if node not in defined[prefix]:
                    report.add_error(
                        "unresolved_ref", ref=node,
                        message=f"{prefix} non definito in "
                                f"{NAMESPACE_STAGE[prefix]} ({site})")
                    continue
                if allowed_types is None:
                    continue
                declared = entity_types.get(node)
                if declared is None:
                    # Riferimento verso una definizione untyped: non
                    # risolvibile. L'errore resta ancorato alla definizione
                    # difettosa, non al campo che la referenzia.
                    report.add_error(
                        "untyped_definition", ref=node,
                        message=f"riferimento da {site} verso una definizione "
                                f"{prefix} priva di entity_type valido: non "
                                f"risolvibile")
                elif declared not in allowed_types:
                    report.add_error(
                        mismatch_code, ref=node,
                        message=f"riferimento da {site} verso un {prefix} con "
                                f"entity_type {declared!r}",
                        expected=" | ".join(allowed_types),
                        actual=declared)


def check_typed_namespaces(args, config, state, report):
    """Modello definizione/riferimento dei namespace tipizzati OPS-/ROLE-/MIL-."""
    documents = stage_documents(args, config, state)
    if not documents:
        return
    defined, entity_types = collect_definitions(documents, report)
    resolve_typed_references(
        documents, defined, entity_types,
        fw.stage_ordinal(args.stage, config), config, report)


def walk_refs(node, path=""):
    """Genera (json_path, stringa-riferimento) per ogni id esatto trovato.

    Usa la forma "lasca" per gli id ASS/P-ASS: anche un alias non
    canonico (ASS-0001) viene emesso, così può essere rifiutato invece di
    passare inosservato come stringa qualsiasi."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk_refs(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from walk_refs(value, f"{path}[{i}]")
    elif isinstance(node, str):
        if fw.LOOSE_ANY_ASS_RE.match(node) or EVD_RE.match(node):
            yield path, node


def find_derivation_cycles(overlay):
    """Cicli nel grafo delle derivation sull'overlay candidate ⊕ canonico.

    Nodo = id; archi = derivation.variables e selected_ref. Ritorna la lista
    dei cicli trovati, ognuno come lista di id."""
    edges = {}
    for entry_id, entry in overlay.items():
        derivation = entry.get("derivation") \
            if isinstance(entry, dict) else None
        if not isinstance(derivation, dict):
            continue
        targets = []
        variables = derivation.get("variables")
        if isinstance(variables, dict):
            targets += [v for v in variables.values() if isinstance(v, str)]
        selected = derivation.get("selected_ref")
        if isinstance(selected, str):
            targets.append(selected)
        edges[entry_id] = [t for t in targets if t in overlay]
    cycles = []
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in overlay}
    for start in sorted(overlay):
        if color.get(start) != WHITE:
            continue
        stack = [(start, iter(edges.get(start, ())))]
        color[start] = GRAY
        trail = [start]
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if color.get(nxt) == GRAY:
                    cycle = trail[trail.index(nxt):] + [nxt]
                    cycles.append(cycle)
                    continue
                if color.get(nxt) == WHITE:
                    color[nxt] = GRAY
                    trail.append(nxt)
                    stack.append((nxt, iter(edges.get(nxt, ()))))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                trail.pop()
                stack.pop()
    return cycles


def load_evidence_ids(state):
    path = state.project / "shared" / "evidence-register.json"
    if not path.exists():
        return set()
    register = fw.read_canonical_json(path, "shared/evidence-register.json")
    if not isinstance(register, list):
        raise fw.CanonicalStateError("evidence-register.json non è una lista")
    return {entry.get("id") for entry in register if isinstance(entry, dict)}


def canonical_json_files(state, config):
    """File JSON canonici del progetto: shared/ + structured-output di stage."""
    for path in sorted((state.project / "shared").glob("*.json")):
        yield path
    for stage in config["stage_order"]:
        path = state.project / stage / "structured-output.json"
        if path.exists():
            yield path


def check(args, config, state, report):
    name = "validate_referential_integrity"
    x_ordinal = fw.stage_ordinal(args.stage, config)
    applicable = config["validators"][name]
    if x_ordinal not in applicable["stages"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile allo stage {args.stage}")
    if args.phase not in applicable["phases"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile alla fase {args.phase}")

    # Id canonici in forma canonica (ASS-0001 è un alias vietato) e
    # nessun duplicato numerico -> altrimenti stato corrotto (exit 3)
    seen_numeric = {}
    for entry in state.assumptions:
        entry_id = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(entry_id, str) or not fw.ASS_RE.match(entry_id):
            raise fw.CanonicalStateError(
                "assumptions-register.json: id non canonico o mancante: "
                f"{entry_id!r}")
        numeric = fw.ass_numeric(entry_id)
        if numeric in seen_numeric:
            raise fw.CanonicalStateError(
                f"assumptions-register.json: id duplicato {entry_id}")
        seen_numeric[numeric] = entry_id

    overlay = fw.build_overlay(state, args.candidate)

    # Collisioni numeriche nell'overlay (belt & braces: con la forma
    # canonica un alias non può più mascherare lo stesso numero)
    numeric_ids = {}
    for entry_id in overlay:
        numeric = fw.ass_numeric(entry_id)
        if numeric is None:
            continue
        if numeric in numeric_ids and numeric_ids[numeric] != entry_id:
            report.add_error(
                "invalid", ref=entry_id,
                message=(f"collisione numerica tra {numeric_ids[numeric]} "
                         f"e {entry_id}"))
        numeric_ids[numeric] = entry_id

    evidence_ids = load_evidence_ids(state)

    # Nessun P-ASS-* nei file canonici (i P-ASS sono transaction-local)
    for path in canonical_json_files(state, config):
        rel = path.relative_to(state.project).as_posix()
        doc = fw.read_canonical_json(path, rel)
        for json_path, ref in walk_refs(doc):
            if fw.P_ASS_RE.match(ref):
                report.add_error(
                    "pass_in_canonical", ref=ref,
                    message=f"P-ASS nel file canonico {rel} ({json_path})",
                    expected="nessun P-ASS-* nel canonico",
                    actual=ref)

    def resolve(json_path, ref, source):
        if EVD_RE.match(ref):
            if ref not in evidence_ids:
                report.add_error(
                    "unresolved_ref", ref=ref,
                    message=f"EVD non presente in evidence-register "
                            f"({source}: {json_path})")
            return
        if not fw.ANY_ASS_RE.match(ref):
            # forma "lasca" ma non canonica: alias numerico vietato
            report.add_error(
                "non_canonical_id", ref=ref,
                message=(f"id non in forma canonica ({source}: {json_path})"),
                expected="ASS-001 … ASS-999, ASS-1000 … (senza zeri iniziali)",
                actual=ref)
            return
        if fw.resolve_ref(ref, overlay) is None:
            kind = ("P-ASS transaction-local non risolvibile nel candidate"
                    if fw.P_ASS_RE.match(ref)
                    else "ASS canonico non presente nel registro")
            report.add_error(
                "unresolved_ref", ref=ref,
                message=f"{kind} ({source}: {json_path})")

    # Riferimenti del candidate structured-output
    structured_path = args.candidate / "structured-output.json"
    if structured_path.exists():
        structured = fw.read_candidate_json(structured_path,
                                            "structured-output.json")
        for json_path, ref in walk_refs(structured):
            resolve(json_path, ref, "structured-output.json")

    # Derivation delle assunzioni proposte
    for entry in fw.load_proposed_assumptions(args.candidate):
        entry_id = entry.get("id")
        # nessun ratio fuori [0,1] persiste dal percorso di integrity
        value = entry.get("value")
        if entry.get("unit") == "ratio" and \
                isinstance(value, (int, float)) and \
                not isinstance(value, bool) and not 0 <= value <= 1:
            report.add_error(
                "ratio_out_of_bounds", ref=entry_id,
                message=f"ratio canonico fuori da [0,1]: {value}",
                expected="0 <= value <= 1", actual=str(value))
        derivation = entry.get("derivation")
        if not isinstance(derivation, dict):
            continue
        variables = derivation.get("variables")
        if not isinstance(variables, dict) or not variables:
            report.add_error(
                "invalid", ref=entry_id,
                message="derivation senza mappa variables esplicita")
            continue
        for var_name, ref in variables.items():
            if not isinstance(ref, str) or not fw.ANY_ASS_RE.match(ref):
                report.add_error(
                    "invalid", ref=entry_id,
                    message=f"variables.{var_name} non è un id ASS-*/P-ASS-*: "
                            f"{ref!r}")
                continue
            resolve(f"{entry_id}.derivation.variables.{var_name}", ref,
                    "proposed-assumptions.json")
        selected = derivation.get("selected_ref")
        if isinstance(selected, str):
            resolve(f"{entry_id}.derivation.selected_ref", selected,
                    "proposed-assumptions.json")
        formula = derivation.get("formula")
        if formula is None:
            continue
        try:
            names = dsl.formula_names(formula)
        except dsl.FormulaError as exc:
            report.add_error(
                exc.code, ref=entry_id,
                message=f"formula non valida in {entry_id}: {exc.message}")
            continue
        undeclared = sorted(names - set(variables))
        if undeclared:
            report.add_error(
                "invalid_formula", ref=entry_id,
                message=("identificatori non dichiarati in variables: "
                         f"{', '.join(undeclared)}"),
                expected=f"nomi in {sorted(variables)}",
                actual=str(undeclared))

    # Cicli di derivation sull'overlay candidate ⊕ canonico: un ciclo
    # interamente canonico è stato corrotto (exit 3); un ciclo che coinvolge
    # il candidate è un difetto del candidate (exit 1). La sostituzione
    # P-ASS -> ASS preserva i cicli, quindi l'overlay copre anche i
    # riferimenti che diventerebbero ciclici dopo l'allocazione.
    for cycle in find_derivation_cycles(overlay):
        if all(fw.ASS_RE.match(node) for node in cycle):
            raise fw.CanonicalStateError(
                "assumptions-register.json: derivation cicliche nel "
                f"registro canonico: {' -> '.join(cycle)}")
        report.add_error(
            "circular_derivation", ref=cycle[0],
            message=f"derivation cicliche: {' -> '.join(cycle)}")

    # Namespace tipizzati OPS-/ROLE-/MIL-. Un progetto senza
    # structured output 7-9 non produce definizioni né riferimenti: gli esiti
    # degli stage 1-6 restano invariati (test T-COMPAT-0.2).
    check_typed_namespaces(args, config, state, report)


if __name__ == "__main__":
    fw.run_validator("validate_referential_integrity", check)
