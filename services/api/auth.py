"""Authentication and exception models for Auralis API."""

from __future__ import annotations

from typing import Any

from fastapi import Header, HTTPException


class PolicyDenied(Exception):
    """Raised by the tool gateway. Rendered as 403 with the exact rule id."""

    def __init__(self, rule_id: str, reason: str, detail: Any = None):
        self.rule_id = rule_id
        self.reason = reason
        self.detail = detail
        super().__init__(f"{rule_id}: {reason}")


def get_principal(x_auralis_principal: str | None = Header(default=None)) -> dict[str, Any]:
    """Resolve calling identity from X-Auralis-Principal header."""
    from services.api.core import db

    if not x_auralis_principal:
        raise HTTPException(status_code=401, detail="X-Auralis-Principal header required")
    row = db.get_conn().execute(
        "SELECT * FROM principal WHERE id = ?", (x_auralis_principal,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="unknown principal")
    if row["status"] != "active":
        raise HTTPException(status_code=403, detail="principal revoked")
    return dict(row)
