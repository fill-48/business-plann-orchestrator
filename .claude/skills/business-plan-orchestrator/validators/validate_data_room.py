#!/usr/bin/env python3
"""Validator e COSTRUTTORE della Data Room — Stage 12 `12_data-room`.

DICHIARATO in `config/enforcement-config.json` con `stages: [12]` e
`phases: ["egress","impact"]`, ed elencato in `egress_required`: il
Transaction Manager lo esegue in egress sul candidate dello Stage 12 e in
impact sulla validation view del progetto.

LA DATA ROOM E' LO STRATO DI EVIDENZA DELL'INTERO PIANO
--------------------------------------------------------
Non e' un contenitore di allegati della funding request: INDICIZZA le prove
gia' prodotte dagli stage 00-11 e dai file forniti dall'utente, ai loro path
relativi ESISTENTI, e registra la tracciabilita' claim -> evidenza di ogni
affermazione del piano. Non genera, non copia, non sposta e non riscrive
alcun file indicizzato: i file del progetto fuori da `12_data-room/` restano
byte-identici.

    LEGGE     shared/assumptions-register.json, evidence-register.json,
              source-register.json, conditions-register.json,
              shared/project-status.md, i file indicizzati (per checksum)
    PRODUCE   12_data-room/structured-output.json   CANONICO (via TM)
              12_data-room/handoff.md               CANONICO (via TM)
              12_data-room/data-room-index.md       DERIVATO (--build)

DUE PERCORSI, E SOLO DUE
------------------------
  - VALIDAZIONE, invocata dal Transaction Manager con l'argv REALE:
        egress  --project --candidate --stage 12_data-room --phase egress
        impact  --project --stage 12_data-room --phase impact
    SOLA LETTURA. `--manifest-input` e' un ingresso OPZIONALE via
    pre-parser; in sua assenza il manifest e' DERIVATO dal candidate
    (egress) o dal progetto (impact). Nessun ingresso privato obbligatorio.
  - COSTRUZIONE, `--build --project <p> --tx <tx>`: MAI passata dal
    Transaction Manager. Legge la proposta DICHIARATA dell'analista
    (`12_data-room/.working/<tx>/data-room-proposal.json`), deriva il
    manifest, lo valida con gli STESSI controlli dell'egress, verifica la
    byte-identita' del progetto fuori da `12_data-room/`, e pubblica con un
    pubblicatore ATOMICO a due livelli il candidate (canonico e handoff) e
    l'indice derivato.

CONFINE DEGLI IMPORT
--------------------
Solo la libreria standard e `_framework`. La validazione a
schema usa un motore MINIMO in libreria standard sul sottoinsieme di JSON
Schema che `schemas/data-room.schema.json` dichiara: nessuna dipendenza di
terze parti e nessuna struttura interna di un altro stage.

TASSONOMIA DEI CODICI
---------------------
I trenta codici `data_room_*` del catalogo chiuso e `path_escape`,
condiviso con il Transaction Manager e riusato verbatim; `corrupted_state`
e' del framework. Nessun altro codice e' coniato.

Exit code: 0 valido | 1 manifest invalido o rifiuto di costruzione |
2 errore d'uso | 3 stato canonico corrotto.
"""
import argparse
import hashlib
import json
import os
import re
import stat as stat_module
import sys
import tempfile
import unicodedata
import zipfile
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _framework as fw  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parents[1]

VALIDATOR_NAME = "validate_data_room"
STAGE12 = "12_data-room"
SUPPORTED_PHASES = ("egress", "impact")
SCHEMA_VERSION = "1.0.0"
SCHEMA_PATH = SKILL_ROOT.joinpath("schemas", "data-room.schema.json")

CANONICAL_NAME = "structured-output.json"
HANDOFF_NAME = "handoff.md"
INDEX_NAME = "data-room-index.md"
PROPOSAL_NAME = "data-room-proposal.json"
WORKING_DIR = ".working"

STATUS_REL = "shared/project-status.md"
ASSUMPTIONS_REL = "shared/assumptions-register.json"
EVIDENCE_REL = "shared/evidence-register.json"
SOURCE_REL = "shared/source-register.json"
CONDITIONS_REL = "shared/conditions-register.json"
RISK_REL = "shared/risk-register.json"
DECISIONS_REL = "shared/decisions-register.json"

# --------------------------------------------------------------------------
# Tassonomia CHIUSA — catalogo `data_room_*` e `path_escape` condiviso.
# --------------------------------------------------------------------------

CODE_SECTION_MISSING = "data_room_section_missing"
CODE_MANIFEST_INVALID = "data_room_manifest_invalid"
CODE_DUPLICATE_ID = "data_room_duplicate_id"
CODE_ARTIFACT_TYPE = "data_room_artifact_type_invalid"
CODE_ORIGIN = "data_room_origin_ambiguous"
CODE_BROKEN_PATH = "data_room_broken_path"
CODE_PATH_ESCAPE = "path_escape"
CODE_CHECKSUM = "data_room_checksum_mismatch"
CODE_VERSION = "data_room_version_inconsistent"
CODE_OWNER = "data_room_owner_invalid"
CODE_CONFIDENTIALITY = "data_room_confidentiality_unsupported"
CODE_CLAIM_LINK = "data_room_claim_link_invalid"
CODE_SECTION_INVALID = "data_room_section_invalid"
CODE_VALIDATION_STATUS = "data_room_validation_status_invalid"
CODE_REQUIRED_MISSING = "data_room_required_missing"
CODE_QUALITY = "data_room_quality_unavailable"
CODE_VOLATILE = "data_room_volatile_in_identity"
CODE_NONDETERMINISTIC = "data_room_nondeterministic"
CODE_CLAIM_NAMESPACE = "data_room_claim_namespace_undeclared"
CODE_CLAIM_STATUS = "data_room_claim_status_invalid"
CODE_HIERARCHY = "data_room_source_hierarchy_ignored"
CODE_PROVENANCE = "data_room_provenance_missing"
CODE_GAP = "data_room_evidence_gap_suppressed"
CODE_STALE = "data_room_stale_evidence"
CODE_CONFLICT = "data_room_conflicting_evidence"
CODE_COMPLETENESS = "data_room_completeness_misrepresented"
CODE_ORPHAN = "data_room_orphan_evidence"
CODE_UNSUPPORTED = "data_room_unsupported_claim"
CODE_SECRET = "data_room_secret_leak"
CODE_SOURCE_MUTATED = "data_room_source_mutated"
CODE_DEBT = "data_room_debt_closed_without_proof"

# --------------------------------------------------------------------------
# Vocabolari chiusi
# --------------------------------------------------------------------------

#: Le UNDICI sezioni: partizione LOGICA, chiusa e ordinata, del manifest.
#: NESSUNA cartella fisica di sezione e' creata.
SECTIONS = (
    ("01_corporate-and-governance", "Societario e governance"),
    ("02_market-and-customer-evidence", "Evidenze di mercato e cliente"),
    ("03_product-technology-operations-ip",
     "Prodotto, tecnologia, operations e IP"),
    ("04_commercial-and-go-to-market", "Commerciale e go-to-market"),
    ("05_team-and-organization", "Team e organizzazione"),
    ("06_roadmap-and-milestones", "Roadmap e milestone"),
    ("07_financial-model-and-plan", "Modello e piano finanziario"),
    ("08_funding-request-and-use-of-proceeds",
     "Funding request e impieghi"),
    ("09_risks-assumptions-and-open-items",
     "Rischi, assunzioni e voci aperte"),
    ("10_source-evidence-and-provenance",
     "Fonti, evidenze e provenienza"),
    ("11_generated-artifact-metadata", "Metadati degli artefatti generati"),
)
SECTION_IDS = tuple(section for section, _ in SECTIONS)
SECTION_TITLES = dict(SECTIONS)

#: La sezione di DEFAULT dell'uscita canonica di ogni stage.
STAGE_SECTIONS = {
    "00_idea-discovery": "01_corporate-and-governance",
    "01_problem-and-need": "02_market-and-customer-evidence",
    "02_customer-segmentation": "02_market-and-customer-evidence",
    "03_value-proposition": "02_market-and-customer-evidence",
    "04_market-and-competition": "02_market-and-customer-evidence",
    "05_business-model": "04_commercial-and-go-to-market",
    "06_go-to-market": "04_commercial-and-go-to-market",
    "07_operations-and-ip": "03_product-technology-operations-ip",
    "08_team-and-governance": "05_team-and-organization",
    "09_roadmap-and-milestones": "06_roadmap-and-milestones",
    "10_financial-plan": "07_financial-model-and-plan",
    "11_funding-request": "08_funding-request-and-use-of-proceeds",
}

#: I registri condivisi indicizzati: i TRE obbligatori e quelli presenti.
REQUIRED_REGISTERS = (ASSUMPTIONS_REL, EVIDENCE_REL, SOURCE_REL)
OPTIONAL_REGISTERS = (CONDITIONS_REL, RISK_REL, DECISIONS_REL)
REGISTER_SECTIONS = {
    ASSUMPTIONS_REL: "09_risks-assumptions-and-open-items",
    CONDITIONS_REL: "09_risks-assumptions-and-open-items",
    RISK_REL: "09_risks-assumptions-and-open-items",
    DECISIONS_REL: "09_risks-assumptions-and-open-items",
    EVIDENCE_REL: "10_source-evidence-and-provenance",
    SOURCE_REL: "10_source-evidence-and-provenance",
}
REGISTER_TITLES = {
    ASSUMPTIONS_REL: "Registro ufficiale delle assunzioni",
    EVIDENCE_REL: "Registro delle evidenze",
    SOURCE_REL: "Registro delle fonti",
    CONDITIONS_REL: "Registro delle condizioni",
    RISK_REL: "Registro dei rischi",
    DECISIONS_REL: "Registro delle decisioni",
}
REGISTER_ANCHOR_STAGE = "00_idea-discovery"

SOURCE_TYPES = ("official", "industry_report", "academic", "news", "company",
                "interview", "internal", "estimate", "other")
GENERATED_TYPES = ("stage_canonical_output", "stage_handoff",
                   "derived_chapter", "derived_workbook",
                   "derived_funding_request", "shared_register")

#: I NOMI degli artefatti che il sistema GENERA: un file con uno di questi
#: nomi non e' mai una fonte originale.
GENERATED_NAMES = {
    CANONICAL_NAME: "stage_canonical_output",
    HANDOFF_NAME: "stage_handoff",
    "financial-plan.md": "derived_chapter",
    "financial-model.xlsx": "derived_workbook",
    "funding-request.md": "derived_funding_request",
    "section-draft.md": None,
    INDEX_NAME: None,
}
#: Derivati obbligatori per stage completato, con il canonico da cui
#: derivano (`derived_from`).
STAGE_DERIVED = {
    "10_financial-plan": ("financial-plan.md", "financial-model.xlsx"),
    "11_funding-request": ("funding-request.md",),
}

EVIDENCE_CLASSES = ("verified_fact", "internal_evidence", "external_source",
                    "founder_assumption", "model_estimate",
                    "missing_information")
#: Le classi che SOSTENGONO un claim: un'assunzione del founder o una stima
#: di modello restano assunzioni, mai prove (evidence-framework.md).
EVIDENTIAL_CLASSES = ("verified_fact", "internal_evidence", "external_source")
LINK_STATUSES = ("supporting", "contradicting", "partial", "missing")
GAP_KINDS = ("claim_unsupported", "missing_link",
             "assumption_without_evidence_refs", "missing_information")
CONFLICT_KINDS = ("contradiction", "duplicate")
STALENESS_CRITERION = "evidence_register_date_age_days"
EXCLUDED_FIELDS = ["generated_at", "last_verified_at"]

CANONICAL_NUM = r"(?:[0-9]{3}|[1-9][0-9]{3,})"
DR_RE = re.compile(rf"^DR-{CANONICAL_NUM}\Z")
CLM_RE = re.compile(rf"^CLM-{CANONICAL_NUM}\Z")
EVD_RE = re.compile(rf"^EVD-{CANONICAL_NUM}\Z")
SRC_RE = re.compile(rf"^SRC-{CANONICAL_NUM}\Z")
ASS_RE = re.compile(rf"^ASS-{CANONICAL_NUM}\Z")
COND_RE = re.compile(rf"^COND-{CANONICAL_NUM}\Z")
LOOSE_EVD_RE = re.compile(r"^EVD-[0-9]+\Z")
LOOSE_SRC_RE = re.compile(r"^SRC-[0-9]+\Z")
LOOSE_COND_RE = re.compile(r"^COND-[0-9]+\Z")
ISO_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
ID_NUMBER_RE = re.compile(r"-([0-9]+)\Z")

#: Pattern DICHIARATI dei segreti, applicati ai SOLI
#: artefatti GENERATI: i file sorgente dell'utente NON sono ispezionati.
#: `re.ASCII`: i confini `\b` sono definiti sull'alfabeto ASCII dei token, cosi'
#: un segreto adiacente a testo non ASCII («, —, €, lettere accentate) resta un
#: token riconosciuto.
SECRET_PATTERNS = (
    ("chiave privata PEM",
     re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.ASCII)),
    ("chiave di accesso AWS",
     re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", re.ASCII)),
    ("token GitHub", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b", re.ASCII)),
    ("token Slack", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b",
                               re.ASCII)),
    ("chiave segreta Stripe",
     re.compile(r"\b(?:sk|rk)_live_[0-9A-Za-z]{16,}\b", re.ASCII)),
    ("chiave API Google", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b",
                                     re.ASCII)),
    ("chiave API Anthropic", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}",
                                        re.ASCII)),
    ("chiave API OpenAI",
     re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}", re.ASCII)),
    ("stringa di connessione con credenziali",
     re.compile(r"\b[A-Za-z][A-Za-z0-9+.\-]*://[^\s/:@]+:[^\s/@]+@[^\s/]+",
                re.ASCII)),
)

#: `--tx`: UN segmento, alfabeto sicuro, senza separatori, lettera di drive,
#: `:` o punto finale.
TX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")
#: Uno schema URI di almeno due caratteri (`https:`, `mailto:`, `doi:`): una
#: lettera sola seguita da `:` e' invece una lettera di drive.
URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]+:")
DRIVE_RE = re.compile(r"^[A-Za-z]:")
#: Ogni terminatore di riga di Markdown o di `str.splitlines`.
LINE_BREAKS_RE = re.compile(r"[\r\n\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]+")

#: Seam di test: nessuno. Le sonde di mutazione del costruttore agiscono
#: in-process sulle funzioni di modulo, mai tramite variabili d'ambiente.


class BuildRefusal(Exception):
    """Rifiuto ATTRIBUITO del costruttore: nessun file e' pubblicato."""

    def __init__(self, errors):
        super().__init__("; ".join(message for _, _, message in errors))
        self.errors = errors


# --------------------------------------------------------------------------
# Serializzazione e identita'
# --------------------------------------------------------------------------


def canonical_json(document):
    """Forma DETERMINISTICA del costruttore: chiavi ordinate, indentazione
    2, `ensure_ascii`, newline finale."""
    return json.dumps(document, indent=2, ensure_ascii=True,
                      sort_keys=True) + "\n"


def transaction_form(document):
    """La forma con cui il Transaction Manager RISCRIVE il canonico al
    commit (`dump_json_bytes`: `ensure_ascii=False`, ordine delle chiavi
    CONSERVATO, quindi ancora ordinato). Ammetterla e' cio' che impedisce
    che un canonico non ASCII, riscritto al commit, fallisca poi l'impact."""
    return json.dumps(document, indent=2, ensure_ascii=False,
                      sort_keys=True) + "\n"


