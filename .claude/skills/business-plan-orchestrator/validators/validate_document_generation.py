#!/usr/bin/env python3
"""Validator, COSTRUTTORE e PUBBLICATORE del documento finale — Stage 13
`13_document-generation`.

DICHIARATO in `config/enforcement-config.json` con `stages: [13]` e
`phases: ["egress","impact"]`, ed elencato in `egress_required`: il
Transaction Manager lo esegue in egress sul candidate dello Stage 13 e in
impact sulla validation view del progetto. `13_document-generation` e'
l'ultimo stage di `stage_order` e coincide con il `release_boundary`: il suo
commit porta il progetto allo stato terminale del piano.

LO STAGE 13 E' UN ASSEMBLATORE, NON UNO STADIO DI RAGIONAMENTO
---------------------------------------------------------------
Il documento finale si assembla SOLO dai canonici JSON degli Stage 01-12 e
dai registri di `shared/`. Ogni carattere del documento appartiene a una
di TRE classi, e nient'altro puo' comparire:

    verbatim canonico   stringa di un canonico a monte, citata intatta con il
                        proprio `json_path`
    modello costante    frase della tabella chiusa `TEMPLATES`, PRIVA di cifre
    letterale legato    `bindings[].rendered`, copiato verbatim da una foglia
                        canonica, con unita' e etichetta epistemica

Nessun valore numerico e' mai convertito, arrotondato o ricalcolato: i numeri
restano la STRINGA SORGENTE (lettura lessicale senza perdita).

    LEGGE     shared/project-status.md (precondizione), shared/project-config
              .json, shared/startup-profile.json, i registri condivisi, gli
              NN_*/structured-output.json degli Stage 01-12, i derivati degli
              Stage 10-12 (per impronta, MAI per contenuto)
    PRODUCE   13_document-generation/structured-output.json   CANONICO (TM)
              13_document-generation/handoff.md               CANONICO (TM)
              output/business-plan.md                         DERIVATO

QUATTRO PERCORSI
----------------
  - EGRESS e IMPACT, invocati dal Transaction Manager con l'argv REALE e
    nessun ingresso privato. L'egress RICOSTRUISCE il documento dagli
    ingressi e dalla proposta del writer e lo confronta byte per byte.
  - `--build --project <p> --tx <tx>`: MAI passato dal Transaction Manager.
    Scrive SOLO il candidate `13_document-generation/.working/<tx>/`.
  - `--publish --project <p>`: MAI passato dal Transaction Manager. Solo con
    il predicato terminale vero; rende il canonico COMMITTATO e scrive SOLO
    `output/business-plan.md`.

CONFINE DEGLI IMPORT
--------------------
Libreria standard e `_framework`, nient'altro: la validazione a schema usa un
motore MINIMO in libreria standard, e l'impronta dei record `ASS-*` e' la
stessa `record_fingerprint` pinnata dal Transaction Manager, riprodotta senza
importarlo.

TASSONOMIA DEI CODICI
---------------------
I diciotto codici `docgen_*` del catalogo chiuso e `path_escape`, condiviso
con il Transaction Manager e riusato verbatim; `corrupted_state` e' del
framework. Nessun altro codice e' coniato.

Exit code: 0 valido o pubblicato | 1 rifiuto attribuito | 2 errore d'uso |
3 stato canonico corrotto.
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
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _framework as fw  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parents[1]

VALIDATOR_NAME = "validate_document_generation"
STAGE13 = "13_document-generation"
SUPPORTED_PHASES = ("egress", "impact")
SCHEMA_VERSION = "1.0.0"
SCHEMAS_DIR = SKILL_ROOT / "schemas"
SCHEMA_PATH = SCHEMAS_DIR / "document-generation.schema.json"

CANONICAL_NAME = "structured-output.json"
HANDOFF_NAME = "handoff.md"
PROPOSAL_NAME = "document-proposal.json"
WORKING_DIR = ".working"
OUTPUT_DIR = "output"
OUTPUT_NAME = "business-plan.md"
OUTPUT_REL = f"{OUTPUT_DIR}/{OUTPUT_NAME}"
SELF_REL = f"{STAGE13}/{CANONICAL_NAME}"

STATUS_REL = "shared/project-status.md"
CONFIG_REL = "shared/project-config.json"
PROFILE_REL = "shared/startup-profile.json"
ASSUMPTIONS_REL = "shared/assumptions-register.json"
EVIDENCE_REL = "shared/evidence-register.json"
SOURCE_REL = "shared/source-register.json"
CONDITIONS_REL = "shared/conditions-register.json"
RISK_REL = "shared/risk-register.json"

S01 = "01_problem-and-need"
S02 = "02_customer-segmentation"
S03 = "03_value-proposition"
S04 = "04_market-and-competition"
S05 = "05_business-model"
S06 = "06_go-to-market"
S07 = "07_operations-and-ip"
S08 = "08_team-and-governance"
S09 = "09_roadmap-and-milestones"
S10 = "10_financial-plan"
S11 = "11_funding-request"
S12 = "12_data-room"
CONTENT_STAGES = (S01, S02, S03, S04, S05, S06, S07, S08, S09, S10, S11, S12)
PINNED_STAGES = CONTENT_STAGES[:-1]

#: Gli schemi DEDICATI degli Stage 7-9: i loro canonici sono conformi o
#: respinti (`XS-02`).
STAGE_SCHEMAS = {S07: "operations-model", S08: "team-governance",
                 S09: "milestone-plan"}
#: Le `schema_version` SUPPORTATE degli Stage 10-12 (`XS-02`).
SUPPORTED_VERSIONS = {S10: "1.1.0", S11: "1.0.0", S12: "1.0.0"}
#: I derivati obbligatori, referenziati per path e impronta, MAI letti.
DERIVED = {S10: ("financial-plan.md", "financial-model.xlsx"),
           S11: ("funding-request.md",), S12: ("data-room-index.md",)}
REQUIRED_REGISTERS = (ASSUMPTIONS_REL, EVIDENCE_REL, SOURCE_REL)
OPTIONAL_REGISTERS = (CONDITIONS_REL, RISK_REL)
REGISTERS = REQUIRED_REGISTERS + OPTIONAL_REGISTERS

# --------------------------------------------------------------------------
# Tassonomia CHIUSA — catalogo `docgen_*` e `path_escape` condiviso.
# --------------------------------------------------------------------------

CODE_CHAIN = "docgen_chain_incomplete"
CODE_INPUT_MISSING = "docgen_input_missing"
CODE_INPUT_INVALID = "docgen_input_invalid"
CODE_INPUT_STALE = "docgen_input_stale"
CODE_FIN_BASIS = "docgen_financial_basis_stale"
CODE_REFERENCE = "docgen_reference_unresolved"
CODE_BINDING = "docgen_binding_divergent"
CODE_UNTRACED = "docgen_untraced_value"
CODE_PROMOTED = "docgen_assumption_promoted"
CODE_DISCLOSURE = "docgen_disclosure_suppressed"
CODE_HIGHLIGHT = "docgen_highlight_invalid"
CODE_PROPOSAL = "docgen_proposal_invalid"
CODE_STRUCTURE = "docgen_structure_invalid"
CODE_PLACEHOLDER = "docgen_placeholder_leak"
CODE_SECRET = "docgen_secret_leak"
CODE_NONDETERMINISTIC = "docgen_nondeterministic"
CODE_OUTPUT_STALE = "docgen_output_stale"
CODE_UPSTREAM = "docgen_upstream_mutated"
CODE_PATH_ESCAPE = "path_escape"

# --------------------------------------------------------------------------
# Vocabolari chiusi
# --------------------------------------------------------------------------

#: I DICIASSETTE capitoli: id, titoli e ordine COSTANTI.
CHAPTERS = (
    ("cap-01", "Executive summary"),
    ("cap-02", "Società e progetto"),
    ("cap-03", "Problema e bisogno del cliente"),
    ("cap-04", "Segmentazione dei clienti"),
    ("cap-05", "Soluzione e proposta di valore"),
    ("cap-06", "Analisi di mercato"),
    ("cap-07", "Scenario competitivo"),
    ("cap-08", "Modello di business"),
    ("cap-09", "Go-to-market"),
    ("cap-10", "Operations e tecnologia"),
    ("cap-11", "Proprietà intellettuale e difendibilità"),
    ("cap-12", "Team e governance"),
    ("cap-13", "Roadmap e milestone"),
    ("cap-14", "Analisi dei rischi"),
    ("cap-15", "Piano finanziario"),
    ("cap-16", "Richiesta di finanziamento e impiego dei fondi"),
    ("cap-17", "Appendice e indice della data room"),
)
CHAPTER_IDS = tuple(ref for ref, _ in CHAPTERS)
CHAPTER_TITLES = dict(CHAPTERS)

#: Attribuzione dei claim della Data Room ai capitoli per `related_section`
#: `00` al capitolo 2, `12` e `13` alla sola appendice.
CLAIM_CHAPTERS = {
    "00_idea-discovery": ("cap-02",), S01: ("cap-03",), S02: ("cap-04",),
    S03: ("cap-05",), S04: ("cap-06", "cap-07"), S05: ("cap-08",),
    S06: ("cap-09",), S07: ("cap-10", "cap-11"), S08: ("cap-12",),
    S09: ("cap-13",), S10: ("cap-15",), S11: ("cap-16",),
    S12: ("cap-17",), STAGE13: ("cap-17",),
}

EVIDENCE_CLASSES = ("verified_fact", "internal_evidence", "external_source",
                    "founder_assumption", "model_estimate",
                    "missing_information")
EVIDENTIAL_CLASSES = ("verified_fact", "internal_evidence", "external_source")
QUALIFIERS = ("none", "founder_assumption", "model_estimate",
              "missing_information", "unvalidated")
#: L'etichetta epistemica OBBLIGATORIA accanto a un valore legato a un record
#: `ASS-*`. Nessuna assunzione e' mai promossa a fatto.
EPISTEMIC_LABELS = {
    "founder_assumption": "(ipotesi del founder)",
    "model_estimate": "(stima)",
    "missing_information": "(dato mancante)",
    "unvalidated": "(da validare)",
}

PROFILE_LABELS = {
    "startup_type": {
        "commercial": "commerciale", "saas": "SaaS",
        "marketplace": "marketplace", "consumer": "consumer",
        "foodtech": "foodtech", "industrial": "industriale",
        "hardware": "hardware", "deeptech": "deeptech", "biotech": "biotech",
        "medtech": "medtech", "service": "servizi", "hybrid": "ibrida"},
    "development_stage": {
        "idea": "idea", "concept": "concept", "mvp": "MVP",
        "pilot": "pilota", "early_revenue": "primi ricavi",
        "growth": "crescita", "preclinical": "preclinica",
        "clinical": "clinica", "pre_seed": "pre-seed", "seed": "seed"},
    "primary_reader": {
        "founder_internal": "founder (uso interno)",
        "business_angel": "business angel",
        "venture_capital": "venture capital",
        "corporate_partner": "partner corporate", "bank": "banca",
        "public_grant": "bando pubblico", "incubator": "incubatore",
        "mixed": "lettori misti"},
    "funding_type": {
        "equity": "equity", "debt": "debito", "grant": "contributo a fondo "
        "perduto", "bootstrapping": "autofinanziamento", "mixed": "misto"},
    "time_horizon": {
        "12_months": "12 mesi", "24_months": "24 mesi",
        "36_months": "36 mesi", "5_years": "5 anni",
        "custom": "personalizzato"},
}
PROFILE_LABELS["secondary_readers"] = PROFILE_LABELS["primary_reader"]
FREQUENCY_LABELS = {"monthly": "mensile", "quarterly": "trimestrale",
                    "annual": "annuale", "yearly": "annuale",
                    "weekly": "settimanale"}
COMPETITION_CATEGORIES = (
    ("direct", "Concorrenti diretti"),
    ("indirect", "Concorrenti indiretti"),
    ("substitutes", "Sostituti"),
    ("internal", "Soluzioni interne"),
    ("status_quo", "Status quo"),
    ("non_consumption", "Non consumo"),
)
#: I moduli del catalogo CHIUSO dello Stage 10.
FIN_MODULES = ("revenue", "gross_margin", "pnl", "cash_flow", "runway",
               "cash_buffer", "break_even", "funding_gap",
               "milestone_coverage", "kpi")
SCENARIOS = ("base", "downside", "upside")

#: La tabella CHIUSA dei modelli costanti. NESSUNA cifra: i numeri entrano
#: SOLO come letterali legati (`{slot}`); `{slot*}` raccoglie tutti i legami
#: residui separati da virgola.
TEMPLATES = {
    "es_identity": "Il progetto {project} è una startup di tipo "
                   "{startup_type}, in fase {stage}. Il documento è destinato "
                   "in primo luogo a: {reader}.",
    "es_beachhead": "Segmento beachhead: {segment}. Criterio di selezione: "
                    "{criteria}.",
    "es_beachhead_short": "Segmento beachhead: {segment}.",
    "vp_segment": "La proposta di valore è rivolta al segmento: {segment}.",
    "es_market": "Dimensione del mercato — TAM: {tam}; SAM: {sam}; SOM: "
                 "{som}.",
    "es_business_model": "Prezzo: {price}; ricorrenza: {recurrence}; "
                         "canale: {channel}.",
    "es_business_model_short": "Prezzo: {price}.",
    "coverage": "Copertura dei claim registrati nella data room: "
                "{coverage}; claim supportati: {supported} su {total}.",
    "es_no_claims": "La data room non registra alcun claim: la copertura "
                    "delle evidenze non è calcolabile.",
    "es_highlight_intro": "Affermazioni supportate da evidenza, selezionate "
                          "per la sintesi:",
    "es_no_highlight_claims": "Nessuna affermazione supportata da evidenza è "
                              "stata selezionata per la sintesi.",
    "es_no_highlight_milestones": "Nessuna milestone è stata selezionata per "
                                  "la sintesi.",
    "es_status": "Esito della validazione del piano finanziario: {result}; "
                 "stato propagato: {propagated}; prontezza per "
                 "l'investitore: {readiness}; copertura degli scenari: "
                 "{coverage}.",
    "es_funding_status": "Stato propagato dalla richiesta di finanziamento: "
                         "{state}; gap residuo dichiarato: {residual}.",
    "es_open_conditions_intro": "Condizioni aperte nel registro delle "
                                "condizioni:",
    "es_open_condition": "Condizione aperta {condition}: {description}",
    "es_no_open_conditions": "Nessuna condizione aperta nel registro delle "
                             "condizioni.",
    "es_unsupported_intro": "Claim registrati senza evidenza probatoria:",
    "es_unsupported_claim": "Claim non supportato {claim}: {statement}",
    "es_no_unsupported_claims": "Nessun claim registrato è privo di "
                                "evidenza probatoria.",
    "es_contested_intro": "Claim con evidenze contrastanti:",
    "es_contested_claim": "Claim contestato {claim}: {statement}",
    "es_unresolved_intro": "Voci non risolte della richiesta di "
                           "finanziamento:",
    "es_unresolved_item": "Voce non risolta della richiesta di "
                          "finanziamento {code}: {message}",
    "es_appendix_pointer": "Incoerenze, lacune di evidenza ed evidenze non "
                           "correnti dichiarate dalla data room sono elencate "
                           "per nome nell'appendice.",
    "es_disclaimer": "Il documento assembla esclusivamente contenuti "
                     "approvati ai gate degli stage precedenti: non introduce "
                     "ricerche, stime o decisioni nuove. La review finale "
                     "avversariale non è stata eseguita.",
    "secondary_reader": "Destinatario secondario: {reader}",
    "no_structure": "La struttura societaria non è dichiarata dagli stage "
                    "approvati.",
    "beachhead": "Il segmento beachhead è: {segment}.",
    "roles_intro": "Ruoli colpiti dal problema:",
    "empty_list": "Nessuna voce è dichiarata dallo stage approvato per questa "
                  "sezione.",
    "no_ip_assets": "Lo stage operations e IP non dichiara alcun asset di "
                    "proprietà intellettuale.",
    "no_know_how": "Lo stage operations e IP non dichiara misure di "
                   "protezione del know-how.",
    "no_financing": "La richiesta di finanziamento non collega alcuna "
                    "milestone al capitale richiesto.",
    "financing_summary": "Residuo non mappato dichiarato dalla richiesta di "
                         "finanziamento: {residual}; milestone fuori "
                         "dall'orizzonte: {count}.",
    "risks_not_applicable": "Nessun rischio è registrato e nessuno stage "
                            "approvato vi fa riferimento.",
    "uncovered_intro": "Driver senza copertura di scenario, elencati per "
                       "nome:",
    "fin_validation": "Esito della validazione: {result}; stato propagato: "
                      "{propagated}; prontezza per l'investitore: "
                      "{readiness}.",
    "blocking_intro": "Motivi dichiarati che impediscono la prontezza per "
                      "l'investitore:",
    "fr_governance": "Stato propagato dalla richiesta di finanziamento: "
                     "{state}; esito della validazione a monte: {result}; "
                     "prontezza a monte: {readiness}.",
    "index_intro": "L'indice completo della data room è il suo derivato, "
                   "elencato con la propria impronta fra gli ingressi di "
                   "provenienza di questa appendice.",
    "no_sources": "Nessuna fonte registrata è collegata alle evidenze citate "
                  "dai claim.",
    "no_conditions": "Il registro delle condizioni non è presente nel "
                     "progetto.",
    "no_conflicts": "La data room non dichiara alcuna incoerenza fra "
                    "evidenze.",
    "stale_intro": "Evidenze non correnti alla data di riferimento della data "
                   "room:",
    "no_stale": "La data room non dichiara evidenze non correnti.",
    "drift_intro": "Registri modificati dopo la costruzione della data room: "
                   "i valori resi restano quelli del registro corrente, e la "
                   "data room ne conserva la versione precedente.",
    "labels_notice": "I valori seguiti da un'etichetta tra parentesi — "
                     "ipotesi del founder, stima, dato mancante, da validare — "
                     "restano assunzioni del piano e non fatti verificati.",
    "review_notice": "La review finale avversariale del documento non è stata "
                     "eseguita in questa release.",
    "export_notice": "La numerazione del documento è logica: non sono "
                     "presenti numeri di pagina, e l'esportazione in PDF o "
                     "DOCX non è disponibile in questa release.",
    "refs_line": "Riferimenti — claim della data room collegati a questo "
                 "capitolo: {claims*}. Il registro completo dei claim è "
                 "nell'appendice.",
    "incoherence_contradiction":
        "INCOERENZA RILEVATA\n\nID: {issue}\nVariabile: claim {claim}\n"
        "Valore A: {evidence_a} (shared/evidence-register.json)\n"
        "Valore B: {evidence_b} (shared/evidence-register.json)\n"
        "Impatto: tracciabilità claim -> evidenza della data room\n"
        "Severità: {severity}\nDecisione richiesta: {decision}\n"
        "File coinvolti: {files*}",
    "incoherence_duplicate":
        "INCOERENZA RILEVATA\n\nID: {issue}\n"
        "Variabile: evidenza duplicata nel registro\n"
        "Valore A: {evidence_a} (shared/evidence-register.json)\n"
        "Valore B: {evidence_b} (shared/evidence-register.json)\n"
        "Impatto: tracciabilità claim -> evidenza della data room\n"
        "Severità: {severity}\nDecisione richiesta: {decision}\n"
        "File coinvolti: {files*}",
}
SLOT_RE = re.compile(r"\{([a-z_]+)(\*?)\}")

#: I testi COSTANTI ammessi come intestazione o cella di tabella: etichette di
#: riga, valori booleani, segnaposto di cella vuota. Tutti privi di cifre.
CELL_CONSTANTS = frozenset((
    "-", "sì", "no", "Voce", "Valore", "Nome del progetto", "Tipo di startup",
    "Fase di sviluppo", "Destinatario principale",
    "Forma di finanziamento cercata", "Orizzonte del piano", "Tipo di problema",
    "Frequenza", "Intensità", "Percepito o dimostrato", "Tempo perso",
    "Ruoli colpiti", "Alternativa", "Perché non basta", "Segmento",
    "Descrizione", "Aderenza al problema", "Accessibilità",
    "Processo di acquisto", "Utente", "Acquirente", "Decisore", "Pagante",
    "Dimensione", "Job", "Pain", "Gain", "Problema o beneficio",
    "Risposta della soluzione", "Metrica", "Affermazione",
    "Classe di evidenza", "Grandezza", "TAM", "SAM", "SOM", "Area geografica",
    "Periodo", "Categoria", "Concorrente", "Valutazione", "Note di ricerca",
    "nessuno identificato", "Prezzo", "Ricavi", "Margine di contribuzione",
    "Ricorrenza", "Canale", "Contatti generati", "Clienti acquisiti",
    "Spesa commerciale", "Costo di acquisizione", "Tasso di abbandono",
    "Capacità di ricavo", "Processo", "Modalità", "Responsabile indicativo",
    "Collo di bottiglia", "Capacità operativa", "Costo operativo unitario",
    "Dipendenza", "Fornitore unico", "Mitigazione", "Requisito", "Asset",
    "Protezione", "Motivazione", "Ruolo", "Stato", "Responsabilità",
    "in organico", "posizione aperta", "Impegno", "Lacuna", "Risposta",
    "Note", "Costo", "Area", "Titolare", "Struttura", "Vesting", "Incentivi",
    "Socio", "Quota", "Advisor", "Milestone", "Inizio", "Obiettivo",
    "Copertura della richiesta", "non coperta dalla richiesta", "Dipende da",
    "Criterio di successo", "Regola go/no-go", "Criterio di uscita",
    "Data obiettivo", "Importo", "Copertura", "Finanziata da",
    "Fuori orizzonte", "Rischio", "Probabilità", "Impatto", "Severità",
    "Piano di contingenza", "Segnale di allerta", "Richiamato da",
    "Operations e IP", "Team e governance", "Roadmap",
    "Data di ancoraggio", "Periodi dell'orizzonte", "Modulo", "Scenario",
    "copertura", "livello", "rapporto", "stato", "motivazione",
    "Documento", "Percorso", "Riferimento data room", "Versione",
    "Capitale richiesto", "Fabbisogno modellato", "Arrotondamento applicato",
    "Politica di determinazione", "Percentuale",
    "Runway prima del finanziamento, misura a cassa zero",
    "Runway prima del finanziamento, misura a buffer",
    "Misura di riferimento", "Runway dopo il finanziamento",
    "Orizzonte finanziato", "Gap residuo", "Base della sufficienza",
    "Tranche", "Supporto", "Sezione", "Testo", "Decisione", "Domanda",
    "Bloccante", "Gravità", "Codice", "Messaggio", "Claim", "Enunciato",
    "Capitolo", "Evidenza", "Classe", "Legame", "Stato nel registro",
    "Assunzione", "Variabile", "Stato di validazione", "Fonte", "Titolo",
    "Editore", "Tipo", "Data", "Condizione", "Responsabile",
    "Da risolvere prima di", "Prova", "Riferimento", "Dettaglio", "Ingresso",
    "Disponibilità", "Corrispondenza con la data room",
    "Criterio di selezione",
    "Data dichiarata del documento", "Etichetta di versione",
    "Fabbisogno di cassa, misura a cassa zero",
    "Fabbisogno di cassa, misura a buffer",
    "Runway, misura a cassa zero, in periodi",
    "Runway, misura a buffer, in periodi", "Esito del modulo di pareggio",
    "Runway prima del finanziamento a cassa zero",
    "Runway prima del finanziamento a buffer",
)) | frozenset(title for _, title in CHAPTERS) | frozenset(
    label for _, label in COMPETITION_CATEGORIES)

#: Il `generator` del front matter, privo di cifre.
GENERATOR = "business-plan-orchestrator · validate_document_generation"
FRONT_MATTER_KEYS = ("title", "project", "version", "date", "language",
                     "reader", "document_identity", "generator")
TERMINAL_TASK = "plan-complete"

CANONICAL_NUM = r"(?:[0-9]{3}|[1-9][0-9]{3,})"
ID_FORMS = {
    "ASS": re.compile(rf"^ASS-{CANONICAL_NUM}\Z"),
    "EVD": re.compile(rf"^EVD-{CANONICAL_NUM}\Z"),
    "SRC": re.compile(rf"^SRC-{CANONICAL_NUM}\Z"),
    "COND": re.compile(rf"^COND-{CANONICAL_NUM}\Z"),
    "MIL": re.compile(rf"^MIL-{CANONICAL_NUM}\Z"),
    "CLM": re.compile(rf"^CLM-{CANONICAL_NUM}\Z"),
    "DR": re.compile(rf"^DR-{CANONICAL_NUM}\Z"),
    "SEG": re.compile(rf"^SEG-{CANONICAL_NUM}\Z"),
    "ROLE": re.compile(rf"^ROLE-{CANONICAL_NUM}\Z"),
    "RISK": re.compile(r"^RISK-[0-9]{3,}\Z"),
}
ISO_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
ID_NUMBER_RE = re.compile(r"-([0-9]+)\Z")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\Z")
PATH_TOKEN_RE = re.compile(
    r'\.([A-Za-z_][A-Za-z0-9_]*)|\[([0-9]+)\]|\["((?:[^"\\]|\\.)*)"\]')
TX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")
LINE_BREAKS_RE = re.compile(r"[\r\n\x0b\x0c\x1c\x1d\x1e\x85  ]+")
BLOCK_MARKER_RE = re.compile(r"^(?:[#>*+=|`~_-]|[0-9]+[.)](?:\s|$))")

#: Pattern DICHIARATI dei segreti, gli stessi della Data Room: `re.ASCII`
#: tiene i confini `\b` sull'alfabeto ASCII dei token, cosi' un segreto
#: adiacente a un carattere non ASCII resta riconosciuto.
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

#: QG-05 — segnaposto e linguaggio di debug, elenco CHIUSO. I token di
#: lavorazione sono cercati come parola intera SENZA distinzione di maiuscole;
#: le quattro grafie di un valore assente serializzato (`None`, `null`, `NaN`,
#: `undefined`) sono cercate nella loro grafia ESATTA, perche' la narrativa
#: canonica dello Stage 11 cita l'enum `none` in minuscolo.
PLACEHOLDER_WORDS = re.compile(
    r"(?<![A-Za-z0-9_])(?:TODO|TBD|FIXME|lorem|traceback|DEBUG)"
    r"(?![A-Za-z0-9_])", re.IGNORECASE)
PLACEHOLDER_EXACT = re.compile(
    r"(?<![A-Za-z0-9_])(?:None|null|NaN|undefined)(?![A-Za-z0-9_])")
PLACEHOLDER_MARKS = re.compile(r"\{\{|\}\}|P-ASS-|\{[a-z_]+\*?\}|<[a-z_]+>")
#: QG-06 — path interni: aree transitorie, path assoluti, localizzatori
#: `json_path` del canonico dello Stage 13 (forma `$.` o `$[`).
INTERNAL_PATHS = re.compile(
    r"\.working/|shared/\.tx|(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\|"
    r"(?:^|(?<=[\s(\[\"']))/(?:[A-Za-z0-9._-]+/)+|\$\.[A-Za-z_]|\$\[")
DIGIT_CATEGORIES = ("Nd", "Nl", "No")


class BuildRefusal(Exception):
    """Rifiuto ATTRIBUITO: nessun file e' pubblicato."""

    def __init__(self, errors):
        super().__init__("; ".join(message for _, _, message in errors))
        self.errors = errors


