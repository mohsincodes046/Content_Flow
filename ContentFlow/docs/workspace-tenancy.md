# Workspace multi-tenancy — final design (Task 1.7)

Status: **design approved in principle; awaiting final review before implementation
and before any migration of real data.**

## Goals (from the approval)

- Exactly **one owner** per workspace.
- **Admin** manages workspace members and settings.
- **Editor** creates and manages content and schedules.
- **Client** can only view content assigned to them and approve, reject or request
  changes.
- **Strict workspace-level isolation**: no data crosses workspaces.
- **Existing users and data are preserved.**

## Model

- A **workspace** is one business or client brand. All content, schedules,
  connected social accounts and quotas belong to a workspace.
- A **user** can belong to many workspaces through **memberships**. Agency staff
  are members of many client workspaces; a client user is usually a member of one.
- Users appear on content only as `created_by_user_id`. Removing a person never
  deletes a workspace's content.

## Schema changes (migration `0002_workspace_tenancy`)

```sql
-- workspaces: existing table
ALTER TABLE workspaces ADD created_by_user_id TEXT NULL REFERENCES users(id) ON DELETE SET NULL;

-- memberships: existing table, wider role list
memberships (
  user_id            TEXT NOT NULL REFERENCES users(id)      ON DELETE CASCADE,
  workspace_id       TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  role               TEXT NOT NULL CHECK (role IN ('owner','admin','editor','client')),
  invited_by_user_id TEXT NULL REFERENCES users(id) ON DELETE SET NULL,
  created_at         TEXT NOT NULL,
  PRIMARY KEY (user_id, workspace_id)
);
CREATE UNIQUE INDEX memberships_one_owner ON memberships(workspace_id) WHERE role = 'owner';
CREATE INDEX memberships_workspace_idx ON memberships(workspace_id);

-- invitations: new
invitations (
  id                  TEXT PRIMARY KEY,
  workspace_id        TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  email               TEXT NOT NULL,              -- stored lowercased
  role                TEXT NOT NULL CHECK (role IN ('admin','editor','client')),
  token_hash          TEXT NOT NULL UNIQUE,       -- SHA-256 of a random token, like sessions
  invited_by_user_id  TEXT NULL REFERENCES users(id) ON DELETE SET NULL,
  created_at          TEXT NOT NULL,
  expires_at          TEXT NOT NULL,              -- 7 days
  accepted_at         TEXT NULL,
  accepted_by_user_id TEXT NULL REFERENCES users(id) ON DELETE SET NULL,
  revoked_at          TEXT NULL
);
CREATE UNIQUE INDEX invitations_one_open ON invitations(workspace_id, email)
  WHERE accepted_at IS NULL AND revoked_at IS NULL;

-- sessions: which workspace the browser is working in
ALTER TABLE sessions ADD active_workspace_id TEXT NULL REFERENCES workspaces(id) ON DELETE SET NULL;

-- workspace-owned tables: submissions, assets, scheduled_posts, social_accounts, oauth_states
--   + workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE
--   user_id -> created_by_user_id, ON DELETE SET NULL (was CASCADE)
-- social_accounts: UNIQUE (workspace_id, platform, account_id)    (was user_id, ...)
-- new indexes: scheduled_posts(workspace_id, scheduled_date, scheduled_time),
--              submissions(workspace_id, created_at), assets(workspace_id),
--              social_accounts(workspace_id, platform)

-- audit_log: new (who did what, per workspace)
audit_log (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  actor_user_id TEXT NULL REFERENCES users(id) ON DELETE SET NULL,
  action TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NULL,
  created_at TEXT NOT NULL, details_json TEXT NULL
);
```

AI quotas are counted per workspace (`rate_limit_events.subject = workspace_id`).

## Permissions

| Capability | Owner | Admin | Editor | Client |
|---|:-:|:-:|:-:|:-:|
| Delete workspace, transfer ownership (and billing, later) | ✅ | – | – | – |
| Rename workspace, workspace settings | ✅ | ✅ | – | – |
| Invite, remove and change roles of members (never the owner) | ✅ | ✅ | – | – |
| Connect and disconnect social accounts | ✅ | ✅ | – | – |
| Upload media, create and edit content, use AI captions | ✅ | ✅ | ✅ | – |
| Schedule, reschedule, delete and publish posts | ✅ | ✅ | ✅ | – |
| View all content, schedule, submissions, connected accounts | ✅ | ✅ | ✅ | – |
| View member list | ✅ | ✅ | ✅ | – |
| View content **assigned** to them | ✅ | ✅ | ✅ | ✅ |
| Approve, reject or request changes on assigned content (Phase 4) | ✅ | ✅ | – | ✅ |

