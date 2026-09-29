> **Esempio completamente fittizio.** Azienda, persone, interviste, numeri e fonti sono inventati a scopo dimostrativo; ogni riferimento a realtà esistenti è casuale.

# Section Handoff — 00 Idea Discovery — TurniDemo

**Progetto:** TurniDemo · **Data:** 2026-07-10

## Stato
Completed

## Obiettivo della sessione
Trasformare l'idea grezza di un SaaS di workforce scheduling per piccole
catene retail/ristorazione in un concept classificato, con prompt contract
approvato e registri iniziali popolati.

## Attività completate
- Raccolta idea grezza (`raw-idea.md`).
- Step-back analysis e reverse prompting (fallback locali, dichiarati).
- Intervista strutturata via subagent `founder-interviewer`
  (`founder-answers.md`).
- Classificazione: `saas` / `pre_seed` / `business_angel` / `equity` /
  `24_months`.
- Concept consolidato (`startup-concept.md`).
- Prompt contract compilato e approvato (`prompt-contract.md`).
- Registri iniziali popolati: assunzioni, evidenze, fonti.

## Decisioni consolidate
- DEC-001 — Beachhead: catene retail/ristorazione italiane, 5-15 punti
  vendita, senza software di workforce management in uso.
- DEC-002 — Prompt contract approvato con destinatario `business_angel` e
  funding `equity` (nessuna componente di debito o bando in questa fase).

## Assunzioni utilizzate o modificate
- ASS-001 — Pricing 50-80€/punto vendita/mese (confidence: low).
- ASS-002 — Tempo risparmiato: 3-4 ore/settimana per store manager.
- ASS-003 — Tasso di conversione da demo a cliente pagante (non ancora
  stimato numericamente — placeholder da validare in Stage 5/6).

## Evidenze e fonti utilizzate
- EVD-001, EVD-002, EVD-003 — interviste qualitative con 4 titolari di
  catena (2 retail, 2 ristorazione).
- EVD-004 — mockup Figma (nessun MVP funzionante).
- SRC-001 — note interne delle interviste (fonte primaria del founder).

## Output prodotti
- `raw-idea.md`, `brainstorming-log.md`, `founder-answers.md`,
  `startup-concept.md`, `prompt-contract.md`, `stage-qa.md`
- `shared/startup-profile.json`, `shared/assumptions-register.json`,
  `shared/evidence-register.json`, `shared/source-register.json`,
  `shared/risk-register.json`, `shared/project-config.json`

## Criticità
- Nessuna incoerenza Critical aperta in questa sessione.
- Il pricing resta una `founder_assumption` a bassa confidenza: va segnalato
  esplicitamente in ogni sezione successiva che lo utilizza.

## Questioni aperte
- Manca un pilota quantitativo per validare tempo risparmiato e conversione
  (registrato in `open-questions.md`).
- Non ancora definita la risposta a "cosa succede se un competitor con più
  risorse copia la feature di conformità normativa?".

## Dipendenze per le sezioni successive
- Stage 1 (Problema e bisogno) eredita il problema come già formulato in
  `startup-concept.md` e non può contraddirlo senza aprire una nuova issue.
- Stage 2 (Customer segmentation) eredita la distinzione
  user/buyer/decision-maker/influencer già stabilita.

## Azione successiva
- Avviare Stage 1 — Problema e bisogno.

## File da leggere nella prossima sessione
1. `shared/project-status.md`
2. `shared/assumptions-register.json`
3. `00_idea-discovery/startup-concept.md` e `00_idea-discovery/prompt-contract.md`
