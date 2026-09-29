# Metodologia — Data Room (Stage 12)

Caricata **on-demand** dal workflow
[`workflows/13_data-room.md`](../workflows/13_data-room.md) e dal
runtime-agent
[`runtime-agents/evidence-analyst.md`](../runtime-agents/evidence-analyst.md).
Le classi di evidenza sono quelle di
[`methodology/evidence-framework.md`](evidence-framework.md), esatte e non
parafrasabili.

---

## 1. Il principio, prima di ogni regola

> La Data Room risponde a una sola domanda: **quali prove sostengono le
> affermazioni del piano?** Contiene solo ciò che rende verificabile il piano.

Non è l'archivio degli allegati della funding request, e non è un secondo
autore del piano. È lo **strato di evidenza** dell'intero business plan: per
ogni affermazione materiale — dal problema alla richiesta di capitale — dice
quale evidenza la sostiene, quale la contraddice e quale manca. Un piano la
cui Data Room è vuota non è un piano senza allegati: è un piano **non
verificabile**, e la Data Room lo deve mostrare invece di nasconderlo.

```text
INDICIZZA, NON GENERA E NON RISCRIVE
NESSUNA ASSUNZIONE PROMOSSA A PROVA
NESSUNA LACUNA SOPPRESSA
NESSUNA CONTRADDIZIONE FUSA NELLA PIÙ RECENTE
NESSUN DEBITO CHIUSO PERCHÉ INDICIZZATO
```

## 2. Undici sezioni, una partizione logica

Il manifest canonico `12_data-room/structured-output.json` è diviso in
**undici** sezioni, elenco chiuso e ordine fisso: dalla
`01_corporate-and-governance` alla `11_generated-artifact-metadata`. Le
sezioni sono una **partizione logica** del manifest: **nessuna cartella
fisica** è creata. Ogni documento resta al proprio path relativo
**esistente** nel progetto, e appartiene a una e una sola sezione. Una sezione
senza documenti è emessa `NOT_APPLICABLE` con una `reason`, mai omessa.

## 3. Il manifest dei documenti

| Campo | Regola |
|---|---|
| `document_id` | `DR-*` in forma canonica degli id, unico; allocato dal costruttore nell'ordine `(ordinale della related_section, path)` |
| `origin` | `source` per un file fornito dall'utente, `generated` per un artefatto del sistema: mai implicito. `generated` spetta **solo** a un registro condiviso o all'uscita canonica, all'handoff o a un derivato dichiarato di uno stage precedente la Data Room: un file dell'utente non diventa generato dichiarandolo tale |
| `artifact_type` | enum chiuso: `source_type` del registro delle fonti più i tipi generati; per un generato è il tipo del suo path (`shared_register`, `stage_canonical_output`, `stage_handoff`, `derived_*`) |
| `path` | relativo al progetto, contenuto, la stessa regola di `safe_rel_path`: un path che esce dal progetto è `path_escape`. È la **grafia canonica** del file su disco: un alias (maiuscole diverse, nome 8.3, punto o spazio finale) è `path_escape`, e le guardie d'area — area nascosta, `12_data-room/`, stage oltre la Data Room — valgono per il file effettivamente nominato |
| `availability` | `available` · `expected` · `missing`, esplicito: l'assenza di un artefatto obbligatorio è **visibile**. `expected` spetta solo a un documento atteso dichiarato dall'analista: un obbligatorio o un generato assente è `missing` |
| `checksum` | `sha256` ricalcolato per ogni `available`; `null` **solo** per `expected` e `missing` |
| `version` | non vuota e **identica** nel manifest e nell'indice derivato |
| `owner` | l'enum del registro delle condizioni: `founder` · `external` · `orchestrator` |
| `confidentiality` | `NOT_SUPPORTED`: nessun portatore di riservatezza esiste, e non se ne inventa uno |
| `validation_status` | l'enum dello `status` del registro delle evidenze; `needs_info` per un documento `missing`, mai `validated` per un `expected`; per un generato disponibile `open` (registro) o `validated` |
| `evidence_quality` | il `quality_rating` del registro delle fonti per la **stessa** fonte (`url_or_path` uguale al path del documento); `null` se la fonte non è registrata |
| `derived_from` | per un riassunto generato (handoff, capitolo, workbook, funding request) il `DR-*` del canonico da cui deriva |

Sono **obbligatori** i tre registri condivisi (assunzioni, evidenze, fonti),
l'uscita canonica di ogni stage completato da 1 a 11 e i derivati degli
Stage 10 e 11. Un obbligatorio assente resta nel manifest come `missing`.

