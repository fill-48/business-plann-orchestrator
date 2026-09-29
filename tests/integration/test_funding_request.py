#!/usr/bin/env python3
"""T-FUNDING-REQUEST — i VENTISETTE contratti della Funding Request (Stage 11).

Modulo di test dello Stage 11, costruito sullo stesso modello di
`tests/integration/test_fin_output.py` e `tests/integration/test_fin_tx.py`.
Entra nel glob di ENTRAMBI i runner (`tests/run-tests.ps1` e
`tests/run-tests.sh` globano `tests/integration/test_*.py`) senza alcuna
modifica ai runner.

NESSUNA UCCISIONE PER ECCEZIONE. Un `ImportError` o un
`FileNotFoundError` identico per ventisette contratti non e' evidenza RED:
non distingue un contratto dall'altro. Ogni contratto porta percio' la propria
CONSTATAZIONE ATTRIBUITA, dichiarata nel registro sotto `observation`, e
`run_one` la usa quando la superficie di produzione e' assente. Ogni riga RED
ha la forma

    RED  FR-C-05  reason=<constatazione ATTRIBUITA al contratto>

e MAI `reason=ImportError`.

I VENTISETTE CONTRATTI DEL CATALOGO
-----------------------------------
    FR-C-01  T-FR-CANONICAL-ONLY-SOURCE      MUT-11-01
    FR-C-02  T-FR-INPUT-COMPLETENESS         MUT-11-02
    FR-C-03  T-FR-POLICY-DECLARED            MUT-11-03
    FR-C-04  T-FR-CAPITAL-RECONCILIATION     MUT-11-04
    FR-C-05  T-FR-ALLOCATION-SUM             MUT-11-05
    FR-C-06  T-FR-PERCENTAGE-SUM             MUT-11-06
    FR-C-07  T-FR-CATEGORY-TRACEABILITY      MUT-11-07
    FR-C-08  T-FR-HORIZON-MATCH              MUT-11-08
    FR-C-09  T-FR-RUNWAY-BEFORE              MUT-11-09
    FR-C-10  T-FR-RUNWAY-AFTER               MUT-11-10
    FR-C-11  T-FR-MILESTONE-COSTED           MUT-11-11
    FR-C-12  T-FR-MILESTONE-IN-ROADMAP       MUT-11-12
    FR-C-13  T-FR-TRANCHE-SUPPORT            MUT-11-13
    FR-C-14  T-FR-SCENARIO-IDS               MUT-11-14
    FR-C-15  T-FR-SCENARIO-NOT-FABRICATED    MUT-11-15
    FR-C-16  T-FR-RESIDUAL-GAP-DISCLOSED     MUT-11-16
    FR-C-17  T-FR-NO-INVENTED-TERMS          MUT-11-17
    FR-C-18  T-FR-DECISION-NEEDED            MUT-11-18
    FR-C-19  T-FR-NO-ASSUMPTION-PROMOTED     MUT-11-19
    FR-C-20  T-FR-NO-FALSE-PRECISION         MUT-11-20
    FR-C-21  T-FR-PROVENANCE-TOTAL           MUT-11-21
    FR-C-22  T-FR-TRIANGULAR-CONSISTENCY     MUT-11-22
    FR-C-23  T-FR-UNRESOLVED-ITEMS           MUT-11-23
    FR-C-24  T-FR-NARRATIVE-TRACED           MUT-11-24
    FR-C-25  T-FR-DETERMINISM                MUT-11-25
    FR-C-26  T-FR-ATOMIC-OUTPUT              MUT-11-26
    FR-C-27  T-FR-NO-FINDING-CLOSED          MUT-11-27

`FR-C-27` e' nel catalogo ma non ha un caso eseguibile nel registro
`CONTRACTS`: il modulo ne esegue ventisei, e `closure_claims` e' il solo
helper predisposto per quel contratto.

SEMANTICA MISURATA QUI: la funding request e' una PROIEZIONE sul canonico
dello Stage 10, non un secondo motore finanziario. Ogni fixture nasce dalla
PIPELINE DI PRODUZIONE dello Stage 10 — motore, costruttore canonico,
renderer del capitolo, exporter del workbook — su progetti TEMPORANEI.
Nessun progetto REALE e' toccato e nessun artefatto di runtime resta nel
checkout.

Exit code del modulo: 0 tutti GREEN | 1 almeno un RED | 2 errore d'uso |
3 difetto di PREPARAZIONE dell'harness (non e' evidenza RED).
"""
import argparse
import hashlib
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from decimal import Decimal
from pathlib import Path

SKILL_REL = ".claude/skills/business-plan-orchestrator"
TESTKIT_REL = "tests/integration"

XLSX_HARNESS = "test_fin_xlsx"

FR_VALIDATOR_REL = f"{SKILL_REL}/validators/validate_funding_request.py"
FR_SCHEMA_REL = f"{SKILL_REL}/schemas/funding-request.schema.json"
FR_WORKFLOW_REL = f"{SKILL_REL}/workflows/12_funding-request.md"
FR_METHODOLOGY_REL = f"{SKILL_REL}/methodology/funding-request.md"
FR_AGENT_REL = f"{SKILL_REL}/runtime-agents/funding-strategist.md"
ENFORCEMENT_REL = f"{SKILL_REL}/config/enforcement-config.json"

STAGE10 = "10_financial-plan"
STAGE11 = "11_funding-request"
STAGE12 = "12_data-room"

CANONICAL_NAME = "structured-output.json"
HANDOFF_NAME = "handoff.md"
CHAPTER_NAME = "financial-plan.md"
WORKBOOK_NAME = "financial-model.xlsx"
REQUEST_NAME = "funding-request.md"

TX10 = "tx-m5b-001"
TX11 = "tx-s11-001"

EXIT_OK = 0
EXIT_RED = 1
EXIT_USAGE = 2
EXIT_STATE = 3

#: I VENTISEI codici `fr_*` coniati dal catalogo dei contratti, piu' il codice
#: PREESISTENTE `derived_artifact_numeric_mismatch`, riusato VERBATIM per
#: `FR-C-22` e mai ridefinito. Nessun codice fuori da questa tassonomia e'
#: ammesso.
CODE_NON_CANONICAL = "fr_non_canonical_arithmetic"
CODE_INPUT_INCOMPLETE = "fr_input_incomplete"
CODE_POLICY_UNDECLARED = "fr_policy_undeclared"
CODE_CAPITAL_RECON = "fr_capital_reconciliation_failed"
CODE_ALLOCATION_SUM = "fr_allocation_sum_mismatch"
CODE_PERCENTAGE_SUM = "fr_percentage_sum_mismatch"
CODE_CATEGORY = "fr_category_not_traceable"
CODE_HORIZON = "fr_horizon_mismatch"
CODE_RUNWAY_BEFORE = "fr_runway_before_mismatch"
CODE_RUNWAY_AFTER = "fr_runway_after_mismatch"
CODE_MILESTONE_COST = "fr_milestone_not_costed"
CODE_MILESTONE_ROADMAP = "fr_milestone_not_in_roadmap"
CODE_TRANCHE = "fr_tranche_unsupported"
CODE_SCENARIO_ID = "fr_scenario_id_mismatch"
CODE_SCENARIO_FABRICATED = "fr_scenario_fabricated"
CODE_RESIDUAL_GAP = "fr_residual_gap_hidden"
CODE_INVENTED_TERMS = "fr_invented_terms"
CODE_DECISION_NEEDED = "fr_decision_needed_missing"
CODE_ASSUMPTION_PROMOTED = "fr_assumption_promoted"
CODE_FALSE_PRECISION = "fr_false_precision"
CODE_PROVENANCE = "fr_provenance_missing"
CODE_UNRESOLVED_ITEMS = "fr_unresolved_items_suppressed"
CODE_NARRATIVE = "fr_narrative_untraced_value"
CODE_NONDETERMINISTIC = "fr_nondeterministic"
CODE_PARTIAL_OUTPUT = "fr_partial_output"
CODE_FINDING_CLOSED = "fr_finding_closed_without_proof"
CODE_DERIVED_MISMATCH = "derived_artifact_numeric_mismatch"

#: Le SETTE chiavi che `FR-C-17` vieta di INVENTARE. Sono le stesse che lo
#: Stage 10 gia' vieta al proprio canonico
#: (`validate_financial_output.STAGE11_FORBIDDEN_KEYS`): qui sono vietate come
#: valori INVENTATI, non come spazio di nomi.
INVENTABLE_TERMS = ("funding_ask", "instrument", "valuation", "round_size",
                    "ownership", "dilution", "terms")

SCENARIO_IDS = ("base", "downside", "upside")

#: Forma canonica degli id: un id VALIDO per il registro base ma NON nella
#: forma canonica e' RICONOSCIUTO e RESPINTO con codice ATTRIBUITO, mai
#: normalizzato.
NON_CANONICAL_EVD = "EVD-0021"
NON_CANONICAL_SRC = "SRC-0007"
NON_CANONICAL_ASS = "ASS-0001"

EVIDENCE_REGISTER_REL = "shared/evidence-register.json"
SOURCE_REGISTER_REL = "shared/source-register.json"
ASSUMPTIONS_REGISTER_REL = "shared/assumptions-register.json"
PROFILE_REL = "shared/startup-profile.json"
STATUS_REL = "shared/project-status.md"

#: Politica di capitalizzazione — la politica di buffer della fixture a ramo
#: PRIMARIO (`funding_gap_to_buffer`): la STESSA gia' usata dai test del
#: motore in `test_fin_engine.py` per esercitare la soglia di cassa.
BUFFER_POLICY = {"kind": "absolute", "value": 20000}

#: Profilo di avvio DICHIARATO della fixture a profilo PRESENTE: i valori sono
#: quelli del progetto dimostrativo, letti e mai inferiti.
STARTUP_PROFILE = {"startup_type": "saas", "development_stage": "pre_seed",
                   "primary_reader": "business_angel",
                   "funding_type": "equity"}

#: `FR-C-18` — i termini finanziari che lo Stage 11 NON produce restano
#: DECISIONI APERTE dichiarate, ciascuna con il proprio codice: strumento,
#: valutazione pre/post-money, quota e diluizione, dimensione del round,
#: condizioni dell'operazione.
TERM_DECISIONS = ("FR-TERM-CONDITIONS", "FR-TERM-DILUTION",
                  "FR-TERM-INSTRUMENT", "FR-TERM-ROUND-SIZE",
                  "FR-TERM-VALUATION")

#: `FR-C-11` — il collegamento fra capitale e milestone che il canonico
#: NON porta e' una decisione DICHIARATA, mai un vuoto muto.
MILESTONE_DECISION = "FR-MILESTONE-FINANCING"

#: Frase di DICHIARAZIONE del fallback a `funding_gap_to_zero` della
#: politica di capitalizzazione: la richiesta e' costruita A CASSA ZERO.
FALLBACK_DISCLOSURE = "a cassa zero"

#: Codice di schema PREESISTENTE del validator, non coniato qui: un canonico
#: fuori schema e' respinto con QUESTO codice attribuito, mai con un
#: traceback.
CODE_SCHEMA = "fr_schema_invalid"

#: Rese numeriche NON dichiarate che
#: il tracciamento deve RESPINGERE, ciascuna col token che il rifiuto NOMINA.
#: Le migliaia puntate italiane `100.000`, `12.000` e `7.000` hanno lo stesso
#: VALORE `Decimal` dei letterali `100`, `12` e `7` della fixture piena, ma non
#: sono quei numeri: la prosa e' in italiano. `12.0` e' una resa
#: a punto decimale che nessun campo emette: la regola chiusa ammette la SOLA
#: resa dichiarata. `EUR-5000000` non e' un id di un namespace APPROVATO, e
#: `5_000_000` e' un numero a gruppi sottolineati. `EUR5000000`,
#: `EUR_5000000` e `x3` sono cifre INCOLLATE a un prefisso: gli unici
#: identificatori sono gli id approvati e i nomi di stage `NN_`, e nessun
#: altro prefisso sottrae una cifra al controllo.
UNDECLARED_RENDERINGS = (
    ("migliaia-100", "La valutazione pre-money e' di 100.000 EUR.", "100.000"),
    ("migliaia-12", "Il round e' di 12.000 EUR.", "12.000"),
    ("migliaia-7", "Diluizione su 7.000 azioni.", "7.000"),
    ("resa-12.0", "Il runway finanziato e' di 12.0 periodi.", "12.0"),
    ("id-non-approvato", "Pre-money EUR-5000000.", "5000000"),
    ("cifre-sottolineate", "Pre-money 5_000_000 EUR.", "5_000_000"),
    ("cifre-incollate", "Pre-money EUR5000000.", "5000000"),
    ("cifre-dopo-sottolineato", "Pre-money EUR_5000000.", "5000000"),
    ("moltiplicatore", "Ritorno atteso x3 sul capitale.", "3"),
)

#: I letterali della fixture piena di cui le migliaia puntate sono
#: VALORE-equivalenti: se la fixture non li dichiarasse, la sonda
#: respingerebbe per la ragione sbagliata e non misurerebbe nulla.
THOUSANDS_TWINS = ("100", "12", "7")

#: Identificatori che RISOLVONO sulla fixture
#: piena, e soltanto quelli: la politica che `policy_ref` nomina
#: (`FR-CAPITAL-POLICY`), un driver che `use_of_proceeds[].driver_refs` riferisce
#: (`DRV-007`), una voce del registro ufficiale delle assunzioni (`ASS-001`),
#: una sezione che la narrativa conia (`FR-S3`), un codice di decisione
#: (`FR-TERM-VALUATION`) e due stage di `stage_order`. La forma del namespace
#: da sola non maschera nulla: gli id della fixture RICCA (roadmap e
#: registri popolati) sono provati da `registered_ids_probes`.
REGISTERED_IDS_PROSE = ("Riferimenti registrati: FR-CAPITAL-POLICY, DRV-007, "
                        "ASS-001, "
                        "FR-S3, FR-TERM-VALUATION; stage 10_financial-plan e "
                        "11_funding-request.")

#: Rese QUALIFICATE da una grandezza. Sulla
#: fixture piena `100`, `12` e `7` sono dichiarati (`THOUSANDS_TWINS`), ma
#: «100 mila», «12K» o «7M» non sono quei numeri: la resa qualificata e' una
#: resa DISTINTA, che nessun campo emette, e il rifiuto la NOMINA intera.
MAGNITUDE_RENDERINGS = (
    ("grandezza-100-mila", "La valutazione pre-money e' di 100 mila EUR.",
     "100 mila"),
    ("grandezza-12-mila", "Il round e' di 12 mila EUR.", "12 mila"),
    ("grandezza-100k", "Pre-money 100k EUR.", "100k"),
    ("grandezza-12K", "Round da 12K EUR.", "12K"),
    ("grandezza-7M", "Pre-money 7M EUR.", "7M"),
    ("grandezza-100-milioni", "La valutazione e' di 100 milioni di EUR.",
     "100 milioni"),
    ("grandezza-12-mln", "Round da 12 mln EUR.", "12 mln"),
    ("grandezza-100mila", "Pre-money 100mila EUR.", "100mila"),
)

#: Cifre decimali Unicode NON ASCII (categoria
#: `Nd`): a larghezza piena e arabo-indiane. Non sono invisibili: sono token, e
#: nessun letterale dichiarato ne e' la resa.
FULLWIDTH_DIGITS = "５" + "０" * 7
ARABIC_INDIC_DIGITS = "٥" + "٠" * 6
UNICODE_DIGIT_RENDERINGS = (
    ("cifre-larghezza-piena", f"Pre-money {FULLWIDTH_DIGITS} EUR.",
     FULLWIDTH_DIGITS),
    ("cifre-arabo-indiane", f"Pre-money {ARABIC_INDIC_DIGITS} EUR.",
     ARABIC_INDIC_DIGITS),
)

#: La regola «maschera SOLO cio' che risolve»
#: vale per OGNI esclusione per forma. Una cifra seguita da `_` non e' un nome
#: di stage per costruzione (`5000000_EUR`, `99_milioni`): lo e' soltanto un
#: nome ESATTO di `stage_order`.
SHAPE_RENDERINGS = (
    ("suffisso-sottolineato", "Pre-money 5000000_EUR.", "5000000"),
    ("nome-di-stage-fittizio", "Pre-money 99_milioni EUR.", "99"),
)

#: Fronte del solo derivato — la riga del
#: checksum non e' saltata per il suo PREFISSO: e' rimosso il solo checksum
#: DICHIARATO, e ogni altra cifra della riga resta un token.
CHECKSUM_LINE_PROBE = ("riga-checksum",
                       "- `canonical_source_checksum`: pre-money 5000000 EUR.",
                       "5000000")

#: Le rese ESATTE dei letterali dichiarati `12`, `7` e `100` restano accettate:
#: il rifiuto delle rese qualificate non tocca la resa legittima.
EXACT_RENDERINGS_PROSE = ("Orizzonte di 12 periodi, runway di 7 periodi, "
                          "impiego al 100%.")

#: L'exploit di riferimento del tracciamento degli id: cifre nascoste dentro
#: id della forma di un namespace approvato ma fabbricati.
TF01_EXPLOIT = ("La valutazione pre-money e' di MIL-5000000 EUR, a fronte di una "
                "diluizione FR-DILUIZIONE-20.")

#: Id della FORMA di un namespace approvato ma
#: FABBRICATI: nessun registro, nessun canonico e nessun codice coniato li
#: dichiara. La forma non li maschera: le loro cifre restano token, e il
#: rifiuto le NOMINA.
FABRICATED_ID_PROBES = (
    ("MIL-5000000", "La valutazione pre-money e' di MIL-5000000 EUR.",
     ("5000000",)),
    ("FR-5000000", "La valutazione pre-money e' di FR-5000000 EUR.",
     ("5000000",)),
    ("EVD-5000000", "Pre-money EVD-5000000 EUR.", ("5000000",)),
    ("DEC-5000000", "Pre-money DEC-5000000 EUR.", ("5000000",)),
    ("DRV-5000000", "Pre-money DRV-5000000 EUR.", ("5000000",)),
    ("MIL-999", "La milestone MIL-999 e' finanziata dal capitale richiesto.",
     ("999",)),
    ("FR-DILUIZIONE-20", "La diluizione e' FR-DILUIZIONE-20.", ("20",)),
    ("exploit", TF01_EXPLOIT, ("5000000", "20")),
)

#: Gli id che la fixture RICCA deve dichiarare, perche' il positivo sugli id
#: provi davvero OGNI sorgente di risoluzione e non sia vacuo.
REQUIRED_REGISTERED_IDS = ("MIL-001", "MIL-003", "EVD-001", "SRC-001",
                           "ASS-001", "DRV-007", "FR-S3", "FR-CAPITAL-POLICY",
                           "10_financial-plan")

#: ESPRESSIONI numeriche
#: complete, come le vede il lettore, che nessun letterale dichiarato rende.
#: Sulla fixture piena `12`, `100` e `7` sono dichiarati (`THOUSANDS_TWINS`):
#: ciascuna riga prova che le cifre di un'espressione MATERIALMENTE DISTINTA
#: non la tracciano, qualunque sia la posizione del qualificatore (prima o
#: dopo le cifre), il separatore (spazio, NBSP, a capo, `_`, `-`), la
#: formattazione Markdown o HTML che lo separa, o la composizione di piu'
#: gruppi di cifre dichiarati in un numerale nuovo. Forma di ogni riga:
#: `(etichetta, prosa, nucleo)`: il rifiuto NOMINA il nucleo numerico
#: dell'espressione (`repr`), che per un numerale composto e' il numerale
#: intero. Non e' un elenco di stringhe vietate: e' un campione della CLASSE,
#: e la proprieta' misurata e' «nessuna di queste rese e' tracciata».
EXPRESSION_RENDERINGS = (
    ("prefisso-EUR-mln", "La valutazione pre-money e' di EUR mln 12.", "12"),
    ("prefisso-EUR-milioni", "Pre-money EUR milioni 12.", "12"),
    ("prefisso-k-euro", "Pre-money k\u20ac 100.", "100"),
    ("prefisso-K-EUR", "Pre-money K EUR 100.", "100"),
    ("prefisso-M-euro", "Pre-money M\u20ac 7.", "7"),
    ("prefisso-mln-di-EUR", "Pre-money mln di EUR 12.", "12"),
    ("sottolineato", "Pre-money 100_mila EUR.", "100"),
    ("trattino", "Pre-money 100-mila EUR.", "100"),
    ("grassetto-grandezza", "Pre-money 100 **mila** EUR.", "100"),
    ("grassetto-cifre", "Pre-money **100** mila EUR.", "100"),
    ("corsivo", "Pre-money 100 *mila* EUR.", "100"),
    ("codice", "Pre-money `100` mila EUR.", "100"),
    ("nbsp", "Pre-money 100\u00a0mila EUR.", "100"),
    ("entita-html", "Pre-money 100&nbsp;mila EUR.", "100"),
    ("tag-html", "Pre-money 100<span> mila</span> EUR.", "100"),
    ("commento-html", "Pre-money 100<!-- --> mila EUR.", "100"),
    ("a-capo", "Pre-money 100\nmila EUR.", "100"),
    ("grandezza-12-mln", "Round da 12 mln EUR.", "12"),
    ("grandezza-100-milioni", "La valutazione e' di 100 milioni di EUR.",
     "100"),
    ("grandezza-100mila", "Pre-money 100mila EUR.", "100"),
    ("grandezza-7M", "Pre-money 7M EUR.", "7"),
    ("composto-spazi", "Pre-money 7 100 100 EUR.", "7 100 100"),
    ("composto-nnbsp", "Pre-money 12\u202f100 EUR.", "12\u202f100"),
    ("composto-apostrofo", "Pre-money 12'100 EUR.", "12'100"),
    ("composto-invisibile", "Pre-money 7\u200b0\u200b0 EUR.",
     "7\u200b0\u200b0"),
    ("esponente-e", "Pre-money 12e8 EUR.", "12e8"),
    ("esponente-E", "Pre-money 12E8 EUR.", "12E8"),
    ("esponente-segno", "Pre-money 12e+8 EUR.", "12e+8"),
    ("potenza", "Pre-money 12 \u00d7 10^8 EUR.", "12 \u00d7 10^8"),
    ("moltiplicazione", "Pre-money 12x7 EUR.", "12x7"),
    ("segno-unicode", "Margine \u221212 EUR.", "\u221212"),
    ("qualificatore-cirillico", "Pre-money 7 \u041c EUR.", "7"),
    # Bypass dell'implementazione: altri nomi di grandezza, numerali composti, grandezze inglesi, per mille
    # scritto, lineette Unicode, testo alternativo di un'immagine, e le
    # divergenze della vista del lettore da CommonMark (commento vuoto, riga
    # di solo tag, voce numerata da un numero diverso da 1, riferimenti a
    # carattere numerici che CommonMark mostra alla lettera).
    ("grandezza-centinaia", "Pre-money 7 centinaia di euro.", "7"),
    ("grandezza-decine", "Pre-money 7 decine di euro.", "7"),
    ("grandezza-centinaia-di-migliaia",
     "Pre-money 7 centinaia di migliaia di euro.", "7"),
    ("composto-centomila", "Pre-money 7 centomila EUR.", "7"),
    ("grandezza-dozzine", "Round di 12 dozzine.", "12"),
    ("grandezza-inglese", "Servono 12 million di euro.", "12"),
    ("grandezza-bln", "Pre-money 12 bln.", "12"),
    ("per-mille-scritto", "Quota di 100 per mille.", "100"),
    ("trattino-figura", "Pre-money 7\u2012mila EUR.", "7"),
    ("lineetta", "Pre-money 7\u2014mila EUR.", "7"),
    ("alt-immagine", "Pre-money 7 ![mila](z) EUR.", "7"),
    ("commento-vuoto",
     "La valutazione pre-money e' di 12<!--> milioni di EUR<!-- -->.", "12"),
    ("riga-di-solo-tag",
     "La valutazione pre-money e' di 12\n<span>\nmilioni di EUR</span>.",
     "12"),
    ("riga-di-solo-tag-composto",
     "La valutazione pre-money e' di 12\n<b>\n100</b> EUR.", "12  100"),
    ("elenco-numerato-non-da-1",
     "La valutazione pre-money e' di EUR mln\n12. Tale valore e' confermato.",
     "12"),
    ("riferimento-numerico-lungo",
     "La valutazione pre-money e' di &#50000000; EUR.", "50000000"),
    ("riferimento-numerico-aperto",
     "La valutazione pre-money e' di &#5000000 EUR.", "5000000"),
    ("riferimento-numerico-in-codice",
     "La valutazione pre-money e' di `&#5000000;` EUR.", "5000000"),
    # Marcatura FRA DUE CIFRE: per il lettore separa (`<br>`, celle, apici),
    # e rimuoverla fabbricherebbe un letterale dichiarato (`10<br>0` -> 100).
    ("a-capo-html-fra-cifre",
     "La diluizione dei soci e' del 10<br>0% dopo il round.", "10 0"),
    ("celle-fra-cifre",
     "<table><tr><td>Diluizione %</td><td>10</td><td>0</td></tr></table>",
     "10 0"),
    ("apice-fra-cifre", "Valutazione 1<sup>2</sup> milioni.", "1\u20632"),
    ("importo-spezzato-da-tag",
     "Valutazione pre-money 2744<br>0.61321581802203258027711 EUR.",
     "2744 0.61321581802203258027711"),
    # Un tag di blocco vale uno spazio, un autolink e un testo fra parentesi
    # angolari che non e' un tag restano visibili, e due punti e parentesi
    # legano le cifre al qualificatore vicino.
    ("tag-di-blocco-dopo-grandezza",
     "La valutazione pre-money e' di 100 mila<br>investiti dai soci.", "100"),
    ("autolink-grandezza", "La valutazione pre-money e' di 100 <mila:euro>.",
     "100"),
    ("parentesi-angolare-testo",
     "La valutazione pre-money e' di 100 <milioni di euro, stima (non > 0).",
     "100"),
    ("due-punti", "Valori in EUR mln: 12.", "12"),
    ("parentesi", "Pre-money 12 (mila).", "12"),
    # Un commento con cifre non spezza la catena fra cifre e grandezza.
    ("commento-con-cifre", "Pre-money 12 <!-- 12 --> mila EUR.",
     "12   12"),
)

#: Caratteri numerici Unicode NON decimali: apici, cifre cerchiate, e una
#: diluizione scritta in apice. Non sono testo
#: invisibile: sono numeri per il lettore, e nessun letterale dichiarato li
#: rende. Le cifre decimali non ASCII restano in
#: `UNICODE_DIGIT_RENDERINGS`.
SUPERSCRIPT_DIGITS = "\u2075" + "\u2070" * 6
CIRCLED_DIGITS = "\u2464" + "\u24ea" * 6
UNICODE_NUMERIC_RENDERINGS = (
    ("apici", f"Pre-money {SUPERSCRIPT_DIGITS} EUR.", SUPERSCRIPT_DIGITS),
    ("cerchiate", f"Pre-money {CIRCLED_DIGITS} EUR.", CIRCLED_DIGITS),
    ("diluizione-in-apice", "Diluizione del \u00b2\u2070%.", "\u00b2\u2070"),
)

#: Positivi ESATTI delle espressioni — la resa dichiarata resta tracciata anche
#: quando la parola che segue NON e' una grandezza, quando e' marcata dalla
#: sola formattazione, o quando tre letterali dichiarati sono citati come
#: TRE numeri distinti (`7 / 100 / 12`, contro il composto `7 100 100`).
EXPRESSION_POSITIVES = (
    "Orizzonte di 12 periodi, runway di 7 periodi, impiego al 100%.",
    "Runway di 12 mesi, sede a 7 Milano, 100 metri, 12 settimane.",
    "Impiego al **100**%, su 12 periodi.",
    "Tre valori dichiarati: 7 / 100 / 12.",
    "Impiego al 100 per cento, su 12 periodi.",
    "Orizzonte di 12 periodi \u2014 runway di 7 periodi &mdash; nessun altro "
    "numero.",
    "Orizzonte di <b>12</b> periodi <!-- nota di redazione -->.",
    "Orizzonte di 12 periodi.\n\n***\n\nRunway: 7 periodi (100% "
    "impiegato).",
    "Fonte: <https://example.org/rapporto>, su 12 periodi.",
)

#: Testi AVVERSARI per il tempo di scansione: migliaia di
#: caratteri invisibili dopo una grandezza, di aperture di commento, di tag
#: fra cifre. La scansione resta lineare (limite largo: 10 s in tutto).
SCAN_TIME_LIMIT_SECONDS = 10
ADVERSARIAL_SCAN_TEXTS = (
    "mln " + "\u200b" * 20000 + "x",
    "<!--" * 20000 + "x",
    "1<!--" * 20000 + "-->",
    "1<b>" * 20000 + "x",
    "7 " + "a" * 40000 + "x",
)

#: Manomissione con numero in chiaro: un numero
#: IN CHIARO, riciclato attraverso campi che il candidate possiede (domanda di
#: decisione, messaggio irrisolto) invece che attraverso un identificatore.
PLAIN_EXPLOIT = ("La valutazione pre-money e' di 5000000 EUR, a fronte di una "
                 "diluizione del 20%.")

#: Espressioni numeriche sul percorso REALE del Transaction Manager: un campione delle
#: rese difficili, sui due fronti insieme.
MAGNITUDE_EXPLOIT = ("La valutazione pre-money e' di EUR mln 12, cioe' "
                     "k\u20ac 100 o 100_mila; il round vale 12e8 EUR e "
                     "7 100 100 EUR.")
MAGNITUDE_EXPLOIT_NAMED = ("12", "100", "12e8", "7 100 100")

#: La grandezza e le sue cifre restano UNA
#: espressione attraverso la punteggiatura ORDINARIA e la struttura locale:
#: il punto dell'abbreviazione, `=`, due punti, parentesi, la virgola davanti
#: a un connettore, prima o dopo le cifre. Sono le forme di riferimento; le
#: varianti vicine, mai viste, le genera
#: `structural_variants`. Nessuna e' una stringa vietata: la proprieta'
#: misurata e' «nessuna grandezza si stacca dalle proprie cifre per un
#: carattere che non e' una parola».
STRUCTURAL_RENDERINGS = (
    ("abbreviazione-col-punto", "La valutazione pre-money e' di EUR mln. 12.",
     "12"),
    ("prefisso-due-punti", "Pre-money EUR mln: 12.", "12"),
    ("etichetta-uguale", "Capitale richiesto (EUR mln) = 12.", "12"),
    ("parentesi-prima", "Pre-money (EUR milioni) 12.", "12"),
    ("virgola-connettore", "Il round vale 12, in milioni di euro.", "12"),
    ("suffisso-due-punti", "Il round vale 12: milioni di euro.", "12"),
    ("suffisso-parentesi", "Il round vale 12 (milioni di euro).", "12"),
    # Varianti vicine delle stesse forme: il connettore ELISO, un codice di
    # valuta, una catena lunga di valute e connettori, il moltiplicatore
    # incollato a un'altra parola, l'abbreviazione col punto davanti alla
    # valuta.
    ("connettore-eliso", "Capitale richiesto (milioni d'euro): 12.", "12"),
    ("codice-valuta", "Capitale richiesto: 12 (US$ mln).", "12"),
    ("catena-lunga",
     "Capitale richiesto in milioni di euro (in EUR): 12.", "12"),
    ("moltiplicatore-incollato", "Valutazione pari a 12×EBITDA.", "12"),
    ("abbreviazione-prima-della-valuta", "Pre-money Mrd. EUR 12.", "12"),
    ("etichetta-a-due-unita",
     "Capitale richiesto e quota ceduta (EUR mln / %): 12 / 20.", "12"),
    ("connettore-eliso-marcato",
     "Capitale richiesto (milioni d'**euro**): 12.", "12"),
    ("abbreviazione-marcata-col-punto", "Pre-money **Mln**. EUR 12.", "12"),
)