# --------------------------------------------------------------------------
# Lettura STRETTA e lessicalmente senza perdita
# --------------------------------------------------------------------------


class LexNum(str):
    """Un numero JSON conservato come la sua STRINGA SORGENTE: nessuna
    conversione, nessun arrotondamento."""
    __slots__ = ()


def _no_constant(name):
    raise ValueError(f"costante JSON non ammessa: {name}")


def _unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"chiave duplicata: {key!r}")
        out[key] = value
    return out


def strict_loads(text, lexical=True):
    """JSON STRETTO: chiavi duplicate e `NaN`/`Infinity` respinti. Con
    `lexical` ogni numero resta la stringa sorgente (`LexNum`)."""
    options = {"object_pairs_hook": _unique_pairs,
               "parse_constant": _no_constant}
    if lexical:
        options.update(parse_int=LexNum, parse_float=LexNum)
    return json.loads(text, **options)


def lexical(value):
    """La forma LESSICALE di una foglia: stringa, `true`/`false`, `None`."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return str(value)
    return None


def plain(node):
    """Copia di un nodo lessicale con i `LexNum` resi stringhe semplici."""
    if isinstance(node, dict):
        return {key: plain(value) for key, value in node.items()}
    if isinstance(node, list):
        return [plain(value) for value in node]
    if isinstance(node, str):
        return str(node)
    return node


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def record_fingerprint(record):
    """L'impronta PINNATA di un record `ASS-*` (`record_fingerprint` del
    Transaction Manager, algoritmo (B)): sha256 della serializzazione compatta
    a chiavi ordinate e `ensure_ascii` del record LETTO dal JSON."""
    blob = json.dumps(record, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)
    return sha256_bytes(blob.encode("utf-8"))


def id_number(ref):
    match = ID_NUMBER_RE.search(str(ref or ""))
    return int(match.group(1)) if match else -1


def is_form(kind, ref):
    return isinstance(ref, str) and bool(ID_FORMS[kind].match(ref))


def has_digit(text):
    return any(unicodedata.category(char) in DIGIT_CATEGORIES
               for char in str(text))


# --------------------------------------------------------------------------
# json_path del canonico: `$`, `.chiave`, `[indice]`, `["chiave"]`
# --------------------------------------------------------------------------


def jp(*parts):
    out = "$"
    for part in parts:
        if isinstance(part, int) and not isinstance(part, bool):
            out += f"[{part}]"
        elif IDENT_RE.match(str(part)):
            out += "." + str(part)
        else:
            out += "[" + json.dumps(str(part), ensure_ascii=True) + "]"
    return out


def resolve_path(document, path):
    if not isinstance(path, str) or not path.startswith("$"):
        raise KeyError(path)
    node = document
    position = 1
    while position < len(path):
        match = PATH_TOKEN_RE.match(path, position)
        if not match:
            raise KeyError(path)
        try:
            if match.group(1) is not None:
                node = node[match.group(1)]
            elif match.group(2) is not None:
                if not isinstance(node, list):
                    raise KeyError(path)
                node = node[int(match.group(2))]
            else:
                node = node[json.loads('"' + match.group(3) + '"')]
        except (KeyError, IndexError, TypeError, ValueError):
            raise KeyError(path)
        position = match.end()
    return node


def leaves_of(node):
    """Ogni stringa foglia e ogni CHIAVE di un sottoalbero: l'insieme dei
    testi verbatim ammessi in un blocco di origine canonica."""
    out = set()
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                out.add(str(key))
                stack.append(value)
        elif isinstance(current, list):
            stack.extend(current)
        elif isinstance(current, str):
            out.add(str(current))
    return out


def json_strings(node):
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
    """Le stringe DECODIFICATE di un JSON, una per riga: la stessa
    rappresentazione per la forma `ensure_ascii`, la riscrittura UTF-8 del
    Transaction Manager e la view di impact."""
    return "\n".join(json_strings(document))


# --------------------------------------------------------------------------
# Motore MINIMO di JSON Schema, in libreria standard
# --------------------------------------------------------------------------

DECIMAL_RE = re.compile(r"^(-?)([0-9]+)(?:\.([0-9]+))?\Z")


def lexical_order(left, right):
    """Confronto LESSICALE di due decimali in forma piana, senza alcuna
    conversione numerica: -1, 0, 1, o `None` se una forma non e' piana."""
    one, two = DECIMAL_RE.match(str(left)), DECIMAL_RE.match(str(right))
    if not one or not two:
        return None

    def parts(match):
        integer = match.group(2).lstrip("0") or "0"
        fraction = (match.group(3) or "").rstrip("0")
        negative = bool(match.group(1)) and (integer != "0" or fraction)
        return negative, integer, fraction
    neg_a, int_a, frac_a = parts(one)
    neg_b, int_b, frac_b = parts(two)
    if neg_a != neg_b:
        return -1 if neg_a else 1
    width = max(len(frac_a), len(frac_b))
    key_a = (len(int_a), int_a, frac_a.ljust(width, "0"))
    key_b = (len(int_b), int_b, frac_b.ljust(width, "0"))
    order = (key_a > key_b) - (key_a < key_b)
    return -order if neg_a else order


def _resolve_ref(root, node):
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
        if kind == "string" and isinstance(value, str) and \
                not isinstance(value, LexNum):
            return True
        if kind == "boolean" and isinstance(value, bool):
            return True
        if kind == "integer" and (
                (isinstance(value, int) and not isinstance(value, bool)) or
                (isinstance(value, LexNum) and
                 re.match(r"^-?[0-9]+\Z", value))):
            return True
        if kind == "number" and (
                (isinstance(value, int) and not isinstance(value, bool)) or
                isinstance(value, LexNum)):
            return True
        if kind == "object" and isinstance(value, dict):
            return True
        if kind == "array" and isinstance(value, list):
            return True
    return False


def _same(left, right):
    return json.dumps(plain(left), sort_keys=True) == \
        json.dumps(plain(right), sort_keys=True)


def _number_text(value):
    return str(value) if isinstance(value, str) else json.dumps(value)


def schema_issues(root, node, value, path="$"):
    """Gli scostamenti di `value` dallo schema, ciascuno col proprio path:
    $ref, type, const, enum, pattern, minLength, minimum, maximum, required,
    additionalProperties, properties, items, minItems, maxItems, uniqueItems,
    allOf, anyOf, oneOf, not."""
    node = _resolve_ref(root, node)
    if not isinstance(node, dict):
        return []
    issues = []
    expected = node.get("type")
    if expected is not None and not _type_ok(expected, value):
        return [(path, f"tipo non ammesso: atteso {expected}")]
    if "const" in node and not _same(value, node["const"]):
        issues.append((path, f"atteso il valore costante {node['const']!r}"))
    if "enum" in node and not any(_same(value, item) for item in node["enum"]):
        issues.append((path, f"valore {plain(value)!r} fuori dall'enum"))
    if isinstance(value, str) and not isinstance(value, LexNum):
        if "minLength" in node and len(value) < node["minLength"]:
            issues.append((path, "stringa troppo corta"))
        if "pattern" in node and not re.search(node["pattern"], value):
            issues.append((path, f"{value!r} non rispetta {node['pattern']}"))
    if (isinstance(value, (int, LexNum)) and not isinstance(value, bool)):
        for keyword, sign in (("minimum", -1), ("maximum", 1)):
            if keyword in node:
                order = lexical_order(_number_text(value),
                                      _number_text(node[keyword]))
                if order is None or order == sign:
                    issues.append((path, f"{value} viola {keyword} "
                                         f"{node[keyword]}"))
    if isinstance(value, dict):
        properties = node.get("properties") or {}
        for key in node.get("required") or ():
            if key not in value:
                issues.append((f"{path}.{key}",
                               f"proprieta' obbligatoria assente: {key}"))
        if node.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    issues.append((f"{path}.{key}",
                                   f"proprieta' inattesa {key!r}: l'oggetto "
                                   "e' chiuso"))
        for key, sub in properties.items():
            if key in value:
                issues += schema_issues(root, sub, value[key], jp_join(path,
                                                                       key))
    if isinstance(value, list):
        if "minItems" in node and len(value) < node["minItems"]:
            issues.append((path, f"{len(value)} voci < {node['minItems']}"))
        if "maxItems" in node and len(value) > node["maxItems"]:
            issues.append((path, f"{len(value)} voci > {node['maxItems']}"))
        if node.get("uniqueItems"):
            seen = [json.dumps(plain(item), sort_keys=True) for item in value]
            if len(set(seen)) != len(seen):
                issues.append((path, "voci duplicate in un elenco unico"))
        if "items" in node:
            for position, item in enumerate(value):
                issues += schema_issues(root, node["items"], item,
                                        f"{path}[{position}]")
    for sub in node.get("allOf") or ():
        issues += schema_issues(root, sub, value, path)
    if "anyOf" in node and not any(
            not schema_issues(root, sub, value, path) for sub in node["anyOf"]):
        issues.append((path, "nessuna alternativa di anyOf e' soddisfatta"))
    if "oneOf" in node:
        matched = len([sub for sub in node["oneOf"]
                       if not schema_issues(root, sub, value, path)])
        if matched != 1:
            issues.append((path, f"oneOf soddisfatto da {matched} "
                                 "alternative invece di una"))
    if "not" in node and not schema_issues(root, node["not"], value, path):
        issues.append((path, "il valore soddisfa uno schema vietato (not)"))
    return issues


def jp_join(path, key):
    if IDENT_RE.match(str(key)):
        return f"{path}.{key}"
    return f"{path}[{json.dumps(str(key), ensure_ascii=True)}]"


def load_schema(name):
    path = SCHEMAS_DIR / f"{name}.schema.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise fw.ValidatorUsageError(
            f"schema assente o malformato: {path}: {exc}")


# --------------------------------------------------------------------------
# Contenimento dei path — la STESSA regola di `safe_rel_path`
# --------------------------------------------------------------------------


def unsafe_path_reason(rel):
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
    """Symlink (ogni OS) e junction/symlink reparse point NTFS: la STESSA
    regola del Transaction Manager."""
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
    """Il path risolto dentro il progetto, oppure il motivo per cui non lo
    e': nessun componente symlink/junction/reparse point, containment
    finale."""
    reason = unsafe_path_reason(rel)
    if reason:
        return None, reason
    current = Path(project)
    for part in rel.split("/"):
        current = current / part
        if _is_link_or_reparse(current):
            return None, f"il path attraversa un symlink/reparse point: {rel!r}"
    try:
        inside = Path(os.path.realpath(current)).is_relative_to(
            Path(os.path.realpath(project)))
    except (OSError, ValueError):
        inside = False
    if not inside:
        return None, f"il path esce dal progetto: {rel!r}"
    return current, None


def area_target(project, rel, area):
    """Un bersaglio di SCRITTURA dentro l'area PROPRIA `area`, verificato a
    ogni strato; `None` e il motivo altrimenti."""
    if not str(rel).startswith(area):
        return None, f"{rel!r} e' fuori dall'area di scrittura {area}"
    target, reason = contained(project, rel)
    if reason:
        return None, reason
    base = Path(os.path.realpath(project)) / area.rstrip("/")
    try:
        inside = Path(os.path.realpath(target)).is_relative_to(base)
    except (OSError, ValueError):
        inside = False
    if not inside:
        return None, f"{rel!r} risolve fuori da {area}"
    return target, None


def tx_reason(tx):
    if not TX_RE.match(str(tx)) or str(tx).endswith("."):
        return (f"--tx {tx!r} non e' un singolo segmento sicuro: ammessi "
                "[A-Za-z0-9._-], senza separatori, lettera di drive, ':' o "
                "punto finale")
    return None


def project_fingerprint(project, own):
    """Impronta di OGNI file del progetto fuori dalle aree PROPRIE `own`,
    senza attraversare collegamenti (`docgen_upstream_mutated`)."""
    out = {}
    root = Path(project)
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            items = sorted(current.iterdir())
        except OSError:
            continue
        for item in items:
            if _is_link_or_reparse(item):
                continue
            rel = item.relative_to(root).as_posix()
            if any(rel == area.rstrip("/") or rel.startswith(area)
                   for area in own):
                continue
            if item.is_dir():
                stack.append(item)
            elif item.is_file():
                out[rel] = sha256_file(item)
    return out


# --------------------------------------------------------------------------
# INGRESSI — letti FAIL-CLOSED, con i controlli XS-01...XS-04 e XS-08
# --------------------------------------------------------------------------


def incoherence(issue, variable, value_a, file_a, value_b, file_b, impact,
                decision, files):
    """Il blocco `INCOERENZA RILEVATA` di `CLAUDE.md`: nessun valore e'
    scelto, mediato o trattato come refuso."""
    return ("INCOERENZA RILEVATA\n\n"
            f"ID: {issue}\nVariabile: {variable}\n"
            f"Valore A: {value_a} ({file_a})\nValore B: {value_b} ({file_b})\n"
            f"Impatto: {impact}\nSeverità: High\n"
            f"Decisione richiesta: {decision}\n"
            f"File coinvolti: {', '.join(files)}")