#: I campi che COMPONGONO il payload di identita'. L'esclusione dei campi
#: temporali e' per COSTRUZIONE: il payload e' costruito da questi elenchi,
#: non filtrato a posteriori.
IDENTITY_ROOM_FIELDS = ("staleness_policy", "sections", "documents", "claims",
                        "evidence_index", "unresolved_evidence_gaps",
                        "stale_evidence", "conflicts", "orphan_evidence",
                        "unsupported_claims", "completeness", "open_items")
IDENTITY_DOCUMENT_FIELDS = ("document_id", "section_id", "title",
                            "artifact_type", "origin", "path", "checksum",
                            "version", "owner", "confidentiality",
                            "related_claims", "related_section",
                            "validation_status", "availability", "source_ref",
                            "evidence_quality", "evidence_refs",
                            "derived_from")


def identity_payload(room):
    payload = {}
    for key in IDENTITY_ROOM_FIELDS:
        if key not in room:
            continue
        if key == "documents":
            payload[key] = [
                {field: entry[field] for field in IDENTITY_DOCUMENT_FIELDS
                 if field in entry}
                for entry in room[key] if isinstance(entry, dict)]
        else:
            payload[key] = room[key]
    return payload


def identity_of(document):
    room = (document or {}).get("data_room") or {}
    blob = json.dumps(identity_payload(room), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def id_number(ref):
    match = ID_NUMBER_RE.search(str(ref or ""))
    return int(match.group(1)) if match else -1


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def content_version(checksum):
    return "sha256:" + checksum[:12]


def json_strings(node):
    """Ogni chiave e ogni stringa di un documento JSON DECODIFICATO."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from json_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from json_strings(value)
    elif isinstance(node, str):
        yield node


def semantic_text(document):
    """La rappresentazione su cui si cercano i segreti di un JSON: le sue
    stringhe DECODIFICATE, una per riga. E' la STESSA per la forma
    `ensure_ascii` del costruttore, per la riscrittura UTF-8 del Transaction
    Manager e per la view di impact: nessuna sequenza di escape (`\\u00ab`,
    `\\n`) fonde un segreto con il testo che lo precede, e costruttore, egress
    e impact concordano sulla stessa semantica."""
    return "\n".join(json_strings(document))


def duplicated(values):
    """I valori che compaiono PIU' di una volta, nell'ordine della prima
    ripetizione. Un'identita' duplicata e' INVALIDA: mai «vince il primo» o
    «vince l'ultimo»."""
    seen = set()
    repeated = []
    for value in values:
        key = json.dumps(value, sort_keys=True, default=str)
        if key in seen and value not in repeated:
            repeated.append(value)
        seen.add(key)
    return repeated


# --------------------------------------------------------------------------
# Motore MINIMO di JSON Schema (sottoinsieme dichiarato dallo schema)
# --------------------------------------------------------------------------


class SchemaIssue:
    __slots__ = ("path", "keyword", "field", "message")

    def __init__(self, path, keyword, field, message):
        self.path = path
        self.keyword = keyword
        self.field = field
        self.message = message


def load_schema():
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise fw.ValidatorUsageError(
            f"schema della Data Room assente o malformato: {SCHEMA_PATH}: "
            f"{exc}")


def _resolve(root, node):
    guard = 0
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            raise fw.ValidatorUsageError(f"$ref non locale nello schema: {ref}")
        target = root
        for part in ref[2:].split("/"):
            target = target[part]
        node = target
        guard += 1
        if guard > 32:
            raise fw.ValidatorUsageError("catena di $ref troppo lunga")
    return node


def _type_ok(expected, value):
    kinds = expected if isinstance(expected, list) else [expected]
    for kind in kinds:
        if kind == "null" and value is None:
            return True
        if kind == "string" and isinstance(value, str):
            return True
        if kind == "boolean" and isinstance(value, bool):
            return True
        if kind == "integer" and isinstance(value, int) and \
                not isinstance(value, bool):
            return True
        if kind == "number" and isinstance(value, (int, float)) and \
                not isinstance(value, bool):
            return True
        if kind == "object" and isinstance(value, dict):
            return True
        if kind == "array" and isinstance(value, list):
            return True
    return False


_PATTERNS = {}


def _pattern(pattern):
    if pattern not in _PATTERNS:
        text = pattern
        if text.endswith("$") and not text.endswith("\\$"):
            text = text[:-1] + r"\Z"
        _PATTERNS[pattern] = re.compile(text)
    return _PATTERNS[pattern]


def _same(left, right):
    return json.dumps(left, sort_keys=True) == json.dumps(right,
                                                          sort_keys=True)


def schema_issues(root, node, value, path=()):
    """Gli scostamenti di `value` dallo schema, ciascuno col proprio path:
    type, const, enum, pattern, minLength, minimum, maximum, required,
    additionalProperties, properties, items, minItems, maxItems, $ref."""
    issues = []
    node = _resolve(root, node)
    field = next((part for part in reversed(path) if isinstance(part, str)),
                 None)
    expected = node.get("type")
    if expected is not None and not _type_ok(expected, value):
        issues.append(SchemaIssue(path, "type", field,
                                  f"tipo non ammesso: atteso {expected}"))
        return issues
    if "const" in node and not _same(value, node["const"]):
        issues.append(SchemaIssue(path, "const", field,
                                  f"atteso il valore costante {node['const']!r}"))
    if "enum" in node and not any(_same(value, item)
                                  for item in node["enum"]):
        issues.append(SchemaIssue(path, "enum", field,
                                  f"valore {value!r} fuori dall'enum "
                                  f"{node['enum']}"))
    if isinstance(value, str):
        if "minLength" in node and len(value) < node["minLength"]:
            issues.append(SchemaIssue(path, "minLength", field,
                                      "stringa vuota non ammessa"))
        if "pattern" in node and not _pattern(node["pattern"]).search(value):
            issues.append(SchemaIssue(path, "pattern", field,
                                      f"{value!r} non rispetta "
                                      f"{node['pattern']}"))
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in node and value < node["minimum"]:
            issues.append(SchemaIssue(path, "minimum", field,
                                      f"{value} < {node['minimum']}"))
        if "maximum" in node and value > node["maximum"]:
            issues.append(SchemaIssue(path, "maximum", field,
                                      f"{value} > {node['maximum']}"))
    if isinstance(value, dict):
        properties = node.get("properties") or {}
        for key in node.get("required") or ():
            if key not in value:
                issues.append(SchemaIssue(path, "required", key,
                                          f"proprieta' obbligatoria assente: "
                                          f"{key}"))
        if node.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    issues.append(SchemaIssue(
                        path, "additionalProperties", key,
                        f"proprieta' inattesa {key!r}: l'oggetto e' chiuso"))
        for key, sub in properties.items():
            if key in value:
                issues += schema_issues(root, sub, value[key], path + (key,))
    if isinstance(value, list):
        if "minItems" in node and len(value) < node["minItems"]:
            issues.append(SchemaIssue(path, "minItems", field,
                                      f"{len(value)} voci < {node['minItems']}"))
        if "maxItems" in node and len(value) > node["maxItems"]:
            issues.append(SchemaIssue(path, "maxItems", field,
                                      f"{len(value)} voci > {node['maxItems']}"))
        if "items" in node:
            for position, item in enumerate(value):
                issues += schema_issues(root, node["items"], item,
                                        path + (position,))
    return issues


#: Classificazione ATTRIBUITA di uno scostamento di schema: il codice e'
#: quello del contratto che il campo misura. Una proprieta' inattesa e'
#: SEMPRE `data_room_manifest_invalid`.
FIELD_CODES = {
    ("documents", "document_id"): CODE_DUPLICATE_ID,
    ("documents", "section_id"): CODE_SECTION_INVALID,
    ("documents", "artifact_type"): CODE_ARTIFACT_TYPE,
    ("documents", "origin"): CODE_ORIGIN,
    ("documents", "derived_from"): CODE_ORIGIN,
    ("documents", "path"): CODE_BROKEN_PATH,
    ("documents", "checksum"): CODE_CHECKSUM,
    ("documents", "version"): CODE_VERSION,
    ("documents", "owner"): CODE_OWNER,
    ("documents", "confidentiality"): CODE_CONFIDENTIALITY,
    ("documents", "related_claims"): CODE_CLAIM_NAMESPACE,
    ("documents", "related_section"): CODE_SECTION_INVALID,
    ("documents", "validation_status"): CODE_VALIDATION_STATUS,
    ("documents", "availability"): CODE_REQUIRED_MISSING,
    ("documents", "source_ref"): CODE_QUALITY,
    ("documents", "evidence_quality"): CODE_QUALITY,
    ("documents", "evidence_refs"): CODE_CLAIM_LINK,
    ("claims", "claim_id"): CODE_CLAIM_NAMESPACE,
    ("claims", "related_section"): CODE_SECTION_INVALID,
    ("claims", "provenance"): CODE_PROVENANCE,
    ("claims", "section"): CODE_PROVENANCE,
    ("claims", "paragraph_anchor"): CODE_PROVENANCE,
    ("claims", "assumption_refs"): CODE_CLAIM_LINK,
    ("claims", "evidence_links"): CODE_CLAIM_LINK,
    ("claims", "evidence_ref"): CODE_CLAIM_LINK,
    ("claims", "document_id"): CODE_CLAIM_LINK,
    ("claims", "document_path"): CODE_CLAIM_LINK,
    ("claims", "status"): CODE_CLAIM_STATUS,
    ("claims", "evidence_class"): CODE_HIERARCHY,
    ("claims", "materiality"): CODE_UNSUPPORTED,
    ("claims", "support_status"): CODE_UNSUPPORTED,
    ("evidence_index", "evidence_ref"): CODE_CLAIM_LINK,
    ("evidence_index", "classification"): CODE_HIERARCHY,
    ("evidence_index", "register_status"): CODE_STALE,
    ("evidence_index", "date"): CODE_STALE,
    ("evidence_index", "freshness"): CODE_STALE,
    ("evidence_index", "verification"): CODE_STALE,
    ("evidence_index", "linked_claims"): CODE_ORPHAN,
    ("evidence_index", "linked_documents"): CODE_ORPHAN,
    ("evidence_index", "orphan"): CODE_ORPHAN,
    ("proposal", "as_of"): CODE_STALE,
    ("proposal", "max_age_days"): CODE_STALE,
}
CONTAINER_CODES = {
    "sections": CODE_SECTION_MISSING,
    "evidence_index": CODE_ORPHAN,
    "unresolved_evidence_gaps": CODE_GAP,
    "stale_evidence": CODE_STALE,
    "conflicts": CODE_CONFLICT,
    "orphan_evidence": CODE_ORPHAN,
    "unsupported_claims": CODE_UNSUPPORTED,
    "completeness": CODE_COMPLETENESS,
    "open_items": CODE_DEBT,
    "identity": CODE_VOLATILE,
    "staleness_policy": CODE_STALE,
}
PROPOSAL_CONTAINERS = {"sources": "documents", "expected": "documents",
                       "claims": "claims"}


def issue_code(issue, proposal=False):
    if issue.keyword == "additionalProperties":
        return CODE_MANIFEST_INVALID
    names = [part for part in issue.path if isinstance(part, str)]
    if proposal:
        container = names[0] if names else None
        if container in PROPOSAL_CONTAINERS:
            container = PROPOSAL_CONTAINERS[container]
        elif container is None:
            return FIELD_CODES.get(("proposal", issue.field),
                                   CODE_MANIFEST_INVALID)
        else:
            return FIELD_CODES.get(("proposal", container),
                                   CODE_MANIFEST_INVALID)
    else:
        if names[:1] != ["data_room"]:
            return CODE_MANIFEST_INVALID
        if len(names) == 1:
            return CONTAINER_CODES.get(issue.field, CODE_MANIFEST_INVALID)
        container = names[1]
    code = FIELD_CODES.get((container, issue.field))
    if code is None and issue.field not in (None, container):
        for name in reversed(names[2:] if not proposal else names[1:]):
            code = FIELD_CODES.get((container, name))
            if code:
                break
    return code or CONTAINER_CODES.get(container, CODE_MANIFEST_INVALID)


def issue_ref(issue):
    parts = [str(part) if isinstance(part, str) else f"[{part}]"
             for part in issue.path]
    location = ".".join(parts).replace(".[", "[")
    if issue.keyword in ("required", "additionalProperties"):
        location = f"{location}.{issue.field}" if location else issue.field
    return location or "$"


# --------------------------------------------------------------------------
# Contenimento dei path — la STESSA regola di `safe_rel_path`
# --------------------------------------------------------------------------


def unsafe_path_reason(rel):
    """`None` se `rel` e' un path relativo POSIX canonico; altrimenti il
    motivo del rifiuto. E' la STESSA regola di `safe_rel_path` del
    Transaction Manager (niente assoluti, `..`, `.`, backslash, lettera di
    drive, `~` o componenti vuoti), riprodotta qui perche' il validator non
    importa il Transaction Manager (confine degli import): il codice
    `path_escape` e' quello del Transaction Manager, riusato verbatim."""
    if not isinstance(rel, str) or not rel:
        return f"path non valido: {rel!r}"
    if "\\" in rel or ":" in rel or rel.startswith("/") or \
            rel.startswith("~"):
        return f"path non relativo/canonico: {rel!r}"
    for part in rel.split("/"):
        if part in ("", ".", ".."):
            return f"path con componente vietato: {rel!r}"
    return None


def _is_link_or_reparse(path):
    """True per symlink (ogni OS) e per junction/symlink reparse point NTFS:
    la STESSA regola del Transaction Manager. Altri reparse point (per
    esempio i file su richiesta di un servizio di sincronizzazione) non sono
    collegamenti e non escono dal progetto."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat_module.S_ISLNK(info.st_mode):
        return True
    if os.name == "nt":
        attrs = getattr(info, "st_file_attributes", 0)
        if attrs & getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            tag = getattr(info, "st_reparse_tag", 0)
            if tag in (getattr(stat_module, "IO_REPARSE_TAG_SYMLINK",
                               0xA000000C),
                       getattr(stat_module, "IO_REPARSE_TAG_MOUNT_POINT",
                               0xA0000003)):
                return True
    return False


def contained(project, rel):
    """Il path risolto dentro il progetto, oppure il motivo per cui NON e'
    contenuto: symlink o reparse point attraversati, uscita dal progetto."""
    reason = unsafe_path_reason(rel)
    if reason:
        return None, reason
    current = Path(project)
    for part in rel.split("/"):
        current = current / part
        if _is_link_or_reparse(current):
            return None, f"il path attraversa un symlink/reparse point: {rel!r}"
    try:
        inside = current.resolve().is_relative_to(Path(project).resolve())
    except OSError:
        inside = False
    if not inside:
        return None, f"il path esce dal progetto: {rel!r}"
    return current, None


def normalized_path(rel):
    return unicodedata.normalize("NFC", str(rel)).casefold()


def hidden_segment(rel):
    return any(part.startswith(".") for part in str(rel).split("/"))


def canonical_rel(project, rel):
    """La grafia CANONICA su disco di `rel`, relativa al progetto: la
    risoluzione del sistema operativo (`os.path.realpath`) normalizza
    maiuscole, nomi 8.3 e punto o spazio finali di ogni componente ESISTENTE;
    la coda inesistente resta come dichiarata. `None` se la risoluzione esce
    dal progetto."""
    base = os.path.realpath(project)
    try:
        resolved = os.path.realpath(os.path.join(base, *str(rel).split("/")))
        return Path(resolved).relative_to(base).as_posix()
    except (OSError, ValueError):
        return None


def path_alias_reason(project, rel):
    """`None` se `rel` e' la grafia canonica del proprio file; altrimenti il
    motivo. Un alias NTFS — maiuscole, nome 8.3, punto o spazio finale —
    nominerebbe lo STESSO file con un altro path ed eluderebbe unicita' e
    guardie d'area. Il punto e lo spazio finali sono
    respinti anche per i path inesistenti, che nessuna risoluzione vede."""
    if any(part != part.rstrip(". ") for part in str(rel).split("/")):
        return (f"{rel!r} ha un componente con punto o spazio finale: su "
                "Windows e' l'alias di un altro nome")
    canonical = canonical_rel(project, rel)
    if canonical is None:
        return f"{rel!r} risolve fuori dal progetto"
    if canonical != rel:
        return (f"{rel!r} non e' la grafia canonica del file: il sistema lo "
                f"risolve in {canonical!r}")
    return None


def file_identity(path):
    """L'identita' del file per il sistema (volume, indice del file): due
    path che la condividono sono lo STESSO file."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_dev, info.st_ino) if info.st_ino else None


def tx_reason(tx):
    """`None` se `--tx` e' un singolo segmento sicuro; altrimenti il motivo:
    un separatore, una lettera di drive o `:` porterebbero il candidate fuori
    da `12_data-room/.working/`."""
    if not TX_RE.match(str(tx)) or str(tx).endswith("."):
        return (f"--tx {tx!r} non e' un singolo segmento sicuro: ammessi "
                "[A-Za-z0-9._-], senza separatori, lettera di drive, ':' o "
                "punto finale")
    return None


def write_target(project, rel):
    """Il bersaglio di SCRITTURA (o di lettura del candidate) `rel` del
    costruttore, oppure il motivo del rifiuto: la STESSA regola di
    `resolve_in_project` del Transaction Manager — nessun componente
    symlink/junction/reparse, containment finale — ristretta all'area
    di scrittura `12_data-room/` nella grafia canonica. Verificata PRIMA di
    leggere la proposta e di nuovo PRIMA di ogni scrittura del pubblicatore:
    l'impronta del progetto, calcolata prima di `publish`, non basta."""
    if str(rel).split("/", 1)[0] != STAGE12:
        return None, f"{rel!r} e' fuori dall'area di scrittura {STAGE12}/"
    target, reason = contained(project, rel)
    if reason:
        return None, reason
    area = Path(os.path.realpath(project)) / STAGE12
    try:
        inside = Path(os.path.realpath(target)).is_relative_to(area)
    except (OSError, ValueError):
        inside = False
    alias = path_alias_reason(project, rel)
    if alias or not inside:
        return None, alias or f"{rel!r} risolve fuori da {STAGE12}/"
    return target, None


def reference_kind(value):
    """Classificazione di `url_or_path` del registro delle fonti, che lo
    schema ammette come stringa LIBERA:
      `external`  URL o URI con schema (`https:`, `mailto:`, `doi:`), dominio
                  nudo, citazione o annotazione: resta nel registro, non e'
                  un file da indicizzare;
      `escape`    un path di filesystem che esce dal progetto (assoluto,
                  lettera di drive, backslash o UNC, `~`, `.` o `..`):
                  respinto `path_escape`, mai letto;
      `path`      un path relativo di progetto: indicizzato SOLO se il file
                  esiste, altrimenti e' un riferimento `external`."""
    if not isinstance(value, str) or not value.strip():
        return "external"
    if URI_SCHEME_RE.match(value):
        return "external"
    if unsafe_path_reason(value) is None:
        return "path"
    if value.startswith(("/", "\\", "~")) or DRIVE_RE.match(value) or \
            "\\" in value or any(part in (".", "..")
                                 for part in value.split("/")):
        return "escape"
    return "external"


# --------------------------------------------------------------------------
# Registri e stato di progetto — letti FAIL-CLOSED
# --------------------------------------------------------------------------


def load_register(project, rel):
    """ASSENTE vale elenco vuoto; PRESENTE ma corrotto, o non un elenco, e'
    stato canonico corrotto (exit 3): mai un registro vuoto per default."""
    target = Path(project).joinpath(rel)
    if not target.is_file():
        return []
    try:
        entries = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise fw.CanonicalStateError(f"registro {rel} corrotto: {exc}")
    if not isinstance(entries, list):
        raise fw.CanonicalStateError(f"registro {rel} non e' un elenco")
    return entries


def register_ids(entries, rel, canonical_re, loose_re):
    """Gli id nella forma CANONICA di un registro (`PREFISSO-NNN`, almeno tre
    cifre) e, per OGNI voce che non lo e', un rilievo ATTRIBUITO: un alias
    e' RICONOSCIUTO e respinto, mai normalizzato o scartato in silenzio."""
    ids = {}
    problems = []
    for position, entry in enumerate(entries):
        ref = entry.get("id") if isinstance(entry, dict) else None
        if isinstance(ref, str) and canonical_re.match(ref):
            if ref in ids:
                problems.append((ref, f"{rel}: identificatore {ref!r} "
                                      "DUPLICATO"))
                continue
            ids[ref] = entry
        elif isinstance(ref, str) and loose_re.match(ref):
            problems.append((ref, f"{rel}: identificatore {ref!r} "
                                  "RICONOSCIUTO come alias NON canonico della "
                                  "forma canonica degli id e RESPINTO: non e' "
                                  "normalizzato ne' scartato in silenzio"))
        else:
            label = ref if isinstance(ref, str) and ref \
                else f"{rel}[{position}]"
            problems.append((label, f"{rel}: voce {label!r} con "
                                    "identificatore in forma libera o assente"))
    return ids, problems


class Registers:
    def __init__(self, project):
        self.assumptions = {}
        for entry in load_register(project, ASSUMPTIONS_REL):
            if isinstance(entry, dict) and ASS_RE.match(str(entry.get("id"))):
                self.assumptions[entry["id"]] = entry
        self.problems = []
        self.evidence, problems = register_ids(
            load_register(project, EVIDENCE_REL), EVIDENCE_REL, EVD_RE,
            LOOSE_EVD_RE)
        self.problems += problems
        self.sources, problems = register_ids(
            load_register(project, SOURCE_REL), SOURCE_REL, SRC_RE,
            LOOSE_SRC_RE)
        self.problems += problems
        self.conditions, problems = register_ids(
            load_register(project, CONDITIONS_REL), CONDITIONS_REL, COND_RE,
            LOOSE_COND_RE)
        self.problems += problems


def read_status(project):
    path = Path(project).joinpath(STATUS_REL)
    if not path.is_file():
        raise fw.CanonicalStateError(f"{STATUS_REL} assente")
    return fw.parse_front_matter(path.read_text(encoding="utf-8"))


def stage_ordinal(config, stage):
    order = config["stage_order"]
    return int(order[stage]) if stage in order else None


def boundary_ordinal(config):
    return stage_ordinal(config, config.get("release_boundary")) or 0


def completed_within(status, config):
    """Gli stage completati indicizzabili: ordinale da 0 a quello dello
    stage PRECEDENTE la Data Room (la Data Room non indicizza se stessa)."""
    own = stage_ordinal(config, STAGE12)
    completed = [stage for stage in status.get("completed_stages") or []
                 if isinstance(stage, str) and
                 stage_ordinal(config, stage) is not None and
                 stage_ordinal(config, stage) < own]
    return sorted(completed, key=lambda stage: stage_ordinal(config, stage))


def required_paths(status, config):
    """Gli artefatti OBBLIGATORI: i tre registri, l'uscita
    canonica di ogni stage completato con ordinale da 1, i derivati
    obbligatori degli Stage 10 e 11 completati."""
    paths = list(REQUIRED_REGISTERS)
    for stage in completed_within(status, config):
        if stage_ordinal(config, stage) >= 1:
            paths.append(f"{stage}/{CANONICAL_NAME}")
        for name in STAGE_DERIVED.get(stage, ()):
            paths.append(f"{stage}/{name}")
    return paths


def generated_type_of(rel, config):
    """Il tipo GENERATO che `rel` ha per costruzione, o `None` se `rel` non e'
    un artefatto del sistema: un registro condiviso, oppure l'uscita
    canonica, l'handoff o un derivato dichiarato di uno stage PRECEDENTE la
    Data Room. Un file dell'utente non diventa generato dichiarandolo tale."""
    rel = str(rel)
    if rel in REQUIRED_REGISTERS + OPTIONAL_REGISTERS:
        return "shared_register"
    parts = rel.split("/")
    ordinal = stage_ordinal(config, parts[0]) if len(parts) == 2 else None
    if ordinal is None or ordinal >= stage_ordinal(config, STAGE12):
        return None
    stage, name = parts
    if name == CANONICAL_NAME:
        return "stage_canonical_output" if ordinal >= 1 else None
    if name == HANDOFF_NAME:
        return "stage_handoff"
    if name in STAGE_DERIVED.get(stage, ()):
        return GENERATED_NAMES[name]
    return None


# --------------------------------------------------------------------------
# Regole derivate — un'unica definizione per costruttore e validator
# --------------------------------------------------------------------------


def evidence_ok(evidence_ref, registers):
    entry = registers.evidence.get(evidence_ref)
    return entry is not None and entry.get("status") != "rejected"


def support_of(claim, registers):
    """`supported` se esiste un legame `supporting` a un'evidenza REGISTRATA,
    non respinta e di classe probatoria, e nessuna contraddizione;
    `contested` se un legame `supporting` e uno `contradicting` coesistono;
    `unsupported` altrimenti. OGNI claim registrato e' MATERIALE."""
    links = [link for link in claim.get("evidence_links") or []
             if isinstance(link, dict)]
    supporting = [link for link in links if link.get("status") ==
                  "supporting" and link.get("evidence_ref")]
    contradicting = [link for link in links if link.get("status") ==
                     "contradicting" and link.get("evidence_ref")]
    if supporting and contradicting:
        return "contested"
    for link in supporting:
        ref = link.get("evidence_ref")
        entry = registers.evidence.get(ref) or {}
        if evidence_ok(ref, registers) and \
                entry.get("classification") in EVIDENTIAL_CLASSES:
            return "supported"
    return "unsupported"


def freshness_of(value, reference, max_age):
    if not isinstance(value, str) or not ISO_DATE_RE.match(value):
        return "undated"
    try:
        stamp = date.fromisoformat(value)
    except ValueError:
        return "undated"
    age = (reference - stamp).days
    if age < 0:
        return "undated"
    return "current" if age <= max_age else "stale"


def normalized_statement(text):
    return " ".join(str(text or "").casefold().split())


def relevant_evidence(claim, registers):
    """Le evidenze REGISTRATE che toccano le assunzioni del claim: devono
    comparire TUTTE fra i suoi legami, mai fuse in una sola."""
    refs = set(claim.get("assumption_refs") or [])
    return sorted((ref for ref, entry in registers.evidence.items()
                   if refs & set(entry.get("affected_assumptions") or [])),
                  key=id_number)


def derive_conflicts(claims, registers):
    records = []
    for claim in claims:
        links = claim.get("evidence_links") or []
        supporting = sorted({link.get("evidence_ref") for link in links
                             if link.get("status") == "supporting" and
                             link.get("evidence_ref")}, key=id_number)
        contradicting = sorted({link.get("evidence_ref") for link in links
                                if link.get("status") == "contradicting" and
                                link.get("evidence_ref")}, key=id_number)
        for first in supporting:
            for second in contradicting:
                records.append(("contradiction", claim.get("claim_id"),
                                first, second))
    refs = sorted(registers.evidence, key=id_number)
    for position, first in enumerate(refs):
        for second in refs[position + 1:]:
            left = normalized_statement(
                registers.evidence[first].get("statement"))
            if left and left == normalized_statement(
                    registers.evidence[second].get("statement")):
                records.append(("duplicate", None, first, second))
    return sorted(records, key=lambda item: (
        CONFLICT_KINDS.index(item[0]), id_number(item[1]), id_number(item[2]),
        id_number(item[3])))


def conflict_record(position, kind, claim_id, first, second):
    if kind == "contradiction":
        decision = ("Confermare quale evidenza prevale o registrarne una "
                    "nuova: non mediare, non scegliere la piu' recente")
        severity = "High"
    else:
        decision = ("Unificare le due voci del registro delle evidenze con "
                    "una decisione tracciata: non fonderle in silenzio")
        severity = "Medium"
    return {"issue_id": f"ISSUE-DR-{position:03d}", "kind": kind,
            "claim_id": claim_id, "evidence_a": first, "evidence_b": second,
            "severity": severity, "decision_required": decision,
            "files": [EVIDENCE_REL, f"{STAGE12}/{CANONICAL_NAME}"]}


def derive_gaps(claims, registers):
    gaps = []
    for claim in claims:
        if claim.get("support_status") == "unsupported":
            gaps.append(("claim_unsupported", claim.get("claim_id"),
                         "claim materiale senza evidenza probatoria "
                         "collegata"))
        if any(link.get("status") == "missing"
               for link in claim.get("evidence_links") or []):
            gaps.append(("missing_link", claim.get("claim_id"),
                         "legame di evidenza dichiarato mancante"))
    for ref, entry in registers.assumptions.items():
        if not entry.get("evidence_refs"):
            gaps.append(("assumption_without_evidence_refs", ref,
                         "l'assunzione non porta evidence_refs: il legame "
                         "ASS -> EVD non e' strutturato"))
    for ref, entry in registers.evidence.items():
        if entry.get("classification") == "missing_information":
            gaps.append(("missing_information", ref,
                         "evidenza registrata come missing_information"))
    return sorted(gaps, key=lambda item: (GAP_KINDS.index(item[0]),
                                          id_number(item[1])))


def derive_completeness(claims, registers):
    """Metriche ricalcolate dall'AUTORITA' — il supporto dal registro delle
    evidenze, la classe di ogni legame dal registro — e mai lette dai campi
    che il documento dichiara: ogni percentuale e' accompagnata da
    denominatore e distribuzione per classe."""
    total = len(claims)
    supported = sum(1 for claim in claims
                    if support_of(claim, registers) == "supported")
    distribution = {name: 0 for name in EVIDENCE_CLASSES}
    for claim in claims:
        for link in claim.get("evidence_links") or []:
            if not isinstance(link, dict):
                continue
            ref = link.get("evidence_ref")
            if ref is None:
                name = "missing_information"
            else:
                name = (registers.evidence.get(ref) or {}).get(
                    "classification")
            if name in distribution:
                distribution[name] += 1
    percent = None
    if total:
        percent = str((Decimal(supported) * 100 / Decimal(total))
                      .quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))
    return {"denominator": "registered_claims", "claims_total": total,
            "claims_supported": supported, "coverage_percent": percent,
            "class_distribution": distribution}


