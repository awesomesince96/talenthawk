import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Plotly runtime is loaded via <script> in index.html (window.Plotly). Types-only imports use @types/plotly.js.

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