class Inputs:
    """Gli ingressi dello Stage 13, letti in SOLA LETTURA.

    `mode` e' `build`/`egress` (tutti i controlli, derivati compresi),
    `publish` (progetto reale, predicato terminale) o `impact` (validation
    view del Transaction Manager: solo `shared/` e i canonici di stage)."""

    def __init__(self, project, config, mode):
        self.project = Path(project)
        self.config = config
        self.mode = mode
        self.errors = []
        self.warnings = []
        self.docs = {}
        self.raw = {}
        self.sha = {}
        self.issue = 0
        self.status = self.read_status()
        self.check_chain()
        self.load_all()

    # ---- utilita' --------------------------------------------------------

    def error(self, code, ref, message):
        self.errors.append((code, ref, message))

    def next_issue(self):
        self.issue += 1
        return f"ISSUE-DG-{self.issue:03d}"

    def read_status(self):
        path = self.project / STATUS_REL
        if not path.is_file():
            raise fw.CanonicalStateError(f"{STATUS_REL} assente")
        return fw.parse_front_matter(path.read_text(encoding="utf-8"))

    def ordered_stages(self):
        order = self.config["stage_order"]
        return [stage for stage, _ in sorted(order.items(),
                                             key=lambda item: int(item[1]))]

    def check_chain(self):
        """`XS-01` — catena completa e Stage 13 non ancora completato
        (`--build`, egress); predicato terminale (`--publish`)."""
        completed = self.status.get("completed_stages") or []
        current = self.status.get("current_stage")
        order = self.ordered_stages()
        if self.mode in ("build", "egress"):
            missing = [stage for stage in order if stage != STAGE13 and
                       stage not in completed]
            if current != STAGE13:
                self.error(CODE_CHAIN, "current_stage",
                           f"current_stage e' {current!r}: lo Stage 13 si "
                           f"costruisce solo con current_stage {STAGE13}")
            if missing:
                self.error(CODE_CHAIN, "completed_stages",
                           f"stage non completati: {missing}: il documento "
                           "finale assembla SOLO stage approvati")
            if STAGE13 in completed:
                self.error(CODE_CHAIN, STAGE13,
                           f"{STAGE13} e' gia' completato: il canonico "
                           "committato e' immutabile (stage_already_completed)")
        elif self.mode == "publish":
            if not (current == order[-1] and current in completed):
                self.error(CODE_CHAIN, "project-status",
                           "predicato terminale FALSO: il derivato si pubblica "
                           "solo dopo l'advance-stage terminale dello Stage 13 "
                           f"(current_stage {current!r})")

    def read_file(self, rel, required=True):
        target, reason = contained(self.project, rel)
        if reason:
            self.error(CODE_PATH_ESCAPE, rel, reason)
            return None
        if not target.is_file():
            if required:
                self.error(CODE_INPUT_MISSING, rel,
                           f"ingresso obbligatorio {rel!r} ASSENTE")
            return None
        data = target.read_bytes()
        self.raw[rel] = data
        self.sha[rel] = sha256_bytes(data)
        return data

    def load_json(self, rel, required=True):
        data = self.read_file(rel, required)
        if data is None:
            return None
        try:
            document = strict_loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            self.error(CODE_INPUT_INVALID, rel,
                       f"{rel!r} non e' JSON stretto: {exc}")
            return None
        self.docs[rel] = document
        return document

    # ---- caricamento -----------------------------------------------------

    def load_all(self):
        view = self.mode == "impact"
        self.config_doc = self.load_json(CONFIG_REL)
        self.profile = self.load_json(PROFILE_REL)
        self.stages = {}
        for stage in CONTENT_STAGES:
            rel = f"{stage}/{CANONICAL_NAME}"
            document = self.load_json(rel)
            self.stages[stage] = document
            for name in DERIVED.get(stage, ()):
                if not view:
                    self.read_file(f"{stage}/{name}")
        self.registers = {}
        for rel in REGISTERS:
            entries = self.load_json(rel, required=rel in REQUIRED_REGISTERS)
            if entries is None:
                self.registers[rel] = [] if rel in OPTIONAL_REGISTERS else None
                continue
            if not isinstance(entries, list) or \
                    not all(isinstance(item, dict) for item in entries):
                self.error(CODE_INPUT_INVALID, rel,
                           f"{rel!r} non e' un elenco di oggetti")
                entries = None
            self.registers[rel] = entries
        self.check_shapes()

    def check_shapes(self):
        for stage, name in STAGE_SCHEMAS.items():
            document = self.stages.get(stage)
            if document is None:
                continue
            schema = load_schema(name)
            for path, message in schema_issues(schema, schema, document)[:8]:
                self.error(CODE_INPUT_INVALID, f"{stage}:{path}",
                           f"{stage} non conforme a {name}.schema.json: "
                           f"{message}")
        for stage, version in SUPPORTED_VERSIONS.items():
            document = self.stages.get(stage)
            if isinstance(document, dict) and \
                    document.get("schema_version") != version:
                self.error(CODE_INPUT_INVALID, stage,
                           f"{stage}: schema_version "
                           f"{document.get('schema_version')!r} non supportata "
                           f"(attesa {version})")
        required = (
            (S01, ("problem_statement", "description"), str),
            (S02, ("customer_segments",), list),
            (S02, ("beachhead", "segment_ref"), str),
            (S03, ("value_proposition", "segment_ref"), str),
            (S03, ("value_proposition", "switching_rationale"), str),
            (S04, ("market_model",), dict),
            (S04, ("competitive_landscape", "categories"), dict),
            (S05, ("business_model", "pricing_ref"), str),
            (S06, ("sales_funnel",), dict),
            (S10, ("financial_plan", "results", "modules"), dict),
            (S10, ("financial_plan", "results", "calendar"), dict),
            (S10, ("financial_plan", "results", "scenarios"), dict),
            (S10, ("financial_plan", "validation"), dict),
            (S10, ("financial_plan", "driver_registry", "drivers"), list),
            (S11, ("funding_request", "requested_capital", "amount"), str),
            (S11, ("funding_request", "use_of_proceeds"), list),
            (S11, ("funding_request", "runway"), dict),
            (S11, ("funding_request", "sufficiency"), dict),
            (S11, ("funding_request", "source"), dict),
            (S11, ("funding_request", "narrative", "sections"), list),
            (S11, ("funding_request", "governance"), dict),
            (S12, ("data_room", "documents"), list),
            (S12, ("data_room", "claims"), list),
            (S12, ("data_room", "sections"), list),
            (S12, ("data_room", "completeness"), dict),
            (S12, ("data_room", "identity"), dict),
        )
        for stage, parts, kind in required:
            document = self.stages.get(stage)
            if document is None:
                continue
            try:
                value = resolve_path(document, jp(*parts))
            except KeyError:
                value = None
            if not isinstance(value, kind) or (kind is str and not value):
                self.error(CODE_INPUT_INVALID, f"{stage}:{jp(*parts)}",
                           f"{stage}: {jp(*parts)} assente o di tipo non "
                           "ammesso per l'assemblaggio")
        if isinstance(self.profile, dict):
            for key in ("startup_type", "development_stage", "primary_reader"):
                if not isinstance(self.profile.get(key), str):
                    self.error(CODE_INPUT_INVALID, f"{PROFILE_REL}:{key}",
                               f"{PROFILE_REL}: {key} assente")
        if isinstance(self.config_doc, dict):
            for key in ("project_name", "project_slug"):
                if not isinstance(self.config_doc.get(key), str):
                    self.error(CODE_INPUT_INVALID, f"{CONFIG_REL}:{key}",
                               f"{CONFIG_REL}: {key} assente")

    # ---- XS-02 / XS-03 / XS-04 / XS-08 -------------------------------------

    def room(self):
        document = self.stages.get(S12)
        return (document or {}).get("data_room") or {}

    def indexed(self):
        return {str(item.get("path")): item for item in
                self.room().get("documents") or () if isinstance(item, dict)}

    def pins(self):
        """`XS-02` e `XS-03`: ogni ingresso immutabile ha lo sha256 del
        manifest della Data Room; i registri modificati dopo sono un WARNING
        divulgato."""
        index = self.indexed()
        drift = []
        immutable = [f"{stage}/{CANONICAL_NAME}" for stage in PINNED_STAGES]
        immutable += [f"{stage}/{name}" for stage in (S10, S11)
                      for name in DERIVED[stage]]
        for rel in immutable:
            if rel not in self.sha:
                continue
            entry = index.get(rel)
            pinned = (entry or {}).get("checksum")
            if entry is None or not isinstance(pinned, str):
                self.error(CODE_INPUT_STALE, rel,
                           f"{rel!r} non e' indicizzato con un checksum dalla "
                           "Data Room: la sua provenienza non e' pinnabile")
                continue
            if pinned != self.sha[rel]:
                self.error(CODE_INPUT_STALE, rel, incoherence(
                    self.next_issue(), f"checksum di {rel}", pinned,
                    f"{S12}/{CANONICAL_NAME}", self.sha[rel], rel,
                    "il documento finale non e' assemblabile: l'ingresso non "
                    "e' quello indicizzato e pinnato dalla Data Room",
                    "ripristinare il file o riaprire lo stage con il "
                    "protocollo di riapertura; nessun valore e' scelto",
                    [rel, f"{S12}/{CANONICAL_NAME}"]))
        for rel in REGISTERS:
            if rel not in self.sha:
                continue
            entry = index.get(rel)
            if entry is not None and entry.get("checksum") != self.sha[rel]:
                drift.append(rel)
        return drift

    def financial_basis(self):
        """`XS-04` — impronta del record `ASS-*` corrente = `source_record_
        hash` di ogni driver dello Stage 10."""
        plan = self.stages.get(S10) or {}
        drivers = ((plan.get("financial_plan") or {}).get("driver_registry")
                   or {}).get("drivers") or []
        raw = self.raw.get(ASSUMPTIONS_REL)
        if raw is None:
            return
        records = {}
        for entry in json.loads(raw.decode("utf-8")):
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                records[entry["id"]] = entry
        for driver in drivers:
            if not isinstance(driver, dict):
                continue
            ref = driver.get("source_ref")
            pinned = driver.get("source_record_hash")
            if not isinstance(ref, str) or not isinstance(pinned, str):
                continue
            record = records.get(ref)
            current = record_fingerprint(record) if record is not None \
                else "record assente"
            if current != pinned:
                self.error(CODE_FIN_BASIS, ref, incoherence(
                    self.next_issue(),
                    f"record {ref} del driver {driver.get('driver_id')}",
                    pinned, f"{S10}/{CANONICAL_NAME}", current,
                    ASSUMPTIONS_REL,
                    "il piano finanziario e' stato calcolato su un record "
                    "diverso da quello corrente: ogni numero finanziario "
                    "sarebbe stantio",
                    "rieseguire lo Stage 10 sul registro corrente con il "
                    "protocollo di riapertura, oppure ripristinare il record; "
                    "nessun valore e' scelto",
                    [ASSUMPTIONS_REL, f"{S10}/{CANONICAL_NAME}"]))

    def funding_projection(self):
        """`XS-08` — la funding request proietta QUESTO piano finanziario."""
        request = (self.stages.get(S11) or {}).get("funding_request") or {}
        source = request.get("source") or {}
        expected = f"{S10}/{CANONICAL_NAME}"
        if source.get("stage") != S10 or \
                source.get("canonical_path") != expected:
            self.error(CODE_INPUT_INVALID, f"{S11}:$.funding_request.source",
                       f"la funding request non proietta {expected}: "
                       f"{plain(source)}")

    def inputs_manifest(self, drift):
        """`inputs[]`: ogni ingresso con ruolo, impronta e corrispondenza con
        la Data Room, ordinato per path."""
        index = self.indexed()
        entries = []

        def add(rel, role, stage):
            if rel not in self.sha:
                return
            entry = index.get(rel)
            if role in ("project_profile", "data_room_manifest") or \
                    (role == "stage_derived" and stage == S12):
                match = "not_indexed"
            elif role == "shared_register":
                match = "register_drift" if rel in drift else (
                    "match" if entry is not None else "not_indexed")
            else:
                match = "match"
            entries.append({
                "path": rel, "role": role, "stage": stage,
                "sha256": self.sha[rel],
                "data_room_document_id": (entry or {}).get("document_id")
                if match != "not_indexed" else None,
                "data_room_match": match})
        add(CONFIG_REL, "project_profile", None)
        add(PROFILE_REL, "project_profile", None)
        for stage in PINNED_STAGES:
            add(f"{stage}/{CANONICAL_NAME}", "stage_canonical", stage)
        add(f"{S12}/{CANONICAL_NAME}", "data_room_manifest", S12)
        for stage, names in DERIVED.items():
            for name in names:
                add(f"{stage}/{name}", "stage_derived", stage)
        for rel in REGISTERS:
            add(rel, "shared_register", None)
        return sorted(entries, key=lambda item: item["path"])


# --------------------------------------------------------------------------
# Proposta del writer
# --------------------------------------------------------------------------


def validate_proposal(proposal):
    """Schema chiuso di `$defs.proposal`, data valida, nessuna cifra in
    `version_label`. Ritorna gli errori attribuiti."""
    errors = []
    schema = load_schema("document-generation")
    for path, message in schema_issues(schema, schema["$defs"]["proposal"],
                                       proposal):
        errors.append((CODE_PROPOSAL, path, f"proposta: {message}"))
    if errors:
        return errors
    try:
        date.fromisoformat(proposal["as_of"])
    except ValueError:
        errors.append((CODE_PROPOSAL, "as_of",
                       f"as_of {proposal['as_of']!r} non e' una data valida"))
    if has_digit(proposal["version_label"]):
        errors.append((CODE_UNTRACED, "version_label",
                       "version_label contiene una cifra: nessuna cifra entra "
                       "nel documento fuori da un letterale legato"))
    return errors


def read_proposal(candidate):
    path = Path(candidate) / PROPOSAL_NAME
    if not path.is_file():
        return None, [(CODE_PROPOSAL, PROPOSAL_NAME,
                       "la proposta del writer e' ASSENTE dal candidate")]
    try:
        proposal = strict_loads(path.read_text(encoding="utf-8"),
                                lexical=False)
    except (UnicodeDecodeError, ValueError) as exc:
        return None, [(CODE_PROPOSAL, PROPOSAL_NAME,
                       f"proposta illeggibile: {exc}")]
    errors = validate_proposal(proposal)
    return (None if errors else proposal), errors


# --------------------------------------------------------------------------
# Formattazione dei letterali legati — funzione PURA della chiave
# --------------------------------------------------------------------------


def format_binding(key, value, unit, currency, qualifier):
    """Il letterale reso: valore VERBATIM, unita' o valuta, etichetta
    epistemica. Nessuna localizzazione, nessun arrotondamento."""
    if value is None:
        text = "non disponibile"
    elif value == "NOT_APPLICABLE":
        text = "non applicabile"
    elif key.startswith("profile."):
        text = PROFILE_LABELS.get(key.split(".")[1], {}).get(value, value)
    elif key == "financial.calendar.frequency":
        text = FREQUENCY_LABELS.get(value, value)
    else:
        text = value
        if unit == "%":
            text = f"{text}%"
        elif unit:
            text = f"{text} {unit}"
        elif currency:
            text = f"{text} {currency}"
    label = EPISTEMIC_LABELS.get(qualifier)
    return f"{text} {label}" if label else text


def expected_qualifier(record):
    """La qualifica DOVUTA a un record `ASS-*`."""
    klass = record.get("evidence_classification")
    if klass in ("founder_assumption", "model_estimate",
                 "missing_information"):
        return str(klass)
    if klass in EVIDENTIAL_CLASSES and \
            record.get("validation_status") == "validated":
        return "none"
    return "unvalidated"


def render_template(template_id, refs, rendered):
    """Il modello costante con i propri slot riempiti dai letterali legati,
    in ordine. `None` se gli slot non corrispondono ai legami."""
    template = TEMPLATES.get(template_id)
    if template is None:
        return None
    queue = list(refs)
    out = []
    position = 0
    for match in SLOT_RE.finditer(template):
        out.append(template[position:match.start()])
        if match.group(2):
            if not queue:
                return None
            out.append(", ".join(rendered.get(ref, "\0") for ref in queue))
            queue = []
        else:
            if not queue:
                return None
            out.append(rendered.get(queue.pop(0), "\0"))
        position = match.end()
    out.append(template[position:])
    if queue:
        return None
    return "".join(out)


def slot_count(template_id):
    return len(SLOT_RE.findall(TEMPLATES.get(template_id, "")))


# --------------------------------------------------------------------------
# COSTRUZIONE del modello strutturato
# --------------------------------------------------------------------------


