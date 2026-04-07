import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Wiki from './pages/Wiki'
import Query from './pages/Query'
import Chat from './pages/Chat'

const navStyle = {
  display: 'flex',
  gap: '1.5rem',
  padding: '1rem 2rem',
  background: '#111118',
  borderBottom: '1px solid #222',
  alignItems: 'center',
}

const logoStyle = {
  fontWeight: 700,
  fontSize: '1.1rem',
  color: '#fff',
  marginRight: '2rem',
}

const linkStyle = ({ isActive }: { isActive: boolean }) => ({
  color: isActive ? '#7b9cff' : '#888',
  fontWeight: isActive ? 600 : 400,
  textDecoration: 'none',
  fontSize: '0.9rem',
})

export default function App() {
  return (
    <BrowserRouter>
      <nav style={navStyle}>
        <span style={logoStyle}>The Director</span>
        <NavLink to="/" style={linkStyle} end>Dashboard</NavLink>
        <NavLink to="/wiki" style={linkStyle}>Wiki</NavLink>
        <NavLink to="/chat" style={linkStyle}>Chat</NavLink>
        <NavLink to="/query" style={linkStyle}>Query</NavLink>
      </nav>
      <main style={{ padding: '2rem', maxWidth: 1200, margin: '0 auto' }}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/wiki" element={<Wiki />} />
          <Route path="/wiki/*" element={<Wiki />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/query" element={<Query />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}
