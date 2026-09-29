> **Esempio completamente fittizio.** Azienda, persone, interviste, numeri e fonti sono inventati a scopo dimostrativo; ogni riferimento a realtà esistenti è casuale.

# Prompt Contract — TurniDemo

**Versione:** 0.1 · **Data:** 2026-07-10 · **Stato:** approved

---

## 1. Obiettivo del progetto
Produrre un business plan per raccogliere un round pre-seed equity da un
business angel, a supporto dello sviluppo di un MVP di workforce scheduling
SaaS per piccole catene retail/ristorazione.

## 2. Destinatario primario
`business_angel`. Nessun destinatario secondario in questa fase (nessuna
componente di debito o bando pubblico prevista).

## 3. Output richiesti
Business plan completo (`output/business-plan.md`), executive summary,
financial model e pitch outline. La Sezione 0 produce concept,
classificazione, registri, prompt contract e handoff; gli altri output
arrivano negli stage successivi.

## 4. Perimetro
Mercato italiano, catene retail e ristorazione da 5 a 50 punti vendita, senza
software di workforce management già in uso. Prodotto: web app + app mobile
per store manager e dipendenti.

## 5. Esclusioni
Fuori perimetro in questa fase: mercati esteri, catene enterprise (>50 PV),
integrazioni con sistemi payroll di terze parti, funzionalità di previsione
della domanda basata su AI.

## 6. Orizzonte temporale
`24_months`, con dettaglio mensile nei primi 12 mesi (fase MVP + pilota) e
trimestrale nei successivi 12.

## 7. Standard metodologico
Vincolante: la metodologia della skill (`methodology/`). Principi: evidenze prima della
narrativa, driver prima delle percentuali, cassa prima dell'utile, milestone
prima del funding.

## 8. Livello di dettaglio
Standard, con rigore massimo richiesto su: market sizing bottom-up e unit
economics (CAC/LTV), dato che sono le due aree più deboli emerse in
intervista (pricing validato da un solo interlocutore su 4).

## 9. Regole sulle fonti
Ogni claim rilevante tracciato in `source-register.json`. Le 4 interviste
qualitative sono `internal_evidence`, non `verified_fact`, finché non
confermate da un pilota quantitativo.

## 10. Regole sulle assunzioni
Un solo `assumptions-register.json`. Il pricing (50-80€/PV/mese) resta
`founder_assumption` con `confidence: low` finché non validato su più
interlocutori o su un pilota reale.

## 11. Strumenti utilizzabili
Runtime-check eseguito: `/step-back-prompting`, `/reverse-prompting`,
`/prompt-contracts` non disponibili in questa demo → fallback locali usati e
dichiarati. Subagent `founder-interviewer` lanciato a runtime.

## 12. Formato degli output
Markdown come fonte primaria versionabile; registri in JSON; prosa estesa solo nella
fase di generazione documentale (Stage 13).

## 13. Criteri di approvazione
Ogni stage è approvato quando il relativo decision gate (vedi workflow
corrispondente) è integralmente soddisfatto e l'utente conferma esplicitamente.

## 14. Condizioni di blocco
Il processo si ferma se: emerge un'incoerenza Critical non risolta, manca un
dato bloccante per lo stage corrente, o una decisione strategica (es. cambio
di beachhead o di modello di pricing) non è stata presa dall'utente.

## 15. Responsabilità dell'utente
Fornire dati/evidenze aggiuntive (in particolare validare il pricing su più
interlocutori), approvare i gate di ciascuno stage, decidere su eventuali
incoerenze rilevate.

## 16. Responsabilità dell'orchestratore
Governare il processo stage-based, mantenere aggiornati i registri
(assunzioni, evidenze, fonti, rischi, decisioni), rilevare e segnalare
incoerenze senza correggerle in silenzio, non inventare dati mancanti.

---

**Approvazione:** Founder TurniDemo · **Data:** 2026-07-10