#: La marcatura Markdown non spezza
#: un'espressione numerica: mantissa ed esponente (`**12**e8`, e lo span di
#: codice, che la resa del contratto usa come superficie VISIBILE per id e
#: stati), segno e cifre, cifre e grandezza, le lettere di una parola del
#: vocabolario, il link (la destinazione e il titolo non sono testo del
#: paragrafo: parentesi bilanciate, escape, titoli, cifre), l'a capo, la riga
#: numerata dentro una voce di elenco. Sono le forme di riferimento; le
#: varianti le genera `markdown_variants`.
MARKDOWN_RENDERINGS = (
    ("esponente-grassetto", "Il round vale **12**e8 EUR.", "12**e8"),
    ("esponente-corsivo", "Il round vale *12*e8 EUR.", "12*e8"),
    ("esponente-codice", "Il round vale `12`e8 EUR.", "12`e8"),
    ("esponente-grassetto-7e12", "Il round vale **7**e12 EUR.", "7**e12"),
    ("esponente-grassetto-dopo", "Il round vale 12**e8** EUR.", "12**e8"),
    ("esponente-segno", "Il round vale **12**e+8 EUR.", "12**e+8"),
    ("esponente-link", "Il round vale [12](u)e8 EUR.", "12]e8"),
    ("segno-grassetto", "Margine -**12** EUR.", "-**12"),
    ("link-milioni", "Pre-money [12](https://example.com) milioni.", "12"),
    ("link-mila", "Pre-money [100](https://example.com) mila.", "100"),
    ("link-parentesi-con-escape",
     "Pre-money [12](https://it.wikipedia.org/wiki/Euro_\\(valuta\\)) "
     "milioni.", "12"),
    ("link-parentesi-bilanciate",
     "Pre-money [12](https://it.wikipedia.org/wiki/Euro_(valuta)) milioni "
     "di euro.", "12"),
    ("link-titolo", "Pre-money [12](https://fonte.example \"Fonte (ISTAT)\") "
                    "miliardi di euro.", "12"),
    ("link-destinazione-con-cifre", "Pre-money [12](allegato-7.pdf) milioni.",
     "12"),
    ("link-composto", "Pre-money [7](#p0)100 EUR.", "7]100"),
    ("grassetto-cifre-mila", "Pre-money **100** mila.", "100"),
    ("grassetto-mila", "Pre-money 100 **mila**.", "100"),
    ("corsivo-milioni", "Pre-money 12 _milioni_ di euro.", "12"),
    ("a-capo-milioni", "Pre-money 12\nmilioni di euro.", "12"),
    ("a-capo-forzato-milioni", "Pre-money 12  \nmilioni di euro.", "12"),
    ("a-capo-barra-milioni", "Pre-money 12\\\nmilioni di euro.", "12"),
    ("a-capo-html-milioni", "Pre-money 12<br>milioni di euro.", "12"),
    ("parola-spezzata-mila", "Pre-money 100 mi**la** EUR.", "100"),
    ("parola-spezzata-milioni", "Pre-money 12 **mil**ioni di euro.", "12"),
    ("parola-spezzata-riferimento", "Pre-money 100 mi&shy;la EUR.", "100"),
    ("elenco-voce-numerata-interna",
     "\n\n- Importi in EUR mln\n  12. capitale richiesto.", "12"),
    # Varianti vicine: due link adiacenti, una sintassi di link che NON e' un
    # link (parentesi con escape) o che non ha destinazione, l'enfasi a
    # trattino basso sul segno, il numerale composto spezzato.
    ("link-adiacenti",
     "Richiesta: [12](https://a.it)[ milioni di euro](https://b.it).", "12"),
    ("sintassi-di-link-non-link", "Importi \\[in milioni\\](12).", "12"),
    ("link-senza-destinazione", "Richiesta: [12]((in milioni)).", "12"),
    ("segno-trattino-basso", "Il margine e' _-12_ punti.", "-12"),
    ("composto-spezzato", "Richiesta: 12 cen&shy;tomila.", "12"),
    ("parola-spezzata-decine", "Richiesta: 12 **de**cine di migliaia.", "12"),
    # Una sintassi di link REALE accanto a una che non lo e', e una
    # destinazione con una barra rovescia a fine riga: la lettura lessicale
    # resta scandita accanto a quella di CommonMark.
    ("sintassi-di-link-mista", "Capitale in milioni ![](logo.png)](12).",
     "12"),
    ("destinazione-barra-a-capo", "Richiesta: [12](\\\na) milioni.", "12"),
)

#: VARIANTI VICINE, mai viste, generate dai test, nella
#: sola notazione ordinaria di un testo d'affari. Ogni variante e'
#: `(etichetta, prosa, contrassegno)`: il rifiuto deve contenere il
#: contrassegno, cioe' le cifre QUALIFICATE (`cifre '12' qualificate`) o il
#: nucleo che nessun letterale rende (`'12**e8'`).
STRUCTURE_QUALIFIERS = ("mln", "mln.", "Mio.", "Mrd.", "mgl.", "milioni",
                        "milioni di euro", "EUR mln", "EUR mln.", "k€",
                        "mila", "miliardi di EUR")
STRUCTURE_SEPARATORS = (". ", ": ", " = ", ", ", "; ", " / ", " | ",
                        " → ", " » ", " — ", "... ", ") ", " (",
                        " «", "\" ", "' ")
STRUCTURE_TEMPLATES = ("Capitale richiesto ({q}) = 12.",
                       "| Capitale richiesto ({q}) | 12 |",
                       "Il round vale 12 ({q}).", "Il round vale 12, in {q}.",
                       "«{q}» 12.", "[{q}] 12.")
QUALIFIED_12 = "cifre '12' qualificate"


def structural_variants():
    """Grandezza e cifre — qualificatore x separatore x orientamento, e forme di
    etichetta, di tabella e di connettore. Un punto seguito da una parola
    MAIUSCOLA o da una cifra apre una frase NUOVA (`12. Mio.`,
    `milioni. 12`): la scala di un'altra frase e' contesto di documento
    fuori contratto, e la combinazione non e' generata. Il punto
    PROPRIO di un'abbreviazione non apre alcuna frase (`EUR mln. 12`)."""
    for qualifier in STRUCTURE_QUALIFIERS:
        for separator in STRUCTURE_SEPARATORS:
            if not separator.endswith(". ") or (
                    separator == ". " and qualifier in ("mln", "EUR mln")):
                yield (f"prima {qualifier!r} {separator!r}",
                       f"Pre-money {qualifier}{separator}12.", QUALIFIED_12)
            if separator.endswith(". ") and qualifier[:1].isupper():
                continue
            yield (f"dopo {separator!r} {qualifier!r}",
                   f"Il round vale 12{separator}{qualifier}.", QUALIFIED_12)
        for template in STRUCTURE_TEMPLATES:
            yield (f"forma {template!r} {qualifier!r}",
                   template.format(q=qualifier), QUALIFIED_12)


MARKDOWN_MARKS = ("**", "*", "__", "_", "`", "~~")
MARKDOWN_DESTINATIONS = (
    "https://example.com", "https://it.wikipedia.org/wiki/Euro_(valuta)",
    "https://it.wikipedia.org/wiki/Euro_\\(valuta\\)",
    "<https://example.com/a b>", "https://fonte.example \"Fonte (ISTAT)\"",
    "https://fonte.example 'Fonte'", "https://fonte.example (Fonte)",
    "a(b(c(d)))", "allegato-7.pdf")
MARKDOWN_BREAKS = ("\n", "  \n", "\\\n", "<br>", "<br/>\n")


def markdown_variants():
    """Marcatura Markdown — marcatore x posizione di taglio, destinazioni di link x
    forma, a capo x orientamento, voci di elenco."""
    for mark in MARKDOWN_MARKS:
        yield (f"esponente {mark}12{mark}e8",
               f"Il round vale {mark}12{mark}e8 EUR.", f"'12{mark}e8'")
        yield (f"esponente 12{mark}e8{mark}",
               f"Il round vale 12{mark}e8{mark} EUR.", f"'12{mark}e8'")
        yield (f"esponente 12e{mark}8{mark}",
               f"Il round vale 12e{mark}8{mark} EUR.", f"'12e{mark}8'")
        yield (f"segno -{mark}12{mark}", f"Margine -{mark}12{mark} EUR.",
               f"'-{mark}12'")
        yield (f"cifre {mark}12{mark} milioni",
               f"Pre-money {mark}12{mark} milioni.", QUALIFIED_12)
        yield (f"grandezza 12 {mark}milioni{mark}",
               f"Pre-money 12 {mark}milioni{mark}.", QUALIFIED_12)
        yield (f"parola 12 mil{mark}ioni{mark}",
               f"Pre-money 12 mil{mark}ioni{mark}.", QUALIFIED_12)
        yield (f"parola 12 {mark}mil{mark}ioni",
               f"Pre-money 12 {mark}mil{mark}ioni.", QUALIFIED_12)
        yield (f"prefisso {mark}EUR mln{mark} 12",
               f"Pre-money {mark}EUR mln{mark}: 12.", QUALIFIED_12)
    for destination in MARKDOWN_DESTINATIONS:
        yield (f"link grandezza ({destination})",
               f"Pre-money [12]({destination}) milioni.", QUALIFIED_12)
        yield (f"immagine grandezza ({destination})",
               f"Pre-money ![12]({destination}) milioni.", QUALIFIED_12)
        yield (f"link esponente ({destination})",
               f"Il round vale [12]({destination})e8 EUR.", "'12]e8'")
        yield (f"link prefisso ({destination})",
               f"Pre-money [EUR mln]({destination}) 12.", QUALIFIED_12)
    for linebreak in MARKDOWN_BREAKS:
        yield (f"a capo dopo {linebreak!r}",
               f"Pre-money 12{linebreak}milioni di euro.", QUALIFIED_12)
        yield (f"a capo prima {linebreak!r}",
               f"Pre-money EUR mln{linebreak}12.", QUALIFIED_12)
    for item in ("\n\n- Importi in EUR mln\n  12. capitale richiesto.",
                 "\n\n1. Importi in EUR mln\n   12. capitale richiesto.",
                 "\n\n* Importi in EUR mln\n  12) capitale richiesto."):
        yield f"elenco {item!r}", item, QUALIFIED_12


#: POSITIVI di grandezza e marcatura — la resa ESATTA dei letterali dichiarati
#: resta accettata quando la punteggiatura o la marcatura la separano da una
#: parola che NON e' una grandezza, quando un link porta una destinazione con
#: parentesi, quando la percentuale chiude la propria espressione, quando la
#: frase FINISCE e la successiva comincia con una parola del vocabolario
#: (la relazione e' locale alla frase), e quando un trattino basso sta DENTRO
#: un identificatore (non e' enfasi).
ROUND5_POSITIVES = (
    "Il capitale richiesto e' di 12 EUR. Migliaia di PMI restano il mercato "
    "di riferimento.",
    "Le assunzioni non validate sono 7. M&A e quotazione non sono previsti.",
    "Il file `cassa_12_periodi.csv` riporta la serie di cassa.",
    "Il mercato vale miliardi. 12 PMI hanno firmato una lettera d'intenti.",
    "**Le lettere firmate sono 12.** Migliaia di PMI restano il mercato.",
    "Il mercato conta migliaia di PMI in 12 regioni.",
    "Il merito e' mio. In 12 mesi il runway e' coperto.",
    "Le lettere d'intenti firmate sono [12][fonte].\n\n"
    "[fonte]: https://www.istat.it/report",
    "\n\n7. Validazione\n   - lettere d'intenti firmate: 12\n"
    "7. Lancio commerciale.",
    "Nei 12 mesi del piano (12 periodi) il runway resta di 7 periodi.",
    "Orizzonte: 12 periodi; runway: 7 periodi; impiego: 100%.",
    "Impiego al **100**%, su **12** periodi.",
    "Fonte: [rapporto annuale](https://example.org/rapporto_(annuale) "
    "\"Rapporto (annuale)\") su 12 periodi.",
    "Runway di 12 mesi / 7 periodi, impiego al 100% (costi operativi).",
    "\n\n- Orizzonte di 12 periodi.\n- Runway di 7 periodi.",
)

#: Famiglie AVVERSARIE per la SCALA del tempo
#: di scansione, `(etichetta, testa, unita', coda)`: il testo e'
#: `testa + unita' * k + coda`. La prima e' un `<img` mai chiuso con
#: `alt=""` ripetuti, che una scansione ingenua tratta in tempo quadratico;
#: le altre sono
#: il generatore generico di attributi, aperture e marcatori ripetuti, un
#: passo della vista del lettore ciascuna. La sonda misura le taglie N, 2N e
#: 4N (N = `SCALING_CHARACTERS` caratteri) e confronta i TEMPI fra loro, mai
#: con una soglia assoluta: T(4N) <= `SCALING_RATIO_LIMIT` x T(N). Lineare
#: vale ~4, quadratico ~16.
SCALING_FAMILIES = (
    ("img-alt-virgolette", "Pre-money 12 <img", " alt=\"\"", " periodi."),
    ("img-alt-apici", "Pre-money 12 <img", " alt=''", " periodi."),
    ("tag-attributi", "Pre-money 12 <b", " a=\"\"", " periodi."),
    ("link-aperture", "Pre-money ", "[12](", " periodi."),
    ("link-parentesi", "Pre-money [12](", "](a(", " periodi."),
    ("link-titoli", "Pre-money ", "[12](x \"", " periodi."),
    ("marcatori-esponente", "Pre-money 12", "**", "e8 periodi."),
    ("grandezza-punteggiatura", "Pre-money EUR mln", ". ", "12 periodi."),
    ("commenti", "Pre-money 12 ", "<!--", " periodi."),
)
#: Le famiglie misurate ANCHE sul fronte del derivato (`check_derived`).
SCALING_DERIVED_FAMILIES = ("img-alt-virgolette", "link-parentesi",
                            "grandezza-punteggiatura")
SCALING_CHARACTERS = 14000
SCALING_RATIO_LIMIT = 8
SCALING_REPEATS = 3
SCALING_ATTEMPTS = 2

#: Grandezza e marcatura sul percorso REALE del Transaction Manager:
#: (A) la grandezza staccata dalle cifre per punteggiatura e
#: struttura, (B) la marcatura Markdown che spezza l'espressione, sui due
#: fronti insieme; (C) il positivo, pubblicato byte per byte.
STRUCTURE_EXPLOIT = ("Capitale richiesto (EUR mln) = 12. La valutazione "
                     "pre-money e' di EUR mln. 12. Il round vale 12, in "
                     "milioni di euro.")
STRUCTURE_EXPLOIT_NAMED = ("12",)
MARKDOWN_EXPLOIT = ("Il round vale **12**e8 EUR, cioe' "
                    "[12](https://it.wikipedia.org/wiki/Euro_\\(valuta\\)) "
                    "milioni di euro.")
MARKDOWN_EXPLOIT_NAMED = ("12**e8", "12")
ROUND5_POSITIVE_PROSE = ("Nei 12 mesi del piano (12 periodi) il runway "
                         "resta di 7 periodi; impiego: 100%.")

#: Coppie COMPENSATE `+X/+Y`, `-X/-Y` aggiunte a
#: `use_of_proceeds[]`: gli aggregati non cambiano. Tre valori, perche' la
#: proprieta' non dipende da `5000000` o da `20`.
OFFSET_VARIANTS = (("5000000", "20"), ("4999999", "19"),
                   ("777777.77", "3.5"))

#: Varianti metamorfiche — ogni variante valida della suite: il prodotto
#: del costruttore deve passare il proprio validator. `zero` e' la rotta del
#: motore con una categoria d'impiego a peso ZERO.
METAMORPHIC_VARIANTS = (
    ("full", "full", None), ("partial", "partial", None),
    ("none", "none", None), ("buffer", "buffer", None),
    ("two", "full", "with_two_use_categories"),
    ("milestone", "full", "with_milestone_coverage"),
    ("profile", "full", "with_startup_profile"),
    ("registers", "full", "with_evidence_registers"),
    ("rich", "full", "with_rich_context"),
    ("zero", "zero", None),
    ("zero-ultima", "full", "with_zero_weight_last_category"),
)

XLSX = None      # harness dello Stage 10 (workbook), popolato da `main`
CHAPTER = None   # harness dello Stage 10 (capitolo)
M5A = None       # harness dello Stage 10 (canonico)
_BASELINE = None


class HarnessUsageError(Exception):
    """Errore d'uso dell'harness (exit 2)."""


class HarnessDefect(Exception):
    """Difetto di PREPARAZIONE (exit 3). Non e' evidenza RED."""


# --------------------------------------------------------------------------
# Preparazione
# --------------------------------------------------------------------------


def resolve_root(raw):
    if not raw:
        raise HarnessUsageError("--root obbligatorio")
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise HarnessUsageError(f"--root non e' una directory: {root}")
    for probe_rel in (SKILL_REL, TESTKIT_REL):
        if not (root / probe_rel).is_dir():
            raise HarnessUsageError(
                f"--root non sembra la radice del repository: {probe_rel} "
                f"assente sotto {root}")
    return root


def load_harness(root, name):
    path = root / TESTKIT_REL / f"{name}.py"
    if not path.is_file():
        raise HarnessDefect(f"harness assente: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def build_context(root):
    ctx = XLSX.build_context(root)
    ctx["root"] = root
    ctx["config"] = json.loads(
        (root / ENFORCEMENT_REL).read_text(encoding="utf-8"))
    ctx["fr_validator"] = root / FR_VALIDATOR_REL
    return ctx


def canonical_json(document):
    """La STESSA forma canonica deterministica gia' usata dallo Stage 10."""
    return json.dumps(document, indent=2, ensure_ascii=True,
                      sort_keys=True) + "\n"


def sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_hashes(root):
    """Impronta per-file di un sottoalbero: prova il ripristino byte per byte."""
    out = {}
    base = Path(root)
    if not base.exists():
        return out
    for path in sorted(base.rglob("*")):
        if path.is_file():
            out[path.relative_to(base).as_posix()] = sha256_of(path)
    return out


# --------------------------------------------------------------------------
# Fixture: la pipeline di produzione dello Stage 10, poi lo Stage 11
# --------------------------------------------------------------------------


def stage10_baseline(ctx, level="full"):
    """La pipeline deterministica COMPLETA dello Stage 10, UNA VOLTA per
    livello di copertura di scenario.

    Riusa i costruttori di produzione: motore, `build_canonical_output`,
    `render_financial_plan`, `export_financial_model`. Il canonico prodotto
    sotto `.working/<tx>/` e' poi PUBBLICATO alla sede PERSISTITA che lo
    Stage 11 legge — la stessa che `validate_financial_output` risolve in fase
    `impact` e che il Transaction Manager scrive al commit.
    """
    global _BASELINE
    if _BASELINE is None:
        _BASELINE = {"holder": Path(tempfile.mkdtemp(prefix="s11_fr_base_"))}
    key = f"baseline-{level}"
    if key in _BASELINE:
        return _BASELINE[key]
    holder = _BASELINE["holder"] / level
    holder.mkdir(parents=True, exist_ok=True)
    if level == "buffer":
        case = buffer_pipeline(ctx, holder)
    elif level == "zero":
        case = zero_weight_pipeline(ctx, holder)
    else:
        case = XLSX.prepare(ctx, holder, name=f"s11-{level}", level=level,
                            tx=TX10)
    if (case.get("built") or {}).get("exit_code") != 0:
        raise HarnessDefect(
            "il costruttore canonico non ha prodotto il canonico "
            f"dello Stage 10: "
            f"{(case.get('built') or {}).get('stdout', '')[:300]}")
    if (case.get("rendered") or {}).get("exit_code") != 0:
        raise HarnessDefect(
            "il renderer non ha prodotto il capitolo: "
            f"{(case.get('rendered') or {}).get('stdout', '')[:300]}")
    if (case.get("export") or {}).get("exit_code") != 0:
        raise HarnessDefect(
            "l'exporter non ha prodotto il workbook: "
            f"{(case.get('export') or {}).get('stdout', '')[:300]}")
    project = Path(case["project"])
    published = project / STAGE10 / CANONICAL_NAME
    published.write_bytes(Path(case["canonical"]).read_bytes())
    _BASELINE[key] = case
    return case


def buffer_pipeline(ctx, holder):
    """La pipeline dello Stage 10 con `cash_buffer_policy` DICHIARATA:
    e' la sola fixture che esercita il ramo PRIMARIO della politica di
    capitalizzazione (`funding_gap_to_buffer`) invece del fallback.

    Stessi costruttori di `test_fin_chapter.prepare` — motore, costruttore
    canonico, renderer, exporter — con la sola politica di buffer passata al
    motore nella forma gia' usata da `test_fin_engine.py`. Nessuna fixture
    del registro chiuso `F-1`...`F-13` e' toccata.
    """
    records = CHAPTER.coverage_records(ctx, "full")
    rows = M5A.ENG.base_rows(ctx["eng"], records)
    config = M5A.ENG.financial_config(ctx["eng"],
                                      cash_buffer_policy=dict(BUFFER_POLICY))
    _, run = M5A.engine_run(ctx, holder, rows, records, config=config,
                            name="s11-buffer-engine")
    project = M5A.fixture_project(ctx, holder, "s11-buffer")
    Path(project, "shared", "assumptions-register.json").write_text(
        json.dumps(list(records.values()), indent=2, ensure_ascii=True,
                   sort_keys=True, default=str), encoding="utf-8")
    payload_path = M5A.write_payload(holder, run["result"],
                                     name="s11-buffer-payload.json")
    built = M5A.run_builder(ctx, payload_path, project, tx=TX10)
    canonical = M5A.canonical_path(project, TX10)
    rendered = CHAPTER.run_renderer(ctx, canonical, project)
    export = XLSX.run_exporter(ctx, canonical, project)
    return {"project": project, "canonical": canonical, "built": built,
            "rendered": rendered, "export": export}


def zero_weight_pipeline(ctx, holder):
    """La pipeline dello Stage 10 con una categoria d'impiego a peso ZERO.

    Stessi costruttori di `buffer_pipeline`. I record sono quelli della
    fixture piena con `opex` = 0 e la terna di `ASS-007` a `(0, 0, 0)`, e la
    riga di `DRV-007` porta la categoria canonica `interest`: nel motore
    una categoria `interest` supera `REC-15` SOLO a peso zero, e la
    ripartizione dichiarata le assegna percio' una quota nulla. E' la rotta
    su cui un costruttore ingenuo emetterebbe `0E-31` / `0E-8` e il
    validator li respingerebbe. Nessuna fixture del registro chiuso
    `F-1`...`F-13` e' toccata.
    """
    records = M5A.ENG.base_records(ctx["eng"], opex="0")
    for ref, (low, mid, high) in CHAPTER.TRIPLET_SPREAD.items():
        if ref == "ASS-007":
            low, mid, high = "0", "0", "0"
        M5A.ENG.with_triplet(records, ref, low, mid, high)
    rows = M5A.ENG.base_rows(ctx["eng"], records)
    for row in rows:
        if row["driver_id"] == "DRV-007":
            row["cost_category"] = "interest"
    _, run = M5A.engine_run(ctx, holder, rows, records,
                            name="s11-zero-engine")
    project = M5A.fixture_project(ctx, holder, "s11-zero")
    Path(project, "shared", "assumptions-register.json").write_text(
        json.dumps(list(records.values()), indent=2, ensure_ascii=True,
                   sort_keys=True, default=str), encoding="utf-8")
    payload_path = M5A.write_payload(holder, run["result"],
                                     name="s11-zero-payload.json")
    built = M5A.run_builder(ctx, payload_path, project, tx=TX10)
    canonical = M5A.canonical_path(project, TX10)
    rendered = CHAPTER.run_renderer(ctx, canonical, project)
    export = XLSX.run_exporter(ctx, canonical, project)
    return {"project": project, "canonical": canonical, "built": built,
            "rendered": rendered, "export": export}


def testkit():
    """Il testkit condiviso, per i soli costruttori di stato di progetto."""
    import bpo_testkit
    return bpo_testkit


def transaction_manager(ctx):
    """Il Transaction Manager DI PRODUZIONE, caricato in SOLA LETTURA: le sonde
    della fase impact usano le SUE funzioni, mai una copia."""
    kit = testkit()
    return kit.load_module(ctx["root"], kit.TRANSACTION_REL,
                           "transaction_manager")


def fr_module(ctx):
    """Il modulo DI PRODUZIONE della funding request, importato in SOLA
    LETTURA per le sonde UNITARIE del tracciamento numerico. E' lo
    stesso file che la CLI esegue, non una copia."""
    path = ctx["fr_validator"]
    if not path.is_file():
        return None
    name = "validate_funding_request_under_test"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: Forma MINIMA di una voce di registro secondo gli schemi
#: `evidence-register.schema.json` e `source-register.schema.json`, usata solo
#: quando il registro della fixture e' vuoto o assente.
REGISTER_TEMPLATES = {
    EVIDENCE_REGISTER_REL: {"statement": "Evidenza di fixture dello Stage 11",
                            "classification": "internal_evidence",
                            "status": "open"},
    SOURCE_REGISTER_REL: {"title": "Fonte di fixture dello Stage 11",
                          "source_type": "internal"},
}


def write_register(project, rel, ids):
    """Riscrive un registro condiviso con i SOLI `ids` dati, ciascuno sulla
    forma della prima voce REALE del registro — o, se il registro della
    fixture e' vuoto, sulla forma minima dello schema: la mutazione
    tocca l'id e nient'altro."""
    path = Path(project) / rel
    current = json.loads(path.read_text(encoding="utf-8")) \
        if path.is_file() else []
    template = dict(current[0]) if current and isinstance(current[0], dict) \
        else dict(REGISTER_TEMPLATES.get(rel, {}))
    entries = []
    for ref in ids:
        entry = dict(template)
        entry["id"] = ref
        entries.append(entry)
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=True),
                    encoding="utf-8")


def with_evidence_registers(project):
    """Registri di evidenza e di fonte POPOLATI in forma canonica degli id: la
    fixture `F-1` porta un registro di evidenza VUOTO, su cui l'omissione di
    una voce non sarebbe misurabile."""
    write_register(project, EVIDENCE_REGISTER_REL, ["EVD-001"])
    write_register(project, SOURCE_REGISTER_REL, ["SRC-001"])
    return project


def with_registered_ids(project):
    """Fixture RICCA: roadmap REALE
    (`MIL-001`...`MIL-004`), copertura delle milestone e registri di evidenza
    e di fonte popolati. E' la fixture su cui gli id di OGNI registro che lo
    Stage 11 legge risolvono davvero."""
    with_milestone_coverage(project)
    with_evidence_registers(project)
    return project


def with_startup_profile(project):
    """Profilo di avvio PRESENTE: i tre campi del lettore si LEGGONO da qui."""
    path = Path(project) / PROFILE_REL
    path.write_text(json.dumps(STARTUP_PROFILE, indent=2, ensure_ascii=True),
                    encoding="utf-8")
    return project


def with_zero_weight_last_category(project):
    """Variante metamorfica DERIVATA IN-MODULO a DUE categorie
    (`with_two_use_categories`) in cui l'ULTIMA della ripartizione
    (`operating_cost`) ha peso ZERO e `interest` porta righe da 175 per
    periodo. La ripartizione esatta assegna all'ultima il residuo; qui
    l'arrotondamento della quota precedente lo rende `-1E-23`, un residuo di
    un'unita' dell'ultima cifra: e' ancora il prodotto del costruttore, e deve
    passare il proprio validator."""
    with_two_use_categories(project)
    canonical_path = stage10_paths(project)["canonical"]
    document = json.loads(canonical_path.read_text(encoding="utf-8"))
    for module in document["financial_plan"]["results"]["modules"].values():
        for line in (module.get("lines") or []) if isinstance(module, dict) \
                else []:
            drivers = set(line.get("driver_refs") or [])
            if drivers & {"DRV-004", "DRV-005"}:
                line["series"] = {key: "0" for key in line.get("series") or {}}
            elif "DRV-007" in drivers:
                line["series"] = {key: "175"
                                  for key in line.get("series") or {}}
    canonical_path.write_text(canonical_json(document), encoding="utf-8")
    return project


def with_rich_context(project):
    """Variante metamorfica — la fixture RICCA degli id registrati (roadmap, copertura delle
    milestone, registri) piu' il profilo di avvio: ogni sorgente che il
    costruttore legge e' popolata insieme."""
    with_registered_ids(project)
    with_startup_profile(project)
    return project


def with_two_use_categories(project):
    """Variante DERIVATA IN-MODULO del canonico dello Stage 10 con DUE
    categorie eleggibili di impiego.

    Il motore dichiara una sola categoria (`operating_cost`): la
    variante sposta le righe di `DRV-007` sulla categoria canonica `interest`
    — un valore dell'enum `cost_category` dello schema — e dichiara
    il secondo candidato con i propri `driver_refs`, cosi' che la regola di
    allocazione dichiarata operi su DUE pesi letti dal canonico.
    """
    canonical_path = stage10_paths(project)["canonical"]
    document = json.loads(canonical_path.read_text(encoding="utf-8"))
    modules = document["financial_plan"]["results"]["modules"]
    for module in modules.values():
        for line in (module.get("lines") or []) if isinstance(module, dict) \
                else []:
            if "DRV-007" in (line.get("driver_refs") or []):
                line["category"] = "interest"
    funding_gap = modules["funding_gap"]
    candidates = funding_gap["use_of_proceeds_candidates"]
    for candidate in candidates:
        candidate["driver_refs"] = [ref for ref in candidate["driver_refs"]
                                    if ref != "DRV-007"]
    candidates.append({"category_id": "interest",
                       "driver_refs": ["DRV-007"],
                       "eligibility_basis": candidates[0]["eligibility_basis"],
                       "label": "oneri finanziari"})
    canonical_path.write_text(canonical_json(document), encoding="utf-8")
    return project


