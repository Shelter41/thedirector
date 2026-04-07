import { useEffect, useRef, useState } from 'react'
import { createActivityStream } from '../lib/api'

interface Event {
  id: number
  event: string
  data: any
  time: string
}

const feedStyle: React.CSSProperties = {
  background: '#0d0d14',
  border: '1px solid #222',
  borderRadius: 8,
  padding: '1rem',
  fontFamily: 'monospace',
  fontSize: '0.8rem',
  maxHeight: 400,
  overflowY: 'auto',
}

const eventColors: Record<string, string> = {
  ingest_progress: '#7b9cff',
  ingest_complete: '#4ade80',
  ingest_error: '#f87171',
  wiki_triage_start: '#fbbf24',
  wiki_triage_batch: '#fbbf24',
  wiki_page_update: '#a78bfa',
  wiki_complete: '#4ade80',
}

export default function ActivityFeed() {
  const [events, setEvents] = useState<Event[]>([])
  const [connected, setConnected] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  let idCounter = 0

  useEffect(() => {
    const es = createActivityStream()

    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)

    const handler = (type: string) => (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data)
        setEvents(prev => {
          const next = [...prev, {
            id: idCounter++,
            event: type,
            data,
            time: new Date().toLocaleTimeString(),
          }]
          return next.slice(-100)
        })
      } catch {}
    }

    const types = [
      'ingest_progress', 'ingest_complete', 'ingest_error',
      'wiki_triage_start', 'wiki_triage_batch', 'wiki_page_update', 'wiki_complete',
    ]
    types.forEach(t => es.addEventListener(t, handler(t)))

    return () => es.close()
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events])

  const formatEvent = (ev: Event) => {
    const d = ev.data
    switch (ev.event) {
      case 'ingest_progress':
        if (d.phase === 'fetching') {
          // Initial start event with no other fields
          if (!('fetched' in d) && !('channel' in d) && !('channel_count' in d)) {
            return `Fetching from ${d.source}...`
          }
          // Gmail per-message progress
          if (typeof d.fetched === 'number' && d.last_subject !== undefined) {
            return `[${d.source}] ${d.fetched} fetched — ${d.last_sender || ''} · ${d.last_subject || '(no subject)'}`
          }
          // Slack channel listing done
          if (d.channel_count !== undefined) {
            return `[slack] discovered ${d.channel_count} channels`
          }
          // Slack channel iteration
          if (d.channel) {
            return `[slack] channel ${d.channel_index}/${d.channel_total}: ${d.channel} (so far: ${d.fetched})`
          }
        }
        if (d.phase === 'fetched') return `Fetched ${d.count} messages from ${d.source}`
        if (d.phase === 'storing') return `Storing ${d.total} messages to disk...`
        if (d.phase === 'stored') return `Stored ${d.new} new of ${d.total} total`
        return JSON.stringify(d)
      case 'ingest_complete':
        return `Complete: ${d.new} new messages, ${d.created || 0} pages created, ${d.updated || 0} updated`
      case 'ingest_error':
        return `Error: ${d.error}`
      case 'wiki_triage_start':
        return `Triaging ${d.total_messages} messages...`
      case 'wiki_triage_batch':
        return `Batch ${d.batch}: ${d.operations} page operations`
      case 'wiki_page_update':
        return `${d.action}: ${d.page} — ${d.reason}`
      case 'wiki_complete':
        return `Wiki loop done: ${d.created} created, ${d.updated} updated`
      default:
        return JSON.stringify(d)
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
        <span style={{
          width: 6, height: 6, borderRadius: '50%',
          background: connected ? '#4ade80' : '#f87171',
        }} />
        <span style={{ fontSize: '0.75rem', color: '#888' }}>
          {connected ? 'LIVE' : 'DISCONNECTED'}
        </span>
      </div>
      <div style={feedStyle}>
        {events.length === 0 && (
          <div style={{ color: '#555' }}>Waiting for activity...</div>
        )}
        {events.map(ev => (
          <div key={ev.id} style={{ marginBottom: '0.3rem' }}>
            <span style={{ color: '#555' }}>{ev.time}</span>{' '}
            <span style={{ color: eventColors[ev.event] || '#888' }}>
              {formatEvent(ev)}
            </span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