A client gets no write access to anything except their review decisions.
"Assigned" is defined in *Open questions* below; until approvals exist
(Phase 4), clients see the workspace calendar read-only.

## How every request is scoped

1. `get_current_user` resolves the session as today.
2. A new dependency, `workspace_context`, reads `sessions.active_workspace_id`,
   **re-checks the membership on every request**, and yields
   `(user, workspace_id, role)`. Removing a member takes effect on their next request.
3. `require_role("owner", "admin", ...)` guards each endpoint.
4. Every query on a workspace-owned table filters on `workspace_id`. Objects in
   another workspace return **404**, never 403, so their existence is not revealed.
5. The publisher loads the page token by `(social_account_id, workspace_id)` of the post.

New endpoints: `GET /api/workspaces`, `POST /api/workspaces`,
`POST /api/workspaces/{id}/switch`, `GET /api/workspaces/current/members`,
`PATCH`/`DELETE /api/workspaces/current/members/{user_id}`,
`POST`/`DELETE /api/workspaces/current/invitations`,
`POST /api/invitations/accept`, `POST /api/workspaces/current/transfer-ownership`.
`GET /api/auth/me` adds the active workspace, the user's role and the workspace list.

## Migrating existing data

Precondition, checked first: **every user has exactly one membership, with role
`owner`.** If not, the migration aborts before changing anything.

1. `python -m app.migrate upgrade` takes a verified backup (SQLite), or a Render
   backup plus `pg_dump` (PostgreSQL).
2. Add the new columns as nullable.
3. Backfill: each row's `workspace_id` = its creator's owner workspace; each
   session's `active_workspace_id` = its user's workspace; each membership gets
   `created_at` = the user's `created_at`; each workspace gets `created_by_user_id`.
4. Rebuild the tables with `NOT NULL`, the new foreign keys, constraints and
   indexes. SQLite uses Alembic batch mode (copy to a new table); PostgreSQL
   uses `ALTER TABLE`.
5. Verify in the same transaction: row counts unchanged for every table, zero
   rows with a NULL `workspace_id`, exactly one owner per workspace. Any failure
   rolls everything back.
6. Rollback after commit: restore the backup (`downgrade` is also implemented
   and tested, but the backup is the authoritative rollback).

Existing users keep their passwords, sessions, workspace, posts, uploads and
connected Facebook Page.

## Tests (to be written with the implementation)

**Isolation**
- For posts, submissions, assets, social accounts, invitations and AI usage:
  a member of workspace B gets 404 for workspace A's IDs on list, read, update
  and delete.
- Route guard: a test enumerates every registered API route and fails if a
  non-public route does not depend on `workspace_context`.
- A post cannot target a Facebook Page or asset from another workspace.
- The publisher only uses the token of the post's own workspace.
- AI quota is counted per workspace, not per user.

**Roles**
- Each role × each endpoint in the permission table is allowed or denied as listed.
- Client can view only assigned content and cannot upload, schedule, connect
  accounts, use AI or see the member list.
- Nobody can remove or demote the owner; there is always exactly one owner
  (also enforced by the unique index).
- Ownership transfer is atomic: the old owner becomes admin.

**Membership lifecycle**
- A removed member loses access on the next request, even with a valid session.
- Switching to a workspace you are not a member of returns 404.
- Invitations: single use, expire after 7 days, bound to the invited email,
  revocable; an open invitation cannot be duplicated.

**Migration (on SQLite and PostgreSQL)**
- A database with real-shaped data upgrades with every row assigned to the
  right workspace, counts unchanged, sessions still valid.
- The precondition check aborts on a user with no or several memberships.
- Downgrade restores the previous schema with data intact.
- The rehearsal tool reports identical data after migrating a copy of real data.

## Open questions

1. **What does "assigned content" mean for a client?** Proposed: a client sees
   items that have been **sent to them for review** (Phase 4 adds a review
   status and an optional reviewer per item), plus anything they already
   approved or rejected. Alternative: a client sees everything in their
   workspace read-only.
2. **Do admins also have all editor rights** (create and schedule content)?
   Proposed: yes, as shown in the table.
3. **May an admin connect and disconnect social accounts?** Proposed: yes,
   treated as workspace settings.
