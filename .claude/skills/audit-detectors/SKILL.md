---
name: audit-detectors
description: Build deterministic fraud/misstatement detectors over an audit dossier that generalize to unseen data. Use when writing or tuning checks.py detectors, when a check over-fires (too many findings), or when adapting the pipeline to a new/final dossier. Encodes the anti-overfitting policies learned on the practice dossier.
---

# Audit Detector Engineering

Cognost-style learned skill: baseline + policies distilled from scored evidence
(practice run 2026-07-18). Changes to these policies are proposal-first — record
the before/after finding counts as evidence, then apply.

## Baseline

Write deterministic checks over parsed dossier data. Every finding cites exact
source (`file:rowN` / `file#sheet:rowN` / `file:pageN`). LLM explains; rules decide.

## Learned policies (evidence: 1170 findings -> 18, zero seeded frauds lost)

1. **Calibrate against the dossier's own baseline, never against intuition.**
   "Weekend posting" sounded anomalous; this company posts 28.5% of entries on
   weekends. A pattern is only reportable if it is RARE in this dataset
   (share < 5%). Compute the base rate first, emit it as an INFO finding so the
   calibration is visible and defensible.

2. **Derive thresholds and targets from the dossier's documents, not from the
   practice data.** Materiality (400k), JET de-minimis (25k), approval limit
   (10k), and the control catalog all come from Pruefungsplanung_JET_2025.docx
   and the permissions matrix — documents the final dossier will also contain.
   Never hardcode account numbers, vendor IDs, user IDs, or amounts seen in
   practice data.

3. **Behavioral patterns need a tightness dimension (usually time).**
   "N payments just under the approval limit" over-fired on innocent pairs
   months apart (seeded traps). Real splitting clusters: require the near-limit
   payments within a 7-day window and combined amount above the limit. The
   seeded fraud was 4 same-day partial payments.

4. **Define "new"/"suspicious" by absence of expected evidence, not by ID
   ranges.** "Vendors in 209xxx range" is overfitting. The general rule that
   found the same 8 ghosts: transacts in next period + zero FY footprint (no
   opening balance, no bookings) + no creation record in the change log.

5. **Two-tier output protects against the false-positive penalty.** FLAGGED
   only for deterministic control violations (self-approval, missing log
   entries, contradiction between provided documents). Patterns needing
   judgment (large asset, bank change, sequence gap) stay NEEDS_REVIEW with the
   innocent explanation stated in the finding text.

6. **Aggregate population-level observations into one finding.** 300 invoices
   without goods receipt = one NEEDS_REVIEW item with samples, never 300 items.

7. **Parameterize the input path** (CLI arg > env > default) and rehearse on a
   copied folder — the run on unseen data is the product.

## Known generalization risks (open)

- ~~File names hardcoded in ingest.py~~ RESOLVED 2026-07-18: `_find_file()`
  resolver (exact -> case-insensitive -> digit/separator-stripped match, loud
  error listing the folder on ambiguity). Evidence: practice dossier rerun
  identical (18/18 findings byte-equal); year-shifted rename simulation
  (2025->2026 across all Begleitdokumente) also 18/18 identical titles.
  Provenance cites the RESOLVED filename so citations stay truthful.
- GL column order is unreliable — field access for user/entry-no/time uses
  content regex (`77\d{5}`, `MV-U\d+|Admin`, `HH:MM:SS`), keep it that way.
- VAT factors 1.0/1.19/1.07 for net-vs-gross matching are German rates; fine
  for this track.
