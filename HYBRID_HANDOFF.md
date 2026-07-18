# HANDOFF — Hybrid "medium graph" + engine (next session)

Goal: implement Tier 2 of docs/HYBRID_ARCHITECTURE.md — a LOCAL deterministic graph
built from the engine's own artifacts, queried alongside the engine, with Cognee Cloud
demoted to a small optional curated layer (Tier 3). Motivation (measured 2026-07-18):
cloud cognify cost hours and real money, >1MB files never landed, and the dashboard
graph would not render at ~20 docs — while every genuine graph win came from small,
dense relationship data the engine ALREADY parses.

## Context you can rely on (verified this session)

- Pipeline: `ingest.py <dossier>` → build/{chains,entities,anomalies,xlsx_docs,
  pdf_docs}.json + planning_text.txt → `checks.py` → build/findings.json (54 findings
  on the final dossier; regression baseline = build_practice_baseline/ for practice).
- chains.json IS already a graph: doc-no → {faktura, goods[], subledger[], gl[]
  (with user/account/amount/date), payments_2026[], approval}.
- entities.json holds vendors/customers/users/master_data_changes/approvals/
  credit_limits/change_log/status_list/legal_cases + doc_prefixes.
- The four proven graph-only catches (use as acceptance tests, they are REAL in the
  final dossier): (1) 720 Generalstorno reversals of locked 31.12.2025 postings by
  BSP-U10 on 05.01.2026 [Aenderungsprotokoll]; (2) "Gutschrift Umsatzbonus 2025"
  credit notes −650,715 / −543,641 / −544,018 EUR to 800291 + 800645, 05.–07.01.2026
  [Fakturajournal_Januar_2026 + Buchungen_Folgeperiode_2026]; (3) BSP-U16 leaver note
  "Konto nicht deaktiviert" [Berechtigungsauswertung, free-text col]; (4) Mahnsperre=Ja
  set by BSP-U08 for 4 debtors Oct 2025 [Stammdatenaenderungen].
  NOTE: do NOT hardcode these IDs in checks — they are validation targets, the rules
  must find them via invariants (audit-detectors skill policy).

## Build plan

### 1. graph.py (new, stdlib + sqlite3, no deps)
- Input: build/*.json (run after ingest; `python3 graph.py`, no args needed).
- Nodes: user, party (vendor/customer), journal/document, account, dataset docs.
- Edges (typed, with prov + date + amount where known):
  created(user→journal), approved(user→journal), posted_without_release(journal),
  changed(user→party, field), invoiced(party→doc), paid(doc→party),
  no_goods_receipt(doc), over_limit(party), storno(user→doc, locked: bool),
  note(user|party → free text from status/permission note columns).
- Store: build/graph.sqlite  (nodes(id,kind,label,attrs), edges(src,dst,kind,attrs)).
- Helpers (importable + CLI):
  `neighborhood(entity_id, depth=2)` → dict; `path(a, b, max_len=4)`;
  `suspicious_motifs()` → the generic motif queries below.
- Motif queries (deterministic, general — these institutionalize the graph catches):
  a) same user creates+approves journal above JET threshold;
  b) N>base-rate storno edges on locked docs by one user within K days;
  c) next-period credit notes ≥ threshold to parties with over_limit or note edges;
  d) user with departed/inactive note but active edges after the note date;
  e) master-data change by user lacking the matching permission attr.
- Wire motifs (b)–(e) into checks.py as CHECK 23–26 (proposal-first: record
  before/after counts in .claude/skills/audit-detectors/SKILL.md, run the
  generalization gate from GT_CALIBRATION_HANDOFF.md).

### 2. Chat integration (app.py)
- In `chat_answer()`: BEFORE Cognee recall, extract entity tokens from the question
  (doc-no / user / party regexes from ingest), pull `neighborhood()` for each from
  graph.sqlite, inject as "## Local graph context". Keep Cognee recall as optional
  enrichment (skip silently if env not set). Target: grounded answers in ~3 s
  without cloud, zero tokens for retrieval.

### 3. Tier-3 curated Cognee push (optional, budget-capped)
- New `cognee_push.py`: builds ONE curated markdown (≤150 KB): engine findings brief +
  all note/status text columns + master-data changes + approval exceptions +
  unstructured docs text. Push to ONE dataset. Refuse if estimated size > 200 KB
  (spend guard — we burned real money on raw uploads; graph view also dies on large
  datasets, so small keeps the mindmap demo alive).

### 4. Frontend (optional polish)
- ChatDock: show a "local graph" badge vs "cloud" per answer (engine field already
  returned by /api/chat).
- Later: mini graph view of the current finding's neighborhood (SVG, no lib) fed by
  a new GET /api/graph/neighborhood?id=.

## Acceptance
1. `ruff check` clean; practice dossier rerun → 18 findings byte-identical
   (regression gate) BEFORE adding checks 23–26; after adding them, previously-correct
   findings unchanged, new checks documented in the skill file.
2. Final dossier rerun: checks 23–26 must surface catches (1),(2),(4) and the BSP-U16
   leaver (3) via invariants — compare against docs/FINAL_REPORT.md.
3. Chat: "Which journals were posted without release?" answers correctly with Cognee
   env vars REMOVED (local-graph only), in seconds.

## Environment gotchas (learned the hard way)
- FastAPI is broken on this machine — app.py stays stdlib-only.
- Dossier files are latin-1; always `encoding="latin-1"` (a grep once "proved" real
  data fabricated because of this).
- GateGuard hooks block first Bash/Write per session — retry the identical call.
- GDPdU column order is unreliable — derive fields by content pattern, never index.
- `graphify update .` after code changes (project rule, cheap).
- Server start: `DOSSIER_PATH="$PWD/dataset/final/Daten BSP" python3 app.py` (:8600);
  kill the old one first.
