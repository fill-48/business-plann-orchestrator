#!/usr/bin/env python3
"""validate_stage_gate — state machine dei gate e conditions register.

Fasi: ingress (condizioni di ingresso + COND dovute), egress (stato del gate
ammesso all'applicazione + COND dovute). Confronto di due_before_stage per
ordinale esplicito (stage_order), mai lessicografico. Puro e read-only: il report
JSON va su stdout; exit 0/1/2/3 secondo il contratto comune dei validator.

Checkpoint evidenze: in egress di Stage 3 legge le classi di
evidenza dei proof point del value-proposition nel candidate. Uno Stage 3
fondato solo su founder_assumption/model_estimate/missing_information non è
approvabile: senza una COND (canonica o proposta nel candidate) con
validation_action, owner e due_before_stage a valle → FAIL
`evidence_checkpoint`; con la COND → WARNING `evidence_unvalidated`
(percorso approved_with_conditions).
"""
import _framework as fw


RESOLUTION_STATES = ("open", "resolved", "waived")

EVIDENCE_CLASSES = frozenset((
    "verified_fact", "internal_evidence", "external_source",
    "founder_assumption", "model_estimate", "missing_information"))
VALIDATED_CLASSES = frozenset((
    "verified_fact", "internal_evidence", "external_source"))

CHECKPOINT_STAGE = "03_value-proposition"


def _check_conditions(config, state, report, x_ordinal):
    for cond in state.conditions:
        if not isinstance(cond, dict):
            raise fw.CanonicalStateError(
                "conditions-register.json: voce non oggetto")
        resolution = cond.get("resolution_status")
        if resolution not in RESOLUTION_STATES:
            # una COND senza resolution_status valido è registro corrotto
            # (stato canonico corrotto): va rifiutata, mai ignorata silenziosamente
            raise fw.CanonicalStateError(
                "conditions-register.json: resolution_status mancante o "
                f"non valido: {resolution!r} ({cond.get('id')})")
        if resolution != "open":
            continue
        due = cond.get("due_before_stage")
        due_ordinal = fw.data_stage_ordinal(due, config)
        if due_ordinal is None:
            raise fw.CanonicalStateError(
                f"conditions-register.json: due_before_stage non canonico: "
                f"{due!r} ({cond.get('id')})")
        if due_ordinal <= x_ordinal:
            report.add_error(
                "condition_due", ref=cond.get("id"),
                message=(f"condizione aperta dovuta prima di {due}: "
                         f"{cond.get('description', '')}"),
                expected="resolution_status != open",
                actual="open")


def _load_candidate_conditions(candidate_dir):
    path = candidate_dir / "proposed-conditions.json"
    if not path.exists():
        return []
    doc = fw.read_candidate_json(path, "proposed-conditions.json")
    if not isinstance(doc, list):
        raise fw.CandidateError(
            "invalid", "proposed-conditions.json non è una lista")
    return [entry for entry in doc if isinstance(entry, dict)]


def _covers_checkpoint(cond, config, stage, x_ordinal):
    """Una COND copre il checkpoint evidenze solo se vincola davvero il futuro:
    aperta, riferita allo Stage 3, con validation_action e owner non vuoti e
    due_before_stage canonico a valle dello Stage 3."""
    if cond.get("stage") != stage:
        return False
    if cond.get("resolution_status") != "open":
        return False
    for field in ("validation_action", "owner"):
        value = cond.get(field)
        if not isinstance(value, str) or not value.strip():
            return False
    due_ordinal = fw.data_stage_ordinal(cond.get("due_before_stage"), config)
    if due_ordinal is None or due_ordinal <= x_ordinal:
        return False
    return True


