import type {
  Action,
  AdapterId,
  ApiErrorData,
  Folio,
  FolioSummary,
  Health,
} from "./types";
import type { WheatStudy } from "./wheat-types";

export class ApiError extends Error {
  code: string;
  recoverable: boolean;
  constructor(error: ApiErrorData) {
    super(error.message);
    this.name = "ApiError";
    this.code = error.code;
    this.recoverable = error.recoverable !== false;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError({
      code: "connection_unavailable",
      message:
        "The local API could not be reached. Your saved evidence is unchanged. Reconnect and try again.",
    });
  }
  const result = (await response.json().catch(() => null)) as
    T | { error?: ApiErrorData; detail?: unknown } | null;
  if (!response.ok) {
    const data = result as { error?: ApiErrorData; detail?: unknown } | null;
    throw new ApiError(
      data?.error ?? {
        code: `http_${response.status}`,
        message:
          typeof data?.detail === "string"
            ? data.detail
            : `The request could not be completed (HTTP ${response.status}). Refresh the folio and try again.`,
      },
    );
  }
  if (!result)
    throw new ApiError({
      code: "invalid_response",
      message:
        "The API returned an empty response. Refresh to recover the saved folio.",
    });
  return result as T;
}

let sessionPromise: Promise<string> | null = null;
async function sessionHeaders(): Promise<Record<string, string>> {
  sessionPromise ??= request<{ token: string }>("/session")
    .then((session) => session.token)
    .catch((error) => {
      sessionPromise = null;
      throw error;
    });
  return { "X-Crucible-Session": await sessionPromise };
}

async function mutation<T>(
  path: string,
  body: Record<string, unknown>,
): Promise<T> {
  const encoded = JSON.stringify(body);
  try {
    return await request<T>(path, {
      method: "POST",
      headers: await sessionHeaders(),
      body: encoded,
    });
  } catch (error) {
    if (!(error instanceof ApiError) || error.code !== "session_required")
      throw error;
    // This rejection occurs before the action is dispatched. Reuse the same
    // revision and idempotency key after refreshing only the local session.
    sessionPromise = null;
    return request<T>(path, {
      method: "POST",
      headers: await sessionHeaders(),
      body: encoded,
    });
  }
}

export const api = {
  wheat: () => request<WheatStudy>("/wheat"),
  wheatAction: (
    study: WheatStudy,
    action: string,
    body: Record<string, unknown> = {},
    idempotencyKey = crypto.randomUUID(),
  ) =>
    mutation<WheatStudy>(`/wheat/actions/${encodeURIComponent(action)}`, {
      ...body,
      revision: study.revision,
      idempotency_key: idempotencyKey,
    }),
  health: () => request<Health>("/health"),
  folios: () => request<{ folios: FolioSummary[] }>("/folios"),
  folio: (id: string) => request<Folio>(`/folios/${encodeURIComponent(id)}`),
  create: (body: { adapter_id: AdapterId; title?: string; claim?: string }) =>
    mutation<Folio>("/folios", body),
  action: (
    folio: Folio,
    action: Action,
    body: Record<string, unknown> = {},
    idempotencyKey = crypto.randomUUID(),
  ) =>
    mutation<Folio>(
      `/folios/${encodeURIComponent(folio.id)}/actions/${action}`,
      { ...body, revision: folio.revision, idempotency_key: idempotencyKey },
    ),
};

export function artifactUrl(sha: string): string {
  return `/api/artifacts/${encodeURIComponent(sha)}`;
}
export function exportUrl(id: string, format: "report" | "export"): string {
  return `/api/folios/${encodeURIComponent(id)}/${format}`;
}
