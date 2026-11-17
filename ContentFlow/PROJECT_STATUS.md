# Project status

Last updated: 2026-11-16 · Branch: `Mohsin`

## Legend
✅ done and tested · 🟡 in progress · ⏳ not started · 🔒 blocked on an external requirement

## Feature status

| Area | Status | Notes |
|---|---|---|
| Registration, login, sessions, password change | ✅ | Rate limited |
| Deployment proxy and Render Blueprint | ✅ | Not deployed; Render deploy branch unconfirmed |
| SQLite → PostgreSQL support and migration tooling | ✅ | Paid database not provisioned (awaiting approval) |
| Workspaces, roles, client management | ✅ | Invitations by shareable link (email delivery not configured) |
| Meta connection: Pages, Instagram, reconnect | ✅ | Live sign-in needs your Meta app + test Page (manual test) |
| Content drafts, platform versions, media library | ✅ | |
| Client approval workflow | ✅ | |
| Facebook and Instagram publishing | ✅ | Live posting needs a real Page/IG account (manual test) |
| Scheduling worker with retries | ✅ | Enabled locally (`CONTENT_FLOW_PUBLISHER_ENABLED=true`) |
| Analytics | ✅ | Live numbers need connected accounts with insights permission (manual test) |
| TikTok, LinkedIn | ✅ code / 🔒 live | Needs app credentials; TikTok audit for public posts; LinkedIn approval for company Pages |

## External requirements (owner action needed)

- Confirm in the Render dashboard which branch (if any) Render deploys from,
  and set the Blueprint Path to `ContentFlow/render.yaml`.
- Approval before provisioning a paid PostgreSQL database.
- Facebook + Instagram go-live (current phase): add the OAuth redirect,
  deauthorize and data-deletion URLs in the Meta app, connect a test Page with
  a linked Instagram professional account, approve the first real test post,
  provide the real support email. App Review package: `docs/META_APP_REVIEW.md`.
- `INSTAGRAM_ACCESS_TOKEN` in `backend/.env` is not referenced by any code;
  revoking it in Meta is recommended (owner decision).

## Real data safety

- Verified backups of the real local database:
  `backend/data/backups/content_flow-20261116-141501-before-sqlalchemy.sqlite3`,
  `backend/data/backups/content_flow-20261117-130959-before-upgrade.sqlite3`.
- 17 Nov 2026: real local database migrated `0001_baseline` → `0005_analytics_cache`
  (owner-approved). Integrity check ok; users, workspaces, sessions, social
  account and assets unchanged; the 3 legacy scheduled posts are now drafts.