class Builder:
    """Assembla il canonico dagli ingressi e dalla proposta. Nessun testo
    libero: solo verbatim, modelli costanti e letterali legati."""

    def __init__(self, inputs, proposal):
        self.inputs = inputs
        self.proposal = proposal
        self.bindings = []
        self.by_key = {}
        self.errors = []
        self.docs = inputs.docs
        self.register = inputs.registers.get(ASSUMPTIONS_REL) or []
        self.register_index = {entry.get("id"): position for position, entry
                               in enumerate(self.register)
                               if isinstance(entry.get("id"), str)}
        self.bound_records = []

    # ---- riferimenti e letterali ------------------------------------------

    def unresolved(self, ref, message):
        self.errors.append((CODE_REFERENCE, str(ref), message))

    def leaf(self, rel, *parts):
        try:
            return resolve_path(self.docs[rel], jp(*parts))
        except KeyError:
            return None

    def bind(self, key, rel, parts, unit=None, currency=None):
        if key in self.by_key:
            return self.by_key[key]
        value = lexical(self.leaf(rel, *parts))
        binding_id = f"BND-{len(self.bindings) + 1:03d}"
        self.bindings.append({
            "binding_id": binding_id, "key": key,
            "source": {"file": rel, "json_path": jp(*parts),
                       "record_id": None},
            "value": value, "unit": unit, "currency": currency,
            "qualifier": "none",
            "rendered": format_binding(key, value, unit, currency, "none")})
        self.by_key[key] = binding_id
        return binding_id

    def bind_register(self, ref, context):
        """Un valore del registro UFFICIALE, con l'etichetta epistemica
        dovuta. Un riferimento non canonico o non registrato e' respinto."""
        if not is_form("ASS", ref) or ref not in self.register_index:
            self.unresolved(ref, f"{context}: il riferimento {ref!r} non "
                                 "risolve in un record ASS-* canonico del "
                                 "registro ufficiale")
            return None
        key = f"register.{ref}"
        if key in self.by_key:
            return self.by_key[key]
        position = self.register_index[ref]
        record = self.register[position]
        value = lexical(record.get("value"))
        unit = record.get("unit") if isinstance(record.get("unit"), str) \
            and record.get("unit") else None
        currency = record.get("currency") if isinstance(
            record.get("currency"), str) and record.get("currency") else None
        qualifier = expected_qualifier(record)
        binding_id = f"BND-{len(self.bindings) + 1:03d}"
        self.bindings.append({
            "binding_id": binding_id, "key": key,
            "source": {"file": ASSUMPTIONS_REL,
                       "json_path": jp(position, "value"), "record_id": ref},
            "value": value, "unit": unit, "currency": currency,
            "qualifier": qualifier,
            "rendered": format_binding(key, value, unit, currency,
                                       qualifier)})
        self.by_key[key] = binding_id
        self.bound_records.append(ref)
        return binding_id

    def rendered(self, binding_id):
        for item in self.bindings:
            if item["binding_id"] == binding_id:
                return item["rendered"]
        return "-"

    # ---- blocchi ----------------------------------------------------------

    @staticmethod
    def block(kind, origin, source=None, template_id=None, text=None,
              items=None, table=None, refs=None):
        return {"kind": kind, "origin": origin, "source": source,
                "template_id": template_id, "text": text,
                "items": list(items or []), "table": table,
                "binding_refs": list(refs or [])}

    def paragraph(self, rel, *parts):
        value = self.leaf(rel, *parts)
        if not isinstance(value, str) or not value.strip():
            return None
        return self.block("paragraph", "canonical",
                          {"file": rel, "json_path": jp(*parts)},
                          text=str(value))

    def template(self, template_id, refs=(), kind="paragraph"):
        refs = [ref for ref in refs if ref]
        mapping = {item["binding_id"]: item["rendered"]
                   for item in self.bindings}
        return self.block(kind, "template", template_id=template_id,
                          text=render_template(template_id, refs, mapping),
                          refs=refs)

    def template_list(self, template_id, chunks):
        mapping = {item["binding_id"]: item["rendered"]
                   for item in self.bindings}
        items = [render_template(template_id, chunk, mapping)
                 for chunk in chunks]
        refs = [ref for chunk in chunks for ref in chunk]
        return self.block("list", "template", template_id=template_id,
                          items=items, refs=refs)

    def canonical_list(self, rel, parts, items):
        return self.block("list", "canonical",
                          {"file": rel, "json_path": jp(*parts)},
                          items=[str(item) for item in items])

    def table(self, rel, parts, columns, rows, refs=()):
        cells = [[str(cell) if cell not in (None, "") else "-"
                  for cell in row] for row in rows]
        source = {"file": rel, "json_path": jp(*parts)} if rel else None
        return self.block("table", "canonical" if rel else "template",
                          source, table={"columns": list(columns),
                                         "rows": cells},
                          refs=[ref for ref in refs if ref])

    def notice(self, template_id, refs=()):
        return self.template(template_id, refs, kind="notice")

    def or_empty(self, block, template_id="empty_list"):
        return block if block is not None else self.notice(template_id)

    # ---- capitoli ---------------------------------------------------------

    def build(self):
        chapters = {}
        for chapter_id, builder in (
                ("cap-02", self.ch02), ("cap-03", self.ch03),
                ("cap-04", self.ch04), ("cap-05", self.ch05),
                ("cap-06", self.ch06), ("cap-07", self.ch07),
                ("cap-08", self.ch08), ("cap-09", self.ch09),
                ("cap-10", self.ch10), ("cap-11", self.ch11),
                ("cap-12", self.ch12), ("cap-13", self.ch13),
                ("cap-14", self.ch14), ("cap-15", self.ch15),
                ("cap-16", self.ch16), ("cap-17", self.ch17)):
            chapters[chapter_id] = builder()
        # «Executive summary per ultimo», per costruzione: il capitolo 1
        # riferisce solo legami e selezioni gia' risolti dagli altri sedici.
        chapters["cap-01"] = self.ch01()
        return chapters

    def ch02(self):
        refs = []
        rows = []
        binding = self.bind("project.name", CONFIG_REL, ("project_name",))
        rows.append(["Nome del progetto", self.rendered(binding)])
        refs.append(binding)
        for field, label in (("startup_type", "Tipo di startup"),
                             ("development_stage", "Fase di sviluppo"),
                             ("primary_reader", "Destinatario principale"),
                             ("funding_type",
                              "Forma di finanziamento cercata"),
                             ("time_horizon", "Orizzonte del piano")):
            if isinstance(self.leaf(PROFILE_REL, field), str):
                binding = self.bind(f"profile.{field}", PROFILE_REL, (field,))
                rows.append([label, self.rendered(binding)])
                refs.append(binding)
        profile = [self.table(None, (), ["Voce", "Valore"], rows, refs)]
        readers = self.leaf(PROFILE_REL, "secondary_readers") or []
        chunks = [[self.bind(f"profile.secondary_readers.{position}",
                             PROFILE_REL, ("secondary_readers", position))]
                  for position, item in enumerate(readers)
                  if isinstance(item, str)]
        if chunks:
            profile.append(self.template_list("secondary_reader", chunks))
        notes = self.paragraph(PROFILE_REL, "sector_notes")
        if notes:
            profile.append(notes)
        structure = self.paragraph(f"{S08}/{CANONICAL_NAME}", "team_governance",
                                   "governance", "structure")
        return [("Profilo del progetto", profile),
                ("Forma giuridica e governance",
                 [self.or_empty(structure, "no_structure")])]

    def ch03(self):
        rel = f"{S01}/{CANONICAL_NAME}"
        problem = self.leaf(rel, "problem_statement") or {}
        rows = []
        refs = []
        for field, label in (("type", "Tipo di problema"),
                             ("frequency", "Frequenza"),
                             ("intensity", "Intensità"),
                             ("perceived_vs_demonstrated",
                              "Percepito o dimostrato")):
            if isinstance(problem.get(field), str):
                rows.append([label, problem[field]])
        if problem.get("time_lost_ref") is not None:
            binding = self.bind_register(problem["time_lost_ref"],
                                         f"{S01} time_lost_ref")
            if binding:
                rows.append(["Tempo perso", self.rendered(binding)])
                refs.append(binding)
        intensity = [self.table(rel, ("problem_statement",), ["Voce", "Valore"],
                                rows, refs)] if rows else []
        roles = [item for item in problem.get("affected_roles") or ()
                 if isinstance(item, str)]
        if roles:
            intensity.append(self.template("roles_intro"))
            intensity.append(self.canonical_list(
                rel, ("problem_statement", "affected_roles"), roles))
        alternatives = [item for item in problem.get("alternatives") or ()
                        if isinstance(item, dict)]
        alt_block = self.table(
            rel, ("problem_statement", "alternatives"),
            ["Alternativa", "Perché non basta"],
            [[item.get("name"), item.get("why_insufficient")]
             for item in alternatives]) if alternatives else None
        return [("Il problema",
                 [self.paragraph(rel, "problem_statement", "description")]),
                ("Intensità e frequenza",
                 intensity or [self.notice("empty_list")]),
                ("Alternative attuali", [self.or_empty(alt_block)])]

    def segment_index(self, ref, context):
        segments = self.leaf(f"{S02}/{CANONICAL_NAME}",
                             "customer_segments") or []
        for position, item in enumerate(segments):
            if isinstance(item, dict) and item.get("id") == ref:
                return position
        self.unresolved(ref, f"{context}: il segmento {ref!r} non risolve "
                             f"in {S02}")
        return None

    def segment_binding(self, ref, context):
        if not is_form("SEG", ref):
            self.unresolved(ref, f"{context}: {ref!r} non e' un SEG-* "
                                 "canonico")
            return None
        position = self.segment_index(ref, context)
        if position is None:
            return None
        return self.bind(f"segments.{ref}.name", f"{S02}/{CANONICAL_NAME}",
                         ("customer_segments", position, "name"))

    def ch04(self):
        rel = f"{S02}/{CANONICAL_NAME}"
        segments = [item for item in self.leaf(rel, "customer_segments") or ()
                    if isinstance(item, dict)]
        overview = self.table(
            rel, ("customer_segments",),
            ["Segmento", "Descrizione", "Aderenza al problema",
             "Accessibilità", "Processo di acquisto"],
            [[item.get("name"), item.get("description"),
              item.get("problem_fit"), item.get("accessibility"),
              item.get("buying_process")] for item in segments])
        roles = self.table(
            rel, ("customer_segments",),
            ["Segmento", "Utente", "Acquirente", "Decisore", "Pagante"],
            [[item.get("name"), (item.get("roles") or {}).get("user"),
              (item.get("roles") or {}).get("buyer"),
              (item.get("roles") or {}).get("decision_maker"),
              (item.get("roles") or {}).get("payer")] for item in segments])
        size_rows = []
        size_refs = []
        for item in segments:
            for ref in item.get("size_refs") or ():
                binding = self.bind_register(ref, f"{S02} size_refs")
                if binding:
                    size_rows.append([item.get("name"),
                                      self.rendered(binding)])
                    size_refs.append(binding)
        sizes = self.table(rel, ("customer_segments",), ["Segmento", "Valore"],
                           size_rows, size_refs) if size_rows else None
        beachhead = self.leaf(rel, "beachhead") or {}
        binding = self.segment_binding(beachhead.get("segment_ref"),
                                       f"{S02} beachhead")
        focus = [self.template("beachhead", [binding])] if binding else []
        rows = [[label, beachhead[field]] for field, label in
                (("selection_criteria", "Criterio di selezione"),
                 ("rationale", "Motivazione"))
                if isinstance(beachhead.get(field), str)]
        if rows:
            focus.append(self.table(rel, ("beachhead",), ["Voce", "Valore"],
                                    rows))
        return [("Segmenti di clienti", [overview]),
                ("Ruoli di acquisto", [roles]),
                ("Dimensione dei segmenti", [self.or_empty(sizes)]),
                ("Segmento beachhead", focus or [self.notice("empty_list")])]

    def ch05(self):
        rel = f"{S03}/{CANONICAL_NAME}"
        proposition = self.leaf(rel, "value_proposition") or {}
        binding = self.segment_binding(proposition.get("segment_ref"),
                                       f"{S03} segment_ref")
        rows = [["Job", item] for item in proposition.get("jobs") or ()
                if isinstance(item, str)]
        rows += [["Pain", item] for item in proposition.get("pains") or ()
                 if isinstance(item, str)]
        rows += [["Gain", item] for item in proposition.get("gains") or ()
                 if isinstance(item, str)]
        canvas = self.table(rel, ("value_proposition",), ["Dimensione", "Voce"],
                            rows) if rows else None
        mapping = [item for item in proposition.get("mapping") or ()
                   if isinstance(item, dict)]
        mapped = self.table(
            rel, ("value_proposition", "mapping"),
            ["Problema o beneficio", "Risposta della soluzione"],
            [[item.get("pain") or item.get("gain"),
              item.get("reliever") or item.get("creator")]
             for item in mapping]) if mapping else None
        metric_rows = []
        metric_refs = []
        for item in proposition.get("value_metrics") or ():
            if not isinstance(item, dict):
                continue
            binding_ref = self.bind_register(item.get("ref"),
                                             f"{S03} value_metrics")
            if binding_ref:
                metric_rows.append([item.get("metric"),
                                    self.rendered(binding_ref)])
                metric_refs.append(binding_ref)
        proofs = [item for item in proposition.get("proof_points") or ()
                  if isinstance(item, dict)]
        evidence = []
        if metric_rows:
            evidence.append(self.table(rel, ("value_proposition",),
                                       ["Metrica", "Valore"], metric_rows,
                                       metric_refs))
        if proofs:
            evidence.append(self.table(
                rel, ("value_proposition", "proof_points"),
                ["Affermazione", "Classe di evidenza"],
                [[item.get("claim"), item.get("evidence_classification")]
                 for item in proofs]))
        return [("Segmento servito",
                 [self.template("vp_segment", [binding])] if binding
                 else [self.notice("empty_list")]),
                ("Lavori, problemi e benefici", [self.or_empty(canvas)]),
                ("Mappatura della soluzione", [self.or_empty(mapped)]),
                ("Perché cambiare",
                 [self.paragraph(rel, "value_proposition",
                                 "switching_rationale")]),
                ("Metriche e prove",
                 evidence or [self.notice("empty_list")])]

    def ch06(self):
        rel = f"{S04}/{CANONICAL_NAME}"
        model = self.leaf(rel, "market_model") or {}
        rows = []
        refs = []
        for field, label in (("tam_ref", "TAM"), ("sam_ref", "SAM"),
                             ("som_ref", "SOM")):
            binding = self.bind_register(model.get(field),
                                         f"{S04} market_model.{field}")
            if binding:
                rows.append([label, self.rendered(binding)])
                refs.append(binding)
        for field, label in (("geography", "Area geografica"),
                             ("period", "Periodo")):
            if isinstance(model.get(field), str):
                rows.append([label, model[field]])
        return [("Dimensione del mercato",
                 [self.table(rel, ("market_model",), ["Grandezza", "Valore"],
                             rows, refs)])]

    def ch07(self):
        rel = f"{S04}/{CANONICAL_NAME}"
        categories = self.leaf(rel, "competitive_landscape",
                               "categories") or {}
        rows = []
        for key, label in COMPETITION_CATEGORIES:
            entry = categories.get(key)
            if not isinstance(entry, dict):
                self.errors.append((CODE_INPUT_INVALID, f"{S04}:{key}",
                                    f"{S04}: la categoria di concorrenza "
                                    f"{key!r} non e' valutata"))
                continue
            competitors = [item for item in entry.get("competitors") or ()
                           if isinstance(item, dict)]
            if competitors:
                for item in competitors:
                    rows.append([label, item.get("name"),
                                 item.get("assessment"), "-"])
            else:
                rows.append([label, "nessuno identificato",
                             entry.get("rationale"),
                             entry.get("research_notes")])
        return [("Categorie di concorrenza",
                 [self.table(rel, ("competitive_landscape", "categories"),
                             ["Categoria", "Concorrente", "Valutazione",
                              "Note di ricerca"], rows)])]

    def ch08(self):
        rel = f"{S05}/{CANONICAL_NAME}"
        model = self.leaf(rel, "business_model") or {}
        rows = []
        refs = []
        for field, label in (("pricing_ref", "Prezzo"),
                             ("revenue_ref", "Ricavi"),
                             ("contribution_margin_ref",
                              "Margine di contribuzione")):
            if model.get(field) is None:
                continue
            binding = self.bind_register(model[field],
                                         f"{S05} business_model.{field}")
            if binding:
                rows.append([label, self.rendered(binding)])
                refs.append(binding)
        for field, label in (("recurrence", "Ricorrenza"),
                             ("channel", "Canale")):
            if isinstance(model.get(field), str):
                rows.append([label, model[field]])
        return [("Prezzo, ricavi e margine",
                 [self.table(rel, ("business_model",), ["Voce", "Valore"],
                             rows, refs)])]

    def ch09(self):
        rel = f"{S06}/{CANONICAL_NAME}"
        funnel = self.leaf(rel, "sales_funnel") or {}
        rows = []
        refs = []

        def add(label, ref, context):
            if ref is None:
                return
            binding = self.bind_register(ref, context)
            if binding:
                rows.append([label, self.rendered(binding)])
                refs.append(binding)
        add("Contatti generati", funnel.get("leads_ref"), f"{S06} leads_ref")
        for item in funnel.get("stages") or ():
            if isinstance(item, dict):
                add(item.get("name"), item.get("rate_ref"),
                    f"{S06} stages.rate_ref")
        for field, label in (("customers_out_ref", "Clienti acquisiti"),
                             ("spend_ref", "Spesa commerciale"),
                             ("cac_ref", "Costo di acquisizione"),
                             ("churn_ref", "Tasso di abbandono"),
                             ("capacity_revenue_ref", "Capacità di ricavo"),
                             ("pricing_ref", "Prezzo")):
            add(label, funnel.get(field), f"{S06} {field}")
        block = self.table(rel, ("sales_funnel",), ["Voce", "Valore"], rows,
                           refs) if rows else None
        return [("Funnel commerciale", [self.or_empty(block)])]

    def ch10(self):
        rel = f"{S07}/{CANONICAL_NAME}"
        model = self.leaf(rel, "operations_model") or {}
        processes = [item for item in model.get("core_processes") or ()
                     if isinstance(item, dict)]
        core = self.table(
            rel, ("operations_model", "core_processes"),
            ["Processo", "Modalità", "Responsabile indicativo",
             "Collo di bottiglia"],
            [[item.get("name"), item.get("make_buy_partner"),
              item.get("owner_hint"),
              "sì" if item.get("bottleneck") is True else "no"]
             for item in processes]) if processes else None
        rows = []
        refs = []
        if model.get("capacity_ref") is not None:
            binding = self.bind_register(model["capacity_ref"],
                                         f"{S07} capacity_ref")
            if binding:
                rows.append(["Capacità operativa", self.rendered(binding)])
                refs.append(binding)
        for ref in model.get("unit_ops_cost_refs") or ():
            binding = self.bind_register(ref, f"{S07} unit_ops_cost_refs")
            if binding:
                rows.append(["Costo operativo unitario",
                             self.rendered(binding)])
                refs.append(binding)
        capacity = self.table(rel, ("operations_model",), ["Voce", "Valore"],
                              rows, refs) if rows else None
        dependencies = [item for item in model.get("critical_dependencies")
                        or () if isinstance(item, dict)]
        dep_block = self.table(
            rel, ("operations_model", "critical_dependencies"),
            ["Dipendenza", "Categoria", "Fornitore unico", "Mitigazione"],
            [[item.get("name"), item.get("category"),
              "sì" if item.get("single_source") is True else
              ("no" if item.get("single_source") is False else "-"),
              item.get("mitigation") or item.get("rationale")]
             for item in dependencies]) if dependencies else None
        requirements = [item for item in model.get("regulatory_requirements")
                        or () if isinstance(item, dict)]
        req_block = self.table(
            rel, ("operations_model", "regulatory_requirements"),
            ["Requisito", "Valutazione"],
            [[item.get("requirement"),
              item.get("assessment") or item.get("rationale")]
             for item in requirements]) if requirements else None
        return [("Processi core", [self.or_empty(core)]),
                ("Capacità e costi operativi", [self.or_empty(capacity)]),
                ("Dipendenze critiche", [self.or_empty(dep_block)]),
                ("Requisiti normativi", [self.or_empty(req_block)])]

    def ch11(self):
        rel = f"{S07}/{CANONICAL_NAME}"
        strategy = self.leaf(rel, "operations_model", "ip_strategy") or {}
        assets = [item for item in strategy.get("assets") or ()
                  if isinstance(item, dict)]
        asset_block = self.table(
            rel, ("operations_model", "ip_strategy", "assets"),
            ["Asset", "Protezione", "Motivazione"],
            [[item.get("name"), item.get("protection"), item.get("rationale")]
             for item in assets]) if assets else None
        know_how = self.paragraph(rel, "operations_model", "ip_strategy",
                                  "know_how_protection")
        return [("Asset di proprietà intellettuale",
                 [self.or_empty(asset_block, "no_ip_assets")]),
                ("Protezione del know-how",
                 [self.or_empty(know_how, "no_know_how")])]

    def role_label(self, ref, context):
        roles = self.leaf(f"{S08}/{CANONICAL_NAME}", "team_governance",
                          "roles") or []
        for item in roles:
            if isinstance(item, dict) and item.get("id") == ref:
                return item.get("person") or item.get("open_position")
        self.unresolved(ref, f"{context}: il ruolo {ref!r} non risolve in "
                             f"{S08}")
        return None

    def ch12(self):
        rel = f"{S08}/{CANONICAL_NAME}"
        team = self.leaf(rel, "team_governance") or {}
        roles = [item for item in team.get("roles") or ()
                 if isinstance(item, dict)]
        rows = []
        fte_rows = []
        fte_refs = []
        for item in roles:
            label = item.get("person") or item.get("open_position")
            state = "in organico" if item.get("person") else \
                "posizione aperta"
            for responsibility in item.get("responsibilities") or ():
                rows.append([label, state, responsibility])
            if item.get("fte_ref") is not None:
                binding = self.bind_register(item["fte_ref"],
                                             f"{S08} fte_ref")
                if binding:
                    fte_rows.append([label, self.rendered(binding)])
                    fte_refs.append(binding)
        people = []
        if rows:
            people.append(self.table(rel, ("team_governance", "roles"),
                                     ["Ruolo", "Stato", "Responsabilità"],
                                     rows))
        if fte_rows:
            people.append(self.table(rel, ("team_governance", "roles"),
                                     ["Ruolo", "Impegno"], fte_rows, fte_refs))
        gaps = [item for item in team.get("capability_gaps") or ()
                if isinstance(item, dict)]
        gap_block = self.table(
            rel, ("team_governance", "capability_gaps"),
            ["Lacuna", "Risposta", "Note"],
            [[item.get("gap"), item.get("addressed_by"), item.get("notes")]
             for item in gaps]) if gaps else None
        hiring_rows = []
        hiring_refs = []
        for item in team.get("hiring_plan") or ():
            if not isinstance(item, dict):
                continue
            label = self.role_label(item.get("role_ref"),
                                    f"{S08} hiring_plan")
            binding = self.bind_register(item.get("cost_driver_ref"),
                                         f"{S08} hiring_plan") \
                if item.get("cost_driver_ref") is not None else None
            hiring_rows.append([label, item.get("period"),
                                self.rendered(binding) if binding else "-"])
            if binding:
                hiring_refs.append(binding)
        hiring = self.table(rel, ("team_governance",),
                            ["Ruolo", "Periodo", "Costo"], hiring_rows,
                            hiring_refs) if hiring_rows else None
        rights = [[item.get("area"),
                   self.role_label(item.get("owner_ref"),
                                   f"{S08} decision_rights")]
                  for item in team.get("decision_rights") or ()
                  if isinstance(item, dict)]
        right_block = self.table(rel, ("team_governance",),
                                 ["Area", "Titolare"], rights) \
            if rights else None
        governance = team.get("governance") or {}
        gov_rows = [[label, governance[field]] for field, label in
                    (("structure", "Struttura"), ("vesting", "Vesting"),
                     ("incentives", "Incentivi"))
                    if isinstance(governance.get(field), str)]
        gov_blocks = []
        if gov_rows:
            gov_blocks.append(self.table(rel, ("team_governance",
                                               "governance"),
                                         ["Voce", "Valore"], gov_rows))
        equity = [item for item in governance.get("equity_split") or ()
                  if isinstance(item, dict)]
        if equity:
            gov_blocks.append(self.table(
                rel, ("team_governance", "governance", "equity_split"),
                ["Socio", "Quota"],
                [[item.get("holder"), lexical(item.get("share"))]
                 for item in equity]))
        advisors = [item for item in team.get("advisors") or ()
                    if isinstance(item, dict)]
        advisor_block = self.table(
            rel, ("team_governance", "advisors"), ["Advisor", "Area"],
            [[item.get("name"), item.get("area")] for item in advisors]) \
            if advisors else None
        return [("Ruoli e responsabilità",
                 people or [self.notice("empty_list")]),
                ("Lacune di competenza", [self.or_empty(gap_block)]),
                ("Piano delle assunzioni", [self.or_empty(hiring)]),
                ("Diritti decisionali", [self.or_empty(right_block)]),
                ("Governance societaria",
                 gov_blocks or [self.notice("empty_list")]),
                ("Advisor", [self.or_empty(advisor_block)])]

    # ---- roadmap ------------------------------------------------------------

    def milestones(self):
        return [item for item in self.leaf(f"{S09}/{CANONICAL_NAME}",
                                           "milestone_plan", "milestones")
                or () if isinstance(item, dict)]

    def milestone_position(self, ref):
        for position, item in enumerate(self.milestones()):
            if item.get("id") == ref:
                return position
        return None

    def financing(self):
        return [item for item in self.leaf(f"{S11}/{CANONICAL_NAME}",
                                           "funding_request",
                                           "milestone_financing") or ()
                if isinstance(item, dict)]

    def coverage_cell(self, ref):
        """La copertura della richiesta per una milestone: il
        `coverage_status` dello Stage 11 legato, o la costante «non coperta
        dalla richiesta» (`XS-07`)."""
        for position, item in enumerate(self.financing()):
            if item.get("milestone_ref") == ref:
                binding = self.bind(
                    f"funding.milestone.{ref}.coverage_status",
                    f"{S11}/{CANONICAL_NAME}",
                    ("funding_request", "milestone_financing", position,
                     "coverage_status"))
                return self.rendered(binding), binding
        return "non coperta dalla richiesta", None

    def ch13(self):
        rel = f"{S09}/{CANONICAL_NAME}"
        milestones = self.milestones()
        titles = {item.get("id"): item.get("title") for item in milestones}
        for item in self.financing():
            ref = item.get("milestone_ref")
            if not is_form("MIL", ref) or ref not in titles:
                self.unresolved(ref, f"{S11} milestone_financing: la "
                                     f"milestone {ref!r} non esiste nella "
                                     f"roadmap {S09} (XS-07)")
        rows = []
        refs = []
        dependency_rows = []
        criteria_rows = []
        rule_rows = []
        for position, item in enumerate(milestones):
            ref = item.get("id")
            if not is_form("MIL", ref):
                self.unresolved(ref, f"{S09}: {ref!r} non e' un MIL-* "
                                     "canonico")
            self.role_label(item.get("owner_ref"), f"{S09} owner_ref")
            cost = self.bind_register(item.get("cost_ref"),
                                      f"{S09} cost_ref") \
                if item.get("cost_ref") is not None else None
            coverage, coverage_ref = self.coverage_cell(ref)
            rows.append([item.get("title"), item.get("category"),
                         item.get("start_date"), item.get("target_date"),
                         self.rendered(cost) if cost else "-", coverage])
            refs += [cost, coverage_ref]
            for dependency in item.get("depends_on") or ():
                if dependency not in titles:
                    self.unresolved(dependency, f"{S09} depends_on di {ref}")
                dependency_rows.append([item.get("title"),
                                        titles.get(dependency)])
            for criterion in item.get("success_criteria") or ():
                criteria_rows.append([item.get("title"), criterion])
            rule_rows.append([item.get("title"), item.get("go_no_go_rule"),
                              item.get("exit_criteria")])
            for risk in item.get("risk_refs") or ():
                self.risk_position(risk, f"{S09} risk_refs di {ref}")
        overview = self.table(
            rel, ("milestone_plan", "milestones"),
            ["Milestone", "Categoria", "Inizio", "Obiettivo", "Costo",
             "Copertura della richiesta"], rows, refs)
        dependencies = self.table(rel, ("milestone_plan", "milestones"),
                                  ["Milestone", "Dipende da"],
                                  dependency_rows) if dependency_rows \
            else None
        criteria = [self.table(rel, ("milestone_plan", "milestones"),
                               ["Milestone", "Criterio di successo"],
                               criteria_rows)] if criteria_rows else []
        criteria.append(self.table(rel, ("milestone_plan", "milestones"),
                                   ["Milestone", "Regola go/no-go",
                                    "Criterio di uscita"], rule_rows))
        financing = self.financing()
        fr = f"{S11}/{CANONICAL_NAME}"
        if financing:
            currency = self.leaf(fr, "funding_request", "requested_capital",
                                 "currency")
            fin_rows = []
            fin_refs = []
            for position, item in enumerate(financing):
                ref = item.get("milestone_ref")
                index = self.milestone_position(ref)
                title = self.bind(f"roadmap.{ref}.title", rel,
                                  ("milestone_plan", "milestones", index,
                                   "title")) if index is not None else None
                amount = self.bind(
                    f"funding.milestone.{ref}.amount", fr,
                    ("funding_request", "milestone_financing", position,
                     "amount"), currency=lexical(currency))
                fin_rows.append([
                    self.rendered(title) if title else ref,
                    item.get("target_date"), self.rendered(amount),
                    item.get("coverage_status"), item.get("financed_by"),
                    "sì" if item.get("out_of_horizon") is True else "no"])
                fin_refs += [title, amount]
            coverage_blocks = [self.table(
                fr, ("funding_request", "milestone_financing"),
                ["Milestone", "Data obiettivo", "Importo", "Copertura",
                 "Finanziata da", "Fuori orizzonte"], fin_rows, fin_refs)]
        else:
            coverage_blocks = [self.notice("no_financing")]
        summary = self.leaf(fr, "funding_request",
                            "milestone_financing_summary")
        if isinstance(summary, dict):
            coverage_blocks.append(self.template("financing_summary", [
                self.bind("funding.milestone_financing_summary."
                          "unmapped_residual", fr,
                          ("funding_request", "milestone_financing_summary",
                           "unmapped_residual")),
                self.bind("funding.milestone_financing_summary."
                          "out_of_horizon_count", fr,
                          ("funding_request", "milestone_financing_summary",
                           "out_of_horizon_count"))]))
        return [("Milestone", [overview]),
                ("Dipendenze fra milestone", [self.or_empty(dependencies)]),
                ("Criteri di successo e di uscita", criteria),
                ("Copertura finanziaria delle milestone", coverage_blocks)]

    # ---- rischi -------------------------------------------------------------

    def risk_position(self, ref, context):
        risks = self.inputs.registers.get(RISK_REL) or []
        if is_form("RISK", ref):
            for position, item in enumerate(risks):
                if item.get("id") == ref:
                    return position
        self.unresolved(ref, f"{context}: il rischio {ref!r} non risolve in "
                             f"{RISK_REL}")
        return None

    def ch14(self):
        risks = self.inputs.registers.get(RISK_REL) or []
        references = []
        ops = self.leaf(f"{S07}/{CANONICAL_NAME}", "operations_model") or {}
        for ref in ops.get("risk_refs") or ():
            references.append((ref, "Operations e IP", None))
        team = self.leaf(f"{S08}/{CANONICAL_NAME}", "team_governance") or {}
        for ref in team.get("risk_refs") or ():
            references.append((ref, "Team e governance", None))
        for position, item in enumerate(self.milestones()):
            for ref in item.get("risk_refs") or ():
                references.append((ref, "Roadmap", position))
        if not risks and not references:
            return "not_applicable", [("Registro dei rischi", [
                self.notice("risks_not_applicable")])]
        rows = [[item.get("risk"), item.get("category"),
                 item.get("probability"), item.get("impact"),
                 item.get("severity"), item.get("mitigation"),
                 item.get("contingency"), item.get("early_warning_indicator"),
                 item.get("status")] for item in risks]
        register = self.table(
            RISK_REL, (), ["Rischio", "Categoria", "Probabilità", "Impatto",
                           "Severità", "Mitigazione", "Piano di contingenza",
                           "Segnale di allerta", "Stato"], rows) \
            if rows else None
        ref_rows = []
        ref_refs = []
        for ref, origin, milestone in references:
            position = self.risk_position(ref, f"risk_refs ({origin})")
            if position is None:
                continue
            text = self.bind(f"risks.{ref}.risk", RISK_REL,
                             (position, "risk"))
            title = self.bind(f"roadmap.{self.milestones()[milestone]['id']}"
                              ".title", f"{S09}/{CANONICAL_NAME}",
                              ("milestone_plan", "milestones", milestone,
                               "title")) if milestone is not None else None
            ref_rows.append([self.rendered(text), origin,
                             self.rendered(title) if title else "-"])
            ref_refs += [text, title]
        recalled = self.table(None, (), ["Rischio", "Richiamato da",
                                         "Milestone"], ref_rows, ref_refs) \
            if ref_rows else None
        return "rendered", [
            ("Registro dei rischi", [self.or_empty(register)]),
            ("Rischi richiamati dagli stage", [self.or_empty(recalled)])]

    # ---- piano finanziario ----------------------------------------------------

    def periods(self):
        calendar = self.leaf(f"{S10}/{CANONICAL_NAME}", "financial_plan",
                             "results", "calendar") or {}
        return {str(item.get("index")) for item in calendar.get("periods")
                or () if isinstance(item, dict)}

    def per_period(self, key, periods):
        """Una metrica PER PERIODO (`<radice>_<indice di periodo>`) e' una
        serie: resta nel capitolo e nel workbook dello Stage 10, rinviati e
        mai copiati."""
        head, _, tail = str(key).rpartition("_")
        return bool(head) and tail in periods

    def fin_bind(self, suffix, *parts):
        return self.bind(f"financial.{suffix}", f"{S10}/{CANONICAL_NAME}",
                         ("financial_plan",) + parts)

    def ch15(self):
        rel = f"{S10}/{CANONICAL_NAME}"
        results = ("financial_plan", "results")
        calendar_rows = []
        calendar_refs = []
        for field, label in (("anchor_date", "Data di ancoraggio"),
                             ("frequency", "Frequenza"),
                             ("horizon_periods", "Periodi dell'orizzonte")):
            if self.leaf(rel, *results, "calendar", field) is not None:
                binding = self.fin_bind(f"calendar.{field}", "results",
                                        "calendar", field)
                calendar_rows.append([label, self.rendered(binding)])
                calendar_refs.append(binding)
        calendar = self.table(rel, results + ("calendar",), ["Voce", "Valore"],
                              calendar_rows, calendar_refs)
        periods = self.periods()
        modules = self.leaf(rel, *results, "modules") or {}
        metric_rows = []
        metric_refs = []
        status_rows = []
        status_refs = []
        for name in FIN_MODULES:
            module = modules.get(name)
            if not isinstance(module, dict):
                continue
            metrics = module.get("metrics")
            if isinstance(metrics, dict):
                for key in sorted(metrics):
                    if self.per_period(key, periods) or \
                            isinstance(metrics[key], (dict, list)):
                        continue
                    binding = self.fin_bind(f"{name}.{key}", "results",
                                            "modules", name, "metrics", key)
                    metric_rows.append([name, key, self.rendered(binding)])
                    metric_refs.append(binding)
            if module.get("status") is not None:
                binding = self.fin_bind(f"{name}.status", "results",
                                        "modules", name, "status")
                status_rows.append([name, self.rendered(binding),
                                    module.get("not_applicable_reason")])
                status_refs.append(binding)
        metrics_block = self.table(rel, results + ("modules",),
                                   ["Modulo", "Metrica", "Valore"],
                                   metric_rows, metric_refs) \
            if metric_rows else None
        status_block = self.table(rel, results + ("modules",),
                                  ["Modulo", "Stato", "Motivazione"],
                                  status_rows, status_refs)
        scenarios = self.leaf(rel, *results, "scenarios") or {}
        coverage = scenarios.get("coverage") or {}
        scenario_rows = []
        scenario_refs = []
        for field, label in (("level", "livello"), ("ratio", "rapporto")):
            if coverage.get(field) is not None:
                binding = self.fin_bind(f"scenarios.coverage.{field}",
                                        "results", "scenarios", "coverage",
                                        field)
                scenario_rows.append(["copertura", label,
                                      self.rendered(binding)])
                scenario_refs.append(binding)
        for name in SCENARIOS:
            entry = scenarios.get(name)
            if not isinstance(entry, dict):
                continue
            if entry.get("status") is not None:
                binding = self.fin_bind(f"scenarios.{name}.status", "results",
                                        "scenarios", name, "status")
                scenario_rows.append([name, "stato", self.rendered(binding)])
                scenario_refs.append(binding)
            if isinstance(entry.get("not_applicable_reason"), str):
                scenario_rows.append([name, "motivazione",
                                      entry["not_applicable_reason"]])
            summary = entry.get("summary")
            if isinstance(summary, dict):
                for key in sorted(summary):
                    if isinstance(summary[key], (dict, list)):
                        continue
                    binding = self.fin_bind(f"scenarios.{name}.summary.{key}",
                                            "results", "scenarios", name,
                                            "summary", key)
                    scenario_rows.append([name, key, self.rendered(binding)])
                    scenario_refs.append(binding)
        scenario_blocks = [self.table(rel, results + ("scenarios",),
                                      ["Scenario", "Voce", "Valore"],
                                      scenario_rows, scenario_refs)] \
            if scenario_rows else [self.notice("empty_list")]
        uncovered = [item for item in coverage.get("uncovered_driver_refs")
                     or () if isinstance(item, str)]
        if uncovered:
            scenario_blocks.append(self.notice("uncovered_intro"))
            scenario_blocks.append(self.canonical_list(
                rel, results + ("scenarios", "coverage",
                                "uncovered_driver_refs"), uncovered))
        validation = [self.template("fin_validation", [
            self.fin_bind("validation.result", "validation", "result"),
            self.fin_bind("validation.propagated_status", "validation",
                          "propagated_status"),
            self.fin_bind("validation.investor_readiness.status",
                          "validation", "investor_readiness", "status")])]
        reasons = [item.get("message") for item in self.leaf(
            rel, "financial_plan", "validation", "investor_readiness",
            "blocking_reasons") or () if isinstance(item, dict) and
            isinstance(item.get("message"), str)]
        if reasons:
            validation.append(self.notice("blocking_intro"))
            validation.append(self.canonical_list(
                rel, ("financial_plan", "validation", "investor_readiness",
                      "blocking_reasons"), reasons))
        warnings = [item.get("code") for item in self.leaf(
            rel, "financial_plan", "validation", "warnings") or ()
            if isinstance(item, dict) and isinstance(item.get("code"), str)]
        if warnings:
            validation.append(self.canonical_list(
                rel, ("financial_plan", "validation", "warnings"), warnings))
        documents = self.inputs.indexed()
        detail_rows = [[documents[path].get("title"), path,
                        documents[path].get("document_id"),
                        documents[path].get("version")]
                       for path in (f"{S10}/{name}" for name in DERIVED[S10])
                       if path in documents]
        detail = self.table(f"{S12}/{CANONICAL_NAME}",
                            ("data_room", "documents"),
                            ["Documento", "Percorso", "Riferimento data room",
                             "Versione"], detail_rows) if detail_rows \
            else None
        return [("Calendario del piano", [calendar]),
                ("Metriche principali", [self.or_empty(metrics_block)]),
                ("Stato dei moduli", [status_block]),
                ("Scenari", scenario_blocks),
                ("Validazione e prontezza", validation),
                ("Documenti di dettaglio", [self.or_empty(detail)])]

    # ---- funding request -----------------------------------------------------

    def fr_bind(self, suffix, *parts, unit=None, currency=None):
        return self.bind(f"funding.{suffix}", f"{S11}/{CANONICAL_NAME}",
                         ("funding_request",) + parts, unit=unit,
                         currency=currency)

    def currency(self):
        return lexical(self.leaf(f"{S11}/{CANONICAL_NAME}", "funding_request",
                                 "requested_capital", "currency"))

    def ch16(self):
        rel = f"{S11}/{CANONICAL_NAME}"
        request = self.leaf(rel, "funding_request") or {}
        currency = self.currency()
        capital_rows = []
        capital_refs = []
        amount = self.fr_bind("requested_capital.amount", "requested_capital",
                              "amount", currency=currency)
        capital_rows.append(["Capitale richiesto", self.rendered(amount)])
        capital_refs.append(amount)
        if (request.get("capital_requirement") or {}).get(
                "modeled_need_amount") is not None:
            need = self.fr_bind("capital_requirement.modeled_need_amount",
                                "capital_requirement", "modeled_need_amount",
                                currency=currency)
            capital_rows.append(["Fabbisogno modellato", self.rendered(need)])
            capital_refs.append(need)
        requested = request.get("requested_capital") or {}
        for field, label in (("rounding_applied", "Arrotondamento applicato"),
                             ("policy_ref", "Politica di determinazione")):
            if isinstance(requested.get(field), str):
                capital_rows.append([label, requested[field]])
        capital = self.table(rel, ("funding_request",), ["Voce", "Valore"],
                             capital_rows, capital_refs)
        proceeds_rows = []
        proceeds_refs = []
        for position, item in enumerate(request.get("use_of_proceeds") or ()):
            if not isinstance(item, dict):
                continue
            money = self.fr_bind(f"use_of_proceeds.{position}.amount",
                                 "use_of_proceeds", position, "amount",
                                 currency=currency)
            share = self.fr_bind(f"use_of_proceeds.{position}.percentage",
                                 "use_of_proceeds", position, "percentage",
                                 unit="%")
            proceeds_rows.append([item.get("label"), self.rendered(money),
                                  self.rendered(share)])
            proceeds_refs += [money, share]
        proceeds = self.table(rel, ("funding_request", "use_of_proceeds"),
                              ["Categoria", "Importo", "Percentuale"],
                              proceeds_rows, proceeds_refs) \
            if proceeds_rows else None
        runway = request.get("runway") or {}
        sufficiency = request.get("sufficiency") or {}
        runway_rows = []
        runway_refs = []

        def add(label, binding):
            runway_rows.append([label, self.rendered(binding)])
            runway_refs.append(binding)
        for field, label in (
                ("runway_to_zero",
                 "Runway prima del finanziamento, misura a cassa zero"),
                ("runway_to_buffer",
                 "Runway prima del finanziamento, misura a buffer")):
            if (runway.get("before_financing") or {}).get(field) is not None:
                add(label, self.fr_bind(f"runway.before_financing.{field}",
                                        "runway", "before_financing", field,
                                        unit="periodi"))
        if isinstance(runway.get("measure"), str):
            runway_rows.append(["Misura di riferimento", runway["measure"]])
        if (runway.get("after_financing") or {}).get("periods") is not None:
            add("Runway dopo il finanziamento",
                self.fr_bind("runway.after_financing.periods", "runway",
                             "after_financing", "periods", unit="periodi"))
        if sufficiency.get("funded_horizon") is not None:
            add("Orizzonte finanziato",
                self.fr_bind("sufficiency.funded_horizon", "sufficiency",
                             "funded_horizon", unit="periodi"))
        if sufficiency.get("residual_gap") is not None:
            add("Gap residuo",
                self.fr_bind("sufficiency.residual_gap", "sufficiency",
                             "residual_gap", currency=currency))
        if isinstance(sufficiency.get("basis"), str):
            runway_rows.append(["Base della sufficienza",
                                sufficiency["basis"]])
        runway_block = self.table(rel, ("funding_request",),
                                  ["Voce", "Valore"], runway_rows,
                                  runway_refs)
        tranches = [item for item in request.get("tranches") or ()
                    if isinstance(item, dict)]
        tranche_blocks = []
        if tranches:
            tranche_blocks.append(self.table(
                rel, ("funding_request", "tranches"),
                ["Tranche", "Supporto", "Motivazione"],
                [[item.get("tranche_id"), item.get("support"),
                  item.get("reason")] for item in tranches]))
        requirement = request.get("investment_requirement") or {}
        req_rows = [[label, requirement[field]] for field, label in
                    (("status", "Stato"), ("reason", "Motivazione"))
                    if isinstance(requirement.get(field), str)]
        if req_rows:
            tranche_blocks.append(self.table(
                rel, ("funding_request", "investment_requirement"),
                ["Voce", "Valore"], req_rows))
        sections = [item for item in (request.get("narrative") or {}).get(
            "sections") or () if isinstance(item, dict)]
        narrative = self.table(rel, ("funding_request", "narrative",
                                     "sections"), ["Sezione", "Testo"],
                               [[item.get("title"), item.get("body")]
                                for item in sections]) if sections else None
        governance = [self.template("fr_governance", [
            self.fr_bind("governance.propagated_state", "governance",
                         "propagated_state"),
            self.fr_bind("governance.source_validation_result", "governance",
                         "source_validation_result"),
            self.fr_bind("governance.source_investor_readiness",
                         "governance", "source_investor_readiness")])]
        decisions = [item for item in (request.get(
            "dependencies_and_assumptions") or {}).get("decision_needed") or ()
            if isinstance(item, dict)]
        if decisions:
            governance.append(self.table(
                rel, ("funding_request", "dependencies_and_assumptions",
                      "decision_needed"),
                ["Decisione", "Domanda", "Bloccante"],
                [[item.get("code"), item.get("question"),
                  "sì" if item.get("blocking") is True else "no"]
                 for item in decisions]))
        unresolved = [item for item in request.get(
            "unresolved_validation_items") or () if isinstance(item, dict)]
        if unresolved:
            governance.append(self.table(
                rel, ("funding_request", "unresolved_validation_items"),
                ["Gravità", "Codice", "Messaggio"],
                [[item.get("severity"), item.get("code"), item.get("message")]
                 for item in unresolved]))
        return [("Capitale richiesto", [capital]),
                ("Impiego dei fondi", [self.or_empty(proceeds)]),
                ("Runway e sufficienza", [runway_block]),
                ("Tranche e requisito d'investimento",
                 tranche_blocks or [self.notice("empty_list")]),
                ("Narrativa della richiesta", [self.or_empty(narrative)]),
                ("Stato di governance e decisioni aperte", governance)]

    # ---- appendice ------------------------------------------------------------

    def claims(self):
        return [item for item in self.inputs.room().get("claims") or ()
                if isinstance(item, dict)]

    def dr_bind(self, suffix, *parts, unit=None):
        return self.bind(f"dataroom.{suffix}", f"{S12}/{CANONICAL_NAME}",
                         ("data_room",) + parts, unit=unit)

    def coverage_refs(self):
        completeness = self.inputs.room().get("completeness") or {}
        if str(completeness.get("claims_total")) in ("0", "None"):
            return None
        return [self.dr_bind("completeness.coverage_percent", "completeness",
                             "coverage_percent", unit="%"),
                self.dr_bind("completeness.claims_supported", "completeness",
                             "claims_supported"),
                self.dr_bind("completeness.claims_total", "completeness",
                             "claims_total")]

    def ch17(self):
        room = self.inputs.room()
        rel = f"{S12}/{CANONICAL_NAME}"
        documents = {item.get("document_id"): item for item in
                     room.get("documents") or () if isinstance(item, dict)}
        index_rows = []
        for section in room.get("sections") or ():
            if not isinstance(section, dict):
                continue
            ids = section.get("document_ids") or []
            if not ids:
                index_rows.append([section.get("title"), "-", "-", "-", "-"])
            for ref in ids:
                item = documents.get(ref) or {}
                index_rows.append([section.get("title"), item.get("title"),
                                   item.get("path"), item.get("availability"),
                                   item.get("version")])
        index = [self.notice("index_intro"),
                 self.table(rel, ("data_room",),
                            ["Sezione", "Documento", "Percorso",
                             "Disponibilità", "Versione"], index_rows)]
        claims = self.claims()
        coverage = self.coverage_refs()
        register = [self.template("coverage", coverage) if coverage
                    else self.notice("es_no_claims")]
        chapter_titles = CHAPTER_TITLES
        claim_rows = [[item.get("claim_id"), item.get("statement"),
                       chapter_titles[CLAIM_CHAPTERS.get(
                           item.get("related_section"), ("cap-17",))[0]],
                       item.get("support_status")] for item in claims]
        if claim_rows:
            register.append(self.table(rel, ("data_room", "claims"),
                                       ["Claim", "Enunciato", "Capitolo",
                                        "Supporto"], claim_rows))
        register_status = {item.get("evidence_ref"): item.get(
            "register_status") for item in room.get("evidence_index") or ()
            if isinstance(item, dict)}
        evidence = self.inputs.registers.get(EVIDENCE_REL) or []
        known = {item.get("id") for item in evidence}
        link_rows = []
        for item in claims:
            for link in item.get("evidence_links") or ():
                if not isinstance(link, dict):
                    continue
                ref = link.get("evidence_ref")
                if ref is not None and (not is_form("EVD", ref) or
                                        ref not in known):
                    self.unresolved(ref, f"{item.get('claim_id')}: "
                                         f"l'evidenza {ref!r} non risolve in "
                                         f"{EVIDENCE_REL}")
                link_rows.append([item.get("claim_id"), ref,
                                  link.get("evidence_class"),
                                  link.get("status"),
                                  register_status.get(ref)])
        if link_rows:
            register.append(self.table(rel, ("data_room",),
                                       ["Claim", "Evidenza", "Classe",
                                        "Legame", "Stato nel registro"],
                                       link_rows))
        assumption_rows = []
        assumption_refs = []
        for ref in sorted(set(self.bound_records), key=id_number):
            record = self.register[self.register_index[ref]]
            binding = self.by_key[f"register.{ref}"]
            assumption_rows.append([
                ref, record.get("variable"), record.get("statement"),
                self.rendered(binding), record.get("evidence_classification"),
                record.get("validation_status")])
            assumption_refs.append(binding)
        assumptions = self.table(ASSUMPTIONS_REL, (),
                                 ["Assunzione", "Variabile", "Enunciato",
                                  "Valore", "Classe di evidenza",
                                  "Stato di validazione"], assumption_rows,
                                 assumption_refs) if assumption_rows else None
        cited = {link.get("evidence_ref") for item in claims
                 for link in item.get("evidence_links") or ()
                 if isinstance(link, dict)}
        sources = self.inputs.registers.get(SOURCE_REL) or []
        source_rows = [[item.get("id"), item.get("title"),
                        item.get("publisher"), item.get("source_type"),
                        item.get("publication_date")]
                       for item in sorted(sources,
                                          key=lambda i: id_number(i.get("id")))
                       if cited & set(item.get("used_for") or ())]
        source_block = self.table(SOURCE_REL, (), ["Fonte", "Titolo",
                                                   "Editore", "Tipo", "Data"],
                                  source_rows) if source_rows else None
        conditions = self.inputs.registers.get(CONDITIONS_REL) or []
        cond_ids = {item.get("id") for item in conditions}
        condition_blocks = []
        if conditions:
            condition_blocks.append(self.table(
                CONDITIONS_REL, (),
                ["Condizione", "Descrizione", "Severità", "Responsabile",
                 "Da risolvere prima di", "Stato"],
                [[item.get("id"), item.get("description"),
                  item.get("severity"), item.get("owner"),
                  item.get("due_before_stage"),
                  item.get("resolution_status")]
                 for item in sorted(conditions,
                                    key=lambda i: id_number(i.get("id")))]))
        else:
            condition_blocks.append(self.notice("no_conditions"))
        open_items = [item for item in room.get("open_items") or ()
                      if isinstance(item, dict)]
        for item in open_items:
            ref = item.get("item_ref")
            if not is_form("COND", ref) or ref not in cond_ids:
                self.unresolved(ref, f"open_items della Data Room: {ref!r} "
                                     f"non risolve in {CONDITIONS_REL}")
        if open_items:
            condition_blocks.append(self.table(
                rel, ("data_room", "open_items"), ["Voce", "Stato", "Prova"],
                [[item.get("item_ref"), item.get("status"),
                  item.get("proof_ref")] for item in open_items]))
        declared = self.conflict_blocks()
        gaps = [item for item in room.get("unresolved_evidence_gaps") or ()
                if isinstance(item, dict)]
        if gaps:
            declared.append(self.table(
                rel, ("data_room", "unresolved_evidence_gaps"),
                ["Tipo", "Riferimento", "Dettaglio"],
                [[item.get("kind"), item.get("ref"), item.get("detail")]
                 for item in gaps]))
        stale = [item for item in room.get("stale_evidence") or ()
                 if isinstance(item, str)]
        if stale:
            declared.append(self.notice("stale_intro"))
            declared.append(self.canonical_list(
                rel, ("data_room", "stale_evidence"), stale))
        else:
            declared.append(self.notice("no_stale"))
        provenance = [
            self.table(SELF_REL, ("document_generation", "document"),
                       ["Voce", "Valore"],
                       [["Data dichiarata del documento",
                         self.proposal["as_of"]],
                        ["Etichetta di versione",
                         self.proposal["version_label"]]]),
            self.table(SELF_REL, ("document_generation", "inputs"),
                       ["Ingresso", "Ruolo", "Versione",
                        "Riferimento data room",
                        "Corrispondenza con la data room"],
                       [[item["path"], item["role"],
                         "sha256:" + item["sha256"][:12],
                         item["data_room_document_id"],
                         item["data_room_match"]]
                        for item in self.inputs_manifest])]
        if self.drift:
            provenance.append(self.notice("drift_intro"))
            provenance.append(self.canonical_list(
                SELF_REL, ("document_generation", "disclosures",
                           "register_drift_since_data_room"), self.drift))
        provenance += [self.notice("labels_notice"),
                       self.notice("review_notice"),
                       self.notice("export_notice")]
        return [("Indice della data room", index),
                ("Registro dei claim", register),
                ("Assunzioni utilizzate", [self.or_empty(assumptions)]),
                ("Fonti", [self.or_empty(source_block, "no_sources")]),
                ("Condizioni e voci aperte", condition_blocks),
                ("Incoerenze e lacune dichiarate", declared),
                ("Stato dei dati e provenienza", provenance)]

    def conflict_blocks(self):
        blocks = []
        room = self.inputs.room()
        for position, item in enumerate(room.get("conflicts") or ()):
            if not isinstance(item, dict):
                continue
            base = ("conflicts", position)
            refs = [self.dr_bind(f"conflicts.{position}.issue_id",
                                 *base, "issue_id")]
            if item.get("kind") == "contradiction":
                template_id = "incoherence_contradiction"
                refs.append(self.dr_bind(f"conflicts.{position}.claim_id",
                                         *base, "claim_id"))
            else:
                template_id = "incoherence_duplicate"
            for field in ("evidence_a", "evidence_b", "severity",
                          "decision_required"):
                refs.append(self.dr_bind(f"conflicts.{position}.{field}",
                                         *base, field))
            for index, _file in enumerate(item.get("files") or ()):
                refs.append(self.dr_bind(f"conflicts.{position}.files.{index}",
                                         *base, "files", index))
            blocks.append(self.notice(template_id, refs))
        if not blocks:
            blocks.append(self.notice("no_conflicts"))
        return blocks

    # ---- executive summary ----------------------------------------------------

    def ch01(self):
        s01 = f"{S01}/{CANONICAL_NAME}"
        s02 = f"{S02}/{CANONICAL_NAME}"
        s03 = f"{S03}/{CANONICAL_NAME}"
        s05 = f"{S05}/{CANONICAL_NAME}"
        identity = [self.template("es_identity", [
            self.by_key.get("project.name"),
            self.by_key.get("profile.startup_type"),
            self.by_key.get("profile.development_stage"),
            self.by_key.get("profile.primary_reader")]),
            self.paragraph(s01, "problem_statement", "description")]
        beachhead = self.leaf(s02, "beachhead") or {}
        segment = self.by_key.get(f"segments.{beachhead.get('segment_ref')}"
                                  ".name")
        target = []
        if segment:
            if isinstance(beachhead.get("selection_criteria"), str):
                criteria = self.bind("segments.beachhead.selection_criteria",
                                     s02, ("beachhead", "selection_criteria"))
                target.append(self.template("es_beachhead",
                                            [segment, criteria]))
            else:
                target.append(self.template("es_beachhead_short", [segment]))
        target.append(self.paragraph(s03, "value_proposition",
                                     "switching_rationale"))
        vp_segment = self.by_key.get(
            f"segments.{self.leaf(s03, 'value_proposition', 'segment_ref')}"
            ".name")
        if vp_segment:
            target.append(self.template("vp_segment", [vp_segment]))
        market = self.leaf(f"{S04}/{CANONICAL_NAME}", "market_model") or {}
        market_refs = [self.by_key.get(f"register.{market.get(field)}")
                       for field in ("tam_ref", "sam_ref", "som_ref")]
        economy = []
        if all(market_refs):
            economy.append(self.template("es_market", market_refs))
        model = self.leaf(s05, "business_model") or {}
        price = self.by_key.get(f"register.{model.get('pricing_ref')}")
        if price and isinstance(model.get("recurrence"), str) and \
                isinstance(model.get("channel"), str):
            economy.append(self.template("es_business_model", [
                price,
                self.bind("business_model.recurrence", s05,
                          ("business_model", "recurrence")),
                self.bind("business_model.channel", s05,
                          ("business_model", "channel"))]))
        elif price:
            economy.append(self.template("es_business_model_short", [price]))
        coverage = self.coverage_refs()
        evidence = [self.template("coverage", coverage) if coverage
                    else self.notice("es_no_claims")]
        by_id = {item.get("claim_id"): item for item in self.claims()}
        chosen = [by_id[ref].get("statement") for ref in
                  self.selection["claim_refs"] if ref in by_id]
        if chosen:
            evidence.append(self.template("es_highlight_intro"))
            evidence.append(self.canonical_list(
                f"{S12}/{CANONICAL_NAME}", ("data_room", "claims"), chosen))
        else:
            evidence.append(self.notice("es_no_highlight_claims"))
        roadmap_rows = []
        roadmap_refs = []
        for ref in self.selection["milestone_refs"]:
            position = self.milestone_position(ref)
            if position is None:
                continue
            item = self.milestones()[position]
            coverage_text, coverage_ref = self.coverage_cell(ref)
            roadmap_rows.append([item.get("title"), item.get("target_date"),
                                 coverage_text])
            roadmap_refs.append(coverage_ref)
        roadmap = [self.table(f"{S09}/{CANONICAL_NAME}",
                              ("milestone_plan", "milestones"),
                              ["Milestone", "Data obiettivo",
                               "Copertura della richiesta"], roadmap_rows,
                              roadmap_refs)] if roadmap_rows else \
            [self.notice("es_no_highlight_milestones")]
        finance = self.es_numbers()
        status = self.es_status()
        return [("Il progetto e il problema", identity),
                ("Cliente target e soluzione", target),
                ("Mercato e modello di business",
                 economy or [self.notice("empty_list")]),
                ("Evidenze", evidence),
                ("Roadmap", roadmap),
                ("Numeri finanziari e richiesta di finanziamento", finance),
                ("Stato del piano", status),
                ("Avvertenza", [self.notice("es_disclaimer")])]

    def es_numbers(self):
        """ES-09 e ES-10: gli STESSI legami dei capitoli 15 e 16 (`XS-05`)."""
        s10 = f"{S10}/{CANONICAL_NAME}"
        rows = []
        refs = []
        for key, label in (
                ("financial.funding_gap.funding_gap_to_zero",
                 "Fabbisogno di cassa, misura a cassa zero"),
                ("financial.funding_gap.funding_gap_to_buffer",
                 "Fabbisogno di cassa, misura a buffer"),
                ("financial.runway.runway_to_zero",
                 "Runway, misura a cassa zero, in periodi"),
                ("financial.runway.runway_to_buffer",
                 "Runway, misura a buffer, in periodi"),
                ("financial.break_even.status",
                 "Esito del modulo di pareggio")):
            binding = self.by_key.get(key)
            if binding:
                rows.append([label, self.rendered(binding)])
                refs.append(binding)
        blocks = []
        if rows:
            blocks.append(self.table(s10, ("financial_plan", "results",
                                           "modules"), ["Grandezza", "Valore"],
                                     rows, refs))
        reason = self.paragraph(s10, "financial_plan", "results", "modules",
                                "break_even", "not_applicable_reason")
        if reason:
            blocks.append(reason)
        s11 = f"{S11}/{CANONICAL_NAME}"
        funding_rows = []
        funding_refs = []
        for key, label in (
                ("funding.requested_capital.amount", "Capitale richiesto"),
                ("funding.runway.before_financing.runway_to_zero",
                 "Runway prima del finanziamento a cassa zero"),
                ("funding.runway.before_financing.runway_to_buffer",
                 "Runway prima del finanziamento a buffer"),
                ("funding.runway.after_financing.periods",
                 "Runway dopo il finanziamento")):
            binding = self.by_key.get(key)
            if binding:
                funding_rows.append([label, self.rendered(binding)])
                funding_refs.append(binding)
        blocks.append(self.table(s11, ("funding_request",), ["Voce", "Valore"],
                                 funding_rows, funding_refs))
        proceeds_rows = []
        proceeds_refs = []
        request = self.leaf(s11, "funding_request") or {}
        for position, item in enumerate(request.get("use_of_proceeds") or ()):
            money = self.by_key.get(f"funding.use_of_proceeds.{position}."
                                    "amount")
            share = self.by_key.get(f"funding.use_of_proceeds.{position}."
                                    "percentage")
            if money and share and isinstance(item, dict):
                proceeds_rows.append([item.get("label"), self.rendered(money),
                                      self.rendered(share)])
                proceeds_refs += [money, share]
        if proceeds_rows:
            blocks.append(self.table(s11, ("funding_request",
                                           "use_of_proceeds"),
                                     ["Categoria", "Importo", "Percentuale"],
                                     proceeds_rows, proceeds_refs))
        return blocks

    def es_status(self):
        """ES-11: stato del piano, NON sopprimibile (`XS-11`)."""
        blocks = [self.template("es_status", [
            self.by_key.get("financial.validation.result"),
            self.by_key.get("financial.validation.propagated_status"),
            self.by_key.get("financial.validation.investor_readiness.status"),
            self.by_key.get("financial.scenarios.coverage.level")]),
            self.template("es_funding_status", [
                self.by_key.get("funding.governance.propagated_state"),
                self.by_key.get("funding.sufficiency.residual_gap")])]
        conditions = self.inputs.registers.get(CONDITIONS_REL) or []
        chunks = []
        for position, item in enumerate(conditions):
            if item.get("resolution_status") == "open":
                chunks.append([
                    self.bind(f"conditions.{item.get('id')}.id",
                              CONDITIONS_REL, (position, "id")),
                    self.bind(f"conditions.{item.get('id')}.description",
                              CONDITIONS_REL, (position, "description"))])
        if chunks:
            blocks.append(self.template("es_open_conditions_intro"))
            blocks.append(self.template_list("es_open_condition", chunks))
        else:
            blocks.append(self.notice("es_no_open_conditions"))
        by_status = {"unsupported": [], "contested": []}
        for position, item in enumerate(self.inputs.room().get("claims") or ()):
            status = item.get("support_status") if isinstance(item, dict) \
                else None
            if status in by_status:
                ref = item.get("claim_id")
                by_status[status].append([
                    self.dr_bind(f"claims.{ref}.claim_id", "claims", position,
                                 "claim_id"),
                    self.dr_bind(f"claims.{ref}.statement", "claims", position,
                                 "statement")])
        if by_status["unsupported"]:
            blocks.append(self.template("es_unsupported_intro"))
            blocks.append(self.template_list("es_unsupported_claim",
                                             by_status["unsupported"]))
        else:
            blocks.append(self.notice("es_no_unsupported_claims"))
        if by_status["contested"]:
            blocks.append(self.template("es_contested_intro"))
            blocks.append(self.template_list("es_contested_claim",
                                             by_status["contested"]))
        request = self.leaf(f"{S11}/{CANONICAL_NAME}", "funding_request") or {}
        items = [[self.fr_bind(f"unresolved_validation_items.{position}.code",
                               "unresolved_validation_items", position,
                               "code"),
                  self.fr_bind(f"unresolved_validation_items.{position}."
                               "message", "unresolved_validation_items",
                               position, "message")]
                 for position, item in enumerate(
                     request.get("unresolved_validation_items") or ())
                 if isinstance(item, dict)]
        if items:
            blocks.append(self.template("es_unresolved_intro"))
            blocks.append(self.template_list("es_unresolved_item", items))
        blocks.append(self.notice("es_appendix_pointer"))
        return blocks

    # ---- selezione e chiusura -----------------------------------------------

    def select(self):
        """`XS-09` e `XS-12`: il writer seleziona SOLO `MIL-*` esistenti e
        `CLM-*` supportati, entro cinque e cinque."""
        highlights = self.proposal.get("highlights")
        milestones = self.milestones()
        claims = self.claims()
        if highlights is None:
            ordered = sorted(milestones, key=lambda item: (
                str(item.get("target_date")), id_number(item.get("id"))))
            self.selection = {
                "milestone_refs": [item.get("id") for item in ordered[:5]],
                "claim_refs": [item.get("claim_id") for item in claims
                               if item.get("support_status") ==
                               "supported"][:5],
                "origin": "default"}
            return
        known_milestones = {item.get("id") for item in milestones}
        statuses = {item.get("claim_id"): item.get("support_status")
                    for item in claims}
        for field, known, kind in (("milestone_refs", known_milestones,
                                    "milestone"),
                                   ("claim_refs", set(statuses), "claim")):
            refs = highlights.get(field) or []
            if len(refs) > 5:
                self.errors.append((CODE_HIGHLIGHT, field,
                                    f"{len(refs)} {kind} in evidenza oltre "
                                    "il limite di cinque"))
            if len(set(refs)) != len(refs):
                self.errors.append((CODE_HIGHLIGHT, field,
                                    f"{kind} in evidenza ripetute"))
            for ref in refs:
                if ref not in known:
                    self.errors.append((CODE_HIGHLIGHT, ref,
                                        f"{kind} in evidenza {ref!r} "
                                        "inesistente"))
        for ref in highlights.get("claim_refs") or []:
            if ref in statuses and statuses[ref] != "supported":
                self.errors.append((CODE_HIGHLIGHT, ref,
                                    f"il claim {ref!r} e' "
                                    f"{statuses[ref]!r}: in evidenza SOLO "
                                    "claim supported"))
        self.selection = {
            "milestone_refs": list(highlights.get("milestone_refs") or []),
            "claim_refs": list(highlights.get("claim_refs") or []),
            "origin": "proposal"}


