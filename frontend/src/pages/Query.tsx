import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { askQuery } from '../lib/api'
import MarkdownViewer from '../components/MarkdownViewer'

interface QueryResult {
  question: string
  answer: string
  sources: string[]
}

export default function Query() {
  const [question, setQuestion] = useState('')
  const [history, setHistory] = useState<QueryResult[]>([])

  const queryMut = useMutation({
    mutationFn: (q: string) => askQuery(q),
    onSuccess: (data, q) => {
      setHistory(prev => [...prev, { question: q, answer: data.answer, sources: data.sources }])
      setQuestion('')
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (question.trim()) {
      queryMut.mutate(question.trim())
    }
  }

  return (
    <div>
      <h1 style={{ marginBottom: '2rem', fontWeight: 600 }}>Query</h1>

      {/* History */}
      <div style={{ marginBottom: '2rem' }}>
        {history.map((item, i) => (
          <div key={i} style={{ marginBottom: '1.5rem' }}>
            <div style={{
              background: '#1a1a2e',
              borderRadius: 8,
              padding: '0.75rem 1rem',
              marginBottom: '0.5rem',
              color: '#7b9cff',
              fontWeight: 500,
            }}>
              {item.question}
            </div>
            <div style={{
              background: '#111118',
              borderRadius: 8,
              border: '1px solid #222',
              padding: '1.25rem',
            }}>
              <MarkdownViewer content={item.answer} />
              {item.sources.length > 0 && (
                <div style={{
                  marginTop: '1rem',
                  paddingTop: '0.75rem',
                  borderTop: '1px solid #222',
                  fontSize: '0.8rem',
                  color: '#888',
                }}>
                  Sources: {item.sources.join(', ')}
                </div>
              )}
            </div>
          </div>
        ))}

        {queryMut.isPending && (
          <div style={{ color: '#888', marginBottom: '1rem' }}>Thinking...</div>
        )}
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '0.5rem' }}>
        <input
          type="text"
          value={question}
          onChange={e => setQuestion(e.target.value)}
          placeholder="Ask about your knowledge base..."
          disabled={queryMut.isPending}
          style={{
            flex: 1,
            background: '#161622',
            border: '1px solid #333',
            borderRadius: 8,
            padding: '0.75rem 1rem',
            color: '#e0e0e0',
            fontSize: '0.95rem',
          }}
        />
        <button
          type="submit"
          disabled={queryMut.isPending || !question.trim()}
          style={{
            background: '#7b9cff',
            border: 'none',
            color: '#000',
            padding: '0.75rem 1.5rem',
            borderRadius: 8,
            cursor: 'pointer',
            fontWeight: 600,
            fontSize: '0.95rem',
          }}
        >
          Ask
        </button>
      </form>
    </div>
  )
}
