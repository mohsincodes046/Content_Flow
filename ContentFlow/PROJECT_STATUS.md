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
| Workspaces, roles, client management | ⏳ | Design approved (`docs/workspace-tenancy.md`) |
| Meta connection: Pages, Instagram, reconnect | 🟡 | OAuth and discovery exist; selection/reconnect pending |
| Content drafts, platform versions, media library | ⏳ | |
| Client approval workflow | ⏳ | |
| Facebook and Instagram publishing | 🟡 | Scheduled Facebook Page images only |
| Scheduling worker with retries | 🟡 | Worker exists; retries pending |
| Analytics | ⏳ | |
| TikTok, LinkedIn | ⏳ | |

## External requirements (owner action needed)

- Confirm in the Render dashboard which branch (if any) Render deploys from,
  and set the Blueprint Path to `ContentFlow/render.yaml`.
- Approval before provisioning a paid PostgreSQL database.
- Approval before migrating the real local database to new schema versions.

## Real data safety

- Verified backup of the real local database:
  `backend/data/backups/content_flow-20261116-141501-before-sqlalchemy.sqlite3`.
