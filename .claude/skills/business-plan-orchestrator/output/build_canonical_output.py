#!/usr/bin/env python3
"""Costruttore dell'OUTPUT CANONICO dello Stage 10.

Proietta il payload INTERMEDIO NON CANONICO prodotto dal motore finanziario
(`validators/validate_financial_engine.py`) sulla forma dichiarata da
`schemas/financial-plan.schema.json` `1.1.0`.

REGOLA STRUTTURALE — NESSUN RICALCOLO
-------------------------------------
Questo modulo e' una FUNZIONE DI PROIEZIONE TOTALE, non un secondo motore.
Non importa il motore, non ricostruisce serie, non somma, non arrotonda e non
converte. La regola non e' di stile: e' MISURATA con una
scansione statica AST che vive nel validator DI PRODUZIONE
(`validators/validate_financial_output.py`) e che dichiara un ELENCO CHIUSO
DI OPERAZIONI AMMESSE:

  - NESSUN operatore aritmetico (`+ - * / // % ** @`), a nessuna profondita';
  - NESSUNA delle funzioni di aggregazione o conversione numerica
    `sum, round, abs, pow, divmod, Decimal, float, complex, int`;
  - NESSUN import di `validate_financial_engine`, `formula_dsl` o `decimal`.

Il prezzo dichiarato e' che il modulo compone path con `Path.joinpath` e
stringhe con f-string e `str.join`, mai con `/` o `+`. E' un prezzo di
LEGGIBILITA' pagato per rendere la scansione NON VACUA per costruzione, e la
sua non-vacuita' e' a sua volta provata da un'AUTO-SONDA dedicata.

UNA SOLA FONTE NUMERICA DI VERITA'
----------------------------------
Ogni numero del documento canonico ESISTE nel payload del motore, allo stesso
path logico e con lo STESSO valore serializzato. Nulla e' derivato qui.

MAPPATURA TOTALE, E LE OMISSIONI SONO DICHIARATE
------------------------------------------------
Ogni blocco del payload che NON entra nel canonico e' NOMINATO in `handoff.md`
e nel report di questo modulo. Un blocco di primo livello che ne' la mappa ne'
lo schema conoscono e' un FAIL, non un caso da interpretare.

CONFINE DI SCRITTURA
--------------------
Scrive ESCLUSIVAMENTE dentro `<project>/10_financial-plan/.working/<tx>/`: e'
il CANDIDATE, non il canonico. Il canonico e' scritto dal Transaction Manager.
`resolve_output_target()` del motore NON e' rilassata: il motore continua a non
scrivere alcun path di progetto, ed e' questo modulo — separato — a scrivere
nel candidate. Un progetto collocato dentro la directory della skill e'
RESPINTO prima di ogni I/O (`real_project_write_forbidden`).

NON PRODUCE ALCUN DERIVATO: nessun Markdown, nessun XLSX, nessun import di
libreria OOXML. Il capitolo e il workbook sono prodotti da
`render_financial_plan.py` e `export_financial_model.py`.

Exit code:  0 documento prodotto · 1 rifiuto attribuito · 2 errore d'uso.
"""
import argparse
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

BUILDER_NAME = "build_canonical_output"
STAGE10 = "10_financial-plan"
WORKING_DIR = ".working"
CANONICAL_NAME = "structured-output.json"
HANDOFF_NAME = "handoff.md"

#: Versione dello schema canonico prodotta da questo modulo.
SCHEMA_VERSION = "1.1.0"

#: Marcatore del payload intermedio ACCETTATO. Un payload che non lo porta non
#: e' l'ingresso dichiarato di questo modulo.
PAYLOAD_KIND = "intermediate_non_canonical"

#: I QUINDICI `module_id` che `results.modules` dichiara `required`.
MODULE_IDS = (
    "revenue", "cogs", "gross_margin", "headcount", "payroll", "opex", "pnl",
    "cash_flow", "balance_sheet", "runway", "cash_buffer", "break_even",
    "funding_gap", "milestone_coverage", "kpi",
)

#: I TRE scenari. `coverage` NON e' uno scenario.
SCENARIO_IDS = ("base", "downside", "upside")

#: Enumerazione CHIUSA di `driver_status`, dal peggiore al migliore.
STATUS_ORDER = ("unresolved", "placeholder", "inferred", "confirmed")

#: Le DODICI riconciliazioni `required` dallo schema.
RECONCILIATION_IDS = (
    "REC-01", "REC-02", "REC-03", "REC-04", "REC-05", "REC-06", "REC-09",
    "REC-11", "REC-12", "REC-13", "REC-14", "REC-15",
)

#: Blocchi di PRIMO LIVELLO ammessi nel payload del motore. Un blocco che non
#: compare qui e' un FAIL: la mappatura e' TOTALE.
PAYLOAD_TOP_LEVEL = ("kind", "milestone", "financial_payload",
                     "governance_projection", "tolerance_ledger")

