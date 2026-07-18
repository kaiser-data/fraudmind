import { useMemo, useState } from 'react'
import { euro } from '../api'
import type {
  Explanation, Finding, GraphPoint, Verdict, VerdictKind,
} from '../types'
import { Chart } from './Chart'

interface ReviewStageProps {
  findings: Finding[]
  explanations: Record<string, Explanation>
  verdicts: Record<string, Verdict>
  graph: GraphPoint[]
  onVerdict: (id: string, verdict: VerdictKind, note: string) => Promise<void>
  onFinish: () => void
}

const TIER_LABEL: Record<Finding['tier'], string> = {
  FLAGGED: 'Fraud indicator',
  NEEDS_REVIEW: 'Possible fraud',
  INFO: 'Information',
}

const TIER_ORDER: Record<Finding['tier'], number> = {
  FLAGGED: 0, NEEDS_REVIEW: 1, INFO: 2,
}

const VERDICT_ICON: Record<VerdictKind, string> = {
  confirmed: '⛔', followup: '◔', dismissed: '—',
}

const DOC_ID = /\b(?:AR|ER|SG|WA|WE)\d{5,6}\b/g
const KONTO = /\b(?:10|20)\d{4}\b/g

export function ReviewStage({
  findings, explanations, verdicts, graph, onVerdict, onFinish,
}: ReviewStageProps) {
  const ordered = useMemo(() =>
    [...findings].sort((a, b) =>
      TIER_ORDER[a.tier] - TIER_ORDER[b.tier]
      || a.id.localeCompare(b.id)), [findings])

  const [activeId, setActiveId] = useState(ordered[0]?.id ?? '')
  const [note, setNote] = useState('')
  const [lang, setLang] = useState<'en' | 'de'>('en')
  const [saving, setSaving] = useState(false)

  const active = ordered.find((f) => f.id === activeId) ?? ordered[0]
  const exp = active ? explanations[active.id] : undefined
  const reviewed = Object.keys(verdicts).length

  const { relatedIds, relatedKontos } = useMemo(() => {
    if (!active) {
      return {
        relatedIds: new Set<string>(),
        relatedKontos: new Set<string>(),
      }
    }
    const hay = active.title + ' ' + active.explanation + ' '
      + active.provenance.join(' ')
    return {
      relatedIds: new Set(hay.match(DOC_ID) ?? []),
      relatedKontos: new Set(hay.match(KONTO) ?? []),
    }
  }, [active])

  if (!active) return <p className="lede">No findings to review.</p>

  const decide = async (verdict: VerdictKind) => {
    setSaving(true)
    try {
      await onVerdict(active.id, verdict, note)
      setNote('')
      const next = ordered.find(
        (f) => f.id !== active.id && !verdicts[f.id])
      if (next) setActiveId(next.id)
    } finally {
      setSaving(false)
    }
  }

  const explanationText = lang === 'de'
    ? exp?.explanation_de : exp?.explanation_en
  const actionText = lang === 'de'
    ? exp?.recommended_action_de : exp?.recommended_action_en
  const headline = (lang === 'de' ? exp?.headline_de : exp?.headline_en)
    ?? active.title

  return (
    <div className="review">
      <aside className="queue" aria-label="Finding queue">
        <div className="queue-progress">
          <span>{reviewed} of {ordered.length} reviewed</span>
          <div className="bar">
            <div className="bar-fill"
              style={{ width: `${(reviewed / ordered.length) * 100}%` }} />
          </div>
        </div>
        <ul>
          {ordered.map((f) => {
            const v = verdicts[f.id]
            return (
              <li key={f.id}>
                <button
                  className={'queue-item'
                    + (f.id === active.id ? ' queue-active' : '')
                    + (v ? ' queue-reviewed' : '')}
                  onClick={() => setActiveId(f.id)}
                >
                  <span className="mono queue-id">{f.id}</span>
                  <span className={'chip chip-' + f.tier}>
                    {TIER_LABEL[f.tier]}
                  </span>
                  {v && (
                    <span className="queue-verdict" title={v.verdict}>
                      {VERDICT_ICON[v.verdict]}
                    </span>
                  )}
                  <span className="queue-title">{f.title}</span>
                </button>
              </li>
            )
          })}
        </ul>
        <button className="btn btn-primary queue-finish" onClick={onFinish}>
          Finish review → report
        </button>
      </aside>

      <article className="docket" key={active.id}>
        <div className="docket-head">
          <span className="mono docket-id">Case {active.id}</span>
          <span className={'chip chip-' + active.tier}>
            {TIER_LABEL[active.tier]}
          </span>
          <span className="chip chip-sev">{active.severity}</span>
          <span className="docket-confidence">
            <span className="confidence-label">
              Engine confidence {Math.round(active.confidence * 100)}%
            </span>
            <span className="bar bar-small">
              <span className="bar-fill"
                style={{ width: `${active.confidence * 100}%` }} />
            </span>
          </span>
          {active.amount_eur ? (
            <span className="mono docket-amount">
              {euro(active.amount_eur)}
            </span>
          ) : null}
        </div>

        <h1 className="docket-headline">{headline}</h1>

        {exp && (
          <div className="lang-toggle" role="group"
            aria-label="Explanation language">
            <button className={lang === 'en' ? 'on' : ''}
              onClick={() => setLang('en')}>EN</button>
            <button className={lang === 'de' ? 'on' : ''}
              onClick={() => setLang('de')}>DE</button>
            {exp.validated && (
              <span className="chip chip-ok"
                title="Every figure in the AI text was verified against the engine finding">
                figures verified
              </span>
            )}
          </div>
        )}

        {explanationText && <p className="docket-exp">{explanationText}</p>}

        <div className="engine-box">
          <div className="engine-label">Engine finding — verbatim</div>
          <p>{active.explanation}</p>
        </div>

        {actionText && (
          <p className="docket-action">
            <strong>Next audit steps:</strong> {actionText}
          </p>
        )}

        <div className="prov-row">
          {active.provenance.map((p) => (
            <span key={p} className="prov-chip mono">{p}</span>
          ))}
        </div>

        <Chart
          points={graph}
          relatedIds={relatedIds}
          relatedKontos={relatedKontos}
          showThreshold={active.check.includes('split')}
        />

        <div className="verdict-bar">
          <input
            className="verdict-note"
            placeholder="Reviewer note (optional, goes into the report)"
            value={note}
            maxLength={500}
            onChange={(e) => setNote(e.target.value)}
          />
          <button className="btn btn-danger" disabled={saving}
            onClick={() => decide('confirmed')}>
            Confirm fraud
          </button>
          <button className="btn btn-warn" disabled={saving}
            onClick={() => decide('followup')}>
            Follow-up
          </button>
          <button className="btn" disabled={saving}
            onClick={() => decide('dismissed')}>
            Dismiss
          </button>
        </div>
        {verdicts[active.id] && (
          <p className="verdict-existing">
            Recorded: <strong>{verdicts[active.id].verdict}</strong>
            {verdicts[active.id].note && <> — {verdicts[active.id].note}</>}
            {' '}({verdicts[active.id].at}) · deciding again overwrites
          </p>
        )}
      </article>
    </div>
  )
}
