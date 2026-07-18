# Engine vs. Cognee Knowledge Graph — result comparison (final dossier)

Two independent methods over the same dossier (Beispiel Dämmstoffe GmbH FY2025):

- **Deterministic engine** (`checks.py`, 22 families): 54 findings, every figure cited to file:row.
- **Cognee Cloud raw-document graph** (`bsp_dossier_raw_2025`, 19 companion documents
  cognified — approval log, master-data changes, permissions, credit limits, legal cases,
  billing journals, OP lists, balance lists, planning workpaper, bill-and-hold, IT attestation).
  Queried blind with three forensic questions; graph had NO access to engine findings.

Every graph claim below was re-verified against raw source files before classification.

## 1. Convergent findings (both methods, independently)

| Finding | Engine | Graph | Verified in source |
|---|---|---|---|
| GL-596001 €6,000,000 posted "GEBUCHT OHNE FREIGABE" by BSP-U09, 30.12.2025 22:47 | F001 (top FLAGGED) | Rank #1, both runs | Freigabe-Log row 3117 ✔ |
| Four ~€1.1M quarter-end self-approvals by BSP-U02 (GL-560001/565001/955001/320001) | F006–F009 | Ranks #2–5 | Freigabe-Log rows 3113–3116 ✔ |
| GL-531863 / GL-912249 / GL-996802 posted without release (BSP-U10/U11) | F012, F013, F020 | Listed | Freigabe-Log ✔ |
| ALPEN TECHNIK bank-details change without valid approval | F003 (CRITICAL) | "most dangerous master-data manipulation" | Stammdatenaenderungen row 51 ✔ |
| HANSEPROFILE credit-limit breach (utilization ≫ limit) | F010 (aggregated, 11 customers) | Rank #2 with amounts | Kreditlimitliste ✔ |
| Bill-and-hold / period-shift revenue pattern | F022 (bill-and-hold agreement) | Flagged via Jan-2026 invoice batch | Bill-and-Hold PDF + Fakturajournal ✔ |

**6 of the engine's top FLAGGED schemes were independently reproduced by the graph** —
same journals, same users, same amounts, without seeing findings.json.

## 2. Graph-only leads the engine MISSED (verified real)

| New lead | Source evidence | Why the engine missed it |
|---|---|---|
| **BSP-U16: employee left 31.10.2025, account never deactivated** — note field literally says "Mitarbeiter/in zum 31.10.2025 ausgeschieden - Konto nicht deaktiviert" | Berechtigungsauswertung_2025.xlsx, user row BSP-U16 ✔ | No check family reads free-text notes in the permissions report (leaver/JML control) |
| **Year-end revenue reversal via "Gutschrift Umsatzbonus 2025"**: ALPEN TECHNIK −€650,715 (SCN0004203, 05.01.2026); HANSEPROFILE −€543,641 + −€544,018 (SCN0004225/54, 07.01.2026) — ~€1.74M of FY2025 revenue credited right after year-end, to the same parties that show credit-limit anomalies | Fakturajournal_Januar_2026.csv + Buchungen_Folgeperiode_2026.csv ✔ | Cut-off check only tested next-period INVOICES with 2025 service dates for parties without 2025 bookings; large post-year-end CREDIT NOTES to active customers fell outside the rule |
| **BSP-U08 (Debitorenbuchhalter) set Mahnsperre=Ja for 4 debtors Oct 2025** (ATLASBAUBEDARF, BOREASZIEGEL, BEISPIEL COM S.R.L., GRANIT SPEDITION) — dunning switched off ahead of year-end | Stammdatenaenderungen rows (10.–22.10.2025) ✔ | Change log was parsed but no check treats "dunning block enabled" as a receivables-concealment vector |
| **Cluster of Name/Firmierung changes by BSP-U08/BSP-U11** (9 debtors incl. SÜD PANEELE KG) | Stammdatenaenderungen ✔ | Field-level risk (renaming can mask counterparties) not in any family |

These four are exactly what a graph is for: cross-document relationship patterns
(user ↔ permission note ↔ action ↔ counterparty) that rule families didn't anticipate.

## 3. Engine-only findings the graph did not surface

- €3.59M manual lines entered AFTER the 15.01.2026 lock date (needs the 1.08M-row GL —
  too large to cognify; the graph never saw Sachkontobuchungen.txt).
- Rare-account postings (945000/940000 retained earnings, ~€55.9M) — same reason.
- Tie-outs, sequence gaps, base-rate time profiling — quantitative sweeps over full
  populations are engine territory.

## 4. Accuracy check (graph hallucination test)

Spot-checked every specific graph claim (journal IDs, amounts, users, dates, parties)
against raw files: **all verified** — including the ones that initially looked fabricated
(the SCN credit notes; a grep encoding issue, not a graph error). One internal
inconsistency: GL-527262 was called "properly released" in one answer and a "release
breach" in another (the log shows it approved by BSP-U10 — the first answer is right).
Verdict: strong recall on relationship facts, one contradiction across answers — which is
why graph output stays a LEAD generator and the engine stays the system of record.

## 5. Division of labor (the architecture, confirmed empirically)

| Capability | Engine | Graph |
|---|---|---|
| Full-population sweeps (1.08M rows), thresholds, quantification | ✅ | ❌ (can't ingest GL scale) |
| Deterministic, replayable, cited findings | ✅ | ⚠️ needs re-verification |
| Cross-document relationship reasoning, unanticipated patterns | ❌ (only coded families) | ✅ (found 4 real new leads) |
| Natural-language Q&A for the reviewer | ❌ | ✅ (powers the case chat) |

**Bottom line:** engine 54 findings / graph independently confirms the 6 lead schemes
AND contributes 4 verified new leads (≈€1.74M revenue-reversal cluster + a JML control
failure). Together: a stronger case than either method alone.

## Follow-up candidates for the check catalog (general, not case-specific)

1. Leaver/JML check: flag active accounts whose permissions-report note/status marks the
   user as departed.
2. Post-year-end credit-note check: next-period credit notes above the JET threshold that
   reverse prior-year revenue for parties with year-end balance anomalies.
3. Dunning-block check: Mahnsperre enabled near year-end for parties with open balances.
