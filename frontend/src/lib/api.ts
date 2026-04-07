const BASE = ''

async function fetchJSON(url: string, opts?: RequestInit) {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

// Auth
export const getGmailAuthUrl = () => fetchJSON('/auth/gmail/url')
export const getGmailStatus = () => fetchJSON('/auth/gmail/status')
export const disconnectGmail = () => fetchJSON('/auth/gmail', { method: 'DELETE' })

export const getSlackAuthUrl = () => fetchJSON('/auth/slack/url')
export const getSlackStatus = () => fetchJSON('/auth/slack/status')
export const disconnectSlack = () => fetchJSON('/auth/slack', { method: 'DELETE' })

// Notion uses a static integration token, not OAuth
export const getNotionStatus = () => fetchJSON('/auth/notion/status')
export const connectNotion = (token: string) =>
  fetchJSON('/auth/notion', {
    method: 'POST',
    body: JSON.stringify({ token }),
  })
export const disconnectNotion = () => fetchJSON('/auth/notion', { method: 'DELETE' })

// Ingest
export const triggerIngest = (source: string, days: number) =>
  fetchJSON('/ingest', {
    method: 'POST',
    body: JSON.stringify({ source, days }),
  })

export const getIngestStatus = () => fetchJSON('/ingest/status')

// Status
export const getStatus = () => fetchJSON('/status')

// Wiki
export const getWikiIndex = () => fetchJSON('/wiki/index')
export const getWikiPage = (path: string) =>
  fetchJSON(`/wiki/page/${path}`)
export const listWikiPages = (directory?: string) =>
  fetchJSON(`/wiki/pages${directory ? `?directory=${directory}` : ''}`)
export const getWikiLog = () => fetchJSON('/wiki/log')

// Query
export const askQuery = (question: string) =>
  fetchJSON('/query', {
    method: 'POST',
    body: JSON.stringify({ question }),
  })

// Chat — streaming agent events
export interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
}

export type ChatEvent =
  | { type: 'thread'; thread_id: string; title: string }
  | { type: 'delta'; text: string }
  | { type: 'tool_call'; id: string; name: string; input: Record<string, any> }
  | { type: 'tool_result'; id: string; ok: boolean; preview?: string; error?: string }
  | { type: 'error'; message: string }
  | { type: 'done' }

export async function* streamChat(
  messages: ChatMsg[],
  threadId?: string | null,
): AsyncGenerator<ChatEvent, void, unknown> {
  const res = await fetch('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, thread_id: threadId }),
  })

  if (!res.ok || !res.body) {
    throw new Error(`chat failed: ${res.status} ${res.statusText}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE frames are separated by a blank line
    const frames = buffer.split('\n\n')
    buffer = frames.pop() || ''

    for (const frame of frames) {
      const line = frame.trim()
      if (!line.startsWith('data:')) continue
      const payload = line.slice(5).trim()
      if (!payload) continue
      try {
        const obj = JSON.parse(payload) as ChatEvent
        yield obj
        if (obj.type === 'done') return
      } catch {
        // ignore parse errors on partial frames
      }
    }
  }
}

// Chat threads (persisted)
export interface ChatThreadMeta {
  id: string
  title: string
  created_at: string
  updated_at: string
  turn_count: number
}

export const listChatThreads = (): Promise<{ threads: ChatThreadMeta[] }> =>
  fetchJSON('/chats')

export const getChatThread = (id: string): Promise<{ meta: ChatThreadMeta; events: any[] }> =>
  fetchJSON(`/chats/${id}`)

export const deleteChatThread = (id: string) =>
  fetchJSON(`/chats/${id}`, { method: 'DELETE' })

// Dream — streaming agent events
export type DreamEvent =
  | { type: 'dream_start'; dream_id: string; max_ops: number; max_writes: number; started_at: string }
  | { type: 'budget'; ops_used: number; ops_total: number; writes_used: number; writes_total: number }
  | { type: 'tool_call'; id: string; name: string; input: Record<string, any> }
  | { type: 'tool_result'; id: string; ok: boolean; preview?: string; error?: string }
  | { type: 'delta'; text: string }
  | { type: 'dream_done'; summary: string }
  | { type: 'error'; message: string }
  | { type: 'done' }

export async function* streamDream(
  maxOps: number,
  maxWrites: number,
): AsyncGenerator<DreamEvent, void, unknown> {
  const res = await fetch('/dream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ max_ops: maxOps, max_writes: maxWrites }),
  })

  if (!res.ok || !res.body) {
    throw new Error(`dream failed: ${res.status} ${res.statusText}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const frames = buffer.split('\n\n')
    buffer = frames.pop() || ''

    for (const frame of frames) {
      const line = frame.trim()
      if (!line.startsWith('data:')) continue
      const payload = line.slice(5).trim()
      if (!payload) continue
      try {
        const obj = JSON.parse(payload) as DreamEvent
        yield obj
        if (obj.type === 'done') return
      } catch {
        // ignore parse errors on partial frames
      }
    }
  }
}

export interface DreamMeta {
  id: string
  started_at: string
  ended_at: string | null
  status: 'running' | 'complete' | 'incomplete' | 'error'
  max_ops: number
  max_writes: number
  ops_used: number
  writes_used: number
}

export const listDreams = (): Promise<{ dreams: DreamMeta[] }> => fetchJSON('/dreams')

export const getDream = (id: string): Promise<{ meta: DreamMeta; events: any[]; report: string | null }> =>
  fetchJSON(`/dreams/${id}`)

export const deleteDream = (id: string) =>
  fetchJSON(`/dreams/${id}`, { method: 'DELETE' })

// SSE
export function createActivityStream(): EventSource {
  return new EventSource(`${BASE}/activity/stream`)
}