def derive_open_items(registers):
    items = []
    for ref in sorted(registers.conditions, key=id_number):
        entry = registers.conditions[ref]
        closed = entry.get("resolution_status") in ("resolved", "waived") \
            and isinstance(entry.get("resolved_by"), str)
        items.append({"item_ref": ref, "origin": CONDITIONS_REL,
                      "status": "CHIUSO" if closed else "APERTO",
                      "proof_ref": entry.get("resolved_by") if closed
                      else None})
    return items


def expected_derived_from(entry, by_path):
    path = str(entry.get("path") or "")
    if entry.get("origin") != "generated" or "/" not in path:
        return []
    stage, name = path.split("/", 1)
    original = by_path.get(f"{stage}/{CANONICAL_NAME}")
    if original is None or name == CANONICAL_NAME:
        return []
    if name == HANDOFF_NAME or name in STAGE_DERIVED.get(stage, ()):
        return [original.get("document_id")]
    return []


def evidence_index(documents, claims, registers, reference, max_age):
    records = []
    for ref in sorted(registers.evidence, key=id_number):
        entry = registers.evidence[ref]
        linked_claims = sorted({claim.get("claim_id") for claim in claims
                                for link in claim.get("evidence_links") or []
                                if link.get("evidence_ref") == ref},
                               key=id_number)
        linked_documents = sorted({item.get("document_id")
                                   for item in documents
                                   if ref in (item.get("evidence_refs") or [])},
                                  key=id_number)
        raw_date = entry.get("date")
        records.append({
            "evidence_ref": ref,
            "classification": entry.get("classification"),
            "register_status": entry.get("status"),
            "date": raw_date if isinstance(raw_date, str) and raw_date
            else None,
            "freshness": freshness_of(raw_date, reference, max_age),
            "verification": "verified" if entry.get("status") == "validated"
            else "unverified",
            "linked_claims": linked_claims,
            "linked_documents": linked_documents,
            "orphan": not linked_claims and not linked_documents,
        })
    return records


