import { useMemo, useState } from 'react'
import { euro } from '../api'
import type { GraphPoint } from '../types'

interface ChartProps {
  points: GraphPoint[]
  relatedIds: Set<string>
  relatedKontos: Set<string>
  showThreshold: boolean
}

const W = 720
const H = 260
const PAD = { top: 16, right: 16, bottom: 28, left: 56 }
const CONTEXT = '#3573BD'
const FLAGGED = '#B42318'

function parseDate(d: string): number {
  const [day, month, year] = d.split('.').map(Number)
  return new Date(year, month - 1, day).getTime()
}

interface PlacedPoint extends GraphPoint {
  x: number
  y: number
  related: boolean
}

interface Placed {
  pts: PlacedPoint[]
  ticks: { y: number; label: string }[]
  months: { x: number; label: string }[]
  yOf?: (amount: number) => number
}

export function Chart(
  { points, relatedIds, relatedKontos, showThreshold }: ChartProps,
) {
  const [hover, setHover] = useState<PlacedPoint | null>(null)

  const placed = useMemo<Placed>(() => {
    const isRelated = (p: GraphPoint) =>
      relatedIds.has(p.id) || (p.konto !== '' && relatedKontos.has(p.konto))
    const kinds = new Set(points.filter(isRelated).map((p) => p.kind))
    const shown = kinds.size > 0
      ? points.filter((p) => kinds.has(p.kind))
      : points
    const usable = shown.filter((p) => p.amount > 0)
    if (usable.length === 0) return { pts: [], ticks: [], months: [] }
    const times = usable.map((p) => parseDate(p.date))
    const tMin = Math.min(...times)
    const tMax = Math.max(...times)
    const logs = usable.map((p) => Math.log10(p.amount))
    const lMin = Math.floor(Math.min(...logs))
    const lMax = Math.ceil(Math.max(...logs))
    const x = (t: number) => PAD.left
      + ((t - tMin) / Math.max(1, tMax - tMin)) * (W - PAD.left - PAD.right)
    const yOf = (amount: number) => H - PAD.bottom
      - ((Math.log10(amount) - lMin) / Math.max(1, lMax - lMin))
      * (H - PAD.top - PAD.bottom)
    const pts: PlacedPoint[] = usable.map((p) => ({
      ...p, x: x(parseDate(p.date)), y: yOf(p.amount), related: isRelated(p),
    }))
    const ticks = []
    for (let l = lMin; l <= lMax; l++) {
      const v = 10 ** l
      const label = v >= 1e6 ? `${v / 1e6} M€`
        : v >= 1e3 ? `${v / 1e3} k€` : `${v} €`
      ticks.push({ y: yOf(v), label })
    }
    const months: { x: number; label: string }[] = []
    const cursor = new Date(tMin)
    cursor.setDate(1)
    while (cursor.getTime() <= tMax) {
      months.push({
        x: x(cursor.getTime()),
        label: cursor.toLocaleDateString('en', { month: 'short' }),
      })
      cursor.setMonth(cursor.getMonth() + 3)
    }
    return { pts, ticks, months, yOf }
  }, [points, relatedIds, relatedKontos])

  if (placed.pts.length === 0) return null
  const related = placed.pts.filter((p) => p.related)
  const thresholdY = showThreshold && placed.yOf ? placed.yOf(10000) : null

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const mx = ((e.clientX - rect.left) / rect.width) * W
    const my = ((e.clientY - rect.top) / rect.height) * H
    let best: PlacedPoint | null = null
    let bestD = 144
    for (const p of placed.pts) {
      const d = (p.x - mx) ** 2 + (p.y - my) ** 2
      if (d < bestD) { bestD = d; best = p }
    }
    setHover(best)
  }

  return (
    <figure className="chart">
      <figcaption className="chart-title">
        Transactions in context — amount over time
      </figcaption>
      <div className="chart-legend">
        <span><i className="dot" style={{ background: FLAGGED }} /> This finding</span>
        <span><i className="dot" style={{ background: CONTEXT }} /> Other transactions</span>
        {showThreshold && <span><i className="dash" /> €10,000 threshold</span>}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Scatter plot of transaction amounts over time with this finding's transactions highlighted"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        {placed.ticks.map((t, i) => (
          <g key={i}>
            <line x1={PAD.left} x2={W - PAD.right} y1={t.y} y2={t.y}
              className="gridline" />
            <text x={PAD.left - 6} y={t.y + 3} className="tick"
              textAnchor="end">{t.label}</text>
          </g>
        ))}
        {placed.months.map((m, i) => (
          <text key={i} x={m.x} y={H - 8} className="tick"
            textAnchor="middle">{m.label}</text>
        ))}
        {thresholdY !== null && (
          <line x1={PAD.left} x2={W - PAD.right} y1={thresholdY}
            y2={thresholdY} className="threshold" />
        )}
        {placed.pts.filter((p) => !p.related).map((p) => (
          <circle key={p.id} cx={p.x} cy={p.y} r={2}
            fill={CONTEXT} opacity={0.22} />
        ))}
        {/* finding dots render LAST so they always sit on top of context */}
        {related.map((p) => (
          <g key={p.id}>
            <circle cx={p.x} cy={p.y} r={9} fill={FLAGGED} opacity={0.18} />
            <circle cx={p.x} cy={p.y} r={5.5}
              fill={FLAGGED} stroke="#fff" strokeWidth={2} />
          </g>
        ))}
        {hover && (
          <circle cx={hover.x} cy={hover.y} r={7} fill="none"
            stroke={hover.related ? FLAGGED : CONTEXT} strokeWidth={1.5} />
        )}
      </svg>
      {hover && (
        <div className="chart-tooltip mono">
          {hover.id} · {hover.party || hover.konto} · {hover.date} ·{' '}
          {euro(hover.amount)}
        </div>
      )}
      {related.length > 0 && (
        <details className="chart-table">
          <summary>View this finding's transactions as a table</summary>
          <table>
            <thead>
              <tr><th>Doc</th><th>Party</th><th>Date</th>
                <th className="num">Amount</th><th>Source</th></tr>
            </thead>
            <tbody>
              {related.map((p) => (
                <tr key={p.id}>
                  <td className="mono">{p.id}</td>
                  <td>{p.party || p.konto}</td>
                  <td className="mono">{p.date}</td>
                  <td className="mono num">{euro(p.amount)}</td>
                  <td className="mono prov-cell">{p.prov}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </figure>
  )
}
