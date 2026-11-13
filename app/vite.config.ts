import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  optimizeDeps: { exclude: ['replicad-opencascadejs'] },
  worker: { format: 'es' },
  server: { port: 5173, strictPort: true },
})
