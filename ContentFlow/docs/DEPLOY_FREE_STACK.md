# Deploying Content Flow on the $0 stack

| Piece | Service (free plan) | What it holds |
|---|---|---|
| API + publisher | **Koyeb** (1 free instance, 512 MB, 0.1 vCPU) | `ContentFlow/backend`, built from `backend/Dockerfile` |
| Database | **Neon** PostgreSQL (free plan; scales to zero when idle) | all application data |
| Media | **Cloudinary** (25 credits / month) | uploaded images and videos |
| Web app | **Vercel** Hobby | `ContentFlow/frontend`; proxies `/api/*` to Koyeb |
| Keep-alive | **cron-job.org** | pings the API so Koyeb does not sleep |

Do the steps in this order. Never paste secrets into chat, commits or screenshots.

## 0. Know the limits first

- **Koyeb free sleeps.** Koyeb scales a free service to zero after 1 hour without
  traffic. While asleep the publisher does not run, so scheduled posts would be late.
  Step 6 (cron ping every 10 minutes) prevents this.
- **No disk on Koyeb.** Everything that must survive a restart lives in Neon and
  Cloudinary. `CONTENT_FLOW_DATA_DIR=/tmp/contentflow` is only a download cache.
- **Vercel body limit (4.5 MB).** The browser uploads media straight to Cloudinary,
  so files never pass through Vercel. Cloudinary must therefore be configured.
- **Neon compute hours.** Neon free suspends the database after 5 minutes without
  queries, and its monthly compute allowance is far below "awake all month". The
  publisher therefore does not poll every minute: it sleeps until the next due post
  (or retry), wakes immediately when any request changes data, and otherwise checks
  once per `CONTENT_FLOW_PUBLISHER_IDLE_SECONDS` (default 1800). `/api/health` does
  not touch the database, so the keep-alive ping does not wake Neon.
- **One worker.** The publisher runs inside the API process; keep one instance and
  one worker (the Dockerfile does this). Do not scale Koyeb above 1 instance.

## 1. Neon (database)

1. Create a project (region close to the Koyeb region, e.g. Frankfurt / `aws-eu-central-1`).
2. **Connection details** → copy the connection string (`postgresql://…?sslmode=require…`).
   This is `CONTENT_FLOW_DATABASE_URL`. The app converts `postgresql://` to psycopg 3
   itself; keep the query parameters.
3. Nothing else: on first start the API sees an empty database and creates the schema
   at the latest migration.

Moving the existing local SQLite data (users, connected accounts, posts) into Neon is a
separate, owner-approved step; see section 8.

## 2. Cloudinary (media)

