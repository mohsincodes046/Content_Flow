"""Workspaces, members and invitations."""
from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.config import public_frontend_url
from app.database import Row, connect_database, utc_now
from app.schemas import (
    InvitationAccept,
    InvitationCreate,
    InvitationPreview,
    InvitationResponse,
    MemberResponse,
    MemberRoleUpdate,
    OwnershipTransfer,
    SessionResponse,
    WorkspaceCreate,
    WorkspaceRename,
    WorkspaceSummary,
)
from app.security import (
    get_current_user,
    record_audit,
    require_content_role,
    require_manager,
    require_roles,
    session_response,
    token_digest,
    user_workspaces,
)
from app.workspaces import (
    accept_invitation,
    create_workspace,
    invitation_expiry,
    membership,
    new_invitation_token,
    open_invitation,
)

router = APIRouter()
require_owner = require_roles("owner")


def _switch(session_id: str, workspace_id: str) -> None:
    with connect_database() as connection:
        connection.execute("UPDATE sessions SET active_workspace_id = ? WHERE id = ?", (workspace_id, session_id))


@router.get("/api/workspaces", response_model=list[WorkspaceSummary])
def list_my_workspaces(user: Annotated[Row, Depends(get_current_user)]) -> list[WorkspaceSummary]:
    with connect_database() as connection:
        return [WorkspaceSummary(**dict(row)) for row in user_workspaces(connection, user["id"])]


