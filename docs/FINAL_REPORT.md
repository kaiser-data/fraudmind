# fraudmind — Overall Final Report (Beispiel Dämmstoffe GmbH FY2025)

Date: 2026-07-18 late session. Sources: deterministic engine (54 findings, the engine output (findings.json)),
Cognee Cloud knowledge graphs (`beispiel_d_mmstoffe_gmbh_2025` curated, 6 docs;
`bsp_dossier_raw_2025` raw, 20 docs), auditor verdicts (10 reviewed, 6 confirmed),
and file-level re-verification of every claim referenced below.

## 1. The fraud narrative (all methods combined, chronological)

1. **Oct–Nov 2025 — master-data groundwork.** BSP-U08 (Debitorenbuchhalter, no
   master-data right per permissions report) sets Mahnsperre=Ja for 4 debtors and later
   changes ALPEN TECHNIK's bank details (17.11., approval invalid → engine F003).
   BSP-U11 renames 5 debtors incl. SÜD PANEELE KG. [Stammdatenaenderungen ✔]
2. **Dec 2025 — approval-control breakdown.** GL-912249 (€74,960) and GL-996802
   (€48,827) posted "GEBUCHT OHNE FREIGABE" by BSP-U10 (08.–09.12.). Quarter-end
   pattern completes 29.12.: BSP-U02 creates AND approves four ~€1.1M journals
   (GL-560001/565001/320001/955001, €4.39M total). [Freigabe-Log ✔ · engine F006–F009]
3. **30.12.2025 22:47 — the €6,000,000 event.** BSP-U09 (management function) posts
   GL-596001 without any release, status literally "GEBUCHT OHNE FREIGABE" — 6×
   materiality, night-time, year-end window (K1+K3+K6+K7). [Freigabe-Log row 3117 ✔ · engine F001]
4. **05.01.2026 — mass reversal of locked year-end revenue.** BSP-U10 executes
   **720 Generalstorno reversals of FESTGESCHRIEBENE 31.12.2025 postings on revenue
   accounts (440020-…)** in one day. NEW — graph-discovered, source-verified; engine's
   change-log check had deliberately exempted stornos as the "legitimate" correction path.
   The volume and timing make this the single biggest open question of the case.
   [Aenderungsprotokoll: 720 rows dated 05.01.2026, all BSP-U10, all 31.12.2025 ✔]
5. **05.–07.01.2026 — revenue pull-back at specific customers.** "Gutschrift
   Umsatzbonus 2025" credit notes: ALPEN TECHNIK −€650,715; HANSEPROFILE −€543,641
   and −€544,018 (~€1.74M) — same parties that show credit-limit anomalies; ALPEN
   TECHNIK is also the bank-change target from step 1. NEW — graph-discovered,
   source-verified. [Fakturajournal_Januar_2026 + Buchungen_Folgeperiode ✔]
6. **After 15.01.2026 lock date.** €3.59M of manual GL lines entered into the closed
   year by BSP-U02/BSP-U10. [engine F004, GL capture timestamps ✔]
7. **Standing weakness.** BSP-U16 left the company 31.10.2025; account never
   deactivated ("Konto nicht deaktiviert" — verbatim note in the permissions report).
   NEW — graph-discovered, source-verified. [Berechtigungsauswertung ✔]

**Quantified, defensible exposure** (engine-computed, no double counting):
confirmed by human review **€13,987,881.24** (6 verdicts); additional review-tier
items pending. Large "exposure" figures the graph produced (€478M) are SELECTION
VOLUMES of management-user journal lines, not misstatement estimates — do not quote
them as impact.

## 2. Method comparison — what each layer contributed

| | Engine (deterministic) | Knowledge graph (Cognee) |
|---|---|---|
| Coverage | full population incl. 1.08M-row GL | 20 companion docs (2 largest failed at gateway) |
| Speed | ~40 s | ~3 h cumulative cognify |
| Output | 54 findings, cited, replayable | independently reproduced the 6 lead schemes blind |
| Unique catches | lock-date breach, rare accounts, tie-outs, time profile | **720-storno event, Umsatzbonus credits (€1.74M), BSP-U16 leaver account, Mahnsperre cluster** — all verified real |
| Failure modes | only finds what a family encodes | 1 internal contradiction; later answers contaminated across datasets (final query echoed engine findings, so only the EARLY queries were truly blind); volume-as-impact framing |

Verdict: the two-method design worked exactly as intended — engine for numbers,
graph for unanticipated relationships — and each caught things the other missed.

## 3. Cognee Cloud operational lessons (why it hurt at the deadline)

- Cognify latency scales with tokens: 280KB file ≈ 38 min; >1MB files died at the
  gateway (upstream timeout). The GL was never feasible.
- Value came from SMALL dense inputs (note columns, change logs, approval exceptions),
  not raw table volume.
- Full analysis and the three-tier hybrid design (engine-only → local deterministic
  graph → selective cognify of a curated fact set, ~5 min instead of hours):
  see docs/HYBRID_ARCHITECTURE.md.

## 4. Auditor next steps (priority order)

1. The 720 locked-posting Generalstornos by BSP-U10 on 05.01.2026: business
   justification, approval, and net P&L effect of storno+rebooking pairs.
2. GL-596001 €6M: underlying documentation, counter-account, who instructed it.
3. Umsatzbonus credit notes vs. FY2025 revenue recognition for ALPEN TECHNIK /
   HANSEPROFILE (and their credit-limit status).
4. Four BSP-U02 self-approved quarter-end journals: substance testing.
5. Post-lock entries (€3.59M) and the BSP-U16 account (disable + activity review).

## 5. Engine roadmap distilled from graph catches (general rules, no identifiers)

1. Post-period mass-storno check: N reversals of locked prior-period postings by one
   user within a short window → FLAGGED (threshold from dossier base rates).
2. Post-year-end credit-note check: next-period credit notes ≥ JET threshold reversing
   prior-year revenue for parties with year-end anomalies.
3. Leaver-account check: active user with departed-status note in the permissions report.
4. Dunning-block (Mahnsperre) enabled near year-end for parties with open balances.
