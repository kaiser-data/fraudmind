import { useState } from 'react'
import { api, euro } from '../api'
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

  const confirmed = findings.filter(
    (f) => verdicts[f.id]?.verdict === 'confirmed')
  const followup = findings.filter(
    (f) => verdicts[f.id]?.verdict === 'followup')
  const confirmedSum = confirmed.reduce(
    (sum, f) => sum + (f.amount_eur ?? 0), 0)
  const unreviewed = findings.length - Object.keys(verdicts).length

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
        <button className="btn btn-primary"
          onClick={() => api.downloadReport(findings, verdicts)}>
          Download report (Markdown)
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
    </div>
  )
}
