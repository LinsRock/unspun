import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['apple-touch-icon.png', 'icon.svg'],
      manifest: {
        name: 'Unspun',
        short_name: 'Unspun',
        description: 'Personal Intelligence Station',
        lang: 'zh-CN',
        id: '/',
        start_url: '/digest',
        scope: '/',
        display: 'standalone',
        theme_color: '#faf8f4',
        background_color: '#faf8f4',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: '/icon-maskable-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,png,svg}'],
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api(?:\/|$)/, /^\/cdn-cgi(?:\/|$)/],
        cleanupOutdatedCaches: true,
      },
    }),
  ],
  server: {
    proxy: {
      // Preserve Host so same-origin write validation sees the browser's origin.
      '/api': { target: process.env.UNSPUN_DEV_API_URL ?? 'http://localhost:8000', changeOrigin: false },
    },
  },
})
