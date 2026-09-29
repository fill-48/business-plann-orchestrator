#!/usr/bin/env python3
"""validate_financial_binding — binding layer dello Stage 10.

Primo anello della pipeline finanziaria dello Stage 10 (binding -> motore ->
riconciliazione -> output canonico). E' un validator di pipeline interna: non
entra in `egress_required`, e al confine di egress il Transaction Manager
invoca soltanto `validate_financial_output`.

CHE COSA VERIFICA
-----------------
Il **binding** fra i ruoli del profilo finanziario attivo e i record canonici
`ASS-*` prodotti dagli Stage 4-9. Nessun **calcolo** finanziario vive qui: il
motore e' `validate_financial_engine` e questo modulo non lo anticipa. Il
validator e' **puro e read-only**: non scrive nulla nel progetto, non crea
`10_financial-plan/` e non modifica la configurazione.

Le quattro modalita' di risoluzione, in ordine di precedenza:

    fpi_declared          seed dalle `financial_plan_inputs` (FPI) dello Stage 9
    upstream_field        campo canonico dichiarato + passo di derivazione
    derivation_closure    chiusura transitiva di `derivation.variables`
    derivation esplicita  explicit_declaration, ULTIMA risorsa e ristretta

`source_path` e' verificato in **tutte e quattro**: il path deve risolvere,
nell'artefatto canonico indicato, **esattamente** a `source_ref`. Nessun
binding e' accettato sulla sola compatibilita' di unita'.

SUPERFICIE CLI
--------------
    --project    directory del progetto (canonico, letto in sola lettura)
    --stage      stage validato          (10_financial-plan)
    --phase      egress | impact         (config/enforcement-config.json)
    --candidate  workspace candidate, obbligatorio in fase egress
    --binding-input <path>|-             INPUT DI BINDING del contratto

`--binding-input` e' un argomento proprio di questo validator (non del
framework): riceve, in JSON, l'**input di binding costruito per il contratto
in esecuzione**. Formato accettato — oggetto JSON con:

    driver_bindings[]        OBBLIGATORIO — le righe di binding
    profile_id               profilo attivo (default: financial_config)
    financial_config         configurazione finanziaria proposta
    consumed_by_engine[]     driver letti dal motore (`input_kind`)
    canonical_records[]      record canonici DICHIARATI dall'input
    shared_canonical_record  singolo record canonico dichiarato
    canonical_after_update   record canonico DOPO un update legittimo
    profile_role_measure_kind  override dichiarato di `role_measure_kind`
    cogs_chain               catena del margine dichiarata
    edge_cases               casi limite della copertura COGS, FAIL-CLOSED

Quando `--binding-input` non e' passato, l'input e' cercato in
`<candidate>/binding-input.json`. La sua assenza e' un ERRORE D'USO (exit 2),
mai un FAIL di contenuto mascherato.

EXIT CODE — semantica ESATTA di `_framework.py`, invariata
-----------------------------------------------------------
    0   nessun errore                     binding accettato
    1   candidate non valido              almeno un codice bloccante di binding
    2   errore d'uso (EXIT_USAGE)         invocazione o input non utilizzabili
    3   stato canonico non valido         canonico illeggibile o incoerente

FASE
----
La validazione del binding vive in **`egress`**. La fase `impact` e'
dichiarata in `enforcement-config.json` e accettata; poiche' il framework non
ammette `--candidate` in `impact`, l'input di binding va allora passato
esplicitamente con `--binding-input`. Il modulo non simula una fase: la fase
NON e' scelta dal validator, e' quella con cui viene invocato, e il report la
riporta cosi' che un input dichiarato `egress` non possa essere eseguito in
silenzio come `impact`.

IDENTIFICATORI DI RICONCILIAZIONE
---------------------------------
`REC-12` e `REC-14` sono identificatori di riconciliazione ESISTENTI del
piano finanziario, non invenzioni di tassonomia. Sono esposti come
`check_id` dei `checks[]` e, quando la riconciliazione e' rotta, anche come
`code` degli `errors[]`. Ogni riconciliazione e' riportata **sempre**, anche
quando passa: `checks[]` porta quindi una voce per driver, con
`NOT_APPLICABLE` dove la riconciliazione e' fuori ambito per `measure_kind`.

DRIVER INFORMATIONAL CONSUMATO
------------------------------
Un driver con `input_kind` informational letto dal motore produce il codice
`driver_informational_consumed`, esito FAIL (contratto `T-FIN-INPUT-KIND`).
Il nome alternativo `driver_input_kind_consumed` NON e' usato.
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

import _framework as fw

VALIDATOR_NAME = "validate_financial_binding"

STAGE10 = "10_financial-plan"

#: Fasi in cui il validator e' dichiarato da `config/enforcement-config.json`
#: (voce `validate_financial_binding`).
SUPPORTED_PHASES = ("egress", "impact")

BINDING_INPUT_DEFAULT = "binding-input.json"

# --------------------------------------------------------------------------
# Costanti STRUTTURALI (nel codice solo costanti strutturali, mai valori
# economici).
# --------------------------------------------------------------------------

#: Campi OBBLIGATORI di una riga di binding.
REQUIRED_BINDING_FIELDS = (
    "driver_id", "role", "driver_class", "producer_stage", "source_ref",
    "source_path", "source_record_hash", "cardinality", "unit", "currency",
    "measure_kind", "frequency", "conversion_policy", "timing_rule",
    "start_period", "end_period", "scenario_polarity", "status",
    "source_priority", "binding_method", "double_count_risk", "input_kind",
)

BINDING_METHODS = ("fpi_declared", "upstream_field", "derivation_closure",
                   "explicit_declaration")

MEASURE_KINDS = ("flow", "stock", "rate", "per_unit")

FREQUENCIES = ("one_off", "monthly", "quarterly", "annual", "per_unit")

CONVERSION_POLICIES = ("allocate", "carry_level", "compound",
                       "preserve_per_unit")

#: Regole di ripartizione, ammesse SOLO per `measure_kind: flow`.
FLOW_TIMING_RULES = ("one_off", "uniform", "front_loaded", "back_loaded",
                     "milestone_start", "milestone_end", "custom_schedule",
                     "ramp", "step", "seasonal", "formula")
#: Regole di livello, ammesse SOLO per `measure_kind: stock`.
STOCK_TIMING_RULES = ("constant", "step_level", "from_schedule")
#: `rate` e `per_unit` non si ripartiscono e non si portano a livello.
NOT_APPLICABLE_RULE = "NOT_APPLICABLE"

#: Politica di conversione ATTESA per natura della misura. Il profilo
#: dichiara `role_measure_kind`; la politica non e' dedotta dal nome.
POLICY_BY_MEASURE_KIND = {
    "flow": "allocate",
    "stock": "carry_level",
    "rate": "compound",
    "per_unit": "preserve_per_unit",
}

#: Tolleranza `ratio` di `REC-12`. Soglia di CALCOLO.
RATIO_TOLERANCE = 1e-6

#: La STESSA tolleranza nella forma SERIALIZZATA che lo schema del report
#: esige per `checks[].tolerance` (`{"type": "string", "minLength": 1}`).
#: Non e' una seconda soglia: e' la rappresentazione di `RATIO_TOLERANCE` nel
#: report. Nessun confronto aritmetico la usa.
RATIO_TOLERANCE_CHECK = "ratio 1e-6"

#: Classi di evidenza della skill, con i nomi esatti di
#: `methodology/evidence-framework.md`.
STRONG_EVIDENCE = ("verified_fact", "internal_evidence", "external_source")
WEAK_EVIDENCE = ("founder_assumption", "model_estimate")
MISSING_EVIDENCE = "missing_information"

#: Ordine di propagazione: lo stato di un derivato e' il MINIMO.
STATUS_ORDER = ("unresolved", "placeholder", "inferred", "confirmed")

#: Tassonomia dei codici bloccanti del binding. L'elenco e' CHIUSO: nessun
#: codice e' inventato altrove. `driver_informational_consumed` copre il
#: consumo di un driver informational da parte del motore.
CODE_REF_UNRESOLVED = "driver_ref_unresolved"
CODE_ROLE_UNBOUND = "driver_role_unbound"
CODE_SOURCE_PATH = "driver_source_path_unverifiable"
CODE_EXPLICIT_UNJUSTIFIED = "driver_explicit_declaration_unjustified"
CODE_DUPLICATE = "driver_duplicate_binding"
CODE_AMBIGUOUS = "driver_ref_ambiguous"
CODE_UNIT_MISMATCH = "driver_unit_mismatch"
CODE_UNIT_ABSENT = "driver_unit_absent"
CODE_CURRENCY_ABSENT = "driver_currency_absent"
CODE_FREQUENCY = "driver_frequency_undeclared"
CODE_MEASURE = "driver_measure_undeclared"
CODE_CONVERSION_POLICY = "driver_conversion_policy_undeclared"
CODE_PERIOD = "driver_period_undeclared"
CODE_STATUS_UNMAPPABLE = "driver_status_unmappable"
CODE_SOURCE_STALE = "driver_source_stale"
CODE_COGS_INCOMPLETE = "cogs_coverage_incomplete"
CODE_COGS_MARGIN_REF = "cogs_margin_reference_missing"
CODE_COGS_NOT_DERIVED = "cogs_margin_not_derived"
CODE_COGS_PRICE_ABSENT = "cogs_margin_price_absent"
CODE_SOURCE_CONFLICT = "source_conflict_unresolved"
CODE_UNRESOLVED_REQUIRED = "unresolved_required_input"
CODE_PLACEHOLDER_OPTIONAL = "placeholder_optional_input"
CODE_REF_ORPHANED = "driver_ref_orphaned"
CODE_UNIT_NON_CANONICAL = "driver_unit_non_canonical"
#: Driver informational consumato dal motore. Esito FAIL.
CODE_INFORMATIONAL_CONSUMED = "driver_informational_consumed"
#: Copertura COGS: un'esclusione deliberata e' registrata, mai silenziosa.
CHECK_COGS_EXCLUSION = "cogs_exclusion_declared"

#: Identificatori di riconciliazione ESISTENTI.
REC_FLOW_QUOTA = "REC-12"
REC_STOCK_LEVEL = "REC-14"

#: Percorso normativo di `upstream_field` per il costo unitario del
#: personale: il ruolo si risolve per `upstream_field` + derivazione, MAI per
#: `explicit_declaration`.
PAYROLL_ROLE = "payroll_unit_cost"
PAYROLL_UPSTREAM_ROOT = "team_governance"
PAYROLL_UPSTREAM_LIST = "hiring_plan"
PAYROLL_UPSTREAM_FIELD = "cost_driver_ref"
PAYROLL_DERIVATION_VARIABLE = "cost_per_fte_year"

#: Modalita' 1 (`fpi_declared`) — prefisso del `source_path` del seed FPI.
FPI_PATH_PREFIX = "milestone_plan.financial_plan_inputs"

_PATH_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")

_MISSING = object()


# --------------------------------------------------------------------------
# CAS esistente — riuso, non riscrittura
# --------------------------------------------------------------------------


def load_record_fingerprint():
    """`record_fingerprint` del Transaction Manager, importato in SOLA LETTURA.

    Riusa il CAS gia' esistente (`record_fingerprint` in
    `transaction/transaction_manager.py`) invece di introdurre una convenzione
    di fingerprint nuova. L'import non modifica il Transaction Manager.
    """
    path = fw.SKILL_ROOT / "transaction" / "transaction_manager.py"
    if not path.is_file():
        raise fw.ValidatorUsageError(
            f"transaction_manager assente: {path}; il CAS esistente non e' "
            "riusabile e source_record_hash non e' verificabile")
    spec = importlib.util.spec_from_file_location("transaction_manager", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("transaction_manager", module)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise fw.ValidatorUsageError(
            f"transaction_manager non importabile in sola lettura: {exc}")
    fingerprint = getattr(module, "record_fingerprint", None)
    if not callable(fingerprint):
        raise fw.ValidatorUsageError(
            "transaction_manager senza record_fingerprint: il CAS esistente "
            "non e' riusabile")
    return fingerprint


# --------------------------------------------------------------------------
# Input di binding e artefatti canonici
# --------------------------------------------------------------------------


def read_binding_input(args, binding_input):
    """Legge l'input di binding del contratto in esecuzione.

    Un input illeggibile, malformato o assente e' un ERRORE D'USO (exit 2):
    non viene mascherato da un FAIL di contenuto, e un FAIL di contenuto non
    viene mascherato da un errore d'uso.
    """
    if binding_input == "-":
        text = sys.stdin.read()
        label = "<stdin>"
    else:
        if binding_input:
            path = Path(binding_input)
        elif args.candidate is not None:
            path = args.candidate / BINDING_INPUT_DEFAULT
        else:
            raise fw.ValidatorUsageError(
                "--binding-input obbligatorio: senza --candidate non esiste "
                f"un {BINDING_INPUT_DEFAULT} da cui leggere l'input di binding")
        if not path.is_file():
            raise fw.ValidatorUsageError(
                f"input di binding assente: {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise fw.ValidatorUsageError(
                f"input di binding illeggibile: {path}: {exc}")
        label = str(path)
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise fw.ValidatorUsageError(
            f"input di binding malformato: {label}: {exc}")
    if not isinstance(doc, dict):
        raise fw.ValidatorUsageError(
            f"input di binding non e' un oggetto JSON: {label}")
    rows = doc.get("driver_bindings")
    if not isinstance(rows, list) or not rows:
        raise fw.ValidatorUsageError(
            f"input di binding senza driver_bindings[] non vuoto: {label}")
    doc["_source_label"] = label
    return doc


def canonical_documents(project):
    """Documenti canonici del progetto, indicizzati per chiave di primo livello.

    Sono gli artefatti contro cui `source_path` e' verificato. La lettura e'
    in SOLA LETTURA e nessuna directory di stage e' creata: se
    `10_financial-plan/` non esiste, non viene creata.
    """
    documents = {}
    if not project.is_dir():
        return documents
    for entry in sorted(project.iterdir()):
        if not entry.is_dir():
            continue
        path = entry / "structured-output.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        rel = f"{entry.name}/structured-output.json"
        for key, value in data.items():
            documents.setdefault(key, {"artifact": rel, "value": value})
    return documents


def resolve_path(documents, source_path):
    """Risolve un `source_path` negli artefatti canonici del progetto.

    Restituisce `(valore, artefatto)` oppure `(_MISSING, artefatto|None)`. Il
    path e' letto alla lettera: `chiave.sotto_chiave[indice]`. Non esiste
    ricerca euristica — un path che non esiste NON viene cercato altrove.
    """
    if not isinstance(source_path, str) or not source_path:
        return _MISSING, None
    tokens = []
    position = 0
    for match in _PATH_TOKEN.finditer(source_path):
        if match.start() != position and source_path[position:match.start()] != ".":
            return _MISSING, None
        position = match.end()
        name, index = match.group(1), match.group(2)
        tokens.append(name if name is not None else int(index))
    if position != len(source_path) or not tokens:
        return _MISSING, None
    root = tokens[0]
    if not isinstance(root, str) or root not in documents:
        return _MISSING, None
    artifact = documents[root]["artifact"]
    value = documents[root]["value"]
    for token in tokens[1:]:
        if isinstance(token, int):
            if not isinstance(value, list) or token >= len(value):
                return _MISSING, artifact
            value = value[token]
        else:
            if not isinstance(value, dict) or token not in value:
                return _MISSING, artifact
            value = value[token]
    return value, artifact


# --------------------------------------------------------------------------
# Mappatura di stato TOTALE e fail-closed
# --------------------------------------------------------------------------


def map_status(record):
    """Funzione TOTALE `status(record)`, regole R1-R8 applicate in ordine.

    La prima regola che matcha decide e NON esiste un ramo «altrimenti
    permissivo»: `R8` non e' un default, e' il gate fail-closed. Restituisce
    `(stato|None, regola)`; `None` significa `driver_status_unmappable`.
    """
    if not isinstance(record, dict):
        return None, "R8"
    validation = record.get("validation_status")
    if validation == "rejected":
        return "unresolved", "R1"
    if validation == "needs_info":
        return "unresolved", "R2"
    if record.get("value") is None:
        return "unresolved", "R3"
    if "evidence_classification" not in record or \
            record.get("evidence_classification") is None:
        return "placeholder", "R4"
    evidence = record.get("evidence_classification")
    if evidence == MISSING_EVIDENCE:
        return "placeholder", "R5"
    if validation == "validated":
        if evidence in STRONG_EVIDENCE:
            return "confirmed", "R6"
        if evidence in WEAK_EVIDENCE:
            return "inferred", "R6"
    if validation == "unvalidated":
        if evidence in WEAK_EVIDENCE or evidence in STRONG_EVIDENCE:
            return "inferred", "R7"
    return None, "R8"


def propagated_status(ref, overlay, seen=None):
    """Stato di un record, propagato sui `derivation.variables`.

    Lo stato di un valore derivato e' il **minimo** degli stati dei suoi input,
    nell'ordine `unresolved < placeholder < inferred < confirmed`. Nessuna
    formula, default o aggregazione promuove uno stato.
    """
    seen = set() if seen is None else seen
    record = overlay.get(ref)
    status, rule = map_status(record)
    if status is None or ref in seen:
        return status, rule
    seen = seen | {ref}
    variables = (record.get("derivation") or {}).get("variables") or {}
    if not isinstance(variables, dict):
        return status, rule
    worst = STATUS_ORDER.index(status)
    for upstream in variables.values():
        if not isinstance(upstream, str) or upstream not in overlay:
            continue
        child, _ = propagated_status(upstream, overlay, seen)
        if child is None:
            return None, "R8"
        worst = min(worst, STATUS_ORDER.index(child))
    return STATUS_ORDER[worst], rule


# --------------------------------------------------------------------------
# Unita' — classe di unita' STRUTTURALE, mai un valore economico
# --------------------------------------------------------------------------


def unit_class(unit):
    """Classe strutturale dell'unita' dichiarata, o `None` se non canonica."""
    if not isinstance(unit, str) or not unit:
        return None
    if unit == "ratio":
        return "rate"
    if "/" in unit:
        return "per_unit"
    if unit in ("count", "FTE"):
        return "level"
    if unit.isalpha() and unit.isupper():
        return "extensive"
    return None


def is_monetary(unit):
    return isinstance(unit, str) and unit.upper().startswith("EUR")


# --------------------------------------------------------------------------
# Algoritmo di `cogs_coverage_incomplete`, fail-closed
# --------------------------------------------------------------------------


def evaluate_cogs_coverage(business_model, overlay, pricing_ref, covered,
                           exclusions, margin_override=None):
    """I sei passi della copertura COGS. Restituisce `(codice|None, dettaglio)`.

    Nessun passo produce «regola non applicabile»: un margine irraggiungibile
    e' un difetto di input, non un permesso a saltare il controllo. E' la
    differenza fra `T-FIN-COGS-COVERAGE` verde *per la ragione giusta* e verde
    *per la ragione sbagliata*.
    """
    detail = {"pricing_ref": pricing_ref, "covered": sorted(covered),
              "declared_exclusions": sorted(exclusions)}

    # 1. risolvi business_model.contribution_margin_ref
    margin_ref = None
    if isinstance(business_model, dict):
        margin_ref = business_model.get("contribution_margin_ref")
    detail["contribution_margin_ref"] = margin_ref
    if not isinstance(margin_ref, str) or not margin_ref:
        return CODE_COGS_MARGIN_REF, detail

    # 2. risolvi il record referenziato; deve essere derived con variables
    margin = margin_override if margin_override is not None \
        else overlay.get(margin_ref)
    if not isinstance(margin, dict):
        return CODE_COGS_MARGIN_REF, detail
    variables = (margin.get("derivation") or {}).get("variables")
    if margin.get("kind") != "derived" or not isinstance(variables, dict) \
            or not variables:
        detail["margin_kind"] = margin.get("kind")
        return CODE_COGS_NOT_DERIVED, detail

    # 3. margin_vars
    margin_vars = [ref for ref in variables.values() if isinstance(ref, str)]
    detail["margin_variables"] = sorted(margin_vars)

    # 4. rimuovi il prezzo — sottrazione, non deduzione
    if pricing_ref not in margin_vars:
        return CODE_COGS_PRICE_ABSENT, detail
    cost_vars = [ref for ref in margin_vars if ref != pricing_ref]
    detail["cost_variables"] = sorted(cost_vars)

    # 5-6. confronto e copertura
    uncovered = sorted(set(cost_vars) - set(covered) - set(exclusions))
    detail["uncovered"] = uncovered
    if uncovered:
        return CODE_COGS_INCOMPLETE, detail
    return None, detail


# --------------------------------------------------------------------------
# Verifiche di riga
# --------------------------------------------------------------------------


def check_row_shape(row, index, report):
    """La riga di binding porta TUTTE le chiavi obbligatorie.

    Una chiave assente NON e' interpretata: e' la stessa violazione che il
    campo dichiarerebbe se fosse presente e vuoto.
    """
    missing = [field for field in REQUIRED_BINDING_FIELDS if field not in row]
    if missing:
        report.add_error(
            CODE_MEASURE if "measure_kind" in missing else CODE_SOURCE_PATH,
            ref=row.get("driver_id") or f"driver_bindings[{index}]",
            message=(f"riga di binding incompleta: chiavi obbligatorie assenti: "
                     f"{', '.join(missing)}"),
            expected="tutte le chiavi obbligatorie della riga di binding",
            actual=f"assenti: {', '.join(missing)}")
    return not missing


def check_source_path(row, documents, report):
    """`source_path` risolve ESATTAMENTE a `source_ref`.

    Tre esiti, e nessun quarto: il path non esiste; il path risolve a un
    `ASS-*` diverso; il path risolve esattamente. Nessun binding e' accettato
    sulla sola compatibilita' di unita'.
    """
    driver_id = row.get("driver_id")
    source_ref = row.get("source_ref")
    source_path = row.get("source_path")
    method = row.get("binding_method")
    if method not in BINDING_METHODS:
        report.add_error(
            CODE_SOURCE_PATH, ref=driver_id,
            message=(f"binding_method non riconosciuto: {method!r}; la "
                     "provenienza non e' verificabile in nessuna delle quattro "
                     "modalita' di binding ammesse"),
            expected=f"binding_method in {BINDING_METHODS}",
            actual=repr(method))
        return False
    if method == "fpi_declared" and not \
            (isinstance(source_path, str)
             and source_path.startswith(FPI_PATH_PREFIX)):
        report.add_error(
            CODE_SOURCE_PATH, ref=driver_id,
            message=(f"binding_method fpi_declared con source_path fuori dalla "
                     f"FPI: {source_path!r}"),
            expected=f"{FPI_PATH_PREFIX}.<chiave>", actual=repr(source_path))
        return False
    resolved, artifact = resolve_path(documents, source_path)
    if resolved is _MISSING:
        report.add_error(
            CODE_SOURCE_PATH, ref=driver_id,
            message=(f"source_path non risolve in alcun artefatto canonico di "
                     f"progetto: {source_path!r}"),
            expected=f"un path che risolve a {source_ref}",
            actual=(f"non risolto in {artifact}" if artifact
                    else "radice non canonica"))
        return False
    if resolved != source_ref:
        report.add_error(
            CODE_SOURCE_PATH, ref=driver_id,
            message=(f"source_path {source_path!r} risolve a {resolved!r} in "
                     f"{artifact}, diverso da source_ref {source_ref!r}: "
                     "unita' compatibile, semantica diversa"),
            expected=source_ref, actual=resolved)
        return False
    return True


def check_explicit_declaration(row, role_has_canonical_path, report):
    """Modalita' 4 — `explicit_declaration` ristretta, cumulativa."""
    if row.get("binding_method") != "explicit_declaration":
        return True
    driver_id = row.get("driver_id")
    missing = []
    if not row.get("decision_ref"):
        missing.append("decision_ref")
    if not row.get("exhaustive_search"):
        missing.append("exhaustive_search")
    if not row.get("rationale"):
        missing.append("rationale")
    if missing:
        report.add_error(
            CODE_EXPLICIT_UNJUSTIFIED, ref=driver_id,
            message=(f"explicit_declaration priva di: {', '.join(missing)}; "
                     "la modalita' li richiede CUMULATIVAMENTE"),
            expected="decision_ref + exhaustive_search + rationale",
            actual=f"assenti: {', '.join(missing)}")
        return False
    if role_has_canonical_path:
        report.add_error(
            CODE_EXPLICIT_UNJUSTIFIED, ref=driver_id,
            message=(f"explicit_declaration sul ruolo {row.get('role')!r} per "
                     "cui ESISTE un percorso canonico: e' ammessa solo quando "
                     "nessun percorso canonico esiste, e non puo' "
                     "sostituire in silenzio un ruolo gia' coperto"),
            expected="nessun percorso canonico per il ruolo",
            actual="percorso canonico disponibile")
        return False
    return True


