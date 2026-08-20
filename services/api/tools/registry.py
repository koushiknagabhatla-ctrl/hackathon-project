"""Signed tool manifests.

Two registration invariants, enforced here and nowhere else:
  * empty sandbox_ref  => rejected (contract invariant 4)
  * write tool with no verification_method => rejected (invariant 7 needs one)

`manifest_for(principal)` returns only the tools that principal's role may
see. Manifest visibility is itself a policy decision, so an agent can never
even see a tool it is not authorised for.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os

from pydantic import BaseModel, Field

from services.api.core import db, policy

# ponytail: local dev HMAC key. Swap for a KMS-held signing key by replacing
# _key() only - the canonical-json payload and verify path stay identical.
_DEV_KEY = os.environ.get("AURALIS_TOOL_SIGNING_KEY", "auralis-dev-tool-key")


class ManifestRejected(ValueError):
    """Registration refused. Never downgrade this to a warning."""


class ToolManifest(BaseModel):
    id: str
    version: str = "1.0.0"
    description: str
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    risk_class: str                      # floor tier; the instance tier is computed
    action_class: str                    # feeds risk.compute_tier
    sandbox_ref: str                     # invariant 4: never empty
    egress_allowlist: list[str] = Field(default_factory=list)
    verification_method: str = ""        # readback | human_confirmation | none
    rollback_tool_id: str | None = None
    allowed_roles: list[str] = Field(default_factory=list)
    reversible: bool = True
    write: bool = False
    public_facing: bool = False
    trust_domain: str = "prod"
    prohibited: bool = False
    signature: str = ""


_REGISTRY: dict[str, ToolManifest] = {}


def _payload(m: ToolManifest) -> str:
    return policy.canonical_json(m.model_dump(exclude={"signature"}))


def sign(m: ToolManifest) -> str:
    return hmac.new(_DEV_KEY.encode(), _payload(m).encode(), hashlib.sha256).hexdigest()


def verify_signature(m: ToolManifest) -> bool:
    return hmac.compare_digest(m.signature, sign(m))


def register(manifest: ToolManifest | dict) -> ToolManifest:
    m = manifest if isinstance(manifest, ToolManifest) else ToolManifest(**manifest)
    if not (m.sandbox_ref or "").strip():
        raise ManifestRejected(
            f"tool '{m.id}' has an empty sandbox_ref: every tool needs a sandbox twin"
        )
    if m.write and not (m.verification_method or "").strip():
        raise ManifestRejected(
            f"write tool '{m.id}' declares no verification_method: an effect that "
            "cannot be read back cannot be closed out"
        )
    m.signature = sign(m)
    _REGISTRY[m.id] = m
    return m


def get(tool_id: str) -> ToolManifest | None:
    return _REGISTRY.get(tool_id)


def require(tool_id: str) -> ToolManifest:
    m = _REGISTRY.get(tool_id)
    if m is None:
        raise ManifestRejected(f"unknown tool '{tool_id}'")
    if not verify_signature(m):
        raise ManifestRejected(f"tool manifest '{tool_id}' failed signature verification")
    return m


def all_manifests() -> list[ToolManifest]:
    return list(_REGISTRY.values())


def manifest_for(principal) -> list[ToolManifest]:
    """Only the tools this principal's role may see.

    A prohibited tool stays visible to its allow-listed roles on purpose: the
    policy engine must refuse it visibly rather than the tool silently not
    existing.
    """
    role = principal["role"] if isinstance(principal, dict) else getattr(principal, "role", "")
    return [
        m for m in _REGISTRY.values()
        if role in m.allowed_roles
        and (m.prohibited or policy.load_bundle().role_permits(role, m.risk_class))
    ]


def visible_to(principal, tool_id: str) -> bool:
    return any(m.id == tool_id for m in manifest_for(principal))


def sync_to_db() -> int:
    """Mirror the in-process registry into tool_manifest for the UI/audit."""
    with db.tx() as c:
        for m in _REGISTRY.values():
            c.execute(
                "INSERT OR REPLACE INTO tool_manifest (id, version, description,"
                " input_schema, output_schema, risk_class, sandbox_ref, egress_allowlist,"
                " verification_method, rollback_tool_id, signature, allowed_roles,"
                " action_class, reversible, write, public_facing, trust_domain, prohibited)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (m.id, m.version, m.description, json.dumps(m.input_schema),
                 json.dumps(m.output_schema), m.risk_class, m.sandbox_ref,
                 json.dumps(m.egress_allowlist), m.verification_method,
                 m.rollback_tool_id, m.signature, json.dumps(m.allowed_roles),
                 m.action_class, int(m.reversible), int(m.write), int(m.public_facing),
                 m.trust_domain, int(m.prohibited)))
    return len(_REGISTRY)


# --------------------------------------------------------------- the tools
_ALL_ROLES = ["auditor", "sim", "agent", "operator", "approver", "admin"]
_ACTORS = ["operator", "approver", "admin"]

_OK = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def _bootstrap() -> None:
    register(ToolManifest(
        id="twin.query", description="Traverse asset dependencies and report blast radius.",
        risk_class="R0", action_class="read", sandbox_ref="sandbox:twin.query",
        verification_method="none", allowed_roles=_ALL_ROLES,
        input_schema={"type": "object",
                      "properties": {"asset_id": {"type": "string"},
                                     "depth": {"type": "integer", "minimum": 0, "maximum": 6}},
                      "required": ["asset_id"]},
        output_schema={"type": "object",
                       "properties": {"root": {"type": "string"},
                                      "nodes": {"type": "array"},
                                      "blast_radius": {"type": "integer"}},
                       "required": ["root", "blast_radius"]},
    ))
    register(ToolManifest(
        id="evidence.get", description="Read one evidence record with provenance.",
        risk_class="R0", action_class="read", sandbox_ref="sandbox:evidence.get",
        verification_method="none", allowed_roles=_ALL_ROLES,
        input_schema={"type": "object", "properties": {"evidence_id": {"type": "string"}},
                      "required": ["evidence_id"]},
        output_schema={"type": "object", "properties": {"id": {"type": "string"},
                                                        "statement": {"type": "string"}},
                       "required": ["id"]},
    ))
    register(ToolManifest(
        id="forecast.run", description="Run the seeded hydrology forecast for an asset.",
        risk_class="R1", action_class="forecast", sandbox_ref="sandbox:forecast.run",
        verification_method="none", allowed_roles=["sim"] + _ACTORS + ["agent"],
        input_schema={"type": "object",
                      "properties": {"asset_id": {"type": "string"},
                                     "horizon_min": {"type": "integer", "minimum": 5, "maximum": 1440},
                                     "seed": {"type": "integer"}},
                      "required": ["asset_id", "horizon_min"]},
        output_schema={"type": "object",
                       "properties": {"median": {"type": "number"}, "p10": {"type": "number"},
                                      "p90": {"type": "number"}, "unit": {"type": "string"}},
                       "required": ["median", "p10", "p90"]},
    ))
    register(ToolManifest(
        id="plan.draft", description="Draft a candidate response plan skeleton.",
        risk_class="R2", action_class="plan", sandbox_ref="sandbox:plan.draft",
        verification_method="none", allowed_roles=["agent"] + _ACTORS,
        input_schema={"type": "object",
                      "properties": {"incident_id": {"type": "string"},
                                     "objective": {"type": "string"}},
                      "required": ["incident_id", "objective"]},
        output_schema={"type": "object", "properties": {"title": {"type": "string"},
                                                        "steps": {"type": "array"}},
                       "required": ["title", "steps"]},
    ))
    register(ToolManifest(
        id="workorder.create", description="Raise a field work order for a qualified operator.",
        risk_class="R3", action_class="workorder", sandbox_ref="sandbox:workorder.create",
        verification_method="readback", rollback_tool_id="workorder.cancel",
        allowed_roles=_ACTORS, write=True, reversible=True,
        input_schema={"type": "object",
                      "properties": {"asset_id": {"type": "string"}, "title": {"type": "string"},
                                     "instructions": {"type": "string"},
                                     "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                                     "incident_id": {"type": "string"}},
                      "required": ["asset_id", "title", "instructions"]},
        output_schema={"type": "object",
                       "properties": {"work_order_id": {"type": "string"},
                                      "status": {"type": "string"}},
                       "required": ["work_order_id", "status"]},
    ))
    register(ToolManifest(
        id="workorder.cancel", description="Cancel a work order raised by workorder.create.",
        risk_class="R3", action_class="workorder", sandbox_ref="sandbox:workorder.cancel",
        verification_method="readback", allowed_roles=_ACTORS, write=True,
        input_schema={"type": "object", "properties": {"work_order_id": {"type": "string"}},
                      "required": ["work_order_id"]},
        output_schema=_OK,
    ))
    register(ToolManifest(
        id="traffic.reroute_advisory",
        description="Publish a routing advisory. R3 for a local link, R4 when public-facing.",
        risk_class="R3", action_class="advisory", sandbox_ref="sandbox:traffic.reroute_advisory",
        verification_method="readback", rollback_tool_id="traffic.restore",
        allowed_roles=_ACTORS, write=True, reversible=True,
        input_schema={"type": "object",
                      "properties": {"asset_id": {"type": "string"},
                                     "advisory": {"type": "string"},
                                     "public_facing": {"type": "boolean"}},
                      "required": ["asset_id", "advisory"]},
        output_schema={"type": "object",
                       "properties": {"asset_id": {"type": "string"},
                                      "advisory": {"type": "string"}},
                       "required": ["asset_id", "advisory"]},
    ))
    register(ToolManifest(
        id="traffic.restore", description="Withdraw a routing advisory.",
        risk_class="R3", action_class="advisory", sandbox_ref="sandbox:traffic.restore",
        verification_method="readback", allowed_roles=_ACTORS, write=True,
        input_schema={"type": "object", "properties": {"asset_id": {"type": "string"}},
                      "required": ["asset_id"]},
        output_schema=_OK,
    ))
    register(ToolManifest(
        id="pump.setpoint", description="Request a pump setpoint change on the twin.",
        risk_class="R3", action_class="actuate", sandbox_ref="sandbox:pump.setpoint",
        verification_method="readback", allowed_roles=_ACTORS, write=True, reversible=True,
        input_schema={"type": "object",
                      "properties": {"asset_id": {"type": "string"},
                                     "setpoint": {"type": "number", "minimum": 0, "maximum": 100},
                                     "unit": {"type": "string"}},
                      "required": ["asset_id", "setpoint"]},
        output_schema={"type": "object",
                       "properties": {"asset_id": {"type": "string"},
                                      "setpoint": {"type": "number"}},
                       "required": ["asset_id", "setpoint"]},
    ))
    register(ToolManifest(
        id="alert.publish_cap",
        description="Publish a CAP public alert. Not automatically reversible: a published "
                    "alert can only be superseded, never unsaid.",
        risk_class="R4", action_class="notify_public", sandbox_ref="sandbox:alert.publish_cap",
        verification_method="human_confirmation", allowed_roles=_ACTORS,
        write=True, reversible=False, public_facing=True,
        input_schema={"type": "object",
                      "properties": {"incident_id": {"type": "string"},
                                     "headline": {"type": "string"},
                                     "severity": {"type": "string",
                                                  "enum": ["Minor", "Moderate", "Severe", "Extreme"]},
                                     "channel": {"type": "string"},
                                     "authority": {"type": "string"}},
                      "required": ["incident_id", "headline", "severity", "authority"]},
        output_schema={"type": "object",
                       "properties": {"publication_id": {"type": "string"},
                                      "status": {"type": "string"}},
                       "required": ["publication_id", "status"]},
    ))
    register(ToolManifest(
        id="network.isolate_segment", description="Isolate a network segment from the estate.",
        risk_class="R4", action_class="isolate", sandbox_ref="sandbox:network.isolate_segment",
        verification_method="readback", rollback_tool_id="network.restore_segment",
        allowed_roles=_ACTORS, write=True, reversible=True,
        input_schema={"type": "object",
                      "properties": {"asset_id": {"type": "string"}, "reason": {"type": "string"}},
                      "required": ["asset_id", "reason"]},
        output_schema={"type": "object",
                       "properties": {"asset_id": {"type": "string"},
                                      "isolated": {"type": "boolean"}},
                       "required": ["asset_id", "isolated"]},
    ))
    register(ToolManifest(
        id="network.restore_segment", description="Return an isolated network segment to service.",
        risk_class="R4", action_class="isolate", sandbox_ref="sandbox:network.restore_segment",
        verification_method="readback", allowed_roles=_ACTORS, write=True, reversible=True,
        input_schema={"type": "object", "properties": {"asset_id": {"type": "string"}},
                      "required": ["asset_id"]},
        output_schema={"type": "object",
                       "properties": {"asset_id": {"type": "string"},
                                      "isolated": {"type": "boolean"}},
                       "required": ["asset_id", "isolated"]},
    ))
    # Registered ONLY so the policy engine can visibly refuse it. Its sandbox
    # always raises and R5_PROHIBITED denies it before execution is reached.
    register(ToolManifest(
        id="scada.direct_control",
        description="Direct SCADA equipment control. Permanently prohibited: Auralis does "
                    "not build direct equipment control. Listed so the refusal is visible.",
        risk_class="R5", action_class="physical_control",
        sandbox_ref="sandbox:scada.direct_control", verification_method="none",
        allowed_roles=["admin"], write=True, reversible=False, prohibited=True,
        input_schema={"type": "object",
                      "properties": {"asset_id": {"type": "string"},
                                     "command": {"type": "string"}},
                      "required": ["asset_id", "command"]},
        output_schema=_OK,
    ))


_bootstrap()
