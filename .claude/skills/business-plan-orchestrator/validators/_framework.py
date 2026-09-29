#!/usr/bin/env python3
"""Framework comune dei validator.

Fornisce: parsing CLI (--project/--candidate/--stage/--phase), contratto di
output JSON con exit code 0/1/2/3, caricamento della configurazione comune,
ordinamento ordinale degli stage (per `stage_order`, mai lessicografico),
lettura dello stato canonico, overlay candidate ⊕ canonico e risoluzione dei riferimenti ASS-*/P-ASS-*.

I validator costruiti su questo framework sono puri e read-only: nessuna
scrittura nel progetto; il report JSON va su stdout.

Due estensioni ADDITIVE, usate dai validator degli Stage 10-13:

- `Report.checks[]` e `Report.add_check()` — una chiave in piu' in
  `to_dict()`, conforme alla forma di `checks` in
  `schemas/financial-plan.schema.json`. Nessun campo esistente cambia
  semantica: `result` ed `exit_code` restano derivati da
  `errors`/`warnings`.
- `load_project_config(project)` accanto a `load_config`, con
  validazione a schema di `financial_config` e i due esiti dichiarati.
  Nessun fallback di runtime per le sei chiavi `required`.

I validator degli Stage 1-9 non ne dipendono: `checks[]` e' una chiave
aggiuntiva del report e `load_project_config` non e' invocata da alcuno di
essi.
"""
import argparse
import json
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SKILL_ROOT / "config" / "enforcement-config.json"
PROJECT_CONFIG_SCHEMA_PATH = SKILL_ROOT / "schemas" / "project-config.schema.json"
PROJECT_CONFIG_REL = "shared/project-config.json"

PHASES = ("ingress", "candidate", "egress", "impact")
CANDIDATE_PHASES = ("candidate", "egress")

# --------------------------------------------------------------------------
# Estensione ADDITIVA `checks[]` di Report.to_dict().
#
# La forma della voce e' quella definita da
# schemas/financial-plan.schema.json al puntatore
#   #/properties/financial_plan/properties/validation/properties/checks/items
# (additionalProperties: false, required check_id + status, OTTO proprieta'
# ammesse, status nel dominio canonical_check_status). Nessun modello di
# `checks` concorrente e' introdotto qui, l'enum non e' esteso e nessuna nona
# proprieta' e' aggiunta.
# --------------------------------------------------------------------------

#: Dominio degli `status` ammessi negli esiti del CALCOLO CANONICO
#: (`#/$defs/canonical_check_status`). `STRUCTURE_PRESENT` e `RUNTIME_REQUIRED`
#: ne sono STRUTTURALMENTE esclusi: restano legittimi solo nel report di QA del
#: workbook, che non e' descritto da quello schema.
CANONICAL_CHECK_STATUS = ("PASS", "UNRESOLVED_INPUT", "WARNING", "FAIL",
                          "NOT_APPLICABLE")

#: Le OTTO proprieta' ammesse da una voce di `checks[]`. `check_id` e `status`
#: sono obbligatorie; le altre sei sono facoltative e sono omesse quando non
#: valorizzate, perche' l'oggetto e' chiuso.
CHECK_PROPERTIES = ("check_id", "status", "expected", "actual", "residual",
                    "tolerance", "affected_refs", "message")

# --------------------------------------------------------------------------
# `financial_config` del progetto (shared/project-config.json).
# --------------------------------------------------------------------------

#: Le SEI chiavi `required` di `financial_config`. NON esiste alcun fallback di
#: runtime per esse: `generic_startup`, `monthly` e 36 periodi sono valori di
#: INIZIALIZZAZIONE che il template di progetto scrive nel file, mai
#: comportamenti del motore in assenza della chiave.
FINANCIAL_CONFIG_REQUIRED_KEYS = (
    "financial_profile",
    "anchor_date",
    "frequency",
    "horizon_periods",
    "currency",
    "calculation_policy_version",
)

FINANCIAL_CONFIG_MISSING = "financial_config_missing"
FINANCIAL_CONFIG_INVALID = "financial_config_invalid"