def advance_stage11(ctx, case):
    """Porta lo Stage 11 a COMPLETATO attraverso il Transaction Manager REALE:
    `advance-stage` pubblica il candidate come canonico dello stage."""
    kit = testkit()
    project = Path(case["project"])
    order = ctx["config"]["stage_order"]
    completed = sorted((stage for stage in order
                        if int(order[stage]) < int(order[STAGE11])),
                       key=lambda stage: int(order[stage]))
    (project / STATUS_REL).write_text(
        kit.project_status_text(project.name, STAGE11, "in_progress",
                                completed), encoding="utf-8")
    return kit.run_tm_cli(ctx["root"], "advance-stage", "--project", project,
                          "--stage", STAGE11, "--candidate",
                          case["paths"]["candidate"], "--gate-result",
                          "approved")


def run_impact_on_view(ctx, tm, project, stages, replacements=None,
                       tx="tx-s11-impact"):
    """La fase impact nella forma REALE del Transaction Manager: la validation
    view di `build_validation_view` — `shared/` piu' i soli
    `NN_*/structured-output.json` — e `run_impact_validators`, che invoca
    `--project <view> --stage <s> --phase impact` SENZA `--candidate`."""
    rel, view = tm.build_validation_view(project, tx, replacements or {},
                                         ctx["config"])
    try:
        derived_in_view = (view / STAGE11 / REQUEST_NAME).exists()
        results, _ = tm.run_impact_validators(ctx["config"], view, rel,
                                              stages)
    finally:
        tm.cleanup_validation_view(project, rel)
    return results, derived_in_view


def report_codes(result):
    report = result.get("report") if isinstance(result.get("report"),
                                                dict) else {}
    return sorted({entry.get("code") for entry in report.get("errors") or ()})


def named_in(verdict, code):
    """Testo dei messaggi e dei ref di QUESTO codice: il rifiuto deve NOMINARE
    cio' che respinge."""
    return " ".join(
        (verdict.get("messages_by_code") or {}).get(code, []) +
        [str(ref) for ref in (verdict.get("refs_by_code") or {}).get(code, [])])


def drop_baseline():
    global _BASELINE
    if _BASELINE is not None:
        shutil.rmtree(_BASELINE["holder"], ignore_errors=True)
        _BASELINE = None


def clone(ctx, base, name="clone", level="full"):
    """Copia PROFONDA del progetto di baseline: ogni mutazione agisce qui."""
    case = stage10_baseline(ctx, level=level)
    target = Path(base) / name
    shutil.copytree(case["project"], target)
    return target


def stage10_paths(project):
    stage = Path(project) / STAGE10
    return {"canonical": stage / CANONICAL_NAME,
            "chapter": stage / CHAPTER_NAME,
            "workbook": stage / WORKBOOK_NAME}


def stage11_paths(project, tx=TX11):
    stage = Path(project) / STAGE11
    return {"candidate": stage / ".working" / tx,
            "canonical": stage / ".working" / tx / CANONICAL_NAME,
            "handoff": stage / ".working" / tx / HANDOFF_NAME,
            "request": stage / REQUEST_NAME}


MISSING_VALIDATOR = (
    f"{FR_VALIDATOR_REL} ASSENTE: il modulo della funding request e' la SEDE "
    "della proiezione, del renderer, del publisher atomico e della validazione "
    "di egress/impact")


def run_fr(ctx, args, env_extra=None):
    """Invoca il MODULO DI PRODUZIONE della funding request, mai una copia."""
    validator = ctx["fr_validator"]
    if not validator.is_file():
        return {"available": False, "reason": MISSING_VALIDATOR,
                "exit_code": None, "report": None, "codes": set(),
                "refs_by_code": {}, "messages_by_code": {},
                "stdout": "", "stderr": "", "command": ""}
    command = [sys.executable, str(validator)] + [str(item) for item in args]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(command, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          cwd=str(ctx["root"]), env=env)
    report = None
    if proc.stdout.strip().startswith("{"):
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            report = None
    codes = set()
    refs_by_code = {}
    messages_by_code = {}
    if report:
        for entry in report.get("errors") or ():
            code = entry.get("code")
            if not code:
                continue
            codes.add(code)
            refs_by_code.setdefault(code, []).append(entry.get("ref"))
            messages_by_code.setdefault(code, []).append(
                str(entry.get("message") or ""))
    return {"available": True, "reason": "", "exit_code": proc.returncode,
            "report": report, "codes": codes, "refs_by_code": refs_by_code,
            "messages_by_code": messages_by_code,
            "stdout": proc.stdout, "stderr": proc.stderr,
            "command": " ".join(command)}


def run_builder(ctx, project, tx=TX11, extra=(), env_extra=None):
    """Modalita' COSTRUZIONE: proiezione + renderer + publisher atomico.

    NON e' il percorso del Transaction Manager, che resta di SOLA LETTURA:
    `--build` non e' mai passato da `run_egress_validators` ne' da
    `run_impact_validators`.
    """
    args = ["--build", "--project", project, "--tx", tx, *extra]
    return run_fr(ctx, args, env_extra=env_extra)


def run_validator(ctx, project, candidate=None, phase="egress", tx=TX11,
                  extra=()):
    """La forma REALE di invocazione del Transaction Manager, e nessun'altra.

        egress   --project --candidate --stage --phase egress
        impact   --project --stage --phase impact      (SENZA --candidate)
    """
    args = ["--project", project, "--stage", STAGE11, "--phase", phase]
    if phase == "egress":
        args += ["--candidate",
                 candidate or stage11_paths(project, tx)["candidate"]]
    args += list(extra)
    return run_fr(ctx, args)


def with_milestone_coverage(project):
    """Variante DERIVATA IN-MODULO del canonico dello Stage 10 con il modulo
    `milestone_coverage` POPOLATO e una milestone FUORI ORIZZONTE.

    Il registro delle fixture `F-1`...`F-13` di `bpo_testkit.py` resta
    CHIUSO: la variante e' derivata qui, sul canonico gia' prodotto
    dalla pipeline di produzione, ed e' l'unico modo di esercitare i contratti di
    milestone — il motore NON produce quel modulo e lo PUBBLICA
    dichiaratamente `NOT_APPLICABLE`.

    Il registro REALE della roadmap e' scritto con il costruttore condiviso
    `bpo_m5_fixtures.canonical_milestone_structured()`, cosi' che i
    `MIL-*` risolvano contro la roadmap e non contro una lista locale.
    """
    import bpo_m5_fixtures as m5
    canonical_path = stage10_paths(project)["canonical"]
    document = json.loads(canonical_path.read_text(encoding="utf-8"))
    results = document["financial_plan"]["results"]
    results["modules"]["milestone_coverage"] = {
        "module_id": "milestone_coverage",
        "status": "PASS",
        "milestones": [
            {"milestone_ref": "MIL-001", "coverage_status": "funded",
             "cost_driver_refs": ["DRV-004"], "period_index": 3},
            {"milestone_ref": "MIL-002", "coverage_status": "unfunded",
             "cost_driver_refs": ["DRV-005"], "period_index": None},
        ],
        "unmapped_residual": "0",
    }
    results["calendar"]["out_of_horizon_milestones"] = ["MIL-002"]
    canonical_path.write_text(canonical_json(document), encoding="utf-8")
    roadmap = Path(project) / "09_roadmap-and-milestones"
    roadmap.mkdir(exist_ok=True)
    (roadmap / CANONICAL_NAME).write_text(
        canonical_json(m5.canonical_milestone_structured()), encoding="utf-8")
    return project


