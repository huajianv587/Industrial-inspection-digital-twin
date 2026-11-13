import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  envDir: '..',
  envPrefix: ['VITE_', 'SUPABASE_URL', 'SUPABASE_ANON_KEY'],
  plugins: [react()],
  build: {
    // Three.js is intentionally isolated into its own browser-rendering chunk.
    // Keep the warning threshold above that known vendor boundary while the
    // application and auth chunks remain independently cacheable.
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('/node_modules/@supabase/')) return 'supabase-auth'
          if (id.includes('/node_modules/three/')) return 'three-scene'
        },
      },
    },
  },
  server: {
    proxy: {
      '/api': process.env.VITE_DEV_API_TARGET || 'http://127.0.0.1:8010',
      '/healthz': process.env.VITE_DEV_API_TARGET || 'http://127.0.0.1:8010',
    },
  },
})
