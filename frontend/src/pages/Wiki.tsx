import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getWikiIndex, getWikiPage } from '../lib/api'
import MarkdownViewer from '../components/MarkdownViewer'

const sidebarStyle: React.CSSProperties = {
  width: 280,
  background: '#111118',
  borderRadius: 8,
  border: '1px solid #222',
  padding: '1rem',
  maxHeight: 'calc(100vh - 140px)',
  overflowY: 'auto',
  flexShrink: 0,
}

// Stable color palette assigned by directory hash so the LLM's chosen
// directories all get a consistent color without hardcoding names.
const palette = ['#7b9cff', '#4ade80', '#fbbf24', '#a78bfa', '#f472b6', '#22d3ee', '#fb923c', '#34d399']
function colorFor(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) | 0
  return palette[Math.abs(h) % palette.length]
}

export default function Wiki() {
  const { '*': splat } = useParams()
  const navigate = useNavigate()
  const [filter, setFilter] = useState('')

  const currentPath = splat || ''

  const { data: index } = useQuery({
    queryKey: ['wiki-index'],
    queryFn: getWikiIndex,
  })

  const { data: page, isLoading: pageLoading } = useQuery({
    queryKey: ['wiki-page', currentPath],
    queryFn: () => getWikiPage(currentPath),
    enabled: !!currentPath,
  })

  const grouped: Record<string, string[]> = index?.pages || {}
  const allEntries = Object.entries(grouped).flatMap(([bucket, list]) =>
    (list as string[]).map(p => ({
      bucket,
      path: p,
      name: p.split('/').pop()?.replace('.md', '') || p,
    }))
  )
  const filtered = filter
    ? allEntries.filter(e => e.name.toLowerCase().includes(filter.toLowerCase()) || e.path.toLowerCase().includes(filter.toLowerCase()))
    : allEntries

  const buckets = Object.keys(grouped).sort()

  return (
    <div style={{ display: 'flex', gap: '1.5rem' }}>
      {/* Sidebar */}
      <div style={sidebarStyle}>
        <input
          type="text"
          placeholder="Filter pages..."
          value={filter}
          onChange={e => setFilter(e.target.value)}
          style={{
            width: '100%',
            background: '#0d0d14',
            border: '1px solid #333',
            borderRadius: 4,
            padding: '0.4rem 0.6rem',
            color: '#e0e0e0',
            fontSize: '0.85rem',
            marginBottom: '1rem',
          }}
        />

        {buckets.length === 0 && (
          <div style={{ color: '#555', fontSize: '0.85rem' }}>No pages yet. Run an ingestion first.</div>
        )}

        {buckets.map(bucket => {
          const bucketPages = filtered.filter(e => e.bucket === bucket)
          if (bucketPages.length === 0) return null
          const label = bucket === '_root' ? '(root)' : bucket
          return (
            <div key={bucket} style={{ marginBottom: '1rem' }}>
              <div style={{
                fontSize: '0.75rem',
                color: colorFor(bucket),
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                marginBottom: '0.4rem',
              }}>
                {label} ({bucketPages.length})
              </div>
              {bucketPages.map(e => {
                const isActive = currentPath === e.path
                return (
                  <div
                    key={e.path}
                    onClick={() => navigate(`/wiki/${e.path}`)}
                    style={{
                      padding: '0.3rem 0.5rem',
                      borderRadius: 4,
                      cursor: 'pointer',
                      background: isActive ? '#1a1a2e' : 'transparent',
                      color: isActive ? '#fff' : '#aaa',
                      fontSize: '0.85rem',
                      marginBottom: '0.15rem',
                    }}
                  >
                    {e.name}
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {!currentPath && (
          <div>
            <h1 style={{ marginBottom: '1rem', fontWeight: 600 }}>Wiki</h1>
            <div style={{ color: '#888', marginBottom: '2rem' }}>
              {index?.total || 0} pages. Select one from the sidebar.
            </div>
            {index?.index_md && (
              <div style={{
                background: '#111118',
                borderRadius: 8,
                border: '1px solid #222',
                padding: '2rem',
              }}>
                <MarkdownViewer content={index.index_md} />
              </div>
            )}
          </div>
        )}
        {currentPath && pageLoading && (
          <div style={{ color: '#888' }}>Loading...</div>
        )}
        {page?.content && (
          <div style={{
            background: '#111118',
            borderRadius: 8,
            border: '1px solid #222',
            padding: '2rem',
          }}>
            <MarkdownViewer content={page.content} />
          </div>
        )}
        {currentPath && !pageLoading && !page?.content && (
          <div style={{ color: '#f87171' }}>Page not found: {currentPath}</div>
        )}
      </div>
    </div>
  )
}
