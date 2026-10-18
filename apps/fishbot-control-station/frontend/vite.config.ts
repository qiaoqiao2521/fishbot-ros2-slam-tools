import path from 'node:path'
import fs from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { validateWorkbenchProfile, workbenchProxy } from './src/lib/workbench-profile'

const frontendPort = Number(process.env.FRONTEND_PORT || '5173')
const profilePath = process.env.FISHBOT_WORKBENCH_PROFILE
const profile = validateWorkbenchProfile(profilePath ? JSON.parse(fs.readFileSync(profilePath, 'utf8')) : {
  schema_version: 1, label: '本机工作台', services: {
    station: { port: Number(process.env.BACKEND_PORT || 8080), domain: null },
    mission: { port: Number(process.env.FISHBOT_MISSION_PORT || 9070), domain: Number(process.env.VITE_FISHBOT_SIM_DOMAIN || 93) },
    cooperation: { port: Number(process.env.FISHBOT_COOP_PORT || 9086), domain: Number(process.env.VITE_COOPERATION_DOMAIN || 114) },
    voice: { port: Number(process.env.FISHBOT_VOICE_PORT || 9094), domain: Number(process.env.VITE_FISHBOT_VOICE_DOMAIN || 121) },
  }, tools: { spatiallm: Number(process.env.FISHBOT_SPATIALLM_PORT || 8867), video: Number(process.env.FISHBOT_VIDEO_PORT || 18089) },
}, frontendPort)
const proxy = workbenchProxy(profile)
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  define: {
    'import.meta.env.VITE_FISHBOT_SIM_DOMAIN': JSON.stringify(String(profile.services.mission.domain)),
    'import.meta.env.VITE_COOPERATION_DOMAIN': JSON.stringify(String(profile.services.cooperation.domain)),
    'import.meta.env.VITE_FISHBOT_VOICE_DOMAIN': JSON.stringify(String(profile.services.voice.domain)),
    'import.meta.env.VITE_FISHBOT_TOOL_PORTS': JSON.stringify(JSON.stringify(profile.tools)),
  },
  server: { host: '127.0.0.1', port: frontendPort, strictPort: true, proxy },
  preview: { host: '127.0.0.1', port: frontendPort, strictPort: true, proxy },
})
