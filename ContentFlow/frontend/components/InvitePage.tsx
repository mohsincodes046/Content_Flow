"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import Logo from "./Logo";
import { api, isSessionUser, roleLabels, type Role, type SessionUser } from "../lib/api";

type Preview = { workspace_name: string; email: string; role: Exclude<Role, "owner"> };

export default function InvitePage() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const [preview, setPreview] = useState<Preview | null>(null);
  const [session, setSession] = useState<SessionUser | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<"signup" | "login">("signup");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const invitation = await api<Preview>(`/api/invitations/${encodeURIComponent(token)}`, {}, "This invitation could not be loaded");
        if (!active) return;
        setPreview(invitation);
        const me = await api<unknown>("/api/auth/me").catch(() => null);
        if (active && isSessionUser(me)) setSession(me);
      } catch (failure) {
        if (active) setError(failure instanceof Error ? failure.message : "This invitation could not be loaded.");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [token]);

  const destination = (role: Role | null) => (role === "client" ? "/review-queue" : "/dashboard");

  async function accept() {
    setPending(true);
    setError("");
    try {
      const joined = await api<SessionUser>("/api/invitations/accept", { method: "POST", json: { token } }, "Unable to accept the invitation");
      router.replace(destination(joined.role));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Unable to accept the invitation.");
      setPending(false);
    }
  }

  async function signOut() {
    await api("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    setSession(null);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!preview) return;
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError("");
    try {
      if (mode === "signup") {
        const joined = await api<SessionUser>("/api/auth/register", {
          method: "POST",
          json: { full_name: String(form.get("full_name") ?? "").trim(), email: preview.email, password: String(form.get("password") ?? ""), invitation_token: token },
        }, "Unable to create your account");
        router.replace(destination(joined.role));
      } else {
        await api("/api/auth/login", { method: "POST", json: { email: preview.email, password: String(form.get("password") ?? "") } }, "Unable to sign in");
        await accept();
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Something went wrong. Please try again.");
      setPending(false);
    }
  }

  return <main className="auth-check-screen invite-screen">
    <Logo />
    {loading && <p>Checking your invitation…</p>}
    {!loading && !preview && <><h1>Invitation unavailable</h1><p role="alert">{error}</p></>}
    {preview && <>
      <h1>Join {preview.workspace_name}</h1>
      <p>You&apos;ve been invited as <b>{roleLabels[preview.role]}</b> using <b>{preview.email}</b>.</p>
      {session && session.email.toLowerCase() === preview.email.toLowerCase() && (
        <button type="button" className="button button-primary" disabled={pending} onClick={() => void accept()}>{pending ? "Joining…" : `Join ${preview.workspace_name}`}</button>
      )}
      {session && session.email.toLowerCase() !== preview.email.toLowerCase() && <>
        <p>You&apos;re signed in as {session.email}. This invitation is for {preview.email}.</p>
        <button type="button" className="button button-outline" onClick={() => void signOut()}>Sign out and continue</button>
      </>}
      {!session && <form className="auth-form invite-form-card" onSubmit={submit}>
        {mode === "signup" && <label><span>YOUR NAME</span><input name="full_name" required maxLength={100} autoComplete="name" /></label>}
        <label><span>PASSWORD</span><input name="password" type="password" required minLength={mode === "signup" ? 8 : 1} maxLength={128} autoComplete={mode === "signup" ? "new-password" : "current-password"} /></label>
        <button type="submit" className="button button-primary" disabled={pending}>{pending ? "Please wait…" : mode === "signup" ? "Create account and join" : "Sign in and join"}</button>
        <button type="button" className="auth-switch-button" onClick={() => setMode(mode === "signup" ? "login" : "signup")}>
          {mode === "signup" ? `Already have an account for ${preview.email}? Sign in` : "New here? Create an account"}
        </button>
      </form>}
      {error && <p role="alert" className="ai-generator-error">{error}</p>}
    </>}
  </main>;
}
