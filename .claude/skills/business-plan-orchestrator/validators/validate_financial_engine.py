#!/usr/bin/env python3
"""validate_financial_engine — motore finanziario dello Stage 10.

Secondo anello della pipeline finanziaria dello Stage 10 (binding -> motore
-> riconciliazione -> output canonico). E' un validator di pipeline interna:
non entra in `egress_required`, e al confine di egress il Transaction Manager
invoca soltanto `validate_financial_output` sul documento canonico.

CHE COSA CALCOLA
----------------
I QUATTORDICI moduli deterministici, in ordine causale — `calendar`,
`revenue`, `cogs`, `gross_margin`, `headcount`, `payroll`, `opex`, `pnl`,
`cash_flow`, `runway`, `cash_buffer`, `break_even`, `funding_gap`, `kpi` —,
i tre scenari (`base`, `downside`, `upside`) con la loro copertura, la
sensitivity a un driver per volta e le UNDICI riconciliazioni: `REC-01`,
`REC-02`, `REC-03`, `REC-04`, `REC-05`, `REC-06`, `REC-11`, `REC-12`,
`REC-13`, `REC-14`, `REC-15`.

Il modulo `milestone_coverage` e la riconciliazione `REC-09` NON sono
calcolati qui: nel documento canonico li pubblica il costruttore
(`output/build_canonical_output.py`) come `NOT_APPLICABLE` con motivazione.

CHE COSA CONSUMA
----------------
Il payload di binding gia' RISOLTO dal layer di binding
(`validate_financial_binding`) piu' una `financial_config` validata. Il motore
NON risolve riferimenti a monte: li consuma risolti. Rilegge il canonico
SOLTANTO per confrontare `source_record_hash`. Non esegue ne' innesca alcuna
ricerca esterna: il registro dei driver arriva GIA' governato.

CHE COSA PRODUCE
----------------
A. un PAYLOAD FINANZIARIO INTERMEDIO NON CANONICO, conforme allo schema
   `financial-plan.schema.json` per `$ref` sulle sole sezioni di competenza;
B. una PROIEZIONE DI GOVERNANCE TIPIZZATA NON CANONICA, restituita ACCANTO ad
   A: porta STATO e RIFERIMENTI, mai importi, serie, metriche o quantita'.

La proiezione NON e' canonica, NON e' una seconda verita' numerica, NON e' un
file sidecar, NON e' prosa e NON e' un artefatto di progetto persistito.
Nessun path canonico e' scritto in alcun caso, nessuna cartella
`10_financial-plan/` e' creata e nessun progetto e' mutato: il documento
canonico e' composto a valle dal costruttore canonico.

SUPERFICIE CLI
--------------
    --project         directory del progetto, letta in SOLA LETTURA
    --stage           10_financial-plan
    --phase           egress | impact
    --candidate       workspace candidate (obbligatorio in fase egress)
    --engine-input    <path>|-   payload di binding + financial_config
    --engine-output   <path>     payload intermedio + proiezione, ammesso
                                 SOLTANTO fuori dal progetto e mai su un path
                                 canonico

EXIT CODE — semantica di `_framework.py`, INVARIATA
---------------------------------------------------
    0  nessun errore        1  contratto violato
    2  errore d'uso         3  stato canonico non valido

DISCIPLINA DELLE COSTANTI
-------------------------
Nel sorgente vivono SOLO costanti strutturali: nomi di modulo, versioni,
tassonomie, precisione decimale e aritmetica di periodo. Orizzonte,
`anchor_date`, valuta, prezzi, salari, tassi, costi unitari e benchmark
NON compaiono: vivono in `financial_config` e nei record `ASS-*`. Le soglie di
riconciliazione sono LETTE da `config/enforcement-config.json` e mai
reinventate. Nessun ramo di calcolo, gate o stato dipende da un attributo di
resa.
"""
import argparse
import calendar as civil
import datetime
import hashlib
import importlib.util
import json
import sys
from decimal import Decimal, localcontext
from pathlib import Path

import _framework as fw

VALIDATOR_NAME = "validate_financial_engine"

STAGE10 = "10_financial-plan"
SUPPORTED_PHASES = ("egress", "impact")
ENGINE_INPUT_DEFAULT = "engine-input.json"

ENGINE_VERSION = "1.0.0"
FORMULA_VERSION = "1.0.0"
MODULE_VERSION = "1.0.0"

#: Precisione interna degli accumuli. L'arrotondamento e' ALLA PRESENTAZIONE:
#: il payload intermedio serializza gli accumuli in forma STRINGA, che lo
#: schema ammette proprio per preservare la precisione.
CALCULATION_PRECISION = 28

#: I QUATTORDICI moduli, in ordine di catena. Gli ultimi tre dipendono da
#: `gross_margin`/`opex`/`payroll` (`break_even`), da `cash_flow`
#: (`funding_gap`) e da tutti i precedenti (`kpi`): l'ordine e' CAUSALE, non
#: alfabetico.
MODULE_ORDER = ("calendar", "revenue", "cogs", "gross_margin", "headcount",
                "payroll", "opex", "pnl", "cash_flow", "runway", "cash_buffer",
                "break_even", "funding_gap", "kpi")

#: I TRE scenari. L'enumerazione e' CHIUSA dallo schema.
SCENARIO_IDS = ("base", "downside", "upside")

#: Polarita'. Decide QUALE estremo della terna dichiarata diventa
#: Downside e quale Upside. Applicare `Downside = High` a TUTTO e' vietato:
#: `churn_rate` e' `cost_like` e `retention_rate` e' `revenue_like`, e leggerli
#: allo stesso modo e' l'errore che il profilo stesso annota.
POLARITY_LOW_ON_DOWNSIDE = ("revenue_like",)
POLARITY_HIGH_ON_DOWNSIDE = ("cost_like",)
#: `timing_like` NON e' invariante: Downside e' RITARDATO e Upside
#: e' ANTICIPATO. A muoversi e' il TIMING DICHIARATO del driver, mai l'importo:
#: la terna di un driver di timing dichiara PERIODI (date di milestone, ramp,
#: ingressi in organico), non valori economici. Trattarlo come invariante
#: ignorerebbe in silenzio gli estremi che il record DICHIARA.
POLARITY_TIMING = ("timing_like",)
#: `neutral` e' l'UNICA polarita' invariante: `cash_buffer` e
#: `financing` non hanno un caso avverso proprio.
POLARITY_INVARIANT = ("neutral",)

#: Le OTTO voci del set minimo di KPI. Lo schema le
#: dichiara TUTTE `required` ed e' `additionalProperties: false`: non ne esiste
#: una nona e non ne manca una. Il modulo esiste SEMPRE; si riduce il contenuto.
KPI_IDS = ("gross_margin_pct", "monthly_burn", "runway", "cac", "ltv",
           "ltv_cac_ratio", "break_even_period", "milestone_coverage")

#: L'insieme di dipendenza PROPRIO di CIASCUN indicatore. E' il solo
#: insieme rispetto al quale un ruolo puo' essere dichiarato mancante per quel
#: KPI: un indicatore non nomina MAI un ruolo che non gli serve, e non nomina
#: MAI come mancante un ruolo che il payload ha LEGATO e CONSUMATO. Scegliere il
#: nome per POSIZIONE invece che per ASSENZA sopprime la ragione finanziaria
#: reale -- «il pareggio non e' raggiunto» -- e la sostituisce con un input che
#: non manca, contraddicendo il modulo `break_even` dello STESSO payload.
KPI_DRIVER_ROLES = {
    "gross_margin_pct": ("unit_price", "customer_volume"),
    "monthly_burn": (),
    "runway": (),
    "cac": ("cac",),
    "ltv": ("unit_price", "customer_volume", "churn_rate"),
    "ltv_cac_ratio": ("unit_price", "customer_volume", "churn_rate", "cac"),
    "break_even_period": ("unit_price", "customer_volume", "variable_cost"),
    "milestone_coverage": ("milestone_cost",),
}

#: Default di POLICY della soglia di copertura degli scenari, DICHIARATO e
#: riportato in `calculation_metadata`. E' una costante di policy, non un
#: valore economico, ed e' serializzata come STRINGA
#: esattamente come le tolleranze di `enforcement-config.json`: un letterale
#: numerico nel sorgente sarebbe indistinguibile da un valore economico.
SCENARIO_COVERAGE_THRESHOLD_DEFAULT = "0.8"

#: Default di POLICY per l'approvabilita' di un piano `base_only` (copertura
#: di scenario NULLA). E' DICHIARATO qui e mai applicato in silenzio: l'esito
#: della sua applicazione e' OSSERVABILE in `validation.result`, in `checks[]`
#: e in `warnings[]`/`errors[]`. NON e' riportato in `calculation_metadata`, e
#: non deve esserlo: nessun campo di schema e' aggiunto per ripeterlo. Con la
#: policy `true` la copertura NULLA porta a `approved_with_conditions` con una
#: `COND-*` esplicita: cioe' un esito che porta la condizione, NON
#: un'approvazione piena. Con la policy dichiarata `false` il piano FALLISCE
#: CHIUSO, che e' l'altra meta' della stessa regola.
SCENARIO_BASE_ONLY_APPROVABLE_DEFAULT = True

#: L'esito di un piano a copertura NULLA approvabile.
#: Non e' un'approvazione: e' un'approvazione CON CONDIZIONI, e il risultato di
#: validazione lo deve RIFLETTERE (almeno `WARNING`), altrimenti un lettore a
#: valle che legga `validation.result` vede un piano approvato.
COVERAGE_BASE_ONLY_OUTCOME = "approved_with_conditions"

#: Livelli di copertura. L'enumerazione e' CHIUSA dallo schema.
COVERAGE_FULL = "full"
COVERAGE_PARTIAL = "partial"
COVERAGE_NONE = "none"

#: Stage entro cui la `COND-*` proposta va chiusa quando la
#: copertura e' NULLA. Non e' una decisione di funding: e' un debito tracciato.
COVERAGE_CONDITION_STAGE = "11_funding-request"
COVERAGE_CONDITION_REF = "COND-S10-SCENARIO-COVERAGE"

#: Mesi per periodo secondo la frequenza del calendario.
MONTHS_PER_PERIOD = {"monthly": 1, "quarterly": 3, "annual": 12}
#: Mesi della frequenza NATIVA di un driver.
NATIVE_MONTHS = {"monthly": 1, "quarterly": 3, "annual": 12}

#: Regole di ripartizione (`flow`) e di livello (`stock`).
FLOW_RULES = ("one_off", "uniform", "front_loaded", "back_loaded",
              "custom_schedule", "milestone_start", "milestone_end")
STOCK_RULES = ("constant", "step_level", "from_schedule")

#: Vocabolario di conversione ACCETTATO in INGRESSO, per natura della misura.
#: E' l'insieme CHIUSO che il validator di binding impone
#: (`CONVERSION_POLICIES` piu' `POLICY_BY_MEASURE_KIND`), esteso alla sola
#: forma `preserve_rate` che lo schema del piano finanziario usa per la STESSA
#: politica di `per_unit`. Nessuna stringa fuori
#: da qui e' accettata, per NESSUNA natura di misura: una politica arbitraria e
#: una politica valida per un'ALTRA natura sono entrambe RESPINTE.
BINDING_POLICY_BY_MEASURE = {
    "flow": ("allocate",),
    "stock": ("carry_level",),
    "rate": ("compound",),
    "per_unit": ("preserve_per_unit", "preserve_rate"),
}

#: MAPPATURA DI CONFINE fra il vocabolario di BINDING e il vocabolario dello
#: SCHEMA di piano finanziario, che divergono su
#: UNA sola etichetta: la politica di `per_unit` si chiama `preserve_per_unit`
#: nel validator di binding e `preserve_rate` nello schema. La mappatura e'
#: DETERMINISTICA, TOTALE sui valori accettati in ingresso, RESPINGE per
#: costruzione ogni valore sconosciuto (che il gate ha gia' bloccato) e
#: PRESERVA la semantica: `rate` e `per_unit` restano DUE politiche distinte e
#: non sono MAI fuse. `require_native_frequency` esiste nell'enumerazione dello
#: schema ma NESSUN `measure_kind` la ammette in ingresso secondo il validator
#: di binding: non e' quindi un valore mappabile, ed e' respinta come
#: qualunque altra politica non ammessa per la propria natura.
CONVERSION_POLICY_BOUNDARY = {
    "allocate": "allocate",
    "carry_level": "carry_level",
    "compound": "compound",
    "preserve_per_unit": "preserve_rate",
    "preserve_rate": "preserve_rate",
}

#: Tassonomia di fonti e usi. Le categorie sono MUTUAMENTE
#: ESCLUSIVE: e' la difesa strutturale contro il doppio conteggio.
SOURCE_CATEGORIES = ("operating_revenue", "other_operating_income")
USE_CATEGORIES = ("operating_cost", "interest", "mandatory_financing_fee")
FINANCING_CATEGORIES = ("equity_financing", "debt_financing",
                        "convertible_financing", "grant_income")

#: Ordine di propagazione. Lo stato di un derivato e' il MINIMO.
STATUS_ORDER = ("unresolved", "placeholder", "inferred", "confirmed")

#: Politica DICHIARATA per una voce di proiezione
#: priva di riferimenti di input consumati. E' il fondo dell'enumerazione
#: chiusa, mai uno stato PRESO IN PRESTITO da un altro modulo.
NO_GOVERNED_INPUT_STATUS = "unresolved"

#: Codici di binding e di gate condivisi con il layer di binding. Nessuno e'
#: inventato qui.
CODE_ROLE_UNBOUND = "driver_role_unbound"
CODE_UNRESOLVED_REQUIRED = "unresolved_required_input"
CODE_PLACEHOLDER_OPTIONAL = "placeholder_optional_input"
CODE_SOURCE_STALE = "driver_source_stale"
CODE_SOURCE_CONFLICT = "source_conflict_unresolved"
CODE_INFORMATIONAL = "driver_informational_consumed"
CODE_FINANCING_IN_PNL = "financing_in_pnl"
CODE_PERIOD_UNDECLARED = "driver_period_undeclared"
#: Codice gia' NOMINATO dal validator di binding
#: (`validate_financial_binding.CODE_CONVERSION_POLICY`). E' RIUSATO qui, non
#: coniato: una politica di conversione non ammessa per la propria
#: natura di misura e' lo stesso difetto, rilevato al confine del motore.
CODE_CONVERSION_POLICY = "driver_conversion_policy_undeclared"

#: I QUATTRO codici propri del calcolo: saldo di apertura usato come fonte,
#: tasso convertito senza composizione, determinismo violato, misure di cassa
#: collassate.
CODE_OPENING_AS_SOURCE = "opening_balance_as_source"
CODE_RATE_NOT_COMPOUNDED = "rate_conversion_not_compounded"
CODE_DETERMINISM = "engine_determinism_violated"
CODE_CASH_COLLAPSED = "cash_metrics_collapsed"

#: I DUE codici di scenari e sensitivity: passo di sensitivity che muove piu'
#: di un driver, serie di scenario identiche etichettate come distinte.
CODE_SENSITIVITY_MULTI = "sensitivity_multi_driver"
CODE_SCENARIO_IDENTICAL = "scenario_series_identical"

#: Codice di dominio esistente: `funding_gap`
#: non compare MAI fra le SOURCES, perche' e' un RESIDUO e non una fonte.
CODE_GAP_AS_SOURCE = "funding_gap_as_source"

#: `check_id` strutturali. La regola vieta di coniare nuovi CODICI DI ERRORE,
#: non identificatori di check: il validator di binding ne dichiara gia'
#: quattro propri (`driver_status_mapping`, `driver_double_count_risk`, ...).
CHECK_DERIVED = "driver_derived_not_assumable"
CHECK_ENGINE_INPUT = "financial_engine_input"

#: Identificatori ESISTENTI delle riconciliazioni del calcolo core. Nessun
#: `rec_id` nuovo e' coniato.
REC_REVENUE_DETAIL = "REC-01"
REC_COGS_DETAIL = "REC-02"
REC_PAYROLL_IDENTITY = "REC-03"
REC_OPEX_DETAIL = "REC-04"
REC_CASH_ROLL_FORWARD = "REC-05"
REC_FLOW_QUOTA = "REC-12"
REC_STOCK_LEVEL = "REC-14"

#: Le QUATTRO riconciliazioni di ponte, scenario, categorie e pareggio.
#: `REC-07` e `REC-08` sono opzionali e non prodotte, `REC-09` e' pubblicata
#: `NOT_APPLICABLE` dal costruttore canonico e `REC-10` riguarda lo Stage 11:
#: nessuna di esse e' prodotta qui.
REC_PNL_CASH_BRIDGE = "REC-06"
REC_SCENARIO_DETAIL = "REC-11"
REC_CATEGORY_TOTAL = "REC-13"
REC_BREAK_EVEN = "REC-15"

#: Etichetta della categoria di residuo per un importo che nessuna categoria
#: della tassonomia dichiara. Non e' una categoria: e' il nome del residuo.
UNCATEGORISED = "uncategorised"

#: Ruolo canonico del saldo di apertura. E' un SALDO, mai una fonte.
OPENING_BALANCE = "opening_cash_balance"

