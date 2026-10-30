/**
 * A small typed wrapper around fetch for the OpenStall API.
 *
 * Every failure becomes an ApiError whose message a person can read, so pages can show it as is.
 */

const DEFAULT_API_BASE_URL = "http://localhost:8000";

/** The API address. Next.js inlines NEXT_PUBLIC_API_BASE_URL at build time. */
export function apiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL || DEFAULT_API_BASE_URL).replace(/\/+$/, "");
}

/** A failed API call. `status` is null when the API could not be reached at all. */
export class ApiError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Calls the API and returns its JSON body, or throws an ApiError. Aborted calls rethrow the AbortError. */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, { ...init, headers });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError(`Could not reach the OpenStall API at ${apiBaseUrl()}. Check that it is running.`, null);
  }

  if (!response.ok) {
    throw new ApiError(await describeFailure(response), response.status);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(`The OpenStall API sent a reply that is not JSON (${path}).`, response.status);
  }
}

export function apiGet<T>(path: string, init: RequestInit = {}): Promise<T> {
  return apiFetch<T>(path, { ...init, method: "GET" });
}

export function apiPost<T>(path: string, body: unknown, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  return apiFetch<T>(path, { ...init, method: "POST", headers, body: JSON.stringify(body) });
}

export type Health = { status: "ok" };

export function getHealth(init: RequestInit = {}): Promise<Health> {
  return apiGet<Health>("/health", init);
}

/** A readable message for anything thrown by an API call. */
export function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "Something went wrong. Please try again.";
}

async function describeFailure(response: Response): Promise<string> {
  const detail = detailFrom(await response.json().catch(() => null));
  if (detail) return `${detail} (HTTP ${response.status})`;
  const status = [response.status, response.statusText].filter(Boolean).join(" ");
  return `The OpenStall API answered ${status}.`;
}

/** FastAPI puts the reason in `detail`: a string, or a list of validation errors. */
function detailFrom(body: unknown): string | null {
  if (!body || typeof body !== "object" || !("detail" in body)) return null;
  const { detail } = body as { detail: unknown };
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return null;
  const problems = detail.map(validationProblem).filter((problem): problem is string => problem !== null);
  return problems.length > 0 ? problems.join("; ") : null;
}

function validationProblem(item: unknown): string | null {
  if (!item || typeof item !== "object") return null;
  const { loc, msg } = item as { loc?: unknown; msg?: unknown };
  if (typeof msg !== "string") return null;
  // loc looks like ["body", "quantity"]: the first part only says where the field was sent.
  const field = Array.isArray(loc) ? loc.slice(1).join(".") : "";
  return field ? `${field}: ${msg}` : msg;
}

function isAbortError(error: unknown): boolean {
  // Checked by name: fetch rejects with a DOMException, which is not an Error in every runtime.
  return typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError";
}