def build_document(inputs, proposal):
    """Il canonico DERIVATO dagli ingressi e dalla proposta. Ogni rifiuto e'
    ATTRIBUITO; nessun file e' scritto qui."""
    if inputs.errors:
        raise BuildRefusal(list(inputs.errors))
    drift = inputs.pins()
    inputs.financial_basis()
    inputs.funding_projection()
    if inputs.errors:
        raise BuildRefusal(list(inputs.errors))
    builder = Builder(inputs, proposal)
    builder.select()
    builder.drift = drift
    builder.inputs_manifest = inputs.inputs_manifest(drift)
    chapters = builder.build()
    if builder.errors:
        raise BuildRefusal(builder.errors)
    body = assemble(builder, inputs, proposal, chapters, drift)
    document = {"schema_version": SCHEMA_VERSION, "document_generation": body}
    body["identity"] = {"algorithm": "sha256",
                        "excluded_fields": ["rendering"],
                        "payload_sha256": identity_of(document)}
    body["rendering"]["markdown_sha256"] = sha256_bytes(
        render_markdown(document).encode("utf-8"))
    return document


def assemble(builder, inputs, proposal, chapters, drift):
    config = inputs.config_doc or {}
    profile = inputs.profile or {}
    out = []
    for ordinal, (chapter_id, title) in enumerate(CHAPTERS, start=1):
        result = chapters[chapter_id]
        status = "rendered"
        if isinstance(result, tuple) and isinstance(result[0], str):
            status, result = result
        sections = []
        for s_ordinal, (s_title, blocks) in enumerate(result, start=1):
            section_id = f"{chapter_id}-{s_ordinal:02d}"
            kept = []
            for block in blocks:
                if block is None:
                    continue
                block = dict(block, block_id=f"{section_id}-b"
                                             f"{len(kept) + 1:02d}")
                kept.append({key: block[key] for key in sorted(block)})
            sections.append({"section_id": section_id, "ordinal": s_ordinal,
                             "title": s_title, "anchor": section_id,
                             "blocks": kept})
        claim_refs = [item.get("claim_id") for item in builder.claims()
                      if chapter_id in CLAIM_CHAPTERS.get(
                          item.get("related_section"), ())]
        if claim_refs and chapter_id != "cap-17":
            refs = [builder.dr_bind(f"claims.{ref}.claim_id", "claims",
                                    position, "claim_id")
                    for position, item in enumerate(builder.claims())
                    for ref in [item.get("claim_id")] if ref in claim_refs]
            last = sections[-1]
            block = builder.template("refs_line", refs)
            block["block_id"] = f"{last['section_id']}-b" \
                                f"{len(last['blocks']) + 1:02d}"
            last["blocks"].append({key: block[key] for key in sorted(block)})
        reason = TEMPLATES["risks_not_applicable"] \
            if status == "not_applicable" else None
        out.append({"chapter_id": chapter_id, "ordinal": ordinal,
                    "title": title, "anchor": chapter_id,
                    "source_stages": SOURCE_STAGES[chapter_id],
                    "status": status, "not_applicable_reason": reason,
                    "claim_refs": claim_refs, "sections": sections})
    room = inputs.room()
    plan = (inputs.stages.get(S10) or {}).get("financial_plan") or {}
    request = (inputs.stages.get(S11) or {}).get("funding_request") or {}
    body = {
        "document": {
            "title": f"Business plan — {config.get('project_name')}",
            "project_name": str(config.get("project_name")),
            "project_slug": str(config.get("project_slug")),
            "version_label": proposal["version_label"],
            "as_of": proposal["as_of"], "language": "it",
            "primary_reader": str(profile.get("primary_reader")),
            "startup_type": str(profile.get("startup_type")),
            "development_stage": str(profile.get("development_stage"))},
        "inputs": builder.inputs_manifest,
        "selection": builder.selection,
        "chapters": out,
        "bindings": builder.bindings,
        "coherence": {"checks": coherence_checks(drift)},
        "disclosures": expected_disclosures(inputs, room, plan, request,
                                            drift),
        "rendering": {"format": "gfm-markdown", "output_path": OUTPUT_REL,
                      "max_heading_level": 3, "markdown_sha256": None},
    }
    return body


