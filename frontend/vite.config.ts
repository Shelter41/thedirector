import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/auth': 'http://localhost:8000',
      '/ingest': 'http://localhost:8000',
      '/status': 'http://localhost:8000',
      '/wiki': 'http://localhost:8000',
      '/query': 'http://localhost:8000',
      '/chat': 'http://localhost:8000',
      '/chats': 'http://localhost:8000',
      '/activity': 'http://localhost:8000',
    },
  },
})
