# Evidence framework

> Fonte: [`reference/architecture.md`](../reference/architecture.md) §3.1, §12.3. Caricare ogni volta che un subagent
> produce un'affermazione rilevante da registrare in
> `shared/evidence-register.json` (schema: `schemas/evidence-register.schema.json`).

## Le 6 classi (esatte, non parafrasabili)

| Classe | Significato operativo | Esempio |
|---|---|---|
| `verified_fact` | Verificato in modo indipendente e riproducibile (documento ufficiale, dato di bilancio, contratto firmato) | "Il contratto di fornitura X è firmato e allegato in data room" |
| `internal_evidence` | Prodotto dall'azienda stessa, non ancora verificato esternamente (test interno, pilota, dato di prodotto) | "Il pilota con 5 clienti ha mostrato un tasso di riordino dell'80%" |
| `external_source` | Proveniente da una fonte terza (report di settore, pubblicazione, dato pubblico) | "Il report di settore Y stima il mercato europeo del software di pianificazione a N miliardi di euro (fonte X)" |
| `founder_assumption` | Dichiarato dal founder ma non ancora supportato da dati | "Riteniamo che il CAC si stabilizzerà intorno ai 900€" |
| `model_estimate` | Derivato da un calcolo/modello del sistema, non da una fonte diretta | "Stima interna: SOM = 3% del SAM sulla base di capacità commerciale" |
| `missing_information` | Gap dichiarato, nessun dato disponibile | "Non abbiamo ancora dati di churn: da validare nel primo trimestre" |

## Regola centrale

**Nessun subagent può trasformare silenziosamente un'ipotesi in un fatto.**
Una `founder_assumption` non diventa `verified_fact` solo perché viene ripetuta
in più sezioni. Passa di classe solo quando arriva una prova concreta, e il
cambio va registrato con una nuova voce (o un aggiornamento tracciato) nel
registro, non con una riscrittura silenziosa.

## Collegamento con `assumptions-register.json`

- Ogni voce di `evidence-register.json` che supporta un numero usato nel piano
  deve avere un `affected_assumptions` che punta a uno o più `ASS-<id>`.
- Se un'evidenza è `missing_information`, l'assunzione collegata resta
  `unvalidated` in `assumptions-register.json` — non va promossa a `validated`.
- Se due evidenze si contraddicono sulla stessa assunzione, non scegliere quella
  più recente o più comoda: apri `INCOERENZA RILEVATA` (vedi `SKILL.md`).

## Cosa fare quando manca informazione (`missing_information`)

1. Dichiara il gap esplicitamente (non ometterlo).
2. Valuta l'impatto (quali sezioni/numeri dipendono da questo).
3. Proponi una modalità di validazione (intervista, test, ricerca, dato di terzi).
4. Se serve procedere comunque, usa una stima prudenziale **etichettata** come
   `model_estimate`, mai come `verified_fact`.
5. Includi la stima nello scenario downside quando si arriverà al financial plan
   (Stage 10).

## Confidence e relevance

Ogni voce ha anche `confidence` (`low|medium|high`, quanto ci fidiamo della
fonte) e `relevance` (`low|medium|high`, quanto pesa sulla decisione corrente).
Un'evidenza `external_source` con `confidence: low` va comunque registrata, ma
non basta da sola a validare un'assunzione critica.
