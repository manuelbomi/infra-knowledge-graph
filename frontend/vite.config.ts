import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend runs on port 8000. Proxying here means the frontend code can
// just call "/api/..." and "/ws/..." without caring whether it's running
// against the Vite dev server or a production build served behind the same
// domain as the API.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
    },
  },
})
