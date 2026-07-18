import { useEffect, useState } from 'react'
import { api } from '../api'
import type { JobStatus } from '../types'

interface AnalyzeStageProps {
  onComplete: () => void
  onBack: () => void
}

const STAGE_LABEL: Record<string, string> = {
  ingest: 'Ingest & chain linking',
  checks: 'Deterministic control tests',
  explain: 'Auditor language (GPT)',
  done: 'Case brain ready',
}

export function AnalyzeStage({ onComplete, onBack }: AnalyzeStageProps) {
  const [status, setStatus] = useState<JobStatus | null>(null)

  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      try {
        const s = await api.status()
        if (cancelled) return
        setStatus(s)
        if (s.done) {
          onComplete()
          return
        }
        if (!s.error) setTimeout(tick, 1000)
      } catch {
        if (!cancelled) setTimeout(tick, 2000)
      }
    }
    tick()
    return () => { cancelled = true }
  }, [onComplete])

  return (
    <div className="stage-narrow">
      <h1 className="display">Building the case brain</h1>
      <p className="lede">
        The engine parses every document, links invoice chains across the
        dossier, and runs its control tests. Findings carry exact
        file-and-row citations.
      </p>
      <section className="panel">
        <ol className="joblog">
          {(status?.log ?? []).map((entry, i) => (
            <li key={i} className={'joblog-' + entry.stage}>
              <span className="mono joblog-time">{entry.at}</span>
              <span className="joblog-stage">
                {STAGE_LABEL[entry.stage] ?? entry.stage}
              </span>
              <span className="joblog-msg">{entry.message}</span>
            </li>
          ))}
        </ol>
        {status?.running && <p className="pulse-line">Working…</p>}
        {status?.error && (
          <>
            <p className="error-line" role="alert">{status.error}</p>
            <button className="btn" onClick={onBack}>Back to dossier</button>
          </>
        )}
      </section>
    </div>
  )
}