@router.post("/api/workspaces", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_new_workspace(
    payload: WorkspaceCreate, user: Annotated[Row, Depends(get_current_user)]
) -> SessionResponse:
    with connect_database() as connection:
        workspace_id = create_workspace(connection, user["id"], payload.name)
    _switch(user["session_id"], workspace_id)
    return session_response({**user, "workspace_id": workspace_id, "workspace_name": payload.name, "role": "owner"})


@router.post("/api/workspaces/{workspace_id}/switch", response_model=SessionResponse)
def switch_workspace(workspace_id: str, user: Annotated[Row, Depends(get_current_user)]) -> SessionResponse:
    with connect_database() as connection:
        member = membership(connection, workspace_id, user["id"])
    if member is None:
        # 404, not 403: do not reveal whether another workspace exists.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    _switch(user["session_id"], workspace_id)
    with connect_database() as connection:
        name = connection.execute("SELECT name FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()["name"]
    return session_response({**user, "workspace_id": workspace_id, "workspace_name": name, "role": member["role"]})


@router.patch("/api/workspaces/current", response_model=WorkspaceSummary)
def rename_workspace(payload: WorkspaceRename, user: Annotated[Row, Depends(require_manager)]) -> WorkspaceSummary:
    with connect_database() as connection:
        connection.execute("UPDATE workspaces SET name = ? WHERE id = ?", (payload.name, user["workspace_id"]))
        record_audit(connection, user["workspace_id"], user["id"], "workspace.renamed", "workspace",
                     user["workspace_id"], {"name": payload.name})
    return WorkspaceSummary(id=user["workspace_id"], name=payload.name, role=user["role"])


@router.get("/api/workspaces/current/members", response_model=list[MemberResponse])
def list_members(user: Annotated[Row, Depends(require_content_role)]) -> list[MemberResponse]:
    with connect_database() as connection:
        rows = connection.execute(
            """
            SELECT users.id AS user_id, users.full_name, users.email, memberships.role,
                   memberships.created_at AS joined_at
            FROM memberships JOIN users ON users.id = memberships.user_id
            WHERE memberships.workspace_id = ?
            ORDER BY CASE memberships.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 WHEN 'editor' THEN 2 ELSE 3 END,
                     users.full_name
            """,
            (user["workspace_id"],),
        ).fetchall()
    return [MemberResponse(**dict(row)) for row in rows]


def _target_member(connection, workspace_id: str, user_id: str) -> Row:  # type: ignore[no-untyped-def]
    target = membership(connection, workspace_id, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    if target["role"] == "owner":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The workspace owner cannot be changed or removed. Transfer ownership first.",
        )
    return target


@router.patch("/api/workspaces/current/members/{member_id}", response_model=MemberResponse)
def change_member_role(
    member_id: str, payload: MemberRoleUpdate, user: Annotated[Row, Depends(require_manager)]
) -> MemberResponse:
    with connect_database() as connection:
        _target_member(connection, user["workspace_id"], member_id)
        connection.execute(
            "UPDATE memberships SET role = ? WHERE workspace_id = ? AND user_id = ?",
            (payload.role, user["workspace_id"], member_id),
        )
        record_audit(connection, user["workspace_id"], user["id"], "member.role_changed", "user", member_id,
                     {"role": payload.role})
        row = connection.execute(
            """
            SELECT users.id AS user_id, users.full_name, users.email, memberships.role,
                   memberships.created_at AS joined_at
            FROM memberships JOIN users ON users.id = memberships.user_id
            WHERE memberships.workspace_id = ? AND memberships.user_id = ?
            """,
            (user["workspace_id"], member_id),
        ).fetchone()
    return MemberResponse(**dict(row))


@router.delete("/api/workspaces/current/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(member_id: str, user: Annotated[Row, Depends(get_current_user)]) -> Response:
    """Managers remove members; anyone except the owner may leave (remove themselves)."""
    if user["workspace_id"] is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Create or join a workspace first.")
    leaving = member_id == user["id"]
    if not leaving and user["role"] not in ("owner", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owners and admins can remove members.")
    with connect_database() as connection:
        _target_member(connection, user["workspace_id"], member_id)
        connection.execute(
            "DELETE FROM memberships WHERE workspace_id = ? AND user_id = ?", (user["workspace_id"], member_id)
        )
        # End the removed person's view of this workspace immediately.
        connection.execute(
            "UPDATE sessions SET active_workspace_id = NULL WHERE user_id = ? AND active_workspace_id = ?",
            (member_id, user["workspace_id"]),
        )
        record_audit(connection, user["workspace_id"], user["id"], "member.left" if leaving else "member.removed",
                     "user", member_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/workspaces/current/transfer-ownership", response_model=list[MemberResponse])
def transfer_ownership(payload: OwnershipTransfer, user: Annotated[Row, Depends(require_owner)]) -> list[MemberResponse]:
    if payload.user_id == user["id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You already own this workspace.")
    with connect_database() as connection:
        connection.lock_for_write()
        target = membership(connection, user["workspace_id"], payload.user_id)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
        if target["role"] == "client":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Make the client an admin or editor first.")
        # Order matters: the one-owner index allows no moment with two owners.
        connection.execute(
            "UPDATE memberships SET role = 'admin' WHERE workspace_id = ? AND user_id = ?",
            (user["workspace_id"], user["id"]),
        )
        connection.execute(
            "UPDATE memberships SET role = 'owner' WHERE workspace_id = ? AND user_id = ?",
            (user["workspace_id"], payload.user_id),
        )
        record_audit(connection, user["workspace_id"], user["id"], "workspace.ownership_transferred", "user",
                     payload.user_id)
    return list_members({**user, "role": "admin"})


@router.get("/api/workspaces/current/invitations", response_model=list[InvitationResponse])
def list_invitations(user: Annotated[Row, Depends(require_manager)]) -> list[InvitationResponse]:
    with connect_database() as connection:
        rows = connection.execute(
            """
            SELECT id, email, role, created_at, expires_at FROM invitations
            WHERE workspace_id = ? AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > ?
            ORDER BY created_at DESC
            """,
            (user["workspace_id"], utc_now()),
        ).fetchall()
    return [InvitationResponse(**dict(row)) for row in rows]


@router.post("/api/workspaces/current/invitations", response_model=InvitationResponse,
             status_code=status.HTTP_201_CREATED)
def create_invitation(payload: InvitationCreate, user: Annotated[Row, Depends(require_manager)]) -> InvitationResponse:
    email = str(payload.email).strip().lower()
    token = new_invitation_token()
    invitation_id = str(uuid4())
    created_at, expires_at = utc_now(), invitation_expiry()
    with connect_database() as connection:
        connection.lock_for_write()
        already_member = connection.execute(
            """
            SELECT 1 FROM memberships JOIN users ON users.id = memberships.user_id
            WHERE memberships.workspace_id = ? AND lower(users.email) = ?
            """,
            (user["workspace_id"], email),
        ).fetchone()
        if already_member:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This person is already a member.")
        # Expired invitations no longer count as open.
        connection.execute(
            "UPDATE invitations SET revoked_at = ? WHERE workspace_id = ? AND email = ? "
            "AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at <= ?",
            (created_at, user["workspace_id"], email, created_at),
        )
        pending = connection.execute(
            "SELECT 1 FROM invitations WHERE workspace_id = ? AND email = ? AND accepted_at IS NULL AND revoked_at IS NULL",
            (user["workspace_id"], email),
        ).fetchone()
        if pending:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email already has a pending invitation. Revoke it to send a new one.",
            )
        connection.execute(
            """
            INSERT INTO invitations (id, workspace_id, email, role, token_hash, invited_by_user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (invitation_id, user["workspace_id"], email, payload.role, token_digest(token), user["id"],
             created_at, expires_at),
        )
        record_audit(connection, user["workspace_id"], user["id"], "invitation.created", "invitation",
                     invitation_id, {"email": email, "role": payload.role})
    # Email delivery is not configured, so the link is returned once for the inviter to share.
    return InvitationResponse(
        id=invitation_id, email=email, role=payload.role, created_at=created_at, expires_at=expires_at,
        invite_url=f"{public_frontend_url()}/invite?token={token}",
    )


@router.delete("/api/workspaces/current/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(invitation_id: str, user: Annotated[Row, Depends(require_manager)]) -> Response:
    with connect_database() as connection:
        result = connection.execute(
            "UPDATE invitations SET revoked_at = ? WHERE id = ? AND workspace_id = ? "
            "AND accepted_at IS NULL AND revoked_at IS NULL",
            (utc_now(), invitation_id, user["workspace_id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found.")
        record_audit(connection, user["workspace_id"], user["id"], "invitation.revoked", "invitation", invitation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/invitations/{token}", response_model=InvitationPreview)
def preview_invitation(token: str) -> InvitationPreview:
    """Lets the invite page show who invited you to what, before you sign in or sign up."""
    with connect_database() as connection:
        invitation = open_invitation(connection, token)
    return InvitationPreview(workspace_name=invitation["workspace_name"], email=invitation["email"],
                             role=invitation["role"])


@router.post("/api/invitations/accept", response_model=SessionResponse)
def accept(payload: InvitationAccept, user: Annotated[Row, Depends(get_current_user)]) -> SessionResponse:
    with connect_database() as connection:
        workspace_id = accept_invitation(connection, payload.token, user["id"], user["email"])
    _switch(user["session_id"], workspace_id)
    return session_response(_reload(user))


def _reload(user: Row) -> Row:
    with connect_database() as connection:
        workspace = connection.execute(
            """
            SELECT workspaces.id, workspaces.name, memberships.role
            FROM sessions JOIN memberships ON memberships.workspace_id = sessions.active_workspace_id
                 AND memberships.user_id = sessions.user_id
            JOIN workspaces ON workspaces.id = memberships.workspace_id
            WHERE sessions.id = ?
            """,
            (user["session_id"],),
        ).fetchone()
    return {**user, "workspace_id": workspace["id"], "workspace_name": workspace["name"], "role": workspace["role"]}
