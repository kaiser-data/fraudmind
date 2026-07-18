import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import type {
  Explanation, Finding, GraphPoint, Verdict, VerdictKind,
} from './types'
import { UploadStage } from './stages/UploadStage'
import { AnalyzeStage } from './stages/AnalyzeStage'
import { ReviewStage } from './stages/ReviewStage'
import { ReportStage } from './stages/ReportStage'
import { ChatDock } from './ChatDock'

type Stage = 'upload' | 'analyze' | 'review' | 'report'

const STEPS: { key: Stage; label: string }[] = [
  { key: 'upload', label: 'Dossier' },
  { key: 'analyze', label: 'Analysis' },
  { key: 'review', label: 'Review' },
  { key: 'report', label: 'Report' },
]

export default function App() {
  const [stage, setStage] = useState<Stage>('upload')
  const [findings, setFindings] = useState<Finding[]>([])
  const [explanations, setExplanations] =
    useState<Record<string, Explanation>>({})
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>({})
  const [graph, setGraph] = useState<GraphPoint[]>([])
  const [hasExistingCase, setHasExistingCase] = useState(false)

  useEffect(() => {
    api.findings()
      .then((f) => setHasExistingCase(f.length > 0))
      .catch(() => setHasExistingCase(false))
  }, [])

  const loadCase = useCallback(async () => {
    const [f, e, v, g] = await Promise.all([
      api.findings(), api.explanations(), api.verdicts(), api.graph(),
    ])
    setFindings(f)
    setExplanations(e)
    setVerdicts(v)
    setGraph(g)
    setStage('review')
  }, [])

  const saveVerdict = useCallback(
    async (id: string, verdict: VerdictKind, note: string) => {
      const updated = await api.saveVerdict(id, verdict, note)
      setVerdicts(updated)
    }, [])

  const stepIndex = STEPS.findIndex((s) => s.key === stage)

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">fm</span>
          <span className="brand-name">fraudmind</span>
          <span className="brand-sub">Fraud Review Console</span>
        </div>
        <nav className="stepper" aria-label="Workflow stage">
          {STEPS.map((s, i) => (
            <button
              key={s.key}
              className={'step' + (i === stepIndex ? ' step-active' : '')
                + (i < stepIndex ? ' step-done' : '')}
              disabled={
                (s.key === 'review' || s.key === 'report')
                  ? findings.length === 0
                  : s.key === 'analyze'}
              onClick={() => setStage(s.key)}
            >
              <span className="step-num">{i + 1}</span> {s.label}
            </button>
          ))}
        </nav>
        <div className="assurance">
          Engine decides numbers · AI writes language · You decide verdicts
        </div>
      </header>

      <main className="content">
        {stage === 'upload' && (
          <UploadStage
            hasExistingCase={hasExistingCase}
            onAnalysisStarted={() => setStage('analyze')}
            onResume={loadCase}
          />
        )}
        {stage === 'analyze' && (
          <AnalyzeStage
            onComplete={loadCase}
            onBack={() => setStage('upload')}
          />
        )}
        {stage === 'review' && (
          <ReviewStage
            findings={findings}
            explanations={explanations}
            verdicts={verdicts}
            graph={graph}
            onVerdict={saveVerdict}
            onFinish={() => setStage('report')}
          />
        )}
        {stage === 'report' && (
          <ReportStage
            findings={findings}
            verdicts={verdicts}
            onBackToReview={() => setStage('review')}
          />
        )}
      </main>
      {findings.length > 0 && <ChatDock />}
    </div>
  )
}
