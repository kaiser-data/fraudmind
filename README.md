# fraudmind

**Deterministic fraud-hunting over audit dossiers — no number without a source.**

Built at the Berlin Summer Lock-In hackathon (cortea fraud-hunt track), 2026-07-18.
fraudmind ingests a German GDPdU audit export (GL, subledgers, fixed assets + accompanying
documents), links every transaction into cross-document chains, runs a catalog of deterministic
fraud/misstatement checks, and serves an interactive "brain" UI backed by a Cognee knowledge
graph. Every finding cites its exact source: `file:row`, `file#sheet:row`, or `file:page`.

## Results on the practice dossier

**18 findings (11 FLAGGED / 6 NEEDS_REVIEW / 1 INFO), ≈ €638k quantified impact:**

| Scheme | Amount |
|---|---|
| Phantom/related-party vendor (self-approved by its own creator, paid in 2 days, zero deliverables) | €295,120 |
| Cut-off manipulation: 8 ghost vendors, Dec services invoiced in Jan, no accrual — triple-corroborated | €192,000 |
| Repairs capitalized as fixed assets (6 additions) | €150,800 |
| Same-day split payments under the €10k approval limit | €39,040 |
| Opening balances unverifiable (empty prior-year TB vs. IT completeness attestation) | — |

Full write-up: [REPORT.md](REPORT.md). Machine-readable: `build/findings.json` after a run.

## Results on the FINAL dossier (Beispiel Dämmstoffe GmbH, 1.08M GL lines)

The same pipeline ran unchanged on the final dossier (`python3 ingest.py <path> && python3 checks.py`) —
all thresholds (materiality €1M, JET de-minimis €50k, lock date 15.01.2026, management user IDs,
designated account 484080) were parsed from the dossier's own audit-planning workpaper, zero
hardcoded identifiers. **54 findings (20 FLAGGED / 33 NEEDS_REVIEW / 1 INFO):**

| Lead finding | Amount |
|---|---|
| Journal GL-596001 posted WITHOUT release by management user BSP-U09, 30.12.2025 22:47 ("GEBUCHT OHNE FREIGABE") | €6,000,000 |
| Four quarter-end journals created AND approved by the same management user BSP-U02 | €4,394,040 |
| Manual GL lines entered AFTER the 15.01.2026 lock date into the closed year | €3,593,881 |
| Rare manual postings on retained-earnings accounts 945000/940000 | ~€55.9M vol. |
| Unapproved bank-details change (ALPEN TECHNIK) + 11 hidden credit-limit breaches | €412,256 |

Cross-validation: the findings, raw evidence rows, approval-log relations, permissions matrix and
planning criteria were pushed to a **Cognee Cloud knowledge graph** (5 documents, dataset
`beispiel_d_mmstoffe_gmbh_2025`); an independent graph query extracts the same top fraud
candidates the deterministic engine flagged — engine decides numbers, graph connects entities.

## Architecture

```
dossier folder ──> ingest.py ──> build/*.json ──> checks.py ──> build/findings.json
   (GDPdU txt,      parse +        linked chains     16 check       two-tier findings
    csv, xlsx,      link by        + entities +      families       with provenance
    docx, pdf)      invoice no.    provenance
                                                        │
                        Cognee Cloud knowledge graph <──┤
                        (entity graph, live Q&A)        ▼
                                     app.py  →  React review console (frontend/)
                                     4 stages: Dossier upload → live Analysis →
                                     Review (auditor decides) → Report (PDF)
```

## Review console (the auditor workflow)

- **Fraud-type headline first**: every case opens with its scheme (e.g. "Master-data
  self-approval (SoD override) — control override · vendor-fraud pattern") and one
  sentence on why the pattern matters; details are progressive-disclosure folds.
- **Decisions on the left**: Confirm fraud / Follow-up / Dismiss + reviewer note,
  directly under the finding queue; every queue item shows confidence, amount,
  and evidence count at a glance.
- **Clickable evidence**: each `file:row` citation opens the actual source record
  in-app with the cited row highlighted in context (`/api/source`).
- **PDF report**: one click produces a formal audit report (scheme headlines,
  methodology, evidence citations, human verdicts) — the submission artifact.
  Plus in-app preview and Markdown export.

*Transparent and traceable by design — the engine decides numbers, AI drafts
language, auditors decide verdicts.*

- **Rules decide, the LLM explains.** Amounts, matches, and violations come from deterministic
  reconciliation — no hallucinated numbers.
- **Two-tier output** (FLAGGED vs NEEDS_REVIEW) protects against false-positive penalties;
  seeded innocent discrepancies stay out of FLAGGED.
- **Anti-overfitting by design**: thresholds (materiality €400k, JET de-minimis €25k, approval
  limit €10k) and control definitions are read from the dossier's own audit-planning workpaper;
  time-based checks self-calibrate against the dossier's base rates (this company posts 28.5% of
  entries on weekends — so weekends are not "odd hours" here); behavioral patterns require
  temporal clustering. The learned policies live in
  [.claude/skills/audit-detectors/SKILL.md](.claude/skills/audit-detectors/SKILL.md).

## Setup

```bash
pip install openpyxl            # xlsx parsing; pdftotext (poppler) optional for PDFs
```

Optional, for the "Ask the brain" panel — a Cognee Cloud account with the dossier ingested:

```bash
# .env  (never committed)
COGNEE_BASE_URL=https://<tenant>.aws.cognee.ai
COGNEE_API_KEY=<key>
```

## Run

```bash
python3 ingest.py "path/to/dossier"     # parse + link -> build/
python3 checks.py "path/to/dossier"     # run checks   -> build/findings.json + console report
python3 app.py                          # brain UI     -> http://127.0.0.1:8600
```

The pipeline runs end-to-end in seconds on a 20k-row GL and is dossier-agnostic: point it at a
new folder (e.g. the final dossier) and it reruns unchanged.

## Check catalog (16 families)

Master-data self-approval & SoD (vs. permissions matrix) · vendor-creation-control bypass ·
cut-off / unrecorded liabilities · repair-capitalization (K3) · journal-approval coverage &
self-approval · JET time-profile (self-calibrating) · round amounts (K6) · split payments with
7-day clustering (K5) · subledger↔GL↔OP-list tie-outs · credit-limit report vs books ·
document-sequence gaps · prior-year completeness contradiction · bank-change payment flows ·
invoices outside the billing journal · material purchases without goods receipt ·
near-duplicate vendors.

## Partner tech

- **Cognee** — knowledge graph over the dossier documents; powers the live "Ask the brain"
  Q&A with graph answers cross-checked against deterministic findings.
- **OpenAI** — auditor-language explanation layer (explain.py, gpt-4.1-mini):
  DE/EN headlines, explanations, and next audit steps per finding; every numeric
  token in the AI text is validated against the engine finding ("figures
  verified" badge) — the LLM never introduces a number.
  (structured output; the LLM never decides a number).