SOURCE_STAGES = {
    "cap-01": list(CONTENT_STAGES), "cap-02": ["00_idea-discovery", S08],
    "cap-03": [S01], "cap-04": [S02], "cap-05": [S03], "cap-06": [S04],
    "cap-07": [S04], "cap-08": [S05], "cap-09": [S06], "cap-10": [S07],
    "cap-11": [S07], "cap-12": [S08], "cap-13": [S09, S11],
    "cap-14": [S07, S08, S09], "cap-15": [S10, S12], "cap-16": [S11],
    "cap-17": [S12]}

XS_MESSAGES = (
    ("XS-01", "catena completa: stage 00-12 completati, current_stage 13"),
    ("XS-02", "ingressi immutabili pinnati ai checksum della Data Room"),
    ("XS-03", "registri condivisi confrontati con la Data Room"),
    ("XS-04", "base finanziaria: record dei driver identici a "
              "source_record_hash"),
    ("XS-05", "stessa chiave semantica, stesso legame e stesso letterale"),
    ("XS-06", "ogni riferimento reso risolve in forma canonica"),
    ("XS-07", "join roadmap e funding request per MIL"),
    ("XS-08", "la funding request proietta questo piano finanziario"),
    ("XS-09", "stato dei claim verbatim, evidenza solo supported"),
    ("XS-10", "etichetta epistemica su ogni valore di registro"),
    ("XS-11", "disclosure obbligatorie presenti e nominate"),
    ("XS-12", "selezione del writer entro i limiti e su id esistenti"),
)


def coherence_checks(drift):
    checks = []
    for check_id, message in XS_MESSAGES:
        status = "PASS"
        refs = []
        if check_id == "XS-03" and drift:
            status = "WARNING"
            refs = list(drift)
        checks.append({"check_id": check_id, "status": status,
                       "affected_refs": refs, "message": message})
    return checks


def expected_disclosures(inputs, room, plan, request, drift):
    conditions = inputs.registers.get(CONDITIONS_REL) or []
    validation = plan.get("validation") or {}
    coverage = ((plan.get("results") or {}).get("scenarios") or {}).get(
        "coverage") or {}
    completeness = room.get("completeness") or {}
    sufficiency = request.get("sufficiency") or {}
    return {
        "open_conditions": [
            {"condition_id": str(item.get("id")),
             "description": str(item.get("description")),
             "severity": str(item.get("severity")),
             "due_before_stage": str(item.get("due_before_stage"))}
            for item in sorted(conditions,
                               key=lambda i: id_number(i.get("id")))
            if item.get("resolution_status") == "open"],
        "unsupported_claims": [str(item) for item in
                               room.get("unsupported_claims") or ()],
        "contested_claims": [str(item.get("claim_id")) for item in
                             room.get("claims") or () if isinstance(item, dict)
                             and item.get("support_status") == "contested"],
        "data_room_conflicts": [str(item.get("issue_id")) for item in
                                room.get("conflicts") or ()
                                if isinstance(item, dict)],
        "data_room_gaps": [{"kind": str(item.get("kind")),
                            "ref": str(item.get("ref"))} for item in
                           room.get("unresolved_evidence_gaps") or ()
                           if isinstance(item, dict)],
        "data_room_completeness": {
            "claims_total": lexical(completeness.get("claims_total")),
            "claims_supported": lexical(completeness.get("claims_supported")),
            "coverage_percent": lexical(completeness.get("coverage_percent"))},
        "financial_readiness": {
            "result": lexical(validation.get("result")),
            "propagated_status": lexical(validation.get("propagated_status")),
            "investor_readiness_status": lexical(
                (validation.get("investor_readiness") or {}).get("status")),
            "scenario_coverage_level": lexical(coverage.get("level"))},
        "funding_residual": {
            "sufficiency": {
                "funded_horizon": lexical(sufficiency.get("funded_horizon")),
                "residual_gap": lexical(sufficiency.get("residual_gap")),
                "residual_gap_disclosed": sufficiency.get(
                    "residual_gap_disclosed") is True,
                "basis": lexical(sufficiency.get("basis"))},
            "unresolved_validation_items": [
                {"severity": str(item.get("severity")),
                 "code": str(item.get("code")),
                 "message": str(item.get("message"))}
                for item in request.get("unresolved_validation_items") or ()
                if isinstance(item, dict)]},
        "register_drift_since_data_room": list(drift),
        "final_review": "not_performed",
    }


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
    commit (`ensure_ascii=False`, ordine delle chiavi conservato): ammetterla
    impedisce che un canonico non ASCII, riscritto al commit, fallisca poi
    l'impact."""
    return json.dumps(document, indent=2, ensure_ascii=False,
                      sort_keys=True) + "\n"


def gen(document):
    return (document or {}).get("document_generation") or {}


def identity_of(document):
    """L'identita': `schema_version` piu' `document_generation` SENZA
    `rendering` e SENZA `identity`, per COSTRUZIONE."""
    body = {key: value for key, value in gen(document).items()
            if key not in ("rendering", "identity")}
    payload = {"schema_version": (document or {}).get("schema_version"),
               "document_generation": body}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)
    return sha256_bytes(blob.encode("utf-8"))


# --------------------------------------------------------------------------
# RESA Markdown e handoff — funzioni PURE del canonico
# --------------------------------------------------------------------------


def inline(value):
    """Testo su UNA riga: terminatori di riga uniti, `<` neutralizzato, spazi
    esterni rimossi. Nessuna parola cambia."""
    text = LINE_BREAKS_RE.sub(" ", str(value)).strip()
    return text.replace("<", "&lt;")


def block_safe(text):
    """Un testo che, a inizio riga, aprirebbe una struttura Markdown (titolo,
    citazione, elenco, tabella, recinto) e' reso letterale."""
    match = re.match(r"^([0-9]+)([.)])", text)
    if match:
        return f"{match.group(1)}\\{match.group(2)}{text[match.end():]}"
    if BLOCK_MARKER_RE.match(text):
        return "\\" + text
    return text


def cell(value):
    text = inline(value)
    return text.replace("|", "\\|") if text else "-"


def yaml_scalar(value):
    return json.dumps(str(value), ensure_ascii=False)


def reader_label(document):
    value = (gen(document).get("document") or {}).get("primary_reader")
    return PROFILE_LABELS["primary_reader"].get(value, value)


def render_block(block):
    kind = block.get("kind")
    lines = []
    if kind == "paragraph":
        lines.append(block_safe(inline(block.get("text"))))
    elif kind == "list":
        for item in block.get("items") or ():
            lines.append("- " + (block_safe(inline(item)) or "-"))
    elif kind == "table":
        table = block.get("table") or {}
        columns = table.get("columns") or []
        lines.append("| " + " | ".join(cell(item) for item in columns) + " |")
        lines.append("|" + "---|" * len(columns))
        for row in table.get("rows") or ():
            lines.append("| " + " | ".join(cell(item) for item in row) + " |")
    elif kind == "notice":
        for line in str(block.get("text") or "").split("\n"):
            text = inline(line)
            lines.append("> " + block_safe(text) if text else ">")
    lines.append("")
    return lines


def render_markdown(document):
    """`output/business-plan.md`: resa GFM deterministica del SOLO
    canonico. Un H1, diciassette H2 «N. Titolo», H3 «N.M Titolo», indice di
    link ad ancore esplicite, nessun numero di pagina."""
    body = gen(document)
    meta = body.get("document") or {}
    identity = (body.get("identity") or {}).get("payload_sha256")
    lines = ["---"]
    for key, value in (("title", meta.get("title")),
                       ("project", meta.get("project_name")),
                       ("version", meta.get("version_label")),
                       ("date", meta.get("as_of")),
                       ("language", meta.get("language")),
                       ("reader", reader_label(document)),
                       ("document_identity", f"sha256:{identity}"),
                       ("generator", GENERATOR)):
        lines.append(f"{key}: {yaml_scalar(value)}")
    lines += ["---", "", f"# {inline(meta.get('title'))}", "", "**Indice**",
              ""]
    chapters = [item for item in body.get("chapters") or ()
                if isinstance(item, dict)]
    for chapter in chapters:
        lines.append(f"- [{chapter.get('ordinal')}. "
                     f"{inline(chapter.get('title'))}]"
                     f"(#{chapter.get('anchor')})")
    lines.append("")
    for chapter in chapters:
        lines += [f'<a id="{chapter.get("anchor")}"></a>',
                  f"## {chapter.get('ordinal')}. {inline(chapter.get('title'))}",
                  ""]
        if chapter.get("status") == "not_applicable":
            lines += ["> " + inline(chapter.get("not_applicable_reason")), ""]
        for section in chapter.get("sections") or ():
            lines += [f'<a id="{section.get("anchor")}"></a>',
                      f"### {chapter.get('ordinal')}.{section.get('ordinal')} "
                      f"{inline(section.get('title'))}", ""]
            for block in section.get("blocks") or ():
                lines += render_block(block)
    return "\n".join(lines).rstrip("\n") + "\n"