def check_units(row, profile, report):
    """Unita' presente, canonica e compatibile con il ruolo."""
    driver_id = row.get("driver_id")
    role = row.get("role")
    unit = row.get("unit")
    ok = True
    if not isinstance(unit, str) or not unit:
        report.add_error(
            CODE_UNIT_ABSENT, ref=driver_id,
            message=(f"il record legato a {role!r} non porta unit: il binding "
                     "non e' ammesso e l'unita' non e' dedotta dal nome"),
            expected="unit copiata dal record canonico", actual=repr(unit))
        return False
    expected_class = (profile.get("role_unit_class") or {}).get(role)
    observed_class = unit_class(unit)
    if expected_class == "rate" and unit != "ratio":
        report.add_error(
            CODE_UNIT_NON_CANONICAL, ref=driver_id,
            message=(f"unita' non canonica su ruolo ratio {role!r}: {unit!r}; "
                     "un ratio espresso in percentuale trattato come frazione "
                     "e' un errore di scala, non una formattazione"),
            expected="ratio", actual=unit)
        ok = False
    if expected_class is not None and observed_class != expected_class:
        report.add_error(
            CODE_UNIT_MISMATCH, ref=driver_id,
            message=(f"unita' {unit!r} (classe {observed_class!r}) "
                     f"incompatibile con la classe del ruolo {role!r}"),
            expected=expected_class, actual=observed_class)
        ok = False
    if is_monetary(unit) and not row.get("currency"):
        report.add_error(
            CODE_CURRENCY_ABSENT, ref=driver_id,
            message=(f"ruolo monetario {role!r} senza currency: la valuta e' "
                     "copiata dal record, mai dedotta"),
            expected="currency ISO-4217", actual=repr(row.get("currency")))
        ok = False
    return ok