EXIT_OK = 0
EXIT_CANDIDATE_INVALID = 1
EXIT_USAGE = 2
EXIT_STATE = 3

# Forma canonica degli id numerici: tre cifre zero-padded fino a 999,
# poi numeri pieni senza zeri iniziali (ASS-001, ASS-999, ASS-1000).
# Gli alias con padding divergente (ASS-0001) NON sono id validi.
CANONICAL_NUM = r"(?:[0-9]{3}|[1-9][0-9]{3,})"
ASS_RE = re.compile(rf"^ASS-{CANONICAL_NUM}$")
P_ASS_RE = re.compile(rf"^P-ASS-{CANONICAL_NUM}$")
ANY_ASS_RE = re.compile(rf"^(P-)?ASS-{CANONICAL_NUM}$")
# Forma "lasca": qualunque stringa che pretende di essere un id ASS/P-ASS.
# Serve a intercettare gli alias non canonici invece di ignorarli.
LOOSE_ANY_ASS_RE = re.compile(r"^(P-)?ASS-[0-9]+$")


def ass_numeric(ref):
    """Valore numerico di un id ASS-*/P-ASS-* canonico; None se non canonico."""
    match = ANY_ASS_RE.match(ref) if isinstance(ref, str) else None
    if not match:
        return None
    prefix = "P-ASS-" if ref.startswith("P-") else "ASS-"
    return (prefix, int(ref[len(prefix):]))


class ValidatorUsageError(Exception):
    """Errore di invocazione/configurazione del validator stesso (exit 2)."""

    exit_code = EXIT_USAGE


class CanonicalStateError(Exception):
    """Stato canonico o journal corrotto (exit 3)."""

    exit_code = EXIT_STATE


