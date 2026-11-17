# Project status

Last updated: 2026-11-17 · Branch: `Mohsin`

## Legend
✅ done and tested · 🟡 in progress · ⏳ not started · 🔒 blocked on an external requirement

## Feature status

| Area | Status | Notes |
|---|---|---|
| Registration, login, sessions, password change | ✅ | Rate limited |
| Free-stack deployment (Koyeb + Neon + Cloudinary + Vercel) | 🟡 | Code + `backend/Dockerfile` + `docs/DEPLOY_FREE_STACK.md` ready; not deployed (owner approval) |
| AI captions (Gemini free) | ✅ | Verified live 17 Nov 2026; falls back to a lighter model when Gemini is busy |
| Cloudinary media storage | ✅ code / 🟡 live | Needs a real `CLOUDINARY_URL` (key + secret) to test live |
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
- Facebook + Instagram live verification (17 Nov 2026, real accounts):
  - Connected: Page "Daily Needs" (token valid, non-expiring, has `pages_manage_posts`)
    and Instagram professional "rajatalal17" linked to it.
  - Scheduled post (16:25 Asia/Karachi) published automatically by the background worker
    to Facebook (`…_122218749560770785`) and Instagram (`18422173327159664`), one attempt
    each; confirmed on Meta (`is_published`, permalink, caption, image).
  - Carousel / multi-photo (2 images) scheduled 23:21 Asia/Karachi: Facebook
    `…_122218783100770785`, Instagram carousel `18067017377639403`
    (instagram.com/p/Df2kA9pgc4p). Video scheduled 23:23: Facebook video
    `1476910607871615`, Instagram Reel `17955229992302760` (instagram.com/reel/Df2kcfLG6AG).
    All published by the background worker on the first attempt.
  - Analytics: Instagram account + post insights return real values. Facebook Page/post
    insights return empty data (Page has no followers yet and the token lacks
    `read_insights`) and show "Unavailable".
  - Owner to do: add `read_insights` to the app's use case, set
    `META_EXTRA_SCOPES=read_insights`, reconnect.
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
