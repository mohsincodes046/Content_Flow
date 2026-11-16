"use client";

import { useState, type FormEvent } from "react";
import { api, roleLabels, type SessionUser } from "../lib/api";

/** Sidebar workspace picker: switch between workspaces or create a new one. */
export default function WorkspaceSwitcher({ user, setNotice }: { user: SessionUser; setNotice: (value: string) => void }) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [pending, setPending] = useState(false);
  const current = user.workspaces.find((workspace) => workspace.id === user.workspace_id);

  async function switchTo(id: string) {
    if (id === user.workspace_id || pending) return;
    setPending(true);
    try {
      await api(`/api/workspaces/${encodeURIComponent(id)}/switch`, { method: "POST" }, "Unable to switch workspace");
      // Every view loads data for the active workspace, so start fresh.
      window.location.reload();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Unable to switch workspace.");
      setPending(false);
    }
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    try {
      await api("/api/workspaces", { method: "POST", json: { name } }, "Unable to create the workspace");
      window.location.reload();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Unable to create the workspace.");
      setPending(false);
    }
  }

  return (
    <div className="workspace-switcher">
      <button type="button" className="workspace-switch" aria-expanded={open} onClick={() => setOpen(!open)}>
        <div className="workspace-avatar">{(current?.name ?? "?")[0]?.toUpperCase()}</div>
        <div>
          <b>{current?.name ?? "No workspace"}</b>
          <small>{current ? roleLabels[current.role] : "Create or join one"}</small>
        </div>
        <span className="workspace-caret" aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="workspace-menu" role="menu">
          {user.workspaces.map((workspace) => (
            <button key={workspace.id} type="button" role="menuitemradio" aria-checked={workspace.id === user.workspace_id}
              className={workspace.id === user.workspace_id ? "workspace-option workspace-option-active" : "workspace-option"}
              disabled={pending} onClick={() => void switchTo(workspace.id)}>
              <span>{workspace.name}</span><small>{roleLabels[workspace.role]}</small>
            </button>
          ))}
          {creating ? (
            <form className="workspace-create" onSubmit={create}>
              <input autoFocus required maxLength={120} placeholder="Client or brand name" value={name}
                onChange={(event) => setName(event.target.value)} aria-label="New workspace name" />
              <button type="submit" className="button button-primary" disabled={pending}>Create</button>
            </form>
          ) : (
            <button type="button" className="workspace-option workspace-new" onClick={() => setCreating(true)}>＋ New workspace</button>
          )}
        </div>
      )}
    </div>
  );
}

/** Shown when the signed-in user belongs to no workspace (for example, after being removed). */
export function NoWorkspace({ user }: { user: SessionUser }) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      await api("/api/workspaces", { method: "POST", json: { name } }, "Unable to create the workspace");
      window.location.reload();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Unable to create the workspace.");
      setPending(false);
    }
  }

  return (
    <main className="auth-check-screen">
      <h1>You&apos;re not in a workspace yet</h1>
      <p>Hi {user.full_name.split(/\s+/)[0]}. Create a workspace for your business, or open an invitation link you received.</p>
      <form className="workspace-create workspace-create-large" onSubmit={create}>
        <input required maxLength={120} placeholder="Workspace name" value={name} onChange={(event) => setName(event.target.value)}
          aria-label="Workspace name" />
        <button type="submit" className="button button-primary" disabled={pending}>{pending ? "Creating…" : "Create workspace"}</button>
      </form>
      {error && <p role="alert" className="ai-generator-error">{error}</p>}
    </main>
  );
}