def related_claims_of(document_id, claims):
    return sorted({claim.get("claim_id") for claim in claims
                   for link in claim.get("evidence_links") or []
                   if link.get("document_id") == document_id},
                  key=id_number)


def link_sort_key(link):
    return (id_number(link.get("evidence_ref")) if link.get("evidence_ref")
            else 10 ** 9,
            id_number(link.get("document_id")) if link.get("document_id")
            else 10 ** 9,
            LINK_STATUSES.index(link.get("status"))
            if link.get("status") in LINK_STATUSES else 9)


# --------------------------------------------------------------------------
# COSTRUZIONE
# --------------------------------------------------------------------------


def system_entry(path, artifact_type, related_section, section_id, title,
                 validation_status):
    return {"path": path, "artifact_type": artifact_type,
            "origin": "generated", "owner": "orchestrator",
            "related_section": related_section, "section_id": section_id,
            "title": title, "validation_status": validation_status,
            "source_ref": None, "evidence_refs": [], "version": None,
            "last_verified_at": None, "generated_at": None, "kind": "system"}


def build_document(project, proposal, config, status, registers):
    """Il manifest DERIVATO dalla proposta DICHIARATA e dallo stato del
    progetto. Ogni rifiuto e' ATTRIBUITO; nessun file e' scritto qui."""
    errors = []
    project = Path(project)
    for ref, message in registers.problems:
        errors.append((CODE_DUPLICATE_ID, ref, message))
    reference = date.fromisoformat(proposal["as_of"])
    max_age = int(proposal["max_age_days"])
    boundary = boundary_ordinal(config)
    completed = completed_within(status, config)

    def section_ok(stage):
        ordinal = stage_ordinal(config, stage)
        return ordinal is not None and ordinal <= boundary

    entries = []
    for rel in REQUIRED_REGISTERS + OPTIONAL_REGISTERS:
        if rel in REQUIRED_REGISTERS or project.joinpath(rel).is_file():
            entries.append(system_entry(
                rel, "shared_register", REGISTER_ANCHOR_STAGE,
                REGISTER_SECTIONS[rel], REGISTER_TITLES[rel], "open"))
    for stage in completed:
        section = STAGE_SECTIONS.get(stage, "11_generated-artifact-metadata")
        if stage_ordinal(config, stage) >= 1:
            entries.append(system_entry(
                f"{stage}/{CANONICAL_NAME}", "stage_canonical_output", stage,
                section, f"Uscita canonica dello stage {stage}", "validated"))
        for name in STAGE_DERIVED.get(stage, ()):
            entries.append(system_entry(
                f"{stage}/{name}", GENERATED_NAMES[name], stage, section,
                f"Artefatto derivato {name} dello stage {stage}",
                "validated"))
        if project.joinpath(stage, HANDOFF_NAME).is_file():
            entries.append(system_entry(
                f"{stage}/{HANDOFF_NAME}", "stage_handoff", stage,
                "11_generated-artifact-metadata",
                f"Handoff dello stage {stage}", "validated"))
    def path_key(rel):
        # Identita' di un path per l'unicita': la grafia CANONICA su disco,
        # poi NFC + casefold.
        return normalized_path(canonical_rel(project, rel) or rel)

    seen = {path_key(entry["path"]): entry for entry in entries}
    declared = {}

    # Fonti del registro che sono FILE del progetto: un URL, un dominio
    # nudo, un DOI o una citazione restano
    # nel registro e non bloccano lo Stage 12; un path di filesystem che esce
    # dal progetto e' `path_escape`, mai letto.
    for ref in sorted(registers.sources, key=id_number):
        source = registers.sources[ref]
        rel = source.get("url_or_path")
        kind = reference_kind(rel)
        if kind == "escape":
            errors.append((CODE_PATH_ESCAPE, ref,
                           f"{SOURCE_REL}: {unsafe_path_reason(rel)}"))
            continue
        if kind == "external":
            continue
        target, reason = contained(project, rel)
        if reason:
            errors.append((CODE_PATH_ESCAPE, ref, f"{SOURCE_REL}: {reason}"))
            continue
        if not target.is_file():
            continue
        stage = rel.split("/", 1)[0]
        related = stage if stage in STAGE_SECTIONS else REGISTER_ANCHOR_STAGE
        refs = [item for item in source.get("used_for") or []
                if isinstance(item, str) and EVD_RE.match(item) and
                item in registers.evidence]
        entry = {"path": rel, "artifact_type": source.get("source_type")
                 if source.get("source_type") in SOURCE_TYPES else "other",
                 "origin": "source", "owner": "founder",
                 "related_section": related,
                 "section_id": "10_source-evidence-and-provenance",
                 "title": source.get("title") or rel,
                 "validation_status": "open", "source_ref": ref,
                 "evidence_refs": refs, "version": None,
                 "last_verified_at": None, "generated_at": None,
                 "kind": "source"}
        key = path_key(rel)
        if key in seen:
            errors.append((CODE_DUPLICATE_ID, rel,
                           f"il path {rel!r} e' gia' indicizzato"))
            continue
        seen[key] = entry
        entries.append(entry)

    for position, item in enumerate(proposal.get("sources") or []):
        rel = item["path"]
        key = path_key(rel)
        # Una fonte si dichiara UNA volta: una seconda dichiarazione con la
        # stessa identita' (anche dopo NFC/NFD o un alias) e' respinta, mai
        # fusa per «vince l'ultima».
        if key in declared:
            errors.append((CODE_DUPLICATE_ID, rel,
                           f"proposta sources[{position}]: {rel!r} ha la "
                           f"stessa identita' di {declared[key]}: una fonte "
                           "si dichiara una sola volta, mai fusione"))
            continue
        declared[key] = f"proposta sources[{position}]"
        existing = seen.get(key)
        if existing is not None and existing.get("kind") != "source":
            errors.append((CODE_ORIGIN, rel,
                           f"proposta sources[{position}]: {rel!r} e' un "
                           "artefatto GENERATO, non una fonte"))
            continue
        if existing is not None and existing["path"] != rel:
            errors.append((CODE_DUPLICATE_ID, rel,
                           f"proposta sources[{position}]: {rel!r} ha la "
                           f"stessa identita' della fonte registrata "
                           f"{existing['path']!r}: nessuna dichiarazione e' "
                           "scartata in silenzio"))
            continue
        declared_ref = item.get("source_ref")
        if existing is not None:
            if declared_ref not in (None, existing["source_ref"]):
                errors.append((CODE_QUALITY, rel,
                               f"proposta sources[{position}]: source_ref "
                               f"{declared_ref!r} diverge dal registro "
                               f"({existing['source_ref']})"))
                continue
            entry = existing
        else:
            registered = registers.sources.get(declared_ref) \
                if declared_ref is not None else None
            if declared_ref is not None and registered is None:
                errors.append((CODE_QUALITY, rel,
                               f"proposta sources[{position}]: source_ref "
                               f"{declared_ref!r} non registrata"))
                continue
            if registered is not None and \
                    registered.get("url_or_path") != rel:
                # La qualita' e' quella della STESSA fonte, mai di una voce
                # valida qualunque.
                errors.append((CODE_QUALITY, rel,
                               f"proposta sources[{position}]: source_ref "
                               f"{declared_ref!r} registra un'altra fonte "
                               f"({registered.get('url_or_path')!r})"))
                continue
            entry = {"path": rel, "origin": "source", "kind": "source",
                     "source_ref": declared_ref, "evidence_refs": [],
                     "generated_at": None}
            seen[key] = entry
            entries.append(entry)
        for field in ("artifact_type", "section_id", "related_section",
                      "owner", "validation_status", "title"):
            entry[field] = item[field]
        entry["version"] = item.get("version")
        entry["last_verified_at"] = item.get("last_verified_at")
        extra = [ref for ref in item.get("evidence_refs") or []]
        for ref in extra:
            if ref not in registers.evidence:
                errors.append((CODE_CLAIM_LINK, ref,
                               f"proposta sources[{position}]: evidence_ref "
                               f"{ref!r} non registrata"))
        entry["evidence_refs"] = sorted(set(entry["evidence_refs"]) |
                                        {ref for ref in extra
                                         if ref in registers.evidence},
                                        key=id_number)

    for position, item in enumerate(proposal.get("expected") or []):
        rel = item["path"]
        key = path_key(rel)
        if key in seen:
            errors.append((CODE_DUPLICATE_ID, rel,
                           f"proposta expected[{position}]: il path {rel!r} "
                           "e' gia' indicizzato"))
            continue
        entry = {"path": rel, "origin": "source", "kind": "expected",
                 "source_ref": None, "evidence_refs": [], "version": None,
                 "last_verified_at": None, "generated_at": None}
        for field in ("artifact_type", "section_id", "related_section",
                      "owner", "validation_status", "title"):
            entry[field] = item[field]
        seen[key] = entry
        entries.append(entry)

    # Disponibilita', checksum e versione, dai file REALI.
    required = set(required_paths(status, config))
    for entry in entries:
        rel = entry["path"]
        if not section_ok(entry["related_section"]):
            errors.append((CODE_SECTION_INVALID, rel,
                           f"related_section {entry['related_section']!r} "
                           "fuori da stage_order o oltre il release "
                           "boundary"))
        target, reason = contained(project, rel)
        if reason:
            errors.append((CODE_PATH_ESCAPE, rel, reason))
            continue
        # Le guardie d'area valgono per il file EFFETTIVAMENTE nominato: la
        # grafia canonica su disco, non l'alias dichiarato.
        canonical = canonical_rel(project, rel) or rel
        alias = path_alias_reason(project, rel)
        if alias:
            errors.append((CODE_PATH_ESCAPE, rel, alias))
        head_ordinal = stage_ordinal(config, canonical.split("/", 1)[0])
        if hidden_segment(canonical) or canonical.split("/", 1)[0] == STAGE12:
            errors.append((CODE_BROKEN_PATH, rel,
                           f"{rel!r} non e' un artefatto stabile indicizzabile"))
            continue
        if head_ordinal is not None and \
                head_ordinal > stage_ordinal(config, STAGE12):
            errors.append((CODE_SECTION_INVALID, rel,
                           f"{rel!r} appartiene a uno stage oltre la Data "
                           "Room"))
            continue
        if alias:
            continue
        present = target.is_file()
        if entry.get("kind") == "expected":
            if present:
                errors.append((CODE_REQUIRED_MISSING, rel,
                               f"{rel!r} e' dichiarato expected ma esiste: "
                               "va indicizzato come fonte disponibile"))
            entry["availability"] = "expected"
        elif present:
            entry["availability"] = "available"
        elif entry.get("kind") == "system" or rel in required:
            entry["availability"] = "missing"
        else:
            errors.append((CODE_BROKEN_PATH, rel,
                           f"la fonte {rel!r} non esiste nel progetto: "
                           "dichiararla expected, non indicizzare un path "
                           "rotto"))
            entry["availability"] = "missing"
        if entry["availability"] == "available":
            entry["checksum"] = sha256_file(target)
            if not entry.get("version"):
                entry["version"] = content_version(entry["checksum"])
        else:
            entry["checksum"] = None
            entry["version"] = entry["availability"]
        if entry["availability"] == "missing":
            entry["validation_status"] = "needs_info"
    if errors:
        raise BuildRefusal(errors)

    # Allocazione DR-*: ordine (ordinale della related_section, path).
    entries.sort(key=lambda entry: (stage_ordinal(
        config, entry["related_section"]), entry["path"]))
    by_path = {}
    for position, entry in enumerate(entries, start=1):
        entry["document_id"] = f"DR-{position:03d}"
        by_path[entry["path"]] = entry

    # Claim: gli id CLM-* sono allocati SOLO qui, dal costruttore.
    raw_claims = sorted(proposal["claims"], key=lambda item: (
        stage_ordinal(config, item["related_section"]) or 0, item["key"]))
    keys = [item["key"] for item in raw_claims]
    for key in sorted({key for key in keys if keys.count(key) > 1}):
        errors.append((CODE_CLAIM_NAMESPACE, key,
                       f"chiave di claim duplicata nella proposta: {key!r}"))
    claims = []
    for position, item in enumerate(raw_claims, start=1):
        claim_id = f"CLM-{position:03d}"
        if not section_ok(item["related_section"]):
            errors.append((CODE_SECTION_INVALID, claim_id,
                           f"related_section {item['related_section']!r} "
                           "fuori dal confine"))
        for ref in item["assumption_refs"]:
            if ref not in registers.assumptions:
                errors.append((CODE_CLAIM_LINK, claim_id,
                               f"assunzione {ref!r} non registrata"))
        links = []
        for link in item["evidence_links"]:
            ref = link.get("evidence_ref")
            document_id = None
            if link.get("document_path") is not None:
                target = by_path.get(link["document_path"])
                if target is None:
                    errors.append((CODE_CLAIM_LINK, claim_id,
                                   f"documento {link['document_path']!r} non "
                                   "indicizzato"))
                else:
                    document_id = target["document_id"]
            if ref is not None and ref not in registers.evidence:
                errors.append((CODE_CLAIM_LINK, claim_id,
                               f"evidenza {ref!r} non registrata"))
                continue
            klass = registers.evidence[ref].get("classification") \
                if ref is not None else "missing_information"
            links.append({"evidence_ref": ref, "document_id": document_id,
                          "status": link["status"], "evidence_class": klass})
        claim = {"claim_id": claim_id, "statement": item["statement"],
                 "related_section": item["related_section"],
                 "provenance": {"section": item["provenance"]["section"],
                                "paragraph_anchor":
                                item["provenance"]["paragraph_anchor"]},
                 "assumption_refs": sorted(set(item["assumption_refs"]),
                                           key=id_number),
                 "evidence_links": sorted(links, key=link_sort_key),
                 "materiality": "material"}
        for problem in claim_link_problems(claim, registers):
            errors.append(problem)
        claim["support_status"] = support_of(claim, registers)
        claims.append(claim)
    if errors:
        raise BuildRefusal(errors)

    documents = []
    for entry in entries:
        document = {
            "document_id": entry["document_id"],
            "section_id": entry["section_id"], "title": entry["title"],
            "artifact_type": entry["artifact_type"],
            "origin": entry["origin"], "path": entry["path"],
            "checksum": entry["checksum"], "version": entry["version"],
            "owner": entry["owner"], "confidentiality": "NOT_SUPPORTED",
            "related_claims": related_claims_of(entry["document_id"],
                                                claims),
            "related_section": entry["related_section"],
            "validation_status": entry["validation_status"],
            "availability": entry["availability"],
            "source_ref": entry["source_ref"],
            "evidence_quality": None,
            "evidence_refs": entry["evidence_refs"],
            "derived_from": [],
            "last_verified_at": entry["last_verified_at"],
            "generated_at": entry["generated_at"]}
        source = registers.sources.get(entry["source_ref"]) \
            if entry["source_ref"] else None
        if source is not None:
            document["evidence_quality"] = source.get("quality_rating")
        documents.append(document)
    by_path = {document["path"]: document for document in documents}
    for document in documents:
        document["derived_from"] = expected_derived_from(document, by_path)

    sections = []
    reasons = proposal.get("section_reasons") or {}
    for ordinal, (section_id, title) in enumerate(SECTIONS, start=1):
        ids = [document["document_id"] for document in documents
               if document["section_id"] == section_id]
        sections.append({
            "section_id": section_id, "ordinal": ordinal, "title": title,
            "status": "POPULATED" if ids else "NOT_APPLICABLE",
            "reason": None if ids else reasons.get(section_id,
                                                   "Nessun artefatto del "
                                                   "progetto rientra in questa "
                                                   "sezione alla data di "
                                                   f"riferimento "
                                                   f"{proposal['as_of']}: "
                                                   "sezione dichiarata "
                                                   "NOT_APPLICABLE, non "
                                                   "omessa."),
            "document_ids": ids})

    index = evidence_index(documents, claims, registers, reference, max_age)
    conflicts = [conflict_record(position, *item) for position, item in
                 enumerate(derive_conflicts(claims, registers), start=1)]
    gaps = [{"kind": kind, "ref": ref, "detail": detail}
            for kind, ref, detail in derive_gaps(claims, registers)]
    room = {
        "staleness_policy": {"criterion": STALENESS_CRITERION,
                             "reference_date": proposal["as_of"],
                             "max_age_days": max_age},
        "generated_at": proposal.get("generated_at"),
        "sections": sections,
        "documents": documents,
        "claims": claims,
        "evidence_index": index,
        "unresolved_evidence_gaps": gaps,
        "stale_evidence": [item["evidence_ref"] for item in index
                           if item["freshness"] != "current"],
        "conflicts": conflicts,
        "orphan_evidence": [item["evidence_ref"] for item in index
                            if item["orphan"]],
        "unsupported_claims": [claim["claim_id"] for claim in claims
                               if claim["support_status"] == "unsupported"],
        "completeness": derive_completeness(claims, registers),
        "open_items": derive_open_items(registers),
    }
    document = {"schema_version": SCHEMA_VERSION, "data_room": room}
    room["identity"] = {"algorithm": "sha256",
                        "excluded_fields": list(EXCLUDED_FIELDS),
                        "payload_sha256": identity_of(document)}
    return document


