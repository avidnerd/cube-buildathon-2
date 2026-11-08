import { defineConfig } from 'vite';

// /api is served by the Python counter-melody generator (counter_api.py).
export default defineConfig({
  server: {
    proxy: { '/api': 'http://127.0.0.1:8001' },
  },
});