def check_declarations(row, profile, role_measure_kind, report):
    """`frequency`, `measure_kind`, `conversion_policy`,
    finestra di periodo: DICHIARATE, mai dedotte dal nome o dall'unita'."""
    driver_id = row.get("driver_id")
    role = row.get("role")
    ok = True
    if row.get("frequency") not in FREQUENCIES:
        report.add_error(
            CODE_FREQUENCY, ref=driver_id,
            message=(f"frequency non dichiarata: {row.get('frequency')!r}; "
                     "dedurla dal nome della variabile e' vietato"),
            expected=f"una di {FREQUENCIES}", actual=repr(row.get("frequency")))
        ok = False
    measure = row.get("measure_kind")
    expected_measure = role_measure_kind.get(role)
    if measure not in MEASURE_KINDS:
        report.add_error(
            CODE_MEASURE, ref=driver_id,
            message=(f"measure_kind non dichiarato: {measure!r}; dedurlo dal "
                     "nome o dall'unita' e' vietato"),
            expected=f"una di {MEASURE_KINDS}", actual=repr(measure))
        ok = False
    elif expected_measure is not None and measure != expected_measure:
        report.add_error(
            CODE_MEASURE, ref=driver_id,
            message=(f"measure_kind {measure!r} incoerente con "
                     f"role_measure_kind del profilo per {role!r}"),
            expected=expected_measure, actual=measure)
        ok = False
    policy = row.get("conversion_policy")
    if policy not in CONVERSION_POLICIES:
        report.add_error(
            CODE_CONVERSION_POLICY, ref=driver_id,
            message=(f"conversion_policy non dichiarata: {policy!r}"),
            expected=f"una di {CONVERSION_POLICIES}", actual=repr(policy))
        ok = False
    elif measure in POLICY_BY_MEASURE_KIND and \
            policy != POLICY_BY_MEASURE_KIND[measure]:
        report.add_error(
            CODE_CONVERSION_POLICY, ref=driver_id,
            message=(f"conversion_policy {policy!r} non derivabile dalla "
                     f"classe di unita' di un driver {measure!r}: la politica "
                     "e' fissata dalla natura della misura"),
            expected=POLICY_BY_MEASURE_KIND[measure], actual=policy)
        ok = False
    needs_window = role == "headcount" or measure == "stock"
    if needs_window and (row.get("start_period") is None or
                         row.get("end_period") is None):
        report.add_error(
            CODE_PERIOD, ref=driver_id,
            message=(f"driver {role!r} senza finestra dichiarata: "
                     f"start_period={row.get('start_period')!r}, "
                     f"end_period={row.get('end_period')!r}; nessuna finestra "
                     "e' dedotta"),
            expected="start_period ed end_period dichiarati",
            actual=f"{row.get('start_period')!r}/{row.get('end_period')!r}")
        ok = False
    return ok


