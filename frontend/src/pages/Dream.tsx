import { useState, useRef, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  streamDream,
  listDreams,
  getDream,
  deleteDream,
  type DreamEvent,
  type DreamMeta,
} from '../lib/api'
import MarkdownViewer from '../components/MarkdownViewer'

interface ToolEntry {
  id: string
  name: string
  input: Record<string, any>
  ok?: boolean
  preview?: string
  error?: string
}

const containerStyle: React.CSSProperties = {
  display: 'flex',
  gap: '1.25rem',
  height: 'calc(100vh - 140px)',
}

const sidebarStyle: React.CSSProperties = {
  width: 260,
  background: '#111118',
  borderRadius: 8,
  border: '1px solid #222',
  padding: '0.75rem',
  overflowY: 'auto',
  flexShrink: 0,
}

const mainColStyle: React.CSSProperties = {
  flex: 1,
  display: 'flex',
  flexDirection: 'column',
  minWidth: 0,
  gap: '1rem',
}

const cardStyle: React.CSSProperties = {
  background: '#161622',
  borderRadius: 8,
  padding: '1.25rem',
  border: '1px solid #222',
}

const eventsStyle: React.CSSProperties = {
  flex: 1,
  background: '#0d0d14',
  border: '1px solid #222',
  borderRadius: 8,
  padding: '1rem',
  overflowY: 'auto',
  fontFamily: 'monospace',
  fontSize: '0.78rem',
}

const toolNameColors: Record<string, string> = {
  list_files: '#7b9cff',
  read_file: '#a78bfa',
  bash: '#fbbf24',
  write_file: '#4ade80',
  delete_file: '#f87171',
  list_chats: '#22d3ee',
  read_chat: '#22d3ee',
  dream_done: '#fb923c',
}