class CandidateError(Exception):
    """Difetto del candidate rilevato fuori dal ciclo di report (exit 1)."""

    def __init__(self, code, message, ref=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.ref = ref
        self.exit_code = EXIT_CANDIDATE_INVALID


def load_config(path=None):
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise ValidatorUsageError(f"configurazione validator assente: {path}")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidatorUsageError(
            f"configurazione validator malformata: {path}: {exc}")
    if "stage_order" not in config:
        raise ValidatorUsageError(
            f"configurazione senza stage_order: {path}")
    return config


def _financial_config_subschema(schema_path=None):
    """Sottoschema `financial_config` dello schema project-config.

    Lo schema resta la SOLA fonte della forma: oggetto chiuso, sei chiavi
    `required`, tre opzionali, enum dei profili. Nulla e' riscritto qui.
    """
    path = Path(schema_path) if schema_path else PROJECT_CONFIG_SCHEMA_PATH
    if not path.exists():
        raise ValidatorUsageError(f"schema project-config assente: {path}")
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidatorUsageError(
            f"schema project-config malformato: {path}: {exc}")
    subschema = (schema.get("properties") or {}).get("financial_config") \
        if isinstance(schema, dict) else None
    if not isinstance(subschema, dict):
        raise ValidatorUsageError(
            f"schema project-config senza properties.financial_config: {path}")
    return subschema


def _financial_config_named_keys(financial, subschema, errors):
    """Chiavi NOMINATE nel messaggio di FAIL — mai un messaggio generico.

    L'ordine e' deterministico: prima le `required` mancanti nell'ordine di
    `FINANCIAL_CONFIG_REQUIRED_KEYS`, poi le proprieta' sconosciute in ordine alfabetico, poi le chiavi
    presenti ma non conformi (tipo, enum, pattern, minimo).
    """
    named = []
    for key in FINANCIAL_CONFIG_REQUIRED_KEYS:
        if key not in financial:
            named.append(key)
    allowed = tuple(subschema.get("properties") or ())
    for key in sorted(financial):
        if key not in allowed and key not in named:
            named.append(key)
    for error in errors:
        path = list(error.absolute_path)
        if path and isinstance(path[0], str) and path[0] not in named:
            named.append(path[0])
    return named


def _financial_config_failure(report, code, message):
    """Esito di CONTENUTO non conforme: FAIL, mai un valore sostituito.

    Con un `report` l'errore vi e' registrato e la funzione restituisce None:
    un report con `errors` esce 1. Senza `report` l'errore e' sollevato come
    `CandidateError`, che il framework mappa sullo stesso exit 1. In nessuno
    dei due casi una delle sei chiavi `required` e' sostituita con un ripiego.
    """
    if report is not None:
        report.add_error(code, message=message)
        return None
    raise CandidateError(code, message)


def load_project_config(project, report=None, schema_path=None):
    """Legge e valida `shared/project-config.json` di un progetto.

    Vive ACCANTO a `load_config`, che resta invariata: `load_config` legge la
    configurazione di enforcement della skill, questa legge la configurazione
    del PROGETTO. Nessun validator degli Stage 1-9 la invoca e
    `financial_config` resta OPZIONALE nello schema: un progetto senza
    `financial_config` resta schema-valido e non cambia comportamento negli
    Stage 1-9.

    Due esiti dichiarati, e nessun terzo:

    - ERRORE D'USO -> `ValidatorUsageError` (exit 2): `project` non e' una
      directory, `shared/project-config.json` e' assente o illeggibile, il JSON
      e' malformato, lo schema project-config e' assente o malformato, `jsonschema`
      non e' importabile. Un errore d'uso NON e' mascherato da un FAIL di
      contenuto.
    - CONTENUTO NON CONFORME -> FAIL: `financial_config_missing` se la
      proprieta' e' assente, `financial_config_invalid` se e' presente ma non
      conforme al sottoschema, in entrambi i casi con le chiavi
      NOMINATE. Un FAIL di contenuto NON e' mascherato da un errore d'uso.

    Restituisce il `financial_config` LETTO quando e' valido — mai una copia
    con valori sostituiti — e `None` quando il contenuto e' non conforme e un
    `report` e' stato fornito. NON esiste alcun fallback di runtime per le sei
    chiavi `required`.
    """
    project = Path(project)
    if not project.is_dir():
        raise ValidatorUsageError(f"project dir inesistente: {project}")
    config_path = project / PROJECT_CONFIG_REL
    if not config_path.is_file():
        raise ValidatorUsageError(f"project-config assente: {config_path}")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidatorUsageError(
            f"project-config malformato: {config_path}: {exc}")
    except OSError as exc:
        raise ValidatorUsageError(
            f"project-config illeggibile: {config_path}: {exc}")
    if not isinstance(config, dict):
        raise ValidatorUsageError(
            f"project-config non e' un oggetto JSON: {config_path}")

    if "financial_config" not in config:
        return _financial_config_failure(
            report, FINANCIAL_CONFIG_MISSING,
            f"financial_config assente da {PROJECT_CONFIG_REL}; chiavi "
            f"obbligatorie mancanti: "
            f"{', '.join(FINANCIAL_CONFIG_REQUIRED_KEYS)}; nessun valore di "
            "default e' sostituito")

    financial = config["financial_config"]
    try:
        import jsonschema
    except ImportError as exc:
        raise ValidatorUsageError(
            "jsonschema non importabile: la validazione a schema di "
            f"financial_config non e' eseguibile ({exc})")
    subschema = _financial_config_subschema(schema_path)
    errors = sorted(
        jsonschema.Draft202012Validator(subschema).iter_errors(financial),
        key=lambda err: (list(map(str, err.absolute_path)), err.message))
    if errors:
        named = _financial_config_named_keys(
            financial if isinstance(financial, dict) else {}, subschema, errors)
        detail = "; ".join(
            "{}: {}".format("/".join(map(str, err.absolute_path)) or
                            "financial_config", err.message)
            for err in errors)
        return _financial_config_failure(
            report, FINANCIAL_CONFIG_INVALID,
            "financial_config non conforme allo schema project-config; "
            f"chiavi: "
            f"{', '.join(named) if named else 'financial_config'}; {detail}; "
            "nessun valore di default e' sostituito")
    return financial


def stage_ordinal(stage, config):
    order = config["stage_order"]
    if stage not in order:
        raise ValidatorUsageError(f"stage non riconosciuto: {stage}")
    return int(order[stage])


def data_stage_ordinal(stage, config):
    """Ordinal per stage proveniente dai DATI (non dalla CLI): None se ignoto."""
    order = config["stage_order"]
    if stage not in order:
        return None
    return int(order[stage])


def parse_args(argv, validator_name):
    parser = argparse.ArgumentParser(prog=validator_name, add_help=False)
    parser.add_argument("--project")
    parser.add_argument("--candidate")
    parser.add_argument("--stage")
    parser.add_argument("--phase")
    try:
        args, unknown = parser.parse_known_args(argv)
    except SystemExit:
        raise ValidatorUsageError("argomenti CLI non validi")
    if unknown:
        raise ValidatorUsageError(f"argomenti non riconosciuti: {unknown}")
    if not args.project or not args.stage or not args.phase:
        raise ValidatorUsageError(
            "argomenti obbligatori: --project, --stage, --phase")
    if args.phase not in PHASES:
        raise ValidatorUsageError(
            f"--phase non riconosciuta: {args.phase} (ammesse: {PHASES})")
    project = Path(args.project)
    if not project.is_dir():
        raise ValidatorUsageError(f"project dir inesistente: {args.project}")
    if args.phase in CANDIDATE_PHASES:
        if not args.candidate:
            raise ValidatorUsageError(
                f"--candidate obbligatorio in fase {args.phase}")
        if not Path(args.candidate).is_dir():
            raise ValidatorUsageError(
                f"candidate dir inesistente: {args.candidate}")
    elif args.candidate:
        raise ValidatorUsageError(
            f"--candidate non ammesso in fase {args.phase} "
            "(nessun P-ASS-* in ingress/impact)")
    args.project = project
    args.candidate = Path(args.candidate) if args.candidate else None
    return args


class Report:
    def __init__(self, validator, stage, phase):
        self.validator = validator
        self.stage = stage
        self.phase = phase
        self.errors = []
        self.warnings = []
        self.affected_refs = []
        # la chiave `checks` esiste SEMPRE, anche vuota. `checks[]` non alimenta
        # `errors` ne' `warnings`, quindi non entra in `result` ne' in
        # `exit_code` e non tocca `affected_refs` del report.
        self.checks = []

    def _touch(self, ref):
        if ref and ref not in self.affected_refs:
            self.affected_refs.append(ref)

    def add_error(self, code, ref=None, message="", expected=None, actual=None):
        entry = {"code": code, "ref": ref, "message": message}
        if expected is not None:
            entry["expected"] = expected
        if actual is not None:
            entry["actual"] = actual
        self.errors.append(entry)
        self._touch(ref)

    def add_warning(self, code, ref=None, message=""):
        self.warnings.append({"code": code, "ref": ref, "message": message})
        self._touch(ref)

    def add_check(self, check_id, status, expected=None, actual=None,
                  residual=None, tolerance=None, affected_refs=None,
                  message=None):
        """Registra un esito nella sezione `checks[]` del report.

        Il delta e' ADDITIVO in senso stretto: `add_check` REGISTRA e basta.
        Non promuove e non declassa nulla, non scrive in `errors` ne' in
        `warnings`, non tocca `affected_refs` del report e quindi non cambia
        `result` ne' `exit_code`. Un `FAIL` che deve bloccare passa da
        `add_error`, un `WARNING` da `add_warning`, un `UNRESOLVED_INPUT` da
        `add_error` se il ruolo e' richiesto: registrarlo qui non sostituisce
        quella chiamata.

        La voce prodotta usa SOLO le otto proprieta' ammesse dallo schema
        di `checks` e uno `status` del dominio
        `canonical_check_status`. Uno stato fuori dominio non e' declassato a
        un default: e' `CanonicalStateError` (exit 3), fail-closed.
        """
        if not isinstance(check_id, str) or not check_id:
            raise ValidatorUsageError(
                "add_check: check_id deve essere una stringa non vuota")
        if status not in CANONICAL_CHECK_STATUS:
            raise CanonicalStateError(
                f"stato di check non canonico: {status!r} "
                f"(ammessi: {', '.join(CANONICAL_CHECK_STATUS)})")
        entry = {"check_id": check_id, "status": status}
        for key, value in (("expected", expected), ("actual", actual),
                           ("residual", residual), ("tolerance", tolerance),
                           ("affected_refs", affected_refs),
                           ("message", message)):
            if value is not None:
                entry[key] = value
        self.checks.append(entry)
        return entry

    @property
    def result(self):
        if self.errors:
            return "FAIL"
        if self.warnings:
            return "WARNING"
        return "PASS"

    @property
    def exit_code(self):
        return EXIT_CANDIDATE_INVALID if self.errors else EXIT_OK

    def to_dict(self):
        return {
            "result": self.result,
            "validator": self.validator,
            "stage": self.stage,
            "phase": self.phase,
            "errors": self.errors,
            "warnings": self.warnings,
            "affected_refs": self.affected_refs,
            # `checks`: UNA chiave in piu'. Le sette preesistenti conservano
            # nome, valore e semantica.
            "checks": self.checks,
        }

    def to_json(self):
        # ensure_ascii=True — il report deve restare stampabile su
        # qualunque stdout (console Windows cp1252 inclusa) senza richiedere
        # PYTHONIOENCODING al chiamante; json.loads ripristina i caratteri.
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=True)


