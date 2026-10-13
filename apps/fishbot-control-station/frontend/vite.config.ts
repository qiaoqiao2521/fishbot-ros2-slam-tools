import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
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
