# Prompt Contract — <PROJECT_NAME>

> Contratto operativo tra utente e orchestratore. Deve essere **approvato**
> prima di creare le sezioni `01_…`–`12_…` del progetto (decision gate della
> Sezione 0, [`reference/architecture.md`](../reference/architecture.md) §8.6).
> I 16 campi seguenti sono obbligatori
> ([`reference/architecture.md`](../reference/architecture.md) §8.5).

**Versione:** 0.1 · **Data:** <YYYY-MM-DD> · **Stato:** draft | approved

---

## 1. Obiettivo del progetto
<Cosa deve produrre questo business plan e per quale decisione serve.>

## 2. Destinatario primario
<founder_internal | business_angel | venture_capital | corporate_partner | bank |
public_grant | incubator | mixed> — più eventuali destinatari secondari.

## 3. Output richiesti
<Es. business-plan.md, executive-summary.md, financial-model.xlsx, pitch outline,
data-room index. Segna quali sono in scope per la fase corrente.>

## 4. Perimetro
<Cosa è incluso: mercati, geografie, segmenti, linee di prodotto, orizzonte.>

## 5. Esclusioni
<Cosa è esplicitamente fuori perimetro, per evitare scope creep.>

## 6. Orizzonte temporale
<12_months | 24_months | 36_months | 5_years | custom> e granularità (mensile il
primo anno, poi trimestrale/annuale).

## 7. Standard metodologico
Vincolanti: i principi non negoziabili della skill (`reference/architecture.md`
§3) e i moduli di `methodology/`. Principi: evidenze prima della narrativa,
driver prima delle percentuali, cassa prima dell'utile, milestone prima del funding.

## 8. Livello di dettaglio
<Sintetico / standard / due-diligence-ready. Indica dove serve rigore massimo
(es. financial plan, market sizing).>

## 9. Regole sulle fonti
Ogni claim rilevante è tracciato in `source-register.json`. Fonti ufficiali > report
di settore > stime interne. Le stime vanno etichettate.

## 10. Regole sulle assunzioni
Un solo `assumptions-register.json`. Nessuna assunzione trasformata in fatto in
silenzio (classi in `evidence-framework.md`). Ogni numero ha un driver. Se
l'utente propone di sostituire un valore gia' persistito, si applica il
protocollo `checks/persistence-conflict-protocol.json`: `INCOERENZA RILEVATA`,
nessuna scrittura nel turno di proposta, conferma esplicita in un turno
successivo, storico del valore precedente e decision log solo dopo conferma.

## 11. Strumenti utilizzabili
<Web research, subagent verticali, /step-back-prompting, /reverse-prompting,
/prompt-contracts, grant-strategia, /goal (nativo). Segna cosa è disponibile dopo
il runtime-check → vedi `capability_map` in project-config.json.>

## 12. Formato degli output
Markdown come fonte primaria versionabile; dati strutturati in JSON/YAML/CSV;
prosa solo nella fase documentale.

## 13. Criteri di approvazione
<Quando una sezione è "approvata": criteri per stage, chi approva, cosa serve.>

## 14. Condizioni di blocco
<Cosa ferma il processo: incoerenza Critical, dato mancante bloccante, decisione
strategica non presa, funding non riconciliato. Include sempre lo stato
`CONFLICT_DETECTED_AWAITING_CONFIRMATION`: finche' la conferma esplicita non
arriva in un turno successivo, il valore nuovo non viene scritto ne'
propagato.>

## 15. Responsabilità dell'utente
<Fornire dati/evidenze, prendere decisioni manageriali, approvare i gate,
validare le assunzioni critiche.>

## 16. Responsabilità dell'orchestratore
<Governare il processo, mantenere i registri, rilevare incoerenze, non inventare
dati, non correggere in silenzio, chiedere conferma sui cambi critici.>

---

**Approvazione:** _____________________  **Data:** ____________
