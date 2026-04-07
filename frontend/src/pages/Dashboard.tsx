import { useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  getGmailStatus, getGmailAuthUrl, disconnectGmail,
  getSlackStatus, getSlackAuthUrl, disconnectSlack,
  getStatus, triggerIngest,
} from '../lib/api'
import ConnectionCard from '../components/ConnectionCard'
import ActivityFeed from '../components/ActivityFeed'

const sectionStyle: React.CSSProperties = {
  marginBottom: '2rem',
}

const headerStyle: React.CSSProperties = {
  fontSize: '0.85rem',
  color: '#888',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
  marginBottom: '1rem',
}

export default function Dashboard() {
  const qc = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()

  // Handle OAuth callbacks
  useEffect(() => {
    if (searchParams.get('gmail') === 'connected') {
      qc.invalidateQueries({ queryKey: ['gmail', 'status'] })
      setSearchParams({})
    }
    if (searchParams.get('slack') === 'connected') {
      qc.invalidateQueries({ queryKey: ['slack', 'status'] })
      setSearchParams({})
    }
  }, [searchParams])

  const { data: status } = useQuery({
    queryKey: ['status'],
    queryFn: getStatus,
    refetchInterval: 10_000,
  })

  const ingestMut = useMutation({
    mutationFn: ({ source, days }: { source: string; days: number }) =>
      triggerIngest(source, days),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['status'] }),
  })

  const timeRanges = [
    { label: '24h', days: 1 },
    { label: '7d', days: 7 },
    { label: '30d', days: 30 },
    { label: '90d', days: 90 },
    { label: '1y', days: 365 },
  ]

  return (
    <div>
      <h1 style={{ marginBottom: '2rem', fontWeight: 600 }}>Dashboard</h1>

      {/* Connections */}
      <div style={sectionStyle}>
        <div style={headerStyle}>Connections</div>
        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
          <ConnectionCard
            name="Gmail"
            provider="gmail"
            getStatus={getGmailStatus}
            getAuthUrl={getGmailAuthUrl}
            disconnect={disconnectGmail}
          />
          <ConnectionCard
            name="Slack"
            provider="slack"
            getStatus={getSlackStatus}
            getAuthUrl={getSlackAuthUrl}
            disconnect={disconnectSlack}
          />
        </div>
      </div>

      {/* Ingest */}
      <div style={sectionStyle}>
        <div style={headerStyle}>Ingest</div>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
          {['all', 'gmail', 'slack'].map(source => (
            <div key={source} style={{ display: 'flex', gap: '0.25rem' }}>
              {timeRanges.map(({ label, days }) => (
                <button
                  key={`${source}-${label}`}
                  onClick={() => ingestMut.mutate({ source, days })}
                  disabled={ingestMut.isPending}
                  style={{
                    background: '#1a1a2e',
                    border: '1px solid #333',
                    color: '#ccc',
                    padding: '0.35rem 0.75rem',
                    borderRadius: 4,
                    cursor: 'pointer',
                    fontSize: '0.8rem',
                  }}
                >
                  {source} {label}
                </button>
              ))}
            </div>
          ))}
        </div>
        {ingestMut.isSuccess && (
          <div style={{ color: '#4ade80', fontSize: '0.85rem' }}>
            Ingestion started (job: {ingestMut.data?.job_id})
          </div>
        )}
        {ingestMut.isError && (
          <div style={{ color: '#f87171', fontSize: '0.85rem' }}>
            {String(ingestMut.error)}
          </div>
        )}
      </div>

      {/* Status + Activity */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem' }}>
        <div>
          <div style={headerStyle}>Status</div>
          <div style={{
            background: '#161622',
            borderRadius: 8,
            padding: '1.25rem',
            border: '1px solid #222',
          }}>
            <div style={{ marginBottom: '0.5rem' }}>
              <span style={{ color: '#888' }}>Wiki pages: </span>
              <span style={{ fontWeight: 600 }}>{status?.wiki?.page_count ?? '—'}</span>
            </div>
            <div style={{ marginBottom: '0.5rem' }}>
              <span style={{ color: '#888' }}>Raw messages: </span>
              <span style={{ fontWeight: 600 }}>{status?.wiki?.raw_count ?? '—'}</span>
            </div>
            <div style={{ marginBottom: '0.5rem' }}>
              <span style={{ color: '#888' }}>Last raw fetch: </span>
              <span style={{ fontWeight: 600 }}>
                {status?.wiki?.last_raw_fetch
                  ? new Date(status.wiki.last_raw_fetch).toLocaleString()
                  : 'never'}
              </span>
            </div>
            <div>
              <span style={{ color: '#888' }}>Last full ingest: </span>
              <span style={{ fontWeight: 600 }}>
                {status?.wiki?.last_ingest
                  ? new Date(status.wiki.last_ingest).toLocaleString()
                  : 'never'}
              </span>
            </div>
          </div>
        </div>
        <div>
          <div style={headerStyle}>Activity</div>
          <ActivityFeed />
        </div>
      </div>
    </div>
  )
}
