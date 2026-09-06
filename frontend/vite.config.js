import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Phase 12 — Vite config
// Proxy /api to the stub server (port 8001 dev) or real Phase 8 backend (port 8000 prod).
// Swap the target URL below when Guhan-10's Phase 8 backend is running.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',   // Phase 8 backend (Guhan-10)
        // target: 'http://localhost:8001', // stub server (npm run stub)
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 600,   // Recharts alone is ~525kB — library minimum, not our code
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react':    ['react', 'react-dom'],
          'vendor-leaflet':  ['leaflet', 'react-leaflet'],
          'vendor-recharts': ['recharts'],
          'vendor-h3':       ['h3-js'],
          'vendor-axios':    ['axios'],
        },
      },
    },
  },
});

