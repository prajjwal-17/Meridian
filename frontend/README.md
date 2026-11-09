# Meridian frontend

Minimal React/Vite workspace for the currently implemented Meridian backend.

```powershell
npm install
npm run dev
```

The Vite dev server proxies `/api/*` to `http://127.0.0.1:8000`. Set
`VITE_API_URL` when the API is hosted elsewhere. The UI currently supports PDF
upload and processing status, document listing, health status, and graph/BM25/
dense/hybrid search through the existing backend modules.
