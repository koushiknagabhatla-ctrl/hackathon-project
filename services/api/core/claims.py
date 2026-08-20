"""Claims ledger. INVARIANT 1 is enforced here, server-side.

A claim of class `fact` or `forecast` MUST carry a non-empty evidence_ids and
every id MUST exist in the evidence table. This is a hard check on the write
path, not prompt text: an agent that was told not to do it and does it anyway
still gets a ValueError and no row.
"""

from __future__ import annotations

from typing import Any

from services.api.models import Claim, Uncertainty

from . import audit, db

GROUNDED_CLASSES = ("fact", "forecast")


class UngroundedClaim(ValueError):
    """Invariant 1 violation. Subclasses ValueError so callers can catch either."""


def check_grounding(claim_class: str, evidence_ids: list[str]) -> None:
    """The whole of invariant 1, in one place, callable before you build a row."""
    if claim_class in GROUNDED_CLASSES and not evidence_ids:
        raise UngroundedClaim(
            f"ungrounded {claim_class} claim: evidence_ids is empty (invariant 1)"
        )
    for ev_id in evidence_ids or []:
        if db.q1("SELECT 1 FROM evidence WHERE id=?", ev_id) is None:
            raise UngroundedClaim(
                f"claim cites evidence that does not exist: {ev_id} (invariant 1)"
            )


def create_claim(
    tenant_id: str,
    statement: str,
    subject: str,
    predicate: str,
    object: str,
    claim_class: str,
    evidence_ids: list[str],
    author: str,
    author_kind: str = "agent",
    incident_id: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    confidence_basis: str | None = None,
    uncertainty: Uncertainty | dict[str, Any] | None = None,
    workflow_id: str | None = None,
) -> Claim:
    evidence_ids = list(evidence_ids or [])
    check_grounding(claim_class, evidence_ids)

    valid_from = valid_from or db.now_iso()
    if not valid_to and evidence_ids:
        # a grounded claim is valid no longer than the evidence holding it up
        valid_to = db.scalar(
            "SELECT MAX(expires_at) FROM evidence WHERE id IN (%s)"
            % ",".join("?" * len(evidence_ids)), *evidence_ids) or ""
    unc = uncertainty.model_dump() if isinstance(uncertainty, Uncertainty) else uncertainty
    claim = Claim(  # the model re-checks invariant 1 on the way out
        id=db.new_id("cl"), incident_id=incident_id, statement=statement, subject=subject,
        predicate=predicate, object=object, claim_class=claim_class, valid_from=valid_from,
        valid_to=valid_to or "", evidence_ids=evidence_ids, confidence_basis=confidence_basis,
        uncertainty=Uncertainty(**unc) if unc else None, author=author, author_kind=author_kind,
    )
    with db.tx() as c:
        c.execute(
            "INSERT INTO claim(id,tenant_id,incident_id,statement,subject,predicate,object,"
            "claim_class,valid_from,valid_to,evidence_ids,confidence_basis,uncertainty,"
            "author,author_kind,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                claim.id, tenant_id, incident_id, statement, subject, predicate, object,
                claim_class, claim.valid_from, claim.valid_to, db.jdump(evidence_ids),
                confidence_basis, db.jdump(unc) if unc else None, author, author_kind,
                claim.status,
            ),
        )
        audit.append(
            tenant_id, workflow_id or incident_id or claim.id, author, author_kind,
            "claim.created", claim.id,
            {"claim_class": claim_class, "statement": statement,
             "evidence_ids": evidence_ids, "incident_id": incident_id,
             "confidence_basis": confidence_basis, "uncertainty": unc},
        )
    return claim


def from_row(row: Any) -> Claim:
    unc = db.jload(row["uncertainty"])
    return Claim(
        id=row["id"], incident_id=row["incident_id"], statement=row["statement"],
        subject=row["subject"], predicate=row["predicate"], object=row["object"],
        claim_class=row["claim_class"], valid_from=row["valid_from"], valid_to=row["valid_to"],
        evidence_ids=db.jload(row["evidence_ids"], []), confidence_basis=row["confidence_basis"],
        uncertainty=Uncertainty(**unc) if unc else None, author=row["author"],
        author_kind=row["author_kind"], status=row["status"],
    )


def set_status(
    claim_id: str, status: str, reason: str, actor_id: str = "svc.claims",
    actor_kind: str = "service", workflow_id: str | None = None,
) -> Claim:
    """flagged / retracted / active. Status changes, rows never disappear."""
    row = db.q1("SELECT * FROM claim WHERE id=?", claim_id)
    if row is None:
        raise ValueError(f"unknown claim: {claim_id}")
    with db.tx() as c:
        c.execute("UPDATE claim SET status=? WHERE id=?", (status, claim_id))
        audit.append(
            row["tenant_id"], workflow_id or row["incident_id"] or claim_id, actor_id,
            actor_kind, f"claim.{status}", claim_id,
            {"reason": reason, "previous_status": row["status"]},
        )
    return from_row(db.q1("SELECT * FROM claim WHERE id=?", claim_id))
