"use client";

/**
 * lib/api.ts — the only path from the web app to the Auralis API.
 *
 * Lane E usage:
 *   const { data, error, loading, correlationId, reload } = useApi<Plan>(`/v1/plans/${id}`);
 *   await api.post<Plan>(`/v1/plans/${id}/approve`, { action_id, decision, rationale });
 *   const { events, status } = useStream();        // SSE, degrades to "degraded"
 *
 * Every request sends X-Auralis-Principal and surfaces X-Correlation-Id.
 * Nothing here throws on a dead API: callers get `error` and the UI stays usable.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiErrorBody, Role, StreamEvent, StreamEventType } from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

/** Where the API lives. Needed for <img src> on binary endpoints such as
 *  camera snapshots, which cannot go through the JSON fetch helper. */
export const API_ORIGIN = API_BASE;

const PRINCIPAL_KEY = "auralis.principal";
const DEFAULT_PRINCIPAL =
  process.env.NEXT_PUBLIC_PRINCIPAL ?? "p_operator";

/** Demo principals, one per role. Swap ids here if Lane F seeds different ones. */
export const PRINCIPALS: Record<Role, string> = {
  operator: "p_operator",
  approver: "p_approver",
  auditor: "p_auditor",
  admin: "p_admin",
  agent: "p_agent",
  sim: "p_sim",
};

export function getPrincipal(): string {
  if (typeof window === "undefined") return DEFAULT_PRINCIPAL;
  // Truthiness, not ??: a stored empty string is not a principal, and sending
  // one as the header is an immediate 401.
  const stored = window.localStorage.getItem(PRINCIPAL_KEY);
  return stored && stored.trim() ? stored : DEFAULT_PRINCIPAL;
}

export function setPrincipal(id: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(PRINCIPAL_KEY, id);
  window.dispatchEvent(new CustomEvent("auralis:principal", { detail: id }));
}

/** Typed API failure. `correlationId` is always populated when the server answered. */
export class ApiError extends Error {
  code: string;
  status: number;
  detail: unknown;
  correlationId: string | null;
  ruleId?: string;
  reason?: string;

  constructor(init: {
    code: string;
    message: string;
    status: number;
    detail?: unknown;
    correlationId?: string | null;
    ruleId?: string;
    reason?: string;
  }) {
    super(init.message);
    this.name = "ApiError";
    this.code = init.code;
    this.status = init.status;
    this.detail = init.detail;
    this.correlationId = init.correlationId ?? null;
    this.ruleId = init.ruleId;
    this.reason = init.reason;
  }

  /** True when the API is unreachable rather than refusing — drives degraded mode. */
  get offline() {
    return this.status === 0;
  }
}

export interface ApiResult<T> {
  data: T;
  correlationId: string | null;
  status: number;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<ApiResult<T>> {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers: {
        Accept: "application/json",
        "X-Auralis-Principal": getPrincipal(),
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(init.headers ?? {}),
      },
      cache: "no-store",
    });
  } catch (e) {
    throw new ApiError({
      code: "source_unavailable",
      message: `Live data source unreachable at ${API_BASE}. System refuses to display fabricated placeholder data.`,
      status: 0,
      detail: e instanceof Error ? e.message : String(e),
    });
  }

  const correlationId = res.headers.get("X-Correlation-Id");
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!res.ok) {
    const err = (body as ApiErrorBody | null)?.error;
    throw new ApiError({
      code: err?.code ?? `http_${res.status}`,
      message: err?.message ?? res.statusText ?? "Request failed",
      status: res.status,
      detail: err?.detail ?? body,
      correlationId: err?.correlation_id ?? correlationId,
      ruleId: err?.rule_id,
      reason: err?.reason,
    });
  }

  return { data: body as T, correlationId, status: res.status };
}

export const api = {
  raw: request,
  async get<T>(path: string, init?: RequestInit): Promise<T> {
    return (await request<T>(path, { ...init, method: "GET" })).data;
  },
  async post<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
    return (
      await request<T>(path, {
        ...init,
        method: "POST",
        body: body === undefined ? undefined : JSON.stringify(body),
      })
    ).data;
  },
};

/** A fresh idempotency key. Every write tool call must carry one (invariant 8). */
export function idempotencyKey(prefix = "web"): string {
  const rand =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2);
  return `${prefix}_${rand}`;
}

// ------------------------------------------------------------------ hooks

export interface UseApiResult<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  correlationId: string | null;
  reload: () => void;
}

/**
 * GET a path. Never throws. `error.offline === true` means degraded mode:
 * render the shell, the last-known data and a clear degraded banner.
 * Pass `path = null` to skip the fetch (conditional loading).
 */
export function useApi<T>(path: string | null, deps: unknown[] = []): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState<boolean>(path !== null);
  const [correlationId, setCorrelationId] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!path) {
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    request<T>(path)
      .then((r) => {
        if (!alive) return;
        setData(r.data);
        setCorrelationId(r.correlationId);
        setError(null);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(
          e instanceof ApiError
            ? e
            : new ApiError({
                code: "unknown",
                message: String(e),
                status: 0,
              }),
        );
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, nonce, ...deps]);

  return { data, error, loading, correlationId, reload };
}

export type StreamStatus = "connecting" | "live" | "degraded";

export interface UseStreamResult {
  events: StreamEvent[];
  last: StreamEvent | null;
  status: StreamStatus;
  /** Attempt count since the last successful open. */
  retries: number;
}

const STREAM_TYPES: StreamEventType[] = [
  "incident",
  "action",
  "evidence",
  "health",
  "audit",
  "ping",
];

/**
 * SSE subscription to /v1/stream.
 *
 * EventSource cannot send headers, so the principal travels as a query param
 * (`?principal=`) in addition to the header used by every other call.
 * If the API is down the hook reports `status: "degraded"`, keeps retrying with
 * backoff, and the UI must stay fully usable on cached/SSR data.
 */
export function useStream(limit = 200): UseStreamResult {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [retries, setRetries] = useState(0);
  const retryRef = useRef(0);

  useEffect(() => {
    if (typeof window === "undefined" || typeof EventSource === "undefined") {
      setStatus("degraded");
      return;
    }
    let es: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const push = (type: StreamEventType, raw: string) => {
      let parsed: unknown = raw;
      try {
        parsed = JSON.parse(raw);
      } catch {
        /* keep the raw string */
      }
      if (type === "ping") return;
      setEvents((prev) =>
        [
          ...prev,
          { type, data: parsed, received_at: new Date().toISOString() },
        ].slice(-limit),
      );
    };

    const connect = () => {
      if (closed) return;
      const url = `${API_BASE}/v1/stream?principal=${encodeURIComponent(getPrincipal())}`;
      es = new EventSource(url);
      es.onopen = () => {
        retryRef.current = 0;
        setRetries(0);
        setStatus("live");
      };
      // default unnamed frames
      es.onmessage = (e) => push("health", e.data);
      for (const t of STREAM_TYPES) {
        es.addEventListener(t, (e) => push(t, (e as MessageEvent).data));
      }
      es.onerror = () => {
        es?.close();
        es = null;
        setStatus("degraded");
        retryRef.current += 1;
        setRetries(retryRef.current);
        const delay = Math.min(1000 * 2 ** (retryRef.current - 1), 30_000);
        timer = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      es?.close();
    };
  }, [limit]);

  return {
    events,
    last: events.length ? events[events.length - 1] : null,
    status,
    retries,
  };
}
