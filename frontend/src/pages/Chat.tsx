import { useState, useRef, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  streamChat,
  listChatThreads,
  getChatThread,
  deleteChatThread,
  type ChatMsg,
  type ChatThreadMeta,
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

interface AssistantTurn {
  role: 'assistant'
  text: string
  tools: ToolEntry[]
}

type Turn = { role: 'user'; text: string } | AssistantTurn

const containerStyle: React.CSSProperties = {
  display: 'flex',
  gap: '1.25rem',
  height: 'calc(100vh - 140px)',
}

const sidebarStyle: React.CSSProperties = {
  width: 240,
  background: '#111118',
  borderRadius: 8,
  border: '1px solid #222',
  padding: '0.75rem',
  overflowY: 'auto',
  flexShrink: 0,
}

const chatColumnStyle: React.CSSProperties = {
  flex: 1,
  display: 'flex',
  flexDirection: 'column',
  minWidth: 0,
}

const messagesStyle: React.CSSProperties = {
  flex: 1,
  overflowY: 'auto',
  paddingRight: '0.5rem',
  marginBottom: '1rem',
}

const inputRowStyle: React.CSSProperties = {
  display: 'flex',
  gap: '0.5rem',
  borderTop: '1px solid #222',
  paddingTop: '1rem',
}

const userBubbleStyle: React.CSSProperties = {
  background: '#1a1a2e',
  borderRadius: 12,
  padding: '0.75rem 1.1rem',
  marginBottom: '1rem',
  marginLeft: '4rem',
  color: '#e0e0e0',
  border: '1px solid #2a2a3e',
}

const assistantBubbleStyle: React.CSSProperties = {
  background: '#111118',
  borderRadius: 12,
  padding: '1rem 1.25rem',
  marginBottom: '1rem',
  marginRight: '4rem',
  border: '1px solid #222',
}

const labelStyle: React.CSSProperties = {
  fontSize: '0.7rem',
  color: '#888',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
  marginBottom: '0.4rem',
}

const toolCardStyle: React.CSSProperties = {
  background: '#0d0d14',
  border: '1px solid #2a2a3e',
  borderRadius: 6,
  padding: '0.5rem 0.75rem',
  marginBottom: '0.5rem',
  fontSize: '0.78rem',
  fontFamily: 'monospace',
}

const toolNameColors: Record<string, string> = {
  list_files: '#7b9cff',
  read_file: '#a78bfa',
  bash: '#fbbf24',
}

function ToolCard({ tool }: { tool: ToolEntry }) {
  const [open, setOpen] = useState(false)
  const color = toolNameColors[tool.name] || '#888'

  let summary = ''
  if (tool.name === 'list_files') summary = `path=${tool.input.path || '(root)'}`
  else if (tool.name === 'read_file') summary = tool.input.path || ''
  else if (tool.name === 'bash') summary = tool.input.command || ''
  else summary = JSON.stringify(tool.input)

  const status =
    tool.ok === undefined ? '...' :
    tool.ok ? 'ok' :
    'error'

  return (
    <div style={toolCardStyle}>
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
        }}>
          {status}
        </span>
      </div>
      {open && (tool.preview || tool.error) && (
        <pre style={{
          marginTop: '0.5rem',
          padding: '0.5rem',
          background: '#06060a',
          borderRadius: 4,
          color: tool.ok ? '#aaa' : '#f87171',
          fontSize: '0.72rem',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          maxHeight: 300,
          overflow: 'auto',
        }}>
          {tool.error || tool.preview}
        </pre>
      )}
    </div>
  )
}