#: Codice del WARNING ADDITIVO di finestra di timing SVUOTATA (politica di
#: clipping ancorato allo start). La severita' WARNING e' portata
#: dall'APPARTENENZA a `validation.warnings[]`: NESSUN campo `severity` esiste
#: e nessuno e' aggiunto. L'attribuzione vive ESCLUSIVAMENTE in
#: `affected_refs[]`, in forma di TRE TOKEN TIPIZZATI: un `DRV-*`, un
#: `module:<module-id>` e uno `scenario:<scenario-id>`. Il campo `message` e'
#: PROSA DESCRITTIVA e NON porta attribuzione: metterla li' la renderebbe
#: «prosa da re-interpretare», che la regola vieta.
CODE_TIMING_WINDOW_EMPTY = "timing_window_empty"

#: Prosa DESCRITTIVA del warning, DELIBERATAMENTE priva di attribuzione.
TIMING_WINDOW_EMPTY_MESSAGE = (
    "la finestra di timing risolta per lo scenario e' VUOTA: lo start risolto "
    "e' successivo all'end DICHIARATO, entrambi dentro l'orizzonte. Sotto la "
    "politica di CLIPPING ANCORATO ALLO START a muoversi e' lo "
    "START e l'END resta quello del binding: la finestra si accorcia fino a "
    "svuotarsi. Il driver NON contribuisce, e la non-contribuzione e' "
    "DICHIARATA qui invece di essere dedotta da un valore zero. "
    "L'attribuzione esatta — driver, modulo consumatore e scenario — vive nei "
    "TRE TOKEN TIPIZZATI di affected_refs[], mai in questa prosa.")

ZERO = Decimal(0)
ONE = Decimal(1)


# --------------------------------------------------------------------------
# CAS esistente — riuso in SOLA LETTURA
# --------------------------------------------------------------------------


def load_record_fingerprint():
    """`record_fingerprint` del Transaction Manager, importato read-only."""
    path = fw.SKILL_ROOT / "transaction" / "transaction_manager.py"
    if not path.is_file():
        raise fw.ValidatorUsageError(
            f"transaction_manager assente: {path}; source_record_hash non e' "
            "verificabile")
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
            "transaction_manager senza record_fingerprint")
    return fingerprint


def engine_source_hash():
    """sha256 del SORGENTE del motore.

    Una stringa di versione ci si dimentica di aggiornarla; un hash del
    sorgente NON PUO' divergere dal codice.
    """
    return hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# Ingresso del motore
# --------------------------------------------------------------------------


def read_engine_input(args, engine_input):
    """Legge il payload di binding gia' risolto.

    Un input assente, illeggibile o malformato e' un ERRORE D'USO (exit 2):
    non e' mascherato da un FAIL di contenuto, e un FAIL di contenuto non e'
    mascherato da un errore d'uso.
    """
    if engine_input == "-":
        text = sys.stdin.read()
        label = "<stdin>"
    else:
        if engine_input:
            path = Path(engine_input)
        elif args.candidate is not None:
            path = args.candidate / ENGINE_INPUT_DEFAULT
        else:
            raise fw.ValidatorUsageError(
                "--engine-input obbligatorio: senza --candidate non esiste un "
                f"{ENGINE_INPUT_DEFAULT} da cui leggere l'ingresso del motore")
        if not path.is_file():
            raise fw.ValidatorUsageError(f"ingresso del motore assente: {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise fw.ValidatorUsageError(
                f"ingresso del motore illeggibile: {path}: {exc}")
        label = str(path)
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise fw.ValidatorUsageError(
            f"ingresso del motore malformato: {label}: {exc}")
    if not isinstance(doc, dict):
        raise fw.ValidatorUsageError(
            f"ingresso del motore non e' un oggetto JSON: {label}")
    rows = doc.get("driver_bindings")
    if not isinstance(rows, list) or not rows:
        raise fw.ValidatorUsageError(
            f"ingresso senza driver_bindings[] non vuoto: {label}")
    doc["_source_label"] = label
    return doc


def resolve_output_target(raw, project):
    """Dove il payload puo' essere scritto (`--engine-output`).

    Il motore NON scrive alcun path canonico e non crea alcuna cartella di
    stage: la destinazione dentro il progetto, dentro una cartella di Stage 10
    o su un `structured-output.json` e' un ERRORE D'USO, respinto PRIMA di
    creare qualunque directory.
    """
    if raw is None:
        return None
    target = Path(raw)
    if not target.is_absolute():
        target = (Path.cwd() / target)
    resolved = Path(target.as_posix())
    parts = resolved.parts
    if STAGE10 in parts:
        raise fw.ValidatorUsageError(
            f"--engine-output su un path di Stage 10: {raw}; il motore non "
            "produce alcun output canonico e non crea alcuna cartella "
            f"{STAGE10}/")
    if resolved.name == "structured-output.json":
        raise fw.ValidatorUsageError(
            f"--engine-output su un path canonico: {raw}; il motore non "
            "produce structured-output.json")
    project_resolved = Path(project).resolve()
    try:
        candidate = Path(target).resolve()
    except OSError as exc:
        raise fw.ValidatorUsageError(f"--engine-output non risolvibile: {exc}")
    if candidate == project_resolved or project_resolved in candidate.parents:
        raise fw.ValidatorUsageError(
            f"--engine-output dentro il progetto: {raw}; nessun progetto e' "
            "mutato dal motore")
    return candidate


def build_overlay(state, doc):
    """Canonico del progetto (+) record DICHIARATI dall'ingresso.

    E' la stessa disciplina del layer di binding: i record dichiarati
    sono la parte canonica dell'ingresso costruito dal contratto in esecuzione,
    non un'invenzione del validator.
    """
    overlay = {}
    for entry in state.assumptions:
        if isinstance(entry, dict) and entry.get("id"):
            overlay.setdefault(entry["id"], entry)
    declared = doc.get("canonical_records")
    if isinstance(declared, list):
        for entry in declared:
            if isinstance(entry, dict) and entry.get("id"):
                overlay[entry["id"]] = entry
    return overlay


def load_profile(profile_id):
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
            raise fw.ValidatorUsageError(f"profilo {profile_id} senza {key}")
    return profile


def resolve_financial_config(args, doc, report):
    """Configurazione finanziaria, senza alcun fallback di runtime."""
    declared = doc.get("financial_config")
    if declared is None:
        return fw.load_project_config(args.project, report=report)
    try:
        import jsonschema
    except ImportError as exc:
        raise fw.ValidatorUsageError(
            f"jsonschema non importabile: {exc}")
    subschema = fw._financial_config_subschema()
    errors = sorted(
        jsonschema.Draft202012Validator(subschema).iter_errors(declared),
        key=lambda err: (list(map(str, err.absolute_path)), err.message))
    if errors:
        named = fw._financial_config_named_keys(
            declared if isinstance(declared, dict) else {}, subschema, errors)
        detail = "; ".join(
            f"{'/'.join(map(str, err.absolute_path)) or 'financial_config'}: "
            f"{err.message}" for err in errors)
        report.add_error(
            fw.FINANCIAL_CONFIG_INVALID,
            message=(f"financial_config dichiarata dall'ingresso non conforme "
                     f"allo schema di financial_config; chiavi: "
                     f"{', '.join(named) if named else 'financial_config'}; "
                     f"{detail}; nessun valore di default e' sostituito"))
        return None
    return declared


def emitted_conversion_policy(policy):
    """La politica di conversione nel vocabolario dello SCHEMA.

    E' la funzione di CONFINE fra i due vocabolari (binding e schema). E'
    DETERMINISTICA e TOTALE sui valori ammessi in ingresso; un valore che non
    conosce e' gia' stato RESPINTO dal gate e viene restituito INVARIATO,
    perche' una coercizione silenziosa nasconderebbe la violazione. `rate` e
    `per_unit` restano due politiche DISTINTE: `compound` e `preserve_rate` non
    sono mai fuse.
    """
    return CONVERSION_POLICY_BOUNDARY.get(policy, policy)


def tolerance_table():
    """Le soglie sono LETTE da `enforcement-config.json`, mai reinventate."""
    config = fw.load_config()
    table = config.get("tolerances")
    if not isinstance(table, dict) or not table:
        raise fw.ValidatorUsageError(
            "enforcement-config senza tolerances: le soglie di "
            "riconciliazione non sono derivabili")
    return table


# --------------------------------------------------------------------------
# Calendario
# --------------------------------------------------------------------------


def parse_iso_date(text):
    """Data ISO-8601 DICHIARATA, mai derivata dall'orologio."""
    parts = str(text).split("-")
    if len(parts) != 3:
        raise fw.ValidatorUsageError(f"anchor_date non ISO-8601: {text!r}")
    year, month, day = (int(part) for part in parts)
    return datetime.date(year, month, day)


def shift_months(year, month, count):
    total = year * 12 + (month - 1) + count
    return total // 12, total % 12 + 1


def month_length(year, month):
    return civil.monthrange(year, month)[1]


def build_calendar(config):
    """Periodi, periodo parziale e quota giornaliera.

    L'orizzonte e l'ancora vengono ENTRAMBI da `financial_config`: nessuno dei
    due e' una costante di questo modulo e nessuno dei due e' derivato
    dall'orologio.
    """
    anchor = parse_iso_date(config["anchor_date"])
    frequency = config["frequency"]
    months = MONTHS_PER_PERIOD[frequency]
    horizon = int(config["horizon_periods"])
    periods = []
    for index in range(horizon):
        span_year, span_month = shift_months(anchor.year, anchor.month,
                                             months * index)
        end_year, end_month = shift_months(anchor.year, anchor.month,
                                           months * index + months - 1)
        span_start = datetime.date(span_year, span_month, 1)
        span_end = datetime.date(end_year, end_month,
                                 month_length(end_year, end_month))
        start = anchor if index == 0 else span_start
        span_days = (span_end - span_start).days + 1
        covered = (span_end - start).days + 1
        fraction = Decimal(covered) / Decimal(span_days)
        entry = {
            "index": index,
            "start_date": str(start),
            "end_date": str(span_end),
            "partial": covered != span_days,
        }
        if entry["partial"]:
            entry["day_fraction"] = amount(fraction)
        periods.append(entry)
        del entry
    fractions = []
    for index in range(horizon):
        span_year, span_month = shift_months(anchor.year, anchor.month,
                                             months * index)
        end_year, end_month = shift_months(anchor.year, anchor.month,
                                           months * index + months - 1)
        span_start = datetime.date(span_year, span_month, 1)
        span_end = datetime.date(end_year, end_month,
                                 month_length(end_year, end_month))
        start = anchor if index == 0 else span_start
        span_days = (span_end - span_start).days + 1
        covered = (span_end - start).days + 1
        fractions.append(Decimal(covered) / Decimal(span_days))
    return {
        "anchor_date": str(anchor),
        "frequency": frequency,
        "horizon_periods": horizon,
        "periods": periods,
    }, fractions, months


def amount(value):
    """Serializzazione di un accumulo `Decimal` a piena precisione.

    Lo schema ammette la forma STRINGA proprio per questo: gli accumuli
    interni NON sono arrotondati a ogni passo.
    """
    return f"{value:f}"


def series_map(values):
    return {str(index): amount(value) for index, value in enumerate(values)}


# --------------------------------------------------------------------------
# Risoluzione dei driver in serie deterministiche
# --------------------------------------------------------------------------


def record_value(record):
    value = record.get("value")
    if value is None:
        return None
    return Decimal(str(value))


def flow_weights(binding, horizon, fractions):
    """Quote di ripartizione di un `flow`.

    Le regole generate dal motore sono NORMALIZZATE per costruzione (Sigma = 1);
    una `custom_schedule` DICHIARATA e' presa alla lettera, cosi' che `REC-12`
    possa misurarne la massa persa invece di sanarla in silenzio.
    """
    start = binding.get("start_period")
    end = binding.get("end_period")
    start = 0 if start is None else int(start)
    end = horizon - 1 if end is None else int(end)
    rule = binding.get("timing_rule")
    weights = [ZERO] * horizon
    if rule == "custom_schedule":
        schedule = binding.get("timing_schedule") or {}
        for key, quota in schedule.items():
            index = int(key)
            if 0 <= index < horizon:
                weights[index] = Decimal(str(quota))
        return weights, sum(weights, ZERO)
    window = [index for index in range(start, end + 1) if index < horizon]
    if not window:
        return weights, ZERO
    if rule in ("one_off", "milestone_start"):
        raw = [ONE if index == window[0] else ZERO for index in window]
    elif rule == "milestone_end":
        raw = [ONE if index == window[-1] else ZERO for index in window]
    elif rule == "front_loaded":
        raw = [Decimal(len(window) - position) * fractions[index]
               for position, index in enumerate(window)]
    elif rule == "back_loaded":
        raw = [Decimal(position + 1) * fractions[index]
               for position, index in enumerate(window)]
    else:
        raw = [fractions[index] for index in window]
    total = sum(raw, ZERO)
    if total == ZERO:
        return weights, ZERO
    for position, index in enumerate(window):
        weights[index] = raw[position] / total
    return weights, sum(weights, ZERO)


def stock_levels(binding, horizon):
    """Livelli di uno `stock`, con gli eventi DICHIARATI.

    Restituisce `(livelli, eventi, periodi_scoperti)`. `from_schedule` esige
    COPERTURA COMPLETA della finestra: i periodi scoperti sono variazioni non
    spiegate, che `REC-14` attribuisce al proprio periodo.
    """
    start = binding.get("start_period")
    end = binding.get("end_period")
    start = 0 if start is None else int(start)
    end = horizon - 1 if end is None else int(end)
    rule = binding.get("timing_rule")
    schedule = binding.get("timing_schedule") or {}
    levels = [ZERO] * horizon
    events = {start}
    if end + 1 < horizon:
        events.add(end + 1)
    uncovered = []
    if rule == "step_level":
        steps = sorted((int(key), Decimal(str(value)))
                       for key, value in schedule.items())
        for index in range(start, min(end + 1, horizon)):
            level = ZERO
            for step_index, step_value in steps:
                if step_index <= index:
                    level = step_value
            levels[index] = level
        events |= {index for index, _ in steps}
    elif rule == "from_schedule":
        declared = {int(key): Decimal(str(value))
                    for key, value in schedule.items()}
        for index in range(start, min(end + 1, horizon)):
            if index in declared:
                levels[index] = declared[index]
                events.add(index)
            else:
                uncovered.append(index)
    else:
        value = binding.get("_resolved_value")
        for index in range(start, min(end + 1, horizon)):
            levels[index] = value
    return levels, events, uncovered


def rate_series(binding, horizon, fractions, months):
    """Conversione COMPOSTA di un tasso, mai per divisione.

    `r_p = 1 - (1 - r_a) ** (p / a)`. La divisione lineare sottostima il tasso
    in direzione sistematicamente favorevole al piano ed e' INVISIBILE alle
    riconciliazioni: e' il difetto `rate_conversion_not_compounded`.
    """
    annual = binding["_resolved_value"]
    native = NATIVE_MONTHS.get(binding.get("frequency"), months)
    values = []
    with localcontext() as local:
        local.prec = CALCULATION_PRECISION
        for index in range(horizon):
            exponent = Decimal(months) * fractions[index] / Decimal(native)
            values.append(ONE - (ONE - annual) ** exponent)
        full = ONE - (ONE - annual) ** (Decimal(months) / Decimal(native))
    return values, full


# --------------------------------------------------------------------------
# Gate che PRECEDONO il calcolo (fail-closed, nessun ripiego)
# --------------------------------------------------------------------------


def provenance_defects(binding, record):
    """Provenienza minima di un driver assunto."""
    missing = []
    for field in ("source_ref", "source_path", "source_record_hash",
                  "rationale", "confidence"):
        if not binding.get(field):
            missing.append(field)
    classification = (record or {}).get("evidence_classification")
    if classification == "external_source":
        if not binding.get("evidence_refs"):
            missing.append("evidence_refs")
        if not (record or {}).get("last_updated"):
            missing.append("last_updated")
    return missing


def resolve_precedence(rows, report):
    """Precedenza delle fonti, mai silenziosa.

    CONVENZIONE: `source_priority` e' un intero e la precedenza e' CRESCENTE,
    come nel layer di binding. Una fonte di priorita' INFERIORE non
    sovrascrive MAI il vincitore; a priorita' PARI con riferimenti DISTINTI e
    senza `decision_ref` la scelta implicita e' VIETATA e il piano si BLOCCA.
    """
    by_role = {}
    for binding in rows:
        by_role.setdefault(binding.get("role"), []).append(binding)
    winners = []
    superseded = []
    blocked = False
    for role in sorted(by_role, key=str):
        group = by_role[role]
        if len(group) == 1 or "one" not in {b.get("cardinality")
                                            for b in group}:
            winners.extend(group)
            continue
        ranked = sorted(group, key=lambda b: (int(b.get("source_priority") or 0),
                                              str(b.get("driver_id"))))
        top = int(ranked[-1].get("source_priority") or 0)
        contenders = [b for b in ranked
                      if int(b.get("source_priority") or 0) == top]
        distinct = {b.get("source_ref") for b in contenders}
        if len(distinct) > 1 and not any(b.get("decision_ref")
                                         for b in contenders):
            names = ", ".join(f"{b.get('driver_id')}(priorita' "
                              f"{b.get('source_priority')})" for b in ranked)
            report.add_error(
                CODE_SOURCE_CONFLICT, ref=role,
                message=(f"due o piu' candidati per il ruolo {role!r} a "
                         f"priorita' PARI ({top}) e nessun DEC-* che risolva: "
                         f"{names}; la scelta implicita e' vietata"),
                expected="priorita' distinte oppure un decision_ref",
                actual=f"priorita' {top} su {len(distinct)} candidati")
            blocked = True
            winners.extend(contenders)
            continue
        winner = ranked[-1]
        winners.append(winner)
        for loser in ranked[:-1]:
            superseded.append({
                "winner": winner.get("driver_id"),
                "winner_priority": winner.get("source_priority"),
                "supersedes": loser.get("driver_id"),
                "superseded_priority": loser.get("source_priority"),
            })
    return winners, superseded, blocked


