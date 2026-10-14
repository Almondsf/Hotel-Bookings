/// <reference types="vitest" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// In development the API is proxied, so the app and API share an origin and
// the SameSite=Strict refresh cookie works exactly as in production.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: { '/api': process.env.API_TARGET ?? 'http://127.0.0.1:8000' },
  },
  test: { environment: 'jsdom' },
});