# --------------------------------------------------------------------------
# Riconciliazioni REC-12 e REC-14, riportate SEMPRE
# --------------------------------------------------------------------------


def reconcile_timing(row, report):
    """`REC-12` (solo `flow`) e `REC-14` (solo `stock`), per driver.

    `REC-12` e' VINCOLATA a `flow`: applicarla a `stock`, `rate` o `per_unit`
    e' un errore di APPLICAZIONE della regola, non un piano invalido. La voce
    fuori ambito e' quindi registrata `NOT_APPLICABLE` e non produce FAIL —
    ed e' registrata, perche' un controllo che non compare nel report equivale
    a un controllo non eseguito.
    """
    driver_id = row.get("driver_id")
    measure = row.get("measure_kind")
    rule = row.get("timing_rule")
    refs = [driver_id] if driver_id else None

    if measure not in MEASURE_KINDS:
        report.add_check(REC_FLOW_QUOTA, "NOT_APPLICABLE", affected_refs=refs,
                         message="measure_kind non dichiarato: la "
                                 "riconciliazione di ripartizione non e' "
                                 "applicabile finche' la natura non e' nota")
        report.add_check(REC_STOCK_LEVEL, "NOT_APPLICABLE", affected_refs=refs,
                         message="measure_kind non dichiarato")
        return

    # ---- REC-12 — Sigma quote di ogni timing_rule = 1, SOLO per flow -------
    if measure != "flow":
        report.add_check(
            REC_FLOW_QUOTA, "NOT_APPLICABLE", affected_refs=refs,
            message=(f"measure_kind {measure!r} e' ESENTE da REC-12: "
                     "nessuna regola di livello e nessun tasso somma a 1"))
    else:
        violation = None
        observed = None
        if rule in STOCK_TIMING_RULES:
            violation = (f"timing_rule {rule!r} e' una regola di LIVELLO "
                         "applicata a un flusso: le quote non sommano piu' a 1")
        elif rule == NOT_APPLICABLE_RULE or rule not in FLOW_TIMING_RULES:
            violation = (f"timing_rule {rule!r} non e' una regola di "
                         "ripartizione ammessa per un flusso")
        elif rule == "custom_schedule":
            schedule = row.get("custom_schedule")
            if not isinstance(schedule, dict) or not schedule:
                violation = "custom_schedule assente o vuota"
            else:
                try:
                    observed = round(sum(float(v) for v in schedule.values()), 10)
                except (TypeError, ValueError):
                    violation = "custom_schedule con quote non numeriche"
                else:
                    if abs(observed - 1.0) > RATIO_TOLERANCE:
                        violation = (f"somma delle quote {observed!r}: la "
                                     "schedule perde massa")
        if violation:
            report.add_check(
                REC_FLOW_QUOTA, "FAIL", affected_refs=refs, expected=1.0,
                actual=observed, tolerance=RATIO_TOLERANCE_CHECK,
                residual=(None if observed is None else round(observed - 1.0, 10)),
                message=f"REC-12 violata su {driver_id}: {violation}")
            report.add_error(
                REC_FLOW_QUOTA, ref=driver_id,
                message=(f"REC-12 violata: Sigma quote di ogni "
                         f"timing_rule = 1 per measure_kind flow — {violation}"),
                expected=1.0, actual=observed)
        else:
            report.add_check(
                REC_FLOW_QUOTA, "PASS", affected_refs=refs, expected=1.0,
                actual=observed, tolerance=RATIO_TOLERANCE_CHECK,
                message=f"REC-12 soddisfatta da {driver_id} ({rule})")

    # ---- REC-14 — livello per periodo = serie dichiarata, SOLO per stock ---
    if measure != "stock":
        report.add_check(
            REC_STOCK_LEVEL, "NOT_APPLICABLE", affected_refs=refs,
            message=(f"measure_kind {measure!r} non e' uno stock: REC-14 "
                     "e' fuori ambito"))
        return
    violation = None
    if rule in FLOW_TIMING_RULES:
        violation = (f"timing_rule {rule!r} RIPARTISCE uno stock come un "
                     "flusso: il livello di ogni periodo non coincide piu' "
                     "con la serie dichiarata")
    elif rule not in STOCK_TIMING_RULES:
        violation = (f"timing_rule {rule!r} non e' una regola di livello "
                     "ammessa per uno stock")
    elif rule in ("step_level", "from_schedule"):
        schedule = row.get("level_schedule")
        if not isinstance(schedule, dict) or not schedule:
            violation = (f"timing_rule {rule!r} senza level_schedule: la "
                         "variazione fra periodi non e' spiegata da alcun "
                         "evento dichiarato")
        else:
            try:
                keys = [int(k) for k in schedule]
            except (TypeError, ValueError):
                violation = "level_schedule con indici di periodo non interi"
            else:
                if keys != sorted(keys):
                    violation = "level_schedule con indici non ordinati"
    if violation:
        report.add_check(
            REC_STOCK_LEVEL, "FAIL", affected_refs=refs,
            expected="livello per periodo = serie dichiarata",
            actual=rule, message=f"REC-14 violata su {driver_id}: {violation}")
        report.add_error(
            REC_STOCK_LEVEL, ref=driver_id,
            message=(f"REC-14 violata: {violation}"),
            expected="livello per periodo = serie dichiarata, ogni variazione "
                     "spiegata da un evento dichiarato",
            actual=rule)
    else:
        report.add_check(
            REC_STOCK_LEVEL, "PASS", affected_refs=refs,
            expected="livello per periodo = serie dichiarata", actual=rule,
            message=f"REC-14 soddisfatta da {driver_id} ({rule})")