def claim_link_problems(claim, registers):
    """Coerenze del legame claim -> evidenza, UNA definizione per costruttore
    e validator: stato `missing` solo senza evidenza o su una
    `missing_information`; classe identica al registro; nessuna evidenza
    pertinente omessa (mai fusione)."""
    problems = []
    claim_id = claim.get("claim_id")
    linked = set()
    # Ogni evidenza — e il legame senza evidenza — si collega UNA volta:
    # un legame ripetuto gonfierebbe la distribuzione per classe.
    for ref in duplicated([link.get("evidence_ref")
                           for link in claim.get("evidence_links") or []
                           if isinstance(link, dict)]):
        problems.append((CODE_DUPLICATE_ID, claim_id,
                         f"legame all'evidenza {ref!r} DUPLICATO nel claim: "
                         "ogni evidenza si collega una sola volta"))
    for link in claim.get("evidence_links") or []:
        if not isinstance(link, dict):
            continue
        ref = link.get("evidence_ref")
        status = link.get("status")
        entry = registers.evidence.get(ref) if ref else None
        if ref:
            linked.add(ref)
        if ref and entry is None:
            # Il riferimento che non risolve e' gia' un legame invalido:
            # nessuno stato ne' classe si giudica su un'evidenza inesistente.
            continue
        klass = entry.get("classification") if entry else \
            "missing_information"
        missing_evidence = ref is None or klass == "missing_information"
        if status in LINK_STATUSES and (status == "missing") != \
                missing_evidence:
            problems.append((CODE_CLAIM_STATUS, claim_id,
                             f"legame {ref!r} di stato {status!r}: lo stato "
                             "`missing` spetta SOLO a un legame senza "
                             "evidenza o a una missing_information"))
        if link.get("evidence_class") != klass:
            problems.append((CODE_HIERARCHY, claim_id,
                             f"classe {link.get('evidence_class')!r} del "
                             f"legame {ref!r} diversa dalla classe "
                             f"registrata {klass!r}: le sei classi sono "
                             "esatte e mai promosse"))
    omitted = [ref for ref in relevant_evidence(claim, registers)
               if ref not in linked]
    if omitted:
        problems.append((CODE_CONFLICT, claim_id,
                         f"evidenze registrate sulle assunzioni del claim "
                         f"NON collegate: {omitted}; fondere o scartare "
                         "evidenze pertinenti nasconde un'INCOERENZA "
                         "RILEVATA"))
    return problems


# --------------------------------------------------------------------------
# Rese derivate: indice e handoff
# --------------------------------------------------------------------------


def inline(value):
    """Testo NON fidato — dell'analista o di un canonico esterno — reso su
    UNA riga e con il separatore di colonna `|` sfuggito: nessun terminatore
    di riga apre una riga strutturale del Markdown reso (riga di tabella
    `DR-*`, intestazione, recinto, `next_action`, blocco INCOERENZA) e nessun
    `|` forma una cella, nemmeno come testo. La resa resta una funzione
    deterministica del SOLO manifest."""
    return LINE_BREAKS_RE.sub(" ", str(value)).replace("|", "\\|")


def cell(value):
    return "-" if value is None or value == "" else inline(value)


def incoherence_block(conflict, claims):
    statement = ""
    for claim in claims:
        if claim.get("claim_id") == conflict.get("claim_id"):
            statement = f" — {inline(claim.get('statement'))}"
    variable = (f"{inline(conflict.get('claim_id'))}{statement}"
                if conflict.get("kind") == "contradiction"
                else "evidenza duplicata nel registro")
    files = ", ".join(inline(item) for item in conflict.get("files") or [])
    return ["```text", "INCOERENZA RILEVATA", "",
            f"ID: {inline(conflict.get('issue_id'))}",
            f"Variabile: {variable}",
            f"Valore A: {inline(conflict.get('evidence_a'))} ({EVIDENCE_REL})",
            f"Valore B: {inline(conflict.get('evidence_b'))} ({EVIDENCE_REL})",
            "Impatto: tracciabilita' claim -> evidenza della Data Room",
            f"Severità: {inline(conflict.get('severity'))}",
            f"Decisione richiesta: {inline(conflict.get('decision_required'))}",
            f"File coinvolti: {files}",
            "```", ""]


def entries_of(room, key):
    return [item for item in room.get(key) or [] if isinstance(item, dict)]


def distribution_text(completeness):
    """La distribuzione per classe nell'ordine FISSO delle sei classi (e poi
    le chiavi estranee in ordine), indipendente dall'ordine delle chiavi del
    JSON letto: la stessa resa al --build e in egress."""
    distribution = completeness.get("class_distribution")
    if not isinstance(distribution, dict):
        distribution = {}
    names = [name for name in EVIDENCE_CLASSES if name in distribution]
    names += sorted(str(name) for name in distribution
                    if name not in EVIDENCE_CLASSES)
    return ", ".join(f"{inline(name)} {inline(distribution.get(name))}"
                     for name in names)


def coverage_line(room, prefix):
    """La riga di copertura: la percentuale e' SEMPRE accompagnata dal
    denominatore e dalla distribuzione per classe."""
    completeness = room.get("completeness") or {}
    return (f"{prefix}{inline(completeness.get('coverage_percent'))}% dei "
            f"{inline(completeness.get('claims_total'))} claim registrati; "
            f"distribuzione per classe: {distribution_text(completeness)}")


def render_index(document):
    """L'indice DERIVATO `12_data-room/data-room-index.md`: resa
    deterministica del SOLO manifest canonico. La resa e' guidata dai
    documenti stessi — ogni voce del manifest ha la PROPRIA riga, anche su un
    manifest malformato — e non aggiunge nulla che il manifest non porti; il
    testo non fidato e' reso su una riga (`inline`, `cell`)."""
    room = (document or {}).get("data_room") or {}
    policy = room.get("staleness_policy") or {}
    documents = entries_of(room, "documents")
    claims = entries_of(room, "claims")
    lines = [
        "# Data Room — indice derivato", "",
        "> Artefatto DERIVATO dal manifest canonico "
        f"`{STAGE12}/{CANONICAL_NAME}` e pubblicato da "
        "`validate_data_room.py --build`. La fonte di verita' e' il "
        "manifest: questo indice non si modifica a mano.", "",
        f"- Identita' del manifest: `sha256:"
        f"{inline((room.get('identity') or {}).get('payload_sha256'))}`",
        f"- Data di riferimento: {inline(policy.get('reference_date'))} · "
        f"soglia di staleness: {inline(policy.get('max_age_days'))} giorni",
        f"- Documenti: {len(documents)} · claim: {len(claims)} · lacune: "
        f"{len(entries_of(room, 'unresolved_evidence_gaps'))} · conflitti: "
        f"{len(entries_of(room, 'conflicts'))}",
        coverage_line(room, "- Copertura: "),
        ""]
    sections = {item.get("section_id"): item for item in
                entries_of(room, "sections")}
    blocks = list(SECTIONS)
    stray = sorted({str(entry.get("section_id")) for entry in documents
                    if entry.get("section_id") not in SECTION_IDS})
    blocks += [(section_id, "sezione non riconosciuta")
               for section_id in stray]
    for section_id, title in blocks:
        rows = [entry for entry in documents
                if str(entry.get("section_id")) == section_id]
        lines.append(f"## {inline(section_id)} — {title}")
        lines.append("")
        section = sections.get(section_id) or {}
        if not rows:
            lines.append(
                f"Stato: {inline(section.get('status', 'NOT_APPLICABLE'))}"
                f" — {inline(section.get('reason'))}")
            lines.append("")
            continue
        lines.append("| document_id | versione | tipo | origine | "
                     "disponibilita' | path | claim |")
        lines.append("|---|---|---|---|---|---|---|")
        for entry in rows:
            claims_cell = ", ".join(map(str, entry.get("related_claims")
                                        or []))
            lines.append(
                f"| {cell(entry.get('document_id'))} | "
                f"{cell(entry.get('version'))} | "
                f"{cell(entry.get('artifact_type'))} | "
                f"{cell(entry.get('origin'))} | "
                f"{cell(entry.get('availability'))} | "
                f"{cell(entry.get('path'))} | {cell(claims_cell)} |")
        lines.append("")
    lines += ["## Claim registrati", "",
              "| claim_id | sezione | supporto | legami |",
              "|---|---|---|---|"]
    for claim in claims:
        links = ", ".join(
            f"{link.get('evidence_ref') or '-'}:{link.get('status')}"
            for link in claim.get("evidence_links") or []
            if isinstance(link, dict))
        lines.append(f"| {cell(claim.get('claim_id'))} | "
                     f"{cell(claim.get('related_section'))} | "
                     f"{cell(claim.get('support_status'))} | {cell(links)} |")
    lines += ["", "## Lacune di evidenza irrisolte", ""]
    gaps = entries_of(room, "unresolved_evidence_gaps")
    for gap in gaps:
        lines.append(f"- `{inline(gap.get('ref'))}` — "
                     f"{inline(gap.get('kind'))}: {inline(gap.get('detail'))}")
    if not gaps:
        lines.append("- nessuna")
    lines += ["", "## Incoerenze", ""]
    conflicts = entries_of(room, "conflicts")
    for conflict in conflicts:
        lines += incoherence_block(conflict, claims)
    if not conflicts:
        lines += ["- nessuna", ""]
    lines += ["## Voci aperte", ""]
    items = entries_of(room, "open_items")
    for item in items:
        proof = f", prova {inline(item.get('proof_ref'))}" \
            if item.get("proof_ref") else ""
        lines.append(f"- `{inline(item.get('item_ref'))}` — "
                     f"{inline(item.get('status'))}{proof}")
    if not items:
        lines.append("- nessuna")
    lines.append("")
    return "\n".join(lines)


def open_items_line(room):
    open_items = ", ".join(f"{inline(item.get('item_ref'))} "
                           f"{inline(item.get('status'))}"
                           for item in entries_of(room, "open_items"))
    return f"- Voci aperte: {open_items or 'nessuna'}"


def handoff_coverage_line(room):
    claims = entries_of(room, "claims")
    support = {state: sum(1 for claim in claims
                          if claim.get("support_status") == state)
               for state in ("supported", "unsupported", "contested")}
    return coverage_line(
        room, f"- Claim registrati: {len(claims)} (supported "
              f"{support['supported']}, unsupported {support['unsupported']}, "
              f"contested {support['contested']}); copertura ")


def render_handoff(document):
    """L'handoff CANONICO dello Stage 12: resa deterministica del SOLO
    manifest, verificata in egress contro questa stessa resa."""
    room = (document or {}).get("data_room") or {}
    documents = entries_of(room, "documents")
    claims = entries_of(room, "claims")
    availability = {state: sum(1 for entry in documents
                               if entry.get("availability") == state)
                    for state in ("available", "expected", "missing")}
    lines = [
        "# Handoff — Stage 12 Data room", "",
        "next_action: revisione della Data Room e advance-stage "
        f"{STAGE12}; poi avviare 13_document-generation.", "",
        f"- Documenti indicizzati: {len(documents)} (available "
        f"{availability['available']}, expected {availability['expected']}, "
        f"missing {availability['missing']})",
        handoff_coverage_line(room),
        f"- Lacune irrisolte: "
        f"{len(entries_of(room, 'unresolved_evidence_gaps'))} · evidenze non "
        f"correnti: {len(room.get('stale_evidence') or [])} · orfane: "
        f"{len(room.get('orphan_evidence') or [])}",
        open_items_line(room),
        f"- Identita' del manifest: sha256:"
        f"{inline((room.get('identity') or {}).get('payload_sha256'))}", ""]
    for conflict in entries_of(room, "conflicts"):
        lines += incoherence_block(conflict, claims)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# VALIDAZIONE — egress, impact e verifica del costruttore
# --------------------------------------------------------------------------


class Scope:
    """Il contesto di una validazione: fase, progetto, registri, stato."""

    def __init__(self, project, config, phase):
        self.project = Path(project)
        self.config = config
        self.phase = phase
        self.status = read_status(project)
        self.registers = Registers(project)
        self.boundary = boundary_ordinal(config)


def in_view(rel, config):
    """La validation view del Transaction Manager porta `shared/` e le uscite
    `NN_*/structured-output.json` degli stage di `stage_order`. Un documento
    e' NELLA view solo se e' un registro condiviso o l'uscita canonica di uno
    stage: un file dell'utente chiamato `structured-output.json` non lo e', e
    in impact resta `NOT_APPLICABLE`."""
    rel = str(rel)
    if rel in REQUIRED_REGISTERS + OPTIONAL_REGISTERS:
        return "register"
    parts = rel.split("/")
    if len(parts) == 2 and parts[1] == CANONICAL_NAME and \
            stage_ordinal(config, parts[0]) is not None:
        return "canonical"
    return None


def add(report, code, ref, message):
    report.add_error(code, ref=ref, message=message)


def check_serialization(raw, document, report):
    if raw is None:
        return
    if raw not in (canonical_json(document), transaction_form(document)):
        add(report, CODE_NONDETERMINISTIC, "serializzazione",
            "il manifest non e' nella forma deterministica (chiavi ordinate, "
            "indentazione 2, newline finale; ensure_ascii o la riscrittura "
            "UTF-8 del Transaction Manager): due esecuzioni non darebbero "
            "byte identici")


def check_schema(document, report):
    schema = load_schema()
    issues = schema_issues(schema, schema, document)
    seen = set()
    for issue in issues:
        code = issue_code(issue)
        ref = issue_ref(issue)
        if (code, ref) in seen:
            continue
        seen.add((code, ref))
        add(report, code, ref, f"schema: {issue.message}")
    return not issues


