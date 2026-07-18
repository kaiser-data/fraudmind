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

## Architecture

```
dossier folder ──> ingest.py ──> build/*.json ──> checks.py ──> build/findings.json
   (GDPdU txt,      parse +        linked chains     16 check       two-tier findings
    csv, xlsx,      link by        + entities +      families       with provenance
    docx, pdf)      invoice no.    provenance
                                                        │
                        Cognee Cloud knowledge graph <──┤
                        (entity graph, live Q&A)        ▼
                                            app.py + brain.html
                                            localhost dashboard: findings register,
                                            impact bars, "Ask the brain" (Cognee API)
```

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
- **OpenAI** — planned: auditor-language explanation/translation layer over raw findings
  (structured output; the LLM never decides a number).