# --------------------------------------------------------------------------
# Gerarchia delle fonti e conflitti
# --------------------------------------------------------------------------


def check_cardinality_and_conflicts(rows, report):
    """Duplicati, ambiguita' e conflitti di fonte.

    Un conflitto a priorita' PARI non si risolve scegliendo il piu' recente,
    il maggiore, il minore o il piu' favorevole al piano: si BLOCCA e richiede
    un `DEC-*` esplicito.
    """
    by_role = {}
    by_ref = {}
    for row in rows:
        by_role.setdefault(row.get("role"), []).append(row)
        by_ref.setdefault(row.get("source_ref"), []).append(row)

    for role, group in sorted(by_role.items(), key=lambda item: str(item[0])):
        if len(group) < 2:
            continue
        cardinalities = {row.get("cardinality") for row in group}
        ids = [row.get("driver_id") for row in group]
        if "one" in cardinalities:
            report.add_error(
                CODE_DUPLICATE, ref=role,
                message=(f"ruolo {role!r} a cardinalita' one con "
                         f"{len(group)} binding: {', '.join(map(str, ids))}"),
                expected="un solo binding", actual=len(group))
        else:
            seen = {}
            for row in group:
                ref = row.get("source_ref")
                if ref in seen:
                    report.add_error(
                        CODE_DUPLICATE, ref=ref,
                        message=(f"lo stesso source_ref {ref!r} e' legato due "
                                 f"volte al ruolo many {role!r} "
                                 f"({seen[ref]} e {row.get('driver_id')}): "
                                 "cardinalita' many non significa duplicati "
                                 "ammessi"),
                        expected="riferimenti distinti", actual=ref)
                else:
                    seen[ref] = row.get("driver_id")
        # Conflitto di fonte fra CANDIDATI dello stesso ruolo. Vale
        # SOLO dove i candidati competono per lo stesso posto, cioe' sui ruoli
        # a cardinalita' `one`: su un ruolo `many` due riferimenti DISTINTI
        # non sono candidati rivali, sono due binding entrambi dovuti (i due
        # headcount_driver_refs della FPI ne sono il caso tipico).
        if "one" not in cardinalities:
            continue
        priorities = {}
        for row in group:
            priorities.setdefault(row.get("source_priority"), []).append(row)
        top = max(priorities) if priorities else None
        contenders = priorities.get(top) or []
        distinct_refs = {row.get("source_ref") for row in contenders}
        if len(distinct_refs) > 1 and \
                not any(row.get("decision_ref") for row in contenders):
            report.add_error(
                CODE_SOURCE_CONFLICT, ref=role,
                message=(f"due o piu' candidati per il ruolo {role!r} a "
                         f"priorita' PARI ({top}) e nessun DEC-* che risolva: "
                         f"{', '.join(sorted(map(str, distinct_refs)))}; la "
                         "scelta implicita e' vietata"),
                expected="priorita' distinte oppure un decision_ref",
                actual=f"priorita' {top} su {len(distinct_refs)} candidati")

    for ref, group in sorted(by_ref.items(), key=lambda item: str(item[0])):
        classes = {row.get("driver_class") for row in group}
        roles = sorted({str(row.get("role")) for row in group})
        if len(classes) > 1:
            report.add_error(
                CODE_AMBIGUOUS, ref=ref,
                message=(f"lo stesso riferimento canonico {ref!r} serve i "
                         f"ruoli {', '.join(roles)} di classi diverse "
                         f"({', '.join(sorted(map(str, classes)))}): il riuso "
                         "con semantica diversa e' ambiguita', non economia"),
                expected="un riferimento per una sola semantica di ruolo",
                actual=", ".join(roles))