def render_handoff(document):
    """L'handoff CANONICO dello Stage 13: resa deterministica del SOLO
    canonico, verificata in egress contro questa stessa resa."""
    body = gen(document)
    meta = body.get("document") or {}
    disclosures = body.get("disclosures") or {}
    checks = ", ".join(f"{item.get('check_id')} {item.get('status')}"
                       for item in (body.get("coherence") or {}).get("checks")
                       or ())
    conditions = ", ".join(item.get("condition_id") for item in
                           disclosures.get("open_conditions") or ()
                           if isinstance(item, dict)) or "nessuna"
    unsupported = ", ".join(disclosures.get("unsupported_claims") or ()) or \
        "nessuno"
    drift = ", ".join(disclosures.get("register_drift_since_data_room") or ()) \
        or "nessuno"
    lines = [
        "# Handoff — Stage 13 Document generation", "",
        f"next_action: advance-stage {STAGE13} con --gate-result approved; "
        f"dopo il commit terminale pubblicare {OUTPUT_REL} con "
        "validate_document_generation.py --publish.", "",
        f"- Documento: {inline(meta.get('title'))} · versione: "
        f"{inline(meta.get('version_label'))} · data dichiarata: "
        f"{inline(meta.get('as_of'))}",
        f"- Identita' del canonico: sha256:"
        f"{(body.get('identity') or {}).get('payload_sha256')}",
        f"- Capitoli: {len(body.get('chapters') or [])} · legami: "
        f"{len(body.get('bindings') or [])}",
        f"- Controlli di coerenza: {checks}",
        f"- Condizioni aperte: {conditions}",
        f"- Claim non supportati: {unsupported}",
        f"- Registri modificati dopo la data room: {drift}",
        "- Review finale avversariale: non eseguita; PDF e DOCX: non "
        "disponibili in questa release.", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# QUALITY GATE della resa — elenco CHIUSO `QG-01`...`QG-10`
# --------------------------------------------------------------------------

H2_RE = re.compile(r"^## ([0-9]+)\. (.+)$")
H3_RE = re.compile(r"^### ([0-9]+)\.([0-9]+) (.+)$")
ANCHOR_RE = re.compile(r'^<a id="([^"]+)"></a>$')
LINK_RE = re.compile(r"\]\(#([^)]+)\)")
TOC_RE = re.compile(r"^- \[([0-9]+)\. (.+)\]\(#([^)]+)\)$")
SEPARATOR_RE = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+$")


def table_width(line):
    return len(re.split(r"(?<!\\)\|", line)) - 2


def markdown_problems(markdown, document):
    """I quality gate `QG-01`...`QG-10` sulla resa. Ritorna i rilievi
    ATTRIBUITI `(codice, riferimento, messaggio)`."""
    problems = []

    def add(code, ref, message):
        problems.append((code, ref, message))
    text = markdown if isinstance(markdown, str) else ""
    # QG-09 — forma del file
    if text.startswith("﻿"):
        add(CODE_NONDETERMINISTIC, "QG-09", "BOM iniziale")
    if "\r" in text:
        add(CODE_NONDETERMINISTIC, "QG-09", "fine riga CR")
    if not text.endswith("\n") or text.endswith("\n\n"):
        add(CODE_NONDETERMINISTIC, "QG-09", "newline finale non singola")
    lines = text.split("\n")
    for number, line in enumerate(lines, start=1):
        if line != line.rstrip(" \t"):
            add(CODE_NONDETERMINISTIC, "QG-09",
                f"spazio finale alla riga {number}")
            break
    # QG-01 — front matter, titoli
    if not lines or lines[0] != "---":
        add(CODE_STRUCTURE, "QG-01", "front matter assente")
        end = 0
    else:
        end = next((i for i, line in enumerate(lines[1:], start=1)
                    if line == "---"), None)
        if end is None:
            add(CODE_STRUCTURE, "QG-01", "front matter non chiuso")
            end = 0
        else:
            keys = [line.split(":", 1)[0] for line in lines[1:end]]
            if keys != list(FRONT_MATTER_KEYS):
                add(CODE_STRUCTURE, "QG-01",
                    f"chiavi del front matter {keys}")
    content = lines[end + 1:] if end else lines
    h1 = [line for line in content if line.startswith("# ")]
    if len(h1) != 1:
        add(CODE_STRUCTURE, "QG-01", f"{len(h1)} titoli H1 invece di uno")
    for line in content:
        if re.match(r"^#{4,}\s", line):
            add(CODE_STRUCTURE, "QG-01", f"titolo oltre il livello 3: {line}")
    h2 = []
    current = None
    expected_section = 0
    section_titles = {}
    for line in content:
        match = H2_RE.match(line)
        if match:
            current = int(match.group(1))
            h2.append((current, match.group(2)))
            expected_section = 0
            continue
        match = H3_RE.match(line)
        if match:
            if current is None or int(match.group(1)) != current:
                add(CODE_STRUCTURE, "QG-01", f"H3 fuori capitolo: {line}")
            expected_section += 1
            if int(match.group(2)) != expected_section:
                add(CODE_STRUCTURE, "QG-01",
                    f"sezioni non consecutive: {line}")
            titles = section_titles.setdefault(current, [])
            if match.group(3) in titles:
                add(CODE_STRUCTURE, "QG-04",
                    f"titolo di sezione duplicato: {line}")
            titles.append(match.group(3))
    expected = [(position, inline(title)) for position, (_, title) in
                enumerate(CHAPTERS, start=1)]
    if h2 != expected:
        add(CODE_STRUCTURE, "QG-01",
            "gli H2 non sono i diciassette capitoli nell'ordine fisso: "
            f"{h2[:20]}")
    # QG-02 — indice e ancore
    anchors = [ANCHOR_RE.match(line).group(1) for line in content
               if ANCHOR_RE.match(line)]
    if len(set(anchors)) != len(anchors):
        add(CODE_STRUCTURE, "QG-02", "ancore duplicate")
    toc = []
    if "**Indice**" in content:
        start = content.index("**Indice**") + 1
        for line in content[start:]:
            if not line and toc:
                break
            match = TOC_RE.match(line)
            if match:
                toc.append((int(match.group(1)), match.group(2),
                            match.group(3)))
    if [(n, t) for n, t, _ in toc] != expected or \
            [a for _, _, a in toc] != [ref for ref, _ in CHAPTERS]:
        add(CODE_STRUCTURE, "QG-02", "l'indice non elenca i diciassette "
                                     "capitoli con le loro ancore")
    for target in LINK_RE.findall(text):
        if target not in anchors:
            add(CODE_STRUCTURE, "QG-02", f"link interno rotto: #{target}")
    # QG-03 — nessun capitolo vuoto, nessun titolo orfano
    for position, line in enumerate(content):
        is_chapter = bool(H2_RE.match(line))
        is_section = bool(H3_RE.match(line))
        if not (is_chapter or is_section):
            continue
        following = []
        for item in content[position + 1:]:
            if H2_RE.match(item) or (is_section and H3_RE.match(item)):
                break
            if item and not ANCHOR_RE.match(item) and not H3_RE.match(item):
                following.append(item)
        if not following:
            add(CODE_STRUCTURE, "QG-03", f"titolo senza contenuto: {line}")
    for chapter in gen(document).get("chapters") or ():
        if isinstance(chapter, dict) and \
                chapter.get("status") == "not_applicable" and \
                inline(chapter.get("not_applicable_reason") or "\0") not in \
                text:
            add(CODE_STRUCTURE, "QG-03",
                f"{chapter.get('chapter_id')} non applicabile senza motivo")
    # QG-07 — tabelle ben formate
    in_table = False
    width = None
    for number, line in enumerate(content, start=1):
        if line.startswith("|"):
            if not in_table:
                in_table = True
                width = table_width(line)
                header = number
                continue
            if number == header + 1 and not SEPARATOR_RE.match(line):
                add(CODE_STRUCTURE, "QG-07", f"tabella senza separatore: "
                                             f"{line[:60]}")
            if table_width(line) != width:
                add(CODE_STRUCTURE, "QG-07",
                    f"tabella sbilanciata: {line[:80]}")
        else:
            in_table = False
    # QG-05 / QG-06 — segnaposto e path interni
    for number, line in enumerate(content, start=1):
        for pattern in (PLACEHOLDER_WORDS, PLACEHOLDER_EXACT,
                        PLACEHOLDER_MARKS):
            match = pattern.search(line)
            if match:
                add(CODE_PLACEHOLDER, "QG-05",
                    f"segnaposto o linguaggio di debug {match.group(0)!r} "
                    f"alla riga {number}")
        match = INTERNAL_PATHS.search(line)
        if match:
            add(CODE_PLACEHOLDER, "QG-06",
                f"path interno {match.group(0)!r} alla riga {number}")
    # QG-08 — segreti
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            add(CODE_SECRET, "QG-08", f"{name} nella resa del documento")
    # QG-10 — letterali delle chiavi di `XS-05` identici in ES e nei capitoli
    body = gen(document)
    bindings = {item.get("binding_id"): item for item in
                body.get("bindings") or () if isinstance(item, dict)}
    summary_refs, body_refs = set(), set()
    for chapter in body.get("chapters") or ():
        if not isinstance(chapter, dict):
            continue
        target = summary_refs if chapter.get("chapter_id") == "cap-01" \
            else body_refs
        for section in chapter.get("sections") or ():
            for block in section.get("blocks") or ():
                target.update(block.get("binding_refs") or ())
    for ref in sorted(summary_refs):
        item = bindings.get(ref) or {}
        if str(item.get("key", "")).startswith(("register.", "financial.",
                                                "funding.")) and \
                ref not in body_refs:
            add(CODE_BINDING, ref,
                f"il letterale {item.get('key')!r} dell'executive summary non "
                "e' lo stesso legame di un capitolo del corpo (XS-05)")
    return problems


# --------------------------------------------------------------------------
# VALIDAZIONE del canonico — egress, impact, build, publish
# --------------------------------------------------------------------------


class Check:
    """Il contesto di una validazione: fase, ingressi e report."""

    def __init__(self, inputs, report, phase):
        self.inputs = inputs
        self.report = report
        self.phase = phase

    def fail(self, code, ref, message):
        self.report.add_error(code, ref=ref, message=message)

    def warn(self, code, ref, message):
        self.report.add_warning(code, ref=ref, message=message)


def source_document(check, document, rel):
    if rel == SELF_REL:
        return document
    return check.inputs.docs.get(rel)


def mutable(rel):
    return str(rel).startswith("shared/")


def check_schema(document, check):
    schema = load_schema("document-generation")
    issues = schema_issues(schema, schema, document)
    for path, message in issues[:20]:
        check.fail(CODE_STRUCTURE, path, f"schema: {message}")
    return not issues


def check_chapters(document, check):
    body = gen(document)
    chapters = [item for item in body.get("chapters") or ()
                if isinstance(item, dict)]
    observed = [(item.get("chapter_id"), item.get("title"),
                 item.get("ordinal"), item.get("anchor")) for item in chapters]
    expected = [(ref, title, position, ref) for position, (ref, title) in
                enumerate(CHAPTERS, start=1)]
    if observed != expected:
        check.fail(CODE_STRUCTURE, "chapters",
                   "i capitoli non sono i DICIASSETTE capitoli fissi del "
                   "documento con id, titoli, ordinali e ancore costanti")
    block_ids = []
    for chapter in chapters:
        for position, section in enumerate(chapter.get("sections") or (),
                                           start=1):
            section_id = f"{chapter.get('chapter_id')}-{position:02d}"
            if section.get("section_id") != section_id or \
                    section.get("ordinal") != position or \
                    section.get("anchor") != section_id:
                check.fail(CODE_STRUCTURE, section.get("section_id"),
                           f"sezione non numerata in ordine: attesa "
                           f"{section_id}")
            for block in section.get("blocks") or ():
                block_ids.append(block.get("block_id"))
    if len(set(block_ids)) != len(block_ids):
        check.fail(CODE_STRUCTURE, "block_id", "block_id duplicati")
    binding_ids = [item.get("binding_id") for item in body.get("bindings")
                   or () if isinstance(item, dict)]
    if len(set(binding_ids)) != len(binding_ids):
        check.fail(CODE_STRUCTURE, "binding_id", "binding_id duplicati")


def blocks_of(document):
    for chapter in gen(document).get("chapters") or ():
        if not isinstance(chapter, dict):
            continue
        for section in chapter.get("sections") or ():
            for block in section.get("blocks") or ():
                if isinstance(block, dict):
                    yield chapter, block


def check_bindings(document, check):
    """Ogni legame risolve, e' riletto dalla SORGENTE e reso dalla funzione
    pura di formattazione (`XS-05`, `XS-10`)."""
    body = gen(document)
    bindings = [item for item in body.get("bindings") or ()
                if isinstance(item, dict)]
    by_id = {item.get("binding_id"): item for item in bindings}
    keys = {}
    for item in bindings:
        keys.setdefault(item.get("key"), []).append(item.get("binding_id"))
    for key, ids in keys.items():
        if len(ids) > 1:
            check.fail(CODE_BINDING, key,
                       f"la chiave {key!r} ha piu' legami {ids}: stessa "
                       "chiave, stesso legame (XS-05)")
    referenced = set()
    for _chapter, block in blocks_of(document):
        for ref in block.get("binding_refs") or ():
            referenced.add(ref)
            if ref not in by_id:
                check.fail(CODE_REFERENCE, ref,
                           f"{block.get('block_id')}: binding_ref {ref!r} non "
                           "risolve in bindings[]")
    for item in bindings:
        ref = item.get("binding_id")
        if ref not in referenced:
            check.fail(CODE_STRUCTURE, ref, f"legame {ref} mai referenziato")
        source = item.get("source") or {}
        rel = source.get("file")
        value = item.get("value")
        record_id = source.get("record_id")
        qualifier = item.get("qualifier")
        current_value = value
        if record_id is not None:
            register = check.inputs.docs.get(ASSUMPTIONS_REL)
            match = PATH_TOKEN_RE.match(str(source.get("json_path")), 1) \
                if str(source.get("json_path")).startswith("$[") else None
            record = None
            if isinstance(register, list) and match and \
                    match.group(2) is not None and \
                    int(match.group(2)) < len(register):
                record = register[int(match.group(2))]
            if not isinstance(record, dict) or record.get("id") != record_id:
                check.fail(CODE_REFERENCE, ref,
                           f"{ref}: il record {record_id!r} non e' alla "
                           "posizione dichiarata del registro")
                continue
            current_value = lexical(record.get("value"))
            unit = record.get("unit") if isinstance(record.get("unit"), str) \
                and record.get("unit") else None
            currency = record.get("currency") if isinstance(
                record.get("currency"), str) and record.get("currency") \
                else None
            due = expected_qualifier(record)
            if qualifier != due:
                check.fail(CODE_PROMOTED, ref,
                           f"{record_id}: qualifica {qualifier!r} invece di "
                           f"{due!r}: un'assunzione non diventa un fatto")
            label = EPISTEMIC_LABELS.get(due)
            if label and not str(item.get("rendered")).endswith(label):
                check.fail(CODE_PROMOTED, ref,
                           f"{record_id}: letterale senza l'etichetta "
                           f"epistemica {label!r}")
            drifted = (current_value != value or unit != item.get("unit") or
                       currency != item.get("currency"))
            if drifted:
                message = (f"{ref}: il valore reso di {record_id} "
                           f"({value!r}) non e' quello del registro corrente "
                           f"({current_value!r})")
                if check.phase in ("impact", "publish"):
                    check.warn(CODE_INPUT_STALE, ref, message +
                               ": il documento e' un'istantanea datata "
                               "(semantica post-completamento)")
                else:
                    check.fail(CODE_BINDING, ref, message)
        else:
            if qualifier != "none":
                check.fail(CODE_PROMOTED, ref,
                           f"{ref}: qualifica {qualifier!r} su un letterale "
                           "non di registro")
            origin = source_document(check, document, rel)
            if origin is None:
                if check.phase != "impact":
                    check.fail(CODE_REFERENCE, ref,
                               f"{ref}: sorgente {rel!r} non disponibile")
                continue
            try:
                current_value = lexical(resolve_path(
                    origin, source.get("json_path")))
            except KeyError:
                check.fail(CODE_BINDING, ref,
                           f"{ref}: json_path {source.get('json_path')!r} non "
                           f"risolve in {rel}")
                continue
            if current_value != value:
                message = (f"{ref}: valore {value!r} diverso dalla foglia "
                           f"sorgente {current_value!r} di {rel}")
                if mutable(rel) and check.phase in ("impact", "publish"):
                    check.warn(CODE_INPUT_STALE, ref, message)
                else:
                    check.fail(CODE_BINDING, ref, message)
        expected = format_binding(str(item.get("key")), value,
                                  item.get("unit"), item.get("currency"),
                                  qualifier if qualifier in QUALIFIERS
                                  else "none")
        if item.get("rendered") != expected:
            check.fail(CODE_BINDING, ref,
                       f"{ref}: letterale reso {item.get('rendered')!r} "
                       f"diverso dalla resa della foglia {expected!r}")


def digit_residue(text, rendered_values):
    residue = str(text)
    for value in sorted(rendered_values, key=len, reverse=True):
        if value:
            residue = residue.replace(value, "")
    return has_digit(residue)


def check_blocks(document, check):
    """La regola delle TRE classi (verbatim canonico, modello costante,
    letterale legato), blocco per blocco."""
    body = gen(document)
    rendered = {item.get("binding_id"): item.get("rendered") for item in
                body.get("bindings") or () if isinstance(item, dict)}
    for chapter, block in blocks_of(document):
        ref = block.get("block_id")
        refs = [item for item in block.get("binding_refs") or ()]
        values = {rendered.get(item) for item in refs if rendered.get(item)}
        origin = block.get("origin")
        kind = block.get("kind")
        source = block.get("source") or {}
        texts = [block.get("text")] if block.get("text") is not None else []
        texts += list(block.get("items") or ())
        table = block.get("table") or {}
        texts += [item for row in table.get("rows") or () for item in row]
        if origin == "template" and kind != "table":
            template_id = block.get("template_id")
            if template_id not in TEMPLATES:
                check.fail(CODE_UNTRACED, ref,
                           f"modello {template_id!r} fuori dalla tabella "
                           "chiusa")
                continue
            if kind in ("paragraph", "notice"):
                if block.get("text") != render_template(template_id, refs,
                                                        rendered):
                    check.fail(CODE_UNTRACED, ref,
                               "il testo non e' il modello costante con i "
                               "propri letterali legati")
            elif kind == "list":
                size = slot_count(template_id)
                chunks = [refs[i:i + size] for i in range(0, len(refs), size)] \
                    if size else []
                items = [render_template(template_id, chunk, rendered)
                         for chunk in chunks]
                if list(block.get("items") or ()) != items:
                    check.fail(CODE_UNTRACED, ref,
                               "le voci non sono il modello costante con i "
                               "propri letterali legati")
            for text in texts:
                if digit_residue(text, values):
                    check.fail(CODE_UNTRACED, ref,
                               "cifra NON tracciata in un blocco di modello: "
                               "nessuna cifra vive fuori da un letterale "
                               "legato")
                    break
        if kind == "table":
            allowed = set(CELL_CONSTANTS) | values
            leaves = set()
            if origin == "canonical":
                origin_doc = source_document(check, document,
                                             source.get("file"))
                if origin_doc is not None:
                    try:
                        leaves = leaves_of(resolve_path(
                            origin_doc, source.get("json_path")))
                    except KeyError:
                        leaves = set()
            for column in table.get("columns") or ():
                if column not in CELL_CONSTANTS:
                    check.fail(CODE_UNTRACED, ref,
                               f"intestazione {column!r} fuori dalle "
                               "costanti")
            for row in table.get("rows") or ():
                for item in row:
                    if item in allowed or item in leaves:
                        continue
                    if re.match(r"^sha256:[0-9a-f]{12}\Z", str(item)) and \
                            any(len(leaf) == 64 and
                                leaf.startswith(item[7:]) for leaf in leaves):
                        continue
                    report_untraced(check, source, ref,
                                    f"cella {item!r} fuori dalle tre classi")
        elif origin == "canonical":
            origin_doc = source_document(check, document, source.get("file"))
            if origin_doc is None:
                if check.phase != "impact":
                    check.fail(CODE_REFERENCE, ref,
                               f"sorgente {source.get('file')!r} non "
                               "disponibile")
                continue
            try:
                target = resolve_path(origin_doc, source.get("json_path"))
            except KeyError:
                report_untraced(check, source, ref,
                                f"json_path {source.get('json_path')!r} non "
                                "risolve")
                continue
            if kind == "paragraph":
                if block.get("text") != target:
                    report_untraced(check, source, ref,
                                    "il testo non e' la citazione verbatim "
                                    "della propria sorgente")
            elif kind == "list":
                leaves = leaves_of(target)
                if any(item not in leaves for item in block.get("items") or
                       ()):
                    report_untraced(check, source, ref,
                                    "una voce non e' verbatim della propria "
                                    "sorgente")
        for text in texts:
            for pattern in (PLACEHOLDER_WORDS, PLACEHOLDER_EXACT,
                            PLACEHOLDER_MARKS):
                match = pattern.search(str(text))
                if match:
                    check.fail(CODE_PLACEHOLDER, source.get("json_path") or ref,
                               f"{ref}: segnaposto {match.group(0)!r} nel "
                               "testo reso")
        del chapter


def report_untraced(check, source, ref, message):
    if check.phase in ("impact", "publish") and mutable(source.get("file")):
        check.warn(CODE_INPUT_STALE, ref, f"{ref}: {message} (registro "
                                          "mutato dopo il documento)")
    else:
        check.fail(CODE_UNTRACED, ref, f"{ref}: {message}")


def claims_table(document):
    for chapter, block in blocks_of(document):
        table = block.get("table") or {}
        if chapter.get("chapter_id") == "cap-17" and \
                block.get("kind") == "table" and \
                "Supporto" in (table.get("columns") or ()):
            return block
    return None


def check_claims(document, check):
    """`XS-09`: stato dei claim VERBATIM, selezione solo `supported`."""
    room = check.inputs.room()
    statuses = {item.get("claim_id"): item.get("support_status")
                for item in room.get("claims") or () if isinstance(item, dict)}
    block = claims_table(document)
    if statuses and block is None:
        check.fail(CODE_DISCLOSURE, "cap-17", "il registro dei claim e' "
                                              "assente dall'appendice")
    if block is not None:
        columns = block["table"].get("columns") or []
        position = columns.index("Supporto")
        seen = set()
        for row in block["table"].get("rows") or ():
            ref = row[0] if row else None
            seen.add(ref)
            if ref not in statuses:
                check.fail(CODE_REFERENCE, ref, f"claim {ref!r} inesistente "
                                                "nella Data Room")
            elif len(row) > position and row[position] != statuses[ref]:
                check.fail(CODE_PROMOTED, ref,
                           f"il claim {ref} e' {statuses[ref]!r} nella Data "
                           f"Room ma e' reso {row[position]!r}")
        for ref in statuses:
            if ref not in seen:
                check.fail(CODE_DISCLOSURE, ref,
                           f"il claim {ref} e' omesso dal registro dei claim")
    selection = gen(document).get("selection") or {}
    for ref in selection.get("claim_refs") or ():
        if statuses.get(ref) != "supported":
            check.fail(CODE_HIGHLIGHT, ref, f"claim {ref!r} in evidenza non "
                                            "supported")
    milestones = {item.get("id") for item in (((check.inputs.stages.get(S09)
                                                or {}).get("milestone_plan"))
                                              or {}).get("milestones") or ()
                  if isinstance(item, dict)}
    refs = selection.get("milestone_refs") or []
    for ref in refs:
        if ref not in milestones:
            check.fail(CODE_HIGHLIGHT, ref, f"milestone {ref!r} in evidenza "
                                            "inesistente")
    for field in ("milestone_refs", "claim_refs"):
        if len(selection.get(field) or []) > 5:
            check.fail(CODE_HIGHLIGHT, field, "oltre il limite di cinque")
    for chapter in gen(document).get("chapters") or ():
        for ref in (chapter or {}).get("claim_refs") or ():
            if ref not in statuses:
                check.fail(CODE_REFERENCE, ref,
                           f"{chapter.get('chapter_id')}: claim {ref!r} "
                           "inesistente")


def check_conditions(document, check):
    """Una `COND` aperta non e' mai resa chiusa."""
    conditions = {item.get("id"): item.get("resolution_status") for item in
                  check.inputs.registers.get(CONDITIONS_REL) or ()}
    for chapter, block in blocks_of(document):
        table = block.get("table") or {}
        columns = table.get("columns") or []
        if chapter.get("chapter_id") != "cap-17" or \
                columns[:1] != ["Condizione"] or "Stato" not in columns:
            continue
        position = columns.index("Stato")
        for row in table.get("rows") or ():
            ref = row[0] if row else None
            status = conditions.get(ref)
            if status is None or len(row) <= position:
                continue
            if row[position] != status:
                if check.phase == "impact":
                    check.warn(CODE_INPUT_STALE, ref,
                               f"{ref}: stato reso {row[position]!r}, "
                               f"registro corrente {status!r}")
                elif status == "open":
                    check.fail(CODE_PROMOTED, ref,
                               f"la condizione {ref} e' APERTA ma e' resa "
                               f"{row[position]!r}")


def check_disclosures(document, check, markdown):
    """`XS-11`: ogni disclosure obbligatoria e' presente e NOMINATA nella
    resa. In impact il documento e' un'istantanea: solo coerenza interna."""
    body = gen(document)
    declared = body.get("disclosures") or {}
    if check.phase in ("build", "egress"):
        room = check.inputs.room()
        plan = (check.inputs.stages.get(S10) or {}).get("financial_plan") or {}
        request = (check.inputs.stages.get(S11) or {}).get(
            "funding_request") or {}
        drift = list(declared.get("register_drift_since_data_room") or [])
        expected = expected_disclosures(check.inputs, room, plan, request,
                                        drift)
        for key, value in expected.items():
            if key == "register_drift_since_data_room":
                continue
            if json.dumps(plain(declared.get(key)), sort_keys=True) != \
                    json.dumps(plain(value), sort_keys=True):
                check.fail(CODE_DISCLOSURE, f"disclosures.{key}",
                           f"la disclosure {key} non e' completa o non e' "
                           "quella degli stage a monte")
    if declared.get("final_review") != "not_performed":
        check.fail(CODE_DISCLOSURE, "final_review",
                   "la review finale non e' dichiarata non eseguita")
    if not isinstance(markdown, str):
        return
    summary = chapter_text(markdown, 1)
    appendix = chapter_text(markdown, 17)
    for item in declared.get("open_conditions") or ():
        ref = item.get("condition_id") if isinstance(item, dict) else item
        if ref not in summary:
            check.fail(CODE_DISCLOSURE, ref,
                       f"la condizione aperta {ref} non e' NOMINATA "
                       "nell'executive summary")
    for key in ("unsupported_claims", "contested_claims"):
        for ref in declared.get(key) or ():
            if ref not in summary:
                check.fail(CODE_DISCLOSURE, ref,
                           f"il claim {ref} ({key}) non e' NOMINATO "
                           "nell'executive summary")
    for ref in declared.get("data_room_conflicts") or ():
        if ref not in appendix:
            check.fail(CODE_DISCLOSURE, ref,
                       f"l'incoerenza {ref} non e' nominata in appendice")
    for item in declared.get("data_room_gaps") or ():
        if isinstance(item, dict) and str(item.get("ref")) not in appendix:
            check.fail(CODE_DISCLOSURE, item.get("ref"),
                       f"la lacuna {item.get('ref')} non e' nominata in "
                       "appendice")
    for item in declared.get("funding_residual", {}).get(
            "unresolved_validation_items") or ():
        if isinstance(item, dict) and str(item.get("code")) not in summary:
            check.fail(CODE_DISCLOSURE, item.get("code"),
                       "voce non risolta della richiesta non nominata")
    for path in declared.get("register_drift_since_data_room") or ():
        if path not in appendix:
            check.fail(CODE_DISCLOSURE, path,
                       f"il drift di {path} non e' divulgato in appendice")


def chapter_text(markdown, number):
    out = []
    inside = False
    for line in markdown.split("\n"):
        if line.startswith("## "):
            inside = line.startswith(f"## {number}. ")
            continue
        if inside:
            out.append(line)
    return "\n".join(out)


def check_inputs(document, check):
    """`inputs[]` coincide con gli ingressi letti ORA: impronte e
    corrispondenza con la Data Room."""
    declared = {item.get("path"): item for item in gen(document).get("inputs")
                or () if isinstance(item, dict)}
    for rel, item in declared.items():
        current = check.inputs.sha.get(rel)
        if current is None:
            if check.phase == "impact":
                continue
            check.fail(CODE_INPUT_MISSING, rel, f"ingresso {rel!r} dichiarato "
                                                "ma assente")
            continue
        if current == item.get("sha256"):
            continue
        message = (f"{rel!r}: impronta dichiarata sha256:"
                   f"{str(item.get('sha256'))[:12]}, corrente sha256:"
                   f"{current[:12]}")
        if mutable(rel):
            check.warn(CODE_INPUT_STALE, rel, message)
        else:
            check.fail(CODE_INPUT_STALE, rel, message)
    if check.phase == "impact":
        check.report.add_check(
            "impact_out_of_view_inputs", "NOT_APPLICABLE",
            message="i derivati degli Stage 10-12 sono fuori dalla validation "
                    "view del Transaction Manager: la loro impronta e' "
                    "verificata in egress, al --build e al --publish")


def check_secrets(document, check, handoff, markdown):
    for label, text in ((SELF_REL, semantic_text(document)),
                        (f"{STAGE13}/{HANDOFF_NAME}", handoff),
                        (OUTPUT_REL, markdown)):
        if text is None:
            continue
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                check.fail(CODE_SECRET, label,
                           f"{name} in un artefatto GENERATO: {label}")


def validate_document(document, check, raw=None, handoff=None):
    """I controlli INTRINSECI del canonico: gli stessi al --build, in egress,
    in impact e al --publish (con le differenze dichiarate di fase)."""
    if raw is not None and raw not in (canonical_json(document),
                                       transaction_form(document)):
        check.fail(CODE_NONDETERMINISTIC, "serializzazione",
                   "il canonico non e' nella forma deterministica (chiavi "
                   "ordinate, indentazione 2, newline finale)")
    schema_valid = check_schema(document, check)
    try:
        identity = gen(document).get("identity") or {}
        if identity.get("payload_sha256") != identity_of(document):
            check.fail(CODE_NONDETERMINISTIC, "identity",
                       "l'identita' dichiarata non e' l'impronta del payload")
        check_chapters(document, check)
        check_bindings(document, check)
        check_blocks(document, check)
        check_claims(document, check)
        check_conditions(document, check)
        check_inputs(document, check)
        markdown = render_markdown(document)
        rendering = gen(document).get("rendering") or {}
        if rendering.get("markdown_sha256") != sha256_bytes(
                markdown.encode("utf-8")):
            check.fail(CODE_NONDETERMINISTIC, "rendering",
                       "rendering.markdown_sha256 non e' l'impronta della "
                       "resa del canonico")
        for code, ref, message in markdown_problems(markdown, document):
            check.fail(code, ref, message)
        check_disclosures(document, check, markdown)
        if check.phase in ("egress", "build"):
            if handoff != render_handoff(document):
                check.fail(CODE_NONDETERMINISTIC, f"{STAGE13}/{HANDOFF_NAME}",
                           "l'handoff canonico e' assente o non e' la resa "
                           "deterministica del canonico")
        check_secrets(document, check, handoff, markdown)
        if check.phase == "impact":
            check.report.add_check(
                "impact_handoff_and_output", "NOT_APPLICABLE",
                message="handoff e derivato output/business-plan.md sono "
                        "fuori dalla validation view: la loro resa e' "
                        "verificata in egress e al --publish")
    except (KeyError, IndexError, TypeError, AttributeError, ValueError) \
            as exc:
        if schema_valid:
            raise
        check.fail(CODE_STRUCTURE, "$",
                   "il canonico non e' conforme allo schema e i controlli "
                   f"semantici non sono eseguibili ({type(exc).__name__}): "
                   "respinto, fail-closed")


def read_canonical(path, lexical_form=False):
    raw = Path(path).read_text(encoding="utf-8")
    return raw, strict_loads(raw, lexical=lexical_form)


# --------------------------------------------------------------------------
# PUBBLICATORE ATOMICO
# --------------------------------------------------------------------------


def publish(targets, guard):
    """Livello 1: temporanei nella STESSA directory, `fsync`; livello 2:
    `os.replace`. Un fallimento a qualunque punto ripristina i byte
    precedenti e rimuove i temporanei. `guard` ri-verifica il contenimento
    PRIMA della directory, DOPO la sua creazione e prima di `os.replace`."""
    staged = []
    backups = {}
    published = []
    try:
        for path, text in targets:
            target = Path(path)
            guard(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            guard(target)
            backups[target] = target.read_bytes() if target.is_file() \
                else None
            handle = tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n",
                dir=str(target.parent), prefix=".dg-", suffix=".part",
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


def refuse(report, errors):
    for code, ref, message in errors:
        report.add_error(code, ref=ref, message=message)
    print(report.to_json())
    return fw.EXIT_CANDIDATE_INVALID


# --------------------------------------------------------------------------
# COSTRUZIONE — `--build`
# --------------------------------------------------------------------------


def run_build(project, tx):
    """Modalita' COSTRUZIONE. NON e' il percorso del Transaction Manager."""
    report = fw.Report(VALIDATOR_NAME, STAGE13, "build")
    project = Path(project)
    if not project.is_dir():
        raise fw.ValidatorUsageError(f"project dir inesistente: {project}")
    if not tx:
        raise fw.ValidatorUsageError("--tx obbligatorio in modalita' --build")
    reason = tx_reason(tx)
    if reason:
        return refuse(report, [(CODE_PATH_ESCAPE, "--tx", reason)])
    area = f"{STAGE13}/{WORKING_DIR}/{tx}/"
    rels = {"proposal": area + PROPOSAL_NAME, "canonical": area + CANONICAL_NAME,
            "handoff": area + HANDOFF_NAME}
    for rel in rels.values():
        _target, reason = area_target(project, rel, f"{STAGE13}/")
        if reason:
            return refuse(report, [(CODE_PATH_ESCAPE, rel, reason)])
    config = fw.load_config()

    def guard(path):
        rel = Path(path).relative_to(project).as_posix()
        _target, why = area_target(project, rel, area)
        if why:
            raise BuildRefusal([(CODE_PATH_ESCAPE, rel, why)])
    try:
        before = project_fingerprint(project, (area,))
        candidate = project.joinpath(STAGE13, WORKING_DIR, tx)
        proposal, errors = read_proposal(candidate)
        if errors:
            return refuse(report, errors)
        inputs = Inputs(project, config, "build")
        document = build_document(inputs, proposal)
        raw = canonical_json(document)
        handoff = render_handoff(document)
        check = Check(inputs, fw.Report(VALIDATOR_NAME, STAGE13, "build"),
                      "build")
        validate_document(strict_loads(raw, lexical=False), check, raw=raw,
                          handoff=handoff)
        after = project_fingerprint(project, (area,))
        if after != before:
            changed = sorted(rel for rel in set(before) | set(after)
                             if before.get(rel) != after.get(rel))
            return refuse(report, [(CODE_UPSTREAM, rel,
                                    f"{rel!r} NON e' byte-identico dopo la "
                                    "costruzione: lo Stage 13 assembla, non "
                                    "riscrive") for rel in changed])
        if check.report.errors:
            return refuse(report, [(item["code"], item.get("ref"),
                                    item.get("message"))
                                   for item in check.report.errors])
        for item in check.report.warnings:
            report.add_warning(item["code"], ref=item.get("ref"),
                               message=item.get("message"))
        for path in document["document_generation"]["disclosures"][
                "register_drift_since_data_room"]:
            report.add_warning(CODE_INPUT_STALE, ref=path,
                               message=f"{path} modificato dopo la Data Room: "
                                       "WARNING divulgato nel documento "
                                       "(XS-03)")
        publish([(project.joinpath(rels["canonical"]), raw),
                 (project.joinpath(rels["handoff"]), handoff)], guard)
    except BuildRefusal as exc:
        return refuse(report, exc.errors)
    except fw.CanonicalStateError as exc:
        report.add_error("corrupted_state", message=str(exc))
        print(report.to_json())
        return fw.EXIT_STATE
    report.add_check("document_built", "PASS",
                     message=f"pubblicato il candidate {area}"
                             f"{{{CANONICAL_NAME}, {HANDOFF_NAME}}}")
    print(report.to_json())
    return fw.EXIT_OK


# --------------------------------------------------------------------------
# PUBBLICAZIONE — `--publish`
# --------------------------------------------------------------------------


def run_publish(project):
    """Il derivato `output/business-plan.md`, SOLO con il predicato terminale
    vero, dalla resa del canonico COMMITTATO."""
    report = fw.Report(VALIDATOR_NAME, STAGE13, "publish")
    project = Path(project)
    if not project.is_dir():
        raise fw.ValidatorUsageError(f"project dir inesistente: {project}")
    config = fw.load_config()
    own = (OUTPUT_DIR + "/",)
    target, reason = area_target(project, OUTPUT_REL, OUTPUT_DIR + "/")
    if reason:
        return refuse(report, [(CODE_PATH_ESCAPE, OUTPUT_REL, reason)])

    def guard(path):
        rel = Path(path).relative_to(project).as_posix()
        _target, why = area_target(project, rel, OUTPUT_DIR + "/")
        if why:
            raise BuildRefusal([(CODE_PATH_ESCAPE, rel, why)])
    try:
        before = project_fingerprint(project, own)
        inputs = Inputs(project, config, "publish")
        if any(code == CODE_CHAIN for code, _, _ in inputs.errors):
            return refuse(report, [item for item in inputs.errors
                                   if item[0] == CODE_CHAIN])
        canonical = project / SELF_REL
        if not canonical.is_file():
            raise fw.CanonicalStateError(
                f"{STAGE13} e' completato ma {SELF_REL} e' ASSENTE")
        try:
            raw, document = read_canonical(canonical)
        except ValueError as exc:
            raise fw.CanonicalStateError(f"{SELF_REL} corrotto: {exc}")
        check = Check(inputs, fw.Report(VALIDATOR_NAME, STAGE13, "publish"),
                      "publish")
        validate_document(document, check, raw=raw)
        for code, ref, message in inputs.errors:
            check.fail(code, ref, message)
        if check.report.errors:
            return refuse(report, [(item["code"], item.get("ref"),
                                    item.get("message"))
                                   for item in check.report.errors])
        for item in check.report.warnings:
            report.add_warning(item["code"], ref=item.get("ref"),
                               message=item.get("message"))
        markdown = render_markdown(document)
        if target.is_file():
            if target.read_bytes() == markdown.encode("utf-8"):
                report.add_check("output_current", "PASS",
                                 message=f"{OUTPUT_REL} e' gia' la resa del "
                                         "canonico committato: nessuna "
                                         "scrittura")
                print(report.to_json())
                return fw.EXIT_OK
            return refuse(report, [(CODE_OUTPUT_STALE, OUTPUT_REL,
                                    f"{OUTPUT_REL} esiste e NON e' la resa del "
                                    "canonico committato: il file non e' "
                                    "toccato; riportare al founder")])
        publish([(target, markdown)], guard)
        after = project_fingerprint(project, own)
        if after != before:
            changed = sorted(rel for rel in set(before) | set(after)
                             if before.get(rel) != after.get(rel))
            return refuse(report, [(CODE_UPSTREAM, rel,
                                    f"{rel!r} cambiato durante --publish")
                                   for rel in changed])
    except BuildRefusal as exc:
        return refuse(report, exc.errors)
    except fw.CanonicalStateError as exc:
        report.add_error("corrupted_state", message=str(exc))
        print(report.to_json())
        return fw.EXIT_STATE
    report.add_check("output_published", "PASS",
                     message=f"pubblicato {OUTPUT_REL}, sha256 = "
                             "rendering.markdown_sha256")
    print(report.to_json())
    return fw.EXIT_OK


# --------------------------------------------------------------------------
# VALIDAZIONE — ingresso dal Transaction Manager
# --------------------------------------------------------------------------


def read_text(path):
    return Path(path).read_text(encoding="utf-8") if Path(path).is_file() \
        else None


def run_egress(args, config, report):
    """EGRESS: controlli intrinseci del candidate e RICOSTRUZIONE completa
    dagli ingressi e dalla proposta, con confronto byte per byte."""
    inputs = Inputs(args.project, config, "egress")
    candidate = Path(args.candidate)
    path = candidate / CANONICAL_NAME
    if not path.is_file():
        report.add_error(CODE_STRUCTURE, CANONICAL_NAME,
                         "il candidate non porta il canonico dello Stage 13")
        return
    try:
        raw, document = read_canonical(path)
    except (UnicodeDecodeError, ValueError) as exc:
        report.add_error(CODE_STRUCTURE, CANONICAL_NAME,
                         f"il canonico non e' JSON stretto: {exc}")
        return
    if not isinstance(document, dict):
        report.add_error(CODE_STRUCTURE, CANONICAL_NAME,
                         "il canonico non e' un oggetto JSON")
        return
    handoff = read_text(candidate / HANDOFF_NAME)
    check = Check(inputs, report, "egress")
    for code, ref, message in inputs.errors:
        check.fail(code, ref, message)
    validate_document(document, check, raw=raw, handoff=handoff)
    proposal, errors = read_proposal(candidate)
    for code, ref, message in errors:
        check.fail(code, ref, message)
    if proposal is None or inputs.errors:
        return
    try:
        expected = build_document(inputs, proposal)
    except BuildRefusal as exc:
        for code, ref, message in exc.errors:
            check.fail(code, ref, message)
        return
    if canonical_json(document) != canonical_json(expected):
        differing = sorted(key for key in set(gen(document)) |
                           set(gen(expected))
                           if json.dumps(gen(document).get(key),
                                         sort_keys=True) !=
                           json.dumps(gen(expected).get(key), sort_keys=True))
        check.fail(CODE_NONDETERMINISTIC, "rebuild",
                   "il candidate NON e' la derivazione deterministica degli "
                   f"ingressi e della proposta: differiscono {differing}")
    if handoff != render_handoff(expected):
        check.fail(CODE_NONDETERMINISTIC, f"{STAGE13}/{HANDOFF_NAME}",
                   "l'handoff del candidate non e' quello della ricostruzione")


def run_impact(args, config, report):
    """IMPACT sulla validation view: il documento e' un'istantanea datata;
    i valori di registro mutati sono WARNING, mai FAIL."""
    status = fw.parse_front_matter(
        Path(args.project).joinpath(STATUS_REL).read_text(encoding="utf-8")) \
        if Path(args.project).joinpath(STATUS_REL).is_file() else {}
    completed = STAGE13 in (status.get("completed_stages") or [])
    path = Path(args.project) / SELF_REL
    if not path.is_file():
        if completed:
            raise fw.CanonicalStateError(
                f"{STAGE13} e' in completed_stages ma {SELF_REL} e' ASSENTE")
        report.add_check(
            "impact_canonical_absent", "NOT_APPLICABLE",
            message=f"{SELF_REL} assente e {STAGE13} non completato: nessuno "
                    "stato canonico del documento finale da proteggere")
        return
    try:
        raw, document = read_canonical(path)
    except (UnicodeDecodeError, ValueError) as exc:
        if completed:
            raise fw.CanonicalStateError(f"{SELF_REL} corrotto: {exc}")
        report.add_error(CODE_STRUCTURE, SELF_REL,
                         f"il canonico non e' JSON stretto: {exc}")
        return
    if not isinstance(document, dict):
        report.add_error(CODE_STRUCTURE, SELF_REL,
                         "il canonico non e' un oggetto JSON")
        return
    inputs = Inputs(args.project, config, "impact")
    check = Check(inputs, report, "impact")
    for code, ref, message in inputs.errors:
        if code in (CODE_INPUT_MISSING,):
            continue
        check.fail(code, ref, message)
    validate_document(document, check, raw=raw)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    pre = argparse.ArgumentParser(prog=VALIDATOR_NAME, add_help=False)
    pre.add_argument("--build", action="store_true")
    pre.add_argument("--publish", action="store_true")
    pre.add_argument("--tx")
    try:
        known, rest = pre.parse_known_args(argv)
    except SystemExit:
        print(f"{VALIDATOR_NAME}: argomenti CLI non validi", file=sys.stderr)
        return fw.EXIT_USAGE
    if known.build or known.publish:
        mode = argparse.ArgumentParser(prog=VALIDATOR_NAME, add_help=False)
        mode.add_argument("--project")
        try:
            args, unknown = mode.parse_known_args(rest)
        except SystemExit:
            print(f"{VALIDATOR_NAME}: argomenti CLI non validi",
                  file=sys.stderr)
            return fw.EXIT_USAGE
        if unknown or not args.project or (known.build and known.publish) or \
                (known.publish and known.tx):
            print(f"{VALIDATOR_NAME}: --build ammette SOLO --project e --tx; "
                  f"--publish SOLO --project (non riconosciuti: {unknown})",
                  file=sys.stderr)
            return fw.EXIT_USAGE
        try:
            if known.build:
                return run_build(args.project, known.tx)
            return run_publish(args.project)
        except fw.ValidatorUsageError as exc:
            print(f"{VALIDATOR_NAME}: {exc}", file=sys.stderr)
            return fw.EXIT_USAGE
    if known.tx:
        print(f"{VALIDATOR_NAME}: --tx e' ammesso solo con --build",
              file=sys.stderr)
        return fw.EXIT_USAGE

    def check_fn(args, config, state, report):
        del state
        if args.stage != STAGE13:
            raise fw.ValidatorUsageError(
                f"stage non pertinente a {VALIDATOR_NAME}: {args.stage} "
                f"(atteso {STAGE13})")
        if args.phase not in SUPPORTED_PHASES:
            raise fw.ValidatorUsageError(
                f"--phase non ammessa per {VALIDATOR_NAME}: {args.phase} "
                f"(ammesse: {SUPPORTED_PHASES})")
        if args.phase == "egress":
            run_egress(args, config, report)
        else:
            run_impact(args, config, report)

    fw.run_validator(VALIDATOR_NAME, check_fn, rest)
    return fw.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
