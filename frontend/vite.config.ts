import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite dev-server config.
//
// The backend runs at http://127.0.0.1:8000 in local development. Instead of
// enabling CORS on FastAPI (which would broaden the attack surface and require
// extra config for cookies later), we proxy `/api` and `/files` here so the
// browser only ever talks to Vite's origin in dev — matching how prod would
// serve the built SPA behind the same origin as the API.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/files': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