# --------------------------------------------------------------------------
# Check principale
# --------------------------------------------------------------------------


def resolve_payroll_upstream(documents, overlay):
    """Modalita' 2 (`upstream_field`) — costo unitario del personale.

    `team_governance.hiring_plan[i].cost_driver_ref` -> record derivato ->
    `derivation.variables.cost_per_fte_year` -> il driver. In assenza del
    percorso il ruolo e' `driver_role_unbound`: nessuna `explicit_declaration`
    e' ammessa per questo ruolo.
    """
    entry = documents.get(PAYROLL_UPSTREAM_ROOT)
    if not entry or not isinstance(entry["value"], dict):
        return None
    plan = entry["value"].get(PAYROLL_UPSTREAM_LIST)
    if not isinstance(plan, list):
        return None
    for index, item in enumerate(plan):
        if not isinstance(item, dict):
            continue
        ref = item.get(PAYROLL_UPSTREAM_FIELD)
        record = overlay.get(ref) if isinstance(ref, str) else None
        if not isinstance(record, dict):
            continue
        variables = (record.get("derivation") or {}).get("variables") or {}
        target = variables.get(PAYROLL_DERIVATION_VARIABLE) \
            if isinstance(variables, dict) else None
        if isinstance(target, str) and target in overlay:
            return {
                "source_ref": target,
                "via": ref,
                "source_path": (f"{PAYROLL_UPSTREAM_ROOT}."
                                f"{PAYROLL_UPSTREAM_LIST}[{index}]."
                                f"{PAYROLL_UPSTREAM_FIELD}"),
                "binding_method": "upstream_field",
                "unit": overlay[target].get("unit"),
            }
    return None


def build_overlay(state, doc):
    """Canonico ⊕ record DICHIARATI dall'input di binding del contratto.

    I record dichiarati dall'input non sono inventati dal validator: sono la
    parte canonica dell'input costruito dal contratto in esecuzione, che il
    chiamante trasmette insieme alle righe di binding. Un
    record dichiarato PREVALE su quello del progetto, perche' e' lo stato
    canonico che il contratto sta esercitando.
    """
    overlay = {}
    for entry in state.assumptions:
        if isinstance(entry, dict) and entry.get("id"):
            overlay.setdefault(entry["id"], entry)
    declared = []
    if isinstance(doc.get("canonical_records"), list):
        declared.extend(doc["canonical_records"])
    for key in ("shared_canonical_record", "canonical_after_update"):
        if isinstance(doc.get(key), dict):
            declared.append(doc[key])
    for entry in declared:
        if isinstance(entry, dict) and entry.get("id"):
            overlay[entry["id"]] = entry
    return overlay, [entry["id"] for entry in declared
                     if isinstance(entry, dict) and entry.get("id")]


def load_profile(profile_id, report):
    path = fw.SKILL_ROOT / "profiles" / f"{profile_id}.json"
    if not path.is_file():
        raise fw.ValidatorUsageError(f"profilo finanziario assente: {path}")
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise fw.ValidatorUsageError(f"profilo malformato: {path}: {exc}")
    for key in ("required_driver_roles", "role_measure_kind",
                "role_driver_class"):
        if key not in profile:
            raise fw.ValidatorUsageError(
                f"profilo {profile_id} senza {key}: il ruolo non e' "
                "verificabile contro il profilo attivo")
    return profile


def resolve_financial_config(args, doc, report):
    """Configurazione finanziaria, senza alcun fallback di runtime.

    In fase `egress` l'input di binding e' l'artefatto del candidate e puo'
    portare la `financial_config` PROPOSTA: quando lo fa, e' validata contro
    lo STESSO sottoschema `financial_config` usato dal framework. Quando non
    lo fa, si legge `shared/project-config.json` con `load_project_config`. In
    nessuno dei due casi una delle sei chiavi `required` e' sostituita con un
    ripiego.
    """
    declared = doc.get("financial_config")
    if declared is None:
        return fw.load_project_config(args.project, report=report)
    try:
        import jsonschema
    except ImportError as exc:
        raise fw.ValidatorUsageError(
            "jsonschema non importabile: la validazione a schema di "
            f"financial_config non e' eseguibile ({exc})")
    subschema = fw._financial_config_subschema()
    errors = sorted(
        jsonschema.Draft202012Validator(subschema).iter_errors(declared),
        key=lambda err: (list(map(str, err.absolute_path)), err.message))
    if errors:
        named = fw._financial_config_named_keys(
            declared if isinstance(declared, dict) else {}, subschema, errors)
        detail = "; ".join(
            "{}: {}".format("/".join(map(str, err.absolute_path)) or
                            "financial_config", err.message)
            for err in errors)
        report.add_error(
            fw.FINANCIAL_CONFIG_INVALID,
            message=(f"financial_config dichiarata dall'input di binding non "
                     f"conforme allo schema di financial_config; chiavi: "
                     f"{', '.join(named) if named else 'financial_config'}; "
                     f"{detail}; nessun valore di default e' sostituito"))
        return None
    return declared