def _check_evidence_checkpoint(args, config, state, report, x_ordinal):
    """Checkpoint evidenze tra Stage 3 e Stage 4."""
    structured_path = args.candidate / "structured-output.json"
    if not structured_path.exists():
        report.add_error(
            "missing_required", ref=args.stage,
            message=("structured-output.json dovuto in egress di Stage 3: "
                     "il checkpoint evidenze non ha dati da valutare"),
            expected="structured-output.json nel candidate",
            actual="assente")
        return
    doc = fw.read_candidate_json(structured_path, "structured-output.json")
    vp = doc.get("value_proposition") if isinstance(doc, dict) else None
    proof_points = vp.get("proof_points") if isinstance(vp, dict) else None
    if not isinstance(proof_points, list) or not proof_points:
        report.add_error(
            "missing_required", ref=args.stage,
            message=("value_proposition.proof_points dovuti in egress di "
                     "Stage 3: ogni claim va provato o marcato assunzione "
                     "(checkpoint evidenze)"),
            expected="proof_points non vuoti",
            actual="assenti o vuoti")
        return

    validated = 0
    for i, point in enumerate(proof_points):
        label = f"proof_points[{i}]"
        if not isinstance(point, dict):
            report.add_error(
                "invalid", ref=args.stage,
                message=f"{label}: proof point non oggetto")
            continue
        classification = point.get("evidence_classification")
        if classification not in EVIDENCE_CLASSES:
            report.add_error(
                "invalid", ref=args.stage,
                message=(f"{label}: evidence_classification fuori dalle 6 "
                         f"classi ammesse: {classification!r}"),
                expected="|".join(sorted(EVIDENCE_CLASSES)),
                actual=str(classification))
            continue
        if classification in VALIDATED_CLASSES:
            refs = point.get("evidence_refs")
            if not isinstance(refs, list) or not refs:
                report.add_error(
                    "invalid", ref=args.stage,
                    message=(f"{label}: classe {classification} senza "
                             "evidence_refs: un claim validato deve puntare "
                             "alle evidenze (EVD-*)"),
                    expected="evidence_refs non vuoti",
                    actual="assenti o vuoti")
                continue
            validated += 1

    if validated > 0:
        return

    # Nessuna evidenza validata: ammesso solo il percorso
    # approved_with_conditions, con una COND che copra il checkpoint.
    conditions = list(state.conditions)
    conditions += _load_candidate_conditions(args.candidate)
    if any(_covers_checkpoint(cond, config, args.stage, x_ordinal)
           for cond in conditions):
        report.add_warning(
            "evidence_unvalidated", ref=args.stage,
            message=("Stage 3 fondato solo su assunzioni non validate: al "
                     "massimo approved_with_conditions, mai approved "
                     "(checkpoint evidenze)"))
        return
    report.add_error(
        "evidence_checkpoint", ref=args.stage,
        message=("Stage 3 fondato solo su founder_assumption/model_estimate/"
                 "missing_information senza una COND con validation_action, "
                 "owner e due_before_stage a valle: non approvabile "
                 "(checkpoint evidenze)"),
        expected=("almeno un proof point con evidenza validata, oppure una "
                  "COND aperta che copra la validazione"),
        actual="nessuna evidenza validata e nessuna COND idonea")


