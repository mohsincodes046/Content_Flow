// Shared API helpers. In production the browser calls the same site (`/`), and
// Next.js proxies /api/* to the backend; locally it calls the API directly.
export const apiUrl = (process.env.NEXT_PUBLIC_CONTENT_FLOW_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export type Role = "owner" | "admin" | "editor" | "client";
export type WorkspaceSummary = { id: string; name: string; role: Role };
export type SessionUser = {
  id: string;
  email: string;
  full_name: string;
  workspace_id: string | null;
  workspace_name: string | null;
  role: Role | null;
  workspaces: WorkspaceSummary[];
};

export const roleLabels: Record<Role, string> = { owner: "Owner", admin: "Admin", editor: "Editor", client: "Client" };
export const canManage = (role: Role | null | undefined) => role === "owner" || role === "admin";
export const canEditContent = (role: Role | null | undefined) => role === "owner" || role === "admin" || role === "editor";
export const canReview = (role: Role | null | undefined) => role === "owner" || role === "admin" || role === "client";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export async function apiErrorMessage(response: Response, fallback: string): Promise<string> {
  const payload: unknown = await response.json().catch(() => null);
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length && typeof detail[0]?.msg === "string") {
      return String(detail[0].msg).replace(/^Value error, /, "");
    }
  }
  return `${fallback} (${response.status}).`;
}

/** fetch() against the API with the session cookie; throws ApiError with the server's message. */
export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}, fallback = "Request failed"): Promise<T> {
  const { json, headers, ...rest } = init;
  const response = await fetch(`${apiUrl}${path}`, {
    credentials: "include",
    ...rest,
    headers: json === undefined ? headers : { "Content-Type": "application/json", ...headers },
    body: json === undefined ? rest.body : JSON.stringify(json),
  });
  if (!response.ok) throw new ApiError(await apiErrorMessage(response, fallback), response.status);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function isSessionUser(value: unknown): value is SessionUser {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.id === "string" && typeof v.email === "string" && typeof v.full_name === "string"
    && Array.isArray(v.workspaces);
}

// --- Posts -------------------------------------------------------------------------------------

export type PostStatus =
  | "draft" | "in_review" | "changes_requested" | "approved" | "rejected"
  | "scheduled" | "publishing" | "published" | "partially_published" | "failed";
export type Asset = {
  id: string; filename: string; media_type: string; size: number;
  width?: number | null; height?: number | null; created_at?: string | null; used_by_posts?: number;
};
export type PostTarget = {
  id: string; social_account_id: string | null; platform: string; account_name: string; caption_override: string | null;
  status: "pending" | "queued" | "publishing" | "published" | "failed" | "cancelled";
  attempts: number; next_attempt_at?: string | null; last_error?: string | null;
  external_id?: string | null; external_url?: string | null; published_at?: string | null; account_status?: string | null;
};
export type PostEvent = { id: string; kind: string; message?: string | null; actor_name?: string | null; created_at: string };
export type Post = {
  id: string; title: string; caption: string; status: PostStatus;
  scheduled_at: string | null; timezone: string | null; planned_platforms: string[];
  reviewer_user_id: string | null; reviewer_name: string | null; created_by_name: string | null;
  created_at: string; updated_at: string; media: Asset[]; targets: PostTarget[];
  issues: { platform: string; account?: string | null; message: string }[]; events: PostEvent[];
};

export const statusLabels: Record<PostStatus, string> = {
  draft: "Draft", in_review: "In review", changes_requested: "Changes requested", approved: "Approved",
  rejected: "Rejected", scheduled: "Scheduled", publishing: "Publishing…", published: "Published",
  partially_published: "Partly published", failed: "Failed",
};

export const browserTimezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
export const assetUrl = (id: string) => `${apiUrl}/api/assets/${encodeURIComponent(id)}/content`;

/** "2026-12-01T09:30" in the browser's timezone, for <input type="datetime-local">. */
export function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export const formatWhen = (iso: string | null) => iso
  ? new Date(iso).toLocaleString("en", { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
  : "Not scheduled";

type UploadTarget =
  | { mode: "local" }
  | { mode: "cloudinary"; asset_id: string; upload_url: string; fields: Record<string, string | number> };

/**
 * Upload one file to the media library. Locally it goes to the API; in production the API
 * hands out a one-file signed Cloudinary upload, the browser sends the file straight there
 * (no proxy body limits), and the API then registers it. Resolves to the API's response,
 * whose JSON body is the new Asset.
 */
export async function uploadAsset(file: File): Promise<Response> {
  const targetResponse = await fetch(`${apiUrl}/api/assets/upload-target`, { credentials: "include" });
  if (!targetResponse.ok) return targetResponse;
  const target = (await targetResponse.json()) as UploadTarget;
  if (target.mode !== "cloudinary") {
    const body = new FormData();
    body.append("file", file);
    return fetch(`${apiUrl}/api/assets`, { method: "POST", credentials: "include", body });
  }
  const body = new FormData();
  for (const [key, value] of Object.entries(target.fields)) body.append(key, String(value));
  body.append("file", file);
  const uploaded = await fetch(target.upload_url, { method: "POST", body });
  if (!uploaded.ok) {
    const payload = (await uploaded.json().catch(() => null)) as { error?: { message?: string } } | null;
    const detail = payload?.error?.message ?? `The media service rejected ${file.name}`;
    return new Response(JSON.stringify({ detail }), { status: uploaded.status, headers: { "Content-Type": "application/json" } });
  }
  return fetch(`${apiUrl}/api/assets/cloudinary`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ asset_id: target.asset_id, filename: file.name }),
  });
}
