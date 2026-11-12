import { useEffect, useMemo, useState } from 'react'
import { api } from './api.js'
import { fmtTime, shortSha } from './util.js'

const LANE_W = 18
const ROW_H = 34
const COLORS = ['#4f8ef7', '#e0609e', '#3fb27f', '#e8a13c', '#8a6ff0', '#39b8c8', '#d9634f', '#7aa328']

/** 车道分配：按时间倒序，每个提交占一条车道，父提交继承/新开车道。 */
function layout(commits) {
  const lanes = []
  const pos = new Map()
  commits.forEach((c, row) => {
    let lane = lanes.indexOf(c.sha)
    if (lane === -1) {
      lane = lanes.indexOf(null)
      if (lane === -1) { lanes.push(null); lane = lanes.length - 1 }
    }
    lanes[lane] = null
    pos.set(c.sha, { row, lane })
    c.parents.forEach((p, i) => {
      if (lanes.includes(p)) return
      if (i === 0) {
        lanes[lane] = p
      } else {
        let free = lanes.indexOf(null)
        if (free === -1) { lanes.push(null); free = lanes.length - 1 }
        lanes[free] = p
      }
    })
  })
  return { pos, laneCount: Math.max(lanes.length, 1) }
}

const x = (lane) => lane * LANE_W + LANE_W / 2 + 4
const y = (row) => row * ROW_H + ROW_H / 2

export default function CommitGraph({ repoId, batchId, onSelect, selected }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    setData(null)
    api.commits(repoId, batchId).then(setData).catch((e) => setError(e.message))
  }, [repoId, batchId])

  const graph = useMemo(() => (data ? layout(data.commits) : null), [data])

  if (error) return <p className="error-banner">{error}</p>
  if (!data) return <p className="muted">加载中…</p>
  if (data.commits.length === 0) return <p className="muted">该批次没有提交。</p>

  const { pos, laneCount } = graph
  const graphW = laneCount * LANE_W + 8
  const height = data.commits.length * ROW_H

  const edges = []
  data.commits.forEach((c) => {
    const from = pos.get(c.sha)
    c.parents.forEach((p) => {
      const to = pos.get(p)
      if (!to) return
      edges.push({ from, to, key: `${c.sha}-${p}` })
    })
  })

  return (
    <div className="commit-graph">
      <div className="graph-rows" style={{ height }}>
        <svg className="graph-svg" width={graphW} height={height}>
          {edges.map((e) => {
            const x1 = x(e.from.lane), y1 = y(e.from.row)
            const x2 = x(e.to.lane), y2 = y(e.to.row)
            const color = COLORS[e.to.lane % COLORS.length]
            return (
              <path
                key={e.key}
                d={`M ${x1} ${y1} C ${x1} ${y1 + ROW_H}, ${x2} ${y2 - ROW_H}, ${x2} ${y2}`}
                stroke={color}
                fill="none"
                strokeWidth="1.6"
              />
            )
          })}
          {data.commits.map((c) => {
            const p = pos.get(c.sha)
            const color = COLORS[p.lane % COLORS.length]
            return (
              <circle
                key={c.sha}
                cx={x(p.lane)}
                cy={y(p.row)}
                r={c.parents.length > 1 ? 6 : 4.5}
                fill={c.parents.length > 1 ? color : '#fff'}
                stroke={color}
                strokeWidth="2"
              />
            )
          })}
        </svg>
        <div className="graph-list" style={{ marginLeft: graphW }}>
          {data.commits.map((c, i) => (
            <div
              key={c.sha}
              className={`commit-row ${selected === c.sha ? 'selected' : ''}`}
              style={{ top: i * ROW_H, height: ROW_H }}
              onClick={() => onSelect(c.sha)}
            >
              <span className="mono sha">{shortSha(c.sha)}</span>
              <span className="msg" title={c.message}>{c.message.split('\n')[0]}</span>
              {c.tip_of.map((b) => <span key={b} className="branch-tip">{b}</span>)}
              {c.parents.length > 1 && <span className="badge st-merge">合并</span>}
              <span className="muted author">{c.author_name}</span>
              <span className="muted time">{fmtTime(c.author_time, c.author_tz)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
