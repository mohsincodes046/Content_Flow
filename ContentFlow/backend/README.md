# Content-Flow API

The API receives content submissions and media for the Content-Flow frontend.
It stores submission records in SQLite and uploaded media in a local data folder.

## Run locally on Windows

From the repository root:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The backend automatically loads `backend\.env` when the app starts. Variables
already set in the process environment take precedence.

The API listens on `http://127.0.0.1:8000`. Interactive endpoint documentation
is available at `http://127.0.0.1:8000/docs`.

The frontend calls this local API by default. If the API runs at a different
address, copy `frontend\.env.example` to `frontend\.env.local`, set
`NEXT_PUBLIC_CONTENT_FLOW_API_URL` to that address, and restart the frontend.

Run the tests with `pip install -r requirements-dev.txt` and `python -m pytest`.

## Code layout and logging

| Module | Responsibility |
|---|---|
| `app/main.py` | App setup: lifespan, middleware, router registration |
| `app/config.py` | Environment loading, paths, settings helpers |
| `app/database.py` | SQLite connection and schema migrations |
| `app/schemas.py` | Request and response models |
| `app/security.py` | Sessions, token encryption, rate limiting |
| `app/publisher.py` | Background scheduled-post publisher |
| `app/ai.py` | AI provider calls |
| `app/social_oauth.py` | Meta OAuth and Graph API calls |
| `app/observability.py` | Logging setup and request IDs |
| `app/routers/` | HTTP endpoints, one module per area |

Application logs go to stderr with a request ID on every line. Set
`CONTENT_FLOW_LOG_LEVEL` (default `INFO`) to change the level. Every response
carries an `X-Request-ID` header, and unexpected errors return a JSON 500 that
includes the same ID, so a user-reported error can be matched to the log.

## Database and migrations

The API uses SQLite (`backend\data\content_flow.sqlite3`) unless
`CONTENT_FLOW_DATABASE_URL` is set to a PostgreSQL URL. Both run the same code
and the same Alembic migrations (`app/migrations/versions/`). Timestamps are
stored as ISO-8601 text on both, so queries behave identically.

```powershell
python -m app.migrate status    # current revision vs. what the code needs
python -m app.migrate backup    # SQLite: verified online backup to data\backups\
python -m app.migrate upgrade   # SQLite: backs up first, then upgrades
```

On startup the API creates the schema in an empty database and stamps a
pre-Alembic SQLite database as the baseline (additive only). If the database
is behind the code, the API refuses to start rather than migrating unattended;
run `python -m app.migrate upgrade`, or set `CONTENT_FLOW_AUTO_MIGRATE=true`
only where unattended migration is acceptable.

Run the test suite against PostgreSQL by pointing
`CONTENT_FLOW_TEST_POSTGRES_URL` at a disposable database (its `public`
schema is dropped before every test). CI runs both SQLite and PostgreSQL.

### Moving data between databases

`python -m app.transfer` copies every table and then verifies each one by row
count and a SHA-256 over all row contents. It opens a SQLite source read-only,
refuses a target that is not empty or not at the same revision, writes in one
transaction, and never overwrites an existing SQLite file.

```powershell
python -m app.transfer --source sqlite:///data/content_flow.sqlite3 --target <postgres-url> --dry-run
python -m app.transfer --source sqlite:///data/content_flow.sqlite3 --target <postgres-url>
python -m app.transfer --source <postgres-url> --target sqlite:///data/rollback.sqlite3   # rollback copy
python -m app.transfer --source <a> --target <b> --verify-only
```

Production cutover (requires approval; see the migration plan):
1. Turn the publisher off; stop writes.
2. `python -m app.migrate backup` and keep an off-Render copy of the file.
3. Transfer with `--dry-run`, then for real; every table must report identical.
4. Set `CONTENT_FLOW_DATABASE_URL`, redeploy, smoke-test, re-enable the publisher.
5. Rollback before new writes: unset the URL. After writes: transfer back to a new SQLite file.

