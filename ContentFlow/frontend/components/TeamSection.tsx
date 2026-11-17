"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, canManage, roleLabels, type Role, type SessionUser } from "../lib/api";

type Member = { user_id: string; full_name: string; email: string; role: Role; joined_at: string };
type Invitation = { id: string; email: string; role: Exclude<Role, "owner">; created_at: string; expires_at: string; invite_url?: string | null };

const roleHelp: Record<Exclude<Role, "owner">, string> = {
  admin: "Manages members, settings and social accounts; creates and schedules content.",
  editor: "Creates, edits and schedules content.",
  client: "Sees only content sent to them for review; approves, rejects or requests changes.",
};

const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("");
const shortDate = (iso: string) => new Date(iso).toLocaleDateString("en", { month: "short", day: "numeric", year: "numeric" });

export default function TeamSection({ user, setNotice }: { user: SessionUser; setNotice: (value: string) => void }) {
  const manager = canManage(user.role);
  const [members, setMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Exclude<Role, "owner">>("editor");
  const [busy, setBusy] = useState(false);
  const [lastLink, setLastLink] = useState<Invitation | null>(null);

  const [reloadKey, setReloadKey] = useState(0);
  const load = useCallback(async () => { setReloadKey((key) => key + 1); }, []);

  useEffect(() => {
    let active = true;
    Promise.all([
      api<Member[]>("/api/workspaces/current/members", {}, "Unable to load members"),
      manager ? api<Invitation[]>("/api/workspaces/current/invitations", {}, "Unable to load invitations") : Promise.resolve([]),
    ])
      .then(([loadedMembers, loadedInvitations]) => {
        if (!active) return;
        setMembers(loadedMembers);
        setInvitations(loadedInvitations);
        setError("");
      })
      .catch((failure: unknown) => {
        if (active) setError(failure instanceof Error ? failure.message : "Unable to load the team.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [manager, reloadKey]);

  async function run(action: () => Promise<unknown>, success: string) {
    if (busy) return;
    setBusy(true);
    try {
      await action();
      setNotice(success);
      await load();
    } catch (failure) {
      setNotice(failure instanceof Error ? failure.message : "That didn't work. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function sendInvitation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      const created = await api<Invitation>("/api/workspaces/current/invitations", { method: "POST", json: { email, role } }, "Unable to create the invitation");
      setLastLink(created);
      setEmail("");
      await load();
    } catch (failure) {
      setNotice(failure instanceof Error ? failure.message : "Unable to create the invitation.");
    } finally {
      setBusy(false);
    }
  }

  return <section className="panel team-panel">
    <div className="section-card-heading">
      <div><span className="calendar-month-label">WORKSPACE TEAM</span><h2>Your team</h2><p>People who can work in {user.workspace_name}.</p></div>
    </div>
    {error && <p className="schedule-load-error" role="alert">{error}</p>}
    <div className="team-table">
      <div className="team-table-head"><span>YOUR PEOPLE</span><span>ROLE</span><span>ACTIONS</span></div>
      {loading && <p className="schedule-state">Loading your team…</p>}
      {members.map((member) => {
        const self = member.user_id === user.id;
        const editable = manager && member.role !== "owner" && !self;
        return <div className="team-table-row" key={member.user_id}>
          <span className="team-member"><i className="user-avatar">{initials(member.full_name)}</i><span><b>{member.full_name}{self ? " (you)" : ""}</b><small>{member.email} · joined {shortDate(member.joined_at)}</small></span></span>
          <span>{editable
            ? <select aria-label={`Role for ${member.full_name}`} value={member.role} disabled={busy}
                onChange={(event) => void run(() => api(`/api/workspaces/current/members/${member.user_id}`, { method: "PATCH", json: { role: event.target.value } }, "Unable to change the role"), `${member.full_name} is now ${roleLabels[event.target.value as Role]}.`)}>
                {(["admin", "editor", "client"] as const).map((r) => <option key={r} value={r}>{roleLabels[r]}</option>)}
              </select>
            : <b className="role-pill">{roleLabels[member.role]}</b>}</span>
          <span className="team-actions">
            {editable && <button type="button" disabled={busy} onClick={() => void run(() => api(`/api/workspaces/current/members/${member.user_id}`, { method: "DELETE" }, "Unable to remove the member"), `${member.full_name} was removed from the workspace.`)}>Remove</button>}
            {user.role === "owner" && !self && member.role !== "client" && <button type="button" disabled={busy} onClick={() => void run(async () => { await api("/api/workspaces/current/transfer-ownership", { method: "POST", json: { user_id: member.user_id } }, "Unable to transfer ownership"); window.location.reload(); }, `${member.full_name} now owns this workspace. You are an admin.`)}>Make owner</button>}
            {self && member.role !== "owner" && <button type="button" disabled={busy} onClick={() => void run(async () => { await api(`/api/workspaces/current/members/${member.user_id}`, { method: "DELETE" }, "Unable to leave the workspace"); window.location.reload(); }, "You left the workspace.")}>Leave workspace</button>}
          </span>
        </div>;
      })}
    </div>

    {manager && <>
      <form className="invite-form" onSubmit={sendInvitation}>
        <span className="calendar-month-label">INVITE SOMEONE</span>
        <div className="invite-fields">
          <input type="email" required maxLength={254} placeholder="name@company.com" value={email} onChange={(event) => setEmail(event.target.value)} aria-label="Email to invite" />
          <select value={role} onChange={(event) => setRole(event.target.value as Exclude<Role, "owner">)} aria-label="Role">
            {(["admin", "editor", "client"] as const).map((r) => <option key={r} value={r}>{roleLabels[r]}</option>)}
          </select>
          <button type="submit" className="button button-primary" disabled={busy}>Create invitation</button>
        </div>
        <small>{roleHelp[role]}</small>
      </form>
      {lastLink?.invite_url && <div className="invite-link" role="status">
        <b>Invitation for {lastLink.email} created.</b>
        <p>Email sending isn&apos;t set up yet, so share this link with them. It works once and expires on {shortDate(lastLink.expires_at)}. It won&apos;t be shown again.</p>
        <div className="invite-link-row"><code>{lastLink.invite_url}</code>
          <button type="button" onClick={() => navigator.clipboard.writeText(lastLink.invite_url ?? "").then(() => setNotice("Invitation link copied.")).catch(() => setNotice("Copy the link manually; clipboard access is unavailable."))}>Copy</button></div>
      </div>}
      {invitations.length > 0 && <div className="team-table">
        <div className="team-table-head"><span>PENDING INVITATIONS</span><span>ROLE</span><span>EXPIRES</span></div>
        {invitations.map((invitation) => <div className="team-table-row" key={invitation.id}>
          <span className="team-member"><span><b>{invitation.email}</b></span></span>
          <span><b className="role-pill">{roleLabels[invitation.role]}</b></span>
          <span className="team-actions">{shortDate(invitation.expires_at)}
            <button type="button" disabled={busy} onClick={() => void run(() => api(`/api/workspaces/current/invitations/${invitation.id}`, { method: "DELETE" }, "Unable to revoke the invitation"), `Invitation for ${invitation.email} revoked.`)}>Revoke</button></span>
        </div>)}
      </div>}
    </>}
  </section>;
}
