> **Esempio completamente fittizio.** Azienda, persone, interviste, numeri e fonti sono inventati a scopo dimostrativo; ogni riferimento a realtà esistenti è casuale.

# Brainstorming Log — Sezione 0

**Progetto:** TurniDemo · **Data:** 2026-07-10

---

## 1. Idea grezza (input dell'utente)

Vedi `raw-idea.md`.

## 2. Step-back analysis

> Capability: `/step-back-prompting` non disponibile in questa demo →
> fallback locale applicato (`fallbacks/step-back-prompting.md`).

- **Principio guida reale:** ridurre il tempo e l'errore umano nella
  pianificazione del personale nei piccoli operatori multi-sede, non
  semplicemente "fare un'app di turni".
- **Causa radice / bisogno:** i responsabili di punto vendita pianificano i
  turni manualmente (Excel/WhatsApp) senza visibilità aggregata su copertura,
  costo del lavoro e conformità normativa sulle ore di riposo.
- **Macro-obiettivo:** ridurre le ore/settimana spese in pianificazione e il
  rischio di sanzioni per turni non conformi, non "avere più funzionalità
  dell'app rispetto ai concorrenti".
- **Rischi di curare il sintomo:** costruire subito uno scambio-turni
  sofisticato senza prima validare che il vero collo di bottiglia sia la
  creazione del piano settimanale (non lo scambio) rischierebbe di investire
  tempo/capitale sulla feature sbagliata.

## 3. Reverse prompting

> Capability: `/reverse-prompting` non disponibile in questa demo → fallback
> locale applicato (`fallbacks/reverse-prompting.md`).

Assunzioni implicite individuate e trasformate in domande:

- "Chi paga davvero?" → Il titolare/HR della catena, non il singolo store
  manager: **confermato** in intervista (domanda 9 del founder-interviewer).
- "Il problema è dimostrato o presunto?" → Confermato da 4 interviste
  qualitative (2 retail, 2 ristorazione), non ancora da un pilota quantitativo.
- "Cosa succede se un competitor con più risorse copia la feature di
  conformità normativa?" → Ambiguità aperta: il founder non ha ancora una
  risposta strutturata (registrata in `open-questions.md`).
- "Il prezzo 50-80€/punto vendita/mese è validato o assunto?" → Assunto da un
  solo interlocutore su 4: registrato come `founder_assumption`, non
  `verified_fact`.

## 4. Domande mirate (founder-interviewer)

Sintesi (dettaglio completo in `founder-answers.md`):
- Problema: pianificazione turni manuale, errori di copertura, rischio
  compliance ore di riposo.
- Cliente: store manager (user), titolare/HR (buyer/decision maker),
  dipendenti (beneficiary/influencer).
- Valore: riduzione ore di pianificazione, riduzione rischio sanzioni,
  copertura ottimale.
- Evidenze: 4 interviste qualitative, mockup Figma, nessun pilota quantitativo.
- Capitale: 150-200k pre-seed, orizzonte 12-18 mesi per MVP su 10-15 PV.

## 5. Classificazione startup

- `startup_type: saas` · `development_stage: pre_seed` ·
  `primary_reader: business_angel` · `funding_type: equity` ·
  `time_horizon: 24_months`
- Metriche/leve dominanti: MRR, churn, NRR, CAC, LTV, payback (da
  `methodology/startup-classification.md`).

## 6. Sintesi → concept consolidato

Vedi `startup-concept.md`.

## 7. Gap e ipotesi da validare

- `missing_information`: nessun pilota quantitativo ancora eseguito.
- Assunzioni critiche registrate: `ASS-001` (pricing), `ASS-002` (tempo
  risparmiato/settimana), `ASS-003` (tasso di conversione da demo a cliente
  pagante).