def apply_gates(doc, rows, overlay, profile, config, fingerprint, report):
    """Ogni gate PRECEDE il calcolo: il motore non parte su un input rotto."""
    blocking = False
    required = list(profile.get("required_driver_roles") or [])
    optional = list(profile.get("optional_driver_roles") or [])
    consumed = doc.get("consumed_by_engine")
    consumed = set(consumed) if isinstance(consumed, list) else \
        {binding.get("driver_id") for binding in rows}

    for binding in rows:
        driver_id = binding.get("driver_id")
        role = binding.get("role")
        record = overlay.get(binding.get("source_ref"))
        if record is None:
            report.add_error(
                CODE_UNRESOLVED_REQUIRED, ref=driver_id,
                message=(f"source_ref {binding.get('source_ref')!r} non "
                         "risolve in alcun record canonico: il motore consuma "
                         "binding GIA' risolti"),
                expected="un ASS-* risolvibile", actual="nessuno")
            blocking = True
            continue
        binding["_record"] = record

        current = fingerprint(record)
        if binding.get("source_record_hash") != current:
            report.add_error(
                CODE_SOURCE_STALE, ref=driver_id,
                message=(f"source_record_hash legato a "
                         f"{binding.get('source_ref')} divergente dal record "
                         "canonico corrente: il valore legato non e' piu' "
                         "quello del canonico. Il gate precede il "
                         "calcolo"),
                expected=current, actual=binding.get("source_record_hash"))
            report.add_check(CODE_SOURCE_STALE, "FAIL",
                             affected_refs=[driver_id], expected=current,
                             actual=binding.get("source_record_hash"))
            blocking = True
            continue
        report.add_check(CODE_SOURCE_STALE, "PASS", affected_refs=[driver_id],
                         message="impronta CAS coincidente col canonico")

        if binding.get("input_kind") == "informational" and \
                driver_id in consumed:
            report.add_error(
                CODE_INFORMATIONAL, ref=driver_id,
                message=(f"driver {driver_id} dichiarato input_kind "
                         "informational ed e' CONSUMATO dal motore: un input "
                         "editabile ma non operativo non e' mai consumato"),
                expected="input_kind operational o derived",
                actual="informational")
            blocking = True

        value = record_value(record)
        if value is None:
            report.add_error(
                CODE_UNRESOLVED_REQUIRED, ref=driver_id,
                message=(f"il record {binding.get('source_ref')} non porta "
                         "alcun valore: nessuno zero implicito e' sostituito"),
                expected="un valore canonico", actual="null")
            blocking = True
            continue
        binding["_resolved_value"] = value

        missing = provenance_defects(binding, record)
        status = binding.get("status")
        if missing:
            status = "unresolved"
            message = (f"provenienza incompleta su un driver non confirmed: "
                       f"campi mancanti {', '.join(missing)}; un benchmark "
                       "privo di evidenza o di data resta unresolved e non "
                       "puo' servire un ruolo richiesto")
            if role in required:
                report.add_error(
                    CODE_UNRESOLVED_REQUIRED, ref=driver_id, message=message,
                    expected="provenienza completa",
                    actual=f"assenti: {', '.join(missing)}")
                blocking = True
            else:
                report.add_warning(CODE_UNRESOLVED_REQUIRED, ref=driver_id,
                                   message=message)
        binding["_status"] = status if status in STATUS_ORDER else "unresolved"

        if status in ("unresolved", "placeholder"):
            if role in required and not missing:
                report.add_error(
                    CODE_UNRESOLVED_REQUIRED, ref=driver_id,
                    message=(f"record {binding.get('source_ref')} in stato "
                             f"{status!r} su ruolo RICHIESTO {role!r}: non e' "
                             "consumabile e promuoverlo e' vietato"),
                    expected="confirmed o inferred", actual=status)
                blocking = True
            elif role in optional and driver_id in consumed:
                report.add_warning(
                    CODE_PLACEHOLDER_OPTIONAL, ref=driver_id,
                    message=(f"record {binding.get('source_ref')} {status} su "
                             f"ruolo OPZIONALE {role!r} ed e' CONSUMATO: "
                             "valore usato e caveat PROPAGATO all'output, mai "
                             "riassorbito in un PASS"))
                report.add_check(CODE_PLACEHOLDER_OPTIONAL, "WARNING",
                                 affected_refs=[driver_id],
                                 message="placeholder su ruolo opzionale "
                                         "CONSUMATO: partecipa al minimo")

        measure = binding.get("measure_kind")
        if measure == "stock" or role == "headcount":
            if binding.get("start_period") is None or \
                    binding.get("end_period") is None:
                report.add_error(
                    CODE_PERIOD_UNDECLARED, ref=driver_id,
                    message=(f"driver {role!r} senza finestra DICHIARATA: "
                             f"start_period={binding.get('start_period')!r}, "
                             f"end_period={binding.get('end_period')!r}; "
                             "nessun parsing di etichette e' ammesso"),
                    expected="start_period ed end_period dichiarati",
                    actual="assenti")
                blocking = True
        # La politica di conversione e' verificata per OGNI natura
        # di misura contro il PROPRIO insieme permesso CHIUSO. Non verificarla
        # fuori da `rate` significa accettare qualunque stringa -- inclusa una
        # inventata -- ed emetterla verbatim nel `driver_registry`, cioe' in una
        # sezione che va validata per `$ref` contro lo schema. Le quattro
        # semantiche restano DISTINTE: `rate` COMPONE,
        # `per_unit` PRESERVA il valore unitario, `flow` RIPARTISCE secondo il
        # timing dichiarato, `stock` PORTA il livello.
        policy = binding.get("conversion_policy")
        permitted = BINDING_POLICY_BY_MEASURE.get(measure)
        if permitted is not None and policy not in permitted:
            if measure == "rate":
                report.add_error(
                    CODE_RATE_NOT_COMPOUNDED, ref=driver_id,
                    message=(f"driver {driver_id} di natura rate con "
                             f"conversion_policy {policy!r}: un tasso non si "
                             "ripartisce, si COMPONE. La "
                             "divisione lineare e' vietata"),
                    expected="compound", actual=policy)
            else:
                report.add_error(
                    CODE_CONVERSION_POLICY, ref=driver_id,
                    message=(f"driver {driver_id} di natura {measure!r} con "
                             f"conversion_policy {policy!r}: non e' derivabile "
                             "dalla classe di unita'. "
                             "L'insieme permesso per questa natura e' CHIUSO: "
                             "una politica valida per un'ALTRA natura non lo "
                             "soddisfa, e una stringa arbitraria nemmeno"),
                    expected=" | ".join(permitted), actual=policy)
            blocking = True

        category = binding.get("cost_category") or binding.get(
            "revenue_category")
        if category in FINANCING_CATEGORIES:
            report.add_error(
                CODE_FINANCING_IN_PNL, ref=driver_id,
                message=(f"la riga {driver_id} dichiara la categoria "
                         f"{category!r}: il P&L non contiene fonti "
                         "finanziarie e la riga e' ESCLUSA da ogni "
                         "modulo operativo e dalla cassa"),
                expected="una categoria operativa della tassonomia di fonti e usi",
                actual=category)
            binding["_financing"] = True

    opening_ref = doc.get("opening_cash_ref")
    opening_record = overlay.get(opening_ref) if opening_ref else None
    opening_value = record_value(opening_record) if opening_record else None
    if opening_value is None:
        report.add_error(
            CODE_UNRESOLVED_REQUIRED, ref=OPENING_BALANCE,
            message=(f"saldo di apertura non risolto: opening_cash_ref="
                     f"{opening_ref!r}; il piano di cassa non parte da uno "
                     "zero implicito"),
            expected="un ASS-* risolvibile", actual=repr(opening_ref))
        blocking = True
    else:
        for binding in rows:
            if binding.get("source_ref") != opening_ref:
                continue
            category = binding.get("cost_category") or binding.get(
                "revenue_category")
            if category in SOURCE_CATEGORIES:
                report.add_error(
                    CODE_OPENING_AS_SOURCE, ref=binding.get("driver_id"),
                    message=(f"il saldo di apertura {opening_ref} e' "
                             f"dichiarato fra le SOURCES dalla riga "
                             f"{binding.get('driver_id')}: e' un SALDO, non "
                             "una fonte del periodo"),
                    expected="il saldo di apertura fuori da SOURCES",
                    actual=category)
                blocking = True

    # `funding_gap` e `cash_buffer` non
    # compaiono nella tassonomia di fonti e usi perche' NON SONO ne' l'una ne'
    # l'altra: il gap e' un RESIDUO calcolato DALLA cassa, mai un ingresso
    # ALLA cassa. Una riga che li dichiari in una categoria di fonte (o di uso)
    # e' la violazione bloccante `funding_gap_as_source`.
    for binding in rows:
        klass = binding.get("driver_class") or binding.get("role")
        if klass not in ("cash_buffer", "funding_gap"):
            continue
        category = binding.get("revenue_category") or binding.get(
            "cost_category")
        if category is None:
            continue
        report.add_error(
            CODE_GAP_AS_SOURCE, ref=binding.get("driver_id"),
            message=(f"la riga {binding.get('driver_id')} dichiara un driver "
                     f"di classe {klass!r} nella categoria {category!r}: "
                     "funding_gap e cash_buffer non compaiono nella tassonomia "
                     "di fonti e usi perche' non sono ne' fonte ne' uso, e il "
                     "gap e' un RESIDUO"),
            expected="nessuna categoria di fonte o di uso",
            actual=category)
        report.add_check(CODE_GAP_AS_SOURCE, "FAIL",
                         affected_refs=[binding.get("driver_id")],
                         message="il fabbisogno non e' una fonte di cassa")
        blocking = True

    bound = {binding.get("role") for binding in rows}
    unbound = []
    for role in required:
        if role in bound:
            continue
        unbound.append(role)
        report.add_error(
            CODE_ROLE_UNBOUND, ref=role,
            message=(f"ruolo RICHIESTO dal profilo non legato: {role!r}; "
                     "nessun driver governato confirmed e nessuna assunzione "
                     "governata legata lo servono, e non esiste valore di "
                     "ripiego"),
            expected="un driver_binding governato per il ruolo",
            actual="nessuno")
        report.add_check(CODE_ROLE_UNBOUND, "FAIL", affected_refs=[role],
                         message=f"ruolo richiesto {role} non legato")
        blocking = True

    return blocking, unbound, opening_value, consumed


def check_derived_assumability(rows, report):
    """Un derivato e' un OUTPUT, mai un'assunzione."""
    offenders = []
    derived = [binding for binding in rows
               if binding.get("input_kind") == "derived" or
               (binding.get("_record") or {}).get("kind") == "derived"]
    for binding in derived:
        record = binding.get("_record") or {}
        derivation = record.get("derivation") or {}
        reasons = []
        if record.get("validation_required"):
            reasons.append("validation_required")
        if record.get("validation_status") == "needs_info":
            reasons.append("validation_status needs_info")
        if not derivation.get("variables"):
            reasons.append("derivation.variables assente")
        if reasons:
            sources = ", ".join(sorted(
                str(ref) for ref in (derivation.get("variables") or {}).values()))
            offenders.append((binding.get("driver_id"), reasons, sources))
    if offenders:
        for driver_id, reasons, sources in offenders:
            report.add_check(
                CHECK_DERIVED, "FAIL", affected_refs=[driver_id],
                message=(f"{driver_id}: valore derived marcato come "
                         f"assunzione editabile o validabile "
                         f"({', '.join(reasons)}); la sua derivation dipende "
                         f"da {sources or '(nessuna variabile)'} e si "
                         "RICALCOLA, non si valida a mano"))
        return
    report.add_check(
        CHECK_DERIVED, "PASS",
        affected_refs=[binding.get("driver_id") for binding in derived] or None,
        message=("nessun valore derived e' marcato come assunzione editabile "
                 f"({len(derived)} driver derived esaminati)"))


# --------------------------------------------------------------------------
# I moduli
# --------------------------------------------------------------------------


def by_role(rows, role):
    return [binding for binding in rows
            if binding.get("role") == role and not binding.get("_financing")]


# --------------------------------------------------------------------------
# Le QUATTRO misure di rischio di cassa, QUATTRO percorsi separati
# --------------------------------------------------------------------------


def runway_measure(ending, horizon, limit):
    """UN percorso di calcolo del runway, parametrizzato dalla PROPRIA soglia.

    Restituisce `(misura, periodo_di_prima_violazione)`.

    La MISURA e' SEMPRE un indice di periodo: l'ORIZZONTE quando la soglia non
    e' mai attraversata. Il PERIODO DI PRIMA VIOLAZIONE e' AUSILIARIO e NON
    ESISTE (`None`) quando la soglia non e' attraversata. E' precisamente
    questa differenza di DOMINIO a distinguere le due grandezze anche quando i
    loro valori coincidono, e a rendere rilevabile la sostituzione dell'una con
    l'altro.
    """
    for index in range(horizon):
        if ending[index] < limit:
            return index, index
    return horizon, None


def funding_gap_measure(worst, limit):
    """UN percorso di calcolo del fabbisogno, parametrizzato dalla PROPRIA
    soglia: `max(0, soglia - minimo di cassa)`, mai un avanzo col segno meno.
    """
    return max(ZERO, limit - worst)


def cash_measure_paths(ending, horizon, threshold):
    """I QUATTRO percorsi, ciascuno invocato con la SOLA soglia che gli compete.

    `runway_to_*` nascono dalla SERIE, `funding_gap_to_*` dal suo MINIMO;
    `*_to_zero` dalla soglia ZERO, `*_to_buffer` dalla soglia di BUFFER. Nessun
    percorso e' riusato per due misure, e nessuna misura e' derivata da un'altra.
    """
    zero_runway, below_zero = runway_measure(ending, horizon, ZERO)
    worst = min(ending) if ending else ZERO
    paths = {
        "runway_to_zero": zero_runway,
        "funding_gap_to_zero": funding_gap_measure(worst, ZERO),
        "first_period_below_zero": below_zero,
    }
    if threshold is None:
        paths["runway_to_buffer"] = None
        paths["funding_gap_to_buffer"] = None
        paths["first_period_below_buffer"] = None
    else:
        buffer_runway, below_buffer = runway_measure(ending, horizon, threshold)
        paths["runway_to_buffer"] = buffer_runway
        paths["funding_gap_to_buffer"] = funding_gap_measure(worst, threshold)
        paths["first_period_below_buffer"] = below_buffer
    return paths


def check_cash_measures(runway_metrics, gap_metrics, paths, horizon, threshold,
                        report):
    """Le QUATTRO misure di cassa non si COLLASSANO (`cash_metrics_collapsed`).

    Il collasso NON e' l'uguaglianza dei VALORI. Due misure calcolate da soglie
    DIVERSE coincidono in casi perfettamente legittimi: quando NESSUNA soglia e'
    attraversata entrambe le misure di runway valgono l'ORIZZONTE; quando zero e
    buffer sono attraversati nello STESSO periodo entrambe valgono quell'indice;
    e due riassunti di fabbisogno possono coincidere su una fixture valida.
    Trattare quell'uguaglianza come prova di collasso respinge un piano
    solvibile e integralmente riconciliato, affermando il contrario di cio' che
    l'output stesso mostra.

    Cio' che questo controllo rileva e' STRUTTURALE:

    1  ogni misura EMESSA coincide con quella prodotta dal PROPRIO percorso di
       calcolo, cioe' dalla PROPRIA soglia. Una misura SOSTITUITA, ALIASSATA o
       DERIVATA dalla definizione sbagliata non vi coincide;
    2  ogni misura di runway e' un INDICE DI PERIODO in `[0, orizzonte]`. Un
       periodo di prima violazione -- AUSILIARIO, e `NOT_APPLICABLE` quando la
       soglia non e' attraversata -- usato COME misura viola il dominio;
    3  senza policy di buffer le due misure di buffer sono `NOT_APPLICABLE`
       DICHIARATO, mai uno zero implicito e mai una copia di quelle di zero.
    """
    offenders = []

    def runway_slot(key, applicable):
        emitted = runway_metrics.get(key)
        if not applicable:
            if emitted != "NOT_APPLICABLE":
                offenders.append(
                    (key, "'NOT_APPLICABLE' DICHIARATO senza policy di buffer",
                     repr(emitted)))
            return
        if isinstance(emitted, bool) or not isinstance(emitted, int):
            offenders.append(
                (key, f"un INDICE DI PERIODO in [0, {horizon}]", repr(emitted)))
        elif emitted < 0 or emitted > horizon:
            offenders.append(
                (key, f"un INDICE DI PERIODO in [0, {horizon}]", repr(emitted)))
        elif emitted != paths[key]:
            offenders.append((key, str(paths[key]), repr(emitted)))

    def gap_slot(key, applicable):
        emitted = gap_metrics.get(key)
        if not applicable:
            if emitted != "NOT_APPLICABLE":
                offenders.append(
                    (key, "'NOT_APPLICABLE' DICHIARATO senza policy di buffer",
                     repr(emitted)))
            return
        expected = amount(paths[key])
        if emitted != expected:
            offenders.append((key, expected, repr(emitted)))

    runway_slot("runway_to_zero", True)
    runway_slot("runway_to_buffer", threshold is not None)
    gap_slot("funding_gap_to_zero", True)
    gap_slot("funding_gap_to_buffer", threshold is not None)

    if not offenders:
        report.add_check(
            CODE_CASH_COLLAPSED, "PASS",
            affected_refs=["runway", "funding_gap"],
            message=("le quattro misure di cassa provengono da QUATTRO percorsi "
                     "di calcolo distinti, ciascuno dalla propria soglia; "
                     "l'eventuale coincidenza dei valori e' un fatto del piano, "
                     "non un collasso"))
        return
    detail = "; ".join(f"{key}: atteso {expected}, emesso {observed}"
                       for key, expected, observed in offenders)
    report.add_error(
        CODE_CASH_COLLAPSED, ref="runway",
        message=(f"le quattro metriche di cassa si collassano: {detail}. "
                 "Una misura SOSTITUITA, ALIASSATA o derivata dalla "
                 "definizione sbagliata non coincide col proprio percorso di "
                 "calcolo. L'uguaglianza NUMERICA di due misure "
                 "distinte non e' un collasso e non e' misurata qui"),
        expected="ogni misura dal PROPRIO percorso di calcolo",
        actual=", ".join(key for key, _, _ in offenders))


