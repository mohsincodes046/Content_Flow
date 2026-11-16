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
| Scheduling worker with retries | ✅ | Enable with `CONTENT_FLOW_PUBLISHER_ENABLED=true` |
| Analytics | ⏳ | |
| TikTok, LinkedIn | ⏳ | |

## External requirements (owner action needed)

- Confirm in the Render dashboard which branch (if any) Render deploys from,
  and set the Blueprint Path to `ContentFlow/render.yaml`.
- Approval before provisioning a paid PostgreSQL database.
- Approval before migrating the real local database to new schema versions.
  It is at `0001_baseline`; the code needs `0004_posts`, so the
  local API refuses to start until `python -m app.migrate upgrade` is run
  (it takes a verified backup first). Rehearsed successfully on a copy.

## Real data safety

- Verified backup of the real local database:
  `backend/data/backups/content_flow-20261116-141501-before-sqlalchemy.sqlite3`.