## AI captions

The authenticated `POST /api/ai/captions` endpoint generates a separate caption
and hashtag list for each selected platform. It supports Claude (default),
OpenAI, and Gemini. Copy `.env.example` to `.env` in this directory, set the key
for the provider you choose, then start the API with:

```powershell
uvicorn app.main:app --env-file .env --reload
```

Keep provider keys only in the backend environment. Never put them in frontend
variables or commit the `.env` file. Without a configured key, the endpoint
returns `503` and the captions page explains that setup is needed.

For Claude, set `CONTENT_FLOW_AI_PROVIDER=claude` and `ANTHROPIC_API_KEY`. For
OpenAI, set `CONTENT_FLOW_AI_PROVIDER=openai` and `OPENAI_API_KEY`. For Gemini,
set `CONTENT_FLOW_AI_PROVIDER=gemini` and `GEMINI_API_KEY`. Model names can be
changed with `CLAUDE_MODEL`, `OPENAI_MODEL`, or `GEMINI_MODEL`.

## Meta account connection

Meta OAuth can connect Facebook Pages and Instagram professional accounts
linked to those Pages. Set `META_APP_ID`, `META_APP_SECRET`, and
`CONTENT_FLOW_TOKEN_ENCRYPTION_KEY` in `backend\.env` (or the backend service
environment), then restart the backend. The encryption key must be a valid
Fernet key; generate one locally with:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

For local development, expose the backend (`127.0.0.1:8000`) through an HTTPS
tunnel such as ngrok and set `CONTENT_FLOW_API_PUBLIC_URL` to its HTTPS URL. The
frontend can continue using `http://localhost:3000`; Meta redirects to the HTTPS
backend callback, which then returns to the local frontend. Meta OAuth will not
start if the configured callback base URL is plain HTTP.

Register the exact callback URL, including the tunnel host, in the Meta
Developer app's Facebook Login settings under **Valid OAuth Redirect URIs**:

```text
https://YOUR-HTTPS-TUNNEL/api/social/oauth/meta/callback
https://contentflow-api.onrender.com/api/social/oauth/meta/callback
```

For a local ngrok session, replace `YOUR-HTTPS-TUNNEL` with the HTTPS hostname
shown by ngrok. If that hostname changes, update both the backend environment
and Meta's allowed redirect URI, then restart the backend.

For Page and linked Instagram access, configure Facebook Login and request
`pages_show_list`, `pages_read_engagement`, `pages_manage_posts`,
`instagram_basic`, and `instagram_content_publish`. Meta app review/Advanced
Access may be required for accounts outside the app's roles. Instagram must be a
professional account linked to a Facebook Page. Keep the App Secret and token
encryption key in backend-only environment settings.

Facebook Page photo publishing is supported for scheduled posts that have an
uploaded image and an explicitly selected connected Page. To enable the
background publisher for local development, set
`CONTENT_FLOW_PUBLISHER_ENABLED=true` in `backend\.env`, then restart the API.
Keep the API process running; it checks for due posts every
`CONTENT_FLOW_PUBLISHER_INTERVAL_SECONDS` (60 seconds by default). Keep the
publisher disabled until you are ready for scheduled Facebook posts to be
published publicly. The current publisher supports images, not videos, and
does not publish to Instagram or other platforms.

The Meta connection endpoints are `GET /api/social/providers`,
`GET /api/social/oauth/meta/start`,
`GET /api/social/oauth/meta/callback`, and
`DELETE /api/social/accounts/{account_id}`. OAuth state is short-lived and
single-use; provider tokens are encrypted at rest and never included in API
responses.

## Render deployment foundation

The repository-root `render.yaml` defines the Next.js web service and FastAPI
web service. Connect the Git repository in Render and create a Blueprint from
that file. The API uses a persistent disk for its current SQLite database and
uploads, so its configured `0.5c-512mb` plan and disk require a paid Render
service. Keep it at one instance; SQLite and local disk are not shared across
instances.