#: Blocchi di PRIMO LIVELLO ammessi dentro `financial_payload`.
PLAN_BLOCKS = ("driver_registry", "results", "reconciliations", "validation",
               "calculation_metadata", "sensitivity")

#: Le SEI proprieta' che lo schema dichiara su `calculation_metadata`, che e'
#: `additionalProperties: false`.
CALCULATION_METADATA_KEYS = ("engine_version", "engine_source_hash",
                             "calculation_policy_version", "modules",
                             "output_checksums", "dependency_graph")

#: Tassonomia di fonti e usi, DICHIARATA qui e non importata: e'
#: l'enumerazione di `$defs.cost_category`, ripartita fra FONTI e USI.
#: Duplicare un'ENUMERAZIONE DICHIARATA non e' duplicare un NUMERO.
SOURCE_CATEGORIES = ("operating_revenue", "other_operating_income")
USE_CATEGORIES = ("operating_cost", "interest", "mandatory_financing_fee")
USE_CATEGORY_LABELS = {
    "operating_cost": "costi operativi",
    "interest": "oneri finanziari",
    "mandatory_financing_fee": "commissioni di finanziamento obbligatorie",
}

#: OMISSIONI DICHIARATE della mappatura payload -> canonico. Nessuna
#: e' silenziosa: ciascuna e' NOMINATA nell'handoff e nel report.
DECLARED_OMISSIONS = (
    ("superseded",
     "driver_registry.superseded — nessun portatore esiste nello schema "
     "canonico, che e' additionalProperties: false su driver_registry. La "
     "precedenza risolta resta nel payload del motore e nel journal."),
    ("sensitivity",
     "financial_payload.sensitivity — nessun portatore esiste nello schema "
     "canonico: in questa versione l'analisi di sensitivita' NON fa "
     "parte del documento canonico."),
    ("tolerance_ledger",
     "tolerance_ledger — artefatto della guardia di tolleranza del motore, di "
     "natura DI TEST: non appartiene al documento pubblicato."),
    ("results.modules.calendar",
     "results.modules.calendar — il calendario NON e' un module_id: lo stesso "
     "blocco, byte per byte, e' pubblicato da results.calendar, che lo schema "
     "dichiara `required`. Nessuna informazione e' persa."),
    ("calculation_metadata.scenario_coverage_threshold_applied",
     "calculation_metadata.scenario_coverage_threshold_applied — "
     "calculation_metadata e' additionalProperties: false e non lo dichiara. "
     "La STESSA soglia DICHIARATA e' pubblicata da "
     "results.scenarios.coverage.threshold, che il canonico porta verbatim: "
     "la coincidenza dei due portatori e' VERIFICATA, non assunta."),
)

#: Codici del rifiuto. Sono IDENTIFICATORI STRUTTURALI della classe `check_id`,
#: nella stessa forma che il motore gia' usa (`financial_engine_gate`,
#: `scenario_coverage`): nessun codice di dominio e' coniato qui.
CODE_PAYLOAD_INVALID = "canonical_payload_invalid"
CODE_UNMAPPED_BLOCK = "canonical_payload_unmapped_block"
CODE_BLOCKED_RUN = "canonical_builder_gate"
CODE_REAL_PROJECT = "real_project_write_forbidden"
CODE_TARGET_FORBIDDEN = "canonical_path_forbidden"
CODE_THRESHOLD_DIVERGENT = "canonical_threshold_divergent"

#: Codici delle RAGIONI DI BLOCCO della prontezza investor-ready, che esige
#: ragioni TIPIZZATE e ATTRIBUITE, mai prosa: ciascuna porta un codice e i
#: propri `affected_refs`.
BLOCK_RESULT = "validation_result"
BLOCK_PROPAGATED = "propagated_status"
BLOCK_UNBOUND = "driver_role_unbound"
BLOCK_COVERAGE = "scenario_coverage"
BLOCK_GOVERNANCE = "governance_plan_propagated_status"


class BuilderRefusal(Exception):
    """Rifiuto ATTRIBUITO: codice, riferimento e messaggio (exit 1)."""

    def __init__(self, code, ref, message):
        super().__init__(message)
        self.code = code
        self.ref = ref
        self.message = message


class BuilderUsageError(Exception):
    """Errore di invocazione del costruttore (exit 2)."""


# --------------------------------------------------------------------------
# Scrittura ATOMICA — livello 1, per singolo file
# --------------------------------------------------------------------------


