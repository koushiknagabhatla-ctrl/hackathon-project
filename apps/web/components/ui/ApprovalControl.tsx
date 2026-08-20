"use client";

/**
 * ApprovalControl — the human authority moment. This is the component the
 * whole product is judged on, so it never guesses:
 *
 *  - BLOCKED  policy effect "deny" -> the exact rule_id and reason are shown,
 *             the controls are inert, and no amount of clicking overrides it.
 *  - CHECKING policy is being re-evaluated -> controls inert, state announced.
 *  - BUSY     a decision is in flight -> spinner, controls inert, aria-busy.
 *  - DECIDED  the action already moved on -> outcome shown, no controls.
 *  - OPEN     approve / deny. Denial always requires a rationale; approval
 *             requires one at R3 and above.
 *
 *   <ApprovalControl
 *     action={action}
 *     onDecision={async ({ decision, rationale }) =>
 *       api.post(`/v1/plans/${planId}/approve`, { action_id: action.id, decision, rationale })}
 *   />
 */

import { useId, useState } from "react";
import type { Action, PolicyDecision } from "@/lib/types";
import { Icon } from "./Icon";
import { RiskBadge } from "./RiskBadge";
import { cx } from "@/lib/format";
import s from "./ui.module.css";

export interface ApprovalDecision {
  decision: "approved" | "denied";
  rationale: string;
}

export interface ApprovalControlProps {
  action: Action;
  onDecision: (d: ApprovalDecision) => Promise<void> | void;
  /** Fresher policy decision than the one embedded in the action, if any. */
  policy?: PolicyDecision | null;
  /** Caller-driven busy, e.g. the plan is executing. */
  busy?: boolean;
  /** Policy is being re-evaluated right now. */
  checking?: boolean;
  /** Dual-control / delegation note shown above the controls. */
  note?: string;
  className?: string;
}

const DECIDED: Action["status"][] = [
  "approved",
  "executing",
  "executed",
  "verified",
  "difference",
  "failed",
  "unknown",
  "rolled_back",
];

export function ApprovalControl({
  action,
  onDecision,
  policy,
  busy,
  checking,
  note,
  className,
}: ApprovalControlProps) {
  const [rationale, setRationale] = useState("");
  const [pending, setPending] = useState<"approved" | "denied" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fieldId = useId();

  const decision = policy ?? action.policy_decision ?? null;
  const blocked = decision?.effect === "deny" || action.status === "blocked";
  const decided = DECIDED.includes(action.status);
  const working = Boolean(busy) || pending !== null;
  const inert = blocked || decided || working || Boolean(checking);

  // Approval of anything at R3+ must be reasoned. Denial always must be.
  const highRisk = ["R3", "R4", "R5"].includes(action.risk_tier);

  async function submit(d: "approved" | "denied") {
    if (inert) return;
    if ((d === "denied" || highRisk) && rationale.trim().length < 8) {
      setError(
        d === "denied"
          ? "A denial needs a rationale. It goes in the audit ledger."
          : `Approving ${action.risk_tier} needs a rationale. It goes in the audit ledger.`,
      );
      return;
    }
    setError(null);
    setPending(d);
    try {
      await onDecision({ decision: d, rationale: rationale.trim() });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(null);
    }
  }

  return (
    <section
      className={cx(s.approval, className)}
      aria-busy={working || Boolean(checking)}
      aria-label={`Authorisation for action ${action.id}`}
    >
      <header className={s.approvalHead}>
        <span className={s.claimKind}>
          <Icon name="shield" size={15} />
          Authorisation
        </span>
        <RiskBadge
          tier={action.risk_tier}
          reason={
            typeof action.risk_inputs?.blast_radius === "number"
              ? `blast radius ${action.risk_inputs.blast_radius}`
              : undefined
          }
        />
      </header>

      {blocked && decision && (
        <div className={s.approvalRule} role="alert">
          <span className={s.statusText} style={{ color: "var(--bad)" }}>
            <Icon name="lock" size={13} /> Blocked by policy
          </span>
          <span className={s.approvalRuleId}>
            {decision.rule_id} · bundle {decision.bundle_version}
          </span>
          <p className={s.approvalReason}>{decision.reason}</p>
          <p className={s.hint}>
            This is a deterministic policy outcome. It cannot be overridden from
            this screen — change the action, the target or the evidence.
          </p>
        </div>
      )}

      {blocked && !decision && (
        <div className={s.approvalRule} role="alert">
          <span className={s.statusText} style={{ color: "var(--bad)" }}>
            <Icon name="lock" size={13} /> Blocked
          </span>
          <p className={s.approvalReason}>
            The action is blocked but no policy decision reached this screen.
            Open the decision log before proceeding.
          </p>
        </div>
      )}

      {!blocked && decision && (
        <p className={s.hint}>
          <Icon name={decision.effect === "allow" ? "check" : "shield"} size={13} />{" "}
          Policy <strong>{decision.effect.replace("_", " ")}</strong> ·{" "}
          {decision.rule_id} — {decision.reason}
        </p>
      )}

      {checking && (
        <p className={s.hint} role="status">
          <span className={s.spinner} aria-hidden="true" /> Re-checking policy…
        </p>
      )}

      {decided && (
        <p className={s.hint} role="status">
          <Icon name="check" size={13} /> Already {action.status.replace("_", " ")}
          {action.executed_at ? ` at ${action.executed_at}` : ""}.
        </p>
      )}

      {note && <p className={s.hint}>{note}</p>}

      {!decided && (
        <div>
          <label className={s.fieldLabel} htmlFor={fieldId}>
            Rationale {highRisk ? "(required)" : "(required to deny)"}
          </label>
          <textarea
            id={fieldId}
            className={s.rationale}
            value={rationale}
            disabled={inert}
            onChange={(e) => setRationale(e.target.value)}
            placeholder="Why this decision, in one or two lines. Recorded in the audit ledger."
          />
        </div>
      )}

      {error && (
        <p className={s.approvalReason} role="alert" style={{ color: "var(--bad)" }}>
          <Icon name="critical" size={13} /> {error}
        </p>
      )}

      {!decided && (
        <div className={s.approvalActions}>
          <button
            type="button"
            className="btn btn--primary"
            aria-disabled={inert}
            disabled={inert}
            onClick={() => submit("approved")}
          >
            {pending === "approved" ? (
              <span className={s.spinner} aria-hidden="true" />
            ) : (
              <Icon name="check" size={15} />
            )}
            Approve
          </button>
          <button
            type="button"
            className="btn"
            aria-disabled={inert}
            disabled={inert}
            onClick={() => submit("denied")}
          >
            {pending === "denied" ? (
              <span className={s.spinner} aria-hidden="true" />
            ) : (
              <Icon name="close" size={15} />
            )}
            Deny
          </button>
        </div>
      )}

      <p className="sr-only" role="status">
        {blocked
          ? `Action blocked by policy rule ${decision?.rule_id ?? "unknown"}.`
          : working
            ? "Submitting decision."
            : decided
              ? `Action already ${action.status}.`
              : "Awaiting your decision."}
      </p>
    </section>
  );
}

export default ApprovalControl;
