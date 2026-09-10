/**
 * Thin client for the SentriX backend API.
 *
 * Deliberately small: `fetch` plus token handling, no data-fetching library.
 * Response types below mirror `backend/app/models/schemas.py` exactly — field
 * names come from the Pydantic models, not from guesses, so a rename on either
 * side surfaces as a type error rather than as `undefined` at runtime.
 */

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export const TOKEN_STORAGE_KEY = "sentrix_token";

// --------------------------------------------------------------------------- //
// Response shapes (backend/app/models/schemas.py)
// --------------------------------------------------------------------------- //

/** `Token` */
export interface TokenResponse {
  access_token: string;
  token_type: string;
}

/** `UserPublic` */
export interface UserPublic {
  username: string;
  role: string;
  agency: string;
}

/** `RiskFactors` */
export interface RiskFactors {
  gnn_score: number;
  ppr_score: number;
  traffic_anomaly_score: number;
  weights: Record<string, number>;
}

/** `AddressRisk` */
export interface AddressRisk {
  address: string;
  risk_score: number;
  contributing_factors: RiskFactors;
  last_updated: string;
}

/** `Alert` */
export interface Alert {
  id: string;
  address: string;
  risk_score: number;
  reason: string;
  flagged_at: string;
}

/** `RankedAddress` */
export interface RankedAddress {
  address: string;
  risk_score: number;
  risk_tier: string;
  last_updated: string;
}

// --------------------------------------------------------------------------- //
// Errors
// --------------------------------------------------------------------------- //

/**
 * Any non-2xx response. `status` is carried so callers can tell a rejected
 * login (401) from an unreachable or broken server (0 / 5xx).
 */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * A 401 from an authenticated endpoint: the token is missing, expired or
 * invalid. Separate from `ApiError` so a caller can `instanceof` it and
 * redirect to /login instead of rendering a generic failure.
 */
export class UnauthorizedError extends ApiError {
  constructor(message = "Session expired or not signed in") {
    super(401, message);
    this.name = "UnauthorizedError";
  }
}

/** The request never reached the server (DNS, refused connection, CORS). */
export class NetworkError extends ApiError {
  constructor(message = "Cannot reach the SentriX API") {
    super(0, message);
    this.name = "NetworkError";
  }
}

// --------------------------------------------------------------------------- //
// Token storage
// --------------------------------------------------------------------------- //

/**
 * `localStorage` access is wrapped because it throws outright in a few real
 * browser configurations (Safari private mode, site data blocked) rather than
 * simply returning null. A storage failure should not take the page down.
 */
export function getToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    // Non-fatal: the session simply will not survive a reload.
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // Non-fatal.
  }
}

export function isAuthenticated(): boolean {
  const token = getToken();
  return token !== null && token.length > 0;
}

// --------------------------------------------------------------------------- //
// Requests
// --------------------------------------------------------------------------- //

function url(path: string): string {
  const base = API_BASE_URL.replace(/\/+$/, "");
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

/** Best-effort extraction of FastAPI's `{"detail": ...}` error body. */
async function errorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    // 422 returns a list of validation objects rather than a string.
    if (Array.isArray(body.detail) && body.detail.length > 0) {
      return JSON.stringify(body.detail[0]);
    }
  } catch {
    // Body was empty or not JSON; fall through.
  }
  return fallback;
}

/**
 * Sign in and store the JWT.
 *
 * `/auth/login` takes `OAuth2PasswordRequestForm`, FastAPI's standard JWT
 * pattern, so the body must be form-encoded. Sending JSON returns 422 — this
 * was confirmed against the running backend, so `URLSearchParams` here is
 * required rather than stylistic.
 */
export async function login(
  username: string,
  password: string,
): Promise<TokenResponse> {
  const body = new URLSearchParams();
  body.set("username", username);
  body.set("password", password);

  let response: Response;
  try {
    response = await fetch(url("/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
  } catch {
    throw new NetworkError();
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      await errorMessage(
        response,
        response.status === 401
          ? "Incorrect username or password"
          : `Login failed (HTTP ${response.status})`,
      ),
    );
  }

  const token = (await response.json()) as TokenResponse;
  if (!token.access_token) {
    throw new ApiError(response.status, "Login response contained no token");
  }
  setToken(token.access_token);
  return token;
}

export function logout(): void {
  clearToken();
}

/**
 * `fetch` with the bearer token attached, parsed as JSON.
 *
 * Throws `UnauthorizedError` on 401 — including when no token is stored at all,
 * so a caller gets the same signal whether the session expired or never
 * existed. The stored token is cleared on 401 so a stale value cannot keep a
 * route guard believing the user is signed in.
 */
export async function authFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  if (!token) {
    throw new UnauthorizedError("Not signed in");
  }

  const headers = new Headers(options.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (options.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(url(path), { ...options, headers });
  } catch {
    throw new NetworkError();
  }

  if (response.status === 401) {
    clearToken();
    throw new UnauthorizedError();
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      await errorMessage(response, `Request failed (HTTP ${response.status})`),
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

// --------------------------------------------------------------------------- //
// Endpoints
// --------------------------------------------------------------------------- //

/** `GET /auth/me` */
export function getCurrentUser(): Promise<UserPublic> {
  return authFetch<UserPublic>("/auth/me");
}

/** `GET /address/{address_id}/risk` */
export function getAddressRisk(addressId: string): Promise<AddressRisk> {
  return authFetch<AddressRisk>(
    `/address/${encodeURIComponent(addressId)}/risk`,
  );
}

/**
 * `GET /alerts`
 *
 * The backend bounds both parameters (`threshold` 0-1, `limit` 1-500) and
 * returns 422 outside those ranges, so they are clamped here rather than
 * letting a stray caller value become a failed request.
 */
export function listAlerts(threshold = 0.8, limit = 50): Promise<Alert[]> {
  const params = new URLSearchParams({
    threshold: String(Math.min(Math.max(threshold, 0), 1)),
    limit: String(Math.min(Math.max(Math.trunc(limit), 1), 500)),
  });
  return authFetch<Alert[]>(`/alerts?${params}`);
}

/**
 * `GET /address/ranked`
 *
 * Risk-ranked addresses for the dashboard table. Shares its candidate pool and
 * fused scores with `/alerts`, so both panels agree on the ranking. Bounds
 * mirror the backend's (`threshold` 0-1, `limit` 1-500) to avoid a 422.
 */
export function listRankedAddresses(threshold = 0, limit = 25): Promise<RankedAddress[]> {
  const params = new URLSearchParams({
    threshold: String(Math.min(Math.max(threshold, 0), 1)),
    limit: String(Math.min(Math.max(Math.trunc(limit), 1), 500)),
  });
  return authFetch<RankedAddress[]>(`/address/ranked?${params}`);
}
