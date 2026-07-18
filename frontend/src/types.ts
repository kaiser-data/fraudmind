export interface Finding {
  id: string
  check: string
  tier: 'FLAGGED' | 'NEEDS_REVIEW' | 'INFO'
  severity: string
  confidence: number
  title: string
  explanation: string
  amount_eur?: number | null
  provenance: string[]
}

export interface Explanation {
  headline_de?: string
  headline_en?: string
  explanation_de?: string
  explanation_en?: string
  recommended_action_de?: string
  recommended_action_en?: string
  model?: string
  validated?: boolean
}

export type VerdictKind = 'confirmed' | 'followup' | 'dismissed'

export interface Verdict {
  verdict: VerdictKind
  note: string
  at: string
}

export interface GraphPoint {
  id: string
  kind: string
  date: string
  amount: number
  party: string
  konto: string
  prov: string
}

export interface JobLogEntry {
  stage: string
  message: string
  at: string
}

export interface JobStatus {
  running: boolean
  stage: string
  log: JobLogEntry[]
  error: string | null
  done: boolean
}

export interface BrainUpdateResult {
  nodes: number
  cognee_pushed: boolean
}
