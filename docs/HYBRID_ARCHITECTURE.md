# Hybrid graph architecture — lessons from the final-dossier run

Problem observed 2026-07-18: cognifying raw dossier documents into Cognee Cloud was the
submission bottleneck. Measured on this dossier (times are server-side pipeline times for
upload+cognify of ONE file, sequential):

| Input | Size | Cognify time |
|---|---|---|
| Tiny PDFs/notes (2–6 KB) | | 12–21 s |
| Small CSVs (5–21 KB) | | 14–60 s |
| Stammdaten-Statusliste | 69 KB | 481 s (8 min) |
| OP-Liste Debitoren | 100 KB | 278 s |
| Freigabe-Log Journale | 280 KB | ~38 min |
| Aenderungsprotokoll | 900 KB | ~10 min |
| Warenausgangsliste | 1.7 MB | 30+ min |
| Fakturajournal erweitert | 2.7 MB | not finished at deadline |
| GL (Sachkontobuchungen) | ~250 MB / 1.08M rows | never attempted — impossible |

Total: ~2.5 h wall-clock for 19 companion documents. Meanwhile the deterministic engine
parsed the ENTIRE dossier (incl. the 1.08M-row GL) in ~40 s. The mismatch is structural:
cognify runs every chunk through an extraction LLM, so cost/latency scale with TOKENS —
and raw ledgers are millions of tokens of mostly routine rows.

## What the graph actually earned its keep on (empirical)

The graph's four verified engine-missed leads all came from SMALL, dense inputs:
- a free-text note column in the permissions report (BSP-U16 leaver account),
- 59 master-data change rows (Mahnsperre / renaming clusters),
- the Jan-2026 billing journal (Umsatzbonus credit notes ~€1.74M),
- cross-linking those parties to credit-limit anomalies.

Nothing came from the megabyte-scale table dumps. Conclusion: **LLM graph extraction adds
value on unstructured text and cross-document relationships — not on raw table volume.**

## Recommended hybrid: "deterministic edges, selective cognify"

```
dossier ──► ingest.py (40 s, exists) ──► chains.json / entities.json
                    │
                    ├─► graph.py (NEW, deterministic, <5 s)
                    │     nodes: users, parties, journals, documents, accounts
                    │     edges: created / approved / changed / paid /
                    │            invoiced / no-goods-receipt / over-limit
                    │     store: SQLite or NetworkX pickle, local
                    │
                    ├─► facts.md (engine-distilled: anomalous rows + ALL
                    │     master-data changes + approval-log exceptions +
                    │     note columns; ~100–200 KB)
                    │
                    └─► unstructured docs verbatim (planning docx, contract
                          PDFs, attestations; ~30 KB)

  cognify ONLY facts.md + unstructured docs  →  ~5 min, cents
  chat/query: local-graph neighborhood + Cognee recall → one LLM call composes
```

### Three tiers, by deadline pressure

| Tier | What runs | Time | Cost | Good enough for |
|---|---|---|---|---|
| 1. Engine only | ingest + checks | ~40 s | 0 LLM tokens | submission under deadline |
| 2. + local graph | graph.py, deterministic edges; LLM reads only note columns & question neighborhoods | +10 s build, ~1 call/question | cents | chat, lead generation, SoD path queries |
| 3. + Cognee cognify of the CURATED set | facts.md + unstructured docs | +5 min | ~$0.10–0.50 | cross-validation story, dashboard mindmap, persistent cross-case memory |

Tonight we effectively ran Tier 3 twice: once curated (5 docs, ~130 KB → ~7 min total,
same answer quality) and once raw (19 docs → 2.5 h). The curated run found the same
convergent schemes; the raw run added leads only where small files carried the signal —
files that a better curation rule ("all companion docs < 100 KB verbatim + engine
extracts of big ones + all note/text columns") would have included anyway.

### Why not local cognee OSS?
Viable middle option (data residency for audits, parallel cognify, no queue), but it
still burns LLM tokens on table rows. The deterministic-edges design wins because the
ingest layer ALREADY produces the graph structure — chains.json IS a graph; we just
never queried it as one. LLM extraction is reserved for the only place it beats rules:
free text.

### Concrete next steps (post-hackathon)
1. `graph.py`: emit nodes/edges from chains/entities into SQLite; add `path(a,b)` and
   `neighborhood(entity, depth)` helpers; wire into `/api/chat` context instead of
   (or before) Cognee recall — chat latency drops from ~30 s to ~3 s.
2. Curation rule in ingest: any companion doc < 100 KB → cognify verbatim; larger →
   engine-distilled extract; ALWAYS include note/status text columns (the BSP-U16 lesson).
3. New deterministic checks from tonight's graph catches (leaver accounts, post-year-end
   credit notes, dunning blocks) — once a graph lead is understood, promote it to a rule:
   graph discovers, engine institutionalizes.
4. Cognee Cloud stays for: the visual mindmap (demo value), cross-session/cross-case
   memory, and as the second opinion on the curated set.
