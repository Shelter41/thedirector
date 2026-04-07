import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

interface BaseProps {
  name: string
  provider: string
  getStatus: () => Promise<any>
  disconnect: () => Promise<any>
}

interface OAuthProps extends BaseProps {
  mode?: 'oauth'
  getAuthUrl: () => Promise<any>
}

interface TokenProps extends BaseProps {
  mode: 'token'
  connectWithToken: (token: string) => Promise<any>
  tokenHelpUrl?: string  // e.g. https://www.notion.so/my-integrations
  tokenHelpText?: string
}

type Props = OAuthProps | TokenProps

const cardStyle: React.CSSProperties = {
  background: '#161622',
  borderRadius: 8,
  padding: '1.25rem',
  border: '1px solid #222',
  minWidth: 240,
}

const modalOverlayStyle: React.CSSProperties = {
  position: 'fixed',
  top: 0, left: 0, right: 0, bottom: 0,
  background: 'rgba(0,0,0,0.7)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  zIndex: 1000,
}

const modalStyle: React.CSSProperties = {
  background: '#161622',
  borderRadius: 8,
  border: '1px solid #333',
  padding: '1.5rem',
  width: 460,
  maxWidth: '90vw',
}

export default function ConnectionCard(props: Props) {
  const { name, provider, getStatus, disconnect } = props
  const qc = useQueryClient()
  const [tokenModalOpen, setTokenModalOpen] = useState(false)
  const [tokenInput, setTokenInput] = useState('')
  const [tokenError, setTokenError] = useState<string | null>(null)

  const { data: status } = useQuery({
    queryKey: [provider, 'status'],
    queryFn: getStatus,
  })

  const oauthConnectMut = useMutation({
    mutationFn: async () => {
      if (props.mode !== 'token') return (props as OAuthProps).getAuthUrl()
      throw new Error('not oauth')
    },
    onSuccess: (data: any) => {
      window.location.href = data.auth_url
    },
  })

  const tokenConnectMut = useMutation({
    mutationFn: async (token: string) => {
      if (props.mode !== 'token') throw new Error('not token mode')
      return (props as TokenProps).connectWithToken(token)
    },
    onSuccess: (data: any) => {
      if (data?.error) {
        setTokenError(data.error)
        return
      }
      setTokenModalOpen(false)
      setTokenInput('')
      setTokenError(null)
      qc.invalidateQueries({ queryKey: [provider, 'status'] })
    },
    onError: (err: any) => {
      setTokenError(err?.message || String(err))
    },
  })

  const disconnectMut = useMutation({
    mutationFn: disconnect,
    onSuccess: () => qc.invalidateQueries({ queryKey: [provider, 'status'] }),
  })

  const connected = status?.connected && !status?.needs_reconnect

  const handleConnectClick = () => {
    if (props.mode === 'token') {
      setTokenError(null)
      setTokenInput('')
      setTokenModalOpen(true)
    } else {
      oauthConnectMut.mutate()
    }
  }

  return (
    <>
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
        {status?.bot_name && (
          <div style={{ fontSize: '0.8rem', color: '#888', marginBottom: '0.75rem' }}>
            Integration: {status.bot_name}
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
            onClick={handleConnectClick}
            disabled={oauthConnectMut.isPending}
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

      {tokenModalOpen && props.mode === 'token' && (
        <div style={modalOverlayStyle} onClick={() => setTokenModalOpen(false)}>
          <div style={modalStyle} onClick={(e) => e.stopPropagation()}>
            <h2 style={{ marginBottom: '0.5rem', fontSize: '1.1rem' }}>Connect {name}</h2>
            {props.tokenHelpText && (
              <p style={{ color: '#aaa', fontSize: '0.85rem', marginBottom: '0.75rem' }}>
                {props.tokenHelpText}
              </p>
            )}
            {props.tokenHelpUrl && (
              <p style={{ marginBottom: '0.75rem' }}>
                <a
                  href={props.tokenHelpUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: '#7b9cff', fontSize: '0.85rem' }}
                >
                  Open {props.tokenHelpUrl}↗
                </a>
              </p>
            )}
            <input
              type="password"
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              placeholder="Paste your integration token"
              autoFocus
              style={{
                width: '100%',
                background: '#0d0d14',
                border: '1px solid #333',
                borderRadius: 4,
                padding: '0.5rem 0.75rem',
                color: '#e0e0e0',
                fontSize: '0.9rem',
                marginBottom: '0.75rem',
                fontFamily: 'monospace',
              }}
            />
            {tokenError && (
              <div style={{ color: '#f87171', fontSize: '0.8rem', marginBottom: '0.75rem' }}>
                {tokenError}
              </div>
            )}
            <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
              <button
                onClick={() => setTokenModalOpen(false)}
                disabled={tokenConnectMut.isPending}
                style={{
                  background: 'transparent',
                  border: '1px solid #555',
                  color: '#aaa',
                  padding: '0.4rem 1rem',
                  borderRadius: 4,
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                }}
              >
                Cancel
              </button>
              <button
                onClick={() => tokenConnectMut.mutate(tokenInput.trim())}
                disabled={tokenConnectMut.isPending || !tokenInput.trim()}
                style={{
                  background: '#7b9cff',
                  border: 'none',
                  color: '#000',
                  padding: '0.4rem 1rem',
                  borderRadius: 4,
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  opacity: (tokenConnectMut.isPending || !tokenInput.trim()) ? 0.5 : 1,
                }}
              >
                {tokenConnectMut.isPending ? 'Connecting...' : 'Connect'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