def atomic_write(path, text):
    """Contenuto COSTRUITO IN MEMORIA, file TEMPORANEO nella STESSA directory,
    `flush` + `fsync`, `os.replace` ATOMICO sul nome finale.

    Un fallimento a QUALUNQUE punto lascia il file precedente INTATTO e non
    lascia alcun file parziale — ne' col nome finale, ne' come temporaneo
    orfano. Non e' MAI ammesso aprire il file finale in scrittura e riempirlo
    progressivamente.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=str(target.parent),
        prefix=".canonical-", suffix=".part", delete=False)
    temporary = Path(handle.name)
    try:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(str(temporary), str(target))
    except BaseException:
        try:
            handle.close()
        except OSError:
            pass
        if temporary.exists():
            temporary.unlink()
        raise
    return target


def canonical_json(document):
    """Forma canonica DETERMINISTICA — la STESSA che il motore gia' produce:
    chiavi ordinate lessicograficamente, indentazione 2, `ensure_ascii`, una
    newline finale."""
    body = json.dumps(document, indent=2, ensure_ascii=True, sort_keys=True)
    return "".join([body, "\n"])


# --------------------------------------------------------------------------
# Ordinamenti DETERMINISTICI
# --------------------------------------------------------------------------


def sorted_drivers(drivers):
    """Array di driver ORDINATO per `driver_id`."""
    return sorted(list(drivers or []), key=lambda entry: str(
        entry.get("driver_id")))


def sorted_milestones(milestones):
    """Array di milestone ORDINATO per `milestone_ref`."""
    return sorted(list(milestones or []), key=lambda entry: str(
        entry.get("milestone_ref")))


def sorted_checks(checks):
    """Array di check ORDINATO per `check_id`, poi per INDICE DI INSERIMENTO.
    `sorted` e' STABILE: l'ordine di inserimento e' preservato a
    parita' di `check_id`."""
    return sorted(list(checks or []), key=lambda entry: str(
        entry.get("check_id")))


def first_ref(entry):
    refs = entry.get("affected_refs") or []
    if not refs:
        return ""
    return str(refs[0])


def sorted_findings(entries):
    """Array di errori e warning ORDINATO per `(code, primo affected_ref)`."""
    return sorted(list(entries or []),
                  key=lambda entry: (str(entry.get("code")), first_ref(entry)))


def minimum_status(refs, status_by_driver):
    """MINIMO dell'enumerazione CHIUSA `driver_status` sui riferimenti DATI.

    Non e' un calcolo di dominio: e' la selezione del minimo di un'enumerazione
    ordinata, esattamente la stessa che la proiezione del motore gia' compie, e
    il canonico la RIPRODUCE senza inventare valori. Dove nessun riferimento e'
    governato, lo stato e' il FONDO dell'enumerazione: fail-closed.
    """
    values = [status_by_driver.get(ref) for ref in refs or []
              if status_by_driver.get(ref) is not None]
    if not values:
        return STATUS_ORDER[0]
    return min(values, key=STATUS_ORDER.index)


# --------------------------------------------------------------------------
# Confine di scrittura
# --------------------------------------------------------------------------


def skill_root():
    return Path(__file__).resolve().parents[1]


def resolve_candidate(project, tx):
    """Il CANDIDATE, e nessun altro path.

    Rifiuta un `tx` che non sia un singolo segmento di path e un progetto il
    cui path risolto cade dentro la directory della skill
    (`real_project_write_forbidden`): i progetti vivono nella working
    directory dell'utente, mai nel pacchetto installato. L'unico target ammesso e'
    `<project>/10_financial-plan/.working/<tx>/`.
    """
    if not tx or "/" in tx or "\\" in tx or tx in (".", ".."):
        raise BuilderUsageError(
            f"--tx deve essere un singolo segmento di path: {tx!r}")
    target = Path(project).resolve()
    projects = skill_root()
    try:
        target.relative_to(projects)
    except ValueError:
        pass
    else:
        raise BuilderRefusal(
            CODE_REAL_PROJECT, target.as_posix(),
            "il costruttore canonico rifiuta un progetto il cui path cade "
            "dentro la directory della skill: il pacchetto non e' mai "
            "scritto e resta BYTE-IDENTICO prima e dopo ogni esecuzione. "
            "I progetti dell'utente vivono nella sua working directory")
    candidate = target.joinpath(STAGE10, WORKING_DIR, tx)
    if candidate.name != tx or candidate.parent.name != WORKING_DIR:
        raise BuilderRefusal(
            CODE_TARGET_FORBIDDEN, candidate.as_posix(),
            "il solo target autorizzato e' "
            "<project>/10_financial-plan/.working/<tx>/")
    return candidate


# --------------------------------------------------------------------------
# Gate di ingresso
# --------------------------------------------------------------------------