function ToolCard({ tool }: { tool: ToolEntry }) {
  const [open, setOpen] = useState(false)
  const color = toolNameColors[tool.name] || '#888'

  let summary = ''
  if (tool.name === 'list_files') summary = `path=${tool.input.path || '(root)'}`
  else if (tool.name === 'read_file') summary = tool.input.path || ''
  else if (tool.name === 'bash') summary = tool.input.command || ''
  else if (tool.name === 'write_file') summary = `${tool.input.path} (${(tool.input.content || '').length} chars)`
  else if (tool.name === 'delete_file') summary = tool.input.path || ''
  else if (tool.name === 'read_chat') summary = `thread=${tool.input.thread_id || ''}`
  else if (tool.name === 'dream_done') summary = '(end)'
  else summary = JSON.stringify(tool.input)

  const status = tool.ok === undefined ? '...' : tool.ok ? 'ok' : 'error'

  return (
    <div style={{
      background: '#0a0a10',
      border: '1px solid #2a2a3e',
      borderRadius: 4,
      padding: '0.4rem 0.6rem',
      marginBottom: '0.4rem',
    }}>
      <div
        onClick={() => setOpen(!open)}
        style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
      >
        <span style={{ color: '#555' }}>{open ? '▾' : '▸'}</span>
        <span style={{ color, fontWeight: 600 }}>{tool.name}</span>
        <span style={{ color: '#888', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {summary}
        </span>
        <span style={{
          color: status === 'ok' ? '#4ade80' : status === 'error' ? '#f87171' : '#888',
          fontSize: '0.7rem',
        }}>{status}</span>
      </div>
      {open && (tool.preview || tool.error || tool.input.content) && (
        <pre style={{
          marginTop: '0.4rem',
          padding: '0.4rem',
          background: '#06060a',
          borderRadius: 3,
          color: tool.ok === false ? '#f87171' : '#aaa',
          fontSize: '0.7rem',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          maxHeight: 240,
          overflow: 'auto',
        }}>
          {tool.error || tool.preview || (tool.input.content || '').slice(0, 1500)}
        </pre>
      )}
    </div>
  )
}

export default function Dream() {
  const qc = useQueryClient()
  const [maxOps, setMaxOps] = useState(10)
  const [maxWrites, setMaxWrites] = useState(5)
  const [running, setRunning] = useState(false)
  const [tools, setTools] = useState<ToolEntry[]>([])
  const [budget, setBudget] = useState<{ ops: [number, number]; writes: [number, number] }>({ ops: [0, 0], writes: [0, 0] })
  const [summary, setSummary] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [streamingText, setStreamingText] = useState('')
  const [selectedDreamId, setSelectedDreamId] = useState<string | null>(null)
  const eventsRef = useRef<HTMLDivElement>(null)

  const { data: dreamList } = useQuery({
    queryKey: ['dreams'],
    queryFn: listDreams,
    refetchInterval: 5000,
  })

  const { data: selectedDream } = useQuery({
    queryKey: ['dream', selectedDreamId],
    queryFn: () => getDream(selectedDreamId!),
    enabled: !!selectedDreamId && !running,
  })

  useEffect(() => {
    eventsRef.current?.scrollTo({ top: eventsRef.current.scrollHeight, behavior: 'smooth' })
  }, [tools, streamingText])

  const start = async () => {
    if (running) return
    setRunning(true)
    setTools([])
    setSummary(null)
    setError(null)
    setStreamingText('')
    setSelectedDreamId(null)
    setBudget({ ops: [0, maxOps], writes: [0, maxWrites] })

    let acc = ''
    try {
      for await (const ev of streamDream(maxOps, maxWrites)) {
        if (ev.type === 'dream_start') {
          setSelectedDreamId(ev.dream_id)
        } else if (ev.type === 'budget') {
          setBudget({
            ops: [ev.ops_used, ev.ops_total],
            writes: [ev.writes_used, ev.writes_total],
          })
        } else if (ev.type === 'tool_call') {
          setTools(prev => [...prev, { id: ev.id, name: ev.name, input: ev.input }])
        } else if (ev.type === 'tool_result') {
          setTools(prev =>
            prev.map(t => t.id === ev.id ? { ...t, ok: ev.ok, preview: ev.preview, error: ev.error } : t)
          )
        } else if (ev.type === 'delta') {
          acc += ev.text
          setStreamingText(acc)
        } else if (ev.type === 'dream_done') {
          setSummary(ev.summary)
        } else if (ev.type === 'error') {
          setError(ev.message)
        }
      }
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setRunning(false)
      qc.invalidateQueries({ queryKey: ['dreams'] })
      qc.invalidateQueries({ queryKey: ['wiki-index'] })
    }
  }

  const loadDream = (id: string) => {
    if (running) return
    setSelectedDreamId(id)
    setTools([])
    setSummary(null)
    setError(null)
    setStreamingText('')
    setBudget({ ops: [0, 0], writes: [0, 0] })
  }

  const removeDream = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('Delete this dream?')) return
    await deleteDream(id)
    qc.invalidateQueries({ queryKey: ['dreams'] })
    if (id === selectedDreamId) setSelectedDreamId(null)
  }

  // When viewing a past dream (not currently running), reconstruct tools/summary from stored events
  useEffect(() => {
    if (!selectedDream || running) return
    const replayedTools: ToolEntry[] = []
    let replayedSummary: string | null = selectedDream.report || null
    for (const e of selectedDream.events || []) {
      if (e.type === 'tool_call') {
        replayedTools.push({ id: e.id, name: e.name, input: e.input || {} })
      } else if (e.type === 'tool_result') {
        const idx = replayedTools.findIndex(t => t.id === e.id)
        if (idx >= 0) {
          replayedTools[idx] = { ...replayedTools[idx], ok: e.ok, preview: e.preview, error: e.error }
        }
      } else if (e.type === 'dream_done' && !replayedSummary) {
        replayedSummary = e.summary
      }
    }
    setTools(replayedTools)
    setSummary(replayedSummary)
    setBudget({
      ops: [selectedDream.meta.ops_used, selectedDream.meta.max_ops],
      writes: [selectedDream.meta.writes_used, selectedDream.meta.max_writes],
    })
  }, [selectedDream, running])

  const dreams: DreamMeta[] = dreamList?.dreams || []

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <div>
          <h1 style={{ fontWeight: 600 }}>Dream</h1>
          <div style={{ color: '#888', fontSize: '0.85rem', marginTop: '0.25rem' }}>
            Periodic wiki health-check. Finds contradictions, orphans, gaps, and consolidates.
          </div>
        </div>
      </div>

      <div style={containerStyle}>
        {/* Sidebar — past dreams */}
        <div style={sidebarStyle}>
          <div style={{
            fontSize: '0.7rem',
            color: '#888',
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            marginBottom: '0.6rem',
          }}>
            Past dreams ({dreams.length})
          </div>
          {dreams.length === 0 && (
            <div style={{ color: '#555', fontSize: '0.8rem' }}>No dreams yet.</div>
          )}
          {dreams.map(d => {
            const isActive = d.id === selectedDreamId
            const statusColor =
              d.status === 'complete' ? '#4ade80' :
              d.status === 'running' ? '#fbbf24' :
              d.status === 'error' ? '#f87171' :
              '#888'
            return (
              <div
                key={d.id}
                onClick={() => loadDream(d.id)}
                style={{
                  padding: '0.5rem 0.6rem',
                  borderRadius: 4,
                  cursor: running ? 'not-allowed' : 'pointer',
                  background: isActive ? '#1a1a2e' : 'transparent',
                  marginBottom: '0.25rem',
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '0.4rem',
                  opacity: running ? 0.5 : 1,
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    <span style={{
                      width: 6, height: 6, borderRadius: '50%',
                      background: statusColor, display: 'inline-block',
                    }} />
                    <span style={{
                      color: isActive ? '#fff' : '#ccc',
                      fontSize: '0.82rem',
                      fontWeight: isActive ? 500 : 400,
                    }}>
                      {new Date(d.started_at).toLocaleString()}
                    </span>
                  </div>
                  <div style={{ color: '#666', fontSize: '0.7rem', marginTop: '0.15rem' }}>
                    {d.ops_used}/{d.max_ops} ops · {d.writes_used}/{d.max_writes} writes
                  </div>
                </div>
                <button
                  onClick={(e) => removeDream(d.id, e)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: '#555',
                    cursor: 'pointer',
                    fontSize: '0.85rem',
                    padding: '0 0.2rem',
                  }}
                  title="Delete dream"
                >×</button>
              </div>
            )
          })}
        </div>

        {/* Main column */}
        <div style={mainColStyle}>
          {/* Controls */}
          <div style={cardStyle}>
            <div style={{ display: 'flex', gap: '2rem', alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <div>
                <label style={{ color: '#888', fontSize: '0.75rem', display: 'block', marginBottom: '0.3rem' }}>
                  Max operations: <span style={{ color: '#fff' }}>{maxOps}</span>
                </label>
                <input
                  type="range"
                  min={1}
                  max={50}
                  value={maxOps}
                  onChange={e => setMaxOps(parseInt(e.target.value))}
                  disabled={running}
                  style={{ width: 200 }}
                />
              </div>
              <div>
                <label style={{ color: '#888', fontSize: '0.75rem', display: 'block', marginBottom: '0.3rem' }}>
                  Max writes: <span style={{ color: '#fff' }}>{maxWrites}</span>
                </label>
                <input
                  type="range"
                  min={0}
                  max={30}
                  value={maxWrites}
                  onChange={e => setMaxWrites(parseInt(e.target.value))}
                  disabled={running}
                  style={{ width: 200 }}
                />
              </div>
              <button
                onClick={start}
                disabled={running}
                style={{
                  background: '#fb923c',
                  border: 'none',
                  color: '#000',
                  padding: '0.6rem 1.5rem',
                  borderRadius: 8,
                  cursor: running ? 'not-allowed' : 'pointer',
                  fontWeight: 600,
                  fontSize: '0.9rem',
                  opacity: running ? 0.5 : 1,
                }}
              >
                {running ? 'Dreaming...' : '✨ Start dreaming'}
              </button>
            </div>

            {/* Budget bars */}
            {(running || budget.ops[1] > 0) && (
              <div style={{ marginTop: '1rem', display: 'flex', gap: '2rem' }}>
                <BudgetBar label="Operations" used={budget.ops[0]} total={budget.ops[1]} color="#7b9cff" />
                <BudgetBar label="Writes" used={budget.writes[0]} total={budget.writes[1]} color="#4ade80" />
              </div>
            )}
          </div>

          {/* Events */}
          <div style={eventsStyle} ref={eventsRef}>
            {tools.length === 0 && !streamingText && !summary && !error && (
              <div style={{ color: '#555' }}>
                {running ? 'Dream starting...' : 'Click "Start dreaming" or select a past dream from the sidebar.'}
              </div>
            )}

            {tools.map(t => <ToolCard key={t.id} tool={t} />)}

            {streamingText && (
              <div style={{
                marginTop: '0.5rem',
                padding: '0.5rem',
                color: '#aaa',
                fontStyle: 'italic',
                fontSize: '0.8rem',
                whiteSpace: 'pre-wrap',
              }}>
                {streamingText}
                {running && ' ▋'}
              </div>
            )}

            {error && (
              <div style={{
                marginTop: '0.75rem',
                padding: '0.5rem 0.75rem',
                background: '#3a1a1a',
                border: '1px solid #f87171',
                borderRadius: 4,
                color: '#f87171',
              }}>
                {error}
              </div>
            )}

            {summary && (
              <div style={{
                marginTop: '0.75rem',
                padding: '1rem 1.25rem',
                background: '#0f1f0f',
                border: '1px solid #4ade80',
                borderRadius: 6,
                fontFamily: '-apple-system, sans-serif',
                fontSize: '0.9rem',
              }}>
                <div style={{
                  fontSize: '0.7rem',
                  color: '#4ade80',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  marginBottom: '0.5rem',
                }}>
                  Dream summary
                </div>
                <MarkdownViewer content={summary} />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function BudgetBar({ label, used, total, color }: { label: string; used: number; total: number; color: string }) {
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0
  return (
    <div style={{ flex: 1 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: '#888', marginBottom: '0.25rem' }}>
        <span>{label}</span>
        <span>{used} / {total}</span>
      </div>
      <div style={{
        background: '#0a0a10',
        height: 6,
        borderRadius: 3,
        overflow: 'hidden',
      }}>
        <div style={{
          background: color,
          height: '100%',
          width: `${pct}%`,
          transition: 'width 0.3s',
        }} />
      </div>
    </div>
  )
}
