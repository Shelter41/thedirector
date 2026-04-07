import ReactMarkdown from 'react-markdown'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getWikiIndex } from '../lib/api'

interface Props {
  content: string
}

export default function MarkdownViewer({ content }: Props) {
  const navigate = useNavigate()
  const { data: index } = useQuery({
    queryKey: ['wiki-index'],
    queryFn: getWikiIndex,
  })

  // Build a slug → full path lookup so [[slug]] resolves regardless of which
  // directory the LLM put the page in.
  const allPages: string[] = Object.values(index?.pages || {}).flat() as string[]
  const slugMap: Record<string, string> = {}
  for (const path of allPages) {
    const slug = (path.split('/').pop() || path).replace('.md', '')
    slugMap[slug] = path
    slugMap[path] = path
    slugMap[path.replace('.md', '')] = path
  }

  // Replace [[slug]] with clickable markdown links before rendering
  const processed = content.replace(
    /\[\[([^\]]+)\]\]/g,
    (_, slug) => `[${slug}](/wiki/resolve/${slug.trim()})`
  )

  return (
    <div style={{ lineHeight: 1.7, fontSize: '0.95rem' }}>
      <ReactMarkdown
        components={{
          a: ({ href, children }) => {
            if (href?.startsWith('/wiki/resolve/')) {
              const slug = href.replace('/wiki/resolve/', '')
              const target = slugMap[slug]
              return (
                <a
                  href="#"
                  onClick={(e) => {
                    e.preventDefault()
                    if (target) {
                      navigate(`/wiki/${target}`)
                    } else {
                      // Unresolved — still navigate so the user sees the 404
                      navigate(`/wiki/${slug}`)
                    }
                  }}
                  style={{
                    color: target ? '#a78bfa' : '#666',
                    cursor: 'pointer',
                    textDecoration: target ? 'none' : 'line-through',
                  }}
                  title={target ? target : 'unresolved link'}
                >
                  {children}
                </a>
              )
            }
            return <a href={href}>{children}</a>
          },
          h1: ({ children }) => <h1 style={{ borderBottom: '1px solid #333', paddingBottom: '0.5rem', marginBottom: '1rem' }}>{children}</h1>,
          h2: ({ children }) => <h2 style={{ color: '#7b9cff', marginTop: '1.5rem', marginBottom: '0.5rem', fontSize: '1.1rem' }}>{children}</h2>,
          strong: ({ children }) => <strong style={{ color: '#fff' }}>{children}</strong>,
          li: ({ children }) => <li style={{ marginBottom: '0.25rem' }}>{children}</li>,
          code: ({ children }) => <code style={{ background: '#1a1a2e', padding: '0.15rem 0.4rem', borderRadius: 3, fontSize: '0.85em' }}>{children}</code>,
        }}
      >
        {processed}
      </ReactMarkdown>
    </div>
  )
}
