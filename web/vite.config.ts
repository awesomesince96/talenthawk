import path from 'path'
import { fileURLToPath } from 'url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const root = fileURLToPath(new URL('.', import.meta.url))

// Use the prebuilt browser bundle so we do not pull plotly.js Node-only sources (buffer/stream).
const plotlyDist = path.resolve(root, 'node_modules/plotly.js/dist/plotly.js')

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      'plotly.js': plotlyDist,
    },
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
