# Meridian frontend

React/Vite workspace for the Meridian Enterprise RAG backend. The frontend keeps
the current API integration in place while presenting three focused workspaces:
Chat, Documents, and Entity graph.

```powershell
npm install
npm run dev
```

The Vite dev server proxies `/api/*` to `http://127.0.0.1:8000`. Set
`VITE_API_URL` when the API is hosted elsewhere.

The Chat workspace sends the development identity headers expected by the API:
`X-Meridian-User`, `X-Meridian-Team`, and `X-Meridian-Department`. Hybrid mode
uses `POST /ask` with the existing reranker enabled; Graph, BM25, and Dense
modes use `GET /search`. Results retain document/chunk metadata, scores, and
citations returned by the backend.

The Documents workspace sends an explicit `permission_tier` with every upload
and exposes department, team, and restricted-user fields when those tiers are
selected. It does not replace the backend's ACL checks.

Useful checks:

```powershell
npm run build
npm run dev
```
