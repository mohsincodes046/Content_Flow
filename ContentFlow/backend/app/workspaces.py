"""Workspace membership and invitation rules (docs/workspace-tenancy.md)."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from fastapi import HTTPException, status

from app.database import DatabaseConnection, Row, utc_now
from app.security import record_audit, token_digest

INVITATION_LIFETIME = timedelta(days=7)


def create_workspace(connection: DatabaseConnection, owner_user_id: str, name: str) -> str:
    workspace_id = str(uuid4())
    now = utc_now()
    connection.execute(
        "INSERT INTO workspaces (id, name, created_at, created_by_user_id) VALUES (?, ?, ?, ?)",
        (workspace_id, name, now, owner_user_id),
    )
    connection.execute(
        "INSERT INTO memberships (user_id, workspace_id, role, created_at) VALUES (?, ?, 'owner', ?)",
        (owner_user_id, workspace_id, now),
    )
    record_audit(connection, workspace_id, owner_user_id, "workspace.created", "workspace", workspace_id)
    return workspace_id


def membership(connection: DatabaseConnection, workspace_id: str, user_id: str) -> Optional[Row]:
    return connection.execute(
        "SELECT user_id, workspace_id, role, created_at FROM memberships WHERE workspace_id = ? AND user_id = ?",
        (workspace_id, user_id),
    ).fetchone()


def new_invitation_token() -> str:
    return secrets.token_urlsafe(32)


def open_invitation(connection: DatabaseConnection, token: str) -> Row:
    """The pending, unexpired invitation for `token`, or a 404 that reveals nothing."""
    row = connection.execute(
        """
        SELECT invitations.*, workspaces.name AS workspace_name
        FROM invitations JOIN workspaces ON workspaces.id = invitations.workspace_id
        WHERE invitations.token_hash = ? AND invitations.accepted_at IS NULL
          AND invitations.revoked_at IS NULL AND invitations.expires_at > ?
        """,
        (token_digest(token), utc_now()),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This invitation is invalid, expired or already used.",
        )
    return row


def accept_invitation(connection: DatabaseConnection, token: str, user_id: str, user_email: str) -> str:
    """Add the user to the invited workspace with the invited role; returns the workspace id."""
    invitation = open_invitation(connection, token)
    if invitation["email"] != user_email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invitation was sent to a different email address.",
        )
    existing = membership(connection, invitation["workspace_id"], user_id)
    if existing is None:
        connection.execute(
            """
            INSERT INTO memberships (user_id, workspace_id, role, invited_by_user_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, invitation["workspace_id"], invitation["role"], invitation["invited_by_user_id"], utc_now()),
        )
    connection.execute(
        "UPDATE invitations SET accepted_at = ?, accepted_by_user_id = ? WHERE id = ?",
        (utc_now(), user_id, invitation["id"]),
    )
    record_audit(
        connection, invitation["workspace_id"], user_id, "invitation.accepted", "invitation", invitation["id"],
        {"role": invitation["role"], "already_member": existing is not None},
    )
    return invitation["workspace_id"]


def invitation_expiry() -> str:
    return (datetime.now(timezone.utc) + INVITATION_LIFETIME).isoformat()
