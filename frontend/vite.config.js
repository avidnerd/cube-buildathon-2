import { defineConfig } from 'vite';

// /api/counter is the Python counter-melody generator (counter_api.py).
// Everything else under /api is the harmony engine (backend/harmony).
const harmony = process.env.HARMONY_API || 'http://127.0.0.1:8765';

export default defineConfig({
  server: {
    proxy: {
      '/api/counter': 'http://127.0.0.1:8001',
      '/api': harmony,
    },
  },
});