def check_binding(args, config, state, report, doc, fingerprint):
    """Il corpo della validazione del binding: risoluzione, codici bloccanti,
    stato, fonti e riconciliazioni."""
    rows = [row for row in doc["driver_bindings"] if isinstance(row, dict)]
    documents = canonical_documents(args.project)
    overlay, declared_ids = build_overlay(state, doc)

    financial = resolve_financial_config(args, doc, report)
    profile_id = doc.get("profile_id") or \
        (financial or {}).get("financial_profile")
    if not profile_id:
        raise fw.ValidatorUsageError(
            "profilo finanziario non determinabile: ne' profile_id "
            "nell'input di binding ne' financial_config.financial_profile")
    profile = load_profile(profile_id, report)

    role_measure_kind = dict(profile.get("role_measure_kind") or {})
    declared_measure = doc.get("profile_role_measure_kind")
    if isinstance(declared_measure, dict):
        role_measure_kind.update(declared_measure)
    required_roles = list(profile.get("required_driver_roles") or [])
    optional_roles = list(profile.get("optional_driver_roles") or [])

    report.add_check(
        "financial_binding_input", "PASS",
        expected="driver_bindings[] fornito dall'input di binding",
        actual=f"{len(rows)} righe da {doc.get('_source_label')}",
        message=(f"input di binding ricevuto in fase {args.phase} per "
                 f"il profilo {profile_id}"))

    payroll_path = resolve_payroll_upstream(documents, overlay)

    # ---- verifiche per riga ------------------------------------------------
    for index, row in enumerate(rows):
        driver_id = row.get("driver_id") or f"driver_bindings[{index}]"
        role = row.get("role")
        check_row_shape(row, index, report)
        source_ref = row.get("source_ref")
        record = overlay.get(source_ref)
        if record is None:
            report.add_error(
                CODE_REF_UNRESOLVED, ref=driver_id,
                message=(f"source_ref {source_ref!r} non risolve in alcun "
                         "record del canonico: il binding e' su un "
                         "riferimento inesistente"),
                expected="un ASS-* risolvibile nell'overlay",
                actual=repr(source_ref))
        check_source_path(row, documents, report)
        has_canonical_path = (role != PAYROLL_ROLE) or (payroll_path is not None)
        check_explicit_declaration(row, has_canonical_path, report)
        check_units(row, profile, report)
        check_declarations(row, profile, role_measure_kind, report)
        reconcile_timing(row, report)

        # Stato mappato da funzione TOTALE, mai promosso.
        if record is not None:
            status, rule = propagated_status(source_ref, overlay)
            if status is None:
                report.add_error(
                    CODE_STATUS_UNMAPPABLE, ref=driver_id,
                    message=(f"combinazione di stato priva di riga nella "
                             f"funzione totale di mappatura dello stato per {source_ref}: "
                             f"validation_status="
                             f"{record.get('validation_status')!r}, "
                             f"evidence_classification="
                             f"{record.get('evidence_classification')!r}; "
                             "non esiste un ramo permissivo (R8)"),
                    expected="una combinazione decisa da R1...R7",
                    actual="R8 — fail-closed")
                report.add_check(
                    CODE_STATUS_UNMAPPABLE, "FAIL", affected_refs=[source_ref],
                    message="mappatura di stato: R8 fail-closed")
            else:
                report.add_check(
                    "driver_status_mapping", "PASS", affected_refs=[driver_id],
                    expected=rule, actual=status,
                    message=f"{source_ref} -> {status} per {rule} (mappatura di stato)")
                if status in ("unresolved", "placeholder"):
                    if role in required_roles:
                        report.add_error(
                            CODE_UNRESOLVED_REQUIRED, ref=driver_id,
                            message=(f"record {source_ref} in stato {status!r} "
                                     f"su ruolo RICHIESTO {role!r}: non e' "
                                     "consumabile e promuoverlo e' vietato"),
                            expected="confirmed o inferred", actual=status)
                        report.add_check(
                            CODE_UNRESOLVED_REQUIRED, "UNRESOLVED_INPUT",
                            affected_refs=[driver_id],
                            message=(f"{source_ref} {status} su ruolo "
                                     "richiesto: FAIL al gate"))
                    elif role in optional_roles and status == "placeholder":
                        report.add_warning(
                            CODE_PLACEHOLDER_OPTIONAL, ref=driver_id,
                            message=(f"record {source_ref} placeholder su "
                                     f"ruolo opzionale {role!r}: valore usato "
                                     "e caveat propagato all'output"))
                        report.add_check(
                            CODE_PLACEHOLDER_OPTIONAL, "WARNING",
                            affected_refs=[driver_id],
                            message="placeholder su ruolo opzionale")

            # `source_record_hash` uguale al record canonico corrente.
            bound = row.get("source_record_hash")
            current = fingerprint(record)
            if bound != current:
                report.add_error(
                    CODE_SOURCE_STALE, ref=driver_id,
                    message=(f"source_record_hash legato a {source_ref} "
                             "divergente dal record canonico corrente: il "
                             "valore legato non e' piu' quello del canonico "
                             "e il rebinding ricalcola l'impronta"),
                    expected=current, actual=bound)
                report.add_check(
                    CODE_SOURCE_STALE, "FAIL", affected_refs=[source_ref],
                    expected=current, actual=bound,
                    message="drift rilevato per confronto di impronta CAS")
            else:
                report.add_check(
                    CODE_SOURCE_STALE, "PASS", affected_refs=[source_ref],
                    expected=current, actual=bound,
                    message="impronta CAS coincidente con il canonico")

        # Modalita' 3 — chiusura transitiva; un upstream rimosso e'
        # `driver_ref_orphaned` alla rilettura.
        for upstream in row.get("upstream_refs") or []:
            if upstream not in overlay:
                report.add_error(
                    CODE_REF_ORPHANED, ref=driver_id,
                    message=(f"upstream_ref {upstream!r} non risolve piu' nel "
                             "canonico: riferimento orfano dopo il commit"),
                    expected="un ASS-* risolvibile", actual=repr(upstream))

        if row.get("double_count_risk") not in ("none", "conditional",
                                                "declared"):
            report.add_check(
                "driver_double_count_risk", "FAIL", affected_refs=[driver_id],
                message=(f"double_count_risk non dichiarato: "
                         f"{row.get('double_count_risk')!r}"))

    # ---- verifiche di insieme ---------------------------------------------
    check_cardinality_and_conflicts(rows, report)

    bound_roles = {row.get("role") for row in rows}
    for role in required_roles:
        if role in bound_roles:
            continue
        if role == PAYROLL_ROLE and payroll_path is not None:
            report.add_check(
                "driver_role_resolution", "PASS", affected_refs=[role],
                expected="upstream_field + derivazione",
                actual=payroll_path["source_ref"],
                message=(f"{role} risolto per upstream_field da "
                         f"{payroll_path['source_path']} -> "
                         f"{payroll_path['via']}."
                         f"derivation.variables.{PAYROLL_DERIVATION_VARIABLE}"
                         f" -> {payroll_path['source_ref']}, SENZA "
                         "explicit_declaration"))
            continue
        report.add_error(
            CODE_ROLE_UNBOUND, ref=role,
            message=(f"ruolo RICHIESTO dal profilo {profile_id} non legato: "
                     f"{role!r}; nessuna delle quattro modalita' di binding lo "
                     "risolve e non esiste valore di ripiego"),
            expected="un driver_binding per il ruolo", actual="nessuno")
        report.add_check(
            CODE_ROLE_UNBOUND, "FAIL", affected_refs=[role],
            message=f"ruolo richiesto {role} non legato")

    # ---- un driver informational non e' MAI consumato dal motore ---------
    consumed = doc.get("consumed_by_engine")
    if isinstance(consumed, list) and consumed:
        rows_by_id = {row.get("driver_id"): row for row in rows}
        flagged = False
        for driver_id in consumed:
            row = rows_by_id.get(driver_id)
            if row is None:
                continue
            if row.get("input_kind") == "informational":
                flagged = True
                report.add_error(
                    CODE_INFORMATIONAL_CONSUMED, ref=driver_id,
                    message=(f"driver {driver_id} dichiarato "
                             "input_kind: informational ed e' CONSUMATO dal "
                             "motore di calcolo: un input editabile ma non "
                             "operativo non e' mai consumato"),
                    expected="input_kind operational o derived",
                    actual="informational")
                report.add_check(
                    CODE_INFORMATIONAL_CONSUMED, "FAIL",
                    affected_refs=[driver_id],
                    message="driver informational consumato dal motore")
        if not flagged:
            report.add_check(
                CODE_INFORMATIONAL_CONSUMED, "PASS",
                affected_refs=list(consumed),
                message="nessun driver informational e' consumato dal motore")

    # ---- copertura COGS, caso nominale e casi limite ----------------------
    business_model = (documents.get("business_model") or {}).get("value")
    milestone_plan = (documents.get("milestone_plan") or {}).get("value")
    fpi = (milestone_plan or {}).get("financial_plan_inputs") \
        if isinstance(milestone_plan, dict) else None
    chain = doc.get("cogs_chain") if isinstance(doc.get("cogs_chain"), dict) \
        else {}
    pricing_ref = chain.get("pricing_ref") or \
        ((fpi or {}).get("pricing_ref") if isinstance(fpi, dict) else None)
    covered = set()
    if isinstance(fpi, dict) and isinstance(fpi.get("cogs_refs"), list):
        covered.update(fpi["cogs_refs"])
    covered.update(chain.get("covered_by_cogs_refs") or [])
    for row in rows:
        if row.get("role") == "variable_cost" and row.get("source_ref"):
            covered.add(row["source_ref"])
        covered.update(row.get("variable_cost_bindings") or [])
    exclusions = set(chain.get("declared_exclusions") or [])
    for row in rows:
        for excluded in row.get("declared_exclusions") or []:
            if row.get("decision_ref") and row.get("rationale"):
                exclusions.add(excluded)
                report.add_check(
                    CHECK_COGS_EXCLUSION, "WARNING", affected_refs=[excluded],
                    message=(f"esclusione deliberata dichiarata da "
                             f"{row.get('driver_id')} con "
                             f"{row.get('decision_ref')}: mai silenziosa "
                             "(esclusione deliberata dei COGS)"))

    if pricing_ref is not None:
        code, detail = evaluate_cogs_coverage(
            business_model, overlay, pricing_ref, covered, exclusions)
        if code:
            report.add_error(
                code, ref=detail.get("contribution_margin_ref"),
                message=(f"copertura COGS (caso nominale): {code}; "
                         f"riferimenti scoperti: "
                         f"{', '.join(detail.get('uncovered') or []) or '-'}; "
                         f"catena: {json.dumps(detail, sort_keys=True)}"),
                expected="ogni costo variabile del contribution margin coperto "
                         "da cogs_refs o escluso con decision_ref",
                actual=detail.get("uncovered") or detail.get("margin_kind"))
            report.add_check(
                code, "FAIL", affected_refs=detail.get("uncovered") or None,
                message="algoritmo di copertura COGS, caso nominale sui dati "
                        "committati")
        else:
            report.add_check(
                CODE_COGS_INCOMPLETE, "PASS",
                message="copertura COGS completa (caso nominale)")

    edge_cases = doc.get("edge_cases")
    if isinstance(edge_cases, dict):
        for name in sorted(edge_cases):
            case = edge_cases[name]
            if not isinstance(case, dict):
                continue
            case_bm = case.get("business_model", business_model)
            override = case.get("margin_record")
            code, detail = evaluate_cogs_coverage(
                case_bm, overlay, pricing_ref, covered, exclusions,
                margin_override=override)
            if code is None:
                # Fail-closed: un caso limite COGS non produce MAI
                # «regola non applicabile». Se l'algoritmo lo accettasse, e'
                # il caso limite a non essere piu' tale, e va riportato.
                report.add_check(
                    CODE_COGS_INCOMPLETE, "FAIL",
                    message=(f"caso limite COGS {name!r}: l'algoritmo non ha "
                             "prodotto alcun codice — il caso limite non e' "
                             "piu' fail-closed"))
                report.add_error(
                    CODE_COGS_INCOMPLETE, ref=name,
                    message=(f"caso limite COGS {name!r} accettato: un "
                             "margine irraggiungibile e' un difetto di input, "
                             "non un permesso a saltare il controllo"),
                    expected="FAIL", actual="nessun codice")
                continue
            report.add_error(
                code, ref=name,
                message=(f"caso limite COGS {name!r}: {code} — FAIL, mai "
                         f"«non applicabile»; catena: "
                         f"{json.dumps(detail, sort_keys=True)}"),
                expected="FAIL", actual=code)
            report.add_check(
                code, "FAIL", affected_refs=[name],
                message=f"caso limite COGS {name}: {code}")

    if declared_ids:
        report.add_check(
            "canonical_records_declared", "PASS",
            affected_refs=sorted(set(declared_ids)),
            message=(f"{len(set(declared_ids))} record canonici DICHIARATI "
                     "dall'input di binding, sovrapposti al canonico del "
                     "progetto in sola lettura"))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    # La superficie CLI del SOLO validate_financial_binding.py
    # acquisisce `--binding-input`. `_framework.parse_args` respinge gli
    # argomenti che non conosce: l'argomento e' quindi estratto PRIMA e il
    # resto e' passato invariato al framework, la cui semantica di exit code
    # (0/1/2/3) resta INVARIATA.
    pre = argparse.ArgumentParser(prog=VALIDATOR_NAME, add_help=False)
    pre.add_argument("--binding-input")
    try:
        known, rest = pre.parse_known_args(argv)
    except SystemExit:
        print(f"{VALIDATOR_NAME}: argomenti CLI non validi", file=sys.stderr)
        return fw.EXIT_USAGE
    binding_input = known.binding_input

    def check_fn(args, config, state, report):
        if args.stage != STAGE10:
            raise fw.ValidatorUsageError(
                f"stage non pertinente a {VALIDATOR_NAME}: {args.stage} "
                f"(atteso {STAGE10})")
        if args.phase not in SUPPORTED_PHASES:
            raise fw.ValidatorUsageError(
                f"--phase non ammessa per {VALIDATOR_NAME}: {args.phase} "
                f"(ammesse: {SUPPORTED_PHASES}, come in enforcement-config)")
        doc = read_binding_input(args, binding_input)
        fingerprint = load_record_fingerprint()
        check_binding(args, config, state, report, doc, fingerprint)

    fw.run_validator(VALIDATOR_NAME, check_fn, rest)
    return fw.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
