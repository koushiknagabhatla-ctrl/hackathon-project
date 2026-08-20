"""Evidence agent: finds evidence that is STALE, CONFLICTING or INSUFFICIENT.

This is the agent that makes the evidence-conflict moment work. Detection is
DETERMINISTIC and runs before the model: two sources disagreeing beyond the
per-metric tolerance in `core/evidence.py` is arithmetic, not judgement. The
model only writes the summary sentence around findings that already exist.

FORBIDDEN ZONE, enforced in code:
  * no tools, `writes=False` - it cannot re-poll a source or retract a record;
  * it does not RESOLVE conflicts. It reports both values, both sources and
    both trust tiers. Nothing here averages, blends or splits a difference -
    `core/evidence.py::PRECEDENCE` decides, deterministically, outside this
    agent, and an equal-tier disagreement escalates to a human instead.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from services.api.core import evidence as ev_mod

from . import base, llm_gateway
from .base import AgentSpec, ClaimDraft, RunContext

SPEC = AgentSpec(
    id="evidence-agent",
    version="1.0.0",
    owner="data.governance",
    scope="staleness, conflicts and sufficiency of the evidence set",
    forbidden=(
        "no writes; may not resolve a conflict, average two readings, or "
        "clear a blocking finding"
    ),
    template="evidence",
    allowed_domains=("evidence",),
    allowed_tools=(),
    runtime_budget_s=20.0,
    tool_call_budget=0,
    writes=False,
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string",
                             "enum": ["stale", "conflict", "insufficient"]},
                    "subject": {"type": "string"},
                    "detail": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "severity": {"type": "string",
                                 "enum": ["info", "warning", "blocking"]},
                    "suggested_resolution": {"type": "string"},
                },
                "required": ["kind", "subject", "detail", "evidence_ids",
                             "severity", "suggested_resolution"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "findings"],
    "additionalProperties": False,
}

PRECEDENCE = list(getattr(ev_mod, "PRECEDENCE",
                          ["statutory", "certified", "verified",
                           "crowdsourced", "unknown"]))
# metrics the response depends on. Absence of one of these is a finding.
REQUIRED_METRICS = ("rainfall", "water_level")


class Finding(BaseModel):
    kind: str
    subject: str
    detail: str
    evidence_ids: list[str] = Field(default_factory=list)
    severity: str = "warning"
    suggested_resolution: str = ""


class EvidenceOutput(BaseModel):
    summary: str = ""
    findings: list[dict[str, Any]] = Field(default_factory=list)
    blocking: bool = False
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    positions: list[dict[str, Any]] = Field(default_factory=list)


# ------------------------------------------------- deterministic detection
def _tier(item: dict[str, Any]) -> int:
    t = str(item.get("trust_tier", "unknown"))
    return PRECEDENCE.index(t) if t in PRECEDENCE else len(PRECEDENCE)


def detect(snapshot: base.Snapshot) -> list[dict[str, Any]]:
    """Arithmetic, not judgement. Runs before the model and is authoritative."""
    items = [dict(e) for e in snapshot.evidence]
    valid = [e for e in items if e.get("status") == "valid"]
    findings: list[dict[str, Any]] = []

    if not valid:
        return [Finding(
            kind="insufficient", subject="incident",
            detail="No valid evidence is attached to this incident at all.",
            evidence_ids=[], severity="blocking",
            suggested_resolution="Do not act. Establish at least one verified "
                                 "observation before planning.",
        ).model_dump()]

    # --- stale -------------------------------------------------------------
    for e in valid:
        expired = bool(e.get("expires_at")) and e["expires_at"] < snapshot.taken_at
        if e.get("fresh") is False or expired:
            findings.append(Finding(
                kind="stale", subject=str((e.get("value") or {}).get("subject") or e["id"]),
                detail=(
                    f"{e.get('source')} last observed at {e.get('observed_at')}, "
                    f"{e.get('age_s')}s before the snapshot"
                    + (f", past its expiry {e.get('expires_at')}" if expired else "")
                    + ". Any action depending on it is risk-escalated by core/risk.py."
                ),
                evidence_ids=[e["id"]], severity="warning",
                suggested_resolution=f"Re-poll {e.get('source')} or mark the feed degraded.",
            ).model_dump())

    # --- conflicting -------------------------------------------------------
    by_subject: dict[str, list[dict[str, Any]]] = {}
    for e in valid:
        val = e.get("value") or {}
        if isinstance(val.get("value"), (int, float)):
            by_subject.setdefault(str(val.get("subject") or val.get("metric")), []).append(e)

    for subject, group in sorted(by_subject.items()):
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                va = float(a["value"]["value"])
                vb = float(b["value"]["value"])
                metric = str(a["value"].get("metric", ""))
                tol = ev_mod.tolerance_for(metric, va, vb)
                if abs(va - vb) <= tol:
                    continue
                ta, tb = _tier(a), _tier(b)
                unit = a["value"].get("unit", "")
                if ta == tb:
                    sev = "blocking"
                    res = (
                        f"Equal trust tier ({a.get('trust_tier')}): source "
                        f"precedence cannot separate these. ESCALATE TO A HUMAN. "
                        f"Do not average them - {(va + vb) / 2:g} {unit} is a "
                        f"number neither source ever reported."
                    )
                else:
                    win, lose = (a, b) if ta < tb else (b, a)
                    sev = "warning"
                    res = (
                        f"Deterministic source precedence ({ev_mod.PRECEDENCE_RULE}): "
                        f"{win.get('source')} ({win.get('trust_tier')}) takes "
                        f"precedence over {lose.get('source')} "
                        f"({lose.get('trust_tier')}). The losing reading stays on "
                        f"the record; it simply does not win."
                    )
                findings.append(Finding(
                    kind="conflict", subject=subject,
                    detail=(
                        f"{a.get('source')} reports {va:g} {unit} "
                        f"({a.get('trust_tier')}, {a['id']}) while "
                        f"{b.get('source')} reports {vb:g} {unit} "
                        f"({b.get('trust_tier')}, {b['id']}) for {subject}. "
                        f"They differ by {abs(va - vb):g} {unit}, beyond the "
                        f"{tol:g} {unit} tolerance for {metric or 'this metric'}."
                    ),
                    evidence_ids=[a["id"], b["id"]], severity=sev,
                    suggested_resolution=res,
                ).model_dump())

    # --- insufficient ------------------------------------------------------
    present = {(e.get("value") or {}).get("metric") for e in valid}
    for metric in REQUIRED_METRICS:
        if metric not in present:
            findings.append(Finding(
                kind="insufficient", subject=metric,
                detail=(
                    f"No valid evidence for {metric}, which the flood forecast "
                    f"requires. The forecast will abstain rather than assume it."
                ),
                evidence_ids=[], severity="blocking",
                suggested_resolution=f"Obtain a {metric} reading before relying on "
                                     f"any projection.",
            ).model_dump())

    for metric in sorted(m for m in present if m):
        group = [e for e in valid if (e.get("value") or {}).get("metric") == metric]
        low = [e for e in group if _tier(e) >= PRECEDENCE.index("crowdsourced")]
        if len(group) == 1 and low:
            findings.append(Finding(
                kind="insufficient", subject=metric,
                detail=(
                    f"{metric} rests on a single {group[0].get('trust_tier')} "
                    f"source ({group[0].get('source')}, {group[0]['id']}) with no "
                    f"corroboration."
                ),
                evidence_ids=[group[0]["id"]], severity="warning",
                suggested_resolution=f"Corroborate {metric} from a certified or "
                                     f"statutory source before acting on it.",
            ).model_dump())

    # --- injection attempts are themselves a finding -----------------------
    for e in valid:
        blob = " ".join(str(v) for v in (e.get("statement", ""), e.get("value", "")))
        flags = llm_gateway.screen(blob)
        if flags:
            findings.append(Finding(
                kind="conflict", subject="prompt_injection",
                detail=(
                    f"Evidence {e['id']} from {e.get('source')} "
                    f"({e.get('trust_tier')}) contains text shaped like an "
                    f"instruction to an AI system: {', '.join(flags)}. It was "
                    f"neutralised before any model saw it. Treat the record as "
                    f"data of questionable provenance."
                ),
                evidence_ids=[e["id"]], severity="blocking",
                suggested_resolution=(
                    "Quarantine the record and review the submitting channel. "
                    "No plan may depend on it."
                ),
            ).model_dump())

    return findings


def deterministic(variables: dict[str, Any]) -> dict[str, Any]:
    findings = list(variables.get("findings_json") or [])
    if not findings:
        return {
            "summary": (
                "The evidence set is internally consistent: nothing stale, no "
                "numeric disagreement beyond tolerance, and every metric the "
                "response depends on is present."
            ),
            "findings": [],
        }
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1
    blocking = [f for f in findings if f.get("severity") == "blocking"]
    parts = [
        f"{len(findings)} evidence problem(s): "
        + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())) + "."
    ]
    if blocking:
        parts.append(
            f"{len(blocking)} of them BLOCK confident action: "
            + "; ".join(f"{b['subject']} - {b['detail']}" for b in blocking[:3])
        )
        parts.append(
            "No value has been reconciled or averaged. Where trust tiers differ, "
            "deterministic source precedence applies; where they are equal, a "
            "human must adjudicate."
        )
    else:
        parts.append(
            "None of them block action, but each escalates the risk tier of any "
            "action that depends on the affected evidence."
        )
    return {"summary": " ".join(parts), "findings": findings}


class EvidenceAgent(base.Agent):
    spec = SPEC

    def _work(self, ctx: RunContext):
        findings = detect(ctx.snapshot)
        variables = base.prompt_vars(ctx, SPEC, SCHEMA, findings_json=findings)
        res = llm_gateway.complete(
            ctx.workflow_id, SPEC.id, SPEC.template, variables, SCHEMA,
            fallback=deterministic, tenant_id=ctx.tenant_id,
            incident_id=ctx.incident_id, snapshot_id=ctx.snapshot.id,
        )

        # The DETERMINISTIC findings are authoritative. The model may reword the
        # summary; it may not add, remove or re-grade a finding.
        blocking = any(f.get("severity") == "blocking" for f in findings)
        conflicts = [f for f in findings if f["kind"] == "conflict"]
        out = EvidenceOutput(
            summary=str(res.parsed.get("summary", "")),
            findings=findings, blocking=blocking, conflicts=conflicts,
            positions=base.positions(ctx.snapshot, SPEC.id),
        )

        drafts = [
            ClaimDraft(
                statement=f["detail"],
                # a finding citing evidence is a fact ABOUT the evidence set;
                # one citing nothing (a missing metric) can only be a
                # recommendation, and the gate enforces exactly that.
                claim_class="fact" if f["evidence_ids"] else "recommendation",
                subject=f["subject"], predicate=f"evidence_{f['kind']}",
                object=f["severity"], evidence_ids=list(f["evidence_ids"]),
                confidence_basis=(
                    f"deterministic detection over snapshot {ctx.snapshot.id}; "
                    f"resolution: {f['suggested_resolution']}"
                ),
            )
            for f in findings
        ]
        return out, drafts, res.degraded, res.prompt_version, res.model_version
