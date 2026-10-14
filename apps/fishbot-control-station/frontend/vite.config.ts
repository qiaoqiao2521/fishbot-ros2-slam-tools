import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const frontendPort = Number(process.env.FRONTEND_PORT || '5173')
if (!Number.isInteger(frontendPort) || frontendPort < 1 || frontendPort > 65535) throw new Error('FRONTEND_PORT must be a valid TCP port.')

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: frontendPort,
    proxy: {
      '/workbench-service/spatiallm': {
        target: 'http://127.0.0.1:8867',
        changeOrigin: true,
        rewrite: () => '/api/health',
      },
      '/workbench-service/video': {
        target: 'http://127.0.0.1:18089',
        changeOrigin: true,
        rewrite: () => '/api/run',
      },
      '/coop-api': {
        target: `http://127.0.0.1:${process.env.FISHBOT_COOP_PORT || '9086'}`,
        changeOrigin: true,
      },
      '/sim-api': {
        target: `http://127.0.0.1:${process.env.FISHBOT_MISSION_PORT || '9070'}`,
        changeOrigin: true,
      },
      '/api': {
        target: `http://127.0.0.1:${process.env.BACKEND_PORT || '8080'}`,
        changeOrigin: true,
      },
    },
  },
})