def check_sections(room, report):
    sections = [item for item in room.get("sections") or []
                if isinstance(item, dict)]
    documents = [item for item in room.get("documents") or []
                 if isinstance(item, dict)]
    if [item.get("section_id") for item in sections] != list(SECTION_IDS):
        add(report, CODE_SECTION_MISSING, "sections",
            "le sezioni non sono le UNDICI dell'elenco chiuso nell'ordine "
            "fisso: una sezione omessa, aggiunta o spostata")
    order = [item.get("document_id") for item in documents]
    for position, section in enumerate(sections, start=1):
        section_id = section.get("section_id")
        ids = section.get("document_ids") or []
        if section.get("ordinal") != position:
            add(report, CODE_SECTION_MISSING, section_id,
                f"ordinale {section.get('ordinal')} invece di {position}")
        expected = [item.get("document_id") for item in documents
                    if item.get("section_id") == section_id]
        if sorted(map(str, ids)) != sorted(map(str, expected)):
            add(report, CODE_SECTION_MISSING, section_id,
                f"la sezione non e' la partizione del manifest: dichiara "
                f"{ids}, i documenti con questa sezione sono {expected}")
        elif ids != expected and all(ref in order for ref in ids):
            add(report, CODE_NONDETERMINISTIC, section_id,
                "document_ids non segue l'ordine del manifest")
        if ids and (section.get("status") != "POPULATED" or
                    section.get("reason") is not None):
            add(report, CODE_SECTION_MISSING, section_id,
                "sezione con documenti non dichiarata POPULATED senza reason")
        if not ids and (section.get("status") != "NOT_APPLICABLE" or
                        not isinstance(section.get("reason"), str) or
                        not section.get("reason")):
            add(report, CODE_SECTION_MISSING, section_id,
                "sezione vuota non emessa NOT_APPLICABLE con reason: una "
                "sezione vuota non si omette in silenzio")


def check_documents(room, scope, report, claims_by_id):
    documents = [item for item in room.get("documents") or []
                 if isinstance(item, dict)]
    config = scope.config
    ids = [item.get("document_id") for item in documents]
    for ref in duplicated(ids):
        add(report, CODE_DUPLICATE_ID, ref,
            f"document_id {ref!r} DUPLICATO: l'unicita' e' misurata a parte "
            "dalla canonicita'")
    paths = {}
    for item in documents:
        key = normalized_path(item.get("path"))
        if key in paths:
            add(report, CODE_DUPLICATE_ID, item.get("document_id"),
                f"il path {item.get('path')!r} e' gia' indicizzato come "
                f"{paths[key]} (confronto dopo normalizzazione)")
        else:
            paths[key] = item.get("document_id")
    required = required_paths(scope.status, config)
    by_path = {item.get("path"): item for item in documents}
    for rel in required:
        if rel not in by_path:
            add(report, CODE_REQUIRED_MISSING, rel,
                f"l'artefatto OBBLIGATORIO {rel!r} e' OMESSO dal manifest: "
                "l'assenza deve essere visibile, mai assorbita")
    out_of_view = []
    mutable = []
    identities = {}
    for item in documents:
        ref = item.get("document_id")
        rel = item.get("path")
        origin = item.get("origin")
        artifact_type = item.get("artifact_type")
        if origin == "source" and artifact_type not in SOURCE_TYPES or \
                origin == "generated" and artifact_type not in GENERATED_TYPES:
            add(report, CODE_ARTIFACT_TYPE, ref,
                f"artifact_type {artifact_type!r} incoerente con origin "
                f"{origin!r}")
        # Classificazione generata/fonte DERIVATA dal path, mai dichiarata.
        generated_type = generated_type_of(rel, config)
        if origin == "generated" and generated_type is None:
            add(report, CODE_ORIGIN, ref,
                f"{rel!r} non e' un artefatto generato dal sistema (registro "
                "condiviso, uscita canonica, handoff o derivato di uno stage "
                "precedente): un file dell'utente non si dichiara generato")
        elif origin == "generated" and artifact_type in GENERATED_TYPES and \
                artifact_type != generated_type:
            add(report, CODE_ARTIFACT_TYPE, ref,
                f"artifact_type {artifact_type!r} invece di "
                f"{generated_type!r} per {rel!r}")
        name = str(rel).rsplit("/", 1)[-1]
        generated_name = name in GENERATED_NAMES or \
            rel in REQUIRED_REGISTERS + OPTIONAL_REGISTERS
        if generated_name and origin == "source":
            add(report, CODE_ORIGIN, ref,
                f"{rel!r} e' un artefatto GENERATO dal sistema dichiarato "
                "come fonte originale")
        if origin == "source" and item.get("derived_from"):
            add(report, CODE_ORIGIN, ref,
                "una fonte originale non deriva da alcun documento")
        expected_from = expected_derived_from(item, by_path)
        if origin == "generated" and item.get("derived_from") != expected_from:
            add(report, CODE_ORIGIN, ref,
                f"derived_from {item.get('derived_from')} invece di "
                f"{expected_from}: il riassunto generato deve nominare il DR-* "
                "del proprio originale")
        availability = item.get("availability")
        status = item.get("validation_status")
        if availability == "expected" and (rel in required or
                                           origin == "generated"):
            add(report, CODE_REQUIRED_MISSING, ref,
                f"{rel!r} e' dichiarato expected: un artefatto obbligatorio o "
                "generato assente resta missing, visibile")
        if availability == "missing" and status != "needs_info":
            add(report, CODE_VALIDATION_STATUS, ref,
                f"validation_status {status!r} per un documento missing: un "
                "documento assente e' needs_info")
        elif availability == "expected" and status == "validated":
            add(report, CODE_VALIDATION_STATUS, ref,
                "un documento expected, non ancora disponibile, non e' "
                "validated")
        elif origin == "generated" and availability == "available" and \
                generated_type is not None and status != (
                    "open" if generated_type == "shared_register"
                    else "validated"):
            add(report, CODE_VALIDATION_STATUS, ref,
                f"validation_status {status!r} incoerente con l'artefatto "
                f"generato {generated_type!r}")
        stage = item.get("related_section")
        ordinal = stage_ordinal(config, stage) if isinstance(stage, str) \
            else None
        if ordinal is None or ordinal > scope.boundary:
            add(report, CODE_SECTION_INVALID, ref,
                f"related_section {stage!r} non e' uno stage di stage_order "
                "entro il release_boundary")
        reason = unsafe_path_reason(rel)
        if reason:
            add(report, CODE_PATH_ESCAPE, ref, reason)
            continue
        view_class = in_view(rel, config)
        canonical = rel
        if scope.phase != "impact" or view_class is not None:
            # Identita' del path sul sistema di destinazione: la grafia
            # CANONICA su disco.
            alias = path_alias_reason(scope.project, rel)
            if alias:
                add(report, CODE_PATH_ESCAPE, ref, alias)
            canonical = canonical_rel(scope.project, rel) or rel
        head = canonical.split("/", 1)[0]
        head_ordinal = stage_ordinal(config, head)
        if head_ordinal is not None and head_ordinal >= stage_ordinal(
                config, STAGE12):
            add(report, CODE_SECTION_INVALID, ref,
                f"{rel!r} appartiene alla Data Room stessa o a uno stage "
                "oltre di essa")
        if hidden_segment(canonical):
            add(report, CODE_BROKEN_PATH, ref,
                f"{rel!r} attraversa un'area transitoria o nascosta")
            continue
        checksum = item.get("checksum")
        if availability == "available" and checksum is None or \
                availability in ("expected", "missing") and checksum is not \
                None:
            add(report, CODE_CHECKSUM, ref,
                f"checksum {checksum!r} incoerente con availability "
                f"{availability!r}: null SOLO per expected/missing")
        for claim_ref in item.get("related_claims") or []:
            if claim_ref not in claims_by_id:
                add(report, CODE_CLAIM_LINK, ref,
                    f"related_claims nomina {claim_ref!r}, che NON risolve "
                    "nel registro dei claim")
        derived = related_claims_of(ref, list(claims_by_id.values()))
        if item.get("related_claims") != derived:
            add(report, CODE_CLAIM_LINK, ref,
                f"related_claims {item.get('related_claims')} invece dei "
                f"claim che lo collegano: {derived}")
        for evidence_ref in item.get("evidence_refs") or []:
            if evidence_ref not in scope.registers.evidence:
                add(report, CODE_CLAIM_LINK, ref,
                    f"evidence_ref {evidence_ref!r} non risolve nel "
                    "registro delle evidenze")
        check_quality(item, scope, report)
        if scope.phase == "impact" and view_class == "register":
            mutable.append(ref)
            continue
        if scope.phase == "impact" and view_class is None:
            out_of_view.append(ref)
            continue
        check_file(item, scope, report, rel in required)
        target, reason = contained(scope.project, rel)
        identity = file_identity(target) if not reason and \
            availability == "available" and target.is_file() else None
        if identity is not None:
            if identity in identities:
                add(report, CODE_DUPLICATE_ID, ref,
                    f"{rel!r} e' lo STESSO file di {identities[identity]}: un "
                    "file e' indicizzato una sola volta")
            else:
                identities[identity] = ref
    if scope.phase == "impact":
        report.add_check(
            "impact_out_of_view_documents", "NOT_APPLICABLE",
            affected_refs=out_of_view or None,
            message="documenti fuori dalla validation view del Transaction "
                    "Manager (che porta SOLO shared/ e i "
                    "NN_*/structured-output.json): esistenza e checksum sono "
                    "verificati in egress e al --build, mai qui")
        report.add_check(
            "impact_mutable_registers", "NOT_APPLICABLE",
            affected_refs=mutable or None,
            message="registri condivisi MUTABILI per transazione: la versione "
                    "indicizzata e' storica; la coerenza semantica con lo "
                    "stato PROPOSTO e' verificata sotto")


def check_quality(item, scope, report):
    ref = item.get("document_id")
    source_ref = item.get("source_ref")
    quality = item.get("evidence_quality")
    if source_ref is None:
        if quality is not None:
            add(report, CODE_QUALITY, ref,
                f"evidence_quality {quality!r} dichiarata per una fonte NON "
                "registrata: deve essere null")
        return
    source = scope.registers.sources.get(source_ref)
    if source is None:
        add(report, CODE_QUALITY, ref,
            f"source_ref {source_ref!r} non risolve nel registro delle fonti")
        return
    if source.get("url_or_path") != item.get("path"):
        # La qualita' e' quella della STESSA fonte, mai di una voce valida
        # qualunque.
        add(report, CODE_QUALITY, ref,
            f"source_ref {source_ref!r} registra la fonte "
            f"{source.get('url_or_path')!r}, non {item.get('path')!r}")
    if quality != source.get("quality_rating"):
        add(report, CODE_QUALITY, ref,
            f"evidence_quality {quality!r} diversa dal quality_rating "
            f"registrato {source.get('quality_rating')!r}")


def check_file(item, scope, report, is_required):
    ref = item.get("document_id")
    rel = item.get("path")
    availability = item.get("availability")
    target, reason = contained(scope.project, rel)
    if reason:
        add(report, CODE_PATH_ESCAPE, ref, reason)
        return
    present = target.is_file()
    if availability == "available":
        if not present:
            if is_required:
                add(report, CODE_REQUIRED_MISSING, ref,
                    f"l'artefatto OBBLIGATORIO {rel!r} e' ASSENTE ma e' "
                    "dichiarato available")
            else:
                add(report, CODE_BROKEN_PATH, ref,
                    f"il path {rel!r} non risolve a un file esistente")
            return
        checksum = item.get("checksum")
        if checksum is not None and checksum != sha256_file(target):
            add(report, CODE_CHECKSUM, ref,
                f"il checksum RICALCOLATO di {rel!r} non corrisponde a quello "
                "dichiarato")
    elif availability in ("expected", "missing") and present:
        add(report, CODE_REQUIRED_MISSING, ref,
            f"{rel!r} esiste ma e' dichiarato {availability}: il tri-stato "
            "non riflette il progetto")


def check_claims(room, scope, report):
    claims = [item for item in room.get("claims") or []
              if isinstance(item, dict)]
    documents = {item.get("document_id"): item for item in
                 room.get("documents") or [] if isinstance(item, dict)}
    config = scope.config
    for ref in duplicated([claim.get("claim_id") for claim in claims]):
        add(report, CODE_DUPLICATE_ID, ref, f"claim_id {ref!r} DUPLICATO")
    for claim in claims:
        claim_id = claim.get("claim_id")
        for stage in (claim.get("related_section"),
                      (claim.get("provenance") or {}).get("section")
                      if isinstance(claim.get("provenance"), dict) else None):
            if stage is None:
                continue
            ordinal = stage_ordinal(config, stage) if isinstance(
                stage, str) else None
            if ordinal is None or ordinal > scope.boundary:
                add(report, CODE_SECTION_INVALID, claim_id,
                    f"sezione {stage!r} fuori da stage_order o oltre il "
                    "release_boundary")
        for ref in claim.get("assumption_refs") or []:
            if ref not in scope.registers.assumptions:
                add(report, CODE_CLAIM_LINK, claim_id,
                    f"assunzione {ref!r} non risolve nel registro ufficiale")
        links = [link for link in claim.get("evidence_links") or []
                 if isinstance(link, dict)]
        for link in links:
            ref = link.get("evidence_ref")
            if ref is not None and ref not in scope.registers.evidence:
                add(report, CODE_CLAIM_LINK, claim_id,
                    f"evidenza {ref!r} non risolve nel registro")
            document_id = link.get("document_id")
            if document_id is None:
                continue
            document = documents.get(document_id)
            if document is None:
                add(report, CODE_CLAIM_LINK, claim_id,
                    f"documento {document_id!r} non risolve nel manifest")
                continue
            # Il legame LOCALIZZA l'evidenza in un documento che la porta e,
            # per un sostegno, che esiste.
            if ref is not None and ref not in (document.get("evidence_refs")
                                               or []):
                add(report, CODE_CLAIM_LINK, claim_id,
                    f"il legame localizza {ref} nel documento {document_id}, "
                    "che non porta quell'evidenza (evidence_refs "
                    f"{document.get('evidence_refs')})")
            if link.get("status") == "supporting" and \
                    document.get("availability") != "available":
                add(report, CODE_CLAIM_LINK, claim_id,
                    f"il legame supporting di {ref} e' localizzato nel "
                    f"documento {document_id} "
                    f"{document.get('availability')}: la prova deve esistere")
        if links != sorted(links, key=link_sort_key):
            add(report, CODE_NONDETERMINISTIC, claim_id,
                "legami non in ordine deterministico")
        for code, ref, message in claim_link_problems(claim, scope.registers):
            add(report, code, ref, message)
        declared = claim.get("support_status")
        derived = support_of(claim, scope.registers)
        if declared != derived:
            add(report, CODE_UNSUPPORTED if declared == "supported"
                else CODE_CLAIM_STATUS, claim_id,
                f"support_status {declared!r} invece di {derived!r}: un "
                "claim materiale e' supportato SOLO da un'evidenza "
                "probatoria collegata, e una contraddizione resta visibile")
    return {claim.get("claim_id"): claim for claim in claims}


EVIDENCE_RECORD_FIELDS = (("classification", CODE_HIERARCHY),
                          ("register_status", CODE_STALE),
                          ("date", CODE_STALE), ("freshness", CODE_STALE),
                          ("verification", CODE_STALE),
                          ("linked_claims", CODE_ORPHAN),
                          ("linked_documents", CODE_ORPHAN),
                          ("orphan", CODE_ORPHAN))


