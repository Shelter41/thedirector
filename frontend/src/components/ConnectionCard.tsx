import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

interface Props {
  name: string
  provider: 'gmail' | 'slack'
  getStatus: () => Promise<any>
  getAuthUrl: () => Promise<any>
  disconnect: () => Promise<any>
}

const cardStyle: React.CSSProperties = {
  background: '#161622',
  borderRadius: 8,
  padding: '1.25rem',
  border: '1px solid #222',
  minWidth: 240,
}

export default function ConnectionCard({ name, provider, getStatus, getAuthUrl, disconnect }: Props) {
  const qc = useQueryClient()
  const { data: status } = useQuery({
    queryKey: [provider, 'status'],
    queryFn: getStatus,
  })

  const connectMut = useMutation({
    mutationFn: getAuthUrl,
    onSuccess: (data) => {
      window.location.href = data.auth_url
    },
  })

  const disconnectMut = useMutation({
    mutationFn: disconnect,
    onSuccess: () => qc.invalidateQueries({ queryKey: [provider, 'status'] }),
  })

  const connected = status?.connected && !status?.needs_reconnect

  return (
    <div style={cardStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
        <span style={{
          width: 8, height: 8, borderRadius: '50%',
          background: connected ? '#4ade80' : status?.needs_reconnect ? '#fbbf24' : '#666',
          display: 'inline-block',
        }} />
        <strong>{name}</strong>
      </div>

      {status?.connected_at && (
        <div style={{ fontSize: '0.8rem', color: '#888', marginBottom: '0.75rem' }}>
          Connected {new Date(status.connected_at).toLocaleDateString()}
        </div>
      )}
      {status?.team_name && (
        <div style={{ fontSize: '0.8rem', color: '#888', marginBottom: '0.75rem' }}>
          Team: {status.team_name}
        </div>
      )}

      {connected ? (
        <button
          onClick={() => disconnectMut.mutate()}
          style={{
            background: 'transparent', border: '1px solid #555', color: '#aaa',
            padding: '0.4rem 1rem', borderRadius: 4, cursor: 'pointer', fontSize: '0.85rem',
          }}
        >
          Disconnect
        </button>
      ) : (
        <button
          onClick={() => connectMut.mutate()}
          disabled={connectMut.isPending}
          style={{
            background: '#7b9cff', border: 'none', color: '#000',
            padding: '0.4rem 1rem', borderRadius: 4, cursor: 'pointer',
            fontWeight: 600, fontSize: '0.85rem',
          }}
        >
          {status?.needs_reconnect ? 'Reconnect' : 'Connect'}
        </button>
      )}
    </div>
  )
}