def line_of(binding, values, prefix):
    line = {
        "line_id": f"{prefix}-{binding.get('driver_id')}",
        "driver_refs": [binding.get("driver_id")],
        "series": series_map(values),
    }
    category = binding.get("cost_category") or binding.get("revenue_category")
    if category is not None:
        line["category"] = category
    return line


def module_result(module_id, status, series=None, lines=None, metrics=None,
                  refs=None, reason=None, notes=None):
    entry = {"module_id": module_id, "status": status}
    if reason is not None:
        entry["not_applicable_reason"] = reason
    if refs:
        entry["input_driver_refs"] = sorted(set(refs))
    if series is not None:
        entry["series"] = series_map(series)
    if lines:
        entry["lines"] = lines
    if metrics:
        entry["metrics"] = metrics
    if notes is not None:
        entry["notes"] = notes
    return entry


def compute(rows, calendar_block, fractions, months, opening_value, config,
            report):
    """La catena deterministica dei moduli, in ordine causale."""
    horizon = calendar_block["horizon_periods"]
    modules = {}
    conversions = []
    detail = {}

    # ---- risoluzione delle serie per driver -------------------------------
    quota = {}
    levels = {}
    rates = {}
    unexplained = {}
    for binding in rows:
        if binding.get("_financing"):
            continue
        measure = binding.get("measure_kind")
        if measure == "flow":
            weights, total = flow_weights(binding, horizon, fractions)
            quota[binding["driver_id"]] = (weights, total)
        elif measure == "stock":
            series, events, uncovered = stock_levels(binding, horizon)
            levels[binding["driver_id"]] = series
            unexplained[binding["driver_id"]] = uncovered
            del events
        elif measure == "rate":
            values, full = rate_series(binding, horizon, fractions, months)
            rates[binding["driver_id"]] = values
            conversions.append({
                "driver_id": binding["driver_id"],
                "conversion_policy": emitted_conversion_policy(
                    binding.get("conversion_policy")),
                "formula": "r_p = 1 - (1 - r_a) ** (p / a)",
                "from_frequency": binding.get("frequency"),
                "to_frequency": calendar_block["frequency"],
                "parameters": {"period_rate": amount(full),
                               "annual_rate": amount(binding["_resolved_value"])},
            })

    # ---- calendar ----------------------------------------------------------
    calendar_refs = [entry["driver_id"] for entry in conversions]
    if conversions:
        calendar_block["conversions_applied"] = conversions
    modules["calendar"] = module_result(
        "calendar", "PASS", refs=calendar_refs,
        metrics={"horizon_periods": horizon,
                 "partial_first_period":
                     amount(fractions[0]) if fractions else amount(ZERO)},
        notes="periodi, quote giornaliere e conversioni applicate")

    # ---- revenue -----------------------------------------------------------
    price_rows = by_role(rows, "unit_price")
    volume_rows = by_role(rows, "customer_volume")
    churn_rows = by_role(rows, "churn_rate")
    conversion_rows = by_role(rows, "conversion_rate")
    price = price_rows[0]["_resolved_value"] if price_rows else ZERO
    survival = []
    with localcontext() as local:
        local.prec = CALCULATION_PRECISION
        running = ONE
        for index in range(horizon):
            for binding in churn_rows:
                running *= (ONE - rates[binding["driver_id"]][index])
            survival.append(running)

    def conversion_factor(index):
        factor = ONE
        for binding in conversion_rows:
            factor *= rates[binding["driver_id"]][index]
        return factor

    active = [ZERO] * horizon
    revenue_lines = []
    revenue_total = [ZERO] * horizon
    revenue_detail = [ZERO] * horizon
    for binding in volume_rows:
        values = []
        for index in range(horizon):
            values.append(levels[binding["driver_id"]][index] *
                          survival[index] * conversion_factor(index))
        for index in range(horizon):
            active[index] += values[index]
        contribution = [values[index] * price for index in range(horizon)]
        line = line_of(binding, contribution, "REVENUE")
        revenue_lines.append(line)
        for index in range(horizon):
            revenue_total[index] += contribution[index]
            if line.get("category") in SOURCE_CATEGORIES:
                revenue_detail[index] += contribution[index]
    revenue_refs = [b["driver_id"] for b in price_rows + volume_rows +
                    churn_rows + conversion_rows]
    modules["revenue"] = module_result(
        "revenue", "PASS", series=revenue_total, lines=revenue_lines,
        refs=revenue_refs,
        notes=("subscription_recurring: active(t) = livello di volume(t) x "
               "sopravvivenza(t) x fattore di conversione(t); ricavo(t) = "
               "active(t) x prezzo unitario. La sopravvivenza consuma il "
               "tasso COMPOSTO del periodo; il fattore di conversione esiste "
               "SOLO se un driver governato conversion_rate e' legato"))
    detail["revenue"] = (revenue_detail, revenue_total, revenue_lines)

    # ---- cogs --------------------------------------------------------------
    cost_rows = by_role(rows, "variable_cost")
    cogs_lines = []
    cogs_total = [ZERO] * horizon
    cogs_detail = [ZERO] * horizon
    for binding in cost_rows:
        contribution = [active[index] * binding["_resolved_value"]
                        for index in range(horizon)]
        line = line_of(binding, contribution, "COGS")
        cogs_lines.append(line)
        for index in range(horizon):
            cogs_total[index] += contribution[index]
            if line.get("category") in USE_CATEGORIES:
                cogs_detail[index] += contribution[index]
    modules["cogs"] = module_result(
        "cogs", "PASS", series=cogs_total, lines=cogs_lines,
        refs=[b["driver_id"] for b in cost_rows + volume_rows],
        notes="cogs(t) = active(t) x Sigma dei costi variabili unitari legati")
    detail["cogs"] = (cogs_detail, cogs_total, cogs_lines)

    # ---- gross_margin ------------------------------------------------------
    margin = [revenue_total[index] - cogs_total[index]
              for index in range(horizon)]
    modules["gross_margin"] = module_result(
        "gross_margin", "PASS", series=margin,
        refs=revenue_refs + [b["driver_id"] for b in cost_rows],
        notes="gross_margin(t) = revenue(t) - cogs(t)")

    # ---- headcount ---------------------------------------------------------
    headcount_rows = by_role(rows, "headcount")
    headcount_total = [ZERO] * horizon
    for binding in headcount_rows:
        for index in range(horizon):
            headcount_total[index] += levels[binding["driver_id"]][index]
    modules["headcount"] = module_result(
        "headcount", "PASS", series=headcount_total,
        refs=[b["driver_id"] for b in headcount_rows],
        notes=("FTE come LIVELLO sulla finestra DICHIARATA "
               "[start_period, end_period], zero fuori: nessuna ripartizione "
               "e nessun parsing di etichette"))

    # ---- payroll -----------------------------------------------------------
    payroll_rows = by_role(rows, "payroll_unit_cost")
    unit_cost = payroll_rows[0]["_resolved_value"] if payroll_rows else ZERO
    payroll_lines = []
    payroll_total = [ZERO] * horizon
    payroll_detail = [ZERO] * horizon
    for binding in headcount_rows:
        contribution = [levels[binding["driver_id"]][index] * unit_cost
                        for index in range(horizon)]
        line = line_of(binding, contribution, "PAYROLL")
        payroll_lines.append(line)
        for index in range(horizon):
            payroll_total[index] += contribution[index]
            if line.get("category") in USE_CATEGORIES:
                payroll_detail[index] += contribution[index]
    modules["payroll"] = module_result(
        "payroll", "PASS", series=payroll_total, lines=payroll_lines,
        refs=[b["driver_id"] for b in headcount_rows + payroll_rows],
        notes="payroll(t) = Sigma (FTE del ruolo(t) x costo unitario)")
    detail["payroll"] = (payroll_detail, payroll_total, payroll_lines)

    # ---- opex --------------------------------------------------------------
    opex_rows = by_role(rows, "opex")
    opex_lines = []
    opex_total = [ZERO] * horizon
    opex_detail = [ZERO] * horizon
    opex_by_category = {}
    for binding in opex_rows:
        weights = quota[binding["driver_id"]][0]
        contribution = [binding["_resolved_value"] * weights[index]
                        for index in range(horizon)]
        line = line_of(binding, contribution, "OPEX")
        opex_lines.append(line)
        key = line.get("category") or UNCATEGORISED
        bucket = opex_by_category.setdefault(key, [ZERO] * horizon)
        for index in range(horizon):
            opex_total[index] += contribution[index]
            bucket[index] += contribution[index]
            if line.get("category") in USE_CATEGORIES:
                opex_detail[index] += contribution[index]
    modules["opex"] = module_result(
        "opex", "PASS", series=opex_total, lines=opex_lines,
        refs=[b["driver_id"] for b in opex_rows],
        notes=("opex(t) = Sigma (valore del driver x quota della timing_rule); "
               "ogni riga porta la propria categoria di costo"))
    detail["opex"] = (opex_detail, opex_total, opex_lines)

    # ---- pnl ---------------------------------------------------------------
    pnl_lines = [line for line in revenue_lines + cogs_lines + payroll_lines +
                 opex_lines if line.get("category") not in FINANCING_CATEGORIES]
    operating_cost = [ZERO] * horizon
    for line in pnl_lines:
        if line.get("category") != "operating_cost":
            continue
        for index in range(horizon):
            operating_cost[index] += Decimal(line["series"][str(index)])
    ebitda = [revenue_total[index] - cogs_total[index] - payroll_total[index] -
              opex_by_category.get("operating_cost", [ZERO] * horizon)[index]
              for index in range(horizon)]
    pnl_metrics = {}
    for index in range(horizon):
        pnl_metrics[f"ebitda_{index}"] = amount(ebitda[index])
        pnl_metrics[f"gross_margin_{index}"] = amount(margin[index])
    modules["pnl"] = module_result(
        "pnl", "PASS", series=ebitda, lines=pnl_lines, metrics=pnl_metrics,
        refs=revenue_refs + [b["driver_id"] for b in cost_rows +
                             headcount_rows + payroll_rows + opex_rows],
        notes=("P&L SEMPLIFICATO: ricavi -> margine lordo -> EBITDA. Nessuna "
               "fonte finanziaria vi entra"))

    # ---- cash_flow ---------------------------------------------------------
    source_total = [ZERO] * horizon
    use_total = [ZERO] * horizon
    for line in pnl_lines:
        category = line.get("category")
        for index in range(horizon):
            value = Decimal(line["series"][str(index)])
            if category in SOURCE_CATEGORIES:
                source_total[index] += value
            elif category in USE_CATEGORIES:
                use_total[index] += value
    # INVARIANTE STRUTTURALE: il cash-in e' ESATTAMENTE la somma delle righe di
    # fonte dichiarate. Il saldo di apertura non vi entra: e' il
    # punto da cui il piano di cassa PARTE.
    cash_in = list(source_total)
    cash_out = list(use_total)
    opening = [ZERO] * horizon
    ending = [ZERO] * horizon
    burn = [ZERO] * horizon
    balance = opening_value
    for index in range(horizon):
        opening[index] = balance
        balance = balance + revenue_total[index] - cogs_total[index] - \
            payroll_total[index] - opex_total[index]
        ending[index] = balance
        burn[index] = cogs_total[index] + payroll_total[index] + \
            opex_total[index] - revenue_total[index]
    for index in range(horizon):
        if cash_in[index] != source_total[index]:
            report.add_error(
                CODE_OPENING_AS_SOURCE, ref=OPENING_BALANCE,
                message=(f"periodo {index}: il cash-in {cash_in[index]} non "
                         f"coincide con la somma delle righe di fonte "
                         f"{source_total[index]}: una grandezza estranea -- il "
                         "saldo di apertura -- e' entrata fra le SOURCES"),
                expected=amount(source_total[index]),
                actual=amount(cash_in[index]))
            break
    cash_metrics = {}
    for index in range(horizon):
        cash_metrics[f"opening_{index}"] = amount(opening[index])
        cash_metrics[f"cash_in_{index}"] = amount(cash_in[index])
        cash_metrics[f"cash_out_{index}"] = amount(cash_out[index])
        cash_metrics[f"ending_{index}"] = amount(ending[index])
        cash_metrics[f"burn_{index}"] = amount(burn[index])
    modules["cash_flow"] = module_result(
        "cash_flow", "PASS", series=ending, metrics=cash_metrics,
        refs=modules["pnl"]["input_driver_refs"],
        notes=("roll-forward completo: opening + cash_in - cash_out = ending "
               "per ogni periodo; il saldo di apertura e' un SALDO, mai una "
               "fonte"))
    detail["cash"] = (opening, cash_in, cash_out, ending)

    # ---- runway e cash_buffer ---------------------------------------------
    policy = config.get("cash_buffer_policy")
    threshold = None
    if isinstance(policy, dict):
        declared = Decimal(str(policy.get("value")))
        if policy.get("kind") == "months_of_burn":
            positive = [value for value in burn if value > ZERO]
            average = (sum(positive, ZERO) / Decimal(len(positive))
                       if positive else ZERO)
            threshold = declared * average
        else:
            threshold = declared

    # Le QUATTRO misure nascono QUI, ciascuna dal proprio percorso e
    # dalla propria soglia, e sono confrontate DOPO con cio' che i due moduli
    # emettono. I due periodi di prima violazione restano AUSILIARI e non
    # sostituiscono alcuna misura.
    paths = cash_measure_paths(ending, horizon, threshold)
    below_zero = paths["first_period_below_zero"]
    below_buffer = paths["first_period_below_buffer"]
    runway_metrics = {
        "runway_to_zero": paths["runway_to_zero"],
        "first_period_below_zero": (below_zero if below_zero is not None
                                    else "NOT_APPLICABLE"),
    }
    if threshold is None:
        runway_metrics["runway_to_buffer"] = "NOT_APPLICABLE"
        runway_metrics["first_period_below_buffer"] = "NOT_APPLICABLE"
    else:
        runway_metrics["runway_to_buffer"] = paths["runway_to_buffer"]
        runway_metrics["first_period_below_buffer"] = (
            below_buffer if below_buffer is not None else "NOT_APPLICABLE")
    # I due riassunti SCALARI del fabbisogno nascono dallo stesso
    # insieme di percorsi, cosi' che la loro provenienza sia verificabile con la
    # stessa disciplina delle due misure di runway.
    gap_metrics = {"funding_gap_to_zero": amount(paths["funding_gap_to_zero"])}
    if threshold is None:
        gap_metrics["funding_gap_to_buffer"] = "NOT_APPLICABLE"
    else:
        gap_metrics["funding_gap_to_buffer"] = amount(
            paths["funding_gap_to_buffer"])
    check_cash_measures(runway_metrics, gap_metrics, paths, horizon, threshold,
                        report)
    modules["runway"] = module_result(
        "runway", "PASS", metrics=runway_metrics,
        refs=modules["cash_flow"]["input_driver_refs"],
        notes=("runway_to_zero e runway_to_buffer restano DUE grandezze "
               "distinte, ciascuna col proprio periodo di prima violazione; "
               "funding_gap_to_zero e funding_gap_to_buffer "
               "appartengono al modulo funding_gap"))

    if threshold is None:
        modules["cash_buffer"] = module_result(
            "cash_buffer", "NOT_APPLICABLE",
            reason=("cash_buffer_policy non dichiarata in financial_config: "
                    "la soglia NON e' zero, e' non applicabile"),
            notes="omissione DICHIARATA e VISIBILE, mai silenziosa")
    else:
        violations = []
        buffer_metrics = {"threshold": amount(threshold)}
        for index in range(horizon):
            if ending[index] < threshold:
                violations.append({
                    "line_id": f"BUFFER-{index}",
                    "category": "operating_cost",
                    "series": {str(index): amount(threshold - ending[index])},
                })
        if violations:
            buffer_metrics["first_violation_period"] = below_buffer
            buffer_metrics["first_violation_shortfall"] = amount(
                threshold - ending[below_buffer])
        else:
            buffer_metrics["first_violation_period"] = "NOT_APPLICABLE"
            buffer_metrics["first_violation_shortfall"] = "NOT_APPLICABLE"
        modules["cash_buffer"] = module_result(
            "cash_buffer", "WARNING" if violations else "PASS",
            lines=violations or None, metrics=buffer_metrics,
            refs=modules["cash_flow"]["input_driver_refs"],
            notes="soglia di buffer e violazioni con PERIODO ed ENTITA'")

    # ---- break_even --------------------------------------------------------
    # I costi fissi del periodo sono payroll + opex; il margine unitario e'
    # prezzo - Sigma dei costi variabili unitari legati. Il PERIODO DI
    # RIFERIMENTO dello scalare di pareggio e' il PRIMO: lo schema
    # porta `break_even_volume` e `break_even_revenue` come grandezze SINGOLE,
    # mentre `fixed_costs_per_period` resta il PROFILO completo.
    unit_variable = ZERO
    for binding in cost_rows:
        unit_variable += binding["_resolved_value"]
    unit_margin = price - unit_variable
    fixed_costs = [payroll_total[index] + opex_total[index]
                   for index in range(horizon)]
    # I costi fissi CATEGORIZZATI: un importo che nessuna categoria della
    # tassonomia dichiara NON e' un costo fisso attribuibile, ed e' esattamente
    # il residuo che `REC-15` misura.
    fixed_categorised = [payroll_detail[index] +
                         opex_by_category.get("operating_cost",
                                              [ZERO] * horizon)[index]
                         for index in range(horizon)]
    break_even_refs = sorted({b["driver_id"] for b in
                              price_rows + cost_rows + headcount_rows +
                              payroll_rows + opex_rows})
    pre_revenue = not price_rows or not volume_rows
    if pre_revenue or unit_margin <= ZERO:
        reason = ("profilo pre-revenue: nessun prezzo o nessun volume legato"
                  if pre_revenue else
                  "margine unitario non positivo: nessun livello di ricavo "
                  "copre i costi fissi, e il pareggio NON e' raggiungibile")
        modules["break_even"] = {
            "module_id": "break_even", "status": "NOT_APPLICABLE",
            "not_applicable_reason": (reason + ". L'esito e' "
                                      "DICHIARATO, mai un'omissione"),
            "outcome": "NOT_REACHABLE",
            "unit_margin": amount(unit_margin),
            "fixed_costs_per_period": series_map(fixed_costs),
            "input_driver_refs": break_even_refs,
        }
        break_even_detail = None
    else:
        with localcontext() as local:
            local.prec = CALCULATION_PRECISION
            reference_volume = fixed_costs[0] / unit_margin
            reference_revenue = reference_volume * price
        first_period = None
        for index in range(horizon):
            if margin[index] >= fixed_costs[index]:
                first_period = index
                break
        modules["break_even"] = {
            "module_id": "break_even",
            "status": "PASS" if first_period is not None else "WARNING",
            "outcome": "REACHED" if first_period is not None else "NOT_REACHED",
            "break_even_volume": amount(reference_volume),
            "break_even_revenue": amount(reference_revenue),
            "first_break_even_period": first_period,
            "unit_margin": amount(unit_margin),
            "fixed_costs_per_period": series_map(fixed_costs),
            "input_driver_refs": break_even_refs,
        }
        if first_period is None:
            modules["break_even"]["not_applicable_reason"] = (
                "il margine lordo del periodo non raggiunge i costi fissi "
                "entro l'orizzonte dichiarato: il pareggio e' NOT_REACHED, "
                "non un primo periodo positivo")
        break_even_detail = (reference_revenue, unit_margin, price,
                             fixed_categorised[0], break_even_refs)
    detail["break_even"] = break_even_detail

    # ---- funding_gap -------------------------------------------------------
    # `financial_need` e' il PROFILO TEMPORALE del fabbisogno residuo -- la
    # serie, per periodo, di quanto manca per non violare la policy di cassa.
    # `funding_gap_to_zero` e `funding_gap_to_buffer` ne sono i due RIASSUNTI
    # SCALARI. Il gap e' `max(0, ...)`: mai un avanzo col segno meno.
    policy_limit = threshold if threshold is not None else ZERO
    financial_need = [funding_gap_measure(ending[index], policy_limit)
                      for index in range(horizon)]
    # `gap_metrics` e' gia' stato prodotto dai percorsi di cassa insieme
    # alle due misure di runway, e verificato dalla stessa guardia strutturale.
    # `funding_gap` non e' ne' fonte ne' uso: non emette righe
    # categorizzate, e nessuna sua grandezza entra nel cash-in.
    modules["funding_gap"] = module_result(
        "funding_gap", "PASS", series=financial_need, metrics=gap_metrics,
        refs=modules["cash_flow"]["input_driver_refs"],
        notes=("financial_need e' il PROFILO TEMPORALE del fabbisogno residuo; "
               "funding_gap_to_zero e funding_gap_to_buffer ne "
               "sono i due riassunti SCALARI. Il gap e' un RESIDUO, mai una "
               "fonte"))

    # ---- kpi ---------------------------------------------------------------
    # Il modulo esiste SEMPRE: e' il suo CONTENUTO a ridursi quando i driver
    # mancano. Un KPI non calcolabile e' NOT_APPLICABLE con il ruolo mancante
    # NOMINATO, mai omesso: un indicatore assente si legge «non pertinente»
    # mentre la verita' e' «non abbiamo il dato».
    indicators = {}

    def missing_for(kpi_id):
        """I ruoli GENUINAMENTE ASSENTI dall'insieme di dipendenza del KPI.

        Il nome e' scelto per ASSENZA dall'insieme di dipendenza PROPRIO
        dell'indicatore, mai per posizione: un ruolo LEGATO e CONSUMATO nello
        stesso payload NON compare qui -- nemmeno quando il suo VALORE rende
        l'indicatore indefinito. Un ruolo legato ma INUTILIZZABILE non e' un
        ruolo MANCANTE: il dato c'e', ed e' il suo valore a non servire.
        Quel fatto diverso vive su `notes`, non qui.
        """
        return sorted({role for role in KPI_DRIVER_ROLES.get(kpi_id) or ()
                       if not by_role(rows, role)})

    def bound_driver_ids(bindings):
        """Gli ID dei driver che LEGANO un ruolo, per l'attribuzione."""
        return ", ".join(sorted(entry["driver_id"] for entry in bindings))

    def unusable_note(kpi_id, unusable):
        """Spiegazione TIPIZZATA dei ruoli LEGATI ma INUTILIZZABILI.

        Il campo `missing_driver_roles` significa ASSENZA: riempirlo di ruoli
        PRESENTI direbbe al lettore a valle «non abbiamo il dato», che e'
        falso, e in un indicatore che ha ANCHE un ruolo davvero assente i due
        casi diventerebbero INDISTINGUIBILI dentro la stessa lista. La
        distinzione vive percio' sul campo TIPIZZATO `notes`, gia' dichiarato
        da `#/$defs/kpi_indicator` e gia' usato per `break_even_period`:
        nessun campo di schema e' inventato.

        Ogni voce NOMINA il ruolo, il driver che lo lega, la CONDIZIONE di
        inutilizzabilita' OSSERVATA e la ragione per cui il KPI non e'
        calcolabile.
        """
        if not unusable:
            return None
        parts = [
            (f"ruolo '{role}' LEGATO al driver {driver_ids} e CONSUMATO in "
             f"questo payload, ma INUTILIZZABILE per {kpi_id}: {condition}; "
             f"{consequence}")
            for role, driver_ids, condition, consequence in unusable]
        return ("ruoli LEGATI ma INUTILIZZABILI, che NON sono ruoli MANCANTI e "
                "quindi NON compaiono in missing_driver_roles -- il quale "
                f"nomina soltanto i ruoli ASSENTI: {' | '.join(parts)}. "
                f"L'indicatore {kpi_id} e' NOT_APPLICABLE per questa ragione, "
                "non per un input mancante")

    def indicator(kpi_id, unit, value=None, series=None, sources=(),
                  missing=(), reason=None):
        entry = {"kpi_id": kpi_id}
        if missing or reason is not None:
            # Un indicatore non calcolabile e' NOT_APPLICABLE. Quando la ragione
            # NON e' un input mancante -- il pareggio non raggiunto entro
            # l'orizzonte, un modulo che il motore non calcola --
            # l'elenco dei ruoli e' VUOTO e la ragione e' DICHIARATA: inventare
            # un ruolo mancante sopprimerebbe la ragione vera e contraddirebbe
            # il modulo che la porta nello STESSO payload.
            entry["status"] = "NOT_APPLICABLE"
            entry["missing_driver_roles"] = sorted(set(missing))
            entry["unit"] = unit
            if reason is not None:
                entry["notes"] = reason
            return entry
        entry["status"] = "PASS"
        entry["unit"] = unit
        if value is not None:
            entry["value"] = amount(value)
        if series is not None:
            entry["series"] = series_map(series)
        entry["recomputable_from"] = sorted(set(sources))
        return entry

    margin_pct = []
    for index in range(horizon):
        if revenue_total[index] == ZERO:
            margin_pct.append(ZERO)
        else:
            with localcontext() as local:
                local.prec = CALCULATION_PRECISION
                margin_pct.append(margin[index] / revenue_total[index])
    indicators["gross_margin_pct"] = (
        indicator("gross_margin_pct", "ratio", series=margin_pct,
                  sources=("results.modules.revenue.series",
                           "results.modules.gross_margin.series"))
        if price_rows and volume_rows else
        indicator("gross_margin_pct", "ratio",
                  missing=missing_for("gross_margin_pct")))
    indicators["monthly_burn"] = indicator(
        "monthly_burn", financial_currency(config), series=burn,
        sources=("results.modules.cash_flow.metrics",))
    indicators["runway"] = indicator(
        "runway", "count", value=Decimal(runway_metrics["runway_to_zero"]),
        sources=("results.modules.runway.metrics",))
    # `cac` non ha ruolo nel profilo attivo: nessun driver lo puo' servire.
    cac_rows = by_role(rows, "cac")
    if cac_rows:
        cac_value = cac_rows[0]["_resolved_value"]
        indicators["cac"] = indicator(
            "cac", financial_currency(config), value=cac_value,
            sources=("driver_registry.drivers",))
    else:
        indicators["cac"] = indicator("cac", financial_currency(config),
                                      missing=missing_for("cac"))
    # `ltv` = prezzo unitario x margine percentuale / churn del periodo. Un
    # churn LEGATO col valore zero non e' un ruolo MANCANTE: e' un ruolo
    # INUTILIZZABILE per questo indicatore, perche' la vita media diverge.
    churn_first = ZERO
    for binding in churn_rows:
        churn_first += rates[binding["driver_id"]][0]
    ltv_unusable = []
    if churn_rows and churn_first <= ZERO:
        ltv_unusable.append((
            "churn_rate", bound_driver_ids(churn_rows),
            f"tasso di churn OSSERVATO al periodo 0 = {churn_first}",
            "la vita media 1/churn e' indefinita o divergente, quindi LTV non "
            "e' calcolabile"))
    if volume_rows and revenue_total and revenue_total[0] == ZERO:
        ltv_unusable.append((
            "customer_volume", bound_driver_ids(volume_rows),
            "ricavo OSSERVATO al periodo 0 = 0",
            "il margine percentuale non e' definito su un ricavo nullo, "
            "quindi LTV non e' calcolabile"))
    if price_rows and churn_rows and churn_first > ZERO and \
            revenue_total and revenue_total[0] != ZERO:
        with localcontext() as local:
            local.prec = CALCULATION_PRECISION
            ltv_value = price * margin_pct[0] / churn_first
        indicators["ltv"] = indicator(
            "ltv", financial_currency(config), value=ltv_value,
            sources=("driver_registry.drivers",
                     "results.modules.gross_margin.series"))
    else:
        ltv_value = None
        indicators["ltv"] = indicator(
            "ltv", financial_currency(config), missing=missing_for("ltv"),
            reason=unusable_note("ltv", ltv_unusable))
    cac_unusable = list(ltv_unusable)
    if cac_rows and cac_rows[0]["_resolved_value"] <= ZERO:
        cac_unusable.append((
            "cac", bound_driver_ids(cac_rows),
            f"CAC OSSERVATO = {cac_rows[0]['_resolved_value']}",
            "il rapporto LTV/CAC e' indefinito con un CAC non positivo"))
    if ltv_value is not None and cac_rows and cac_rows[0]["_resolved_value"] \
            > ZERO:
        with localcontext() as local:
            local.prec = CALCULATION_PRECISION
            indicators["ltv_cac_ratio"] = indicator(
                "ltv_cac_ratio", "ratio",
                value=ltv_value / cac_rows[0]["_resolved_value"],
                sources=("results.modules.kpi.indicators.ltv",
                         "results.modules.kpi.indicators.cac"))
    else:
        # Caso MISTO: un ruolo genuinamente ASSENTE (`cac` non legato) e un
        # ruolo LEGATO ma inutilizzabile (`churn_rate` a zero) possono
        # coesistere. Restano DISTINGUIBILI perche' vivono su due portatori
        # diversi: la lista dei MANCANTI e la nota TIPIZZATA.
        indicators["ltv_cac_ratio"] = indicator(
            "ltv_cac_ratio", "ratio", missing=missing_for("ltv_cac_ratio"),
            reason=unusable_note("ltv_cac_ratio", cac_unusable))
    outcome = modules["break_even"].get("outcome")
    if outcome == "REACHED":
        indicators["break_even_period"] = indicator(
            "break_even_period", "count",
            value=Decimal(modules["break_even"]["first_break_even_period"]),
            sources=("results.modules.break_even",))
    else:
        # Il pareggio NON RAGGIUNTO entro l'orizzonte, o NON RAGGIUNGIBILE, e'
        # una ragione FINANZIARIA, non un input mancante. Se ogni dipendenza e'
        # legata, l'elenco dei ruoli resta VUOTO e la ragione e' quella che il
        # modulo `break_even` dichiara nello STESSO payload: i due blocchi non
        # si contraddicono piu'.
        missing_break_even = missing_for("break_even_period")
        indicators["break_even_period"] = indicator(
            "break_even_period", "count", missing=missing_break_even,
            reason=None if missing_break_even else
            (f"break_even.outcome = {outcome}: il pareggio non e' disponibile "
             "per una ragione FINANZIARIA dichiarata da "
             "results.modules.break_even, non per un input mancante; ogni "
             "ruolo di dipendenza dell'indicatore e' LEGATO e CONSUMATO"))
    # Il modulo `milestone_coverage` NON e' calcolato dal motore (nel
    # canonico lo pubblica il costruttore come NOT_APPLICABLE). Quando il ruolo
    # non e' legato la ragione e' il ruolo mancante; quando lo fosse, la
    # ragione resta il modulo non calcolato e non un input inventato.
    missing_milestone = missing_for("milestone_coverage")
    indicators["milestone_coverage"] = indicator(
        "milestone_coverage", "ratio", missing=missing_milestone,
        reason=None if missing_milestone else
        ("il modulo milestone_coverage NON e' prodotto dal motore "
         "finanziario: l'indicatore non e' calcolabile per confine di "
         "modulo, non per un input mancante"))
    modules["kpi"] = {
        "module_id": "kpi",
        "status": "PASS",
        "indicators": {kpi_id: indicators[kpi_id] for kpi_id in KPI_IDS},
    }
    # Lo schema NON porta `input_driver_refs` su `modules.kpi`: i
    # riferimenti del modulo vivono nella PROIEZIONE di governance, mai dentro
    # `module_result`.
    detail["kpi_refs"] = sorted(set(modules["pnl"]["input_driver_refs"]) |
                                set(break_even_refs))

    # `REC-13` -- il TOTALE AUTORITATIVO conta ogni driver UNA SOLA VOLTA,
    # mentre la somma delle categorie conta ogni RIGA. Se lo stesso costo e'
    # mappato in DUE categorie la somma per categoria supera il totale, e la
    # riga `other` porta lo scarto col segno: e' la difesa strutturale contro
    # il doppio conteggio, non un controllo a valle.
    # La chiave autoritativa e' il RECORD CANONICO (`ASS-*`), non il driver:
    # ogni `ASS-*` di costo appartiene a UNA categoria autoritativa. Lo stesso costo legato due volte in due categorie
    # e' contato UNA volta nel totale e DUE nella somma per categoria.
    cost_lines = cogs_lines + payroll_lines + opex_lines
    source_of = {binding["driver_id"]: binding.get("source_ref")
                 for binding in rows}

    def source_key(line):
        refs = line.get("driver_refs") or [line.get("line_id")]
        return tuple(sorted(source_of.get(ref) or ref for ref in refs))

    authoritative = [ZERO] * horizon
    counted = set()
    for line in cost_lines:
        key = source_key(line)
        if key in counted:
            continue
        counted.add(key)
        for index in range(horizon):
            authoritative[index] += Decimal(line["series"][str(index)])
    detail["categories"] = (cost_lines, authoritative, source_of)

    # `REC-06` -- il ponte P&L -> cassa. La variazione di cassa del periodo
    # differisce dall'EBITDA per le uscite che l'EBITDA non contiene: le
    # categorie di costo DIVERSE da `operating_cost`. Ciascuna e' una VOCE DI
    # RACCORDO dichiarata; senza di esse il ponte sarebbe un'identita' banale
    # fra grandezze gia' uguali, e un test che passa sempre non misura nulla.
    bridge_items = []
    for category in sorted(opex_by_category):
        if category == "operating_cost" or category == UNCATEGORISED:
            continue
        bridge_items.append((category, opex_by_category[category]))
    detail["bridge"] = (ebitda, opening, ending, bridge_items)

    return modules, detail, quota, levels, unexplained, calendar_block