function eventsToTurns(events: any[]): Turn[] {
  // Reconstruct user/assistant turns from the persisted event log so the
  // user can revisit a past conversation in full.
  const turns: Turn[] = []
  let pendingTools: ToolEntry[] = []

  for (const e of events) {
    if (e.type === 'user') {
      turns.push({ role: 'user', text: e.text || '' })
    } else if (e.type === 'tool_call') {
      pendingTools.push({ id: e.id, name: e.name, input: e.input || {} })
    } else if (e.type === 'tool_result') {
      pendingTools = pendingTools.map(t =>
        t.id === e.id ? { ...t, ok: e.ok, preview: e.preview, error: e.error } : t
      )
    } else if (e.type === 'assistant') {
      turns.push({ role: 'assistant', text: e.text || '', tools: pendingTools })
      pendingTools = []
    }
  }
  return turns
}

export default function Chat() {
  const qc = useQueryClient()
  const [history, setHistory] = useState<Turn[]>([])
  const [threadId, setThreadId] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [pending, setPending] = useState<AssistantTurn | null>(null)
  const [error, setError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  const { data: threadList } = useQuery({
    queryKey: ['chat-threads'],
    queryFn: listChatThreads,
    refetchInterval: 5000,
  })

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history, pending])

  const send = async () => {
    const trimmed = input.trim()
    if (!trimmed || streaming) return

    setError(null)
    const nextHistory: Turn[] = [...history, { role: 'user', text: trimmed }]
    setHistory(nextHistory)
    setInput('')
    setStreaming(true)

    const apiMessages: ChatMsg[] = nextHistory.map(t => ({
      role: t.role,
      content: t.role === 'user' ? t.text : (t as AssistantTurn).text,
    }))

    let acc: AssistantTurn = { role: 'assistant', text: '', tools: [] }
    setPending(acc)

    try {
      for await (const ev of streamChat(apiMessages, threadId)) {
        if (ev.type === 'thread') {
          setThreadId(ev.thread_id)
        } else if (ev.type === 'delta') {
          acc = { ...acc, text: acc.text + ev.text }
          setPending(acc)
        } else if (ev.type === 'tool_call') {
          acc = {
            ...acc,
            tools: [...acc.tools, { id: ev.id, name: ev.name, input: ev.input }],
          }
          setPending(acc)
        } else if (ev.type === 'tool_result') {
          acc = {
            ...acc,
            tools: acc.tools.map(t =>
              t.id === ev.id
                ? { ...t, ok: ev.ok, preview: ev.preview, error: ev.error }
                : t
            ),
          }
          setPending(acc)
        } else if (ev.type === 'error') {
          setError(ev.message)
        }
      }
      setHistory([...nextHistory, acc])
    } catch (e: any) {
      const msg = e?.message || String(e)
      setError(msg)
      setHistory([
        ...nextHistory,
        { role: 'assistant', text: acc.text || `_Error: ${msg}_`, tools: acc.tools },
      ])
    } finally {
      setStreaming(false)
      setPending(null)
      qc.invalidateQueries({ queryKey: ['chat-threads'] })
    }
  }

  const newConversation = () => {
    if (streaming) return
    setHistory([])
    setThreadId(null)
    setPending(null)
    setError(null)
  }

  const loadThread = async (id: string) => {
    if (streaming) return
    try {
      const { events } = await getChatThread(id)
      setHistory(eventsToTurns(events))
      setThreadId(id)
      setPending(null)
      setError(null)
    } catch (e: any) {
      setError(e?.message || String(e))
    }
  }

  const removeThread = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('Delete this conversation?')) return
    await deleteChatThread(id)
    qc.invalidateQueries({ queryKey: ['chat-threads'] })
    if (id === threadId) newConversation()
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const renderAssistant = (turn: AssistantTurn, isPending: boolean) => (
    <div style={assistantBubbleStyle}>
      <div style={labelStyle}>Director</div>
      {turn.tools.length > 0 && (
        <div style={{ marginBottom: turn.text ? '0.75rem' : 0 }}>
          {turn.tools.map(t => <ToolCard key={t.id} tool={t} />)}
        </div>
      )}
      {turn.text ? (
        <MarkdownViewer content={turn.text + (isPending ? ' ▋' : '')} />
      ) : isPending && turn.tools.length === 0 ? (
        <div style={{ color: '#666' }}>Thinking...</div>
      ) : null}
    </div>
  )

  const threads: ChatThreadMeta[] = threadList?.threads || []

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h1 style={{ fontWeight: 600 }}>Chat</h1>
        <button
          onClick={newConversation}
          disabled={streaming}
          style={{
            background: '#7b9cff',
            border: 'none',
            color: '#000',
            padding: '0.4rem 0.9rem',
            borderRadius: 4,
            cursor: streaming ? 'not-allowed' : 'pointer',
            fontSize: '0.8rem',
            fontWeight: 600,
          }}
        >
          + New conversation
        </button>
      </div>

      <div style={containerStyle}>
        {/* Sidebar: thread list */}
        <div style={sidebarStyle}>
          <div style={{
            fontSize: '0.7rem',
            color: '#888',
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            marginBottom: '0.6rem',
          }}>
            Conversations ({threads.length})
          </div>
          {threads.length === 0 && (
            <div style={{ color: '#555', fontSize: '0.8rem' }}>No saved conversations yet.</div>
          )}
          {threads.map(t => {
            const isActive = t.id === threadId
            return (
              <div
                key={t.id}
                onClick={() => loadThread(t.id)}
                style={{
                  padding: '0.5rem 0.6rem',
                  borderRadius: 4,
                  cursor: 'pointer',
                  background: isActive ? '#1a1a2e' : 'transparent',
                  marginBottom: '0.25rem',
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '0.4rem',
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    color: isActive ? '#fff' : '#ccc',
                    fontSize: '0.82rem',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    fontWeight: isActive ? 500 : 400,
                  }}>
                    {t.title}
                  </div>
                  <div style={{ color: '#666', fontSize: '0.7rem', marginTop: '0.15rem' }}>
                    {t.turn_count} turn{t.turn_count !== 1 ? 's' : ''} · {new Date(t.updated_at).toLocaleDateString()}
                  </div>
                </div>
                <button
                  onClick={(e) => removeThread(t.id, e)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: '#555',
                    cursor: 'pointer',
                    fontSize: '0.85rem',
                    padding: '0 0.2rem',
                  }}
                  title="Delete conversation"
                >
                  ×
                </button>
              </div>
            )
          })}
        </div>

        {/* Chat column */}
        <div style={chatColumnStyle}>
          <div style={messagesStyle}>
            {history.length === 0 && !pending && (
              <div style={{ color: '#666', textAlign: 'center', marginTop: '4rem' }}>
                Ask the Director anything about your wiki.
              </div>
            )}

            {history.map((turn, i) => (
              <div key={i}>
                {turn.role === 'user' ? (
                  <div style={userBubbleStyle}>
                    <div style={labelStyle}>You</div>
                    <div style={{ whiteSpace: 'pre-wrap' }}>{turn.text}</div>
                  </div>
                ) : (
                  renderAssistant(turn as AssistantTurn, false)
                )}
              </div>
            ))}

            {pending && renderAssistant(pending, true)}

            {error && (
              <div style={{ color: '#f87171', fontSize: '0.85rem', marginBottom: '1rem' }}>
                {error}
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          <div style={inputRowStyle}>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask the Director..."
              disabled={streaming}
              rows={2}
              style={{
                flex: 1,
                background: '#161622',
                border: '1px solid #333',
                borderRadius: 8,
                padding: '0.75rem 1rem',
                color: '#e0e0e0',
                fontSize: '0.95rem',
                fontFamily: 'inherit',
                resize: 'none',
              }}
            />
            <button
              onClick={send}
              disabled={streaming || !input.trim()}
              style={{
                background: '#7b9cff',
                border: 'none',
                color: '#000',
                padding: '0 1.5rem',
                borderRadius: 8,
                cursor: streaming || !input.trim() ? 'not-allowed' : 'pointer',
                fontWeight: 600,
                fontSize: '0.95rem',
                opacity: streaming || !input.trim() ? 0.5 : 1,
              }}
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