Console → **Settings → API Keys** (or the dashboard's "API environment variable").
`CLOUDINARY_URL` has the shape `cloudinary://API_KEY:API_SECRET@CLOUD_NAME`, with the
real key and secret in place of the placeholders and no `<` `>`.

## 3. Koyeb (API)

1. **Create Web Service → GitHub** → repository `Content_Flow`, branch to deploy.
2. **Builder: Dockerfile.** Work directory: `ContentFlow/backend`
   (Dockerfile location `Dockerfile`).
3. **Instance:** Free. **Region:** Frankfurt (closest to Pakistan) or Washington.
4. **Port:** 8000, protocol HTTP, public. **Health check:** HTTP `GET /api/health`.
5. **Environment variables** (use Koyeb *Secrets* for the secret ones):

| Variable | Value | Secret |
|---|---|---|
| `CONTENT_FLOW_DATABASE_URL` | Neon connection string | yes |
| `CLOUDINARY_URL` | Cloudinary URL | yes |
| `CONTENT_FLOW_TOKEN_ENCRYPTION_KEY` | Same key as local if you move data (section 8); otherwise a new one | yes |
| `META_APP_ID` | Meta app ID | – |
| `META_APP_SECRET` | Meta app secret | yes |
| `META_GRAPH_VERSION` | same as local | – |
| `CONTENT_FLOW_AI_PROVIDER` | `gemini` | – |
| `GEMINI_API_KEY` | Google AI Studio key | yes |
| `CONTENT_FLOW_API_PUBLIC_URL` | `https://<your-app>.vercel.app` (the API is reached through Vercel's `/api` proxy) | – |
| `CONTENT_FLOW_FRONTEND_URL` | `https://<your-app>.vercel.app` | – |
| `CONTENT_FLOW_ALLOWED_ORIGINS` | `https://<your-app>.vercel.app` | – |
| `CONTENT_FLOW_COOKIE_SECURE` | `true` | – |
| `CONTENT_FLOW_PUBLISHER_ENABLED` | `true` | – |
| `CONTENT_FLOW_TRUSTED_PROXY_HOPS` | `2` (Vercel + Koyeb each add one `X-Forwarded-For` entry). Check after deploy, see section 7 | – |

   Optional: `GEMINI_MODEL`, `GEMINI_FALLBACK_MODELS`, `META_EXTRA_SCOPES`,
   `META_WEBHOOK_VERIFY_TOKEN`, the `CONTENT_FLOW_*_LIMIT` values.
6. Deploy. Note the public URL `https://<service>-<org>.koyeb.app`;
   `https://…koyeb.app/api/health` must return `{"status":"ok"}`.

## 4. Vercel (web app)

1. **Add New → Project** → import `Content_Flow`. **Root Directory:** `ContentFlow/frontend`.
   Framework: Next.js (auto-detected).
2. Environment variables (Production):
   - `NEXT_PUBLIC_CONTENT_FLOW_API_URL` = `/`: the browser calls the same site.
   - `CONTENT_FLOW_API_INTERNAL_URL` = `https://<service>-<org>.koyeb.app`: Next.js rewrites
     `/api/*` there, so the session cookie stays first-party on the Vercel domain.
3. Deploy, then put the final `https://<your-app>.vercel.app` into the three Koyeb
   variables above and redeploy Koyeb.

## 5. Meta app dashboard

Replace the ngrok URLs with the Vercel domain:
- Valid OAuth Redirect URI: `https://<your-app>.vercel.app/api/social/oauth/meta/callback`
- Deauthorize: `https://<your-app>.vercel.app/api/social/meta/deauthorize`
- Data deletion: `https://<your-app>.vercel.app/api/social/meta/data-deletion`
- Privacy / Terms / Data deletion instructions: `https://<your-app>.vercel.app/privacy`,
  `/terms`, `/data-deletion`. App domain: `<your-app>.vercel.app`.

## 6. Keep-alive (cron-job.org)

Create a cron job: URL `https://<service>-<org>.koyeb.app/api/health`, every **10 minutes**,
method GET. Ping Koyeb directly (not through Vercel) so it is cheap and always reaches
the instance. Turn on failure notifications to get an email if the API goes down.

## 7. Check after deploy

- Register / log in on the Vercel URL; Settings shows the workspace.
- Upload an image: it must appear in Cloudinary under `contentflow/<workspace-id>/`.
- Connect Facebook & Instagram (OAuth round trip through the Vercel domain).
- Schedule a test post a few minutes ahead (owner-approved content only) and see it publish.
- AI captions: **Write with AI** returns drafts.
- Rate-limit IP: with `CONTENT_FLOW_TRUSTED_PROXY_HOPS=2`, the logs of a login request
  should show your own public IP, not a Vercel or Koyeb address. If they don't, adjust
  the value (1 if only Koyeb adds an entry).

## 8. Moving the local data into Neon (optional, owner approval required)

Only after Neon has the schema (first Koyeb start) and **before** anyone uses production:

```
python -m app.migrate status                     # local must be at head
python -m app.transfer --source sqlite:///data/content_flow.sqlite3 --target "<neon url>" --dry-run
python -m app.transfer --source sqlite:///data/content_flow.sqlite3 --target "<neon url>"
```

The tool refuses a non-empty target, copies in one transaction and verifies every table
by checksum. Social tokens are encrypted, so Koyeb needs the **same**
`CONTENT_FLOW_TOKEN_ENCRYPTION_KEY` as local. Media uploaded locally before Cloudinary
stays on this computer, so those old library items will not open in production. Re-upload
any you still need. Starting fresh (register again, reconnect Meta) avoids all of this.
