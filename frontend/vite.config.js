import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Final.md §15.4 Swap #2 — deck.gl H3HexagonLayer + MapLibre GL JS
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // HTTP API proxy only — WebSocket connects directly to backend (no ws proxy)
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
        configure: (proxy) => {
          proxy.on('error', () => {});   // swallow ECONNREFUSED when backend is off
        },
      },
    },
  },
  optimizeDeps: {
    // Pre-bundle deck.gl ESM packages so Vite doesn't re-transform them on every reload
    include: [
      'deck.gl',
      '@deck.gl/react',
      '@deck.gl/core',
      '@deck.gl/layers',
      '@deck.gl/geo-layers',
      'react-map-gl',
      'maplibre-gl',
    ],
  },
  build: {
    chunkSizeWarningLimit: 2000,   // deck.gl + maplibre-gl are legitimately large
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react':    ['react', 'react-dom'],
          'vendor-deck':     ['deck.gl', '@deck.gl/react', '@deck.gl/core',
                              '@deck.gl/layers', '@deck.gl/geo-layers'],
          'vendor-maplibre': ['maplibre-gl', 'react-map-gl'],
          'vendor-leaflet':  ['leaflet', 'react-leaflet'],
          'vendor-recharts': ['recharts'],
          'vendor-h3':       ['h3-js'],
          'vendor-axios':    ['axios'],
        },
      },
    },
  },
});