**Un file, un documento.** L'identità di un path è la sua grafia canonica
su disco, poi NFC e `casefold`; due documenti che nominano lo stesso file —
anche attraverso un alias o un hard link — sono un duplicato. Una fonte si
dichiara **una sola volta**: una seconda dichiarazione con la stessa identità
(anche dopo NFC/NFD) è respinta, mai fusa per «vince l'ultima».

**Il registro delle fonti.** `url_or_path` è una stringa libera. È
indicizzato come documento **solo** un path relativo di progetto che nomina
un file esistente. Un URL o un URI con schema (`https:`, `mailto:`, `doi:`),
un dominio nudo, una citazione o un'annotazione, o un path che non esiste
nel progetto, **restano nel registro** e non bloccano lo Stage 12; un path di
filesystem che esce dal progetto (assoluto, lettera di drive, backslash, `~`,
`..`) è `path_escape` e non è mai letto.

## 4. Claim e legami

Lo spazio di nomi **`CLM-*`** è introdotto dallo Stage 12 e da nessun altro:

```text
CLM-<id>    ^CLM-(?:[0-9]{3}|[1-9][0-9]{3,})$     forma canonica degli id
```

Gli identificatori `CLM-*` sono **definiti e allocati soltanto** nel
canonico dello Stage 12, come `$defs.clm_id` tipizzato e riusato per `$ref`.
La proposta dell'analista usa chiavi locali; il costruttore alloca
`CLM-001`, `CLM-002`, … nell'ordine `(ordinale della related_section,
chiave)`. Un alias (`CLM-0001`) o un id fuori spazio di nomi è respinto,
mai normalizzato. Ogni `related_claims[]` e ogni legame **risolve** contro
quel registro.

**Ogni claim registrato è materiale.** Non esiste una classe di claim non
materiale e nessuna materialità è decisa a runtime: è la scelta fail-closed.

Ogni legame porta uno stato — `supporting`, `contradicting`, `partial`,
`missing` — e la classe **registrata** della propria evidenza: le sei classi
sono esatte e una classe diversa da quella del registro è una promozione
silenziosa. Lo stato `missing` spetta solo a un legame senza evidenza o a una
`missing_information`. Ogni claim porta una provenienza `{section,
paragraph_anchor}`, con `null` **esplicito** dove non disponibile: assente
non è non disponibile.

Un claim è `supported` solo se un legame `supporting` lo collega a
un'evidenza registrata, non respinta e **probatoria** — `verified_fact`,
`internal_evidence` o `external_source`. Un'assunzione del founder o una
stima di modello restano assunzioni: non sostengono un claim. Un claim con un
legame `supporting` e uno `contradicting` è `contested`. Ogni evidenza
registrata che tocca le assunzioni di un claim **deve** comparire fra i suoi
legami: scartarne una è una fusione.

Ogni evidenza — e il legame senza evidenza — si collega a un claim **una
sola volta**: un legame ripetuto gonfierebbe la distribuzione per classe. Un
legame che localizza la propria evidenza in un documento nomina un documento
che **porta** quell'evidenza (`evidence_refs`); un legame `supporting` la
localizza in un documento `available`, mai in uno atteso o mancante.

## 5. Evidenza stantia — il criterio dichiarato

La staleness è una funzione **deterministica** dei soli ingressi dichiarati,
senza alcuna lettura dell'orologio:

```text
reference_date   dichiarata dall'analista (as_of della proposta)
max_age_days     dichiarata dall'analista
age              reference_date − date dell'evidenza nel registro

current   se 0 <= age <= max_age_days
stale     se age > max_age_days
undated   se la data manca, non è ISO 8601 (YYYY-MM-DD)
          o è successiva a reference_date
