import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base подставляется при сборке для GitHub Pages: BASE_PATH=/alice-301-backend/
export default defineConfig({
  plugins: [react()],
  base: process.env.BASE_PATH || '/',
})
