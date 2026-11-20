"use client";

import { useEffect, useState } from "react";
import { api, apiUrl, canManage, type SessionUser } from "../lib/api";

export type SocialAccount = {
  id: string; platform: string; account_id: string; account_name: string; account_type: string;
  connected_at: string; status: "active" | "needs_reconnect"; last_error?: string | null; last_checked_at?: string | null;
  profile_picture_url?: string | null; parent_account_id?: string | null; can_publish?: boolean | null;
  followers_count?: number | null; linked_page_name?: string | null;
};
type Provider = { provider: string; configured: boolean; accounts: SocialAccount[]; publisher_enabled: boolean };
type Candidate = {
  key: string; platform: string; account_id: string; account_name: string; account_type: string;
  profile_picture_url?: string | null; linked_page_name?: string | null; followers_count?: number | null;
  can_publish: boolean; already_connected: boolean;
};
type Pending = { id: string; provider: string; signed_in_as?: string | null; candidates: Candidate[] };

// Which accounts the user asked for. Meta signs in once for Pages and their linked
// Instagram accounts; the choice only decides which accounts the picker offers.
type ConnectMode = "facebook" | "instagram" | "both";
const CONNECT_MODE_KEY = "contentflow.metaConnectMode";
const connectModes: Array<{ mode: ConnectMode; label: string; primary?: boolean }> = [
  { mode: "both", label: "＋ Connect Instagram & Facebook", primary: true },
  { mode: "facebook", label: "＋ Connect Facebook" },
  { mode: "instagram", label: "＋ Connect Instagram" },
];
const emptyForMode: Record<ConnectMode, string> = {
  facebook: "Meta sign-in worked, but no Facebook Pages you manage were found.",
  instagram: "Meta sign-in worked, but none of your Facebook Pages has a linked Instagram professional account. Link one in Instagram (Settings → Account type and tools) or in Meta Business Suite, then connect again.",
  both: "Meta sign-in worked, but no Facebook Pages you manage were found.",
};
function takeConnectMode(): ConnectMode {
  try {
    const stored = window.sessionStorage.getItem(CONNECT_MODE_KEY);
    window.sessionStorage.removeItem(CONNECT_MODE_KEY);
    return stored === "facebook" || stored === "instagram" ? stored : "both";
  } catch {
    return "both";
  }
}
function rememberConnectMode(mode: ConnectMode) {
  try { window.sessionStorage.setItem(CONNECT_MODE_KEY, mode); } catch { /* the picker then shows every account */ }
}

const platformLabel: Record<string, string> = { facebook: "Facebook Page", instagram: "Instagram", tiktok: "TikTok", linkedin: "LinkedIn", youtube: "YouTube" };
const platformIcon: Record<string, { icon: string; color: string }> = {
  facebook: { icon: "f", color: "#4d76e9" }, instagram: { icon: "◎", color: "#e76072" },
  tiktok: { icon: "♪", color: "#1c1c20" }, linkedin: { icon: "in", color: "#3285bd" }, youtube: { icon: "▶", color: "#e8584d" },
};
const oauthMessages: Record<string, string> = {
  invalid_state: "The sign-in could not be verified. Please connect again.",
  cancelled: "Sign-in was cancelled.",
  no_accounts: "Meta sign-in worked, but no Facebook Pages you manage were found.",
  missing_permissions: "Meta didn't grant the permissions needed. Connect again and allow all requested permissions.",
  connect_failed: "Meta could not connect. Please try again.",
};

function Avatar({ url, platform, name }: { url?: string | null; platform: string; name: string }) {
  const style = { "--account-color": platformIcon[platform]?.color } as React.CSSProperties;
  // Profile pictures come from Meta's CDN; plain <img> avoids configuring remote image hosts.
  // eslint-disable-next-line @next/next/no-img-element
  return url ? <img className="account-picture" src={url} alt="" width={36} height={36} /> : <span className="account-icon account-icon-large" style={style} aria-label={name}>{platformIcon[platform]?.icon ?? "•"}</span>;
}

