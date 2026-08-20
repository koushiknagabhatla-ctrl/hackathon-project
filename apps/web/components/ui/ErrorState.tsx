"use client";

/**
 * ErrorState — what replaces a skeleton the moment a fetch fails. It gives the
 * operator three things a spinner never does: what broke, the correlation id to
 * quote, and a retry button. Never leave a skeleton running on a dead request.
 *
 *   const { data, error, loading, correlationId, reload } = useApi<Plan>(path);
 *   if (error) return <ErrorState error={error} onRetry={reload} correlationId={correlationId} />;
 *
 * `error.offline === true` (ApiError) switches the copy to degraded mode: the
 * rest of the screen stays usable, this panel explains what is missing.
 */

import { ApiError } from "@/lib/api";
import { Icon } from "./Icon";
import { cx } from "@/lib/format";
import s from "./ui.module.css";

export interface ErrorStateProps {
  error: unknown;
  onRetry?: () => void;
  correlationId?: string | null;
  /** What failed, in the operator's words: "incident detail", "plan actions". */
  what?: string;
  className?: string;
}

export function ErrorState({
  error,
  onRetry,
  correlationId,
  what = "this data",
  className,
}: ErrorStateProps) {
  const api = error instanceof ApiError ? error : null;
  const offline = api?.offline ?? false;
  const code = api?.code ?? "unknown_error";
  const message =
    api?.message ?? (error instanceof Error ? error.message : String(error));
  const cid = api?.correlationId ?? correlationId ?? null;

  return (
    <div className={cx(s.state, className)} role="alert">
      <span className={s.stateIcon} aria-hidden="true">
        <Icon name={offline ? "offline" : "critical"} size={20} />
      </span>
      <h3 className={s.stateTitle}>
        {offline ? `The API is unreachable` : `Could not load ${what}`}
      </h3>
      <p className={s.stateBody}>
        {offline
          ? "Auralis is running in degraded mode. Everything already loaded stays usable and nothing you do here is lost, but live values will not update until the connection returns."
          : message}
      </p>
      <pre className={s.diag}>
        {`code: ${code}`}
        {api ? `\nstatus: ${api.status}` : ""}
        {api?.ruleId ? `\nrule: ${api.ruleId}` : ""}
        {cid ? `\ncorrelation-id: ${cid}` : ""}
      </pre>
      {onRetry && (
        <button type="button" className="btn btn--primary" onClick={onRetry}>
          <Icon name="refresh" size={15} />
          Retry
        </button>
      )}
    </div>
  );
}

export default ErrorState;
