import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { spawn } from 'child_process'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'
import net from 'net'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT      = join(__dirname, '..')
const API_PORT  = 8765

function portInUse(port) {
  return new Promise(resolve => {
    const s = net.createConnection(port, '127.0.0.1')
    s.on('connect', () => { s.destroy(); resolve(true)  })
    s.on('error',   () =>               resolve(false) )
  })
}

function apiServerPlugin() {
  let proc = null

  return {
    name: 'api-server',

    async configureServer(server) {
      if (await portInUse(API_PORT)) {
        console.log(`  \x1b[32m✓\x1b[0m  api_server already running on :${API_PORT}`)
        return
      }

      const python = process.platform === 'win32'
        ? join(ROOT, '.venv', 'Scripts', 'python.exe')
        : join(ROOT, '.venv', 'bin', 'python')

      proc = spawn(
        python,
        ['-m', 'uvicorn', 'api_server:app', '--host', '0.0.0.0', '--port', String(API_PORT)],
        { cwd: ROOT, stdio: 'pipe' }
      )

      const tag = `  \x1b[35m[api]\x1b[0m `
      proc.stdout.on('data', d => d.toString().split('\n').filter(Boolean).forEach(l => console.log(tag + l)))
      proc.stderr.on('data', d => d.toString().split('\n').filter(Boolean).forEach(l => console.log(tag + l)))
      proc.on('exit', code => { if (code) console.log(`${tag}exited (${code})`) })

      const kill = () => { if (proc && !proc.killed) proc.kill() }
      server.httpServer?.on('close', kill)
      process.on('SIGINT',  kill)
      process.on('SIGTERM', kill)

      console.log(`  \x1b[32m→\x1b[0m  api_server starting on http://localhost:${API_PORT}`)
    },
  }
}

export default defineConfig({
  plugins: [react(), apiServerPlugin()],
  server: {
    port: 3000,
  },
})