export default function AccountsSection({ user, setNotice }: { user: SessionUser; setNotice: (value: string) => void }) {
  const manager = canManage(user.role);
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    api<Provider[]>("/api/social/providers", {}, "Unable to load connected accounts")
      .then((result) => { if (active) { setProviders(result); setError(""); } })
      .catch((failure: unknown) => { if (active) setError(failure instanceof Error ? failure.message : "Unable to load connected accounts."); });
    return () => { active = false; };
  }, [reloadKey]);

  // Returning from Meta sign-in: either show the account picker or a message.
  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const result = query.get("social");
    const connectionId = query.get("connection");
    if (!result) return;
    query.delete("social");
    query.delete("connection");
    window.history.replaceState(window.history.state, "", `${window.location.pathname}${query.toString() ? `?${query}` : ""}`);
    const mode = takeConnectMode();
    if (result === "select" && connectionId) {
      api<Pending>(`/api/social/connections/${encodeURIComponent(connectionId)}`, {}, "Unable to load the accounts from Meta")
        .then((loaded) => {
          const candidates = mode === "both" ? loaded.candidates : loaded.candidates.filter((c) => c.platform === mode);
          if (!candidates.length) {
            void api(`/api/social/connections/${encodeURIComponent(connectionId)}`, { method: "DELETE" }).catch(() => undefined);
            setNotice(emptyForMode[mode]);
            return;
          }
          setPending({ ...loaded, candidates });
          setChosen(candidates.filter((c) => !c.already_connected && c.can_publish).map((c) => c.key));
        })
        .catch((failure: unknown) => setNotice(failure instanceof Error ? failure.message : "Unable to load the accounts from Meta."));
    } else {
      setNotice(oauthMessages[result] ?? "Sign-in did not complete.");
    }
  }, [setNotice]);

  const meta = providers?.find((provider) => provider.provider === "meta");
  const accounts = providers?.flatMap((provider) => provider.accounts) ?? [];
  const others = providers?.filter((provider) => provider.provider !== "meta") ?? [];
  const pageName = (id?: string | null) => accounts.find((account) => account.id === id)?.account_name;

  async function act(label: string, action: () => Promise<unknown>, success: string) {
    if (busy) return;
    setBusy(label);
    try {
      await action();
      setNotice(success);
      setReloadKey((key) => key + 1);
    } catch (failure) {
      setNotice(failure instanceof Error ? failure.message : "That didn't work. Please try again.");
    } finally {
      setBusy("");
    }
  }

  const connectHref = `${apiUrl}/api/social/oauth/meta/start`;
  const connectButton = ({ mode, label, primary }: (typeof connectModes)[number]) => meta?.configured
    ? <a key={mode} className={`button ${primary ? "button-primary" : "button-outline"}`} href={connectHref} onClick={() => rememberConnectMode(mode)}>{label}</a>
    : <button key={mode} type="button" className="button button-outline" onClick={() => setNotice("Facebook and Instagram connections are not set up on this server yet. Ask your Content-Flow administrator to configure Meta sign-in.")}>{label}</button>;

  return <section className="panel manage-accounts-panel">
    <div className="section-card-heading">
      <div><span className="calendar-month-label">SOCIAL CONNECTIONS</span><h2>Connected accounts</h2>
        <p>Connect Facebook Pages, Instagram professional accounts, or both, through Meta sign-in. An Instagram account must be a Business or Creator account linked to a Facebook Page.</p></div>
      {manager && <div className="team-actions">{connectModes.map(connectButton)}{others.map((p) => p.configured
        ? <a key={p.provider} className="button button-outline" href={`${apiUrl}/api/social/oauth/${p.provider}/start`}>＋ Connect {platformLabel[p.provider]}</a>
        : <button key={p.provider} type="button" className="button button-outline" title="Not configured on this server" onClick={() => setNotice(`${platformLabel[p.provider]} is not set up on this server yet. An administrator must add the app credentials.`)}>＋ {platformLabel[p.provider]}</button>)}</div>}
    </div>
    {error && <p className="schedule-load-error" role="alert">{error}</p>}

    {pending && <div className="connection-picker" role="dialog" aria-label="Choose accounts to connect">
      <b>Choose the accounts to add to {user.workspace_name}</b>
      <p>{pending.signed_in_as ? `Signed in to Meta as ${pending.signed_in_as}. ` : ""}Only selected accounts are saved.</p>
      {pending.candidates.map((candidate) => <label key={candidate.key} className={`candidate-row ${candidate.can_publish ? "" : "candidate-limited"}`}>
        <input type="checkbox" checked={chosen.includes(candidate.key)} onChange={() => setChosen((current) => current.includes(candidate.key) ? current.filter((key) => key !== candidate.key) : [...current, candidate.key])} />
        <Avatar url={candidate.profile_picture_url} platform={candidate.platform} name={candidate.account_name} />
        <span><b>{candidate.platform === "instagram" ? `@${candidate.account_name}` : candidate.account_name}</b>
          <small>{platformLabel[candidate.platform]}{candidate.linked_page_name ? ` · linked to ${candidate.linked_page_name}` : ""}{typeof candidate.followers_count === "number" ? ` · ${candidate.followers_count.toLocaleString()} followers` : ""}{candidate.already_connected ? " · already connected (will refresh)" : ""}{candidate.can_publish ? "" : " · your Page role can't publish"}</small></span>
      </label>)}
      <div className="connection-picker-actions">
        <button type="button" className="button button-primary" disabled={!chosen.length || Boolean(busy)} onClick={() => void act("select", async () => { await api(`/api/social/connections/${pending.id}/select`, { method: "POST", json: { keys: chosen } }, "Unable to save the accounts"); setPending(null); }, `${chosen.length} account${chosen.length === 1 ? "" : "s"} connected.`)}>Add {chosen.length} selected</button>
        <button type="button" className="button button-outline" onClick={() => { void api(`/api/social/connections/${pending.id}`, { method: "DELETE" }).catch(() => undefined); setPending(null); }}>Cancel</button>
      </div>
    </div>}

    {providers === null && !error && <p className="schedule-state">Loading connected accounts…</p>}
    {providers !== null && accounts.length === 0 && !pending && <div className="upcoming-empty">
      <b>No accounts connected yet.</b>
      <p>{manager ? "Connect a Facebook Page to publish automatically. Instagram professional accounts linked to your Pages appear in the same step." : "Ask a workspace owner or admin to connect your Facebook Page and Instagram account."}</p>
    </div>}

    <div className="connected-account-list">{accounts.map((account) => {
      const reconnect = account.status === "needs_reconnect";
      return <article key={account.id} className={`connected-account ${reconnect ? "connected-account-warning" : ""}`}>
        <Avatar url={account.profile_picture_url} platform={account.platform} name={account.account_name} />
        <div className="connected-account-text">
          <b>{account.platform === "instagram" ? `@${account.account_name}` : account.account_name}</b>
          <small>{platformLabel[account.platform] ?? account.platform}
            {account.platform === "instagram" && (pageName(account.parent_account_id) || account.linked_page_name) ? ` · linked to ${pageName(account.parent_account_id) ?? account.linked_page_name}` : ""}
            {typeof account.followers_count === "number" ? ` · ${account.followers_count.toLocaleString()} followers` : ""}
            {account.can_publish === false ? " · read-only Page role" : ""}</small>
          {reconnect && <small className="publish-error-text">{account.last_error ?? "This connection needs to be renewed."}</small>}
          {!reconnect && account.last_error && <small className="account-note">Last check: {account.last_error}</small>}
        </div>
        <span className={`connection-state ${reconnect ? "social-not-connected" : ""}`}><i />{reconnect ? "Needs reconnect" : "Connected"}</span>
        <div className="team-actions">
          <button type="button" disabled={Boolean(busy)} onClick={() => void act(account.id, () => api(`/api/social/accounts/${account.id}/check`, { method: "POST" }, "Unable to check the connection"), "Connection checked.")}>{busy === account.id ? "Checking…" : "Check connection"}</button>
          {manager && reconnect && <a className="button button-primary" href={["facebook", "instagram"].includes(account.platform) ? connectHref : `${apiUrl}/api/social/oauth/${account.platform}/start`}>Reconnect</a>}
          {manager && <button type="button" disabled={Boolean(busy)} onClick={() => void act(`delete-${account.id}`, () => api(`/api/social/accounts/${account.id}`, { method: "DELETE" }, "Unable to disconnect"), `${account.account_name} disconnected.`)}>Disconnect</button>}
        </div>
      </article>;
    })}</div>

    <div className="integration-note"><span>✳</span><span>
      {meta?.publisher_enabled ? "Scheduled posts publish automatically to connected accounts." : "Automatic publishing is turned off on this server; scheduled posts stay on the calendar."}
      {" "}TikTok posts stay private until TikTok approves the app; LinkedIn posts go to the connected member profile.</span></div>
  </section>;
}
