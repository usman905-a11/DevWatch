import fs from 'node:fs'
import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

function readRootEnv(): Record<string, string> {
  const envPath = path.resolve(__dirname, '../.env')
  if (!fs.existsSync(envPath)) return {}
  const parsed: Record<string, string> = {}
  for (const rawLine of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const clean = line.startsWith('export ') ? line.slice(7).trim() : line
    const eq = clean.indexOf('=')
    if (eq <= 0) continue
    const key = clean.slice(0, eq).trim()
    let val = clean.slice(eq + 1).trim()
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1)
    }
    parsed[key] = val
  }
  return parsed
}

const rootEnv = readRootEnv()
const rawTarget = (
  process.env.DEVWATCH_SERVICE_URL
  ?? rootEnv.DEVWATCH_SERVICE_URL
  ?? 'http://127.0.0.1:8000'
).trim()
const serviceTarget = rawTarget.replace(/^http:\/\/localhost(?=(:|\/|$))/i, 'http://127.0.0.1')
const serviceApiKey = (
  process.env.DEVWATCH_API_KEY !== undefined
    ? process.env.DEVWATCH_API_KEY
    : (rootEnv.DEVWATCH_API_KEY ?? '')
).trim()

function createBackendProxy() {
  const headers = serviceApiKey ? { 'X-API-Key': serviceApiKey } : undefined
  return {
    '/api': { target: serviceTarget, changeOrigin: true, ws: true, headers },
    '/workspace': { target: serviceTarget, changeOrigin: true, headers },
    '/fs': { target: serviceTarget, changeOrigin: true, headers },
    '/health': { target: serviceTarget, changeOrigin: true, headers },
  }
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: createBackendProxy(),
  },
  preview: {
    proxy: createBackendProxy(),
  },
})
