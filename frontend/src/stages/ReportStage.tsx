import { useState } from 'react'
import { api, euro } from '../api'
import { schemeFor } from '../schemes'
import type { BrainUpdateResult, Finding, Verdict } from '../types'

interface ReportStageProps {
  findings: Finding[]
  verdicts: Record<string, Verdict>
  onBackToReview: () => void
}

const VERDICT_TEXT: Record<string, string> = {
  confirmed: 'Confirmed fraud',
  followup: 'Follow-up',
  dismissed: 'Dismissed',
}

export function ReportStage(
  { findings, verdicts, onBackToReview }: ReportStageProps,
) {
  const [brainResult, setBrainResult] = useState<BrainUpdateResult | null>(null)
  const [brainBusy, setBrainBusy] = useState(false)
  const [brainError, setBrainError] = useState<string | null>(null)
  const [preview, setPreview] = useState(false)

  const confirmed = findings.filter(
    (f) => verdicts[f.id]?.verdict === 'confirmed')
  const followup = findings.filter(
    (f) => verdicts[f.id]?.verdict === 'followup')
  const confirmedSum = confirmed.reduce(
    (sum, f) => sum + (f.amount_eur ?? 0), 0)
  const unreviewed = findings.length - Object.keys(verdicts).length
  const today = new Date().toISOString().slice(0, 10)

  const updateBrain = async () => {
    setBrainBusy(true)
    setBrainError(null)
    try {
      setBrainResult(await api.brainUpdate())
    } catch (err: unknown) {
      setBrainError(
        err instanceof Error ? err.message : 'Brain update failed')
    } finally {
      setBrainBusy(false)
    }
  }

  return (
    <div className="stage-wide">
      <h1 className="display">Verification report</h1>
      <p className="lede">
        Engine findings with your recorded verdicts. Figures come from the
        deterministic engine and cite source documents; verdicts are yours.
      </p>

      <div className="tiles">
        <div className="tile">
          <span className="tile-num mono">{findings.length}</span>
          <span className="tile-label">Engine findings</span>
        </div>
        <div className="tile">
          <span className="tile-num mono">
            {Object.keys(verdicts).length}
          </span>
          <span className="tile-label">Reviewed</span>
        </div>
        <div className="tile tile-danger">
          <span className="tile-num mono">{confirmed.length}</span>
          <span className="tile-label">Confirmed fraud</span>
        </div>
        <div className="tile tile-danger">
          <span className="tile-num mono">{euro(confirmedSum)}</span>
          <span className="tile-label">Confirmed impact</span>
        </div>
        <div className="tile">
          <span className="tile-num mono">{followup.length}</span>
          <span className="tile-label">Follow-up</span>
        </div>
      </div>

      {unreviewed > 0 && (
        <p className="warn-line">
          {unreviewed} finding{unreviewed > 1 ? 's' : ''} not yet reviewed —
          they appear in the report as “not yet reviewed”.{' '}
          <button className="link" onClick={onBackToReview}>
            Back to review
          </button>
        </p>
      )}

      <section className="panel">
        <table className="report-table">
          <thead>
            <tr>
              <th>Finding</th><th>Tier</th>
              <th className="num">Amount</th><th>Verdict</th><th>Note</th>
            </tr>
          </thead>
          <tbody>
            {findings.map((f) => {
              const v = verdicts[f.id]
              return (
                <tr key={f.id}>
                  <td>
                    <span className="mono">{f.id}</span> {f.title}
                  </td>
                  <td>{f.tier}</td>
                  <td className="mono num">{euro(f.amount_eur)}</td>
                  <td className={v ? 'verdict-' + v.verdict : ''}>
                    {v ? VERDICT_TEXT[v.verdict] : 'Not reviewed'}
                  </td>
                  <td>{v?.note ?? ''}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>

      <div className="report-actions">
        <button className="btn btn-primary" onClick={() => window.print()}>
          Download PDF report
        </button>
        <button className="btn" onClick={() => setPreview(!preview)}>
          {preview ? 'Hide report preview' : 'Preview report in app'}
        </button>
        <button className="btn"
          onClick={() => api.downloadReport(findings, verdicts)}>
          Download Markdown
        </button>
        <button className="btn" onClick={updateBrain} disabled={brainBusy}>
          {brainBusy ? 'Updating…' : 'Write fraud nodes to case brain'}
        </button>
      </div>
      {brainResult && (
        <p className="ok-line">
          {brainResult.nodes} fraud node{brainResult.nodes === 1 ? '' : 's'}
          {' '}written to the case brain
          {brainResult.cognee_pushed
            ? ' and pushed to the knowledge graph.'
            : ' (stored locally; knowledge-graph push unavailable).'}
        </p>
      )}
      {brainError && <p className="error-line" role="alert">{brainError}</p>}

      <p className="trust-foot">
        Deterministic engine · every figure cited to document and row ·
        AI drafts language only · human verdicts recorded with timestamp.
      </p>

      {/* Formal report — print target for "Download PDF report";
          on-screen when preview is toggled */}
      <div className={'print-report' + (preview ? ' print-preview' : '')}
        aria-hidden={!preview}>
        <h1>fraudmind — Fraud &amp; Misstatement Findings Report</h1>
        <p className="pr-meta">
          Date: {today} · Engine findings: {findings.length} ·
          Reviewed: {Object.keys(verdicts).length} ·
          Confirmed fraud: {confirmed.length} ·
          Confirmed impact: {euro(confirmedSum)}
        </p>
        <p className="pr-method">
          Methodology: deterministic rule engine over the complete GDPdU
          dossier (ledgers, subledgers, master data, accompanying documents).
          Every finding cites its source records (file : row). Language
          model used for wording only, never for detection; all figures
          validated against engine output. Verdicts recorded by a human
          reviewer.
        </p>

        {findings.map((f) => {
          const v = verdicts[f.id]
          const scheme = schemeFor(f.check)
          return (
            <section key={f.id} className="pr-finding">
              <h2>
                {f.id} — {scheme.label}
              </h2>
              <p className="pr-line pr-title">{f.title}</p>
              <p className="pr-line">
                {scheme.kind} · Tier: {f.tier} · Severity: {f.severity}
                {f.amount_eur ? <> · Amount: {euro(f.amount_eur)}</> : null}
              </p>
              <p className="pr-line">
                Reviewer verdict:{' '}
                <strong>
                  {v ? VERDICT_TEXT[v.verdict] : 'Not yet reviewed'}
                </strong>
                {v?.note ? <> — {v.note}</> : null}
              </p>
              <p className="pr-exp">{f.explanation}</p>
              <p className="pr-evidence">
                Evidence: {f.provenance.join(' · ')}
              </p>
            </section>
          )
        })}

        <p className="pr-foot">
          Generated by fraudmind — deterministic fraud-hunting over GDPdU
          audit dossiers. AI supports, auditors decide.
        </p>
      </div>
    </div>
  )
}
