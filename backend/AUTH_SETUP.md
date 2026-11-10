# Meridian authentication — Stage 1

Stage 1 adds account and session tables without changing existing documents,
chunks, embeddings, ACL assignments, or retrieval code.

Apply the additive migration from the `backend` directory:

```powershell
.\.venv\Scripts\python.exe scripts/migrate_auth.py
```

Create the first administrator once. Replace the example values with the
administrator's real details:

```powershell
.\.venv\Scripts\python.exe scripts/bootstrap_admin.py `
  --name "Initial Administrator" `
  --email "admin@example.com"
```

The command generates a cryptographically secure temporary password, prints it
once, stores only its Argon2id hash, and marks the account for a mandatory
password change. If an active administrator already exists, rerunning the
command exits without creating another account.

Development defaults use an HTTP-only session cookie with `SameSite=Lax` and
`AUTH_COOKIE_SECURE=false`. Set `AUTH_COOKIE_SECURE=true` behind HTTPS in
production. Session lifetime is controlled by `AUTH_SESSION_TTL_HOURS`.
`AUTH_ALLOWED_ORIGINS` must contain the exact browser origins that are allowed
to call cookie-authenticated state-changing endpoints.

The current retrieval routes still use the existing development identity
headers. Replacing those headers with the authenticated database identity is a
separate Stage 3 change.