def financial_currency(config):
    """La valuta DICHIARATA in `financial_config`. Mai un letterale."""
    return config.get("currency")


# --------------------------------------------------------------------------
# Riconciliazioni
# --------------------------------------------------------------------------


def reconciliation(rec_id, formula, status, tolerance_text, tolerance_unit,
                   residual=None, breakdown=None, refs=None, expected=None,
                   observed=None, reason=None):
    entry = {
        "rec_id": rec_id,
        "formula": formula,
        "status": status,
        "severity": "FAIL",
        "tolerance": tolerance_text,
        "tolerance_unit": tolerance_unit,
    }
    if expected is not None:
        entry["expected"] = expected
    if observed is not None:
        entry["actual"] = observed
    if residual is not None:
        entry["residual"] = residual
    if breakdown:
        entry["residual_breakdown"] = breakdown
    if refs:
        entry["affected_refs"] = sorted(set(refs))
    if reason is not None:
        entry["not_applicable_reason"] = reason
    return entry


def detail_reconciliation(rec_id, formula, pair, rows, threshold, text, unit,
                          per_category=False):
    """`REC-01`, `REC-02`, `REC-03`, `REC-04` — dettaglio = totale.

    Un importo che nessuna categoria della tassonomia dichiara entra nel TOTALE del
    modulo e non nel DETTAGLIO: e' esattamente il residuo che la
    riconciliazione misura, attribuito al periodo o alla categoria.
    """
    detail_series, total_series, lines = pair
    breakdown = {}
    worst = ZERO
    refs = []
    for index, total in enumerate(total_series):
        residual = total - detail_series[index]
        if residual != ZERO:
            breakdown[str(index)] = amount(residual)
        if residual.copy_abs() > worst.copy_abs():
            worst = residual
    if per_category:
        breakdown = {}
        for line in lines:
            key = line.get("category") or UNCATEGORISED
            if line.get("category") in USE_CATEGORIES:
                continue
            bucket = breakdown.setdefault(key, ZERO)
            for value in line["series"].values():
                bucket += Decimal(value)
            breakdown[key] = bucket
        breakdown = {key: amount(value) for key, value in breakdown.items()}
    for line in lines:
        if line.get("category") in USE_CATEGORIES or \
                line.get("category") in SOURCE_CATEGORIES:
            continue
        refs.extend(line.get("driver_refs") or [])
    if rec_id == REC_PAYROLL_IDENTITY:
        breakdown = {}
        for line in lines:
            if line.get("category") in USE_CATEGORIES:
                continue
            total = ZERO
            for value in line["series"].values():
                total += Decimal(value)
            for driver_id in line.get("driver_refs") or []:
                breakdown[driver_id] = amount(total)
    status = "PASS" if worst.copy_abs() <= threshold else "FAIL"
    del rows
    return reconciliation(
        rec_id, formula, status, text, unit, residual=amount(worst),
        breakdown=breakdown or {"0": amount(ZERO)}, refs=refs,
        expected=amount(sum(detail_series, ZERO)),
        observed=amount(sum(total_series, ZERO)))


