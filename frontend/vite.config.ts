import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api': {
        // Dev overlay: the compose service is named `app` (the single
        // container that also serves the built SPA in production). This
        // proxy is dev-server only — `npm run build` ignores server.proxy.
        target: 'http://app:8000',
        changeOrigin: true,
        // Proxy WebSocket upgrades too (real-time notifications endpoint
        // lives under /api/notifications/ws/notifications)
        ws: true,
      },
      '/health': {
        target: 'http://app:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks: {
          reactCore: ['react', 'react-dom', 'react-router-dom'],
          charting: ['recharts'],
        },
        assetFileNames: (assetInfo: any) => {
          if (assetInfo.name && typeof assetInfo.name === 'string' && assetInfo.name.endsWith('.css')) {
            return 'assets/[name]-[hash][extname]';
          }
          return 'assets/[name]-[hash][extname]';
        },
      },
    },
    minify: 'esbuild',
    cssCodeSplit: true,
  },
  optimizeDeps: {
    include: ['recharts'],
  },
})
