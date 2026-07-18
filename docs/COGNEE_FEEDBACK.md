# Cognee Cloud — field feedback & improvement suggestions

From a day of production-pressure use at the Berlin Summer Lock-In hackathon
(fraud-hunt track): 3 datasets, ~25 documents cognified, dozens of GRAPH_COMPLETION
recalls, plus daily use of the Claude Code memory plugin. Written as constructive
feedback — the graph genuinely earned its keep (it found four verified fraud leads our
deterministic engine missed), which is exactly why the friction points below matter.

## A. Cloud ingestion (the deadline killer)

Measured cognify times (single files, sequential, `/api/v1/remember`):

| File size | Time |
|---|---|
| 2–20 KB | 12–60 s |
| 69 KB | 8 min |
| 100 KB | 4.6 min |
| 280 KB | ~38 min |
| 900 KB | ~10 min (variance is high) |
| >1 MB | gateway timeout ("upstream request timeout") — never completed |

1. **Async ingestion API.** `/remember` blocks until cognify finishes; the HTTP gateway
   times out long before large files complete, so work is lost even though billing
   tokens were spent. Return a `pipeline_run_id` immediately + a status endpoint
   (`GET /pipeline_runs/{id}`) + optional webhook. This single change would have saved
   our submission evening.
2. **Chunk-level progress & resume.** A 280 KB file that dies at minute 30 restarts
   from zero. Persist chunk state so re-uploading the same content hash resumes.
3. **Table-aware ingestion mode.** CSV rows are semi-structured; running each chunk
   through full LLM entity extraction is why cost scales so badly. A `mode=tabular`
   that maps columns→properties deterministically (LLM only for free-text columns)
   would cut ingest time ~10x for exactly the files enterprises have.
4. **Size guidance & preflight.** Reject or warn on files that will exceed gateway
   limits BEFORE spending tokens; document the practical ceiling (we found it
   empirically at ~1 MB).
5. **Batch endpoint.** Uploading 19 documents = 19 sequential blocking calls. Accept a
   zip or a manifest of files and pipeline them server-side.

## B. Query & retrieval

6. **Dataset isolation for blind evaluation.** Recall answers occasionally drew on
   content from a *different* dataset of the same tenant (our engine-findings dataset
   leaked into "blind" queries against the raw-documents dataset). If `datasets:[X]`
   is passed, retrieval must be strictly scoped to X — for audit/eval use cases this
   is correctness, not preference.
7. **Provenance in recall responses.** GRAPH_COMPLETION returns fluent text but no
   machine-readable citations (document id, chunk, source row). We had to re-verify
   every claim manually against raw files. Returning `sources:[{document, chunk,
   text_span}]` per answer would make outputs audit-grade.
8. **Deterministic/repeatable recall option.** Two identical queries can produce
   contradictory judgments (one of ours called the same journal both "properly
   released" and a "release breach"). A `temperature=0`-style flag plus returning the
   retrieved subgraph itself would let clients do their own reasoning.
9. **Raw subgraph export.** `GET /datasets/{id}/graph?entity=X&depth=2` returning
   nodes/edges as JSON. We wanted to run our own path queries (user→journal→approval)
   and could only do it through natural-language completion.

## C. Claude Code plugin (cognee-memory)

10. **Hook latency vs. Claude Code timeout.** The `UserPromptSubmit` hook
    (`session-context-lookup.py`) regularly exceeds the plugin's shipped 15 s timeout —
    we had to hand-edit hooks.json to 60 s (diff: `"timeout": 15` → `"timeout": 60`).
    Either ship a higher default, or better: make the lookup fast enough for 15 s
    (local cache of the last N recalls, async prefetch on session start, skip the
    lookup when the prompt is < ~10 tokens like "go"/"proceed").
11. **Graceful degradation.** When the cloud is slow/unreachable the hook should fail
    open instantly (empty context) instead of stalling prompt submission — memory
    lookup is an enhancement, never a blocker.
12. **Noise filtering on auto-saved turns.** The plugin stores every prompt/answer,
    including "go", "proceed" and interrupted turns; recall then surfaces five copies
    of the same summary (visible in our session context). Deduplicate by content hash
    and skip sub-threshold prompts.
13. **Session→graph promotion controls.** An explicit "promote this session's facts to
    the permanent graph" step (or a TTL on session memory) would keep the long-term
    graph curated instead of accumulating every working turn.

## D. Product / dashboard

14. **Cognify cost preview** ("this upload ≈ N tokens ≈ €X, ~Y minutes") before
    committing — after the fact we could infer it only from wall-clock time.
15. **Mindmap improvements for demos**: filter by document, highlight a node's
    neighborhood, export as PNG/SVG. The graph visual was our best demo asset; we
    couldn't isolate the fraud cluster on stage.
16. **Per-dataset delete/rename in the console.** Iterating on ingestion strategies
    (curated vs. raw) creates junk datasets that currently linger.

## What worked well (keep it)

- `/remember` with multipart file upload + auto-cognify is a genuinely simple mental
  model; zero-schema onboarding is the product's superpower.
- GRAPH_COMPLETION answer quality on small, dense, entity-rich documents was
  excellent — it independently reproduced our engine's six lead fraud schemes and
  found four real leads we had missed (720 locked-posting reversals, post-year-end
  credit notes, a never-deactivated leaver account, unauthorized dunning blocks).
- Cross-document entity linking (user ↔ journal ↔ approval ↔ permission ↔ party) is
  exactly the capability rules engines lack; that's the reason we'd keep Cognee in the
  architecture despite everything in section A.

*Context for all measurements: docs/HYBRID_ARCHITECTURE.md (cost/latency post-mortem)
and docs/ENGINE_VS_GRAPH.md (method comparison) in this repo.*