def prepare(ctx, base, name="fr", level="full", tx=TX11, build_extra=(),
            hook=None):
    """Progetto TEMPORANEO con Stage 10 pubblicato e Stage 11 costruito."""
    project = clone(ctx, base, name=name, level=level)
    if hook is not None:
        hook(project)
    built = run_builder(ctx, project, tx=tx, extra=build_extra)
    paths = stage11_paths(project, tx)
    document = None
    if paths["canonical"].is_file():
        try:
            document = json.loads(
                paths["canonical"].read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HarnessDefect(f"canonico Stage 11 non e' JSON: {exc}")
    validated = None
    if document is not None:
        validated = run_validator(ctx, project, paths["candidate"])
    return {"project": project, "tx": tx, "built": built, "paths": paths,
            "document": document, "validated": validated,
            "stage10": stage10_paths(project)}


def not_built(case, findings, observation):
    """`True` quando la funding request NON e' stata prodotta, con la propria
    CONSTATAZIONE ATTRIBUITA registrata: nessun contratto e' GREEN per
    silenzio e nessun contratto e' RED per `ImportError`."""
    built = case.get("built") or {}
    if not built.get("available", True):
        findings.append(f"constatazione: {observation} — {built['reason']}")
        return True
    if case.get("document") is None:
        findings.append(
            f"constatazione: {observation} — nessun canonico Stage 11 "
            f"prodotto (exit {built.get('exit_code')}): "
            f"{(built.get('stderr') or built.get('stdout') or '')[:300]}")
        return True
    return False


def request_of(document):
    return (document or {}).get("funding_request") or {}


def plan_of(document):
    return (document or {}).get("financial_plan") or {}


def modules_of(document):
    return ((plan_of(document).get("results") or {}).get("modules")) or {}


def stage10_document(case):
    return json.loads(
        case["stage10"]["canonical"].read_text(encoding="utf-8"))


def mutate(document, path, value):
    """Copia PROFONDA con UN solo valore sostituito. `path` e' punteggiato e
    accetta indici interi per gli array."""
    copy = json.loads(json.dumps(document))
    node = copy
    steps = path.split(".")
    for step in steps[:-1]:
        node = node[int(step)] if step.isdigit() else node[step]
    last = steps[-1]
    if last.isdigit():
        node[int(last)] = value
    else:
        node[last] = value
    return copy


def drop(document, path):
    """Copia PROFONDA con UNA sola chiave RIMOSSA."""
    copy = json.loads(json.dumps(document))
    node = copy
    steps = path.split(".")
    for step in steps[:-1]:
        node = node[int(step)] if step.isdigit() else node[step]
    node.pop(steps[-1], None)
    return copy


def probe(ctx, case, document, name="probe"):
    """Scrive un documento MUTATO in un candidate SEPARATO e lo valida.

    Il candidate di riferimento non e' mai toccato: la mutazione vive in una
    transazione propria, esattamente come `probe_document` dello Stage 10.
    """
    paths = stage11_paths(case["project"], name)
    paths["candidate"].mkdir(parents=True, exist_ok=True)
    paths["canonical"].write_text(canonical_json(document), encoding="utf-8")
    source_handoff = case["paths"]["handoff"]
    paths["handoff"].write_text(
        source_handoff.read_text(encoding="utf-8")
        if source_handoff.is_file() else "# Handoff\n", encoding="utf-8")
    return run_validator(ctx, case["project"], paths["candidate"])


def rejects(verdict, code, label):
    """Il verdetto deve RESPINGERE con QUESTO codice. «Fallisce» non e'
    evidenza; «fallisce con QUESTO codice» lo e'."""
    problems = []
    if verdict.get("exit_code") == 0:
        problems.append(f"{label}: la mutazione e' stata ACCETTATA (exit 0)")
    if code not in (verdict.get("codes") or set()):
        problems.append(
            f"{label}: atteso il codice {code!r}, ottenuti "
            f"{sorted(verdict.get('codes') or ())}")
    return problems


def accepts(verdict, label):
    """Il caso POSITIVO deve passare: senza di esso i casi negativi non
    dimostrerebbero che il gate discrimina."""
    if verdict is None:
        return [f"{label}: nessun verdetto prodotto"]
    if not verdict.get("available", True):
        return [f"{label}: {verdict['reason']}"]
    if verdict.get("exit_code") != 0:
        return [f"{label}: atteso exit 0, ottenuto {verdict.get('exit_code')} "
                f"(codici {sorted(verdict.get('codes') or ())}; "
                f"{(verdict.get('stderr') or '')[:200]})"]
    return []


def amount(value):
    """Un importo canonico puo' arrivare come NUMERO o come STRINGA
    (`$defs.amount`): la precisione Decimal degli accumuli e' preservata dalla
    forma stringa, e assumere `float` la romperebbe."""
    return Decimal(str(value))


def first_use_index(request):
    uses = request.get("use_of_proceeds") or []
    if not uses:
        raise HarnessDefect(
            "la funding request non porta alcuna voce di use_of_proceeds: la "
            "mutazione di allocazione non sarebbe costruibile")
    return 0


# --------------------------------------------------------------------------
# Manomissioni COERENTI e percorso REALE
# --------------------------------------------------------------------------


def probe_with_markdown(ctx, case, document, markdown, name="probe"):
    """`probe` con il DERIVATO riscritto: il candidate MUTATO vive
    in una transazione propria e `funding-request.md` e' sostituito da
    `markdown` per la sola durata della validazione, poi ripristinato byte
    per byte. E' la forma delle manomissioni COERENTI (numero in chiaro,
    coppie compensate, capitale riprezzato): canonico E derivato manomessi
    insieme, coerenti fra loro."""
    request_md = case["paths"]["request"]
    original = request_md.read_bytes()
    request_md.write_bytes(markdown.encode("utf-8"))
    try:
        return probe(ctx, case, document, name)
    finally:
        request_md.write_bytes(original)


def milestone_status_of(stage10):
    return str((modules_of(stage10).get("milestone_coverage") or {})
               .get("status") or "NOT_APPLICABLE")


def rebuild_prose(module, document, stage10, extra=None):
    """La narrativa e il derivato RICOSTRUITI con le funzioni DI
    PRODUZIONE `build_narrative` e `render_request` sul documento MUTATO, con
    `extra` aggiunto al paragrafo `FR-S1` di ENTRAMBI i fronti. Ritorna il
    Markdown; il documento e' aggiornato sul posto."""
    request = document["funding_request"]
    request["narrative"] = module.build_narrative(
        request, milestone_status_of(stage10))
    if extra:
        request["narrative"]["sections"][0]["body"] += f" {extra}"
    return module.render_request(document)


def markdown_with_prose(case, prose, markdown=None):
    """Il derivato con `prose` inserita nel paragrafo `FR-S1`, subito dopo il
    corpo generato: la sede delle manomissioni della prosa."""
    body = str(request_of(case["document"])["narrative"]["sections"][0]
               ["body"])
    text = markdown if markdown is not None else \
        case["paths"]["request"].read_text(encoding="utf-8")
    if body not in text:
        raise HarnessDefect(
            f"il paragrafo FR-S1 non compare in {REQUEST_NAME}: la "
            "manomissione del derivato non sarebbe costruibile")
    return text.replace(body, f"{body} {prose}", 1)


def reprice(module, case, requested, gap=None, contingency=None):
    """Capitale riprezzato — un candidate INTERNAMENTE COERENTE con un
    capitale richiesto `requested` DIVERSO dal fabbisogno modellato.

    E' costruito con le funzioni DI PRODUZIONE: addendo di base, atteso e osservato della riconciliazione
    allineati a `requested`; `use_of_proceeds` ripartito con
    `derive_allocation` sul nuovo importo; runway finanziato e orizzonte
    finanziato ricostruiti con `derive_runway_after`; la voce di provenance
    del capitale richiesto AUTO-dichiarata `derivation: reconciliation`.
    `gap` e' il gap residuo dichiarato: `None` vale il gap ONESTO di
    `derive_residual_gap`, una stringa lo sostituisce. `contingency`, se
    data, e' una contingency DICHIARATA dal candidate e sommata come addendo.
    Ritorna `(documento, markdown, gap onesto)`."""
    stage10 = stage10_document(case)
    modules = modules_of(stage10)
    document = json.loads(json.dumps(case["document"]))
    request = document["funding_request"]
    value = Decimal(str(requested))
    request["requested_capital"]["amount"] = str(value)
    capital = request["capital_requirement"]
    recon = capital["reconciliation"]
    base_value = value if contingency is None else value - Decimal(contingency)
    for addend in recon["addends"]:
        if addend["role"] == "base":
            addend["amount"] = str(base_value)
    if contingency is not None:
        capital["contingency_component"] = {
            "state": "declared", "amount": contingency,
            "reason": "contingency DICHIARATA dal candidate"}
        recon["addends"].append({"name": "contingency_component",
                                 "amount": contingency, "role": "addend"})
    recon.update({"expected": str(value), "actual": str(value),
                  "residual": "0", "status": "PASS"})
    weights, _ = module.derive_line_weights(modules)
    names = [entry["category_id"] for entry in request["use_of_proceeds"]]
    amounts, percentages = module.derive_allocation(value, names, weights)
    for entry, amount_value, percentage in zip(request["use_of_proceeds"],
                                               amounts, percentages):
        entry["amount"] = str(amount_value)
        entry["percentage"] = str(percentage)
    series = (modules.get("cash_flow") or {}).get("series") or {}
    horizon = ((plan_of(stage10).get("results") or {}).get("calendar")
               or {}).get("horizon_periods")
    limit = Decimal("0")
    if request["runway"]["measure"] == "to_buffer":
        limit = Decimal(str(((modules.get("cash_buffer") or {})
                             .get("metrics") or {}).get("threshold")))
    after = module.derive_runway_after(series, horizon, value, limit)
    honest = module.derive_residual_gap(series, horizon, value, limit)
    request["runway"]["after_financing"]["periods"] = after
    request["sufficiency"]["funded_horizon"] = after
    request["sufficiency"]["residual_gap"] = str(honest) if gap is None \
        else gap
    for entry in request["provenance"]:
        if entry["field"] == "requested_capital.amount":
            entry["derivation"] = "reconciliation"
            entry["derivation_paths"] = [capital["modeled_need_ref"]]
    return document, rebuild_prose(module, document, stage10), honest


def extend_uses(document, entries):
    """Aggiunge `entries` a `use_of_proceeds[]`, ciascuna con le proprie voci
    di provenance COPIATE da quelle di `use_of_proceeds[0]`: il join campi x
    provenienza di `FR-C-21` resta totale, e la sola differenza e' la voce."""
    request = document["funding_request"]
    uses = request["use_of_proceeds"]
    template = {entry["field"]: entry for entry in request["provenance"]}
    for entry in entries:
        index = len(uses)
        uses.append(entry)
        for key in ("amount", "percentage"):
            copy = dict(template[f"use_of_proceeds[0].{key}"])
            copy["field"] = f"use_of_proceeds[{index}].{key}"
            request["provenance"].append(copy)
    request["provenance"].sort(key=lambda item: str(item["field"]))
    return document


def offset_uses(module, case, amount_value, percentage, extra=None):
    """Coppia COMPENSATA:
    due copie di `use_of_proceeds[0]` con `+X/+Y` e `-X/-Y`. Gli aggregati di
    `FR-C-05` e `FR-C-06` restano invariati; la narrativa e il derivato sono
    ricostruiti con le funzioni di produzione, piu' `extra`. Ritorna
    `(documento, markdown)`."""
    document = json.loads(json.dumps(case["document"]))
    origin = document["funding_request"]["use_of_proceeds"][0]
    extend_uses(document, [
        dict(origin, amount=amount_value, percentage=percentage),
        dict(origin, amount=f"-{amount_value}", percentage=f"-{percentage}")])
    markdown = rebuild_prose(module, document, stage10_document(case), extra)
    return document, markdown


def projection_probes(ctx, case, probes):
    """Classe della PROIEZIONE — ogni
    `(etichetta, mutazione, codice)` altera un valore STRUTTURATO del
    candidate che la proiezione autoritativa del validator fissa; narrativa e
    derivato sono ricostruiti con le funzioni di produzione, cosi' che il solo
    difetto sia il valore. Ciascuna e' respinta con il codice del contratto
    che lega quel valore al canonico dello Stage 10, in un report JSON e mai
    con un traceback."""
    findings = []
    module = fr_module(ctx)
    if module is None:
        return [f"proiezione: {MISSING_VALIDATOR}"]
    for label, change, code in probes:
        document = json.loads(json.dumps(case["document"]))
        change(document["funding_request"])
        markdown = rebuild_prose(module, document, stage10_document(case))
        verdict = probe_with_markdown(ctx, case, document, markdown,
                                      f"proj-{len(findings)}")
        findings += rejects(verdict, code, f"proiezione: {label}")
        if "Traceback" in (verdict.get("stderr") or ""):
            findings.append(f"proiezione: {label}: traceback invece di un "
                            "rifiuto attribuito")
    return findings


def setter(path, value):
    """Mutazione di `projection_probes`: `path` puntato, indici interi."""
    def change(request):
        node = request
        steps = path.split(".")
        for step in steps[:-1]:
            node = node[int(step)] if step.isdigit() else node[step]
        node[int(steps[-1]) if steps[-1].isdigit() else steps[-1]] = value
    return change


def without_provenance(field, then=None):
    """Mutazione che toglie la voce di provenance di `field` (e applica
    `then`): la voce autoritativa non si omette."""
    def change(request):
        request["provenance"] = [entry for entry in request["provenance"]
                                 if entry["field"] != field]
        if then is not None:
            then(request)
    return change


def all_messages(verdict):
    return " ".join(" ".join(messages) for messages in
                    (verdict.get("messages_by_code") or {}).values())


def names_all(verdict, code, numbers, label):
    """Il rifiuto NOMINA ciascuno dei `numbers` sotto `code` (`repr`)."""
    named = named_in(verdict, code)
    return [f"{label}: il rifiuto {code} non NOMINA {number!r}"
            for number in numbers if repr(number) not in named]


def tm_chain(ctx, base, name, tamper, codes, named=(), level="full",
             hook=None, view=True):
    """Una manomissione sul percorso REALE, che il Transaction
    Manager NON modificato percorre.

    `tamper(module, case)` ritorna `(documento, markdown)`: i byte ESATTI del
    candidate e del derivato manomessi (`markdown` `None` lascia il derivato
    generato). Misura, nell'ordine: l'egress RESPINGE con ciascuno dei
    `codes` e NOMINA i `named`; l'`advance-stage --gate-result approved`
    REALE NON pubblica nulla; con `view`, la validation view di impact del
    Transaction Manager, col candidate manomesso iniettato, lo RESPINGE; la
    fase impact col derivato PRESENTE (manomissione dopo la pubblicazione,
    simulata scrivendo il candidate alla sede canonica) lo RESPINGE."""
    findings = []
    tm = transaction_manager(ctx)
    module = fr_module(ctx)
    if module is None:
        return [f"{name} (TM): {MISSING_VALIDATOR}"]
    case = prepare(ctx, base, name, level=level, hook=hook)
    if not_built(case, findings, f"{name}: nessuna funding request da "
                                 "manomettere"):
        return findings
    project = Path(case["project"])
    published = project / STAGE11 / CANONICAL_NAME
    document, markdown = tamper(module, case)
    candidate = canonical_json(document).encode("utf-8")
    case["paths"]["canonical"].write_bytes(candidate)
    if markdown is not None:
        case["paths"]["request"].write_bytes(markdown.encode("utf-8"))
    verdict = run_validator(ctx, project, case["paths"]["candidate"])
    for code in codes:
        problems = rejects(verdict, code, f"{name} (TM) egress")
        findings += problems
        if not problems and code in (CODE_NARRATIVE, CODE_DERIVED_MISMATCH):
            findings += names_all(verdict, code, named,
                                  f"{name} (TM) egress")
    exit_code, out, _ = advance_stage11(ctx, case)
    if exit_code == 0 or published.is_file():
        findings.append(
            f"{name} (TM): l'advance-stage REALE ha PUBBLICATO il candidate "
            f"manomesso (exit {exit_code}, canonico pubblicato: "
            f"{published.is_file()}): {out.strip()[:200]!r}")
        return findings
    if view:
        results, _ = run_impact_on_view(
            ctx, tm, project, [STAGE11],
            {f"{STAGE11}/{CANONICAL_NAME}": candidate}, tx=f"tx-{name}-view")
        invoked = [result for result in results
                   if result["validator"] == "validate_funding_request"]
        if not invoked or invoked[0]["exit_code"] == 0:
            findings.append(
                f"{name} (TM): la validation view di impact ACCETTA il "
                "candidate manomesso: "
                f"{[(r['exit_code'], report_codes(r)) for r in invoked]}")
    published.write_bytes(candidate)
    try:
        impact = run_validator(ctx, project, phase="impact")
    finally:
        published.unlink()
    if impact.get("exit_code") == 0:
        findings.append(
            f"{name} (TM): la fase impact col derivato PRESENTE ACCETTA il "
            "candidate manomesso")
    return findings


def tm_positive(ctx, base, name, level="full", hook=None, prose=None):
    """Controllo POSITIVO sullo STESSO percorso REALE: il
    prodotto del costruttore (piu' `prose` sui due fronti, se data) passa
    egress; l'`advance-stage` REALE lo pubblica BYTE PER BYTE; la validation
    view di impact e la fase impact col derivato presente lo accettano."""
    findings = []
    tm = transaction_manager(ctx)
    case = prepare(ctx, base, name, level=level, hook=hook)
    if not_built(case, findings, f"{name}: nessuna funding request per il "
                                 "controllo positivo"):
        return findings
    if prose:
        candidate = tamper_stage11(case, prose)
    else:
        candidate = case["paths"]["canonical"].read_bytes()
    findings += accepts(run_validator(ctx, case["project"],
                                      case["paths"]["candidate"]),
                        f"(positivo {name}, TM) egress")
    exit_code, out, err = advance_stage11(ctx, case)
    project = Path(case["project"])
    published = project / STAGE11 / CANONICAL_NAME
    if exit_code != 0 or not published.is_file() or \
            published.read_bytes() != candidate:
        findings.append(
            f"(positivo {name}, TM) advance-stage REALE non pubblica il "
            f"candidate validato byte per byte (exit {exit_code}): "
            f"{out.strip()[:200]!r} {err.strip()[:200]!r}")
        return findings
    results, _ = run_impact_on_view(ctx, tm, project, [STAGE11],
                                    tx=f"tx-{name}-pos")
    invoked = [result for result in results
               if result["validator"] == "validate_funding_request"]
    if not invoked or invoked[0]["exit_code"] != 0:
        findings.append(
            f"(positivo {name}, TM) impact sulla view REALE: "
            f"{[(r['exit_code'], report_codes(r)) for r in invoked]}")
    findings += accepts(run_validator(ctx, project, phase="impact"),
                        f"(positivo {name}, TM) impact col derivato presente")
    return findings


# --------------------------------------------------------------------------
# FR-C-01 — T-FR-CANONICAL-ONLY-SOURCE
# --------------------------------------------------------------------------


def c01(ctx, base):
    """Il JSON canonico dello Stage 10 e' l'UNICA sorgente numerica: ogni
    valore emesso risale a un path canonico DICHIARATO, e nessun operatore
    aritmetico opera su valori che non ne provengano."""
    findings = []
    case = prepare(ctx, base, "c01")
    if not_built(case, findings,
                 "nessuna proiezione esiste, quindi nessun valore emesso puo' "
                 "risalire a un path canonico dichiarato"):
        return findings
    findings += accepts(case["validated"], "(positivo) proiezione nominale")

    request = request_of(case["document"])
    stage10 = stage10_document(case)

    # Sonda STRUMENTATA: ogni voce di provenance dichiara un path canonico che
    # RISOLVE nel canonico dello Stage 10. Un valore emesso senza path e' gia'
    # `FR-C-21`; qui si misura che il path dichiarato PORTI il valore.
    provenance = request.get("provenance") or []
    if not provenance:
        findings.append(
            "la funding request non dichiara alcuna provenance[]: la sonda "
            "strumentata non avrebbe nulla da risolvere")
    unresolved = []
    for entry in provenance:
        path = str(entry.get("canonical_path") or "")
        if not path:
            unresolved.append(entry.get("field"))
            continue
        found, _ = resolve_canonical(stage10, path)
        if not found and str(entry.get("derivation") or "") == "":
            unresolved.append(f"{entry.get('field')} -> {path}")
    if unresolved:
        findings.append(
            f"path canonici dichiarati e NON risolvibili nel canonico dello "
            f"Stage 10: {unresolved[:5]}")

    # MUT-11-01 — il fabbisogno modellato e' RICALCOLATO dal `cash_flow` invece
    # di essere LETTO dal path canonico che `modeled_need_ref` NOMINA.
    cash = (modules_of(stage10).get("cash_flow") or {}).get("series") or {}
    if not cash:
        raise HarnessDefect(
            "il canonico dello Stage 10 non porta la serie di cash_flow: la "
            "mutazione MUT-11-01 non sarebbe costruibile")
    recomputed = str(-amount(cash[sorted(cash, key=int)[0]]))
    mutated = mutate(case["document"],
                     "funding_request.capital_requirement.modeled_need_amount",
                     recomputed)
    findings += rejects(probe(ctx, case, mutated, "m-s11-01"),
                        CODE_NON_CANONICAL, "MUT-11-01")

    # Ogni valore emesso risale al canonico: lo stato di governance si
    # PROPAGA e non si lava (workflow dello Stage 11, Passo 2), e una voce di
    # provenance non dichiara da se' periodo o checksum.
    def provenance_metadata(request):
        for entry in request["provenance"]:
            if entry["field"] == "requested_capital.amount":
                entry["period"] = 3
                entry["canonical_source_checksum"] = "0" * 64
    findings += projection_probes(ctx, case, (
        ("stato di governance lavato ad approved",
         setter("governance", {"source_validation_result": "PASS",
                               "source_propagated_status": "confirmed",
                               "source_investor_readiness": "ready",
                               "propagated_state": "approved"}),
         CODE_NON_CANONICAL),
        ("metadati di provenance AUTO-dichiarati", provenance_metadata,
         CODE_NON_CANONICAL)))
    return findings


def resolve_canonical(document, path):
    """Risolve un path canonico DICHIARATO in forma puntata con indici.

    Ritorna `(trovato, valore)`. E' la stessa disciplina del gate
    `derived_consistency.resolve_canonical`, riprodotta qui perche' l'harness
    non importa un modulo di produzione per una risoluzione di sola lettura.
    """
    node = document
    for step in str(path).split("."):
        match = re.match(r"^([^\[\]]*)((?:\[[^\[\]]+\])*)$", step)
        if not match:
            return False, None
        name, indexes = match.group(1), match.group(2)
        if name:
            if not isinstance(node, dict) or name not in node:
                return False, None
            node = node[name]
        for raw in re.findall(r"\[([^\[\]]+)\]", indexes):
            key = raw.strip("'\"")
            if isinstance(node, list):
                try:
                    node = node[int(key)]
                except (ValueError, IndexError):
                    return False, None
            elif isinstance(node, dict):
                if key not in node:
                    return False, None
                node = node[key]
            else:
                return False, None
    return True, node


# --------------------------------------------------------------------------
# FR-C-02 — T-FR-INPUT-COMPLETENESS
# --------------------------------------------------------------------------


def c02(ctx, base):
    """Ingresso incompleto ⇒ rifiuto PRIMA di qualunque scrittura: canonico,
    capitolo e workbook presenti e validati."""
    findings = []
    case = prepare(ctx, base, "c02")
    if not_built(case, findings,
                 "il gate di ingresso a tre artefatti non esiste, quindi un "
                 "ingresso incompleto non e' respinto prima della scrittura"):
        return findings
    findings += accepts(case["validated"], "(positivo) tre ingressi presenti")

    # MUT-11-02 — rimozione del WORKBOOK. Il rifiuto deve precedere qualunque
    # I/O: la cartella dello Stage 11 resta ESATTAMENTE com'era.
    project = clone(ctx, base, "c02-missing")
    stage10_paths(project)["workbook"].unlink()
    before = tree_hashes(Path(project) / STAGE11)
    built = run_builder(ctx, project, tx="tx-c02")
    if not built.get("available", True):
        findings.append(f"MUT-11-02: {built['reason']}")
        return findings
    if built.get("exit_code") != 1:
        findings.append(
            f"MUT-11-02: atteso exit 1 con workbook assente, ottenuto "
            f"{built.get('exit_code')}")
    if CODE_INPUT_INCOMPLETE not in (built.get("codes") or set()):
        findings.append(
            f"MUT-11-02: atteso il codice {CODE_INPUT_INCOMPLETE!r}, ottenuti "
            f"{sorted(built.get('codes') or ())}")
    named = " ".join(
        (built.get("messages_by_code") or {}).get(CODE_INPUT_INCOMPLETE, []))
    if WORKBOOK_NAME not in named and "workbook" not in named.lower():
        findings.append(
            "MUT-11-02: il rifiuto non NOMINA l'artefatto mancante: "
            f"{named[:200]!r}")
    if tree_hashes(Path(project) / STAGE11) != before:
        findings.append(
            "MUT-11-02: il rifiuto per ingresso incompleto ha SCRITTO nello "
            "Stage 11: il rifiuto deve precedere qualunque I/O")
    return findings


# --------------------------------------------------------------------------
# FR-C-03 — T-FR-POLICY-DECLARED
# --------------------------------------------------------------------------


def c03(ctx, base):
    """La politica di capitalizzazione e' DICHIARATA nell'output: misura di
    base, buffer, contingency, granularita' e arrotondamento."""
    findings = []
    case = prepare(ctx, base, "c03")
    if not_built(case, findings,
                 "nessun capital_requirement esiste, quindi la politica di "
                 "capitalizzazione non e' dichiarata da alcun portatore"):
        return findings
    findings += accepts(case["validated"], "(positivo) politica dichiarata")

    request = request_of(case["document"])
    capital = request.get("capital_requirement") or {}
    for key in ("modeled_need_ref", "buffer_component", "contingency_component",
                "timing_granularity", "policy_ref"):
        if key not in capital:
            findings.append(
                f"capital_requirement senza il componente NOMINATO {key!r}: "
                "un importo senza politica dichiarata e' irricevibile")
    rounding = (request.get("requested_capital") or {}).get("rounding_applied")
    if rounding is None:
        findings.append(
            "requested_capital.rounding_applied assente: l'arrotondamento e' "
            "il quinto componente della politica e va DICHIARATO")

    # Buffer — un `buffer_component` numerico POSITIVO sommato alla base
    # e' un FAIL, non un arrotondamento: i tre stati sono CHIUSI.
    state = (capital.get("buffer_component") or {}).get("state")
    if state not in ("included_in_base", "NOT_APPLICABLE", "absent"):
        findings.append(
            f"buffer_component.state fuori dai TRE stati chiusi: "
            f"{state!r}")

    # MUT-11-03 — `policy_ref` assente.
    findings += rejects(
        probe(ctx, case,
              drop(case["document"],
                   "funding_request.capital_requirement.policy_ref"),
              "m-s11-03"),
        CODE_POLICY_UNDECLARED, "MUT-11-03")

    # La granularita' dichiarata e' quella del
    # calendario canonico, non una scelta del documento sotto validazione.
    findings += projection_probes(ctx, case, (
        ("granularita' annual su calendario mensile",
         setter("capital_requirement.timing_granularity", "annual"),
         CODE_POLICY_UNDECLARED),))
    return findings


# --------------------------------------------------------------------------
# FR-C-04 — T-FR-CAPITAL-RECONCILIATION
# --------------------------------------------------------------------------


def c04(ctx, base):
    """`requested_capital` riconcilia al fabbisogno modellato sotto la politica
    selezionata, con gli addendi NOMINATI e sommati, a `EUR 0.01`."""
    findings = []
    case = prepare(ctx, base, "c04")
    if not_built(case, findings,
                 "nessuna riconciliazione del capitale richiesto esiste, "
                 "quindi il residuo non e' misurato contro alcuna tolleranza"):
        return findings
    findings += accepts(case["validated"], "(positivo) riconciliazione chiusa")

    request = request_of(case["document"])
    recon = (request.get("capital_requirement") or {}).get("reconciliation") \
        or {}
    for key in ("expected", "actual", "residual", "tolerance", "status"):
        if key not in recon:
            findings.append(
                f"la riconciliazione non riporta {key!r}: il residuo va "
                "riportato con expected, actual, residual e tolerance")
    if recon.get("tolerance") != "0.01":
        findings.append(
            f"tolleranza della riconciliazione del capitale: attesa '0.01' "
            f"(EUR), trovata {recon.get('tolerance')!r}")

    # Politica di capitalizzazione — la misura selezionata e' NOMINATA per esteso e la
    # riconciliazione quadra CONTRO QUELLA MISURA, non contro «il fabbisogno».
    need_ref = (request.get("capital_requirement") or {}).get(
        "modeled_need_ref")
    if not need_ref or "funding_gap" not in str(need_ref):
        findings.append(
            f"modeled_need_ref deve NOMINARE il path canonico della politica "
            f"di capitalizzazione: "
            f"{need_ref!r}")

    # MUT-11-04 — `requested_capital` alterato di EUR 0.02 senza toccare gli
    # addendi.
    requested = request.get("requested_capital") or {}
    altered = str(amount(requested.get("amount", 0)) + Decimal("0.02"))
    findings += rejects(
        probe(ctx, case,
              mutate(case["document"],
                     "funding_request.requested_capital.amount", altered),
              "m-s11-04"),
        CODE_CAPITAL_RECON, "MUT-11-04")

    # Ramo PRIMARIO della politica di capitalizzazione: con una
    # `cash_buffer_policy` dichiarata la base e' `funding_gap_to_buffer`, il
    # buffer e' ESPOSTO e mai sommato, e il fallback e' RESPINTO.
    primary = prepare(ctx, base, "c04-buffer", level="buffer")
    if not_built(primary, findings,
                 "la fixture a ramo PRIMARIO non produce alcuna funding "
                 "request"):
        return findings
    findings += accepts(primary["validated"], "(positivo) ramo primario")
    capital = request_of(primary["document"]).get("capital_requirement") or {}
    stage10 = stage10_document(primary)
    metrics = (modules_of(stage10).get("funding_gap") or {}).get("metrics") \
        or {}
    if not str(capital.get("modeled_need_ref") or "").endswith(
            "funding_gap_to_buffer"):
        findings.append(
            f"ramo primario: modeled_need_ref = "
            f"{capital.get('modeled_need_ref')!r} invece di "
            "funding_gap_to_buffer")
    if str((request_of(primary["document"]).get("requested_capital") or {})
           .get("amount")) != str(metrics.get("funding_gap_to_buffer")):
        findings.append(
            "ramo primario: il capitale richiesto non e' il letterale "
            "canonico di funding_gap_to_buffer")
    buffer_component = capital.get("buffer_component") or {}
    if buffer_component.get("state") != "included_in_base":
        findings.append(
            f"ramo primario: buffer_component.state = "
            f"{buffer_component.get('state')!r} invece di included_in_base")
    for addend in (capital.get("reconciliation") or {}).get("addends") or ():
        if addend.get("name") == "buffer_component" and \
                addend.get("role") != "exposure":
            findings.append(
                "ramo primario: il buffer compare fra gli addendi SOMMATI")
    fallback = mutate(primary["document"],
                      "funding_request.capital_requirement.modeled_need_ref",
                      "financial_plan.results.modules.funding_gap.metrics."
                      "funding_gap_to_zero")
    findings += rejects(probe(ctx, primary, fallback, "m-s11-04-fallback"),
                        CODE_CAPITAL_RECON,
                        "MUT-11-04 fallback con primaria disponibile")

    # Capitale riprezzato — il capitale richiesto riconcilia
    # al fabbisogno modellato SOTTO LA POLITICA SELEZIONATA, e non a se'
    # stesso: su OGNI ramo (fallback pieno, primario con buffer, copertura
    # nulla) un candidate internamente coerente con un capitale DIVERSO e'
    # respinto, qualunque derivazione dichiari la propria provenance.
    findings += capital_binding_probes(ctx, case, "full")
    findings += capital_binding_probes(ctx, primary, "buffer")
    uncovered = prepare(ctx, base, "c04-none", level="none")
    if not not_built(uncovered, findings, "la fixture a copertura nulla non "
                                          "produce alcuna funding request"):
        findings += accepts(uncovered["validated"],
                            "(positivo) copertura nulla")
        findings += capital_binding_probes(ctx, uncovered, "none")
    # Classe della proiezione — la valuta del capitale, il buffer
    # e la contingency sono quelli che la
    # politica fissa, anche quando la voce di provenance e' omessa; un
    # importo fuori scala e' respinto con attribuzione, non con un traceback.
    threshold = "financial_plan.results.modules.cash_buffer.metrics.threshold"
    findings += projection_probes(ctx, case, (
        ("valuta del capitale USD", setter("requested_capital.currency", "USD"),
         CODE_CAPITAL_RECON),
        ("importo di contingency con stato assente",
         setter("capital_requirement.contingency_component",
                {"state": "absent", "reason": "contingency stimata", "amount": "5000"}),
         CODE_CAPITAL_RECON),
        ("buffer incluso inventato sul fallback",
         setter("capital_requirement.buffer_component",
                {"state": "included_in_base", "amount": "20000",
                 "source_path": threshold, "reason": "x"}),
         CODE_CAPITAL_RECON),
        ("capitale richiesto fuori scala",
         setter("requested_capital.amount", "1E+1000000"),
         CODE_CAPITAL_RECON)))
    findings += projection_probes(ctx, primary, (
        ("buffer 999999 senza voce di provenance",
         without_provenance("capital_requirement.buffer_component.amount",
                            setter("capital_requirement.buffer_component."
                                   "amount", "999999")),
         CODE_CAPITAL_RECON),
        ("buffer absent sul ramo primario",
         without_provenance("capital_requirement.buffer_component.amount",
                            setter("capital_requirement.buffer_component",
                                   {"state": "absent", "reason": "x"})),
         CODE_CAPITAL_RECON)))
    findings += tm_chain(
        ctx, base, "cap-tm-capitale",
        lambda module, target: reprice(module, target, "1000",
                                       gap="0,00")[:2],
        (CODE_CAPITAL_RECON, CODE_RESIDUAL_GAP))
    return findings


def capital_binding_probes(ctx, case, level):
    """Capitale riprezzato — la RELAZIONE che `FR-C-04`, `FR-C-16` e `FR-C-01`
    fissano, non un importo d'esempio.

    Sotto la politica di capitalizzazione (`FR-CAPITAL-POLICY`, workflow
    dello Stage 11, Passo 3) il capitale richiesto e' la misura di
    fabbisogno SELEZIONATA, con il
    buffer ESPOSTO e mai sommato, la contingency ASSENTE e NESSUN
    arrotondamento; nessun portatore di finanziamento PARZIALE esiste (le
    tranche sono `not_supported`, `FR-C-13`) e la politica non ammette una
    contingency. Percio' OGNI capitale diverso dal fabbisogno e'
    un `FAIL` di `FR-C-04`, ANCHE quando il resto del documento e' reso
    coerente con esso: sottostimato, sovrastimato, parziale col gap ONESTO,
    o gonfiato da una contingency dichiarata. Un gap residuo dichiarato nullo
    o non numerico quando il capitale non copre il fabbisogno e' anche
    `FR-C-16`."""
    findings = []
    module = fr_module(ctx)
    if module is None:
        return [f"capitale ({level}): {MISSING_VALIDATOR}"]
    need = amount(request_of(case["document"])["capital_requirement"]
                  ["modeled_need_amount"])
    variants = [
        ("sottostimato-1000-gap-zero", "1000", "0"),
        ("sottostimato-1000-gap-non-numerico", "1000", "0,00"),
        ("sottostimato-meta-gap-zero", str(need / 2), "0"),
        ("parziale-coerente-gap-onesto", str(need / 2), None),
        ("sovrastimato", str(need + Decimal("5000000")), None),
    ]
    for label, requested, gap in variants:
        document, markdown, honest = reprice(module, case, requested, gap)
        verdict = probe_with_markdown(ctx, case, document, markdown,
                                      f"cap-{level}-{label}")
        findings += rejects(verdict, CODE_CAPITAL_RECON,
                            f"capitale ({level}) {label}")
        if gap is not None and honest > Decimal("0"):
            findings += rejects(verdict, CODE_RESIDUAL_GAP,
                                f"capitale ({level}) {label}: gap {gap!r} contro "
                                f"un gap reale {honest}")
    document, markdown, _ = reprice(module, case, str(need + Decimal("5000")),
                                    contingency="5000")
    findings += rejects(
        probe_with_markdown(ctx, case, document, markdown,
                            f"cap-{level}-contingency"),
        CODE_CAPITAL_RECON,
        f"capitale ({level}) contingency DICHIARATA fuori dalla politica")
    return findings


# --------------------------------------------------------------------------
# FR-C-05 — T-FR-ALLOCATION-SUM
# --------------------------------------------------------------------------


def c05(ctx, base):
    """`sum(use_of_proceeds[].amount) == requested_capital.amount`, entro
    `EUR 0.01`, e sempre `FAIL`, mai `WARNING`."""
    findings = []
    case = prepare(ctx, base, "c05")
    if not_built(case, findings,
                 "nessun use_of_proceeds esiste, quindi la somma degli "
                 "impieghi non e' confrontata col capitale richiesto"):
        return findings
    findings += accepts(case["validated"], "(positivo) somma degli impieghi")

    request = request_of(case["document"])
    index = first_use_index(request)
    altered = str(amount(request["use_of_proceeds"][index]["amount"]) +
                  Decimal("0.02"))
    verdict = probe(
        ctx, case,
        mutate(case["document"],
               f"funding_request.use_of_proceeds.{index}.amount", altered),
        "m-s11-05")
    findings += rejects(verdict, CODE_ALLOCATION_SUM, "MUT-11-05")
    for entry in (verdict.get("report") or {}).get("warnings") or ():
        if entry.get("code") == CODE_ALLOCATION_SUM:
            findings.append(
                "MUT-11-05: lo scostamento di allocazione e' stato declassato a "
                "WARNING: per questo codice esiste SOLO la forma FAIL")

    # DUE categorie eleggibili: la ripartizione chiude
    # ESATTAMENTE e ogni quota segue il peso canonico della propria categoria.
    multi = prepare(ctx, base, "c05-multi", hook=with_two_use_categories)
    if not_built(multi, findings,
                 "la variante a due categorie non produce alcuna funding "
                 "request"):
        return findings
    findings += accepts(multi["validated"], "(positivo) due categorie")
    request = request_of(multi["document"])
    uses = request.get("use_of_proceeds") or []
    if sorted(entry.get("category_id") for entry in uses) != \
            ["interest", "operating_cost"]:
        findings.append(
            f"due categorie eleggibili attese, emesse "
            f"{[entry.get('category_id') for entry in uses]}")
        return findings
    requested = amount(request["requested_capital"]["amount"])
    total = sum((amount(entry["amount"]) for entry in uses), Decimal("0"))
    if abs(total - requested) > Decimal("0.01"):
        findings.append(
            f"due categorie: somma degli impieghi {total} contro il capitale "
            f"richiesto {requested}")
    weights = {}
    for module in modules_of(stage10_document(multi)).values():
        for line in (module.get("lines") or []) if isinstance(module, dict) \
                else []:
            weights[line.get("category")] = weights.get(
                line.get("category"), Decimal("0")) + sum(
                (amount(value) for value in (line.get("series") or {})
                 .values()), Decimal("0"))
    share_total = weights.get("interest", Decimal("0")) + \
        weights.get("operating_cost", Decimal("0"))
    for entry in uses:
        expected = requested * weights.get(entry["category_id"],
                                           Decimal("0")) / share_total
        if abs(expected - amount(entry["amount"])) > Decimal("0.01"):
            findings.append(
                f"la quota di {entry['category_id']} ({entry['amount']}) non "
                f"segue il peso canonico dichiarato (attesa {expected})")
    findings += rejects(
        probe(ctx, multi,
              mutate(multi["document"],
                     "funding_request.use_of_proceeds.1.amount",
                     str(amount(uses[1]["amount"]) + Decimal("0.02"))),
              "m-s11-05-multi"),
        CODE_ALLOCATION_SUM, "MUT-11-05 seconda categoria")

    # Impieghi — una voce d'impiego sostiene la
    # tracciabilita' SOLO se e' essa stessa valida. La riconciliazione degli
    # aggregati e' NECESSARIA ma non SUFFICIENTE: coppie compensate `+X/-X`,
    # voci non numeriche o una ripartizione che devia dalla regola dichiarata
    # lasciano invariati gli aggregati, e non devono diventare letterali
    # dichiarati.
    findings += allocation_binding_probes(ctx, case, multi)
    findings += tm_chain(
        ctx, base, "imp-tm-compensate",
        lambda module, target: offset_uses(module, target, "5000000", "20",
                                           PLAIN_EXPLOIT),
        (CODE_ALLOCATION_SUM, CODE_CATEGORY, CODE_NARRATIVE,
         CODE_DERIVED_MISMATCH), named=("5000000", "20"))
    return findings


def allocation_binding_probes(ctx, case, multi):
    """Impieghi — la proprieta', su TRE valori compensati e
    sulle loro varianti: (a) la coppia `+X/+Y`, `-X/-Y` e' respinta (`FR-C-05`
    voce negativa) e X e Y restano NON TRACCIATI nella prosa, su entrambi i
    fronti; (b) una voce con importo e quota non numerici e' respinta anche
    se gli aggregati la ignorano; (c) una ripartizione fra DUE categorie che
    sposta importo dall'una all'altra lasciando invariati gli aggregati e'
    respinta, perche' ogni quota e' quella della regola dichiarata
    (`ALLOCATION_RULE`, `FR-C-07`); (d) il peso ZERO resta lecito: la
    variante a peso zero del motore e' ACCETTATA."""
    findings = []
    module = fr_module(ctx)
    if module is None:
        return [f"impieghi: {MISSING_VALIDATOR}"]
    for amount_value, percentage in OFFSET_VARIANTS:
        exploit = (f"La valutazione pre-money e' di {amount_value} EUR, a "
                   f"fronte di una diluizione del {percentage}%.")
        document, markdown = offset_uses(module, case, amount_value,
                                         percentage, exploit)
        label = f"impieghi compensata {amount_value}/{percentage}"
        verdict = probe_with_markdown(ctx, case, document, markdown,
                                      f"imp-{amount_value}")
        for code in (CODE_ALLOCATION_SUM, CODE_NARRATIVE,
                     CODE_DERIVED_MISMATCH):
            problems = rejects(verdict, code, label)
            findings += problems
            if not problems and code != CODE_ALLOCATION_SUM:
                findings += names_all(verdict, code,
                                      (amount_value, percentage), label)

    document = json.loads(json.dumps(case["document"]))
    origin = document["funding_request"]["use_of_proceeds"][0]
    extend_uses(document, [dict(origin, amount="5.000.000",
                                percentage="20,00")])
    markdown = rebuild_prose(module, document, stage10_document(case))
    verdict = probe_with_markdown(ctx, case, document, markdown,
                                  "imp-non-numerica")
    findings += rejects(verdict, CODE_ALLOCATION_SUM,
                        "impieghi voce con importo non numerico")
    findings += rejects(verdict, CODE_PERCENTAGE_SUM,
                        "impieghi voce con quota non numerica")

    if multi is not None and multi.get("document") is not None:
        document = json.loads(json.dumps(multi["document"]))
        uses = document["funding_request"]["use_of_proceeds"]
        requested = amount(document["funding_request"]["requested_capital"]
                           ["amount"])
        moved = amount(uses[0]["amount"]) + Decimal("1000")
        uses[0]["amount"] = str(moved)
        uses[1]["amount"] = str(requested - moved)
        uses[0]["percentage"] = str(moved / requested * Decimal("100"))
        uses[1]["percentage"] = str(Decimal("100") -
                                    moved / requested * Decimal("100"))
        markdown = rebuild_prose(module, document, stage10_document(multi))
        verdict = probe_with_markdown(ctx, multi, document, markdown,
                                      "imp-ripartizione")
        findings += rejects(verdict, CODE_ALLOCATION_SUM,
                            "impieghi ripartizione deviata a somma invariata")
        findings += rejects(verdict, CODE_NARRATIVE,
                            "impieghi ripartizione deviata: la quota spostata non "
                            "e' un letterale tracciato")

    zero = prepare(ctx, Path(case["project"]).parent, "imp-zero",
                   level="zero")
    if not not_built(zero, findings, "la variante a peso zero non produce "
                                     "alcuna funding request"):
        weights = [entry.get("amount") for entry in
                   request_of(zero["document"]).get("use_of_proceeds") or []]
        if not any(amount(value) == 0 for value in weights):
            findings.append(
                f"impieghi peso zero: precondizione — nessuna categoria a peso "
                f"zero nella variante ({weights})")
        findings += accepts(zero["validated"],
                            "(positivo impieghi/metamorfico) categoria a peso ZERO del "
                            "costruttore")
    return findings


# --------------------------------------------------------------------------
# FR-C-06 — T-FR-PERCENTAGE-SUM
# --------------------------------------------------------------------------


def c06(ctx, base):
    """`sum(use_of_proceeds[].percentage) == 100`, entro `ratio 1e-6`: la
    ridondanza importo/percentuale e' verificata su ENTRAMBI i lati."""
    findings = []
    case = prepare(ctx, base, "c06")
    if not_built(case, findings,
                 "nessuna percentuale di impiego esiste, quindi la ridondanza "
                 "importo/percentuale non e' verificata su alcun lato"):
        return findings
    findings += accepts(case["validated"], "(positivo) somma percentuale")

    request = request_of(case["document"])
    index = first_use_index(request)
    lowered = str(amount(request["use_of_proceeds"][index]["percentage"]) -
                  Decimal("0.1"))
    findings += rejects(
        probe(ctx, case,
              mutate(case["document"],
                     f"funding_request.use_of_proceeds.{index}.percentage",
                     lowered),
              "m-s11-06"),
        CODE_PERCENTAGE_SUM, "MUT-11-06")

    # Impieghi — una quota NEGATIVA compensata da
    # una positiva lascia la somma a 100 ma non e' una quota: e' respinta, e
    # la quota fabbricata non diventa un letterale che la prosa possa citare.
    module = fr_module(ctx)
    if module is None:
        findings.append(f"impieghi quote: {MISSING_VALIDATOR}")
        return findings
    for percentage in ("20", "7.5"):
        document = json.loads(json.dumps(case["document"]))
        origin = document["funding_request"]["use_of_proceeds"][0]
        extend_uses(document, [
            dict(origin, amount="0", percentage=percentage),
            dict(origin, amount="0", percentage=f"-{percentage}")])
        markdown = rebuild_prose(
            module, document, stage10_document(case),
            f"La diluizione per il lettore e' del {percentage}%.")
        verdict = probe_with_markdown(ctx, case, document, markdown,
                                      f"imp-quota-{percentage}")
        label = f"impieghi quota compensata {percentage}"
        findings += rejects(verdict, CODE_PERCENTAGE_SUM, label)
        problems = rejects(verdict, CODE_NARRATIVE, label)
        findings += problems
        if not problems:
            findings += names_all(verdict, CODE_NARRATIVE, (percentage,),
                                  label)
    return findings


# --------------------------------------------------------------------------
# FR-C-07 — T-FR-CATEGORY-TRACEABILITY
# --------------------------------------------------------------------------


def c07(ctx, base):
    """Ogni categoria di use-of-proceeds risale a un `category_id` di
    `use_of_proceeds_candidates` e ai suoi `driver_refs`."""
    findings = []
    case = prepare(ctx, base, "c07")
    if not_built(case, findings,
                 "nessun candidate_ref esiste, quindi nessuna categoria di "
                 "impiego risale ai candidati del canonico dello Stage 10"):
        return findings
    findings += accepts(case["validated"], "(positivo) categorie risolte")

    request = request_of(case["document"])
    stage10 = stage10_document(case)
    candidates = {
        entry.get("category_id")
        for entry in ((modules_of(stage10).get("funding_gap") or {})
                      .get("use_of_proceeds_candidates") or [])}
    for entry in request.get("use_of_proceeds") or ():
        if entry.get("candidate_ref") not in candidates:
            findings.append(
                f"candidate_ref {entry.get('candidate_ref')!r} non risolve nei "
                f"candidati del canonico: {sorted(c for c in candidates if c)}")

    index = first_use_index(request)
    invented = json.loads(json.dumps(case["document"]))
    target = invented["funding_request"]["use_of_proceeds"][index]
    target["category_id"] = "CAT-INVENTATA"
    target["candidate_ref"] = "CAT-INVENTATA"
    findings += rejects(probe(ctx, case, invented, "m-s11-07"),
                        CODE_CATEGORY, "MUT-11-07")

    # Impieghi — ogni candidato e' allocato UNA
    # volta sola: la stessa categoria spezzata in due voci POSITIVE, con
    # somme e quote che quadrano, fabbrica un importo (`20000`) che nessuna
    # regola dichiarata produce, ed e' respinta.
    module = fr_module(ctx)
    if module is None:
        findings.append(f"impieghi duplicato: {MISSING_VALIDATOR}")
        return findings
    document = json.loads(json.dumps(case["document"]))
    uses = document["funding_request"]["use_of_proceeds"]
    whole = amount(uses[index]["amount"])
    share = Decimal("20000") / whole * Decimal("100")
    extend_uses(document, [dict(uses[index], amount="20000",
                                percentage=str(share))])
    uses[index]["amount"] = str(whole - Decimal("20000"))
    uses[index]["percentage"] = str(amount(uses[index]["percentage"]) - share)
    markdown = rebuild_prose(module, document, stage10_document(case),
                             "Il marketing assorbe 20000 EUR.")
    verdict = probe_with_markdown(ctx, case, document, markdown,
                                  "imp-duplicato")
    findings += rejects(verdict, CODE_CATEGORY,
                        "impieghi stessa categoria in due voci")
    problems = rejects(verdict, CODE_NARRATIVE, "impieghi importo spezzato")
    findings += problems
    if not problems:
        findings += names_all(verdict, CODE_NARRATIVE, ("20000",),
                              "impieghi importo spezzato")

    # Classe della proiezione — categoria ed etichetta di una voce
    # sono quelle del candidato che la sostiene: scambiarle fra due voci, o
    # rinominarne una, attribuisce l'importo della regola a un'altra
    # categoria anche a somme e quote invariate.
    def swap(key):
        def change(request):
            first, second = request["use_of_proceeds"][:2]
            first[key], second[key] = second[key], first[key]
        return change
    findings += projection_probes(ctx, case, (
        ("categoria rinominata", setter("use_of_proceeds.0.category_id",
                                        "stipendi_fondatori"),
         CODE_CATEGORY),
        ("etichetta rinominata", setter("use_of_proceeds.0.label",
                                        "stipendi dei fondatori"),
         CODE_CATEGORY)))
    multi = prepare(ctx, base, "c07-two", hook=with_two_use_categories)
    if not not_built(multi, findings, "la variante a due categorie non "
                                      "produce alcuna funding request"):
        findings += projection_probes(ctx, multi, (
            ("categorie scambiate", swap("category_id"), CODE_CATEGORY),
            ("etichette scambiate", swap("label"), CODE_CATEGORY)))
    return findings


# --------------------------------------------------------------------------
# FR-C-08 — T-FR-HORIZON-MATCH
# --------------------------------------------------------------------------


def c08(ctx, base):
    """L'orizzonte dichiarato coincide con `results.calendar`, campo per
    campo."""
    findings = []
    case = prepare(ctx, base, "c08")
    if not_built(case, findings,
                 "nessun orizzonte e' dichiarato, quindi non e' confrontato "
                 "campo per campo con results.calendar"):
        return findings
    findings += accepts(case["validated"], "(positivo) orizzonte coincidente")

    request = request_of(case["document"])
    calendar = ((plan_of(stage10_document(case)).get("results") or {})
                .get("calendar") or {})
    horizon = request.get("horizon") or {}
    for key in ("anchor_date", "frequency", "horizon_periods"):
        if horizon.get(key) != calendar.get(key):
            findings.append(
                f"horizon.{key} = {horizon.get(key)!r} diverge da "
                f"results.calendar.{key} = {calendar.get(key)!r}")

    reduced = int(horizon.get("horizon_periods") or 0) - 1
    findings += rejects(
        probe(ctx, case,
              mutate(case["document"],
                     "funding_request.horizon.horizon_periods", reduced),
              "m-s11-08"),
        CODE_HORIZON, "MUT-11-08")
    return findings


# --------------------------------------------------------------------------
# FR-C-09 — T-FR-RUNWAY-BEFORE
# --------------------------------------------------------------------------


def c09(ctx, base):
    """Runway PRIMA del finanziamento letto dalle metriche canoniche:
    `runway_to_zero` e `runway_to_buffer` restano DUE grandezze distinte."""
    findings = []
    case = prepare(ctx, base, "c09")
    if not_built(case, findings,
                 "nessun runway ante-finanziamento esiste, quindi le due "
                 "misure canoniche non sono ne' lette ne' tenute distinte"):
        return findings
    findings += accepts(case["validated"], "(positivo) due misure distinte")

    request = request_of(case["document"])
    before = (request.get("runway") or {}).get("before_financing") or {}
    metrics = (modules_of(stage10_document(case)).get("runway") or {}) \
        .get("metrics") or {}
    for key in ("runway_to_zero", "runway_to_buffer"):
        if key not in before:
            findings.append(
                f"runway.before_financing senza {key!r}: collassare le due "
                "grandezze e' un difetto, non una semplificazione")
        elif str(before.get(key)) != str(metrics.get(key)):
            findings.append(
                f"runway.before_financing.{key} = {before.get(key)!r} diverge "
                f"dalla metrica canonica {metrics.get(key)!r}")

    # Politica di capitalizzazione — la misura scelta e' COERENTE con la base.
    measure = (request.get("runway") or {}).get("measure")
    need_ref = str((request.get("capital_requirement") or {}).get(
        "modeled_need_ref") or "")
    expected_measure = "to_buffer" if need_ref.endswith("funding_gap_to_buffer") \
        else "to_zero"
    if measure != expected_measure:
        findings.append(
            f"runway.measure = {measure!r} incoerente con la misura di base "
            f"selezionata dalla politica ({need_ref!r}): atteso "
            f"{expected_measure!r}")

    # MUT-11-09 — le due grandezze COLLASSATE in una.
    collapsed = mutate(case["document"],
                       "funding_request.runway.before_financing."
                       "runway_to_buffer", before.get("runway_to_zero"))
    findings += rejects(probe(ctx, case, collapsed, "m-s11-09"),
                        CODE_RUNWAY_BEFORE, "MUT-11-09")

    # Il LETTORE vede la misura selezionata e, sul fallback, la
    # dichiarazione della politica di capitalizzazione: la richiesta
    # e' costruita A CASSA ZERO e nessuna soglia di buffer era disponibile.
    sections = {entry.get("section_id"): str(entry.get("body") or "")
                for entry in (request.get("narrative") or {})
                .get("sections") or ()}
    reader_text = case["paths"]["request"].read_text(encoding="utf-8") \
        if case["paths"]["request"].is_file() else ""
    basis = str((request.get("sufficiency") or {}).get("basis") or "")
    for label, text in (("narrativa FR-S3", sections.get("FR-S3", "")),
                        (REQUEST_NAME, reader_text),
                        ("sufficiency.basis", basis)):
        if FALLBACK_DISCLOSURE not in text:
            findings.append(
                f"fallback: {label} non dichiara che la richiesta e' costruita "
                f"{FALLBACK_DISCLOSURE!r} (fallback della politica di "
                f"capitalizzazione)")
    hidden = json.loads(json.dumps(case["document"]))
    for entry in hidden["funding_request"]["narrative"]["sections"]:
        entry["body"] = str(entry.get("body") or "").replace(
            FALLBACK_DISCLOSURE, "")
    hidden["funding_request"]["sufficiency"]["basis"] = "misura to_zero"
    findings += rejects(probe(ctx, case, hidden, "m-s11-09-fallback"),
                        CODE_RESIDUAL_GAP,
                        "MUT-11-09 fallback non dichiarato al lettore")

    # Ramo PRIMARIO: il runway ante-finanziamento e' citato ALLA MISURA
    # SELEZIONATA, e non soltanto a cassa zero.
    primary = prepare(ctx, base, "c09-buffer", level="buffer")
    if not_built(primary, findings,
                 "la fixture a ramo PRIMARIO non produce alcuna funding "
                 "request"):
        return findings
    findings += accepts(primary["validated"], "(positivo) ramo primario")
    request = request_of(primary["document"])
    runway = request.get("runway") or {}
    to_buffer = (runway.get("before_financing") or {}).get("runway_to_buffer")
    if runway.get("measure") != "to_buffer":
        findings.append(
            f"ramo primario: runway.measure = {runway.get('measure')!r}")
    expected = f"{to_buffer} periodi alla misura to_buffer"
    sections = {entry.get("section_id"): str(entry.get("body") or "")
                for entry in (request.get("narrative") or {})
                .get("sections") or ()}
    reader_text = primary["paths"]["request"].read_text(encoding="utf-8") \
        if primary["paths"]["request"].is_file() else ""
    for label, text in (("narrativa FR-S3", sections.get("FR-S3", "")),
                        (REQUEST_NAME, reader_text)):
        if expected not in text:
            findings.append(
                f"ramo primario: {label} non cita il runway alla misura "
                f"selezionata ({expected!r}): {text[:200]!r}")
    if FALLBACK_DISCLOSURE in sections.get("FR-S3", ""):
        findings.append(
            "ramo primario: la narrativa dichiara un fallback a cassa zero che "
            "non e' scattato")
    return findings


# --------------------------------------------------------------------------
# FR-C-10 — T-FR-RUNWAY-AFTER
# --------------------------------------------------------------------------


def c10(ctx, base):
    """Runway DOPO il finanziamento riconcilia al flusso di cassa canonico,
    periodo per periodo, con tolleranza `count` ESATTA."""
    findings = []
    case = prepare(ctx, base, "c10")
    if not_built(case, findings,
                 "nessun runway post-finanziamento esiste, quindi non e' "
                 "ricostruito periodo per periodo dal flusso di cassa"):
        return findings
    findings += accepts(case["validated"], "(positivo) runway ricostruito")

    request = request_of(case["document"])
    after = (request.get("runway") or {}).get("after_financing") or {}
    if "periods" not in after:
        findings.append(
            "runway.after_financing senza `periods`: il runway finanziato non "
            "e' una stima narrativa")
    if str(after.get("tolerance") or "") not in ("0", ""):
        findings.append(
            f"la tolleranza del runway finanziato deve essere `count` ESATTA: "
            f"{after.get('tolerance')!r}")

    incremented = int(after.get("periods") or 0) + 1
    findings += rejects(
        probe(ctx, case,
              mutate(case["document"],
                     "funding_request.runway.after_financing.periods",
                     incremented),
              "m-s11-10"),
        CODE_RUNWAY_AFTER, "MUT-11-10")
    return findings


# --------------------------------------------------------------------------
# FR-C-11 — T-FR-MILESTONE-COSTED
# --------------------------------------------------------------------------


def c11(ctx, base):
    """Ogni milestone finanziata mappa a un `MIL-*` DATATO e COSTATO;
    `out_of_horizon_milestones` e' LETTO e DICHIARATO, e il residuo non mappato
    e' ESPOSTO, mai assorbito."""
    findings = []
    case = prepare(ctx, base, "c11", hook=with_milestone_coverage)
    if not_built(case, findings,
                 "nessun milestone_financing esiste, quindi le milestone "
                 "fuori orizzonte non sono ne' lette ne' dichiarate"):
        return findings
    findings += accepts(case["validated"], "(positivo) milestone costate")

    request = request_of(case["document"])
    stage10 = stage10_document(case)
    calendar = ((plan_of(stage10).get("results") or {}).get("calendar") or {})
    out_of_horizon = set(calendar.get("out_of_horizon_milestones") or [])
    financed = {entry.get("milestone_ref"): entry
                for entry in request.get("milestone_financing") or ()}
    for ref in sorted(out_of_horizon):
        entry = financed.get(ref)
        if entry is None:
            findings.append(
                f"la milestone fuori orizzonte {ref} non compare in "
                "milestone_financing: ignorarla sottostimerebbe in silenzio il "
                "fabbisogno")
            continue
        if not entry.get("out_of_horizon"):
            findings.append(
                f"{ref} e' in out_of_horizon_milestones ma non e' DICHIARATA "
                "tale nella funding request")
        if entry.get("target_date") is not None:
            findings.append(
                f"{ref} e' fuori orizzonte e riceve comunque una target_date "
                f"PLAUSIBILE {entry.get('target_date')!r}: una data fuori "
                f"orizzonte non si inventa")
    if "unmapped_residual" not in request.get("milestone_financing_summary",
                                              {}):
        findings.append(
            "milestone_financing_summary.unmapped_residual assente: il residuo "
            "non mappato va ESPOSTO, mai assorbito")

    # MUT-11-11 — milestone fuori orizzonte IGNORATA e costo omesso dai totali
    # senza dichiarazione.
    mutated = json.loads(json.dumps(case["document"]))
    entries = mutated["funding_request"].get("milestone_financing") or []
    dropped = None
    for position, entry in enumerate(entries):
        if entry.get("out_of_horizon"):
            dropped = entries.pop(position)
            break
    if dropped is None and entries:
        dropped = entries.pop(0)
    if dropped is None:
        findings.append(
            "nessuna milestone da rimuovere: la mutazione MUT-11-11 non e' "
            "costruibile su questa fixture")
        return findings
    findings += rejects(probe(ctx, case, mutated, "m-s11-11"),
                        CODE_MILESTONE_COST, "MUT-11-11")
    decisions = [entry.get("code") for entry in
                 (request.get("dependencies_and_assumptions") or {})
                 .get("decision_needed") or ()]
    if MILESTONE_DECISION in decisions:
        findings.append(
            f"{MILESTONE_DECISION} dichiarata benche' milestone_financing sia "
            "popolato dal canonico")

    # Classe della proiezione — il finanziamento delle
    # milestone e' quello della copertura canonica: nessun importo, nessuna
    # data diversa da quella proiettata, nessuna milestone dichiarata
    # finanziata se il canonico non lo dice, nessuna milestone aggiunta.
    def funded_claim(request):
        for entry in request["milestone_financing"]:
            if entry["milestone_ref"] == "MIL-002":
                entry["coverage_status"] = "funded"
                entry["financed_by"] = "requested_capital"

    def extra_milestone(request):
        request["milestone_financing"].append({
            "milestone_ref": "MIL-003", "target_date": "2026-06-30",
            "cost_ref": ["DRV-004"], "amount": "5000000",
            "coverage_status": "funded", "financed_by": "requested_capital",
            "out_of_horizon": False})
    findings += projection_probes(ctx, case, (
        ("importo inventato", setter("milestone_financing.0.amount",
                                     "5000000"), CODE_MILESTONE_COST),
        ("data non proiettata", setter("milestone_financing.0.target_date",
                                       "2031-12-31"), CODE_MILESTONE_COST),
        ("milestone dichiarata finanziata", funded_claim,
         CODE_MILESTONE_COST),
        ("milestone aggiunta", extra_milestone, CODE_MILESTONE_COST)))

    # Sul canonico prodotto dal motore
    # `milestone_coverage` e' NOT_APPLICABLE e `milestone_financing` e' vuoto:
    # il vuoto e' una decisione DICHIARATA e una riga per il lettore, mai un
    # silenzio.
    plain = prepare(ctx, base, "c11-na")
    if not_built(plain, findings,
                 "la fixture senza copertura delle milestone non produce "
                 "alcuna funding request"):
        return findings
    findings += accepts(plain["validated"], "(positivo) gap di milestone")
    request = request_of(plain["document"])
    if request.get("milestone_financing"):
        findings.append(
            "la fixture F-1 porta milestone_financing popolato: il caso del "
            "gap non e' misurabile")
    decisions = [entry.get("code") for entry in
                 (request.get("dependencies_and_assumptions") or {})
                 .get("decision_needed") or ()]
    if MILESTONE_DECISION not in decisions:
        findings.append(
            f"milestone_financing e' vuoto e decision_needed non porta "
            f"{MILESTONE_DECISION}: il gap non e' esposto")
    reader_text = plain["paths"]["request"].read_text(encoding="utf-8") \
        if plain["paths"]["request"].is_file() else ""
    if "milestone_coverage" not in reader_text or \
            "## Milestone" not in reader_text:
        findings.append(
            f"{REQUEST_NAME} non dichiara al lettore che nessuna milestone e' "
            "collegata al capitale richiesto")
    silenced = json.loads(json.dumps(plain["document"]))
    block = silenced["funding_request"]["dependencies_and_assumptions"]
    block["decision_needed"] = [entry for entry in block["decision_needed"]
                                if entry.get("code") != MILESTONE_DECISION]
    findings += rejects(probe(ctx, plain, silenced, "m-s11-11-gap"),
                        CODE_MILESTONE_COST,
                        "MUT-11-11 gap di milestone non dichiarato")
    return findings


# --------------------------------------------------------------------------
# FR-C-12 — T-FR-MILESTONE-IN-ROADMAP
# --------------------------------------------------------------------------


def c12(ctx, base):
    """Nessun claim di milestone non risalente alla roadmap: ogni
    `milestone_ref` risolve contro il registro REALE, non contro una lista
    locale."""
    findings = []
    case = prepare(ctx, base, "c12", hook=with_milestone_coverage)
    if not_built(case, findings,
                 "nessun milestone_ref e' emesso, quindi nessuna risoluzione "
                 "contro la roadmap dello Stage 9 e' esercitata"):
        return findings
    findings += accepts(case["validated"], "(positivo) milestone risolte")

    request = request_of(case["document"])
    entries = request.get("milestone_financing") or []
    if not entries:
        findings.append(
            "nessuna milestone finanziata: la mutazione MUT-11-12 non sarebbe "
            "costruibile")
        return findings
    findings += rejects(
        probe(ctx, case,
              mutate(case["document"],
                     "funding_request.milestone_financing.0.milestone_ref",
                     "MIL-999"),
              "m-s11-12"),
        CODE_MILESTONE_ROADMAP, "MUT-11-12")
    return findings


# --------------------------------------------------------------------------
# FR-C-13 — T-FR-TRANCHE-SUPPORT
# --------------------------------------------------------------------------


def c13(ctx, base):
    """Tranche o rilascio a stadi SOLO dove supportato: altrimenti
    `not_supported` esplicito. Uno schedule di finanziamento NON si inventa."""
    findings = []
    case = prepare(ctx, base, "c13")
    if not_built(case, findings,
                 "nessun portatore di tranche esiste, quindi lo stato "
                 "not_supported non e' dichiarato da alcun campo"):
        return findings
    findings += accepts(case["validated"], "(positivo) tranche dichiarate")

    request = request_of(case["document"])
    tranches = request.get("tranches") or []
    if not tranches:
        findings.append(
            "tranches[] assente: l'assenza di uno schedule va DICHIARATA, non "
            "omessa")
    for entry in tranches:
        if entry.get("support") not in ("supported", "not_supported"):
            findings.append(
                f"tranche con support fuori dall'enum chiuso: "
                f"{entry.get('support')!r}")

    # MUT-11-13 — tranche con importi e date INVENTATE.
    mutated = json.loads(json.dumps(case["document"]))
    mutated["funding_request"]["tranches"] = [{
        "tranche_id": "TR-001", "support": "not_supported",
        "amount": "250000.00", "target_date": "2027-03-31",
        "trigger": "chiusura del round"}]
    findings += rejects(probe(ctx, case, mutated, "m-s11-13"),
                        CODE_TRANCHE, "MUT-11-13")

    # Classe della proiezione — nessun portatore canonico
    # espone uno schedule: una tranche DICHIARATA supportata con importo e
    # data inventati, o la dichiarazione not_supported rimossa, sono respinte
    # e non raggiungono la pubblicazione del Transaction Manager REALE.
    fabricated = [{"tranche_id": "TR-001", "support": "supported",
                   "reason": "prima tranche", "amount": "5000000",
                   "target_date": "2027-01-31",
                   "source_path": "financial_plan.results.modules."
                                  "funding_gap"}]
    findings += projection_probes(ctx, case, (
        ("tranche supportata inventata", setter("tranches", fabricated),
         CODE_TRANCHE),
        ("dichiarazione not_supported rimossa", setter("tranches", []),
         CODE_TRANCHE)))

    def invented_schedule(module, target):
        document = json.loads(json.dumps(target["document"]))
        request = document["funding_request"]
        request["tranches"] = json.loads(json.dumps(fabricated))
        request["scenario_sensitivity"]["base"][
            "requested_capital_delta"] = "5000000"
        request["governance"]["propagated_state"] = "approved"
        return document, rebuild_prose(module, document,
                                       stage10_document(target))
    findings += tm_chain(ctx, base, "proiezione-tm", invented_schedule,
                         (CODE_TRANCHE, CODE_SCENARIO_FABRICATED,
                          CODE_NON_CANONICAL))
    return findings


# --------------------------------------------------------------------------
# FR-C-14 — T-FR-SCENARIO-IDS
# --------------------------------------------------------------------------


def c14(ctx, base):
    """Le cifre di scenario mappano agli STESSI identificatori canonici
    `base`, `downside`, `upside` — minuscoli, sull'enum canonico."""
    findings = []
    case = prepare(ctx, base, "c14")
    if not_built(case, findings,
                 "nessuna scenario_sensitivity esiste, quindi gli id di "
                 "scenario non sono confrontati con l'enum canonico"):
        return findings
    findings += accepts(case["validated"], "(positivo) id di scenario")

    request = request_of(case["document"])
    sensitivity = request.get("scenario_sensitivity") or {}
    declared = sorted(key for key in sensitivity if key != "coverage_level")
    if declared != sorted(SCENARIO_IDS):
        findings.append(
            f"scenario_sensitivity porta {declared} invece dei tre id "
            f"canonici {sorted(SCENARIO_IDS)}")
    for name in SCENARIO_IDS:
        entry = sensitivity.get(name) or {}
        if entry.get("scenario") != name:
            findings.append(
                f"scenario_sensitivity.{name}.scenario = "
                f"{entry.get('scenario')!r}: l'id deve coincidere con l'enum "
                "canonico")

    findings += rejects(
        probe(ctx, case,
              mutate(case["document"],
                     "funding_request.scenario_sensitivity.base.scenario",
                     "Base"),
              "m-s11-14"),
        CODE_SCENARIO_ID, "MUT-11-14")
    return findings


# --------------------------------------------------------------------------
# FR-C-15 — T-FR-SCENARIO-NOT-FABRICATED
# --------------------------------------------------------------------------


def c15(ctx, base):
    """Con `coverage.level == "none"` gli scenari `downside`/`upside` restano
    `NOT_APPLICABLE`: NON prodotti, NON etichettati.

    «Non abbiamo dati per testare il peggio», mai «il peggio non cambia
    nulla». `COND-S10-SCENARIO-COVERAGE` e' DIFFERITA con motivazione, e il
    differimento non modifica questo contratto: ne fissa il contesto di
    ammissibilita'.
    """
    findings = []
    case = prepare(ctx, base, "c15", level="none")
    if not_built(case, findings,
                 "nessuno scenario e' emesso, quindi con copertura `none` non "
                 "esiste alcun NOT_APPLICABLE dichiarato da misurare"):
        return findings
    findings += accepts(case["validated"], "(positivo) copertura none")

    request = request_of(case["document"])
    sensitivity = request.get("scenario_sensitivity") or {}
    for name in ("downside", "upside"):
        entry = sensitivity.get(name) or {}
        if entry.get("status") != "NOT_APPLICABLE":
            findings.append(
                f"con coverage.level == none lo scenario {name} ha status "
                f"{entry.get('status')!r} invece di NOT_APPLICABLE")
        if not str(entry.get("not_applicable_reason") or "").strip():
            findings.append(
                f"lo scenario {name} NOT_APPLICABLE senza motivazione NOMINATA")
    decisions = [
        entry.get("code")
        for entry in ((request.get("dependencies_and_assumptions") or {})
                      .get("decision_needed") or [])]
    if not any("SCENARIO-COVERAGE" in str(code).upper() for code in decisions):
        findings.append(
            "decision_needed[] non NOMINA COND-S10-SCENARIO-COVERAGE: il "
            "differimento va dichiarato, non assorbito")

    # MUT-11-15 — TRE serie identiche emesse con etichette differenziate.
    mutated = json.loads(json.dumps(case["document"]))
    base_entry = mutated["funding_request"]["scenario_sensitivity"]["base"]
    for name in ("downside", "upside"):
        fabricated = json.loads(json.dumps(base_entry))
        fabricated["scenario"] = name
        fabricated.pop("not_applicable_reason", None)
        mutated["funding_request"]["scenario_sensitivity"][name] = fabricated
    findings += rejects(probe(ctx, case, mutated, "m-s11-15"),
                        CODE_SCENARIO_FABRICATED, "MUT-11-15")

    # Classe della proiezione — nessun portatore
    # canonico espone un fabbisogno SCALARE per scenario (decisione
    # FR-SCENARIO-CAPITAL-DELTA): un delta di capitale e' fabbricato anche
    # sullo scenario base e anche con copertura piena.
    findings += projection_probes(ctx, case, (
        ("delta di capitale sullo scenario base",
         setter("scenario_sensitivity.base.requested_capital_delta",
                "5000000"), CODE_SCENARIO_FABRICATED),))
    covered = prepare(ctx, base, "c15-full")
    if not not_built(covered, findings, "la fixture a copertura piena non "
                                        "produce alcuna funding request"):
        findings += projection_probes(ctx, covered, (
            ("delta di capitale con copertura piena",
             setter("scenario_sensitivity.downside.requested_capital_delta",
                    "-3000"), CODE_SCENARIO_FABRICATED),))
    return findings


# --------------------------------------------------------------------------
# FR-C-16 — T-FR-RESIDUAL-GAP-DISCLOSED
# --------------------------------------------------------------------------


def c16(ctx, base):
    """Sufficienza e GAP RESIDUO sempre esposti: `residual_gap_disclosed` e'
    obbligatorio e vincolato a `true`. Emettere nascondendo il gap e'
    STRUTTURALMENTE impossibile."""
    findings = []
    case = prepare(ctx, base, "c16")
    if not_built(case, findings,
                 "nessuna sufficiency esiste, quindi il gap residuo non e' ne' "
                 "esposto ne' vincolato a una dichiarazione obbligatoria"):
        return findings
    findings += accepts(case["validated"], "(positivo) gap esposto")

    sufficiency = request_of(case["document"]).get("sufficiency") or {}
    if sufficiency.get("residual_gap_disclosed") is not True:
        findings.append(
            "residual_gap_disclosed deve valere true e non puo' valere altro: "
            f"{sufficiency.get('residual_gap_disclosed')!r}")
    if "residual_gap" not in sufficiency:
        findings.append(
            "sufficiency senza residual_gap: il gap va riportato anche quando "
            "vale 0")

    # MUT-11-16 (a) — rimozione del campo.
    findings += rejects(
        probe(ctx, case,
              drop(case["document"],
                   "funding_request.sufficiency.residual_gap_disclosed"),
              "m-s11-16a"),
        CODE_RESIDUAL_GAP, "MUT-11-16 (a) campo rimosso")
    # MUT-11-16 (b) — gap positivo NON dichiarato.
    hidden = mutate(case["document"],
                    "funding_request.sufficiency.residual_gap_disclosed", False)
    hidden = mutate(hidden, "funding_request.sufficiency.residual_gap",
                    "120000.00")
    findings += rejects(probe(ctx, case, hidden, "m-s11-16b"),
                        CODE_RESIDUAL_GAP, "MUT-11-16 (b) gap non dichiarato")

    # Capitale e gap — il gap residuo e' quello che il
    # validator RICOSTRUISCE dal flusso di cassa canonico al capitale che la
    # politica fissa, nella sua resa canonica: un gap NON NUMERICO non salta
    # il confronto, e una resa diversa dello stesso valore non diventa un
    # letterale dichiarato. Narrativa e derivato sono ricostruiti con le
    # funzioni di produzione, cosi' che il solo difetto sia il campo.
    module = fr_module(ctx)
    if module is None:
        findings.append(f"capitale gap: {MISSING_VALIDATOR}")
        return findings
    for gap in ("0,00", "0.00", "NaN", "zero", "1E+1000000"):
        document = mutate(case["document"],
                          "funding_request.sufficiency.residual_gap", gap)
        markdown = rebuild_prose(module, document, stage10_document(case))
        verdict = probe_with_markdown(ctx, case, document, markdown,
                                      f"cap-gap-{gap}")
        findings += rejects(verdict, CODE_RESIDUAL_GAP,
                            f"capitale gap residuo dichiarato {gap!r}")
        if "Traceback" in (verdict.get("stderr") or ""):
            findings.append(f"capitale gap residuo {gap!r}: traceback invece di un "
                            "rifiuto attribuito")
    return findings


# --------------------------------------------------------------------------
# FR-C-17 — T-FR-NO-INVENTED-TERMS
# --------------------------------------------------------------------------


def c17(ctx, base):
    """Nessuna valutazione, diluizione, strumento, prezzo o termine INVENTATO.
    Il test negativo e' ESPLICITO PER CIASCUNO dei sette."""
    findings = []
    case = prepare(ctx, base, "c17")
    if not_built(case, findings,
                 "nessun documento e' emesso, quindi i sette termini vietati "
                 "non sono respinti ne' strutturalmente ne' per contratto"):
        return findings
    findings += accepts(case["validated"], "(positivo) nessun termine inventato")

    for term in INVENTABLE_TERMS:
        mutated = json.loads(json.dumps(case["document"]))
        mutated["funding_request"][term] = 4000000
        verdict = probe(ctx, case, mutated, f"m-s11-17-{term}")
        problems = rejects(verdict, CODE_INVENTED_TERMS, f"MUT-11-17 {term}")
        if problems:
            findings += problems
            continue
        named = " ".join(
            (verdict.get("messages_by_code") or {}).get(CODE_INVENTED_TERMS,
                                                        []))
        refs = " ".join(str(ref) for ref in
                        (verdict.get("refs_by_code") or {}).get(
                            CODE_INVENTED_TERMS, []))
        if term not in named and term not in refs:
            findings.append(
                f"MUT-11-17 {term}: il rifiuto non NOMINA il termine iniettato")
    return findings


# --------------------------------------------------------------------------
# FR-C-18 — T-FR-DECISION-NEEDED
# --------------------------------------------------------------------------


def c18(ctx, base):
    """Termine ignoto ⇒ stato `decision_needed` DICHIARATO, mai un valore
    plausibile. `funding_type`, `primary_reader` e `development_stage` si
    LEGGONO da `shared/startup-profile.json` e non si inferiscono MAI."""
    findings = []
    case = prepare(ctx, base, "c18")
    if not_built(case, findings,
                 "nessun decision_needed esiste, quindi un termine ignoto non "
                 "riceve uno stato dichiarato e il profilo non e' letto"):
        return findings
    findings += accepts(case["validated"], "(positivo) termini ignoti dichiarati")

    request = request_of(case["document"])
    reader = request.get("reader_context") or {}
    profile_path = Path(case["project"]) / "shared" / "startup-profile.json"
    if profile_path.is_file():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        for key in ("funding_type", "primary_reader", "development_stage"):
            if reader.get(key) != profile.get(key):
                findings.append(
                    f"reader_context.{key} = {reader.get(key)!r} non coincide "
                    f"col profilo LETTO {profile.get(key)!r}")
    else:
        for key in ("funding_type", "primary_reader", "development_stage"):
            if reader.get(key) is not None:
                findings.append(
                    f"shared/startup-profile.json e' ASSENTE ma "
                    f"reader_context.{key} porta {reader.get(key)!r}: il "
                    "profilo si LEGGE, non si INFERISCE")
        decisions = [
            str(entry.get("code"))
            for entry in ((request.get("dependencies_and_assumptions") or {})
                          .get("decision_needed") or [])]
        if not any("PROFILE" in code.upper() for code in decisions):
            findings.append(
                "profilo assente e nessun decision_needed lo dichiara: sarebbe "
                "un'inferenza silenziosa")

    # MUT-11-18 (a) — valore PLAUSIBILE al posto della voce decision_needed.
    mutated = json.loads(json.dumps(case["document"]))
    mutated["funding_request"]["dependencies_and_assumptions"][
        "decision_needed"] = []
    findings += rejects(probe(ctx, case, mutated, "m-s11-18a"),
                        CODE_DECISION_NEEDED, "MUT-11-18 (a) voce rimossa")
    # MUT-11-18 (b) — `funding_type` INFERITO invece che letto dal profilo.
    inferred = mutate(case["document"],
                      "funding_request.reader_context.funding_type", "equity")
    inferred = mutate(inferred, "funding_request.reader_context.profile_ref",
                      "inferito dal contesto")
    findings += rejects(probe(ctx, case, inferred, "m-s11-18b"),
                        CODE_DECISION_NEEDED, "MUT-11-18 (b) profilo inferito")

    # I termini finanziari IGNOTI (strumento,
    # valutazione pre/post-money, diluizione, dimensione del round, condizioni)
    # sono DECISIONI APERTE dichiarate, con e senza profilo, e l'affermazione
    # dell'handoff canonico che li dichiara e' VERA.
    profiled = prepare(ctx, base, "c18-profile", hook=with_startup_profile)
    if not_built(profiled, findings,
                 "la fixture a profilo PRESENTE non produce alcuna funding "
                 "request"):
        return findings
    findings += accepts(profiled["validated"], "(positivo) profilo presente")
    reader = request_of(profiled["document"]).get("reader_context") or {}
    for key in ("funding_type", "primary_reader", "development_stage"):
        if reader.get(key) != STARTUP_PROFILE[key]:
            findings.append(
                f"profilo presente: reader_context.{key} = {reader.get(key)!r}"
                f" invece del valore LETTO {STARTUP_PROFILE[key]!r}")
    for label, current in (("profilo assente", case),
                           ("profilo presente", profiled)):
        decisions = {
            entry.get("code"): entry for entry in
            (request_of(current["document"]).get(
                "dependencies_and_assumptions") or {})
            .get("decision_needed") or ()}
        for code in TERM_DECISIONS:
            entry = decisions.get(code)
            if entry is None:
                findings.append(
                    f"{label}: il termine ignoto {code} non e' una decisione "
                    "DICHIARATA in decision_needed")
            elif not str(entry.get("question") or "").strip():
                findings.append(f"{label}: {code} senza domanda")
        handoff = current["paths"]["handoff"].read_text(encoding="utf-8") \
            if current["paths"]["handoff"].is_file() else ""
        missing = [code for code in TERM_DECISIONS if code not in handoff]
        if missing:
            findings.append(
                f"{label}: l'handoff canonico afferma che i termini ignoti sono "
                f"dichiarati ma non NOMINA {missing}")
    for code in TERM_DECISIONS:
        dropped = json.loads(json.dumps(profiled["document"]))
        block = dropped["funding_request"]["dependencies_and_assumptions"]
        block["decision_needed"] = [entry for entry in block["decision_needed"]
                                    if entry.get("code") != code]
        verdict = probe(ctx, profiled, dropped, f"m-s11-18-{code.lower()}")
        problems = rejects(verdict, CODE_DECISION_NEEDED,
                           f"MUT-11-18 termine {code} rimosso")
        findings += problems
        if not problems and code not in named_in(verdict,
                                                 CODE_DECISION_NEEDED):
            findings.append(
                f"MUT-11-18 termine {code} rimosso: il rifiuto non NOMINA il "
                "termine")
    return findings


# --------------------------------------------------------------------------
# FR-C-19 — T-FR-NO-ASSUMPTION-PROMOTED
# --------------------------------------------------------------------------


def c19(ctx, base):
    """Nessuna assunzione trattata in silenzio come fatto validato:
    `unvalidated_count` e' confrontato contro `shared/assumptions-register.json`
    REALE, non contro una copia."""
    findings = []
    case = prepare(ctx, base, "c19")
    if not_built(case, findings,
                 "nessun unvalidated_count e' emesso, quindi nessuna "
                 "assunzione e' confrontata col registro ufficiale"):
        return findings
    findings += accepts(case["validated"], "(positivo) conteggio coerente")

    request = request_of(case["document"])
    register = json.loads(
        (Path(case["project"]) / "shared" / "assumptions-register.json")
        .read_text(encoding="utf-8"))
    refs = set((request.get("dependencies_and_assumptions") or {})
               .get("assumption_refs") or ())
    expected = sum(1 for entry in register
                   if entry.get("id") in refs
                   and entry.get("validation_status") != "validated")
    declared = (request.get("dependencies_and_assumptions") or {}) \
        .get("unvalidated_count")
    if declared != expected:
        findings.append(
            f"unvalidated_count = {declared!r} invece di {expected!r}, "
            "ricalcolato sul registro ufficiale")

    findings += rejects(
        probe(ctx, case,
              mutate(case["document"],
                     "funding_request.dependencies_and_assumptions."
                     "unvalidated_count", 0),
              "m-s11-19"),
        CODE_ASSUMPTION_PROMOTED, "MUT-11-19")

    # Conteggio delle assunzioni — un letterale dichiarato e' la
    # derivazione del VALIDATOR, non del documento sotto validazione: omettere
    # assunzioni da `assumption_refs` e dichiarare il conteggio COERENTE con
    # l'elenco ridotto fabbrica un numero (`3`) che il registro ufficiale non
    # produce. E' respinto, e la prosa che lo cita non e' tracciata.
    module = fr_module(ctx)
    if module is None:
        findings.append(f"conteggio: {MISSING_VALIDATOR}")
    else:
        unvalidated = sorted(
            entry.get("id") for entry in register
            if entry.get("id") in refs
            and entry.get("validation_status") != "validated")
        if len(unvalidated) <= 3:
            findings.append(
                f"conteggio: precondizione — la fixture porta solo "
                f"{len(unvalidated)} assunzioni non validate")
        else:
            document = json.loads(json.dumps(case["document"]))
            block = document["funding_request"]["dependencies_and_assumptions"]
            block["assumption_refs"] = unvalidated[:3]
            block["unvalidated_count"] = 3
            markdown = rebuild_prose(module, document, stage10_document(case))
            verdict = probe_with_markdown(ctx, case, document, markdown,
                                          "tok-conteggio")
            findings += rejects(verdict, CODE_ASSUMPTION_PROMOTED,
                                "conteggio fabbricato da assumption_refs "
                                "ridotti")
            findings += rejects(verdict, CODE_NARRATIVE,
                                "conteggio fabbricato: la prosa non e' "
                                "tracciata")

    # Forma canonica degli id, fronte delle ASSUNZIONI — un alias `ASS-0001` nel
    # registro UFFICIALE non e' scartato in silenzio da assumption_refs (che
    # abbasserebbe unvalidated_count): e' RICONOSCIUTO e RESPINTO con codice
    # attribuito, in costruzione E in egress.
    project = clone(ctx, base, "c19-alias")
    path = Path(project) / ASSUMPTIONS_REGISTER_REL
    entries = json.loads(path.read_text(encoding="utf-8"))
    alias = dict(entries[0])
    alias["id"] = NON_CANONICAL_ASS
    path.write_text(json.dumps(entries + [alias], indent=2,
                               ensure_ascii=True), encoding="utf-8")
    built = run_builder(ctx, project, tx="tx-c19-alias")
    problems = rejects(built, CODE_ASSUMPTION_PROMOTED,
                       "MUT-11-19 alias di assunzione nel registro (build)")
    findings += problems
    if not problems and NON_CANONICAL_ASS not in named_in(
            built, CODE_ASSUMPTION_PROMOTED):
        findings.append(
            f"MUT-11-19 (build): il rifiuto non NOMINA {NON_CANONICAL_ASS}")
    if stage11_paths(project, "tx-c19-alias")["canonical"].is_file():
        findings.append(
            "MUT-11-19 (build): canonico dello Stage 11 SCRITTO nonostante "
            "l'alias nel registro")
    reference = Path(case["project"]) / ASSUMPTIONS_REGISTER_REL
    original = reference.read_bytes()
    reference.write_text(json.dumps(register + [alias], indent=2,
                                    ensure_ascii=True), encoding="utf-8")
    try:
        verdict = run_validator(ctx, case["project"],
                                case["paths"]["candidate"])
    finally:
        reference.write_bytes(original)
    problems = rejects(verdict, CODE_ASSUMPTION_PROMOTED,
                       "MUT-11-19 alias di assunzione nel registro (egress)")
    findings += problems
    if not problems and NON_CANONICAL_ASS not in named_in(
            verdict, CODE_ASSUMPTION_PROMOTED):
        findings.append(
            f"MUT-11-19 (egress): il rifiuto non NOMINA {NON_CANONICAL_ASS}")
    return findings


# --------------------------------------------------------------------------
# FR-C-20 — T-FR-NO-FALSE-PRECISION
# --------------------------------------------------------------------------


def c20(ctx, base):
    """Nessuna falsa precisione: `rounding_applied` dichiarato, e una cifra
    arrotondata non e' ripresentata con decimali."""
    findings = []
    case = prepare(ctx, base, "c20")
    if not_built(case, findings,
                 "nessun rounding_applied e' dichiarato, quindi la coerenza "
                 "fra politica e cifre emesse non e' misurabile"):
        return findings
    findings += accepts(case["validated"], "(positivo) nessuna falsa precisione")

    requested = request_of(case["document"]).get("requested_capital") or {}
    # La politica di capitalizzazione non applica alcun arrotondamento: il
    # valore dichiarato deve percio' essere `none`.
    if requested.get("rounding_applied") != "none":
        findings.append(
            f"rounding_applied = {requested.get('rounding_applied')!r}: sotto "
            "la politica di capitalizzazione l'arrotondamento e' NESSUNO e va "
            "dichiarato `none`")

    mutated = mutate(case["document"],
                     "funding_request.requested_capital.rounding_applied",
                     "nearest_thousand")
    findings += rejects(probe(ctx, case, mutated, "m-s11-20"),
                        CODE_FALSE_PRECISION, "MUT-11-20")
    return findings


# --------------------------------------------------------------------------
# FR-C-21 — T-FR-PROVENANCE-TOTAL
# --------------------------------------------------------------------------


def c21(ctx, base):
    """Ogni campo numerico ha una voce `provenance[]`: path canonico, scenario,
    periodo, unita', valuta, checksum. Il join campi x provenienza ha residuo
    ZERO.

    Qui vive anche il fronte FAIL-CLOSED della forma canonica degli id: un
    `EVD-0021` — valido per il registro base, NON canonico — e' RICONOSCIUTO
    e RESPINTO con
    codice ATTRIBUITO, mai normalizzato, troncato o riscritto.
    """
    findings = []
    case = prepare(ctx, base, "c21", hook=with_evidence_registers)
    if not_built(case, findings,
                 "nessuna provenance[] esiste, quindi il join fra campi "
                 "numerici e provenienza non ha residuo da misurare"):
        return findings
    findings += accepts(case["validated"], "(positivo) provenienza totale")

    request = request_of(case["document"])
    provenance = request.get("provenance") or []
    for entry in provenance:
        for key in ("field", "canonical_path", "scenario", "period", "unit",
                    "currency", "canonical_source_checksum"):
            if key not in entry:
                findings.append(
                    f"voce di provenance senza {key!r}: {entry.get('field')!r}")
                break

    # MUT-11-21 (a) — un campo numerico SENZA provenienza.
    mutated = json.loads(json.dumps(case["document"]))
    entries = mutated["funding_request"]["provenance"]
    if not entries:
        findings.append("provenance[] vuota: MUT-11-21 non e' costruibile")
        return findings
    entries.pop(0)
    findings += rejects(probe(ctx, case, mutated, "m-s11-21a"),
                        CODE_PROVENANCE, "MUT-11-21 (a) provenienza rimossa")

    # MUT-11-21 (b) — id di evidenza in forma NON canonica.
    aliased = json.loads(json.dumps(case["document"]))
    index = aliased["funding_request"].setdefault(
        "evidence_index", {"evidence_refs": [], "source_refs": []})
    index["evidence_refs"] = [NON_CANONICAL_EVD]
    verdict = probe(ctx, case, aliased, "m-s11-21b")
    problems = rejects(verdict, CODE_PROVENANCE,
                       "MUT-11-21 (b) alias non canonico")
    findings += problems
    if not problems:
        named = " ".join(
            (verdict.get("messages_by_code") or {}).get(CODE_PROVENANCE, []) +
            [str(ref) for ref in
             (verdict.get("refs_by_code") or {}).get(CODE_PROVENANCE, [])])
        if NON_CANONICAL_EVD not in named:
            findings.append(
                f"MUT-11-21 (b): il rifiuto non NOMINA {NON_CANONICAL_EVD}: un "
                "alias va RICONOSCIUTO e respinto, non ignorato")

    # Forma canonica degli id sul percorso dei REGISTRI. Un alias nei
    # registri condivisi non sparisce prima del controllo: la costruzione e'
    # RESPINTA con codice attribuito che NOMINA ogni alias, nessun canonico e'
    # scritto, e un registro di soli alias NON diventa `availability: missing`.
    for label, evd, src, aliases in (
            ("misto", ["EVD-001", NON_CANONICAL_EVD, "EVD-21"],
             ["SRC-001", NON_CANONICAL_SRC],
             [NON_CANONICAL_EVD, "EVD-21", NON_CANONICAL_SRC]),
            ("solo-alias-evd", [NON_CANONICAL_EVD, "EVD-0022"], None,
             [NON_CANONICAL_EVD, "EVD-0022"]),
            ("solo-alias-src", None, [NON_CANONICAL_SRC],
             [NON_CANONICAL_SRC])):
        project = clone(ctx, base, f"c21-reg-{label}")
        if evd is not None:
            write_register(project, EVIDENCE_REGISTER_REL, evd)
        if src is not None:
            write_register(project, SOURCE_REGISTER_REL, src)
        tx = f"tx-c21-{label}"
        built = run_builder(ctx, project, tx=tx)
        problems = rejects(built, CODE_PROVENANCE,
                           f"MUT-11-21 (c) registri {label} (build)")
        findings += problems
        if not problems:
            named = named_in(built, CODE_PROVENANCE)
            unnamed = [alias for alias in aliases if alias not in named]
            if unnamed:
                findings.append(
                    f"MUT-11-21 (c) registri {label}: il rifiuto non NOMINA "
                    f"{unnamed}")
        if stage11_paths(project, tx)["canonical"].is_file():
            findings.append(
                f"MUT-11-21 (c) registri {label}: canonico dello Stage 11 "
                "SCRITTO nonostante gli alias: e' un'omissione silenziosa")

    # Il Transaction Manager non passa MAI `--build`: lo stesso alias,
    # comparso nel registro DOPO la costruzione, e' respinto in EGRESS.
    reference = Path(case["project"]) / EVIDENCE_REGISTER_REL
    original = reference.read_bytes()
    write_register(case["project"], EVIDENCE_REGISTER_REL,
                   ["EVD-001", NON_CANONICAL_EVD])
    try:
        verdict = run_validator(ctx, case["project"],
                                case["paths"]["candidate"])
    finally:
        reference.write_bytes(original)
    problems = rejects(verdict, CODE_PROVENANCE,
                       "MUT-11-21 (d) alias nel registro (egress)")
    findings += problems
    if not problems and NON_CANONICAL_EVD not in named_in(verdict,
                                                          CODE_PROVENANCE):
        findings.append(
            f"MUT-11-21 (d): il rifiuto in egress non NOMINA "
            f"{NON_CANONICAL_EVD}")

    # Nessuna voce OMESSA e nessun riferimento che non risolve: l'indice delle
    # evidenze coincide con le voci canoniche dei registri.
    registered = [ref for ref in (request.get("evidence_index") or {})
                  .get("evidence_refs") or ()]
    if not registered:
        findings.append(
            "la fixture non porta alcuna evidenza registrata: l'omissione non "
            "e' misurabile")
        return findings
    omitted = mutate(case["document"],
                     "funding_request.evidence_index.evidence_refs", [])
    verdict = probe(ctx, case, omitted, "m-s11-21e")
    problems = rejects(verdict, CODE_PROVENANCE,
                       "MUT-11-21 (e) evidenza registrata OMESSA")
    findings += problems
    if not problems and registered[0] not in named_in(verdict,
                                                      CODE_PROVENANCE):
        findings.append(
            f"MUT-11-21 (e): il rifiuto non NOMINA l'evidenza omessa "
            f"{registered[0]}")
    dangling = mutate(case["document"],
                      "funding_request.evidence_index.evidence_refs",
                      sorted(registered + ["EVD-999"]))
    verdict = probe(ctx, case, dangling, "m-s11-21f")
    problems = rejects(verdict, CODE_PROVENANCE,
                       "MUT-11-21 (f) riferimento che NON risolve")
    findings += problems
    if not problems and "EVD-999" not in named_in(verdict, CODE_PROVENANCE):
        findings.append("MUT-11-21 (f): il rifiuto non NOMINA EVD-999")
    # Il join campi x provenienza e' contro la
    # proiezione AUTORITATIVA: una voce che il costruttore emette non si
    # omette, anche se il campo non e' fra quelli sempre obbligatori.
    findings += projection_probes(ctx, case, (
        ("voce di provenance del runway ante-finanziamento omessa",
         without_provenance("runway.before_financing.runway_to_zero"),
         CODE_PROVENANCE),))
    return findings


# --------------------------------------------------------------------------
# FR-C-22 — T-FR-TRIANGULAR-CONSISTENCY
# --------------------------------------------------------------------------


def c22(ctx, base):
    """Nessuna divergenza numerica fra JSON, Markdown, workbook e funding
    request — confronto TRIANGOLARE. Solo `FAIL`: nessuna forma `WARNING`
    esiste per questo codice."""
    findings = []
    case = prepare(ctx, base, "c22")
    if not_built(case, findings,
                 "nessun funding-request.md e' reso, quindi il confronto "
                 "triangolare con canonico, capitolo e workbook non esiste"):
        return findings
    findings += accepts(case["validated"], "(positivo) derivati coerenti")

    request_md = case["paths"]["request"]
    if not request_md.is_file():
        findings.append(
            f"{REQUEST_NAME} ASSENTE: il derivato obbligatorio non e' stato "
            "prodotto")
        return findings

    # MUT-11-22 — un valore alterato nel SOLO `funding-request.md`.
    text = request_md.read_text(encoding="utf-8")
    amount_value = str((request_of(case["document"])
                        .get("requested_capital") or {}).get("amount"))
    if amount_value not in text:
        findings.append(
            f"il capitale richiesto {amount_value!r} non compare nel derivato: "
            "il confronto triangolare non avrebbe presa")
        return findings
    altered = text.replace(amount_value, "999999.99", 1)
    request_md.write_text(altered, encoding="utf-8")
    verdict = run_validator(ctx, case["project"], case["paths"]["candidate"])
    findings += rejects(verdict, CODE_DERIVED_MISMATCH, "MUT-11-22")
    for entry in (verdict.get("report") or {}).get("warnings") or ():
        if entry.get("code") == CODE_DERIVED_MISMATCH:
            findings.append(
                "MUT-11-22: la divergenza e' stata declassata a WARNING: per "
                "questo codice esiste SOLO la forma FAIL")
    request_md.write_text(text, encoding="utf-8")

    # Un numero INVENTATO nel derivato e' respinto anche
    # quando e' SOTTOSTRINGA di un letterale dichiarato: il confronto e' per
    # TOKEN numerico, mai per sottostringa; ne'
    # per VALORE: una resa che nessun campo emette non e' tracciata;
    # ne' per le sole CIFRE di una resa
    # qualificata, ne' ignorando cifre non ASCII, ne' per FORMA di un
    # identificatore o di una riga.
    findings += thousands_twins_missing(case["document"], "MUT-11-22")
    # La STESSA scansione per espressione completa, sul
    # derivato: qualificatori prima o dopo le cifre, separati da spazi,
    # `_`, `-`, a capo o formattazione Markdown/HTML; numerali composti da
    # gruppi dichiarati; esponenti; caratteri numerici non decimali.
    for label, extra, invented in (
            ("pre-money", "Valutazione pre-money: 5 milioni EUR.", "5"),
            ("diluizione", "Diluizione del 20% per il lettore.", "20"),
            *UNDECLARED_RENDERINGS, *MAGNITUDE_RENDERINGS,
            *UNICODE_DIGIT_RENDERINGS, *SHAPE_RENDERINGS,
            CHECKSUM_LINE_PROBE, *EXPRESSION_RENDERINGS,
            *UNICODE_NUMERIC_RENDERINGS, *STRUCTURAL_RENDERINGS,
            *MARKDOWN_RENDERINGS):
        request_md.write_bytes(f"{text}\n{extra}\n".encode("utf-8"))
        try:
            verdict = run_validator(ctx, case["project"],
                                    case["paths"]["candidate"])
        finally:
            request_md.write_text(text, encoding="utf-8")
        problems = rejects(verdict, CODE_DERIVED_MISMATCH,
                           f"MUT-11-22 numero inventato ({label})")
        findings += problems
        if not problems and repr(invented) not in named_in(
                verdict, CODE_DERIVED_MISMATCH):
            findings.append(
                f"MUT-11-22 ({label}): il rifiuto non NOMINA il numero "
                f"inventato {invented!r}")
    # Gli id che RISOLVONO restano identificatori: il
    # derivato che li cita e' accettato; e la resa ESATTA
    # dei letterali dichiarati resta accettata, anche
    # marcata dalla sola formattazione, o citata come numeri DISTINTI.
    for label, extra in (("id registrati", REGISTERED_IDS_PROSE),
                         ("rese esatte", EXACT_RENDERINGS_PROSE),
                         *((f"positivo espressioni {index}", prose)
                           for index, prose in
                           enumerate(EXPRESSION_POSITIVES)),
                         *((f"positivo grandezza-marcatura {index}", prose)
                           for index, prose in
                           enumerate(ROUND5_POSITIVES))):
        request_md.write_text(f"{text}\n{extra}\n", encoding="utf-8")
        try:
            verdict = run_validator(ctx, case["project"],
                                    case["paths"]["candidate"])
        finally:
            request_md.write_text(text, encoding="utf-8")
        findings += accepts(verdict, f"(positivo) {label} nel derivato")

    # Sulla fixture RICCA: gli id REGISTRATI passano, gli
    # id FABBRICATI in un namespace approvato sono respinti e nominati.
    rich = prepare(ctx, base, "c22-rich", hook=with_registered_ids)
    if not_built(rich, findings, "la fixture ricca degli id registrati non produce "
                                 "alcuna funding request"):
        return findings
    findings += registered_ids_probes(ctx, rich, "derived")
    module = fr_module(ctx)
    if module is None:
        findings.append(f"sonda unitaria: {MISSING_VALIDATOR}")
    else:
        findings += unit_trace_probe(module, rich, "derived",
                                     Path(base) / "c22-unit",
                                     ctx["config"]["stage_order"])
        # Il fronte del DERIVATO non si fida del
        # documento sotto validazione: codici, domande e messaggi che il
        # candidate possiede non sottraggono nulla alla scansione.
        findings += self_declaration_markdown_probes(ctx, module, rich)
        # Grandezza e marcatura — le varianti generate e i
        # positivi, sul fronte del derivato.
        findings += variant_probe(module, rich, "derived",
                                  Path(base) / "c22-r5",
                                  ctx["config"]["stage_order"])
        uncovered = prepare(ctx, base, "c22-none", level="none")
        if not not_built(uncovered, findings, "la fixture a copertura nulla "
                                              "non produce alcuna funding "
                                              "request"):
            findings += accepts(uncovered["validated"],
                                "(positivo) voce irrisolta dello Stage 10 "
                                "con cifre, resa fedelmente")
            findings += unresolved_rewrite_probes(ctx, module, uncovered)
    findings += tm_chain(ctx, base, "tok-tm-derivato", ft01_markdown_only,
                         (CODE_DERIVED_MISMATCH,), named=("5000000", "20"),
                         hook=with_registered_ids, view=False)

    # Un canonico FUORI SCHEMA e' respinto con il codice di
    # schema ATTRIBUITO, in un report JSON, mai con un traceback.
    findings += schema_invalid_attributed(
        probe(ctx, case, drop(case["document"], "funding_request.runway"),
              "schema-egress"), "(egress) runway assente")

    # La fase IMPACT nella forma REALE del Transaction
    # Manager, a Stage 11 COMPLETATO.
    findings += impact_on_validation_view(ctx, base)
    return findings


#: Casi della sonda UNITARIA: `(etichetta, gap residuo dichiarato, prosa,
#: numeri inventati)`. Il gap residuo e' il letterale che la sonda governa:
#: `50` traccia `50` e non `5`; `50.0` traccia `50.0` e NON `50`,
#: perche' si traccia la RESA dichiarata e non il valore.
UNIT_TRACE_CASES = (
    ("tracciati", "50", "Il gap residuo e' di 50 EUR su 200 assunzioni.", ()),
    ("inventati", "50", "Valutazione pre-money 5 milioni; diluizione 20%.",
     ("5", "20")),
    ("migliaia", "50",
     "Pre-money 100.000 EUR; round 12.000 EUR; 7.000 azioni.",
     ("100.000", "12.000", "7.000")),
    ("resa-non-dichiarata", "50", "Runway finanziato di 12.0 periodi.",
     ("12.0",)),
    ("resa-dichiarata", "50.0", "Il gap residuo e' di 50.0 EUR.", ()),
    ("valore-senza-resa", "50.0", "Il gap residuo e' di 50 EUR.", ("50",)),
    ("id-non-approvato", "50", "Pre-money EUR-5000000 o USD-7000000.",
     ("5000000", "7000000")),
    ("cifre-sottolineate", "50", "Pre-money 5_000_000 EUR.", ("5_000_000",)),
    ("cifre-incollate", "50",
     "Pre-money EUR5000000 o EUR_7000000, ritorno x3.",
     ("5000000", "7000000", "3")),
    # SOLO gli id che RISOLVONO sulla fixture ricca: roadmap
    # (`MIL-001`, `MIL-003`), registri di evidenza, di fonte e delle assunzioni,
    # driver riferiti da `use_of_proceeds`, codici di decisione, sezioni e
    # politica coniati dallo stage, stage di `stage_order`.
    ("id-registrati", "50",
     "Rif. ASS-001, COND-S10-SCENARIO-COVERAGE, FR-CAPITAL-POLICY, DRV-007, "
     "EVD-001, "
     "FR-S3, FR-TERM-VALUATION, MIL-001, MIL-003, SRC-001; stage "
     "10_financial-plan e 11_funding-request.", ()),
    # Gli id NON registrati della forma di un namespace approvato: la forma
    # del namespace non li maschera, e le loro cifre sono nominate.
    ("id-non-registrati", "50",
     "Rif. P-ASS-001, COND-001, DEC-A10-22, OPS-001, RISK-001, ROLE-001.",
     ("001", "10", "22")),
    ("id-fabbricati", "50",
     "Pre-money MIL-5000000 EUR, FR-5000000, EVD-5000000, DEC-5000000, "
     "DRV-5000000; la milestone MIL-999; diluizione FR-DILUIZIONE-20.",
     ("5000000", "999", "20")),
    ("forme-di-stage-fittizie", "50",
     "Pre-money 5000000_EUR; 99_milioni EUR; 10_financial-plan-bis.",
     ("5000000", "99", "10")),
    # La resa QUALIFICATA da una grandezza e' distinta dalle
    # sue cifre, incollata o separata, in qualunque grafia del vocabolario
    # chiuso; parole che NON sono grandezze non qualificano nulla.
    ("grandezze", "50",
     "Pre-money 100 mila EUR; round 12 mila; 100k; 12K; 7M; 100 milioni; "
     "12 mln; 100mila.",
     ("100 mila", "12 mila", "100k", "12K", "7M", "100 milioni", "12 mln",
      "100mila")),
    ("grandezze-varianti", "50",
     "Pre-money 100 k EUR; 7 M EUR; 12 MLN; 12 Mila; 7 miliardi; 12 mld; "
     "7 miliardo; 12 milione; 12 kEUR; 7MEUR; 100 k€.",
     ("100 k", "7 M", "12 MLN", "12 Mila", "7 miliardi", "12 mld",
      "7 miliardo", "12 milione", "12 kEUR", "7MEUR", "100 k€")),
    ("resa-esatta", "50", EXACT_RENDERINGS_PROSE, ()),
    ("parole-non-grandezze", "50",
     "Runway di 12 mesi, sede a 7 Milano, 100 metri.", ()),
    # Cifre decimali Unicode non ASCII.
    ("cifre-unicode", "50",
     f"Pre-money {FULLWIDTH_DIGITS} EUR; pre-money {ARABIC_INDIC_DIGITS} EUR.",
     (FULLWIDTH_DIGITS, ARABIC_INDIC_DIGITS)),
    # Espressioni numeriche — l'intera classe, una riga per resa, sulle funzioni
    # DI PRODUZIONE dei due fronti; e i positivi esatti.
    *((f"espressione-{label}", "50", prose, (core,))
      for label, prose, core in (*EXPRESSION_RENDERINGS,
                                 *UNICODE_NUMERIC_RENDERINGS)),
    *((f"espressione-positivo-{index}", "50", prose, ())
      for index, prose in enumerate(EXPRESSION_POSITIVES)),
    # Grandezza e marcatura — le forme di riferimento, e i positivi.
    *((f"grandezza-marcatura-{label}", "50", prose, (core,))
      for label, prose, core in (*STRUCTURAL_RENDERINGS,
                                 *MARKDOWN_RENDERINGS)),
    *((f"grandezza-marcatura-positivo-{index}", "50", prose, ())
      for index, prose in enumerate(ROUND5_POSITIVES)),
)


def unit_trace_probe(module, case, front, workdir, stage_order):
    """Sonda UNITARIA del tracciamento numerico sulle funzioni DI PRODUZIONE:
    con i letterali dichiarati `50` e `200`, il `5` e il `20` inventati sono
    RESPINTI; le migliaia puntate `100.000`, `12.000`, `7.000` non sono
    tracciate dai `100`, `12`, `7` dichiarati; una resa non dichiarata e'
    respinta anche a pari valore; una resa QUALIFICATA da una grandezza non e'
    tracciata dalle sue cifre; le cifre non ASCII sono token; SOLO gli id che
    RISOLVONO restano identificatori; i valori tracciati continuano a passare
    (`UNIT_TRACE_CASES`).

    Gli id risolvibili sono calcolati UNA volta dalla funzione DI PRODUZIONE
    `resolvable_ids`, sul canonico dello Stage 10 e sui registri della fixture
    `case`, e passati a entrambi i fronti: la regola e' una sola.

    `front == "narrative"` misura `check_narrative`, `front == "derived"`
    misura `check_derived` su un `funding-request.md` scritto qui.
    """
    findings = []
    document = case["document"]
    resolver = getattr(module, "resolvable_ids", None)
    if resolver is None:
        findings.append(
            f"sonda unitaria {front}: constatazione — il modulo non "
            "espone alcuna RISOLUZIONE degli identificatori (resolvable_ids): "
            "un id e' mascherato per la sola FORMA del suo namespace")
        return findings
    resolved = resolver(stage10_document(case), case["project"], stage_order)
    # La produzione traccia contro un insieme di letterali
    # AUTORITATIVO passato esplicitamente (`trusted`), mai letto dal
    # documento sotto validazione. La sonda passa i letterali che dichiara,
    # quando la funzione lo accetta.
    trusting = "trusted" in inspect.signature(
        module.check_narrative).parameters
    for label, residual_gap, body, invented in UNIT_TRACE_CASES:
        request = json.loads(json.dumps(request_of(document)))
        request["sufficiency"]["residual_gap"] = residual_gap
        request["dependencies_and_assumptions"]["unvalidated_count"] = 200
        declared = [literal for literal, _ in
                    module.declared_literals(request)]
        request["narrative"]["numeric_refs"] = [
            {"literal": literal, "field": field}
            for literal, field in module.declared_literals(request)]
        if label == "migliaia":
            missing = [twin for twin in THOUSANDS_TWINS
                       if twin not in declared]
            if missing:
                findings.append(
                    f"sonda unitaria {front} ({label}): precondizione "
                    f"— la fixture non dichiara {missing}, e la sonda "
                    "non misurerebbe l'equivalenza di valore")
        report = module.fw.Report("validate_funding_request", STAGE11,
                                  "egress")
        extra = {"trusted": frozenset(declared)} if trusting else {}
        if front == "narrative":
            request["narrative"]["sections"] = [
                {"section_id": "FR-UNIT", "title": "sonda", "body": body}]
            module.check_narrative(request, report, resolved, **extra)
            code = CODE_NARRATIVE
        else:
            project = Path(workdir) / label
            (project / STAGE11).mkdir(parents=True, exist_ok=True)
            # Ogni letterale dichiarato e' un PARAGRAFO proprio: righe
            # consecutive formano un solo paragrafo Markdown, e una fila di
            # numeri separati da spazi e' un numerale composto.
            (project / STAGE11 / REQUEST_NAME).write_bytes(
                ("\n\n".join(declared + [body]) + "\n").encode("utf-8"))
            module.check_derived({"funding_request": request}, project,
                                 report, resolved=resolved, **extra)
            code = CODE_DERIVED_MISMATCH
        errors = [entry for entry in report.errors if entry["code"] == code]
        text = " ".join(str(entry.get("message")) for entry in errors)
        if not invented and errors:
            findings.append(
                f"sonda unitaria {front} ({label}): valori TRACCIATI respinti: "
                f"{text[:300]}")
        for number in invented:
            if repr(number) not in text:
                findings.append(
                    f"sonda unitaria {front} ({label}): il numero inventato "
                    f"{number!r} e' AMMESSO benche' non sia la RESA di alcun "
                    f"letterale dichiarato (gap residuo {residual_gap!r})")
    return findings


def thousands_twins_missing(document, label):
    """Precondizione della sonda delle migliaia: la fixture DICHIARA i letterali `100`, `12` e
    `7` in `narrative.numeric_refs[]`. Senza di essi le migliaia puntate
    sarebbero respinte per la ragione sbagliata e la sonda sarebbe vacua."""
    narrative = request_of(document).get("narrative") or {}
    declared = {str(item.get("literal"))
                for item in narrative.get("numeric_refs") or []}
    missing = [twin for twin in THOUSANDS_TWINS if twin not in declared]
    if not missing:
        return []
    return [f"{label}: precondizione — la fixture non dichiara "
            f"{missing}, e le migliaia puntate non misurerebbero "
            "l'equivalenza di valore"]


def schema_invalid_attributed(verdict, label):
    """Un canonico dello Stage 11 FUORI SCHEMA fallisce
    CHIUSO con un report JSON che porta `fr_schema_invalid` ATTRIBUITO, e non
    con un `KeyError` non gestito senza report."""
    problems = rejects(verdict, CODE_SCHEMA, f"schema {label}")
    if verdict.get("report") is None:
        problems.append(
            f"schema {label}: nessun report JSON (exit "
            f"{verdict.get('exit_code')}): "
            f"{(verdict.get('stderr') or '').strip()[-200:]!r}")
    if "Traceback" in (verdict.get("stderr") or ""):
        problems.append(
            f"schema {label}: il validator termina con un traceback invece di "
            "un rifiuto attribuito")
    return problems


def impact_on_validation_view(ctx, base):
    """Dopo l'`advance-stage` REALE dello Stage 11, la validation view
    del Transaction Manager NON contiene il derivato `funding-request.md` (per
    costruzione: solo `shared/` e i `NN_*/structured-output.json`). La fase
    impact deve PASSARE su quella view, e restare DISCRIMINANTE: una
    generazione divergente del canonico dello Stage 11 e' ancora respinta."""
    findings = []
    case = prepare(ctx, base, "c22-impact")
    if not_built(case, findings,
                 "nessuna funding request da portare a completamento"):
        return findings
    # Il Transaction Manager CONSUMA il candidate al commit: i byte validati
    # sono fissati PRIMA dell'advance.
    candidate_bytes = case["paths"]["canonical"].read_bytes()
    exit_code, out, err = advance_stage11(ctx, case)
    if exit_code != 0:
        findings.append(
            f"(impact) advance-stage REALE dello Stage 11 fallisce (exit "
            f"{exit_code}): {out.strip()[:250]!r} {err.strip()[:250]!r}")
        return findings
    project = Path(case["project"])
    published = project / STAGE11 / CANONICAL_NAME
    if not published.is_file() or published.read_bytes() != candidate_bytes:
        findings.append(
            "(impact) il canonico dello Stage 11 pubblicato dal Transaction "
            "Manager non e' il candidate validato")
        return findings
    tm = transaction_manager(ctx)
    results, derived_in_view = run_impact_on_view(ctx, tm, project,
                                                  [STAGE10, STAGE11])
    if derived_in_view:
        findings.append(
            f"(impact) la validation view contiene {REQUEST_NAME}: la sonda "
            "non misurerebbe il percorso REALE del Transaction Manager")
    invoked = [result for result in results
               if result["validator"] == "validate_funding_request"]
    if not invoked:
        findings.append(
            "(impact) run_impact_validators non ha invocato "
            "validate_funding_request sullo Stage 11")
    for result in results:
        if result["exit_code"] != 0:
            findings.append(
                f"(impact) {result['validator']} ({result['stage']}) exit "
                f"{result['exit_code']} sulla validation view REALE: "
                f"{report_codes(result)}")
    diverged = mutate(json.loads(published.read_text(encoding="utf-8")),
                      "funding_request.source.canonical_source_checksum",
                      "0" * 64)
    results, _ = run_impact_on_view(
        ctx, tm, project, [STAGE11],
        {f"{STAGE11}/{CANONICAL_NAME}":
         canonical_json(diverged).encode("utf-8")},
        tx="tx-s11-impact-neg")
    negative = [result for result in results
                if result["validator"] == "validate_funding_request"]
    if not negative or negative[0]["exit_code"] == 0 or \
            CODE_DERIVED_MISMATCH not in report_codes(negative[0]):
        findings.append(
            "(impact) una generazione DIVERGENTE del canonico dello Stage 11 "
            "e' accettata sulla validation view: la fase impact e' VACUA "
            f"({[(r['exit_code'], report_codes(r)) for r in negative]})")

    # La fase impact e' RAGGIUNGIBILE: sulla
    # view REALE un canonico dello Stage 11 FUORI SCHEMA e' respinto con
    # `fr_schema_invalid` ATTRIBUITO, non da un `KeyError` senza report.
    schema_invalid = drop(json.loads(published.read_text(encoding="utf-8")),
                          "funding_request.runway")
    results, _ = run_impact_on_view(
        ctx, tm, project, [STAGE11],
        {f"{STAGE11}/{CANONICAL_NAME}":
         canonical_json(schema_invalid).encode("utf-8")},
        tx="tx-s11-impact-schema")
    invoked = [result for result in results
               if result["validator"] == "validate_funding_request"]
    if not invoked:
        findings.append(
            "(impact) schema: run_impact_validators non ha invocato "
            "validate_funding_request sul canonico fuori schema")
    for result in invoked:
        report = result.get("report") if isinstance(result.get("report"),
                                                    dict) else {}
        crashed = "raw_stdout" in report
        findings += schema_invalid_attributed(
            {"exit_code": result["exit_code"],
             "codes": set(report_codes(result)),
             "report": None if crashed else report,
             "stderr": str(report.get("stderr") or "") if crashed else ""},
            "(impact) runway assente sulla view REALE")
    return findings


# --------------------------------------------------------------------------
# FR-C-23 — T-FR-UNRESOLVED-ITEMS
# --------------------------------------------------------------------------


def c23(ctx, base):
    """Le voci di validazione irrisolte sono ESPOSTE, mai soppresse: il
    conteggio a valle e' IDENTICO a quello a monte."""
    findings = []
    # La fixture a copertura NULLA e' la sola che porta una voce di
    # validazione irrisolta REALE (`scenario_coverage`, WARNING): su una
    # fixture senza voci il filtro non sopprimerebbe nulla e il caso negativo
    # non discriminerebbe.
    case = prepare(ctx, base, "c23", level="none")
    if not_built(case, findings,
                 "nessun unresolved_validation_items[] esiste, quindi le voci "
                 "irrisolte del canonico non sono ne' copiate ne' contate"):
        return findings
    findings += accepts(case["validated"], "(positivo) voci irrisolte esposte")

    request = request_of(case["document"])
    validation = plan_of(stage10_document(case)).get("validation") or {}
    upstream = len(validation.get("errors") or []) + \
        len(validation.get("warnings") or [])
    downstream = len(request.get("unresolved_validation_items") or [])
    if downstream != upstream:
        findings.append(
            f"unresolved_validation_items porta {downstream} voci contro le "
            f"{upstream} del canonico: il conteggio deve essere IDENTICO")

    mutated = json.loads(json.dumps(case["document"]))
    mutated["funding_request"]["unresolved_validation_items"] = [
        entry for entry in
        mutated["funding_request"].get("unresolved_validation_items") or []
        if str(entry.get("severity")).upper() != "WARNING"]
    findings += rejects(probe(ctx, case, mutated, "m-s11-23"),
                        CODE_UNRESOLVED_ITEMS, "MUT-11-23")
    return findings


# --------------------------------------------------------------------------
# FR-C-24 — T-FR-NARRATIVE-TRACED
# --------------------------------------------------------------------------


def c24(ctx, base):
    """La narrativa NON calcola: ogni numero citato e' in
    `narrative.numeric_refs[]` e risolve in `provenance[]`."""
    findings = []
    case = prepare(ctx, base, "c24")
    if not_built(case, findings,
                 "nessuna narrative esiste, quindi nessun letterale numerico "
                 "della prosa e' tracciato a una voce di provenienza"):
        return findings
    findings += accepts(case["validated"], "(positivo) prosa tracciata")

    narrative = request_of(case["document"]).get("narrative") or {}
    if not narrative.get("sections"):
        findings.append("narrative senza sections[]")
    if "numeric_refs" not in narrative:
        findings.append("narrative senza numeric_refs[]")

    mutated = json.loads(json.dumps(case["document"]))
    sections = mutated["funding_request"]["narrative"].get("sections") or []
    if not sections:
        findings.append("nessuna sezione narrativa: MUT-11-24 non e' costruibile")
        return findings
    sections[0]["body"] = str(sections[0].get("body", "")) + \
        "\n\nIl fabbisogno complessivo e' di 1234567.89 EUR.\n"
    findings += rejects(probe(ctx, case, mutated, "m-s11-24"),
                        CODE_NARRATIVE, "MUT-11-24")

    # Numeri INVENTATI che sono SOTTOSTRINGA di un
    # letterale dichiarato: il `5`, il `3`, il `40` e il `20` compaiono tutti
    # dentro le cifre di `27440.61321581802203258027711`, e sono respinti
    # perche' il confronto e' per TOKEN; e per
    # RESA dichiarata, non per VALORE: `100.000` non e' il `100` dichiarato.
    findings += thousands_twins_missing(case["document"], "MUT-11-24")
    for label, extra, invented in (
            ("pre-money", " La valutazione pre-money e' di 5 milioni.",
             ("5",)),
            ("break-even", " Il break-even e' atteso in 3 anni con un margine "
                           "del 40%.", ("3", "40")),
            ("diluizione", " La diluizione per il lettore e' del 20%.",
             ("20",)),
            *((label, f" {extra}", (number,))
              for label, extra, number in (
                  *UNDECLARED_RENDERINGS, *MAGNITUDE_RENDERINGS,
                  *UNICODE_DIGIT_RENDERINGS, *SHAPE_RENDERINGS,
                  *EXPRESSION_RENDERINGS, *UNICODE_NUMERIC_RENDERINGS,
                  *STRUCTURAL_RENDERINGS, *MARKDOWN_RENDERINGS))):
        mutated = json.loads(json.dumps(case["document"]))
        mutated["funding_request"]["narrative"]["sections"][0]["body"] += extra
        verdict = probe(ctx, case, mutated, f"m-s11-24-{label}")
        problems = rejects(verdict, CODE_NARRATIVE,
                           f"MUT-11-24 numero inventato ({label})")
        findings += problems
        if problems:
            continue
        named = named_in(verdict, CODE_NARRATIVE)
        for number in invented:
            if repr(number) not in named:
                findings.append(
                    f"MUT-11-24 ({label}): il rifiuto non NOMINA il numero "
                    f"inventato {number!r}")
    # Gli id che RISOLVONO restano identificatori: la
    # narrativa che li cita e' accettata; e la resa ESATTA
    # dei letterali dichiarati resta accettata, anche marcata
    # dalla sola formattazione, o citata come numeri DISTINTI.
    for label, extra in (("ids", REGISTERED_IDS_PROSE),
                         ("rese-esatte", EXACT_RENDERINGS_PROSE),
                         *((f"positivo-espressioni-{index}", prose)
                           for index, prose in
                           enumerate(EXPRESSION_POSITIVES)),
                         *((f"positivo-grandezza-marcatura-{index}", prose)
                           for index, prose in
                           enumerate(ROUND5_POSITIVES))):
        mutated = json.loads(json.dumps(case["document"]))
        mutated["funding_request"]["narrative"]["sections"][0]["body"] += \
            f" {extra}"
        findings += accepts(probe(ctx, case, mutated, f"m-s11-24-{label}"),
                            f"(positivo) {label} nella narrativa")

    # Titolo di sezione — il TITOLO di sezione e' dentro il
    # portatore di `FR-C-24` (`narrative { sections[] }`) ed e' reso nel
    # derivato come intestazione: la stessa scansione del corpo. Il derivato
    # e' lasciato INTATTO, cosi' che il rifiuto venga dal fronte JSON.
    for label, title, invented in (
            ("titolo-inventato",
             "Capitale richiesto: pre-money 5000000 EUR, diluizione 20%",
             ("5000000", "20")),
            ("titolo-qualificato", "Capitale richiesto: 12 mln", ("12",)),
            ("titolo-dichiarato", "Capitale richiesto su 12 periodi", ())):
        verdict = probe(ctx, case,
                        mutate(case["document"],
                               "funding_request.narrative.sections.0.title",
                               title), f"titolo-{label}")
        if not invented:
            findings += accepts(verdict, f"(positivo titolo) {label}")
            continue
        problems = rejects(verdict, CODE_NARRATIVE, f"titolo {label}")
        findings += problems
        if not problems:
            findings += names_all(verdict, CODE_NARRATIVE, invented,
                                  f"titolo {label}")

    # Sulla fixture RICCA: gli id REGISTRATI passano, gli
    # id FABBRICATI o soltanto AUTO-dichiarati sono respinti e nominati; e
    # l'exploit degli id fabbricati e' respinto sul percorso REALE del
    # Transaction Manager.
    rich = prepare(ctx, base, "c24-rich", hook=with_registered_ids)
    if not_built(rich, findings, "la fixture ricca degli id registrati non produce "
                                 "alcuna funding request"):
        return findings
    findings += registered_ids_probes(ctx, rich, "narrative")
    findings += tm_fabricated_id_exploit(ctx, base)
    module = fr_module(ctx)
    if module is None:
        findings.append(f"sonda unitaria: {MISSING_VALIDATOR}")
    else:
        findings += unit_trace_probe(module, rich, "narrative",
                                     Path(base) / "c24-unit",
                                     ctx["config"]["stage_order"])
        # Lo stesso token dichiarato OVUNQUE nel candidate
        # resta non autoritativo, su ENTRAMBI i fronti.
        document, markdown = declared_everywhere(module, rich)
        verdict = probe_with_markdown(ctx, rich, document, markdown,
                                      "tok-ovunque")
        for code in (CODE_NARRATIVE, CODE_DERIVED_MISMATCH):
            problems = rejects(verdict, code, "token dichiarato ovunque")
            findings += problems
            if not problems:
                findings += names_all(verdict, code, ("5000000", "20"),
                                      "token dichiarato ovunque")
        findings += scan_time_probe(module, rich)
        # Grandezza e marcatura — le varianti generate e i
        # positivi, sul fronte JSON; e la SCALA del tempo di
        # scansione sui due fronti.
        findings += variant_probe(module, rich, "narrative",
                                  Path(base) / "c24-r5",
                                  ctx["config"]["stage_order"])
        findings += scan_scaling_probe(module, rich,
                                       Path(base) / "c24-scala",
                                       ctx["config"]["stage_order"])

    # METAMORFICO: per ogni variante
    # valida della suite, `validator(builder(ingressi))` e' GREEN.
    findings += builder_output_validates(ctx, base)

    # Sul percorso REALE del Transaction Manager: (A) l'exploit di
    # auto-dichiarazione sui due fronti, (B) le rese per espressione
    # completa, (E) i controlli POSITIVI — la variante a peso zero e quella a
    # copertura nulla, pubblicate byte per byte.
    findings += tm_chain(ctx, base, "tok-tm-ovunque", declared_everywhere,
                         (CODE_NARRATIVE, CODE_DERIVED_MISMATCH),
                         named=("5000000", "20"), hook=with_registered_ids)
    findings += tm_chain(
        ctx, base, "espr-tm-espressioni",
        lambda _module, target: (
            json.loads(canonical_json_with_prose(target, MAGNITUDE_EXPLOIT)),
            markdown_with_prose(target, MAGNITUDE_EXPLOIT)),
        (CODE_NARRATIVE, CODE_DERIVED_MISMATCH),
        named=MAGNITUDE_EXPLOIT_NAMED)
    findings += tm_positive(ctx, base, "meta-tm-peso-zero", level="zero")
    findings += tm_positive(ctx, base, "meta-tm-copertura-nulla", level="none")
    # Grandezza e marcatura sul percorso REALE: (A) grandezza
    # staccata per punteggiatura e struttura, (B) marcatura Markdown che
    # spezza l'espressione, sui due fronti insieme: egress RESPINGE, il
    # Transaction Manager NON pubblica; (C) il positivo,
    # pubblicato byte per byte.
    for name, exploit, named in (
            ("gm-tm-struttura", STRUCTURE_EXPLOIT, STRUCTURE_EXPLOIT_NAMED),
            ("gm-tm-markdown", MARKDOWN_EXPLOIT, MARKDOWN_EXPLOIT_NAMED)):
        findings += tm_chain(
            ctx, base, name,
            lambda _module, target, prose=exploit: (
                json.loads(canonical_json_with_prose(target, prose)),
                markdown_with_prose(target, prose)),
            (CODE_NARRATIVE, CODE_DERIVED_MISMATCH), named=named)
    findings += tm_positive(ctx, base, "gm-tm-positivo",
                            prose=ROUND5_POSITIVE_PROSE)
    return findings


def scan_time_probe(module, case):
    """La scansione della narrativa resta LINEARE su testi
    avversari (`ADVERSARIAL_SCAN_TEXTS`): nessun testo del candidate costa al
    validator un tempo quadratico. Limite largo, `SCAN_TIME_LIMIT_SECONDS`."""
    request = json.loads(json.dumps(request_of(case["document"])))
    extra = {"trusted": frozenset()} if "trusted" in inspect.signature(
        module.check_narrative).parameters else {}
    started = time.perf_counter()
    for text in ADVERSARIAL_SCAN_TEXTS:
        request["narrative"]["sections"] = [
            {"section_id": "FR-UNIT", "title": "sonda", "body": text}]
        module.check_narrative(
            request, module.fw.Report("validate_funding_request", STAGE11,
                                      "egress"), frozenset(), **extra)
    elapsed = time.perf_counter() - started
    if elapsed > SCAN_TIME_LIMIT_SECONDS:
        return [f"tempo di scansione: {elapsed:.1f} s su "
                f"{len(ADVERSARIAL_SCAN_TEXTS)} testi avversari (limite "
                f"{SCAN_TIME_LIMIT_SECONDS} s)"]
    return []


def front_errors(module, case, front, body, project, resolved):
    """Gli errori che il fronte `front` DI PRODUZIONE
    (`check_narrative` o `check_derived`) solleva su `body`, con i letterali
    AUTORITATIVI della fixture `case`. Sul derivato ogni letterale dichiarato
    e' un paragrafo proprio (come in `unit_trace_probe`) e `body` il
    paragrafo che segue."""
    request = json.loads(json.dumps(request_of(case["document"])))
    declared = [literal for literal, _ in module.declared_literals(request)]
    report = module.fw.Report("validate_funding_request", STAGE11, "egress")
    extra = {"trusted": frozenset(declared)} if "trusted" in \
        inspect.signature(module.check_narrative).parameters else {}
    if front == "narrative":
        request["narrative"]["sections"] = [
            {"section_id": "FR-UNIT", "title": "sonda", "body": body}]
        module.check_narrative(request, report, resolved, **extra)
        code = CODE_NARRATIVE
    else:
        (Path(project) / STAGE11).mkdir(parents=True, exist_ok=True)
        (Path(project) / STAGE11 / REQUEST_NAME).write_bytes(
            ("\n\n".join(declared + [body]) + "\n").encode("utf-8"))
        module.check_derived({"funding_request": request}, project, report,
                             resolved=resolved, **extra)
        code = CODE_DERIVED_MISMATCH
    return [entry for entry in report.errors if entry["code"] == code]


def variant_probe(module, case, front, workdir, stage_order):
    """Grandezza e marcatura — le VARIANTI generate
    (`structural_variants`, `markdown_variants`) sulle funzioni DI
    PRODUZIONE del fronte `front`: ciascuna e' RESPINTA, e il rifiuto porta il
    proprio contrassegno (cifre qualificate o nucleo nominato). I positivi
    (`ROUND5_POSITIVES`) restano ACCETTATI. Una sola risoluzione degli id, come in
    `unit_trace_probe`."""
    findings = []
    resolved = module.resolvable_ids(stage10_document(case), case["project"],
                                     stage_order)
    bypassed = []
    for index, (label, prose, needle) in enumerate(
            (*structural_variants(), *markdown_variants())):
        errors = front_errors(module, case, front, f"Testo. {prose}",
                              Path(workdir) / f"v{index}", resolved)
        text = " ".join(str(entry.get("message")) for entry in errors)
        if needle not in text:
            bypassed.append(f"{label}: {prose!r}")
    if bypassed:
        findings.append(
            f"grandezza/marcatura varianti ({front}): {len(bypassed)} rese ACCETTATE o non "
            f"nominate come espressione intera: {bypassed[:6]}")
    for index, prose in enumerate(ROUND5_POSITIVES):
        errors = front_errors(module, case, front, f"Testo. {prose}",
                              Path(workdir) / f"p{index}", resolved)
        if errors:
            findings.append(
                f"grandezza/marcatura positivo ({front}) {prose!r} RESPINTO: "
                f"{' '.join(str(e.get('message')) for e in errors)[:300]}")
    return findings


def scan_scaling_probe(module, case, workdir, stage_order):
    """La vista del lettore e la scansione
    restano LINEARI nella lunghezza del testo, misurate come SCALA e mai con
    una soglia assoluta di tempo: per ogni famiglia di `SCALING_FAMILIES`,
    sui due fronti DI PRODUZIONE (`check_narrative`; `check_derived` per
    `SCALING_DERIVED_FAMILIES`), il tempo migliore su `SCALING_REPEATS`
    esecuzioni alle taglie N, 2N e 4N, dopo un riscaldamento. La famiglia e'
    SUPERLINEARE se T(4N) > `SCALING_RATIO_LIMIT` x T(N) in OGNUNO di
    `SCALING_ATTEMPTS` tentativi: un picco di carico dell'host non basta."""
    findings = []
    resolved = module.resolvable_ids(stage10_document(case), case["project"],
                                     stage_order)
    fronts = [("narrative", family) for family in SCALING_FAMILIES]
    fronts += [("derived", family) for family in SCALING_FAMILIES
               if family[0] in SCALING_DERIVED_FAMILIES]
    for front, (label, head, unit, tail) in fronts:
        units = max(1, SCALING_CHARACTERS // len(unit))
        project = Path(workdir) / f"scala-{front}-{label}"
        front_errors(module, case, front, head + unit * 50 + tail, project,
                     resolved)
        ratios = []
        for _ in range(SCALING_ATTEMPTS):
            times = []
            for factor in (1, 2, 4):
                text = head + unit * (units * factor) + tail
                best = None
                for _ in range(SCALING_REPEATS):
                    started = time.perf_counter()
                    front_errors(module, case, front, text, project, resolved)
                    elapsed = time.perf_counter() - started
                    best = elapsed if best is None else min(best, elapsed)
                times.append(best)
            ratio = times[2] / max(times[0], 1e-6)
            ratios.append(ratio)
            if ratio <= SCALING_RATIO_LIMIT:
                break
        if min(ratios) > SCALING_RATIO_LIMIT:
            findings.append(
                f"scala ({front}, {label}): T(4N)/T(N) = "
                f"{', '.join(f'{r:.1f}' for r in ratios)} oltre il limite "
                f"{SCALING_RATIO_LIMIT} (N = {len(head + unit * units + tail)} "
                "caratteri): la scansione e' SUPERLINEARE")
    return findings


def canonical_json_with_prose(case, prose):
    """Il canonico di `case` con `prose` aggiunta al corpo `FR-S1`."""
    document = json.loads(json.dumps(case["document"]))
    section = document["funding_request"]["narrative"]["sections"][0]
    section["body"] = f"{section['body']} {prose}"
    return canonical_json(document)


def builder_output_validates(ctx, base):
    """Metamorfico — il prodotto del costruttore passa il
    proprio validator, su OGNI variante della suite (`METAMORPHIC_VARIANTS`),
    compresa la categoria d'impiego a peso ZERO che la rotta del motore
    produce: costruzione exit 0 ed egress exit 0, sui due fronti."""
    findings = []
    for name, level, hook_name in METAMORPHIC_VARIANTS:
        hook = globals()[hook_name] if hook_name else None
        case = prepare(ctx, base, f"meta-{name}", level=level, hook=hook)
        if not_built(case, findings, f"variante metamorfica {name}: il costruttore "
                                     "non produce la funding request"):
            continue
        findings += accepts(case["validated"],
                            f"variante metamorfica {name}: validator(builder)")
    return findings


def registered_ids_of(case):
    """Gli identificatori che la fixture DICHIARA davvero,
    LETTI dal canonico dello Stage 11 GENERATO — sezioni, codici di decisione,
    assunzioni, evidenze e fonti, milestone e loro driver di costo, driver
    dell'impiego, identificatore della politica, stage sorgente — e dalla
    roadmap REALE del progetto. Nessuno e' scritto a mano: il positivo prova
    che OGNI id che la pipeline emette risolve."""
    request = request_of(case["document"])
    block = request.get("dependencies_and_assumptions") or {}
    index = request.get("evidence_index") or {}
    ids = [section.get("section_id") for section in
           (request.get("narrative") or {}).get("sections") or []]
    ids += [item.get("code") for item in block.get("decision_needed") or []]
    ids += [item.get("code")
            for item in request.get("unresolved_validation_items") or []]
    ids += list(block.get("assumption_refs") or [])
    ids += list(index.get("evidence_refs") or [])
    ids += list(index.get("source_refs") or [])
    for entry in request.get("milestone_financing") or []:
        ids.append(entry.get("milestone_ref"))
        ids += list(entry.get("cost_ref") or [])
    for entry in request.get("use_of_proceeds") or []:
        ids += list(entry.get("driver_refs") or [])
    ids += re.findall(r"FR-[A-Z0-9]+-POLICY", str(
        (request.get("capital_requirement") or {}).get("policy_ref") or ""))
    ids.append((request.get("source") or {}).get("stage"))
    roadmap = Path(case["project"]) / "09_roadmap-and-milestones" / \
        CANONICAL_NAME
    if roadmap.is_file():
        plan = json.loads(roadmap.read_text(encoding="utf-8"))
        ids += [item.get("id") for item in
                (plan.get("milestone_plan") or {}).get("milestones") or []]
    return sorted({str(item) for item in ids if item})


def apply_prose(ctx, case, front, prose, name):
    """Aggiunge `prose` al fronte `front` di `case` e valida in egress: la
    narrativa JSON in un candidate SEPARATO (`probe`), oppure il derivato
    `funding-request.md`, ripristinato byte per byte dopo la validazione."""
    if front == "narrative":
        mutated = json.loads(json.dumps(case["document"]))
        mutated["funding_request"]["narrative"]["sections"][0]["body"] += \
            f" {prose}"
        return probe(ctx, case, mutated, name)
    request_md = case["paths"]["request"]
    text = request_md.read_text(encoding="utf-8")
    request_md.write_text(f"{text}\n{prose}\n", encoding="utf-8")
    try:
        return run_validator(ctx, case["project"], case["paths"]["candidate"])
    finally:
        request_md.write_text(text, encoding="utf-8")


def registered_ids_probes(ctx, case, front):
    """Un identificatore e' sottratto alla scansione
    numerica SOLO se RISOLVE in un identificatore AUTORITATIVO del contesto di
    validazione; la forma del namespace da sola non basta.

    Sulla fixture RICCA `case`: (a) la prosa che cita OGNI id che la fixture
    dichiara (`registered_ids_of`) e' ACCETTATA; (b) ogni id FABBRICATO di
    `FABRICATED_ID_PROBES`, exploit compreso, e' RESPINTO e le sue cifre sono
    NOMINATE; (c) sul fronte JSON, un id soltanto AUTO-dichiarato dal canonico
    sotto validazione — un codice di decisione o una sezione aggiunti — non
    diventa per questo risolvibile: il documento non e' autorita' di se'."""
    findings = []
    label = "narrativa" if front == "narrative" else REQUEST_NAME
    code = CODE_NARRATIVE if front == "narrative" else CODE_DERIVED_MISMATCH
    findings += accepts(case["validated"], f"(positivo id registrati, {label}) "
                                           "fixture ricca")
    ids = registered_ids_of(case)
    missing = [ref for ref in REQUIRED_REGISTERED_IDS if ref not in ids]
    if missing:
        findings.append(
            f"id registrati ({label}): precondizione — la fixture ricca non dichiara "
            f"{missing}, e il positivo non proverebbe gli id REGISTRATI")
    prose = f"Riferimenti registrati: {', '.join(ids)}."
    findings += accepts(apply_prose(ctx, case, front, prose,
                                    "ids-registrati"),
                        f"(positivo id registrati, {label}) id registrati {ids}")
    for name, extra, invented in FABRICATED_ID_PROBES:
        verdict = apply_prose(ctx, case, front, extra,
                              f"ids-{name.lower()}")
        problems = rejects(verdict, code,
                           f"id registrati ({label}) id fabbricato {name}")
        findings += problems
        if problems:
            continue
        named = named_in(verdict, code)
        for number in invented:
            if f"'{number}'" not in named:
                findings.append(
                    f"id registrati ({label}) {name}: il rifiuto non NOMINA le cifre "
                    f"{number!r} che l'id fabbricato nasconde")
    if front != "narrative":
        return findings
    for name, ref, extend in (
            ("decisione", "FR-DILUIZIONE-20",
             lambda request: request["dependencies_and_assumptions"]
             ["decision_needed"].append({
                 "code": "FR-DILUIZIONE-20", "blocking": False,
                 "question": "Quale diluizione si propone?"})),
            ("sezione", "FR-5000000",
             lambda request: request["narrative"]["sections"].append({
                 "section_id": "FR-5000000", "title": "Valutazione",
                 "body": "Sezione FR-5000000."}))):
        mutated = json.loads(json.dumps(case["document"]))
        extend(mutated["funding_request"])
        mutated["funding_request"]["narrative"]["sections"][0]["body"] += \
            f" Riferimento {ref}."
        verdict = probe(ctx, case, mutated, f"ids-auto-{name}")
        findings += rejects(verdict, CODE_NARRATIVE,
                            f"id AUTO-dichiarato ({name} {ref})")
    return findings


def self_declared_decisions(case, *entries):
    """Copia del documento di `case` con le decisioni `(codice, domanda)`
    AGGIUNTE a `decision_needed[]`: dichiarazioni del SOLO candidate."""
    document = json.loads(json.dumps(case["document"]))
    decisions = document["funding_request"]["dependencies_and_assumptions"][
        "decision_needed"]
    for code, question in entries:
        decisions.append({"code": code, "question": question,
                          "blocking": False})
    return document


def ft01_markdown_only(module, case):
    """Codici auto-dichiarati sul solo derivato: due codici di
    decisione AUTO-dichiarati, `FR-DILUIZIONE-20` e `MIL-5000000`, la
    narrativa JSON INTATTA e l'exploit nel paragrafo `FR-S1` del solo
    derivato, reso fedelmente da `render_request`."""
    document = self_declared_decisions(
        case, ("FR-DILUIZIONE-20", "Quale diluizione si propone?"),
        ("MIL-5000000", "Quale valutazione pre-money si propone?"))
    markdown = markdown_with_prose(case, TF01_EXPLOIT,
                                   module.render_request(document))
    return document, markdown


def self_declaration_markdown_probes(ctx, module, case):
    """Auto-dichiarazione — fronte del DERIVATO, fixture RICCA. Il
    documento sotto validazione e' INPUT NON FIDATO: cio' che dichiara in
    campi propri non allarga l'insieme degli identificatori o delle rese
    numeriche che la scansione del derivato considera autoritativi.

    (a) codici di decisione AUTO-dichiarati e exploit nel paragrafo `FR-S1`
    (`ft01_markdown_only`); (b) una domanda di decisione riscritta con la
    frase in chiaro, riciclata nel paragrafo; (c) un codice di decisione con
    cifre, nella SOLA propria riga di elenco. Ogni variante e' respinta con
    `derived_artifact_numeric_mismatch`, che NOMINA le cifre."""
    findings = []
    recycled = json.loads(json.dumps(case["document"]))
    for item in recycled["funding_request"]["dependencies_and_assumptions"][
            "decision_needed"]:
        if item["code"] == "FR-TERM-VALUATION":
            item["question"] = PLAIN_EXPLOIT
    variants = (
        ("codici-auto-dichiarati", ft01_markdown_only(module, case)[0],
         TF01_EXPLOIT, ("5000000", "20")),
        ("domanda-riciclata", recycled, PLAIN_EXPLOIT, ("5000000", "20")),
        ("codice-nella-propria-riga",
         self_declared_decisions(case, ("FR-VALUTAZIONE-5000000",
                                        "Quale valutazione si propone?")),
         None, ("5000000",)),
    )
    for label, document, prose, invented in variants:
        markdown = module.render_request(document)
        if prose:
            markdown = markdown_with_prose(case, prose, markdown)
        verdict = probe_with_markdown(ctx, case, document, markdown,
                                      f"tok-md-{label}")
        problems = rejects(verdict, CODE_DERIVED_MISMATCH,
                           f"auto-dichiarazione (derivato) {label}")
        findings += problems
        if not problems:
            findings += names_all(verdict, CODE_DERIVED_MISMATCH, invented,
                                  f"auto-dichiarazione (derivato) {label}")
    return findings


def unresolved_rewrite_probes(ctx, module, case):
    """Messaggio irrisolto riscritto — fixture a copertura NULLA, la sola
    con una voce di validazione irrisolta REALE. La voce copiata FEDELMENTE
    dallo Stage 10 resta esente nella SOLA propria riga: l'autorita' e' il
    canonico dello Stage 10, non il documento sotto validazione. Un messaggio
    RISCRITTO dal candidate non lo e': la frase riciclata nel paragrafo
    `FR-S1`, o anche nella sola riga di elenco, e' respinta e nominata."""
    findings = []
    document = json.loads(json.dumps(case["document"]))
    items = document["funding_request"]["unresolved_validation_items"]
    if not items:
        return ["messaggio irrisolto: precondizione — la fixture a copertura nulla "
                "non porta alcuna voce irrisolta"]
    items[0]["message"] = f"{items[0]['message']} {PLAIN_EXPLOIT}"
    rendered = module.render_request(document)
    for label, markdown in (
            ("messaggio-riscritto-e-paragrafo",
             markdown_with_prose(case, PLAIN_EXPLOIT, rendered)),
            ("messaggio-riscritto-nella-propria-riga", rendered)):
        verdict = probe_with_markdown(ctx, case, document, markdown,
                                      f"tok-md-{label}")
        problems = rejects(verdict, CODE_DERIVED_MISMATCH,
                           f"auto-dichiarazione (derivato) {label}")
        findings += problems
        if not problems:
            findings += names_all(verdict, CODE_DERIVED_MISMATCH,
                                  ("5000000", "20"),
                                  f"auto-dichiarazione (derivato) {label}")
    return findings


def declared_everywhere(module, case):
    """Lo STESSO token dichiarato OVUNQUE il candidate possa
    dichiararlo: codici e domande di decisione, titolo di sezione, etichetta
    d'impiego, riferimento di politica, messaggio irrisolto (dove esiste), e
    la prosa su ENTRAMBI i fronti. Ripeterlo non lo rende autoritativo."""
    document = self_declared_decisions(
        case, ("FR-DILUIZIONE-20", f"Diluizione FR-DILUIZIONE-20: "
                                   f"{PLAIN_EXPLOIT}"),
        ("MIL-5000000", "Valutazione MIL-5000000?"))
    request = document["funding_request"]
    request["narrative"]["sections"][0]["title"] = \
        "Capitale richiesto FR-DILUIZIONE-20 MIL-5000000"
    request["use_of_proceeds"][0]["label"] = "MIL-5000000 FR-DILUIZIONE-20"
    request["requested_capital"]["policy_ref"] = \
        f"{request['requested_capital']['policy_ref']}; MIL-5000000"
    for item in request.get("unresolved_validation_items") or []:
        item["message"] = f"{item['message']} MIL-5000000 FR-DILUIZIONE-20"
    request["narrative"]["sections"][0]["body"] += f" {TF01_EXPLOIT}"
    return document, module.render_request(document)


def tamper_stage11(case, prose):
    """Aggiunge `prose` alla sezione `FR-S1` del candidate canonico (byte
    DETERMINISTICI) E al paragrafo `FR-S1` di `funding-request.md`: e' la
    manomissione della prosa, sui due fronti insieme. Ritorna i
    byte del candidate manomesso."""
    document = json.loads(json.dumps(case["document"]))
    section = document["funding_request"]["narrative"]["sections"][0]
    body = str(section["body"])
    section["body"] = f"{body} {prose}"
    # Byte ESATTI, senza traduzione dei fine riga della piattaforma: il
    # confronto col canonico pubblicato e' byte per byte.
    candidate = canonical_json(document).encode("utf-8")
    case["paths"]["canonical"].write_bytes(candidate)
    request_md = case["paths"]["request"]
    raw = request_md.read_bytes()
    anchor = body.encode("utf-8")
    if anchor not in raw:
        raise HarnessDefect(
            f"il paragrafo FR-S1 non compare in {REQUEST_NAME}: la "
            "manomissione del derivato non sarebbe costruibile")
    request_md.write_bytes(raw.replace(
        anchor, f"{body} {prose}".encode("utf-8"), 1))
    return candidate


def tm_fabricated_id_exploit(ctx, base):
    """L'exploit degli id fabbricati sul percorso REALE,
    che il Transaction Manager NON modificato percorre.

    Manomesso l'exploit nel candidate canonico e nel derivato di una fixture
    RICCA: l'egress lo RESPINGE nominando `5000000` e `20`; l'`advance-stage`
    REALE NON pubblica nulla; la validation view di impact, col canonico
    manomesso iniettato, lo RESPINGE. Controllo positivo sullo STESSO
    percorso: la prosa con gli id REGISTRATI passa egress, e' pubblicata
    byte per byte e passa l'impact sulla view."""
    findings = []
    tm = transaction_manager(ctx)
    case = prepare(ctx, base, "ids-tm-exploit", hook=with_registered_ids)
    if not_built(case, findings, "nessuna funding request da manomettere"):
        return findings
    project = Path(case["project"])
    published = project / STAGE11 / CANONICAL_NAME
    tampered = tamper_stage11(case, TF01_EXPLOIT)
    verdict = run_validator(ctx, project, case["paths"]["candidate"])
    problems = rejects(verdict, CODE_NARRATIVE, "id fabbricati (TM) egress exploit")
    problems += rejects(verdict, CODE_DERIVED_MISMATCH,
                        "id fabbricati (TM) egress exploit, derivato")
    findings += problems
    if not problems:
        named = named_in(verdict, CODE_NARRATIVE)
        for number in ("5000000", "20"):
            if f"'{number}'" not in named:
                findings.append(f"id fabbricati (TM) egress: il rifiuto non NOMINA "
                                f"{number!r}")
    exit_code, out, err = advance_stage11(ctx, case)
    if exit_code == 0 or published.is_file():
        findings.append(
            f"id fabbricati (TM) l'advance-stage REALE ha PUBBLICATO l'exploit (exit "
            f"{exit_code}, canonico pubblicato: {published.is_file()}): "
            f"{out.strip()[:200]!r}")
    results, _ = run_impact_on_view(
        ctx, tm, project, [STAGE11],
        {f"{STAGE11}/{CANONICAL_NAME}": tampered}, tx="tx-s11-impact-ids")
    invoked = [result for result in results
               if result["validator"] == "validate_funding_request"]
    if not invoked or invoked[0]["exit_code"] == 0 or \
            CODE_NARRATIVE not in report_codes(invoked[0]):
        findings.append(
            "id fabbricati (TM) la validation view di impact ACCETTA l'exploit: "
            f"{[(r['exit_code'], report_codes(r)) for r in invoked]}")

    clean = prepare(ctx, base, "ids-tm-registrati", hook=with_registered_ids)
    if not_built(clean, findings, "nessuna funding request per il controllo "
                                  "positivo sul percorso REALE"):
        return findings
    ids = registered_ids_of(clean)
    candidate = tamper_stage11(clean, f"Riferimenti registrati: "
                                      f"{', '.join(ids)}.")
    findings += accepts(run_validator(ctx, clean["project"],
                                      clean["paths"]["candidate"]),
                        "(positivo id registrati, TM) egress con id registrati")
    exit_code, out, err = advance_stage11(ctx, clean)
    published = Path(clean["project"]) / STAGE11 / CANONICAL_NAME
    if exit_code != 0 or not published.is_file() or \
            published.read_bytes() != candidate:
        findings.append(
            f"(positivo id registrati, TM) advance-stage REALE con id registrati non "
            f"pubblica il candidate validato (exit {exit_code}): "
            f"{out.strip()[:200]!r} {err.strip()[:200]!r}")
        return findings
    results, _ = run_impact_on_view(ctx, tm, Path(clean["project"]),
                                    [STAGE11], tx="tx-s11-impact-ids-pos")
    invoked = [result for result in results
               if result["validator"] == "validate_funding_request"]
    if not invoked or invoked[0]["exit_code"] != 0:
        findings.append(
            "(positivo id registrati, TM) impact sulla view REALE con id registrati: "
            f"{[(r['exit_code'], report_codes(r)) for r in invoked]}")
    return findings


# --------------------------------------------------------------------------
# FR-C-25 — T-FR-DETERMINISM
# --------------------------------------------------------------------------


def c25(ctx, base):
    """Generazione DETERMINISTICA: due esecuzioni consecutive ⇒ byte
    identici, confrontati con `sha256`."""
    findings = []
    case = prepare(ctx, base, "c25")
    if not_built(case, findings,
                 "nessun artefatto e' prodotto, quindi due esecuzioni non "
                 "sono confrontabili byte per byte"):
        return findings
    findings += accepts(case["validated"], "(positivo) prima esecuzione")

    first = {name: sha256_of(path)
             for name, path in (("canonical", case["paths"]["canonical"]),
                                ("handoff", case["paths"]["handoff"]),
                                ("request", case["paths"]["request"]))
             if Path(path).is_file()}
    second_run = run_builder(ctx, case["project"], tx=case["tx"])
    if second_run.get("exit_code") != 0:
        findings.append(
            f"la seconda esecuzione fallisce (exit {second_run.get('exit_code')}"
            f"): {(second_run.get('stderr') or '')[:200]}")
        return findings
    second = {name: sha256_of(path)
              for name, path in (("canonical", case["paths"]["canonical"]),
                                 ("handoff", case["paths"]["handoff"]),
                                 ("request", case["paths"]["request"]))
              if Path(path).is_file()}
    divergent = sorted(name for name in first
                       if first.get(name) != second.get(name))
    if divergent:
        findings.append(
            f"due esecuzioni consecutive producono byte DIVERSI per "
            f"{divergent}: la generazione non e' deterministica")

    # MUT-11-25 — ordinamento dipendente dall'ordine di inserimento del
    # dizionario invece che dalla forma canonica ordinata: il verificatore
    # deve respingere un canonico che due esecuzioni non riprodurrebbero
    # byte per byte.
    document = json.loads(
        case["paths"]["canonical"].read_text(encoding="utf-8"))
    unordered = dict(reversed(list(document.items())))
    if json.dumps(unordered, indent=2, ensure_ascii=True, sort_keys=False) == \
            json.dumps(document, indent=2, ensure_ascii=True, sort_keys=True):
        findings.append(
            "MUT-11-25 non e' costruibile: il documento non ha due chiavi di "
            "primo livello da riordinare")
        return findings
    paths = stage11_paths(case["project"], "m-s11-25")
    paths["candidate"].mkdir(parents=True, exist_ok=True)
    paths["canonical"].write_text(
        json.dumps(unordered, indent=2, ensure_ascii=True, sort_keys=False) +
        "\n", encoding="utf-8")
    paths["handoff"].write_text(
        case["paths"]["handoff"].read_text(encoding="utf-8"), encoding="utf-8")
    findings += rejects(
        run_validator(ctx, case["project"], paths["candidate"]),
        CODE_NONDETERMINISTIC, "MUT-11-25")
    return findings


# --------------------------------------------------------------------------
# FR-C-26 — T-FR-ATOMIC-OUTPUT
# --------------------------------------------------------------------------


def c26(ctx, base):
    """Nessun output parziale: un fallimento INIETTATO dopo il primo file
    pubblicato lascia lo stato precedente INTATTO — `sha256` di TUTTI gli
    artefatti invariati."""
    findings = []
    case = prepare(ctx, base, "c26")
    if not_built(case, findings,
                 "nessun publisher atomico a due livelli esiste, quindi un "
                 "fallimento non e' dimostrabile senza output parziale"):
        return findings
    findings += accepts(case["validated"], "(positivo) pubblicazione completa")

    project = Path(case["project"])
    before = tree_hashes(project / STAGE11)
    failed = run_builder(ctx, project, tx=case["tx"],
                         env_extra={"BPO_FR_TEST_FAIL": "after_first_publish"})
    if not failed.get("available", True):
        findings.append(f"MUT-11-26: {failed['reason']}")
        return findings
    if failed.get("exit_code") == 0:
        findings.append(
            "MUT-11-26: il fallimento iniettato non ha fermato la "
            "pubblicazione")
    if CODE_PARTIAL_OUTPUT not in (failed.get("codes") or set()):
        findings.append(
            f"MUT-11-26: atteso il codice {CODE_PARTIAL_OUTPUT!r}, ottenuti "
            f"{sorted(failed.get('codes') or ())}")
    after = tree_hashes(project / STAGE11)
    if after != before:
        changed = sorted(set(before) ^ set(after)) or sorted(
            name for name in before if before[name] != after.get(name))
        findings.append(
            f"MUT-11-26: il fallimento ha lasciato uno stato DIVERSO: {changed}")
    leftovers = sorted(path.name for path in (project / STAGE11).rglob("*.part"))
    if leftovers:
        findings.append(
            f"MUT-11-26: file temporanei ORFANI dopo il fallimento: {leftovers}")

    # Il SECONDO punto di fallimento dichiarato, `staging`: il fallimento
    # durante lo staging non tocca alcun bersaglio.
    failed = run_builder(ctx, project, tx=case["tx"],
                         env_extra={"BPO_FR_TEST_FAIL": "staging"})
    if failed.get("exit_code") == 0 or \
            CODE_PARTIAL_OUTPUT not in (failed.get("codes") or set()):
        findings.append(
            f"MUT-11-26 (staging): atteso il rifiuto {CODE_PARTIAL_OUTPUT!r}, "
            f"ottenuti exit {failed.get('exit_code')} e "
            f"{sorted(failed.get('codes') or ())}")
    if tree_hashes(project / STAGE11) != before:
        findings.append(
            "MUT-11-26 (staging): il fallimento durante lo staging ha lasciato "
            "uno stato DIVERSO")
    leftovers = sorted(path.name for path in (project / STAGE11).rglob("*.part"))
    if leftovers:
        findings.append(
            f"MUT-11-26 (staging): file temporanei ORFANI: {leftovers}")
    return findings


# --------------------------------------------------------------------------
# FR-C-27 — T-FR-NO-FINDING-CLOSED
# --------------------------------------------------------------------------


#: Le decisioni aperte e le condizioni che lo Stage 11 PORTA senza chiuderle:
#: i termini finanziari ignoti, la condizione di copertura di scenario e il
#: collegamento capitale-milestone. Helper di `FR-C-27` (`closure_claims`),
#: non collegato al registro `CONTRACTS`.
CARRIED_DEBTS = ("FR-TERM-CONDITIONS", "FR-TERM-DILUTION", "FR-TERM-INSTRUMENT",
                 "FR-TERM-ROUND-SIZE", "FR-TERM-VALUATION",
                 "COND-S10-SCENARIO-COVERAGE", "FR-MILESTONE-FINANCING")

#: Un verbo di CHIUSURA, in qualunque grafia, italiano o inglese. La forma
#: NEGATA immediatamente precedente («non sanata», «NON e' chiuso», «not
#: closed») non e' una chiusura e resta ammessa.
CLOSURE_RE = re.compile(
    r"(?i)(?P<neg>\b(?:non|not|mai|never)\s+(?:(?:e'|è|is|was|been|viene|"
    r"stat[oaie])\s+)?)?\b(?:chius[oaie]|closed?|sanat[oaie]|resolved)\b")


def closure_claims(text):
    """Le righe che dichiarano CHIUSO uno dei debiti portati."""
    claims = []
    for line in text.splitlines():
        if not any(debt in line for debt in CARRIED_DEBTS):
            continue
        for match in CLOSURE_RE.finditer(line):
            if match.group("neg") is None:
                claims.append(line.strip())
                break
    return claims


# --------------------------------------------------------------------------
# Registro dei contratti
# --------------------------------------------------------------------------


CONTRACTS = [
    {"id": "FR-C-01", "name": "T-FR-CANONICAL-ONLY-SOURCE", "fn": c01,
     "fixture": "F-1 piena, pipeline Stage 10 di produzione",
     "expected_code": CODE_NON_CANONICAL, "mutation": "MUT-11-01",
     "observation": "nessuna proiezione esiste, quindi nessun valore emesso "
                    "risale a un path canonico dichiarato"},
    {"id": "FR-C-02", "name": "T-FR-INPUT-COMPLETENESS", "fn": c02,
     "fixture": "F-1 con workbook rimosso",
     "expected_code": CODE_INPUT_INCOMPLETE, "mutation": "MUT-11-02",
     "observation": "il gate di ingresso a tre artefatti non esiste, quindi un "
                    "ingresso incompleto non e' respinto prima della scrittura"},
    {"id": "FR-C-03", "name": "T-FR-POLICY-DECLARED", "fn": c03,
     "fixture": "F-1", "expected_code": CODE_POLICY_UNDECLARED,
     "mutation": "MUT-11-03",
     "observation": "nessun capital_requirement esiste, quindi la politica di "
                    "capitalizzazione non e' dichiarata da alcun portatore"},
    {"id": "FR-C-04", "name": "T-FR-CAPITAL-RECONCILIATION", "fn": c04,
     "fixture": "F-1 + ramo primario con buffer", "expected_code": CODE_CAPITAL_RECON,
     "mutation": "MUT-11-04",
     "observation": "nessuna riconciliazione del capitale richiesto esiste, "
                    "quindi il residuo non e' misurato contro alcuna tolleranza"},
    {"id": "FR-C-05", "name": "T-FR-ALLOCATION-SUM", "fn": c05,
     "fixture": "F-1 + variante a due categorie", "expected_code": CODE_ALLOCATION_SUM,
     "mutation": "MUT-11-05",
     "observation": "nessun use_of_proceeds esiste, quindi la somma degli "
                    "impieghi non e' confrontata col capitale richiesto"},
    {"id": "FR-C-06", "name": "T-FR-PERCENTAGE-SUM", "fn": c06,
     "fixture": "F-1", "expected_code": CODE_PERCENTAGE_SUM,
     "mutation": "MUT-11-06",
     "observation": "nessuna percentuale di impiego esiste, quindi la "
                    "ridondanza importo/percentuale non e' verificata"},
    {"id": "FR-C-07", "name": "T-FR-CATEGORY-TRACEABILITY", "fn": c07,
     "fixture": "F-1", "expected_code": CODE_CATEGORY, "mutation": "MUT-11-07",
     "observation": "nessun candidate_ref esiste, quindi nessuna categoria di "
                    "impiego risale ai candidati del canonico dello Stage 10"},
    {"id": "FR-C-08", "name": "T-FR-HORIZON-MATCH", "fn": c08,
     "fixture": "F-1", "expected_code": CODE_HORIZON, "mutation": "MUT-11-08",
     "observation": "nessun orizzonte e' dichiarato, quindi non e' confrontato "
                    "campo per campo con results.calendar"},
    {"id": "FR-C-09", "name": "T-FR-RUNWAY-BEFORE", "fn": c09,
     "fixture": "F-1 fallback + ramo primario con buffer", "expected_code": CODE_RUNWAY_BEFORE,
     "mutation": "MUT-11-09",
     "observation": "nessun runway ante-finanziamento esiste, quindi le due "
                    "misure canoniche non sono ne' lette ne' tenute distinte"},
    {"id": "FR-C-10", "name": "T-FR-RUNWAY-AFTER", "fn": c10,
     "fixture": "F-1", "expected_code": CODE_RUNWAY_AFTER,
     "mutation": "MUT-11-10",
     "observation": "nessun runway post-finanziamento esiste, quindi non e' "
                    "ricostruito periodo per periodo dal flusso di cassa"},
    {"id": "FR-C-11", "name": "T-FR-MILESTONE-COSTED", "fn": c11,
     "fixture": "variante con milestone + F-1 senza copertura", "expected_code": CODE_MILESTONE_COST,
     "mutation": "MUT-11-11",
     "observation": "nessun milestone_financing esiste, quindi le milestone "
                    "fuori orizzonte non sono ne' lette ne' dichiarate"},
    {"id": "FR-C-12", "name": "T-FR-MILESTONE-IN-ROADMAP", "fn": c12,
     "fixture": "F-1", "expected_code": CODE_MILESTONE_ROADMAP,
     "mutation": "MUT-11-12",
     "observation": "nessun milestone_ref e' emesso, quindi nessuna "
                    "risoluzione contro la roadmap dello Stage 9 e' esercitata"},
    {"id": "FR-C-13", "name": "T-FR-TRANCHE-SUPPORT", "fn": c13,
     "fixture": "F-1", "expected_code": CODE_TRANCHE, "mutation": "MUT-11-13",
     "observation": "nessun portatore di tranche esiste, quindi lo stato "
                    "not_supported non e' dichiarato da alcun campo"},
    {"id": "FR-C-14", "name": "T-FR-SCENARIO-IDS", "fn": c14,
     "fixture": "F-1", "expected_code": CODE_SCENARIO_ID,
     "mutation": "MUT-11-14",
     "observation": "nessuna scenario_sensitivity esiste, quindi gli id di "
                    "scenario non sono confrontati con l'enum canonico"},
    {"id": "FR-C-15", "name": "T-FR-SCENARIO-NOT-FABRICATED", "fn": c15,
     "fixture": "F-3 copertura none", "expected_code": CODE_SCENARIO_FABRICATED,
     "mutation": "MUT-11-15",
     "observation": "nessuno scenario e' emesso, quindi con copertura none non "
                    "esiste alcun NOT_APPLICABLE dichiarato da misurare"},
    {"id": "FR-C-16", "name": "T-FR-RESIDUAL-GAP-DISCLOSED", "fn": c16,
     "fixture": "F-1", "expected_code": CODE_RESIDUAL_GAP,
     "mutation": "MUT-11-16",
     "observation": "nessuna sufficiency esiste, quindi il gap residuo non e' "
                    "ne' esposto ne' vincolato a una dichiarazione obbligatoria"},
    {"id": "FR-C-17", "name": "T-FR-NO-INVENTED-TERMS", "fn": c17,
     "fixture": "F-1, sette iniezioni", "expected_code": CODE_INVENTED_TERMS,
     "mutation": "MUT-11-17",
     "observation": "nessun documento e' emesso, quindi i sette termini "
                    "vietati non sono respinti ne' per contratto"},
    {"id": "FR-C-18", "name": "T-FR-DECISION-NEEDED", "fn": c18,
     "fixture": "F-1 senza e con profilo", "expected_code": CODE_DECISION_NEEDED,
     "mutation": "MUT-11-18",
     "observation": "nessun decision_needed esiste, quindi un termine ignoto "
                    "non riceve uno stato dichiarato e il profilo non e' letto"},
    {"id": "FR-C-19", "name": "T-FR-NO-ASSUMPTION-PROMOTED", "fn": c19,
     "fixture": "F-1 + alias ASS nel registro", "expected_code": CODE_ASSUMPTION_PROMOTED,
     "mutation": "MUT-11-19",
     "observation": "nessun unvalidated_count e' emesso, quindi nessuna "
                    "assunzione e' confrontata col registro ufficiale"},
    {"id": "FR-C-20", "name": "T-FR-NO-FALSE-PRECISION", "fn": c20,
     "fixture": "F-1", "expected_code": CODE_FALSE_PRECISION,
     "mutation": "MUT-11-20",
     "observation": "nessun rounding_applied e' dichiarato, quindi la coerenza "
                    "fra politica e cifre emesse non e' misurabile"},
    {"id": "FR-C-21", "name": "T-FR-PROVENANCE-TOTAL", "fn": c21,
     "fixture": "F-1 + alias EVD/SRC nei registri e nel documento",
     "expected_code": CODE_PROVENANCE, "mutation": "MUT-11-21",
     "observation": "nessuna provenance[] esiste, quindi il join fra campi "
                    "numerici e provenienza non ha residuo da misurare"},
    {"id": "FR-C-22", "name": "T-FR-TRIANGULAR-CONSISTENCY", "fn": c22,
     "fixture": "F-1 con derivato alterato + view impact del TM",
     "expected_code": CODE_DERIVED_MISMATCH, "mutation": "MUT-11-22",
     "observation": "nessun funding-request.md e' reso, quindi il confronto "
                    "triangolare con canonico, capitolo e workbook non esiste"},
    {"id": "FR-C-23", "name": "T-FR-UNRESOLVED-ITEMS", "fn": c23,
     "fixture": "F-1", "expected_code": CODE_UNRESOLVED_ITEMS,
     "mutation": "MUT-11-23",
     "observation": "nessun unresolved_validation_items[] esiste, quindi le "
                    "voci irrisolte del canonico non sono ne' copiate ne' "
                    "contate"},
    {"id": "FR-C-24", "name": "T-FR-NARRATIVE-TRACED", "fn": c24,
     "fixture": "F-1 + numeri inventati", "expected_code": CODE_NARRATIVE, "mutation": "MUT-11-24",
     "observation": "nessuna narrative esiste, quindi nessun letterale "
                    "numerico della prosa e' tracciato a una provenienza"},
    {"id": "FR-C-25", "name": "T-FR-DETERMINISM", "fn": c25,
     "fixture": "F-1, due esecuzioni", "expected_code": CODE_NONDETERMINISTIC,
     "mutation": "MUT-11-25",
     "observation": "nessun artefatto e' prodotto, quindi due esecuzioni non "
                    "sono confrontabili byte per byte"},
    {"id": "FR-C-26", "name": "T-FR-ATOMIC-OUTPUT", "fn": c26,
     "fixture": "F-1 con fallimento iniettato (due punti)",
     "expected_code": CODE_PARTIAL_OUTPUT, "mutation": "MUT-11-26",
     "observation": "nessun publisher atomico a due livelli esiste, quindi un "
                    "fallimento non e' dimostrabile senza output parziale"},
]

CONTRACT_IDS = tuple(entry["id"] for entry in CONTRACTS)


# --------------------------------------------------------------------------
# Esecuzione
# --------------------------------------------------------------------------


def run_one(ctx, contract):
    """Un'uccisione PER ECCEZIONE non e' evidenza RED: la
    constatazione ATTRIBUITA del contratto prende il posto del traceback."""
    with tempfile.TemporaryDirectory(prefix="s11_fr_") as base:
        try:
            findings = contract["fn"](ctx, Path(base))
        except HarnessDefect:
            raise
        except (AssertionError, AttributeError, ImportError, IndexError,
                KeyError, OSError, TypeError, ValueError) as exc:
            findings = [f"constatazione: {contract['observation']} — "
                        f"superficie assente o incompleta: {exc!r}"]
    return {"contract": contract, "red": bool(findings), "findings": findings}


def format_line(result):
    contract = result["contract"]
    return ("{state:<5} {cid:<12} {name:<32} fixture={fixture} | EXPECTED: "
            "{exp} | mutazione={mut} | reason={reason}".format(
                state="RED" if result["red"] else "GREEN",
                cid=contract["id"], name=contract["name"],
                fixture=contract["fixture"], exp=contract["expected_code"],
                mut=contract["mutation"],
                reason="; ".join(result["findings"]) or "-"))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(
        prog="test_funding_request.py", add_help=True,
        description="I 26 contratti della Funding Request.")
    parser.add_argument("--root", required=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--contract", help="esegue un solo contratto")
    mode.add_argument("--all", action="store_true",
                      help="esegue tutti i contratti (default)")
    parser.add_argument("--list", action="store_true",
                        help="elenca gli id dei contratti ospitati qui")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE

    if args.list:
        for contract_id in CONTRACT_IDS:
            print(contract_id)
        return EXIT_OK

    try:
        root = resolve_root(args.root)
    except HarnessUsageError as exc:
        print(f"USAGE ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.contract and args.contract not in CONTRACT_IDS:
        print(f"USAGE ERROR: contratto inesistente: {args.contract}; ammessi: "
              f"{', '.join(CONTRACT_IDS)}", file=sys.stderr)
        return EXIT_USAGE

    global XLSX, CHAPTER, M5A
    try:
        # Una sola catena di costruzione dell'ingresso: l'harness del workbook
        # riusa quello del capitolo, che riusa quello del canonico, che riusa
        # quello del motore. Nessuna fixture e' duplicata qui.
        XLSX = load_harness(root, XLSX_HARNESS)
        XLSX.CHAPTER = XLSX.load_chapter_harness(root)
        XLSX.GATE = XLSX.load_gate(root)
        CHAPTER = XLSX.CHAPTER
        M5A = CHAPTER.M5A
        ctx = build_context(root)
        selected = [entry for entry in CONTRACTS
                    if not args.contract or entry["id"] == args.contract]
        results = [run_one(ctx, entry) for entry in selected]
    except HarnessDefect as exc:
        print(f"HARNESS DEFECT: {exc}", file=sys.stderr)
        drop_baseline()
        return EXIT_STATE
    except HarnessUsageError as exc:
        print(f"USAGE ERROR: {exc}", file=sys.stderr)
        drop_baseline()
        return EXIT_USAGE
    finally:
        pass

    # Le constatazioni RED citano rese Unicode (`\u2212`, apici,
    # cifre cerchiate): la riga di esito non deve fallire sulla codifica della
    # console, e un carattere non codificabile e' reso come sequenza di escape.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    for result in results:
        print(format_line(result))
    red = [result for result in results if result["red"]]
    reasons = {"; ".join(result["findings"]) for result in red}
    print("SUMMARY: {total} contratti, {red} RED, {green} GREEN "
          "(constatazioni DISTINTE: {distinct}/{red}; modulo {v}: {vs})".format(
              total=len(results), red=len(red), green=len(results) - len(red),
              distinct=len(reasons), v=FR_VALIDATOR_REL,
              vs="presente" if ctx["fr_validator"].is_file() else "ASSENTE"))
    drop_baseline()
    if red:
        return EXIT_RED
    print("PASS: T-FUNDING-REQUEST {n} contratti della Funding Request "
          "(Stage 11)"
          .format(n=len(results)))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