def check_derived_lists(room, scope, report):
    """Le liste DERIVATE sono verificate RECORD PER RECORD: un duplicato e'
    respinto e nessun record ombra nasconde quello vero; lacune e conflitti
    sono la derivazione ESATTA — molteplicita', identita', risoluzione, tipo
    e contenuto."""
    registers = scope.registers
    claims = [item for item in room.get("claims") or []
              if isinstance(item, dict)]
    documents = [item for item in room.get("documents") or []
                 if isinstance(item, dict)]
    policy = room.get("staleness_policy") or {}
    try:
        reference = date.fromisoformat(str(policy.get("reference_date")))
        max_age = int(policy.get("max_age_days"))
    except (TypeError, ValueError):
        add(report, CODE_STALE, "staleness_policy",
            "criterio di staleness non dichiarato o non valido")
        return
    expected_index = evidence_index(documents, claims, registers, reference,
                                    max_age)
    expected_by_ref = {record["evidence_ref"]: record
                       for record in expected_index}
    declared_records = [item for item in room.get("evidence_index") or []
                        if isinstance(item, dict)]
    declared_refs = [item.get("evidence_ref") for item in declared_records]
    for ref in duplicated(declared_refs):
        add(report, CODE_DUPLICATE_ID, ref,
            f"{ref} compare piu' volte nell'indice delle evidenze: un record "
            "ombra non nasconde quello vero")
    for record in declared_records:
        ref = record.get("evidence_ref")
        expected = expected_by_ref.get(ref)
        if expected is None:
            add(report, CODE_CLAIM_LINK, ref,
                f"{ref} nell'indice delle evidenze non risolve nel registro")
            continue
        for field, code in EVIDENCE_RECORD_FIELDS:
            if record.get(field) != expected[field]:
                add(report, code, ref,
                    f"evidence_index.{field} {record.get(field)!r} invece "
                    f"di {expected[field]!r}")
    for ref in expected_by_ref:
        if ref not in declared_refs:
            add(report, CODE_ORPHAN, ref,
                f"{ref} e' registrata ma ASSENTE dall'indice delle evidenze: "
                "scartare non e' rilevare")
    if declared_refs != sorted(declared_refs, key=id_number):
        add(report, CODE_NONDETERMINISTIC, "evidence_index",
            "indice delle evidenze non in ordine numerico")
    for key, code, derived in (
            ("orphan_evidence", CODE_ORPHAN,
             [item["evidence_ref"] for item in expected_index
              if item["orphan"]]),
            ("stale_evidence", CODE_STALE,
             [item["evidence_ref"] for item in expected_index
              if item["freshness"] != "current"]),
            ("unsupported_claims", CODE_UNSUPPORTED,
             sorted((claim.get("claim_id") for claim in claims
                     if support_of(claim, registers) == "unsupported"),
                    key=id_number))):
        declared = room.get(key)
        if declared != derived:
            add(report, code, key,
                f"{key} {declared} invece di {derived}")
    check_gaps(room, scope, report, claims)
    check_conflicts(room, scope, report, claims)
    completeness = room.get("completeness")
    derived = derive_completeness(claims, registers)
    if completeness != derived:
        add(report, CODE_COMPLETENESS, "completeness",
            f"metriche di completezza {completeness} invece di {derived}: la "
            "copertura non travisa la qualita' e porta denominatore e "
            "distribuzione per classe")


def check_gaps(room, scope, report, claims):
    registers = scope.registers
    derived_gaps = [{"kind": kind, "ref": ref, "detail": detail}
                    for kind, ref, detail in derive_gaps(
                        [dict(claim, support_status=support_of(claim,
                                                                registers))
                         for claim in claims], registers)]
    derived_by_key = {(gap["kind"], gap["ref"]): gap for gap in derived_gaps}
    declared = [item for item in room.get("unresolved_evidence_gaps") or []
                if isinstance(item, dict)]
    keys = [(item.get("kind"), item.get("ref")) for item in declared]
    for kind, ref in duplicated(keys):
        add(report, CODE_DUPLICATE_ID, ref,
            f"lacuna {kind} su {ref} DUPLICATA: ogni lacuna compare una "
            "sola volta")
    for kind, ref in derived_by_key:
        if (kind, ref) not in keys:
            add(report, CODE_GAP, ref,
                f"lacuna irrisolta {kind} su {ref} SOPPRESSA: deve comparire "
                "in unresolved_evidence_gaps")
    claim_ids = {claim.get("claim_id") for claim in claims}
    resolvable = {"claim_unsupported": claim_ids, "missing_link": claim_ids,
                  "assumption_without_evidence_refs":
                  set(registers.assumptions),
                  "missing_information": set(registers.evidence)}
    for item, key in zip(declared, keys):
        expected = derived_by_key.get(key)
        if expected is not None:
            if item != expected:
                add(report, CODE_GAP, key[1],
                    f"lacuna {key[0]} su {key[1]} RISCRITTA: {item} invece "
                    f"della derivazione {expected}")
            continue
        if key[1] not in resolvable.get(key[0], ()):
            add(report, CODE_CLAIM_LINK, key[1],
                f"la lacuna {key[0]} nomina {key[1]!r}, che non risolve: un "
                "riferimento pendente e' un FAIL attribuito")
        elif scope.phase != "impact":
            # In impact i registri, mutabili, possono aver risolto dopo la
            # pubblicazione una lacuna allora reale: resta ammessa.
            add(report, CODE_GAP, key[1],
                f"lacuna {key[0]} su {key[1]} NON derivata dai legami e dai "
                "registri: inventata o di tipo diverso")
    if keys != sorted(keys, key=lambda item: (
            GAP_KINDS.index(item[0]) if item[0] in GAP_KINDS else 9,
            id_number(item[1]))):
        add(report, CODE_NONDETERMINISTIC, "unresolved_evidence_gaps",
            "lacune non in ordine deterministico")


CONFLICT_FIELDS = ("kind", "claim_id", "evidence_a", "evidence_b",
                   "severity", "decision_required", "files")


def check_conflicts(room, scope, report, claims):
    registers = scope.registers
    derived = {record[:4]: record for record in (
        tuple(conflict_record(0, *item)[field] for field in CONFLICT_FIELDS)
        for item in derive_conflicts(claims, registers))}
    declared = [item for item in room.get("conflicts") or []
                if isinstance(item, dict)]
    tuples = [(item.get("kind"), item.get("claim_id"), item.get("evidence_a"),
               item.get("evidence_b")) for item in declared]
    for record in duplicated(tuples):
        add(report, CODE_DUPLICATE_ID, record[1] or record[2],
            f"conflitto {record} DUPLICATO: ogni INCOERENZA RILEVATA compare "
            "una sola volta")
    for ref in duplicated([item.get("issue_id") for item in declared]):
        add(report, CODE_DUPLICATE_ID, ref, f"issue_id {ref!r} DUPLICATO")
    for record in derived:
        if record not in tuples:
            add(report, CODE_CONFLICT, record[1] or record[2],
                f"INCOERENZA RILEVATA non esposta: {record[0]} fra "
                f"{record[2]} e {record[3]}; mai fusione, mai la piu' "
                "recente")
    for item, record in zip(declared, tuples):
        expected = derived.get(record)
        if expected is None:
            add(report, CODE_CLAIM_STATUS if record[0] == "contradiction"
                else CODE_CONFLICT, record[1] or record[2],
                f"il conflitto dichiarato {record} non risulta dai legami e "
                "dal registro: la contraddizione dichiarata e' stata "
                "attenuata o inventata")
            continue
        # Severita', decisione e file del conflitto DERIVATO: mai attenuati,
        # mai «prevale la piu' recente».
        actual = tuple(item.get(field) for field in CONFLICT_FIELDS)
        if actual != expected:
            add(report, CODE_CONFLICT, item.get("issue_id"),
                f"il conflitto {item.get('issue_id')} non e' il record "
                "derivato: severita', decisione richiesta e file coinvolti "
                "non si attenuano")
    if tuples != sorted(tuples, key=lambda item: (
            CONFLICT_KINDS.index(item[0]) if item[0] in CONFLICT_KINDS
            else 9, id_number(item[1]), id_number(item[2]),
            id_number(item[3]))) or [item.get("issue_id") for item in
                                     declared] != [
            f"ISSUE-DR-{position:03d}" for position in
            range(1, len(declared) + 1)]:
        add(report, CODE_NONDETERMINISTIC, "conflicts",
            "conflitti non in ordine deterministico o numerazione non "
            "progressiva")


def check_open_items(room, scope, report):
    """OGNI record di `open_items` e' valutato, e un `item_ref` duplicato e'
    respinto: un record ombra CHIUSO non nasconde quello vero. In egress la
    lista e' la derivazione ESATTA del registro;
    in impact una voce APERTO resta ammessa se il registro, mutabile, l'ha
    risolta dopo la pubblicazione."""
    records = [item for item in room.get("open_items") or []
               if isinstance(item, dict)]
    registers = scope.registers
    refs = [item.get("item_ref") for item in records]
    for ref in duplicated(refs):
        add(report, CODE_DUPLICATE_ID, ref,
            f"{ref} compare piu' volte in open_items: un record ombra non "
            "nasconde quello vero")
    for ref in registers.conditions:
        if ref not in refs:
            add(report, CODE_DEBT, ref,
                f"la condizione {ref} e' OMESSA: il debito differito e' "
                "esposto, mai chiuso dall'esistenza della data room")
    derived = {item["item_ref"]: item for item in derive_open_items(registers)}
    for item in records:
        ref = item.get("item_ref")
        entry = registers.conditions.get(ref)
        if entry is None:
            add(report, CODE_DEBT, ref,
                f"{ref} non e' una condizione registrata")
            continue
        if item.get("status") == "CHIUSO":
            closed = entry.get("resolution_status") in ("resolved", "waived")
            if not closed or item.get("proof_ref") != entry.get(
                    "resolved_by") or not item.get("proof_ref"):
                add(report, CODE_DEBT, ref,
                    f"{ref} dichiarata CHIUSA senza la prova registrata "
                    f"(resolution_status {entry.get('resolution_status')!r}, "
                    f"resolved_by {entry.get('resolved_by')!r}, prova "
                    f"dichiarata {item.get('proof_ref')!r})")
                continue
        elif item.get("proof_ref") is not None:
            add(report, CODE_DEBT, ref,
                f"{ref} APERTO con la prova {item.get('proof_ref')!r}: la "
                "prova appartiene solo a una voce CHIUSO")
            continue
        drift = scope.phase == "impact" and item.get("status") == "APERTO" \
            and derived[ref].get("status") == "CHIUSO"
        if item != derived[ref] and not drift:
            add(report, CODE_DEBT, ref,
                f"{ref}: la voce {item} non e' la derivazione esatta del "
                f"registro delle condizioni ({derived[ref]})")
    if refs != sorted(refs, key=id_number):
        add(report, CODE_NONDETERMINISTIC, "open_items",
            "voci aperte non in ordine numerico")


def check_ordering(room, scope, report):
    documents = [item for item in room.get("documents") or []
                 if isinstance(item, dict)]
    keys = [(stage_ordinal(scope.config, item.get("related_section")) or 0,
             id_number(item.get("document_id"))) for item in documents]
    if keys != sorted(keys):
        add(report, CODE_NONDETERMINISTIC, "documents",
            "documenti non ordinati per (ordinale della related_section, "
            "document_id) a ordinali ESPLICITI, mai lessicografici")
    claims = [item.get("claim_id") for item in room.get("claims") or []
              if isinstance(item, dict)]
    if claims != sorted(claims, key=id_number):
        add(report, CODE_NONDETERMINISTIC, "claims",
            "claim non in ordine numerico")
    for item in documents:
        for key in ("related_claims", "evidence_refs", "derived_from"):
            values = item.get(key) or []
            if values != sorted(values, key=id_number):
                add(report, CODE_NONDETERMINISTIC, item.get("document_id"),
                    f"{key} non in ordine numerico")


def check_identity(document, report):
    identity = (document.get("data_room") or {}).get("identity") or {}
    if identity.get("payload_sha256") != identity_of(document):
        add(report, CODE_VOLATILE, "identity",
            "l'identita' dichiarata non e' l'impronta del payload di "
            "identita', che ESCLUDE per costruzione last_verified_at e "
            "generated_at")


def scan_text(text, label, report):
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(text or ""):
            add(report, CODE_SECRET, label,
                f"{name} in un artefatto GENERATO: {label}")