def cash_reconciliation(detail, threshold, text, unit):
    """`REC-05` — `opening + cash_in - cash_out = ending`.

    `expected` e `actual` sono le DUE GRANDEZZE DAVVERO CONFRONTATE — il ponte
    `opening + cash_in - cash_out` contro il saldo `ending` — e la loro
    differenza e' esattamente il residuo misurato in `residual` e ripartito in
    `residual_breakdown`. Il ponte per periodo e' lo STESSO calcolato nel
    ciclo sottostante.
    """
    opening, cash_in, cash_out, ending = detail
    breakdown = {}
    worst = ZERO
    bridge_total = ZERO
    for index in range(len(ending)):
        bridge = opening[index] + cash_in[index] - cash_out[index]
        bridge_total += bridge
        residual = bridge - ending[index]
        breakdown[str(index)] = amount(residual)
        if residual.copy_abs() > worst.copy_abs():
            worst = residual
    status = "PASS" if worst.copy_abs() <= threshold else "FAIL"
    return reconciliation(
        REC_CASH_ROLL_FORWARD, "opening + cash_in - cash_out = ending", status,
        text, unit, residual=amount(worst), breakdown=breakdown,
        expected=amount(bridge_total),
        observed=amount(sum(ending, ZERO)))


def flow_quota_reconciliation(rows, quota, threshold, text, unit):
    """`REC-12` — Sigma quote = 1, SOLO per `measure_kind: flow`."""
    breakdown = {}
    refs = []
    worst = ZERO
    exempt = []
    for binding in rows:
        driver_id = binding.get("driver_id")
        if binding.get("measure_kind") != "flow":
            exempt.append(driver_id)
            continue
        if driver_id not in quota:
            continue
        residual = quota[driver_id][1] - ONE
        breakdown[driver_id] = amount(residual)
        refs.append(driver_id)
        if residual.copy_abs() > worst.copy_abs():
            worst = residual
    status = "PASS" if worst.copy_abs() <= threshold else "FAIL"
    entry = reconciliation(
        REC_FLOW_QUOTA, "Sigma quote di ogni timing_rule = 1 (solo flow)",
        status, text, unit, residual=amount(worst),
        breakdown=breakdown or {"(nessun flow)": amount(ZERO)}, refs=refs,
        expected=amount(ONE),
        observed=amount(ONE + worst))
    if exempt:
        entry["not_applicable_reason"] = (
            "measure_kind stock, rate e per_unit sono ESENTI da REC-12: "
            f"{', '.join(sorted(exempt))}")
    return entry


def declared_levels(binding, horizon):
    """Ricostruzione INDIPENDENTE della serie di livello DICHIARATA.

    E' deliberatamente separata da `stock_levels`: una riconciliazione che
    rileggesse la stessa funzione tornerebbe per costruzione e non misurerebbe
    nulla. Qui si legge SOLO la dichiarazione del binding.
    """
    start = binding.get("start_period")
    end = binding.get("end_period")
    start = 0 if start is None else int(start)
    end = horizon - 1 if end is None else int(end)
    schedule = binding.get("timing_schedule") or {}
    rule = binding.get("timing_rule")
    series = {}
    for index in range(horizon):
        if index < start or index > end:
            series[index] = ZERO
            continue
        if rule == "constant":
            series[index] = binding.get("_resolved_value")
        elif rule == "step_level":
            level = ZERO
            for key in sorted(schedule, key=int):
                if int(key) <= index:
                    level = Decimal(str(schedule[key]))
            series[index] = level
        elif rule == "from_schedule":
            if str(index) in schedule:
                series[index] = Decimal(str(schedule[str(index)]))
        else:
            series[index] = binding.get("_resolved_value")
    return series


def stock_level_reconciliation(rows, levels, unexplained, threshold, text,
                               unit):
    """`REC-14` — livello per periodo = serie dichiarata, ogni variazione
    spiegata da un evento DICHIARATO.

    DUE proprieta', entrambe misurate: (a) COPERTURA -- ogni periodo della
    finestra ha un livello dichiarato; (b) IDENTITA' -- il livello EMESSO
    coincide con quello DICHIARATO. Senza (b) una serie ripartita `1/12`
    sopravviverebbe alla riconciliazione, che e' esattamente il difetto da
    rilevare.
    """
    breakdown = {}
    refs = []
    worst = ZERO
    for binding in rows:
        driver_id = binding.get("driver_id")
        if binding.get("measure_kind") != "stock":
            continue
        for index in unexplained.get(driver_id) or []:
            previous = levels[driver_id][index - 1] if index > 0 else ZERO
            gap = (levels[driver_id][index] - previous).copy_abs()
            breakdown[str(index)] = amount(gap if gap > ZERO else previous)
            refs.append(driver_id)
            if previous.copy_abs() > worst.copy_abs():
                worst = previous
        declared = declared_levels(binding, len(levels[driver_id]))
        for index, expected in sorted(declared.items()):
            observed = levels[driver_id][index]
            residual = observed - expected
            if residual.copy_abs() > threshold:
                breakdown[str(index)] = amount(residual)
                refs.append(driver_id)
                if residual.copy_abs() > worst.copy_abs():
                    worst = residual
    status = "PASS" if not breakdown else "FAIL"
    return reconciliation(
        REC_STOCK_LEVEL,
        "livello(t) = serie dichiarata e ogni variazione e' spiegata da un "
        "evento dichiarato", status, text, unit,
        residual=amount(worst), breakdown=breakdown or {"0": amount(ZERO)},
        refs=refs, expected="livello dichiarato",
        observed="livello emesso")


# --------------------------------------------------------------------------
# Proiezione di governance NON canonica
# --------------------------------------------------------------------------


def bridge_reconciliation(detail, threshold, text, unit):
    """`REC-06` -- ponte P&L -> cassa = variazione di cassa del periodo.

    `EBITDA(t) + Sigma voci di raccordo(t) = ending(t) - opening(t)`. Le voci
    di raccordo sono le uscite che l'EBITDA non contiene. Un importo che
    NESSUNA categoria della tassonomia dichiara non e' una voce di raccordo: resta
    fuori dal ponte ed e' esattamente il residuo che questa riconciliazione
    misura.
    """
    ebitda, opening, ending, bridge_items = detail
    worst = ZERO
    breakdown = {}
    for index in range(len(ebitda)):
        delta = ending[index] - opening[index]
        bridged = ebitda[index]
        for _, series in bridge_items:
            bridged -= series[index]
        residual = bridged - delta
        breakdown[str(index)] = amount(residual)
        if residual.copy_abs() > worst.copy_abs():
            worst = residual
    status = "PASS" if worst.copy_abs() <= threshold else "FAIL"
    named = ", ".join(category for category, _ in bridge_items) or "nessuna"
    return reconciliation(
        REC_PNL_CASH_BRIDGE,
        "EBITDA(t) + Sigma voci di raccordo(t) = ending(t) - opening(t); "
        f"voci di raccordo dichiarate: {named}",
        status, text, unit, residual=amount(worst), breakdown=breakdown,
        refs=[category for category, _ in bridge_items])


def category_reconciliation(detail, threshold, text, unit):
    """`REC-13` -- Sigma categorie mappate + `other` = totale costi.

    Il totale conta ogni driver UNA VOLTA; la somma per categoria conta ogni
    RIGA. Lo stesso costo mappato in DUE categorie fa quindi comparire uno
    scarto nella riga `other`, che deve tendere a zero.
    """
    cost_lines, authoritative, source_of = detail
    horizon = len(authoritative)
    mapped = [ZERO] * horizon
    by_category = {}
    duplicated = {}
    counted = {}
    for line in cost_lines:
        category = line.get("category")
        if category not in USE_CATEGORIES:
            continue
        bucket = by_category.setdefault(category, [ZERO] * horizon)
        for index in range(horizon):
            value = Decimal(line["series"][str(index)])
            mapped[index] += value
            bucket[index] += value
        for ref in line.get("driver_refs") or []:
            counted.setdefault(source_of.get(ref) or ref, set()).add(category)
    for ref, categories in counted.items():
        if len(categories) > 1:
            duplicated[ref] = sorted(categories)
    worst = ZERO
    breakdown = {}
    for index in range(horizon):
        other = authoritative[index] - mapped[index]
        breakdown[str(index)] = amount(other)
        if other.copy_abs() > worst.copy_abs():
            worst = other
    breakdown[UNCATEGORISED] = amount(worst)
    for ref, categories in sorted(duplicated.items()):
        breakdown[ref] = ", ".join(categories)
    status = "PASS" if worst.copy_abs() <= threshold else "FAIL"
    return reconciliation(
        REC_CATEGORY_TOTAL,
        "Sigma categorie mappate + other = totale costi; le categorie di "
        "costo sono MUTUAMENTE ESCLUSIVE e la riga other tende a zero",
        status, text, unit, residual=amount(worst), breakdown=breakdown,
        refs=sorted(duplicated) or sorted(by_category))


def break_even_reconciliation(detail, threshold, text, unit):
    """`REC-15` -- identita' del pareggio coi costi fissi del periodo.

    `ricavo_di_pareggio x (margine_unitario / prezzo_unitario) = costi fissi
    del periodo di riferimento`, che e' la forma DIMENSIONALMENTE COERENTE
    dell'identita' di pareggio ed e' equivalente a
    `volume_di_pareggio x margine_unitario = costi fissi`.
    I costi fissi sono quelli CATEGORIZZATI: un importo che nessuna categoria
    della tassonomia dichiara non e' un costo fisso attribuibile.
    """
    if detail is None:
        return reconciliation(
            REC_BREAK_EVEN,
            "ricavo di pareggio x (margine unitario / prezzo) = costi fissi",
            "NOT_APPLICABLE", text, unit,
            reason=("il pareggio non e' raggiungibile: margine unitario non "
                    "positivo o profilo pre-revenue, e l'identita' "
                    "non ha oggetto"))
    revenue, margin, price, fixed, refs = detail
    with localcontext() as local:
        local.prec = CALCULATION_PRECISION
        implied = revenue * margin / price
    residual = implied - fixed
    status = "PASS" if residual.copy_abs() <= threshold else "FAIL"
    return reconciliation(
        REC_BREAK_EVEN,
        "ricavo di pareggio x (margine unitario / prezzo unitario) = costi "
        "fissi CATEGORIZZATI del periodo di riferimento",
        status, text, unit, residual=amount(residual),
        breakdown={"0": amount(residual)}, refs=refs,
        expected=amount(fixed), observed=amount(implied))


def scenario_reconciliation(results, threshold, text, unit):
    """`REC-11` -- dettaglio di scenario = sintesi di quello SCENARIO.

    Una riconciliazione INDIPENDENTE per ciascuno scenario prodotto: riusare
    la sintesi del base e' la mutazione di test `M-25`, e la coincidenza sul solo base
    non soddisfa il contratto.
    """
    worst = ZERO
    breakdown = {}
    refs = []
    for scenario_id in SCENARIO_IDS:
        entry = results.get(scenario_id)
        if not entry or entry.get("status") == "NOT_APPLICABLE":
            continue
        refs.append(scenario_id)
        for key, block in sorted((entry.get("series") or {}).items()):
            total = ZERO
            for value in block.values():
                total += Decimal(str(value))
            declared = (entry.get("summary") or {}).get(f"{key}_total")
            if declared is None:
                residual = total
            else:
                residual = Decimal(str(declared)) - total
            breakdown[f"{scenario_id}.{key}"] = amount(residual)
            if residual.copy_abs() > worst.copy_abs():
                worst = residual
    if not refs:
        return reconciliation(
            REC_SCENARIO_DETAIL,
            "dettaglio di scenario = sintesi di scenario",
            "NOT_APPLICABLE", text, unit,
            reason=("nessuno scenario prodotto: con copertura NULLA Downside e "
                    "Upside non sono ne' prodotti ne' etichettati"))
    status = "PASS" if worst.copy_abs() <= threshold else "FAIL"
    return reconciliation(
        REC_SCENARIO_DETAIL,
        "dettaglio di scenario = sintesi di scenario, per CIASCUNO scenario "
        "prodotto e con riconciliazione INDIPENDENTE",
        status, text, unit, residual=amount(worst), breakdown=breakdown,
        refs=refs)


def minimum_status(refs, status_by_driver):
    values = [status_by_driver.get(ref) for ref in refs
              if status_by_driver.get(ref) is not None]
    if not values:
        return NO_GOVERNED_INPUT_STATUS
    return min(values, key=STATUS_ORDER.index)


# --------------------------------------------------------------------------
# Architettura degli scenari
# --------------------------------------------------------------------------


def scenario_endpoints(binding):
    """La TERNA dichiarata dal record `ASS-*`.

    Restituisce `(base, basso, alto)` oppure `None` se il record non porta la
    terna: in quel caso il driver e' SCOPERTO e conta come tale nella politica
    di copertura degli scenari. NESSUN valore e' inventato e NESSUN
    moltiplicatore di default e' applicato.
    """
    record = binding.get("_record") or {}
    keys = ("base_case", "downside_case", "upside_case")
    if any(record.get(key) is None for key in keys):
        return None
    values = [Decimal(str(record[key])) for key in keys]
    return values[0], min(values[1], values[2]), max(values[1], values[2])