Add `ANTHROPIC_API_KEY` as a secret in Render's API service settings. The
Blueprint currently expects the frontend URL
`https://contentflow-web.onrender.com`; if Render assigns a different frontend
URL, update `CONTENT_FLOW_ALLOWED_ORIGINS` in the API service and redeploy it.
The API URL is passed to the frontend by the Blueprint.

The scheduler uses this API process and local SQLite/database storage, so keep
the Render API at one instance. If deploying publicly, enable the publisher
only after reviewing storage persistence, Meta permissions, and the publishing
behavior for the target Page.

Set `CONTENT_FLOW_DATA_DIR` to move the SQLite database and uploads out of
`backend\data`. Set `CONTENT_FLOW_ALLOWED_ORIGINS` to a comma-separated list
of frontend origins when running outside the local development defaults.

## Initial endpoints

- `GET /api/health` — check that the API is running.
- `POST /api/auth/register` — create a user and workspace; starts a session.
- `POST /api/auth/login` — start a session with email and password.
- `GET /api/auth/me` — return the signed-in user and workspace.
- `POST /api/auth/change-password` — verify the current password and set a new
  Content-Flow password (8–128 characters); other active sessions are revoked.
- `POST /api/auth/logout` — revoke the current session.
- `GET /api/scheduled-posts` — list the signed-in user's scheduled-post records.
- `POST /api/scheduled-posts` — save a batch of scheduled-post details.
- `PATCH /api/scheduled-posts/{id}` — change a post's scheduled date.
- `DELETE /api/scheduled-posts/{id}` — remove a scheduled post.
- `POST /api/assets` — upload one image or video (up to 50 MB).
- `POST /api/ai/captions` — generate platform-specific captions and hashtags
  with the configured Claude, OpenAI, or Gemini provider.
- `GET /api/social/providers` — show configured Meta OAuth status and the
  signed-in workspace's connected accounts.
- `GET /api/social/oauth/meta/start` and
  `GET /api/social/oauth/meta/callback` — authorize Facebook Pages and linked
  Instagram professional accounts through Meta.
- `DELETE /api/social/accounts/{account_id}` — disconnect one owned account.
- `POST /api/submissions` — save campaign instructions, target audience,
  language, selected platforms, and uploaded asset IDs.
- `GET /api/submissions` — list recent submissions.
- `GET /api/submissions/{id}` — read one submission.

Upload assets first, then send their returned IDs as `asset_ids` when creating
a submission. Accepted platforms are `instagram`, `facebook`, `linkedin`,
`youtube`, and `tiktok`.

New accounts get a private workspace. Passwords are hashed with Argon2, and
signup requires a Content-Flow password of at least 8 characters (separate
from your email password). The authenticated password-change endpoint also
requires the current Content-Flow password and keeps the current session
active. Sessions use random HttpOnly cookies whose tokens are stored hashed,
and submissions/uploads are scoped to the signed-in account. Signup and login
are available to anyone who can reach this local development server.

Scheduled posts persist their uploaded media, caption, local date and time,
selected platforms, and selected Facebook Page. With the publisher enabled,
Facebook Page image posts are sent when due; their status is visible in the
schedule API. Other platforms remain calendar-only. TikTok, LinkedIn, and
YouTube OAuth/publishing, Instagram publishing, Facebook video publishing, and
automatic retries after publishing failures are not implemented. AI captions
require a configured provider key.

For HTTPS deployment, set `CONTENT_FLOW_COOKIE_SECURE=true` and configure
`CONTENT_FLOW_ALLOWED_ORIGINS` for the exact frontend origin. Before a public
deployment, add email verification, password recovery, abuse/rate limiting,
backups, and a reviewed production hosting configuration. Human approval
actions and social publishing are not connected yet. Do not expose this development service publicly or upload private
institute/student material until production controls are configured.
