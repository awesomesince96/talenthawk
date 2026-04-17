/**
 * Copy Plotly's prebuilt browser bundle into public/ so index.html can load it
 * from the same origin (no CDN / ad-block issues). Run via npm predev / prebuild.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const webRoot = path.join(__dirname, '..')
const src = path.join(webRoot, 'node_modules', 'plotly.js', 'dist', 'plotly.min.js')
const dstDir = path.join(webRoot, 'public')
const dst = path.join(dstDir, 'plotly.min.js')

if (!fs.existsSync(src)) {
  console.error('copy-plotly: missing', src, '— run npm install in web/')
  process.exit(1)
}
fs.mkdirSync(dstDir, { recursive: true })
fs.copyFileSync(src, dst)
console.log('copy-plotly:', path.relative(webRoot, dst))