def timing_endpoints(binding, horizon):
    """Gli estremi di TIMING dichiarati da un driver `timing_like`.

    Restituisce `(base, anticipato, ritardato)` come INDICI DI PERIODO, oppure
    `None` quando la terna non e' UTILIZZABILE come timing: non dichiarata, non
    intera, negativa, fuori orizzonte, oppure su un driver che non dichiara
    alcuna finestra da muovere. Nessun ritardo di default e nessun
    moltiplicatore e' inventato, e un driver con estremi inutilizzabili NON
    conta come coperto.
    """
    if binding.get("start_period") is None:
        return None
    endpoints = scenario_endpoints(binding)
    if endpoints is None:
        return None
    periods = []
    for value in endpoints:
        if value != value.to_integral_value():
            return None
        index = int(value)
        if index < 0 or index >= horizon:
            return None
        periods.append(index)
    # `scenario_endpoints` normalizza la coppia dichiarata in (basso, alto):
    # il periodo BASSO e' quello ANTICIPATO, il periodo ALTO e' il RITARDATO.
    return periods[0], periods[1], periods[2]


def scenario_timing(binding, scenario, horizon):
    """Il PERIODO DI INIZIO del driver PER QUELLO SCENARIO.

    Downside RITARDATO, Upside ANTICIPATO, Base INVARIATO. Gli estremi sono
    quelli DICHIARATI dal record: il driver non e' spostato di una quantita'
    inventata, e' portato sull'estremo che il record stesso porta.
    """
    endpoints = timing_endpoints(binding, horizon)
    if endpoints is None:
        return None
    base, early, late = endpoints
    if scenario == "base":
        return base
    return late if scenario == "downside" else early


def scenario_usable(binding, horizon):
    """Il driver porta estremi di scenario UTILIZZABILI per la propria polarita'.

    Per un driver di TIMING gli estremi devono essere periodi utilizzabili; per
    ogni altra polarita' basta la terna di valori. E' questa funzione -- non la
    sola presenza della terna -- a decidere la COPERTURA: un driver i cui
    estremi non sono consumabili non puo' contare come coperto mentre si
    comporta da invariante.
    """
    if binding.get("scenario_polarity") in POLARITY_TIMING:
        return timing_endpoints(binding, horizon) is not None
    return scenario_endpoints(binding) is not None


def scenario_value(binding, scenario):
    """Il valore risolto del driver PER QUELLO SCENARIO.

    E' la POLARITA' a decidere quale estremo della terna diventa Downside:
    per un driver `cost_like` il caso avverso e' il valore ALTO, per un
    `revenue_like` e' il valore BASSO. Applicare `Downside = High` a tutto e'
    esplicitamente vietato, ed e' la mutazione di test `M-24`.

    Per un driver `timing_like` l'IMPORTO non si muove: la terna dichiara
    PERIODI ed e' `scenario_timing` a consumarla.
    """
    endpoints = scenario_endpoints(binding)
    if endpoints is None:
        return None
    base, low, high = endpoints
    if scenario == "base":
        return base
    polarity = binding.get("scenario_polarity")
    if polarity in POLARITY_INVARIANT or polarity in POLARITY_TIMING:
        return base
    if polarity in POLARITY_HIGH_ON_DOWNSIDE:
        return high if scenario == "downside" else low
    return low if scenario == "downside" else high


def scenario_coverage(rows, profile, config):
    """Copertura di scenario sui SOLI ruoli RICHIESTI dal profilo.

    Restituisce `(livello, rapporto, scoperti, soglia)`. La copertura e'
    riportata NOMINALMENTE: l'elenco degli scoperti non e' mai riassorbito in
    un rapporto numerico.
    """
    required = set(profile.get("required_driver_roles") or [])
    horizon = int(config["horizon_periods"])
    covered, uncovered = [], []
    for binding in rows:
        if binding.get("_financing") or binding.get("role") not in required:
            continue
        if scenario_usable(binding, horizon):
            covered.append(binding["driver_id"])
        else:
            uncovered.append(binding["driver_id"])
    total = len(covered) + len(uncovered)
    policy = config.get("scenario_coverage_policy") or {}
    declared = policy.get("threshold")
    threshold = Decimal(str(declared)) if declared is not None else \
        Decimal(SCENARIO_COVERAGE_THRESHOLD_DEFAULT)
    # La policy di approvabilita' di un piano `base_only` e' LETTA dalla
    # configurazione. Il default e'
    # DICHIARATO e riportato nei metadati, mai applicato in silenzio.
    approvable = policy.get("base_only_approvable")
    if approvable is None:
        approvable = SCENARIO_BASE_ONLY_APPROVABLE_DEFAULT
    if not total:
        return COVERAGE_NONE, ZERO, [], threshold, bool(approvable)
    with localcontext() as local:
        local.prec = CALCULATION_PRECISION
        ratio = Decimal(len(covered)) / Decimal(total)
    if not covered:
        level = COVERAGE_NONE
    elif ratio >= threshold:
        level = COVERAGE_FULL
    else:
        level = COVERAGE_PARTIAL
    return level, ratio, sorted(uncovered), threshold, bool(approvable)


def resolve_scenario_rows(rows, scenario, horizon):
    """Il set risolto PROPRIO di uno scenario.

    Ogni scenario riceve una struttura PROPRIA: nessuna struttura mutabile e'
    condivisa fra le esecuzioni, ed e' precisamente cio' che rende impossibile
    per costruzione il cross-leak che la mutazione di test `M-22` introduce.

    Per un driver `timing_like` a muoversi e' la FINESTRA DICHIARATA -- Downside
    RITARDATO, Upside ANTICIPATO -- e non l'importo.
    """
    resolved = []
    for binding in rows:
        clone = dict(binding)
        if binding.get("scenario_polarity") in POLARITY_TIMING:
            start = scenario_timing(binding, scenario, horizon)
            if start is not None:
                clone["start_period"] = start
        else:
            value = scenario_value(binding, scenario)
            if value is not None:
                clone["_resolved_value"] = value
        resolved.append(clone)
    return resolved


def scenario_result(scenario, modules, refs, checksum):
    """Un `scenario_result` conforme allo schema, senza campi aggiunti.

    Nessun campo di stato propagato vi e' inserito: lo stato PER SCENARIO vive
    nella proiezione di governance NON canonica.
    """
    series = {}
    for module_id in ("revenue", "cogs", "gross_margin", "pnl", "cash_flow",
                      "funding_gap"):
        entry = modules.get(module_id) or {}
        if entry.get("series"):
            series[module_id] = entry["series"]
    summary = {}
    for module_id, block in sorted(series.items()):
        total = ZERO
        for value in block.values():
            total += Decimal(str(value))
        summary[f"{module_id}_total"] = amount(total)
    ending = (modules.get("cash_flow") or {}).get("series") or {}
    if ending:
        last = max(int(key) for key in ending)
        summary["ending_cash"] = ending[str(last)]
    return {
        "scenario": scenario,
        "status": "PASS",
        "driver_refs": sorted(set(refs)),
        "series": series,
        "summary": summary,
        "output_checksum": checksum,
    }


def not_applicable_scenario(scenario, reason):
    """Uno scenario NON PRODOTTO e NON ETICHETTATO.

    Non e' omesso in silenzio: e' DICHIARATO `NOT_APPLICABLE` con motivazione,
    senza serie, senza sintesi e senza checksum. Etichettare Downside o Upside
    senza input differenziati e' `scenario_series_identical`.
    """
    return {"scenario": scenario, "status": "NOT_APPLICABLE",
            "not_applicable_reason": reason}


def sensitivity_report(rows, scenario_ids, horizon, report):
    """Sensitivity: UN DRIVER PER VOLTA.

    Ogni passo muove un solo driver e l'effetto resta attribuibile a quel
    driver. Un passo che ne muovesse due sarebbe `sensitivity_multi_driver`.

    Un driver i cui estremi non sono CONSUMABILI non compare fra i passi: un
    driver elencato come «mosso» che in realta' resta invariante e' la stessa
    falsita' della copertura contata su estremi ignorati.
    """
    steps = []
    for binding in rows:
        if binding.get("_financing"):
            continue
        if not scenario_usable(binding, horizon):
            continue
        for scenario in scenario_ids:
            if scenario == "base":
                continue
            moved = [binding["driver_id"]]
            if len(moved) != 1:
                report.add_error(
                    CODE_SENSITIVITY_MULTI, ref=",".join(moved),
                    message=("un passo di sensitivity muove piu' di un driver: "
                             "l'effetto non e' piu' attribuibile al singolo "
                             "driver"),
                    expected="un driver per volta", actual=len(moved))
                continue
            steps.append({"driver_id": binding["driver_id"],
                          "scenario": scenario,
                          "polarity": binding.get("scenario_polarity")})
    return steps


def build_projection(modules, rows, consumed, extra_refs=None,
                     scenario_refs=None):
    """La proiezione porta STATO e RIFERIMENTI, mai quantita'.

    Chiavi DETERMINISTICHE, valori dall'enumerazione CHIUSA di `driver_status`,
    UNA voce per OGNI modulo prodotto e pertinente, minimo esatto sui
    riferimenti DICHIARATI e CONSUMATI, coerenza col livello di piano, e
    nessuna voce dentro `module_result`.
    """
    status_by_driver = {binding["driver_id"]: binding.get("_status")
                        for binding in rows}
    extra_refs = extra_refs or {}
    projected = {}
    for module_id in MODULE_ORDER:
        entry = modules.get(module_id)
        if entry is None:
            continue
        # Lo schema non porta `input_driver_refs` su `modules.kpi`:
        # i suoi riferimenti arrivano QUI, nella proiezione, e non dentro il
        # modulo. Una voce PRODOTTA non e' mai omessa.
        refs = sorted(entry.get("input_driver_refs") or
                      extra_refs.get(module_id) or [])
        projected[module_id] = {
            "propagated_status": minimum_status(refs, status_by_driver),
            "input_driver_refs": refs,
        }
    plan_refs = sorted(driver_id for driver_id in status_by_driver
                       if driver_id in consumed)
    # UNO STATO SEPARATO PER CIASCUNO SCENARIO, derivato dal
    # `driver_refs` PROPRIO di quello scenario. Nessuno stato e' calcolato una
    # volta e copiato, e uno scenario NOT_APPLICABLE porta il fondo
    # dell'enumerazione chiusa, mai uno stato PRESO IN PRESTITO da un altro.
    scenarios = {}
    for scenario_id, refs in sorted((scenario_refs or {}).items()):
        own = sorted(set(refs or []))
        scenarios[scenario_id] = {
            "propagated_status": minimum_status(own, status_by_driver),
            "driver_refs": own,
        }
    return {
        "plan": {"propagated_status": minimum_status(plan_refs,
                                                     status_by_driver)},
        "modules": projected,
        "scenarios": scenarios,
    }


# --------------------------------------------------------------------------
# Corpo del validator
# --------------------------------------------------------------------------


