> **Esempio completamente fittizio.** Azienda, persone, interviste, numeri e fonti sono inventati a scopo dimostrativo; ogni riferimento a realtà esistenti è casuale.

# Stage QA — 00 Idea Discovery — TurniDemo

## Decision gate della Sezione 0 — verifica dei 7 criteri

| # | Criterio | Esito |
|---|---|---|
| 1 | Concept comprensibile | ✅ `startup-concept.md` completo |
| 2 | Startup classificata | ✅ `startup-profile.json` valido (saas/pre_seed/business_angel/equity/24_months) |
| 3 | Destinatario identificato | ✅ `business_angel` |
| 4 | Output definiti | ✅ campo 3 del prompt contract |
| 5 | Assunzioni iniziali registrate | ✅ 3 assunzioni critiche in `assumptions-register.json` |
| 6 | Data gap espliciti | ✅ `open-questions.md` aggiornato (pilota quantitativo mancante) |
| 7 | Prompt contract approvato | ✅ `Stato: approved` |

**Esito complessivo:** gate superato — Sezione 0 `approved`.

## Note di qualità

- Il pricing (50-80€/PV/mese) è validato da un solo interlocutore su 4:
  correttamente etichettato `founder_assumption`/`confidence: low`, non
  promosso a fatto.
- Nessuna incoerenza numerica rilevata in questa sessione (nessun
  `INCOERENZA RILEVATA` aperto).
- Gap principale per gli stage successivi: assenza
  di un pilota quantitativo per validare tempo risparmiato e tasso di
  conversione.