def file_text(path):
    """Il testo di un artefatto generato per la scansione dei segreti: i
    membri di un pacchetto zip (il workbook); per un JSON il testo E la forma
    DECODIFICATA (`semantic_text`), come per il manifest; altrimenti il
    testo UTF-8."""
    path = Path(path)
    if zipfile.is_zipfile(path):
        parts = []
        with zipfile.ZipFile(path) as package:
            for member in sorted(package.namelist()):
                parts.append(package.read(member).decode("utf-8",
                                                         errors="replace"))
        return "\n".join(parts)
    text = path.read_bytes().decode("utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        try:
            return text + "\n" + semantic_text(json.loads(text))
        except (ValueError, RecursionError):
            return text
    return text


def check_secrets(document, scope, report, handoff, index):
    """Scansione dei segreti sui SOLI artefatti generati. Il manifest e'
    scandito sulla forma DECODIFICATA (`semantic_text`), identica per il
    costruttore, l'egress, la riscrittura UTF-8 del TM e l'impact. In impact
    sono scanditi i generati NELLA validation view — registri condivisi e
    uscite canoniche — e sono `NOT_APPLICABLE` solo quelli fuori."""
    room = document.get("data_room") or {}
    scan_text(semantic_text(document), f"{STAGE12}/{CANONICAL_NAME}", report)
    if handoff is not None:
        scan_text(handoff, f"{STAGE12}/{HANDOFF_NAME}", report)
    if index is not None:
        scan_text(index, f"{STAGE12}/{INDEX_NAME}", report)
    out_of_view = []
    scanned = set()
    for item in room.get("documents") or []:
        if not isinstance(item, dict) or item.get("origin") != "generated" \
                or item.get("availability") != "available":
            continue
        rel = item.get("path")
        if scope.phase == "impact" and in_view(rel, scope.config) is None:
            out_of_view.append(item.get("document_id"))
            continue
        target, reason = contained(scope.project, rel)
        if reason or not target.is_file():
            continue
        scanned.add(rel)
        scan_text(file_text(target), rel, report)
    # Ogni registro condiviso PRESENTE e' scandito anche se il manifest non
    # lo indicizza — per esempio il registro delle decisioni che
    # `update-assumption` o `resolve-condition` creano dopo la pubblicazione:
    # e' nella view di impact, e costruttore, egress e impact concordano.
    for rel in REQUIRED_REGISTERS + OPTIONAL_REGISTERS:
        if rel in scanned:
            continue
        target, reason = contained(scope.project, rel)
        if reason or not target.is_file():
            continue
        scan_text(file_text(target), rel, report)
    if scope.phase == "impact":
        report.add_check(
            "impact_generated_secret_scan", "NOT_APPLICABLE",
            affected_refs=out_of_view or None,
            message="SOLO i documenti generati FUORI dalla validation view del "
                    "Transaction Manager (handoff, derivati, indice) non sono "
                    "ispezionabili in impact: la loro scansione avviene in "
                    "egress e al --build; il manifest, i registri condivisi "
                    "e le uscite canoniche della view sono scanditi qui")


INDEX_ROW_RE = re.compile(r"^\| (DR-[0-9]+) \| ((?:\\\||[^|])*) \|",
                          re.MULTILINE)


def check_index(document, index, report, phase):
    """L'indice derivato e' la resa deterministica (`render_index`) del
    manifest CORRENTE: confronto dell'INTERA resa, mai per sottostringa o a
    senso unico, cosi' nessuna riga `DR-*`, disponibilita', voce aperta o
    INCOERENZA e' falsificabile. L'indice resta FUORI dalla transazione
    canonica: e' un derivato, verificato in egress e al `--build`."""
    if phase == "impact":
        report.add_check(
            "derived_index_version", "NOT_APPLICABLE",
            message=f"{INDEX_NAME} e' un DERIVATO fuori dalla validation view "
                    "del Transaction Manager: il confronto con il manifest e' "
                    "obbligatorio in egress e al --build")
        return
    label = f"{STAGE12}/{INDEX_NAME}"
    if index is None:
        add(report, CODE_VERSION, label,
            "l'indice derivato e' ASSENTE: la coerenza delle versioni fra "
            "manifest e indice non e' verificabile")
        return
    room = document.get("data_room") or {}
    rows = {match.group(1): match.group(2).replace("\\|", "|")
            for match in INDEX_ROW_RE.finditer(index)}
    for item in room.get("documents") or []:
        if not isinstance(item, dict):
            continue
        ref = item.get("document_id")
        version = item.get("version")
        if rows.get(ref) != (version if version else "-"):
            add(report, CODE_VERSION, ref,
                f"versione {version!r} del manifest diversa da quella "
                f"dell'indice derivato {rows.get(ref)!r}")
    if index != render_index(document):
        add(report, CODE_VERSION, label,
            "l'indice derivato non e' la resa deterministica del manifest "
            "corrente (render_index): righe, disponibilita', voci aperte e "
            "INCOERENZA si verificano sull'intera resa")


def check_handoff(document, handoff, report, phase):
    """L'handoff CANONICO del candidate (nel write-set del Transaction
    Manager) esiste ed e' la resa deterministica `render_handoff` del
    manifest: nessun blocco INCOERENZA RILEVATA omesso, nessuna copertura o
    voce aperta falsificata, mai assente. Le
    difformita' materiali sono attribuite ai contratti che misurano."""
    label = f"{STAGE12}/{HANDOFF_NAME}"
    if phase == "impact":
        report.add_check(
            "candidate_handoff_rendering", "NOT_APPLICABLE",
            message=f"{label} e' fuori dalla validation view del Transaction "
                    "Manager: la sua corrispondenza al manifest e' "
                    "verificata in egress e al --build")
        return
    if handoff == render_handoff(document):
        return
    add(report, CODE_VERSION, label,
        "l'handoff canonico e' ASSENTE dal candidate" if handoff is None else
        "l'handoff canonico non e' la resa deterministica del manifest "
        "(render_handoff): una superficie canonica non si modifica a mano")
    text = handoff or ""
    lines = set(text.splitlines())
    room = document.get("data_room") or {}
    claims = entries_of(room, "claims")
    for conflict in entries_of(room, "conflicts"):
        if "\n".join(incoherence_block(conflict, claims)) not in text:
            add(report, CODE_CONFLICT, conflict.get("issue_id"),
                f"il blocco INCOERENZA RILEVATA di "
                f"{conflict.get('issue_id')} manca o e' alterato "
                "nell'handoff canonico")
    if handoff_coverage_line(room) not in lines:
        add(report, CODE_COMPLETENESS, label,
            "la copertura dell'handoff canonico non e' quella del manifest, "
            "con denominatore e distribuzione per classe")
    if open_items_line(room) not in lines:
        add(report, CODE_DEBT, label,
            "le voci aperte dell'handoff canonico non sono quelle del "
            "manifest")


def validate_document(document, scope, report, raw=None, handoff=None,
                      index=None):
    check_serialization(raw, document, report)
    schema_valid = check_schema(document, report)
    for ref, message in scope.registers.problems:
        add(report, CODE_DUPLICATE_ID, ref, message)
    try:
        room = document.get("data_room")
        if not isinstance(room, dict):
            return
        check_sections(room, report)
        claims_by_id = check_claims(room, scope, report)
        check_documents(room, scope, report, claims_by_id)
        check_derived_lists(room, scope, report)
        check_open_items(room, scope, report)
        check_ordering(room, scope, report)
        check_identity(document, report)
        check_index(document, index, report, scope.phase)
        check_handoff(document, handoff, report, scope.phase)
        check_secrets(document, scope, report, handoff, index)
    except (KeyError, IndexError, TypeError, AttributeError, ValueError) \
            as exc:
        if schema_valid:
            raise
        add(report, CODE_MANIFEST_INVALID, "$",
            "il manifest non e' conforme allo schema e i controlli semantici "
            f"non sono eseguibili sulla sua struttura ({type(exc).__name__}: "
            f"{exc}): respinto, fail-closed")


# --------------------------------------------------------------------------
# PUBBLICATORE ATOMICO A DUE LIVELLI
# --------------------------------------------------------------------------


def publish(targets, guard=None):
    """Livello 1 — STAGING in temporanei nella STESSA directory, `flush` e
    `fsync`; livello 2 — `os.replace` per file. Un fallimento a QUALUNQUE
    punto ripristina i byte precedenti di OGNI bersaglio e rimuove i
    temporanei: nessun output parziale. `guard(target)` verifica il
    contenimento del bersaglio PRIMA e DOPO la creazione delle directory e di
    nuovo prima di `os.replace`, e solleva `BuildRefusal`."""
    staged = []
    backups = {}
    published = []
    try:
        for path, text in targets:
            target = Path(path)
            if guard is not None:
                guard(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            if guard is not None:
                guard(target)
            backups[target] = target.read_bytes() if target.is_file() \
                else None
            handle = tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n",
                dir=str(target.parent), prefix=".dr-", suffix=".part",
                delete=False)
            temporary = Path(handle.name)
            staged.append((temporary, target))
            try:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                handle.close()
        for temporary, target in staged:
            if guard is not None:
                guard(target)
            os.replace(str(temporary), str(target))
            published.append(target)
    except BaseException:
        for target in published:
            original = backups.get(target)
            if original is None:
                if target.is_file():
                    target.unlink()
            else:
                target.write_bytes(original)
        for temporary, _ in staged:
            if temporary.exists():
                temporary.unlink()
        raise
    return [target for _, target in staged]


# --------------------------------------------------------------------------
# COSTRUZIONE — `--build`
# --------------------------------------------------------------------------


def project_fingerprint(project):
    """Impronta di OGNI file del progetto fuori da `12_data-room/` e dalle
    aree transitorie: le fonti dell'utente e gli artefatti degli stage 00-11
    devono restare BYTE-IDENTICI."""
    out = {}
    base = Path(project)
    for path in sorted(base.rglob("*")):
        if not path.is_file() or _is_link_or_reparse(path):
            continue
        rel = path.relative_to(base).as_posix()
        if rel.startswith(f"{STAGE12}/") or rel.startswith("shared/.tx/") or \
                f"/{WORKING_DIR}/" in f"/{rel}":
            continue
        out[rel] = sha256_file(path)
    return out


def build_targets(tx):
    """I path che il costruttore LEGGE (il candidate, la proposta) e SCRIVE
    (canonico, handoff, indice): tutti sotto `12_data-room/`."""
    candidate = f"{STAGE12}/{WORKING_DIR}/{tx}"
    return {"candidate": candidate,
            "proposal": f"{candidate}/{PROPOSAL_NAME}",
            "canonical": f"{candidate}/{CANONICAL_NAME}",
            "handoff": f"{candidate}/{HANDOFF_NAME}",
            "index": f"{STAGE12}/{INDEX_NAME}"}


def containment_problems(project, tx):
    """Rifiuti ATTRIBUITI `path_escape` di un `--tx` o di un bersaglio che
    uscirebbe dall'area di scrittura `12_data-room/`, PRIMA di qualunque
    lettura o scrittura."""
    reason = tx_reason(tx)
    if reason:
        return [(CODE_PATH_ESCAPE, "--tx", reason)]
    problems = []
    for rel in build_targets(tx).values():
        _target, reason = write_target(project, rel)
        if reason:
            problems.append((CODE_PATH_ESCAPE, rel, reason))
    return problems


def refuse(report, errors):
    for code, ref, message in errors:
        report.add_error(code, ref=ref, message=message)
    print(report.to_json())
    return fw.EXIT_CANDIDATE_INVALID


def run_build(project, tx):
    """Modalita' COSTRUZIONE. NON e' il percorso del Transaction Manager."""
    report = fw.Report(VALIDATOR_NAME, STAGE12, "build")
    project = Path(project)
    if not project.is_dir():
        raise fw.ValidatorUsageError(f"project dir inesistente: {project}")
    if not tx:
        raise fw.ValidatorUsageError("--tx obbligatorio in modalita' --build")
    problems = containment_problems(project, tx)
    if problems:
        return refuse(report, problems)
    candidate = project.joinpath(STAGE12, WORKING_DIR, tx)
    config = fw.load_config()

    def guard(path):
        rel = Path(path).relative_to(project).as_posix()
        _target, reason = write_target(project, rel)
        if reason:
            raise BuildRefusal([(CODE_PATH_ESCAPE, rel, reason)])
    try:
        before = project_fingerprint(project)
        proposal_path = candidate.joinpath(PROPOSAL_NAME)
        try:
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            return refuse(report, [(
                CODE_MANIFEST_INVALID, str(proposal_path.name),
                f"proposta dell'analista assente o illeggibile: {exc}")])
        schema = load_schema()
        issues = schema_issues(schema, schema["$defs"]["proposal"], proposal)
        if issues:
            return refuse(report, [(issue_code(issue, proposal=True),
                                    issue_ref(issue) or PROPOSAL_NAME,
                                    f"proposta: {issue.message}")
                                   for issue in issues])
        try:
            date.fromisoformat(proposal["as_of"])
        except ValueError:
            return refuse(report, [(CODE_STALE, "as_of",
                                    "data di riferimento non valida")])
        status = read_status(project)
        registers = Registers(project)
        document = build_document(project, proposal, config, status,
                                  registers)
        raw = canonical_json(document)
        handoff = render_handoff(document)
        index = render_index(document)
        scope = Scope(project, config, "egress")
        check = fw.Report(VALIDATOR_NAME, STAGE12, "build")
        validate_document(document, scope, check, raw=raw, handoff=handoff,
                          index=index)
        after = project_fingerprint(project)
        if after != before:
            changed = sorted(rel for rel in set(before) | set(after)
                             if before.get(rel) != after.get(rel))
            return refuse(report, [(CODE_SOURCE_MUTATED, rel,
                                    f"{rel!r} NON e' byte-identico dopo la "
                                    "generazione: la Data Room indicizza, "
                                    "non riscrive") for rel in changed])
        if check.errors:
            return refuse(report, [(item["code"], item.get("ref"),
                                    item.get("message"))
                                   for item in check.errors])
        publish([(candidate.joinpath(CANONICAL_NAME), raw),
                 (candidate.joinpath(HANDOFF_NAME), handoff),
                 (project.joinpath(STAGE12, INDEX_NAME), index)], guard=guard)
    except BuildRefusal as exc:
        return refuse(report, exc.errors)
    except fw.CanonicalStateError as exc:
        report.add_error("corrupted_state", message=str(exc))
        print(report.to_json())
        return fw.EXIT_STATE
    report.add_check(
        "data_room_built", "PASS",
        message=f"pubblicati il candidate {STAGE12}/{WORKING_DIR}/{tx}/"
                f"{{{CANONICAL_NAME}, {HANDOFF_NAME}}} e {STAGE12}/"
                f"{INDEX_NAME}")
    print(report.to_json())
    return fw.EXIT_OK


# --------------------------------------------------------------------------
# VALIDAZIONE — ingresso dal Transaction Manager
# --------------------------------------------------------------------------


def read_text(path):
    return Path(path).read_text(encoding="utf-8") if Path(path).is_file() \
        else None


def check_manifest(args, config, report, manifest_input):
    scope = Scope(args.project, config, args.phase)
    if manifest_input:
        target = Path(manifest_input)
        if not target.is_file():
            raise fw.ValidatorUsageError(
                f"--manifest-input inesistente: {manifest_input}")
    elif args.phase == "egress":
        target = Path(args.candidate).joinpath(CANONICAL_NAME)
    else:
        target = Path(args.project).joinpath(STAGE12, CANONICAL_NAME)
    if not target.is_file():
        if args.phase == "egress":
            add(report, CODE_MANIFEST_INVALID, CANONICAL_NAME,
                "il candidate non porta il manifest canonico della Data Room")
            return
        if STAGE12 in (scope.status.get("completed_stages") or []):
            raise fw.CanonicalStateError(
                f"{STAGE12} e' in completed_stages ma il suo canonico "
                f"{STAGE12}/{CANONICAL_NAME} e' ASSENTE")
        report.add_check(
            "impact_canonical_absent", "NOT_APPLICABLE",
            message=f"{STAGE12}/{CANONICAL_NAME} assente e {STAGE12} non "
                    "completato: nessuno stato canonico della Data Room da "
                    "proteggere (comportamento dichiarato, precedente O-08)")
        return
    raw = target.read_text(encoding="utf-8")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        add(report, CODE_MANIFEST_INVALID, str(target.name),
            f"il manifest non e' JSON: {exc}")
        return
    if not isinstance(document, dict):
        add(report, CODE_MANIFEST_INVALID, str(target.name),
            "il manifest non e' un oggetto JSON")
        return
    handoff = index = None
    if args.phase == "egress":
        handoff = read_text(Path(args.candidate).joinpath(HANDOFF_NAME))
        index = read_text(Path(args.project).joinpath(STAGE12, INDEX_NAME))
    validate_document(document, scope, report, raw=raw, handoff=handoff,
                      index=index)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    pre = argparse.ArgumentParser(prog=VALIDATOR_NAME, add_help=False)
    pre.add_argument("--build", action="store_true")
    pre.add_argument("--tx")
    pre.add_argument("--manifest-input")
    try:
        known, rest = pre.parse_known_args(argv)
    except SystemExit:
        print(f"{VALIDATOR_NAME}: argomenti CLI non validi", file=sys.stderr)
        return fw.EXIT_USAGE

    if known.build:
        build = argparse.ArgumentParser(prog=VALIDATOR_NAME, add_help=False)
        build.add_argument("--project")
        try:
            args, unknown = build.parse_known_args(rest)
        except SystemExit:
            print(f"{VALIDATOR_NAME}: argomenti CLI non validi",
                  file=sys.stderr)
            return fw.EXIT_USAGE
        if unknown or not args.project or known.manifest_input:
            print(f"{VALIDATOR_NAME}: in modalita' --build sono ammessi "
                  f"SOLO --project e --tx (non riconosciuti: {unknown})",
                  file=sys.stderr)
            return fw.EXIT_USAGE
        try:
            return run_build(args.project, known.tx)
        except fw.ValidatorUsageError as exc:
            print(f"{VALIDATOR_NAME}: {exc}", file=sys.stderr)
            return fw.EXIT_USAGE

    if known.tx:
        print(f"{VALIDATOR_NAME}: --tx e' ammesso solo con --build",
              file=sys.stderr)
        return fw.EXIT_USAGE

    def check_fn(args, config, state, report):
        del state
        if args.stage != STAGE12:
            raise fw.ValidatorUsageError(
                f"stage non pertinente a {VALIDATOR_NAME}: {args.stage} "
                f"(atteso {STAGE12})")
        if args.phase not in SUPPORTED_PHASES:
            raise fw.ValidatorUsageError(
                f"--phase non ammessa per {VALIDATOR_NAME}: {args.phase} "
                f"(ammesse: {SUPPORTED_PHASES})")
        check_manifest(args, config, report, known.manifest_input)

    fw.run_validator(VALIDATOR_NAME, check_fn, rest)
    return fw.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