def read_payload(path):
    source = Path(path)
    if not source.is_file():
        raise BuilderUsageError(f"payload del motore assente: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BuilderUsageError(f"payload del motore non e' JSON: {exc}")
    if not isinstance(payload, dict):
        raise BuilderRefusal(
            CODE_PAYLOAD_INVALID, "(radice)",
            "il payload del motore non e' un oggetto JSON")
    return payload


def check_total_mapping(payload):
    """La mappatura payload -> canonico e' TOTALE ed ESPLICITA.

    Un blocco di primo livello che ne' la mappa ne' lo schema conoscono e' un
    FAIL, non un caso da interpretare: e' la stessa disciplina fail-closed della
    mappatura di stato.
    """
    for key in sorted(payload):
        if key not in PAYLOAD_TOP_LEVEL:
            raise BuilderRefusal(
                CODE_UNMAPPED_BLOCK, key,
                f"blocco di primo livello NON MAPPATO nel payload: {key!r}. "
                "La mappatura payload -> canonico e' TOTALE: nessuna omissione "
                "silenziosa e nessuna interpretazione")
    plan = payload.get("financial_payload")
    if not isinstance(plan, dict):
        raise BuilderRefusal(
            CODE_PAYLOAD_INVALID, "financial_payload",
            "il payload non porta `financial_payload`")
    for key in sorted(plan):
        if key not in PLAN_BLOCKS:
            raise BuilderRefusal(
                CODE_UNMAPPED_BLOCK, f"financial_payload.{key}",
                f"blocco di primo livello NON MAPPATO dentro "
                f"financial_payload: {key!r}")
    if payload.get("kind") != PAYLOAD_KIND:
        raise BuilderRefusal(
            CODE_PAYLOAD_INVALID, "kind",
            f"il payload non porta il marcatore atteso "
            f"kind == {PAYLOAD_KIND!r}: {payload.get('kind')!r}")
    return plan


def check_run_not_blocked(plan):
    """Una RUN BLOCCATA non produce ALCUN documento.

    Il payload di una run bloccata porta il `driver_registry` VERBATIM, quindi
    NON valido per lo schema: deve restare CONFINATO al percorso di
    fallimento. Il costruttore lo RIFIUTA e non scrive alcun file — nemmeno
    parziale, nemmeno nel candidate — e non lo «ripulisce», perche' ripulirlo
    nasconderebbe la violazione invece di mostrarla.
    """
    validation = plan.get("validation") or {}
    modules = (plan.get("results") or {}).get("modules") or {}
    produced = [key for key in modules if key != "calendar"]
    if validation.get("result") == "FAIL" or not produced:
        raise BuilderRefusal(
            CODE_BLOCKED_RUN, "financial_payload.validation.result",
            "RUN BLOCCATA: il gate fail-closed del motore precede il calcolo "
            f"(validation.result = {validation.get('result')!r}, moduli "
            f"prodotti = {sorted(produced)}). Nessun documento canonico e' "
            "scritto, nemmeno parziale e nemmeno nel candidate, e il payload "
            "NON e' ripulito: un driver_registry non valido per schema resta "
            "confinato al percorso di fallimento")


# --------------------------------------------------------------------------
# Proiezione
# --------------------------------------------------------------------------


def project_driver_registry(plan):
    """COPIA STRUTTURALE, piu' `materiality` e `source_type` SE PRESENTI.

    `superseded` e' un'OMISSIONE DICHIARATA: lo schema canonico non lo
    dichiara. Nessun campo e' dedotto: dove `materiality` e' ASSENTE nel
    payload resta ASSENTE nel canonico, e la resa a valle e' «non dichiarata»,
    MAI «bassa».
    """
    registry = copy.deepcopy(plan.get("driver_registry") or {})
    registry.pop("superseded", None)
    registry["drivers"] = sorted_drivers(registry.get("drivers"))
    registry["unbound_required_roles"] = sorted(
        list(registry.get("unbound_required_roles") or []))
    return registry


def use_of_proceeds_candidates(modules):
    """CATEGORIE ELEGGIBILI, mai un'allocazione.

    Sono la PROIEZIONE delle sole categorie di USO gia' DICHIARATE dalle righe
    di costo dei moduli prodotti: una classificazione, non una quantita'.
    Nessun importo e' associato a una categoria, nessuna somma di categorie
    produce un totale, e la loro somma non e' un `ask`. E' cio' che rende
    STRUTTURALMENTE impossibile l'allocazione che appartiene allo Stage 11.
    """
    refs_by_category = {}
    modules_by_category = {}
    for module_id in sorted(modules):
        for line in (modules[module_id] or {}).get("lines") or []:
            category = line.get("category")
            if category not in USE_CATEGORIES:
                continue
            refs_by_category.setdefault(category, set()).update(
                line.get("driver_refs") or [])
            modules_by_category.setdefault(category, set()).add(module_id)
    candidates = []
    for category in sorted(refs_by_category):
        sources = ", ".join(sorted(modules_by_category.get(category) or []))
        candidates.append({
            "category_id": category,
            "label": USE_CATEGORY_LABELS.get(category, category),
            "eligibility_basis": (
                f"categoria di USO della tassonomia dei costi, DICHIARATA "
                f"dalle righe di costo dei moduli {sources}. E' una CATEGORIA "
                "ELEGGIBILE, non un'allocazione: nessun importo le e' "
                "associato e la somma delle categorie non e' una richiesta di "
                "funding"),
            "driver_refs": sorted(refs_by_category[category]),
        })
    return candidates


def project_modules(plan, profile):
    """I QUINDICI moduli. Un modulo non prodotto o non pertinente NON e'
    omesso: porta `NOT_APPLICABLE` con motivazione NOMINATA."""
    produced = copy.deepcopy((plan.get("results") or {}).get("modules") or {})
    produced.pop("calendar", None)
    not_applicable = list(profile.get("not_applicable_modules") or [])
    modules = {}
    for module_id in MODULE_IDS:
        entry = produced.get(module_id)
        if entry is not None:
            modules[module_id] = entry
            continue
        if module_id == "balance_sheet":
            modules[module_id] = {
                "module_id": "balance_sheet",
                "status": "NOT_APPLICABLE",
                "reason": (
                    "stato patrimoniale non calcolato in questa versione: "
                    "e' un'OMISSIONE DICHIARATA e VISIBILE, mai "
                    "un'assenza"),
                "decision_ref": "DEC-S10-23",
            }
            continue
        modules[module_id] = {
            "module_id": module_id,
            "status": "NOT_APPLICABLE",
            "not_applicable_reason": (
                f"il modulo {module_id} NON e' prodotto dal motore finanziario: "
                "il payload intermedio non lo porta e il costruttore canonico "
                "NON ricalcola alcuna grandezza finanziaria (D-01). Il modulo "
                "e' PUBBLICATO come NOT_APPLICABLE con questa motivazione "
                "NOMINATA, mai omesso: un modulo assente da un output si legge "
                "come non pertinente, mentre la verita' e' che non e' stato "
                "calcolato"),
        }
    for module_id in sorted(not_applicable):
        entry = modules.get(module_id) or {}
        if entry.get("status") != "NOT_APPLICABLE":
            raise BuilderRefusal(
                CODE_PAYLOAD_INVALID, module_id,
                f"il profilo attivo dichiara {module_id} in "
                f"not_applicable_modules ma il payload lo porta con status "
                f"{entry.get('status')!r}")
    funding = modules.get("funding_gap") or {}
    if funding.get("status") != "NOT_APPLICABLE":
        candidates = use_of_proceeds_candidates(produced)
        if candidates:
            funding["use_of_proceeds_candidates"] = candidates
    coverage = modules.get("milestone_coverage") or {}
    if coverage.get("milestones"):
        coverage["milestones"] = sorted_milestones(coverage.get("milestones"))
    return modules


def project_reconciliations(plan):
    """Le DODICI riconciliazioni. `REC-09` non e' prodotta dal motore: e'
    PUBBLICATA `NOT_APPLICABLE` con motivazione NOMINATA, mai omessa e mai
    inventata — calcolarla qui violerebbe la regola del nessun ricalcolo."""
    recon = copy.deepcopy(plan.get("reconciliations") or {})
    for rec_id in RECONCILIATION_IDS:
        if rec_id in recon:
            continue
        recon[rec_id] = {
            "rec_id": rec_id,
            "formula": (
                "copertura delle milestone: costo di ciascuna MIL-* contro le "
                "risorse correnti e gia' acquisite"),
            "status": "NOT_APPLICABLE",
            "severity": "FAIL",
            "tolerance": "EUR 0.01",
            "tolerance_unit": "EUR",
            "not_applicable_reason": (
                f"{rec_id} non e' prodotta dal motore finanziario: il modulo "
                "milestone_coverage non appartiene al payload del motore e "
                "il costruttore canonico NON ricalcola alcuna grandezza "
                "finanziaria (D-01). La riconciliazione e' RIPORTATA come "
                "NOT_APPLICABLE con questa motivazione NOMINATA, perche' un "
                "controllo che non compare nel report equivale a un controllo "
                "non eseguito"),
        }
    return recon


def project_calculation_metadata(plan, coverage):
    """`calculation_metadata` proiettata sulle SOLE proprieta' dichiarate.

    `scenario_coverage_threshold_applied` non e' dichiarata dallo schema, che e'
    `additionalProperties: false`. La STESSA soglia e' pubblicata da
    `results.scenarios.coverage.threshold`: la coincidenza e' VERIFICATA, non
    assunta, e l'omissione e' DICHIARATA nell'handoff.
    """
    metadata = copy.deepcopy(plan.get("calculation_metadata") or {})
    applied = metadata.pop("scenario_coverage_threshold_applied", None)
    declared = (coverage or {}).get("threshold")
    if applied is not None and str(applied) != str(declared):
        raise BuilderRefusal(
            CODE_THRESHOLD_DIVERGENT,
            "calculation_metadata.scenario_coverage_threshold_applied",
            f"la soglia di copertura applicata {applied!r} DIVERGE da quella "
            f"pubblicata da results.scenarios.coverage.threshold {declared!r}: "
            "l'omissione dichiarata presuppone che i due portatori coincidano")
    projected = {}
    for key in CALCULATION_METADATA_KEYS:
        if key in metadata:
            projected[key] = metadata[key]
    return projected


def project_governance(payload, modules, scenarios):
    """Canonicalizzazione dello STATO PROPAGATO.

    Porta STATO e RIFERIMENTI, MAI una quantita'. Il `propagated_status` e i
    `driver_refs`/`input_driver_refs` provengono dalla PROIEZIONE NON CANONICA
    che il motore gia' produce; lo `status` proviene dal modulo o
    dallo scenario PRODOTTO. Nessuna voce e' omessa: quindici moduli e tre
    scenari, sempre.
    """
    projection = payload.get("governance_projection") or {}
    projected_modules = projection.get("modules") or {}
    projected_scenarios = projection.get("scenarios") or {}
    entries = {}
    for module_id in MODULE_IDS:
        source = projected_modules.get(module_id) or {}
        entry = {
            "propagated_status": source.get(
                "propagated_status", STATUS_ORDER[0]),
            "status": module_status_of(modules.get(module_id) or {}),
        }
        refs = sorted(list(source.get("input_driver_refs") or []))
        if refs:
            entry["input_driver_refs"] = refs
        reason = not_applicable_reason_of(modules.get(module_id) or {})
        if entry["status"] == "NOT_APPLICABLE" and reason:
            entry["not_applicable_reason"] = reason
        entries[module_id] = entry
    scenario_entries = {}
    for scenario_id in SCENARIO_IDS:
        source = projected_scenarios.get(scenario_id) or {}
        result = scenarios.get(scenario_id) or {}
        entry = {
            "propagated_status": source.get(
                "propagated_status", STATUS_ORDER[0]),
            "status": scenario_status_of(result),
        }
        refs = sorted(list(source.get("driver_refs") or []))
        if refs:
            entry["driver_refs"] = refs
        reason = result.get("not_applicable_reason")
        if entry["status"] == "NOT_APPLICABLE" and reason:
            entry["not_applicable_reason"] = reason
        scenario_entries[scenario_id] = entry
    return {
        "plan": {"propagated_status": (projection.get("plan") or {}).get(
            "propagated_status", STATUS_ORDER[0])},
        "modules": entries,
        "scenarios": scenario_entries,
    }


def module_status_of(entry):
    """Mappatura TOTALE e DICHIARATA su `module_status`.

    Gli stati di un modulo prodotto sono gia' quelli di `module_status`; uno
    stato fuori dominio non e' declassato a un default, e' un rifiuto
    fail-closed.
    """
    status = entry.get("status")
    if status in ("PASS", "WARNING", "NOT_APPLICABLE"):
        return status
    raise BuilderRefusal(
        CODE_PAYLOAD_INVALID, str(entry.get("module_id")),
        f"stato di modulo fuori dal dominio module_status: {status!r}")


def scenario_status_of(entry):
    """Mappatura TOTALE e DICHIARATA da `canonical_check_status` di uno
    `scenario_result` su `module_status` della voce di governance.

    Il motore produce `PASS` per uno scenario prodotto e
    `NOT_APPLICABLE` per uno non prodotto. `WARNING` e' trasportato alla
    lettera. Ogni altro stato — `FAIL`, `UNRESOLVED_INPUT` — non ha una
    controparte in `module_status` e non e' declassato a un default: e' un
    rifiuto fail-closed, mai un'interpretazione.
    """
    status = entry.get("status")
    if status in ("PASS", "WARNING", "NOT_APPLICABLE"):
        return status
    raise BuilderRefusal(
        CODE_PAYLOAD_INVALID, str(entry.get("scenario")),
        f"stato di scenario {status!r} privo di controparte in module_status: "
        "la mappatura di governance e' TOTALE e fail-closed")


def not_applicable_reason_of(entry):
    return entry.get("not_applicable_reason") or entry.get("reason")


def investor_readiness(plan, registry, scenarios, recon, governance):
    """Prontezza INVESTOR-READY, regola CONSERVATIVA.

    E' la TERZA prontezza e resta DISTINTA dalle altre due. La regola e'
    STRETTAMENTE PIU' SEVERA di qualunque regola filtrata per materialita': non
    puo' produrre un falso `ready`, puo' solo bloccare piu' del dovuto — che e'
    la direzione FAIL-CLOSED. NESSUN percorso la deriva da `validation.result`
    soltanto, e la materialita' NON la filtra.
    """
    validation = plan.get("validation") or {}
    reasons = []
    if validation.get("result") != "PASS":
        reasons.append({
            "code": BLOCK_RESULT,
            "message": (
                f"validation.result e' {validation.get('result')!r}: la "
                "prontezza investor-ready esige PASS, e un WARNING non e' "
                "un'approvazione piena"),
            "affected_refs": ["financial_plan.validation.result"],
        })
    if validation.get("propagated_status") != "confirmed":
        reasons.append({
            "code": BLOCK_PROPAGATED,
            "message": (
                f"validation.propagated_status e' "
                f"{validation.get('propagated_status')!r}: i numeri non sono "
                "fatti di soli input confermati"),
            "affected_refs": ["financial_plan.validation.propagated_status"],
        })
    unbound = list(registry.get("unbound_required_roles") or [])
    if unbound:
        reasons.append({
            "code": BLOCK_UNBOUND,
            "message": (
                "ruoli RICHIESTI dal profilo attivo e non legati a un input "
                "governato: nessun valore di ripiego esiste"),
            "affected_refs": sorted(unbound),
        })
    coverage = (scenarios or {}).get("coverage") or {}
    if coverage.get("level") == "none":
        refs = list(coverage.get("uncovered_driver_refs") or [])
        reasons.append({
            "code": BLOCK_COVERAGE,
            "message": (
                "copertura di scenario NULLA: Downside e Upside non sono "
                "prodotti e l'esito e' approved_with_conditions, non "
                "un'approvazione piena"),
            "affected_refs": sorted(refs) or [
                "financial_plan.results.scenarios.coverage.level"],
        })
    failed = []
    for rec_id in sorted(recon or {}):
        entry = recon[rec_id] or {}
        if entry.get("severity") == "FAIL" and entry.get("status") == "FAIL":
            failed.append(rec_id)
    if failed:
        reasons.append({
            "code": "reconciliation_failed",
            "message": (
                "riconciliazioni con severita' FAIL e stato FAIL: "
                "un'identita' di modello non chiude"),
            "affected_refs": sorted(failed),
        })
    plan_status = (governance.get("plan") or {}).get("propagated_status")
    if plan_status != "confirmed":
        reasons.append({
            "code": BLOCK_GOVERNANCE,
            "message": (
                f"governance.plan.propagated_status e' {plan_status!r}: lo "
                "stato propagato canonico non e' confermato"),
            "affected_refs": ["financial_plan.governance.plan"
                              ".propagated_status"],
        })
    status = "ready" if not reasons else "not_ready"
    return {"status": status,
            "blocking_reasons": sorted_findings(reasons)}


def project_validation(plan, registry, scenarios, recon, governance):
    validation = copy.deepcopy(plan.get("validation") or {})
    validation["checks"] = sorted_checks(validation.get("checks"))
    validation["errors"] = sorted_findings(validation.get("errors"))
    validation["warnings"] = sorted_findings(validation.get("warnings"))
    validation["investor_readiness"] = investor_readiness(
        plan, registry, scenarios, recon, governance)
    return validation


def build_document(payload, profile):
    """La PROIEZIONE TOTALE. Nessun numero e' derivato qui."""
    plan = check_total_mapping(payload)
    check_run_not_blocked(plan)
    registry = project_driver_registry(plan)
    modules = project_modules(plan, profile)
    results = copy.deepcopy(plan.get("results") or {})
    scenarios = copy.deepcopy(results.get("scenarios") or {})
    coverage = scenarios.get("coverage") or {}
    governance = project_governance(payload, modules, scenarios)
    recon = project_reconciliations(plan)
    validation = project_validation(plan, registry, scenarios, recon,
                                    governance)
    metadata = project_calculation_metadata(plan, coverage)
    return {
        "schema_version": SCHEMA_VERSION,
        "financial_plan": {
            "driver_registry": registry,
            "results": {
                "calendar": results.get("calendar") or {},
                "modules": modules,
                "scenarios": scenarios,
            },
            "reconciliations": recon,
            "validation": validation,
            "calculation_metadata": metadata,
            "governance": governance,
        },
    }


def build_handoff(document, payload_path):
    """`handoff.md` — le omissioni DICHIARATE, NOMINATE una per una."""
    plan = document["financial_plan"]
    checksum = ((plan.get("calculation_metadata") or {}).get(
        "output_checksums") or {}).get("base")
    readiness = (plan.get("validation") or {}).get("investor_readiness") or {}
    lines = [
        "# Handoff — Stage 10 `10_financial-plan`",
        "",
        "Documento canonico prodotto da "
        "`output/build_canonical_output.py` come **candidate**, "
        "mai come canonico: il canonico e' scritto dal Transaction Manager, "
        "al commit dello stage.",
        "",
        f"- `schema_version`: `{document['schema_version']}`",
        f"- `canonical_source_checksum` "
        f"(`calculation_metadata.output_checksums.base`): `{checksum}`",
        f"- prontezza investor-ready: `{readiness.get('status')}`, con "
        f"{len(readiness.get('blocking_reasons') or [])} ragioni di blocco "
        "TIPIZZATE e ATTRIBUITE",
        f"- payload di origine: `{Path(payload_path).name}`",
        "",
        "## Omissioni DICHIARATE della mappatura payload -> canonico",
        "",
        "Nessuna omissione e' silenziosa. Ogni blocco del payload del motore "
        "che non entra nel canonico e' NOMINATO qui, e il costruttore "
        "RIFIUTA (`canonical_payload_unmapped_block`) un payload che porta "
        "un blocco di primo livello che ne' la mappa ne' lo schema conoscono.",
        "",
    ]
    for name, reason in DECLARED_OMISSIONS:
        lines.append(f"- **`{name}`** — {reason}")
    lines.extend([
        "",
        "## Che cosa questo documento NON contiene",
        "",
        "- nessun artefatto derivato: il capitolo `financial-plan.md` e il "
        "workbook `financial-model.xlsx` sono prodotti dai passi "
        "successivi di rendering (`output/render_financial_plan.py`) ed "
        "export (`output/export_financial_model.py`);",
        "- nessuna chiave di Stage 11: `funding_ask`, `instrument`, "
        "`valuation`, `round_size`, `ownership`, `dilution`, `terms` sono "
        "fuori dallo Stage 10;",
        "- nessuna allocazione di `use_of_proceeds`: sono **categorie "
        "eleggibili**, senza importi, e la loro somma non e' un `ask`.",
        "",
    ])
    return "".join(["\n".join(lines), "\n"])


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def load_profile(profile_id):
    path = Path(__file__).resolve().parents[1].joinpath(
        "profiles", f"{profile_id}.json")
    if not path.is_file():
        raise BuilderRefusal(
            CODE_PAYLOAD_INVALID, str(profile_id),
            f"profilo attivo non trovato: {profile_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def run(args):
    payload = read_payload(args.engine_payload)
    plan = payload.get("financial_payload") or {}
    profile_id = (plan.get("driver_registry") or {}).get("profile_id")
    if not profile_id:
        raise BuilderRefusal(
            CODE_PAYLOAD_INVALID, "driver_registry.profile_id",
            "il payload non dichiara il profilo attivo")
    profile = load_profile(profile_id)
    candidate = resolve_candidate(args.project, args.tx)
    document = build_document(payload, profile)
    checksum = ((document["financial_plan"].get("calculation_metadata") or {})
                .get("output_checksums") or {}).get("base")
    target = candidate.joinpath(CANONICAL_NAME)
    previous = None
    if target.is_file():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        previous = (((existing.get("financial_plan") or {}).get(
            "calculation_metadata") or {}).get("output_checksums")
            or {}).get("base")
    regenerated = bool(previous) and previous != checksum
    atomic_write(target, canonical_json(document))
    handoff = candidate.joinpath(HANDOFF_NAME)
    atomic_write(handoff, build_handoff(document, args.engine_payload))
    report = {
        "result": "PASS",
        "builder": BUILDER_NAME,
        "stage": STAGE10,
        "errors": [],
        "warnings": [],
        "written": [target.as_posix(), handoff.as_posix()],
        "canonical_source_checksum": checksum,
        "regenerated": regenerated,
        "previous_canonical_source_checksum": previous,
        "declared_omissions": [name for name, _ in DECLARED_OMISSIONS],
    }
    if regenerated:
        report["warnings"].append({
            "code": "derived_artifact_stale",
            "ref": "calculation_metadata.output_checksums.base",
            "message": (
                f"il documento precedente portava il checksum {previous!r} "
                f"mentre il payload corrente porta {checksum!r}: il documento "
                "e' stato RIGENERATO per intero dal payload, mai LETTO come "
                "ingresso"),
        })
    return report


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(
        prog=BUILDER_NAME, add_help=True,
        description="Costruttore dell'output canonico dello Stage 10 "
                    "(`structured-output.json`).")
    parser.add_argument("--engine-payload", required=True,
                        help="payload intermedio del motore finanziario")
    parser.add_argument("--project", required=True,
                        help="directory del progetto (fuori da projects/ del checkout)")
    parser.add_argument("--tx", required=True,
                        help="identificatore di transazione del candidate")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    try:
        report = run(args)
    except BuilderUsageError as exc:
        print(f"{BUILDER_NAME}: {exc}", file=sys.stderr)
        return 2
    except BuilderRefusal as exc:
        print(json.dumps({
            "result": "FAIL", "builder": BUILDER_NAME, "stage": STAGE10,
            "errors": [{"code": exc.code, "ref": exc.ref,
                        "message": exc.message}],
            "warnings": [], "written": [],
            "canonical_source_checksum": None, "regenerated": False,
        }, indent=2, ensure_ascii=True, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
