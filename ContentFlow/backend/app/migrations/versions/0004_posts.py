"""Posts: drafts, platform versions, approvals, scheduling and publishing history.

Revision ID: 0004_posts
Revises: 0003_social_connections
Create Date: 2026-11-16

Additive. Existing `scheduled_posts` rows are copied into the new tables and the
old table is kept unchanged as an archive (nothing reads it any more, so a copied
post can never be published twice). Copy rules:
  * Facebook post with an image and a Page   -> post + target for that Page,
    status scheduled / published / failed as before
  * anything else (no connected account)     -> draft keeping its date and
    planned platforms ("calendar only", as it was before)
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time, timedelta, timezone

import sqlalchemy as sa
from alembic import op

revision = "0004_posts"
down_revision = "0003_social_connections"
branch_labels = None
depends_on = None

POST_STATUSES = (
    "draft", "in_review", "changes_requested", "approved", "rejected",
    "scheduled", "publishing", "published", "partially_published", "failed",
)
TARGET_STATUSES = ("pending", "queued", "publishing", "published", "failed", "cancelled")


def upgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("assets") as batch:
        batch.add_column(sa.Column("width", sa.Integer))
        batch.add_column(sa.Column("height", sa.Integer))

    op.create_table(
        "posts",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.Text, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("title", sa.Text, nullable=False, server_default=""),
        sa.Column("caption", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("reviewer_user_id", sa.Text, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("scheduled_at", sa.Text),        # UTC ISO-8601
        sa.Column("timezone", sa.Text),            # IANA name chosen by the person scheduling
        sa.Column("planned_platforms_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("legacy_scheduled_post_id", sa.Text, unique=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.Column("submitted_at", sa.Text),
        sa.Column("decided_at", sa.Text),
        sa.CheckConstraint(f"status IN {POST_STATUSES}", name="posts_status_check"),
    )
    op.create_index("posts_workspace_schedule_idx", "posts", ["workspace_id", "scheduled_at"])
    op.create_index("posts_workspace_status_idx", "posts", ["workspace_id", "status"])
    op.create_index("posts_reviewer_idx", "posts", ["reviewer_user_id", "status"])

    op.create_table(
        "post_media",
        sa.Column("post_id", sa.Text, sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("asset_id", sa.Text, sa.ForeignKey("assets.id"), nullable=False),
        sa.PrimaryKeyConstraint("post_id", "position"),
    )
    op.create_index("post_media_asset_idx", "post_media", ["asset_id"])

    op.create_table(
        "post_targets",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("post_id", sa.Text, sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("social_account_id", sa.Text, sa.ForeignKey("social_accounts.id", ondelete="SET NULL")),
        sa.Column("platform", sa.Text, nullable=False),
        sa.Column("account_name", sa.Text, nullable=False, server_default=""),  # kept if the account is removed
        sa.Column("caption_override", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.Text),
        sa.Column("claimed_at", sa.Text),
        sa.Column("last_error", sa.Text),
        sa.Column("external_id", sa.Text),
        sa.Column("external_url", sa.Text),
        sa.Column("published_at", sa.Text),
        sa.CheckConstraint(f"status IN {TARGET_STATUSES}", name="post_targets_status_check"),
        sa.UniqueConstraint("post_id", "social_account_id", name="post_targets_post_account_key"),
    )
    op.create_index("post_targets_due_idx", "post_targets", ["status", "next_attempt_at"])

    op.create_table(
        "post_events",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("post_id", sa.Text, sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", sa.Text, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("seq", sa.Integer, nullable=False),   # order within the post (clock ticks can tie)
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("message", sa.Text),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.UniqueConstraint("post_id", "seq", name="post_events_post_seq_key"),
    )

    op.create_table(
        "publish_attempts",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("target_id", sa.Text, sa.ForeignKey("post_targets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.Text, nullable=False),
        sa.Column("finished_at", sa.Text),
        sa.Column("outcome", sa.Text, nullable=False),   # published | retry | failed
        sa.Column("error", sa.Text),
        sa.Column("external_id", sa.Text),
    )
    op.create_index("publish_attempts_target_idx", "publish_attempts", ["target_id", "started_at"])

    _copy_legacy_scheduled_posts(bind)


def _copy_legacy_scheduled_posts(bind: sa.engine.Connection) -> None:
    rows = bind.execute(sa.text("SELECT * FROM scheduled_posts ORDER BY created_at")).mappings().all()
    for row in rows:
        local = datetime.combine(date.fromisoformat(row["scheduled_date"]), time.fromisoformat(row["scheduled_time"]))
        offset = timezone(timedelta(minutes=-(row["timezone_offset_minutes"] or 0)))
        scheduled_at = local.replace(tzinfo=offset).astimezone(timezone.utc).isoformat()
        platforms = json.loads(row["platforms_json"])
        account = None
        if row["facebook_account_id"] and row["asset_id"]:
            account = bind.execute(sa.text(
                "SELECT id, account_name FROM social_accounts WHERE id = :id AND workspace_id = :ws"),
                {"id": row["facebook_account_id"], "ws": row["workspace_id"]}).mappings().first()
        legacy_status = row["publish_status"]
        if account is not None:
            status = {"published": "published", "failed": "failed"}.get(legacy_status, "scheduled")
            if legacy_status == "publishing":
                status = "failed"  # interrupted mid-send before the upgrade; never resend automatically
        else:
            status = "draft"
        post_id = str(uuid.uuid4())
        planned = [p for p in platforms if account is None or p != "facebook"]
        bind.execute(sa.text(
            "INSERT INTO posts (id, workspace_id, created_by_user_id, title, caption, status, scheduled_at, timezone, "
            "planned_platforms_json, legacy_scheduled_post_id, created_at, updated_at) "
            "VALUES (:id, :ws, :by, :title, :caption, :status, :at, NULL, :planned, :legacy, :created, :created)"),
            {"id": post_id, "ws": row["workspace_id"], "by": row["user_id"], "title": row["media_name"],
             "caption": row["caption"], "status": status, "at": scheduled_at, "planned": json.dumps(planned),
             "legacy": row["id"], "created": row["created_at"]})
        if row["asset_id"]:
            bind.execute(sa.text("INSERT INTO post_media (post_id, position, asset_id) VALUES (:p, 0, :a)"),
                         {"p": post_id, "a": row["asset_id"]})
        if account is not None:
            target_status = {"scheduled": "queued", "published": "published"}.get(status, "failed")
            bind.execute(sa.text(
                "INSERT INTO post_targets (id, post_id, social_account_id, platform, account_name, status, last_error, "
                "external_id, published_at) VALUES (:id, :p, :acct, 'facebook', :name, :st, :err, :ext, :pub)"),
                {"id": str(uuid.uuid4()), "p": post_id, "acct": account["id"], "name": account["account_name"],
                 "st": target_status,
                 "err": row["publish_error"] or ("Interrupted while sending before an upgrade. Check the Page before retrying."
                                                 if legacy_status == "publishing" else None),
                 "ext": row["published_post_id"], "pub": row["created_at"] if status == "published" else None})
        bind.execute(sa.text(
            "INSERT INTO post_events (id, post_id, actor_user_id, seq, kind, message, created_at) "
            "VALUES (:id, :p, NULL, 1, 'imported', 'Imported from the previous scheduler.', :at)"),
            {"id": str(uuid.uuid4()), "p": post_id, "at": datetime.now(timezone.utc).isoformat()})
    copied = bind.execute(sa.text("SELECT COUNT(*) FROM posts WHERE legacy_scheduled_post_id IS NOT NULL")).scalar_one()
    if copied != len(rows):
        raise RuntimeError(f"Aborting: copied {copied} of {len(rows)} scheduled posts.")


def downgrade() -> None:
    raise NotImplementedError("Restore the verified backup taken by `python -m app.migrate upgrade`.")
