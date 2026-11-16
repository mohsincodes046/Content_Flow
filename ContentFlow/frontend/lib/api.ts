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