def canonical_blob(payload):
    return json.dumps(payload, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"))


def check_engine(args, config, state, report, doc, fingerprint, output):
    tolerances = tolerance_table()
    financial = resolve_financial_config(args, doc, report)
    profile_id = doc.get("profile_id") or (financial or {}).get(
        "financial_profile")
    if not profile_id:
        raise fw.ValidatorUsageError(
            "profilo finanziario non determinabile: ne' profile_id "
            "nell'ingresso ne' financial_config.financial_profile")
    profile = load_profile(profile_id)
    rows = [entry for entry in doc["driver_bindings"] if isinstance(entry, dict)]
    overlay = build_overlay(state, doc)

    report.add_check(
        CHECK_ENGINE_INPUT, "PASS",
        expected="driver_bindings[] gia' risolto da validate_financial_binding",
        actual=f"{len(rows)} righe da {doc.get('_source_label')}",
        message=(f"ingresso del motore ricevuto in fase {args.phase} per il "
                 f"profilo {profile_id}"))

    payload = {
        "kind": "intermediate_non_canonical",
        "milestone": "financial-engine",
        "financial_payload": {
            "driver_registry": {
                "engine_version": ENGINE_VERSION,
                "formula_version": FORMULA_VERSION,
                "profile_id": profile_id,
                "drivers": [],
                "unbound_required_roles": [],
            },
            "results": {"modules": {}},
            "reconciliations": {},
            "validation": {},
            "calculation_metadata": {},
        },
        "governance_projection": {"plan": {}, "modules": {}, "scenarios": {}},
        "tolerance_ledger": {},
    }

    winners, superseded, conflict = resolve_precedence(rows, report)
    if superseded:
        payload["financial_payload"]["driver_registry"]["superseded"] = \
            superseded
    blocking, unbound, opening_value, consumed = apply_gates(
        doc, winners, overlay, profile, financial or {}, fingerprint, report)
    blocking = blocking or conflict or financial is None
    check_derived_assumability(winners, report)

    # Attribuzione TIPIZZATA dei soli warning `timing_window_empty`.
    # Il portatore intermedio `report.warnings` porta UN SOLO `ref`; la
    # proiezione sul payload legge qui la TERNA DI TOKEN del singolo warning,
    # identificato per identita' dell'oggetto. Nessun warning preesistente e'
    # toccato: per essi la mappa e' vuota e la proiezione resta quella
    # ordinaria.
    timing_window_refs = {}

    payload["financial_payload"]["driver_registry"]["unbound_required_roles"] \
        = sorted(unbound)
    payload["financial_payload"]["driver_registry"]["drivers"] = \
        [schema_driver(binding) for binding in winners]

    if not blocking:
        calendar_block, fractions, months = build_calendar(financial)
        modules, detail, quota, levels, unexplained, calendar_block = compute(
            winners, calendar_block, fractions, months, opening_value,
            financial, report)
        text_eur, value_eur = tolerance_pair(tolerances,
                                             financial.get("currency"))
        text_ratio, value_ratio = tolerance_pair(tolerances, "ratio")
        text_count, value_count = tolerance_pair(tolerances, "count")
        stock_unit = stock_tolerance_unit(winners) or "count"
        recon = {
            REC_REVENUE_DETAIL: detail_reconciliation(
                REC_REVENUE_DETAIL, "Sigma dettaglio ricavi = totale ricavi",
                detail["revenue"], winners, value_eur, text_eur,
                financial.get("currency")),
            REC_COGS_DETAIL: detail_reconciliation(
                REC_COGS_DETAIL, "Sigma dettaglio COGS = totale COGS",
                detail["cogs"], winners, value_eur, text_eur,
                financial.get("currency")),
            REC_PAYROLL_IDENTITY: detail_reconciliation(
                REC_PAYROLL_IDENTITY,
                # La formula descrive CIO' CHE IL RESIDUO MISURA, non
                # un'identita' vera per costruzione come
                # «Sigma (FTE x costo unitario) = payroll». Il residuo di
                # questa riconciliazione e'
                # `payroll totale - Sigma righe di payroll CATEGORIZZATE`,
                # cioe' il payroll NON CATEGORIZZATO, ed e' ripartito PER
                # RUOLO in `residual_breakdown`.
                "payroll totale - Sigma righe di payroll CATEGORIZZATE = "
                "payroll NON categorizzato (residuo attribuito PER RUOLO)",
                detail["payroll"], winners, value_eur, text_eur,
                financial.get("currency")),
            REC_OPEX_DETAIL: detail_reconciliation(
                REC_OPEX_DETAIL, "Sigma dettaglio opex = totale opex",
                detail["opex"], winners, value_eur, text_eur,
                financial.get("currency"), per_category=True),
            REC_CASH_ROLL_FORWARD: cash_reconciliation(
                detail["cash"], value_eur, text_eur,
                financial.get("currency")),
            REC_FLOW_QUOTA: flow_quota_reconciliation(
                winners, quota, value_ratio, text_ratio, "ratio"),
            REC_STOCK_LEVEL: stock_level_reconciliation(
                winners, levels, unexplained, value_count,
                f"{stock_unit} {tolerances.get('count')}", stock_unit),
            REC_PNL_CASH_BRIDGE: bridge_reconciliation(
                detail["bridge"], value_eur, text_eur,
                financial.get("currency")),
            REC_CATEGORY_TOTAL: category_reconciliation(
                detail["categories"], value_eur, text_eur,
                financial.get("currency")),
            REC_BREAK_EVEN: break_even_reconciliation(
                detail["break_even"], value_eur, text_eur,
                financial.get("currency")),
        }

        # ---- scenari: TRE MOTORI INDIPENDENTI, non tre etichette ----------
        level, ratio, uncovered, cover_threshold, base_only_approvable = \
            scenario_coverage(winners, profile, financial)
        horizon_periods = calendar_block["horizon_periods"]
        scenario_results = {}
        scenario_refs = {}
        scenario_checksums = {}
        covered_refs = sorted(binding["driver_id"] for binding in winners
                              if scenario_usable(binding, horizon_periods))
        # Il MODULO CONSUMATORE e' letto dai moduli GIA' PRODOTTI, per
        # RIFERIMENTO e mai per valore: e' il primo modulo dell'ordine causale
        # che DICHIARA il driver fra i propri `input_driver_refs`.
        module_by_driver = {}
        for module_id in MODULE_ORDER:
            if module_id == "calendar":
                continue
            for driver_id in (modules.get(module_id) or {}).get(
                    "input_driver_refs") or ():
                module_by_driver.setdefault(driver_id, module_id)
        # Copertura NULLA: Downside e Upside NON sono prodotti e NON sono
        # etichettati. Non esiste percorso che li produca.
        produced = SCENARIO_IDS if level != COVERAGE_NONE else ("base",)
        for scenario_id in SCENARIO_IDS:
            if scenario_id not in produced:
                scenario_results[scenario_id] = not_applicable_scenario(
                    scenario_id,
                    "copertura di scenario NULLA sui driver richiesti: "
                    "nessun driver porta la terna di scenario, e produrre una "
                    "serie etichettata Downside o Upside senza input "
                    "differenziati sarebbe una conformita' nominale che "
                    "inganna il lettore")
                scenario_refs[scenario_id] = []
                scenario_checksums[scenario_id] = None
                continue
            own_rows = resolve_scenario_rows(winners, scenario_id,
                                             horizon_periods)
            # ---- `timing_window_empty` — UNICO SITO DI EMISSIONE -----------
            # DOPO che `resolve_scenario_rows` ha prodotto il CLONE specifico
            # dello scenario, PRIMA di invocare `compute`, usando lo
            # `start_period` e l'`end_period` DEL CLONE, l'identificatore dello
            # scenario e quello del driver, ed emettendo nel REPORT PRINCIPALE
            # RITENUTO — non nel report locale `fw.Report(...)` che il ciclo
            # costruisce e SCARTA.
            #
            # PREDICATO DI FINESTRA VUOTA, RIDERIVATO e DICHIARATO:
            #     start_period > end_period, con ENTRAMBI dentro l'orizzonte.
            # Non e' condiviso con `flow_weights` ne' con `stock_levels`, che
            # lo possiedono: la duplicazione e' DELIBERATA, cosi' che
            # l'emissione del warning resti separata dalle funzioni di calcolo
            # e non ne possa alterare il comportamento.
            #
            # L'emissione e' PURAMENTE ADDITIVA: non altera alcun valore e non
            # modifica alcun altro contratto del payload.
            for clone in own_rows:
                start = clone.get("start_period")
                end = clone.get("end_period")
                if not isinstance(start, int) or not isinstance(end, int):
                    continue
                if not (0 <= start < horizon_periods
                        and 0 <= end < horizon_periods):
                    continue
                if start <= end:
                    continue
                driver_id = clone.get("driver_id")
                module_id = module_by_driver.get(driver_id)
                if module_id is None:
                    # Un driver che NESSUN modulo dichiara fra i propri input
                    # non pubblica alcuna grandezza: non esiste una finestra
                    # svuotata pubblicata in silenzio, e attribuire il warning
                    # a un modulo che non lo consuma sarebbe un'affermazione
                    # PIU' FORTE DEL VERO.
                    continue
                report.add_warning(
                    CODE_TIMING_WINDOW_EMPTY, ref=driver_id,
                    message=TIMING_WINDOW_EMPTY_MESSAGE)
                timing_window_refs[id(report.warnings[-1])] = [
                    driver_id, f"module:{module_id}",
                    f"scenario:{scenario_id}"]
            own_modules, _, _, _, _, own_calendar = compute(
                own_rows, build_calendar(financial)[0], fractions, months,
                opening_value, financial,
                fw.Report(VALIDATOR_NAME, args.stage, args.phase))
            own_blob = canonical_blob({"calendar": own_calendar,
                                       "modules": own_modules})
            digest = hashlib.sha256(own_blob.encode("utf-8")).hexdigest()
            scenario_checksums[scenario_id] = digest
            # Il `driver_refs` PROPRIO di QUESTO scenario: i
            # driver governati che QUESTO scenario CONSUMA. Un driver privo di
            # terna e' comunque consumato -- con il proprio valore base -- e
            # partecipa quindi al minimo. Restringere
            # l'insieme ai soli driver con terna renderebbe il `driver_refs` di
            # uno scenario NON PRODOTTO indistinguibile da quello del base a
            # copertura nulla, e la mutazione di test `M-44` diventerebbe
            # invisibile.
            scenario_refs[scenario_id] = [
                binding["driver_id"] for binding in own_rows
                if not binding.get("_financing")]
            scenario_results[scenario_id] = scenario_result(
                scenario_id, own_modules, scenario_refs[scenario_id], digest)
        # `scenario_series_identical` — tre serie IDENTICHE etichettate
        # Base/Downside/Upside.
        distinct = {scenario_checksums[sid] for sid in produced}
        if len(produced) > 1 and len(distinct) == 1:
            report.add_error(
                CODE_SCENARIO_IDENTICAL, ref=",".join(produced),
                message=("gli scenari prodotti portano serie IDENTICHE con "
                         "etichette differenziate: «abbiamo testato il peggio e "
                         "non cambia nulla» invece di «non abbiamo dati per "
                         "testare il peggio»"),
                expected="un checksum DISTINTO per scenario prodotto",
                actual=sorted(distinct))
        coverage_block = {
            "level": level,
            "ratio": amount(ratio),
            "threshold": amount(cover_threshold),
            "uncovered_driver_refs": uncovered,
        }
        if level == COVERAGE_NONE:
            coverage_block["proposed_condition_ref"] = COVERAGE_CONDITION_REF
            # `coverage` e' `additionalProperties: false` nello schema:
            # la policy LETTA non e' riportata qui, e non e'
            # riportata NEPPURE in `calculation_metadata`. Cio' che la rende
            # osservabile e' il suo EFFETTO -- `validation.result`, `checks[]`,
            # `warnings[]`/`errors[]` -- non un campo che la ripeta. Nessun
            # campo di schema e' aggiunto.
            # Un piano `base_only` NON e' approvato pienamente:
            # e' `approved_with_conditions`. Il RISULTATO DI VALIDAZIONE deve
            # rifletterlo, perche' e' `validation.result` il portatore
            # dell'esito: un lettore a valle che vi legga `PASS` vede un piano
            # pienamente approvato, e il caso PEGGIORE risulterebbe piu' pulito
            # del caso PARZIALE, che e' piu' lieve.
            if base_only_approvable:
                report.add_check(
                    "scenario_coverage", "WARNING",
                    affected_refs=uncovered,
                    expected=f"copertura >= {cover_threshold}",
                    actual=str(ratio),
                    message=("copertura di scenario NULLA: Downside e Upside "
                             f"sono NOT_APPLICABLE e la condizione "
                             f"{COVERAGE_CONDITION_REF} e' PROPOSTA con "
                             f"due_before_stage {COVERAGE_CONDITION_STAGE}"))
                report.add_warning(
                    "scenario_coverage", ref=COVERAGE_CONDITION_REF,
                    message=(f"copertura di scenario NULLA: l'esito e' "
                             f"{COVERAGE_BASE_ONLY_OUTCOME}, NON "
                             "un'approvazione piena. Nessun numero di Downside "
                             "o di Upside e' pubblicato, nessuna prontezza "
                             "piena di scenario e' dichiarata, e la condizione "
                             f"{COVERAGE_CONDITION_REF} resta APERTA con "
                             f"due_before_stage {COVERAGE_CONDITION_STAGE}: "
                             "va chiusa prima di quello stage"))
            else:
                report.add_check(
                    "scenario_coverage", "FAIL",
                    affected_refs=uncovered,
                    expected=f"copertura >= {cover_threshold}",
                    actual=str(ratio),
                    message=("copertura di scenario NULLA con "
                             "scenario_coverage_policy.base_only_approvable "
                             "dichiarata false"))
                report.add_error(
                    "scenario_coverage", ref=COVERAGE_CONDITION_REF,
                    message=("copertura di scenario NULLA e "
                             "scenario_coverage_policy.base_only_approvable "
                             "DICHIARATA false: la policy dichiarata non ammette "
                             "un piano base_only, e il piano FALLISCE CHIUSO. "
                             "Nessuna condizione lo rende approvabile a "
                             "runtime"),
                    expected="base_only_approvable true, oppure almeno un "
                             "driver richiesto con estremi di scenario "
                             "consumabili",
                    actual="base_only_approvable false su copertura none")
        elif level == COVERAGE_PARTIAL:
            report.add_warning(
                "scenario_coverage", ref=",".join(uncovered) or None,
                message=("copertura di scenario PARZIALE: i driver privi di "
                         f"terna sono NOMINATI ({', '.join(uncovered)}) e lo "
                         "stato non e' riassorbibile in un PASS"))
        recon[REC_SCENARIO_DETAIL] = scenario_reconciliation(
            scenario_results, value_eur, text_eur, financial.get("currency"))
        sensitivity = sensitivity_report(winners, produced, horizon_periods,
                                         report)
        payload["tolerance_ledger"] = {
            REC_REVENUE_DETAIL: amount(value_eur),
            REC_COGS_DETAIL: amount(value_eur),
            REC_PAYROLL_IDENTITY: amount(value_eur),
            REC_OPEX_DETAIL: amount(value_eur),
            REC_CASH_ROLL_FORWARD: amount(value_eur),
            REC_FLOW_QUOTA: str(tolerances.get("ratio")),
            REC_STOCK_LEVEL: str(tolerances.get("count")),
            REC_PNL_CASH_BRIDGE: amount(value_eur),
            REC_SCENARIO_DETAIL: amount(value_eur),
            REC_CATEGORY_TOTAL: amount(value_eur),
            REC_BREAK_EVEN: amount(value_eur),
        }
        payload["financial_payload"]["results"] = {
            "calendar": calendar_block, "modules": modules,
            "scenarios": dict(scenario_results, coverage=coverage_block)}
        payload["financial_payload"]["sensitivity"] = sensitivity
        payload["financial_payload"]["reconciliations"] = recon
        for rec_id in sorted(recon):
            entry = recon[rec_id]
            report.add_check(
                rec_id, entry["status"], expected=entry.get("expected"),
                actual=entry.get("actual"), residual=entry.get("residual"),
                tolerance=entry.get("tolerance"),
                affected_refs=entry.get("affected_refs"),
                message=entry["formula"])
            if entry["status"] == "FAIL":
                report.add_error(
                    rec_id, ref=rec_id,
                    message=(f"{rec_id} violata: {entry['formula']}; "
                             f"residuo {entry.get('residual')} oltre la "
                             f"tolleranza {entry.get('tolerance')}"),
                    expected=entry.get("expected"), actual=entry.get("actual"))
        payload["governance_projection"] = build_projection(
            modules, winners, consumed,
            extra_refs={"kpi": detail["kpi_refs"]},
            scenario_refs=scenario_refs)
        payload["financial_payload"]["calculation_metadata"] = \
            build_metadata(modules, financial,
                           extra_refs={"kpi": detail["kpi_refs"]},
                           scenario_checksums=scenario_checksums,
                           coverage_threshold=cover_threshold)
        second, _, _, _, _, _ = compute(
            winners, build_calendar(financial)[0], fractions, months,
            opening_value, financial, fw.Report(VALIDATOR_NAME, args.stage,
                                                args.phase))
        # L'autoverifica confronta la CATENA DETERMINISTICA (calendario e
        # moduli) fra due esecuzioni sullo stesso ingresso. Il determinismo
        # PER SCENARIO e' misurato separatamente dai checksum di ciascuno
        # scenario prodotto, che non sarebbero distinguibili in
        # un blob unico.
        first_blob = canonical_blob({"calendar": calendar_block,
                                     "modules": modules})
        second_blob = canonical_blob({"calendar": calendar_block,
                                      "modules": second})
        if first_blob != second_blob:
            report.add_error(
                CODE_DETERMINISM, ref="output_checksums.base",
                message=("due esecuzioni sullo stesso ingresso producono "
                         "risultati diversi: il ricalcolo non e' "
                         "deterministico"),
                expected=hashlib.sha256(first_blob.encode("utf-8")).hexdigest(),
                actual=hashlib.sha256(second_blob.encode("utf-8")).hexdigest())
        else:
            report.add_check(
                CODE_DETERMINISM, "PASS",
                affected_refs=["output_checksums.base", "engine_source_hash"],
                message=("autoverifica di determinismo: due esecuzioni sullo "
                         "stesso ingresso producono lo STESSO checksum"))
    else:
        report.add_check(
            "financial_engine_gate", "FAIL",
            message=("il gate fail-closed precede il calcolo: nessun modulo e' "
                     "prodotto, nessun valore e' stimato e nessuno zero e' "
                     "sostituito"))

    payload["financial_payload"]["validation"] = {
        "result": report.result,
        "checks": list(report.checks),
        "errors": [{"code": entry["code"], "message": entry["message"],
                    "affected_refs": [entry["ref"]] if entry.get("ref") else []}
                   for entry in report.errors],
        "warnings": [{"code": entry["code"], "message": entry["message"],
                      "affected_refs": timing_window_refs.get(id(entry))
                      or ([entry["ref"]] if entry.get("ref") else [])}
                     for entry in report.warnings],
        "propagated_status":
            payload["governance_projection"].get("plan", {}).get(
                "propagated_status", NO_GOVERNED_INPUT_STATUS),
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, ensure_ascii=True,
                                     sort_keys=True) + "\n", encoding="utf-8")


def stock_tolerance_unit(rows):
    for binding in rows:
        if binding.get("measure_kind") == "stock" and \
                binding.get("role") == "headcount":
            return binding.get("unit")
    return None


def tolerance_pair(tolerances, key):
    raw = tolerances.get(key)
    if raw is None:
        raise fw.ValidatorUsageError(
            f"enforcement-config senza tolleranza per {key!r}: la soglia non "
            "e' derivabile e non e' inventata qui")
    return f"{key} {raw}", Decimal(str(raw))


def schema_driver(binding):
    """Proiezione di una riga di binding su `$defs.driver_entry` dello schema."""
    allowed = ("driver_id", "semantic_name", "driver_class", "role",
               "source_ref", "source_path", "source_record_hash", "unit",
               "currency", "measure_kind", "frequency", "conversion_policy",
               "timing_rule", "timing_schedule", "start_period", "end_period",
               "scenario_polarity", "polarity_override_rationale", "status",
               "confidence", "source_priority", "evidence_refs",
               "decision_ref", "upstream_refs", "binding_method",
               "exhaustive_search", "rationale", "double_count_risk",
               "input_kind", "scenario_coverage", "notes")
    entry = {key: binding[key] for key in allowed if key in binding}
    entry["status"] = binding.get("_status") or binding.get("status")
    # Il payload EMESSO porta il vocabolario dello SCHEMA, attraverso la
    # mappatura di confine DICHIARATA. Un valore che la
    # mappatura non conosce e' gia' stato BLOCCATO dal gate ed e' emesso
    # VERBATIM: coercirlo qui nasconderebbe la violazione invece di mostrarla.
    if "conversion_policy" in entry:
        entry["conversion_policy"] = emitted_conversion_policy(
            entry["conversion_policy"])
    return entry


def build_metadata(modules, config, extra_refs=None, scenario_checksums=None,
                   coverage_threshold=None):
    declared = []
    graph = []
    extra_refs = extra_refs or {}
    for module_id in MODULE_ORDER:
        entry = modules.get(module_id)
        if entry is None:
            continue
        refs = sorted(entry.get("input_driver_refs") or
                      extra_refs.get(module_id) or [])
        declared.append({
            "module_id": module_id,
            "module_version": MODULE_VERSION,
            "input_driver_refs": refs,
            "formula_semantics": entry.get("notes") or module_id,
        })
        position = MODULE_ORDER.index(module_id)
        graph.append({
            "module_id": module_id,
            "consumes_driver_refs": refs,
            "feeds_modules": list(MODULE_ORDER[position + 1:]),
        })
    body = canonical_blob({module_id: modules[module_id]
                           for module_id in sorted(modules)})
    # UN checksum per OGNI scenario prodotto; `null` DICHIARATO per quelli
    # NOT_APPLICABLE. Il solo checksum `base` non e' sufficiente (mutazione di
    # test `M-35`).
    checksums = {"base": hashlib.sha256(body.encode("utf-8")).hexdigest()}
    for scenario_id, value in (scenario_checksums or {}).items():
        checksums[scenario_id] = value
    metadata = {
        "engine_version": ENGINE_VERSION,
        "engine_source_hash": engine_source_hash(),
        "calculation_policy_version": config["calculation_policy_version"],
        "modules": declared,
        "output_checksums": checksums,
        "dependency_graph": graph,
    }
    # Il default di POLICY applicato a runtime e' RIPORTATO nei
    # metadati, mai applicato in silenzio.
    if coverage_threshold is not None:
        metadata["scenario_coverage_threshold_applied"] = \
            amount(coverage_threshold)
    return metadata


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    pre = argparse.ArgumentParser(prog=VALIDATOR_NAME, add_help=False)
    pre.add_argument("--engine-input")
    pre.add_argument("--engine-output")
    try:
        known, rest = pre.parse_known_args(argv)
    except SystemExit:
        print(f"{VALIDATOR_NAME}: argomenti CLI non validi", file=sys.stderr)
        return fw.EXIT_USAGE
    engine_input = known.engine_input
    engine_output = known.engine_output

    def check_fn(args, config, state, report):
        if args.stage != STAGE10:
            raise fw.ValidatorUsageError(
                f"stage non pertinente a {VALIDATOR_NAME}: {args.stage} "
                f"(atteso {STAGE10})")
        if args.phase not in SUPPORTED_PHASES:
            raise fw.ValidatorUsageError(
                f"--phase non ammessa per {VALIDATOR_NAME}: {args.phase} "
                f"(ammesse: {SUPPORTED_PHASES})")
        output = resolve_output_target(engine_output, args.project)
        doc = read_engine_input(args, engine_input)
        fingerprint = load_record_fingerprint()
        check_engine(args, config, state, report, doc, fingerprint, output)

    fw.run_validator(VALIDATOR_NAME, check_fn, rest)
    return fw.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