def check(args, config, state, report):
    name = "validate_stage_gate"
    x_ordinal = fw.stage_ordinal(args.stage, config)
    applicable = config["validators"][name]
    if x_ordinal not in applicable["stages"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile allo stage {args.stage}")
    if args.phase not in applicable["phases"]:
        raise fw.ValidatorUsageError(
            f"{name} non applicabile alla fase {args.phase}")

    status = state.status
    current_stage = status.get("current_stage")
    gate_state = status.get("status")
    completed = status.get("completed_stages", [])
    if not isinstance(completed, list):
        raise fw.CanonicalStateError("completed_stages non è una lista")
    gate_states = set(config["gate_states"])
    approved = set(config["approved_states"])

    if gate_state == "not_applicable":
        report.add_error(
            "invalid_state", ref=current_stage,
            message=("not_applicable è vietato: non è uno stato della "
                     "state machine dei gate"),
            expected="uno stato della state machine dei gate (gate_states)",
            actual="not_applicable")
        return
    if gate_state not in gate_states and gate_state != "not_started":
        raise fw.CanonicalStateError(
            f"project-status: stato gate non riconosciuto: {gate_state!r}")

    # Coerenza semantica globale dello status: duplicati,
    # ordine, prefisso, salti di stage e stati incongruenti sono stato
    # canonico corrotto (exit 3), mai un PASS silenzioso.
    fw.validate_status_coherence(status, config)

    if gate_state == "conflict_awaiting_confirmation":
        report.add_error(
            "conflict_pending", ref=current_stage,
            message=("conflitto in attesa di conferma esplicita: nessun "
                     "avanzamento né applicazione canonica"),
            expected="nessun conflitto pendente",
            actual="conflict_awaiting_confirmation")

    if args.phase == "ingress":
        if args.stage in completed:
            report.add_error(
                "stage_already_completed", ref=args.stage,
                message=("stage già approvato: non si riapre senza ISSUE- "
                         "(§15)"),
                expected="stage non in completed_stages",
                actual="in completed_stages")
        else:
            predecessor = None
            for folder, ordinal in config["stage_order"].items():
                if int(ordinal) == x_ordinal - 1:
                    predecessor = folder
                    break
            if predecessor is None or predecessor not in completed:
                report.add_error(
                    "stage_not_authorized", ref=args.stage,
                    message=(f"stage precedente ({predecessor}) non "
                             "completato: ingresso non autorizzato"),
                    expected=f"{predecessor} in completed_stages",
                    actual=str(completed))
            elif current_stage == predecessor:
                # ingresso dallo stage precedente: il suo gate deve essere
                # approvato (il solo completed_stages non basta)
                if gate_state not in approved:
                    report.add_error(
                        "predecessor_not_approved", ref=predecessor,
                        message=("il gate dello stage precedente non è "
                                 "approved/approved_with_conditions"),
                        expected="approved | approved_with_conditions",
                        actual=gate_state)
            elif current_stage == args.stage:
                # stage predisposto ma non ancora avviato:
                # l'unico stato ammesso per l'ingresso è not_started
                if gate_state != "not_started":
                    report.add_error(
                        "invalid_state", ref=args.stage,
                        message=("stage già avviato: il re-ingresso non è "
                                 "un ingresso"),
                        expected="not_started",
                        actual=gate_state)
            else:
                # qualunque altra combinazione è già stata rifiutata dalla
                # coerenza globale (current futuro/incongruente -> exit 3)
                report.add_error(
                    "stage_not_authorized", ref=args.stage,
                    message=("current_stage incongruente con l'ingresso "
                             f"richiesto: {current_stage!r}"),
                    expected=f"{predecessor} | {args.stage}",
                    actual=str(current_stage))
    else:  # egress
        if args.stage in completed:
            # uno stage già completato non si riscrive mai in egress
            # (a prescindere dallo stato del gate), salvo protocollo ISSUE.
            report.add_error(
                "stage_already_completed", ref=args.stage,
                message=("stage già completato: l'output non si riscrive "
                         "senza ISSUE- (§15)"),
                expected="stage non in completed_stages",
                actual="in completed_stages")
        elif current_stage != args.stage:
            report.add_error(
                "stage_not_authorized", ref=args.stage,
                message=("egress richiesto per uno stage diverso da "
                         "current_stage"),
                expected=args.stage,
                actual=str(current_stage))
        elif gate_state in approved:
            report.add_error(
                "stage_already_completed", ref=args.stage,
                message=("stage già approvato: l'output non si riscrive "
                         "senza ISSUE- (§15)"),
                expected="in_progress | needs_revision",
                actual=gate_state)
        elif gate_state == "blocked":
            report.add_error(
                "invalid_state", ref=args.stage,
                message="stage bloccato: nessuna applicazione canonica",
                expected="in_progress | needs_revision",
                actual="blocked")
        elif gate_state == "not_started":
            report.add_error(
                "invalid_state", ref=args.stage,
                message="stage mai avviato: nessun output da applicare",
                expected="in_progress | needs_revision",
                actual="not_started")

    _check_conditions(config, state, report, x_ordinal)

    if args.phase == "egress" and args.stage == CHECKPOINT_STAGE:
        _check_evidence_checkpoint(args, config, state, report, x_ordinal)


if __name__ == "__main__":
    fw.run_validator("validate_stage_gate", check)