def read_canonical_json(path, label):
    if not path.exists():
        raise CanonicalStateError(f"file canonico assente: {label}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CanonicalStateError(f"file canonico corrotto: {label}: {exc}")


def read_candidate_json(path, label):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CandidateError("invalid", f"file candidate corrotto: {label}: {exc}")


def parse_front_matter(text):
    """Parser minimale (zero dipendenze) del front matter di project-status.md.

    Supporta `chiave: valore` con stringhe quotate, liste JSON anche
    multi-linea e scalari bare-word.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise CanonicalStateError("project-status.md senza front matter")
    try:
        end = next(i for i, ln in enumerate(lines[1:], start=1)
                   if ln.strip() == "---")
    except StopIteration:
        raise CanonicalStateError("front matter non terminato in project-status.md")
    data = {}
    i = 1
    while i < end:
        line = lines[i]
        i += 1
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            raise CanonicalStateError(
                f"riga front matter non valida: {line.strip()!r}")
        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest.startswith("["):
            while rest.count("[") > rest.count("]") and i < end:
                rest += " " + lines[i].strip()
                i += 1
            try:
                data[key] = json.loads(rest)
            except json.JSONDecodeError as exc:
                raise CanonicalStateError(
                    f"lista front matter non valida per {key}: {exc}")
        elif rest.startswith('"') and rest.endswith('"') and len(rest) >= 2:
            data[key] = rest[1:-1]
        else:
            data[key] = rest
    return data


def validate_status_coherence(status, config):
    """Coerenza semantica globale di project-status.

    Regole: completed_stages senza duplicati, ordinati per ordinale e
    prefisso contiguo della pipeline a partire da 00; current_stage uguale
    all'ultimo stage completato oppure al suo immediato successore (nessun
    salto, nessuno status "futuro"); stato gate nel vocabolario reale
    (gate_states + not_started); approved* implica current_stage nei
    completed; not_started implica stage non ancora completato.
    Ogni violazione è stato canonico corrotto (exit 3)."""
    order = config["stage_order"]
    current = status.get("current_stage")
    if current not in order:
        raise CanonicalStateError(
            f"project-status: current_stage sconosciuto: {current!r}")
    state = status.get("status")
    allowed_states = set(config["gate_states"]) | {"not_started"}
    if state not in allowed_states:
        raise CanonicalStateError(
            f"project-status: stato gate non riconosciuto: {state!r}")
    completed = status.get("completed_stages", [])
    if not isinstance(completed, list):
        raise CanonicalStateError("completed_stages non è una lista")
    ordinals = []
    for stage in completed:
        if stage not in order:
            raise CanonicalStateError(
                f"completed_stages: stage sconosciuto: {stage!r}")
        ordinals.append(int(order[stage]))
    if len(set(ordinals)) != len(ordinals):
        raise CanonicalStateError("completed_stages: duplicati")
    if ordinals != sorted(ordinals):
        raise CanonicalStateError(
            "completed_stages: non ordinati per ordinale di stage")
    if ordinals and ordinals != list(range(len(ordinals))):
        raise CanonicalStateError(
            "completed_stages: non è un prefisso contiguo della pipeline "
            "(stage saltati)")
    last = ordinals[-1] if ordinals else -1
    current_ordinal = int(order[current])
    if current_ordinal not in (last, last + 1):
        raise CanonicalStateError(
            f"current_stage {current} incoerente con completed_stages "
            f"(ultimo completato: ordinale {last})")
    approved = set(config.get("approved_states", []))
    if state in approved and current not in completed:
        raise CanonicalStateError(
            f"status {state} ma current_stage {current} non è nei "
            "completed_stages")
    if state == "not_started" and current in completed:
        raise CanonicalStateError(
            "status not_started su uno stage già completato")


class ProjectState:
    """Stato canonico read-only del progetto."""

    def __init__(self, project, config):
        self.project = Path(project)
        self.config = config
        shared = self.project / "shared"
        self.assumptions = read_canonical_json(
            shared / "assumptions-register.json", "shared/assumptions-register.json")
        if not isinstance(self.assumptions, list):
            raise CanonicalStateError("assumptions-register.json non è una lista")
        conditions_path = shared / "conditions-register.json"
        if conditions_path.exists():
            self.conditions = read_canonical_json(
                conditions_path, "shared/conditions-register.json")
            if not isinstance(self.conditions, list):
                raise CanonicalStateError(
                    "conditions-register.json non è una lista")
        else:
            self.conditions = []
        status_path = shared / "project-status.md"
        if not status_path.exists():
            raise CanonicalStateError("shared/project-status.md assente")
        self.status = parse_front_matter(
            status_path.read_text(encoding="utf-8"))

    def assumptions_by_id(self):
        out = {}
        for entry in self.assumptions:
            entry_id = entry.get("id")
            if entry_id:
                out.setdefault(entry_id, []).append(entry)
        return out


def load_proposed_assumptions(candidate_dir):
    path = Path(candidate_dir) / "proposed-assumptions.json"
    if not path.exists():
        return []
    proposed = read_candidate_json(path, "proposed-assumptions.json")
    if not isinstance(proposed, list):
        raise CandidateError("invalid", "proposed-assumptions.json non è una lista")
    return proposed


def build_overlay(state, candidate_dir):
    """Mappa id -> entry: ASS-* dal canonico, P-ASS-* dal candidate."""
    overlay = {}
    for entry in state.assumptions:
        entry_id = entry.get("id")
        if entry_id:
            overlay[entry_id] = entry
    if candidate_dir is not None:
        seen = set()
        for entry in load_proposed_assumptions(candidate_dir):
            entry_id = entry.get("id")
            if not entry_id or not P_ASS_RE.match(entry_id):
                raise CandidateError(
                    "invalid",
                    f"proposed assumption con id non P-ASS-*: {entry_id!r}",
                    ref=entry_id)
            if entry_id in seen:
                raise CandidateError(
                    "invalid", f"P-ASS duplicato nel candidate: {entry_id}",
                    ref=entry_id)
            seen.add(entry_id)
            overlay[entry_id] = entry
    return overlay


def resolve_ref(ref, overlay):
    return overlay.get(ref)


def run_validator(name, check_fn, argv=None):
    """Entry point comune: parsing, esecuzione pura, report su stdout, exit."""
    argv = sys.argv[1:] if argv is None else argv
    try:
        args = parse_args(argv, name)
        config = load_config()
    except ValidatorUsageError as exc:
        print(f"{name}: {exc}", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    report = Report(name, args.stage, args.phase)
    try:
        stage_ordinal(args.stage, config)
        state = ProjectState(args.project, config)
        check_fn(args, config, state, report)
    except ValidatorUsageError as exc:
        print(f"{name}: {exc}", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    except CanonicalStateError as exc:
        report.add_error("corrupted_state", message=str(exc))
        print(report.to_json())
        sys.exit(EXIT_STATE)
    except CandidateError as exc:
        report.add_error(exc.code, ref=exc.ref, message=exc.message)
        print(report.to_json())
        sys.exit(EXIT_CANDIDATE_INVALID)
    print(report.to_json())
    sys.exit(report.exit_code)