```

Un'evidenza è `verified` solo se il registro la dichiara `validated`; ogni
altra è `unverified`, e la marcatura non si attenua.

## 6. Lacune, conflitti, orfane, completezza

- **Lacune irrisolte** (`unresolved_evidence_gaps`): ogni claim non
  supportato, ogni legame `missing`, ogni assunzione senza `evidence_refs`,
  ogni evidenza `missing_information`. Quando tutte le assunzioni hanno
  `evidence_refs` vuoti, la lista **non** è vuota.
- **Conflitti**: due evidenze opposte sullo stesso claim, o due voci del
  registro con lo stesso enunciato, aprono `INCOERENZA RILEVATA` nel formato
  di `SKILL.md`: mai la più recente, mai la più comoda.
- **Orfane**: un'evidenza registrata non collegata ad alcun claim né ad
  alcun documento è **rilevata** e marcata, mai scartata.
- **Completezza**: la copertura è riportata con il denominatore (i claim
  registrati) e la distribuzione dei legami per classe di evidenza, **in
  ogni superficie** che la stampa — indice derivato e handoff canonico. Una
  copertura del 100% fatta di sole assunzioni del founder non esiste: quei
  claim non sono supportati.

Le liste dichiarate sono la derivazione **esatta** dai legami e dai
registri, record per record: molteplicità, identità, tipo e contenuto. Una
lacuna o un conflitto duplicato è respinto; una lacuna inventata, riscritta
o di tipo diverso è respinta; un riferimento che non risolve (`CLM-*`,
`EVD-*`, `ASS-*`) è un FAIL attribuito, mai una voce accettata. Un conflitto
dichiarato porta severità, decisione richiesta e file coinvolti del
conflitto derivato: non si attenua. Nell'indice delle evidenze ogni record è
valutato: un record «ombra» dello stesso `EVD-*` è un duplicato.

## 7. Debiti esposti, mai chiusi dall'indice

Ogni condizione del registro è esposta in `open_items`. Una voce è `CHIUSO`
solo se il registro la dichiara risolta o rinunciata **con** la decisione
che la chiude (`proof_ref` = `resolved_by`); altrimenti è `APERTO`, senza
prova. L'esistenza di un indice non chiude nulla. Ogni voce è valutata e un
`item_ref` duplicato è respinto: una voce «ombra» `CHIUSO` non nasconde
quella vera. In egress la lista è la derivazione esatta del registro; in
impact una voce `APERTO` resta ammessa quando il registro, mutabile, la
risolve dopo la pubblicazione.

## 8. Identità, determinismo, segreti

L'identità del manifest è lo `sha256` del payload di identità, che
**esclude per costruzione** `generated_at` e `last_verified_at`. Due
generazioni dagli stessi ingressi producono byte identici: ordinali
espliciti, mai lessicografici; chiavi ordinate; nessun path assoluto.
Il transaction manager riscrive il canonico con `ensure_ascii=False`: il
validator ammette quella forma, e un canonico con testo non ASCII supera
egress e impact.

Gli artefatti **generati** — il manifest, l'handoff, l'indice e i documenti
`origin: generated` — sono scanditi per pattern dichiarati di segreti
(chiavi private PEM, token di provider noti, stringhe di connessione con
credenziali). I file sorgente dell'utente **non** sono ispezionati. Il
manifest e ogni JSON generato sono scanditi sulle loro **stringhe
decodificate**, la stessa rappresentazione per la forma `ensure_ascii` del
costruttore, la riscrittura UTF-8 del transaction manager e la view di
impact: un segreto adiacente a testo non ASCII («», —, €, lettere
accentate) o a un a capo non si nasconde dietro una sequenza di escape, e i
confini dei token sono definiti sull'alfabeto ASCII.

L'handoff canonico e l'indice derivato sono la resa **deterministica** del
solo manifest: l'egress li confronta per intero con quella resa, mai per
sottostringa. Un handoff assente, senza un blocco `INCOERENZA RILEVATA`, con
una copertura o voci aperte diverse dal manifest è respinto. Il testo
dell'analista (motivi delle sezioni, enunciati dei claim) è reso su **una
riga**: nessun a capo apre una riga di tabella `DR-*`, un recinto, un
`next_action` o un blocco `INCOERENZA`.

## 9. Fase impact

La validation view del transaction manager porta solo `shared/` e i
`NN_*/structured-output.json`. Un documento è nella view solo se è un
registro condiviso o l'uscita canonica di uno stage di `stage_order`: un
file dell'utente chiamato `structured-output.json` non lo è. In fase impact
i controlli su file fuori dalla view — fonti, handoff, derivati, indice —
sono `NOT_APPLICABLE` con motivo; i registri condivisi, mutabili per
transazione, sono verificati per coerenza semantica e non per byte, e sono
**scanditi per i segreti** insieme al manifest e alle uscite canoniche della
view — anche un registro presente ma non indicizzato, come il registro delle
decisioni creato da un `update-assumption` dopo la pubblicazione:
`NOT_APPLICABLE` vale solo per ciò che la view non contiene. Con il
canonico assente, la fase impact è `NOT_APPLICABLE` se lo Stage 12 non è
completato, ed è stato corrotto (exit 3) se lo è.

## 10. Scritture del costruttore

`--tx` è un **singolo segmento** sicuro (`[A-Za-z0-9._-]`, senza
separatori, lettera di drive, `:` o punto finale). Il costruttore legge e
scrive **solo** sotto `12_data-room/` — il candidate
`12_data-room/.working/<tx>/` e l'indice `12_data-room/data-room-index.md` —
e verifica, **prima** di leggere la proposta e di nuovo **prima** di ogni
scrittura, che nessun componente del path sia un symlink, una junction o un
reparse point e che il bersaglio resti nell'area autorizzata, nella grafia
canonica. Un bersaglio che uscirebbe dall'area è un rifiuto `path_escape`
attribuito e nulla è pubblicato: nessun file degli Stage 0–11 o dell'utente
è scrivibile attraverso un alias.
