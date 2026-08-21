"""Fast2SMS India Emergency Advisory & Citizen SMS Dispatch Adapter.

Dispatches real-time SMS emergency advisories directly via Fast2SMS Quick SMS API
to registered disaster management officers and citizen mobile numbers during verified
incidents and early warning broadcasts.

Keeps credentials secure server-side via FAST2SMS_API_KEY.
Zero-fabrication rule: If FAST2SMS_API_KEY is not configured, suppresses transmission
and records honest 'unconfigured' status in the Merkle audit ledger.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from dotenv import load_dotenv

from services.api.core import db

load_dotenv()

log = logging.getLogger("auralis.fast2sms")

FAST2SMS_QUICK_URL = "https://www.fast2sms.com/dev/bulkV2"
FAST2SMS_WALLET_URL = "https://www.fast2sms.com/dev/wallet"


def check_sms_wallet() -> dict[str, Any]:
    """Check active SMS credits and wallet balance from Fast2SMS."""
    key = os.environ.get("FAST2SMS_API_KEY")
    if not key:
        return {"configured": False, "status": "unconfigured", "wallet": 0, "sms_count": 0}

    try:
        with httpx.Client(timeout=6.0) as client:
            resp = client.post(FAST2SMS_WALLET_URL, headers={"authorization": key})
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "configured": True,
                    "status": "ok",
                    "wallet": float(data.get("wallet", 0.0)),
                    "sms_count": int(data.get("sms_count", 0)),
                }
    except Exception as exc:
        log.warning("Fast2SMS wallet check error: %s", exc)
    return {"configured": True, "status": "error", "wallet": 0, "sms_count": 0}


def send_emergency_sms(
    to_phone: str,
    message_text: str,
    incident_id: str,
    recipient_category: str = "disaster_officer",
    tenant_id: str = "ten_vijayawada",
) -> dict[str, Any]:
    """Send an emergency SMS via Fast2SMS Quick Route, recording the transmission in the audit ledger."""
    key = os.environ.get("FAST2SMS_API_KEY")
    notif_id = f"sms_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    # Clean phone number (extract digits, ensure 10 digits for Indian numbers)
    clean_phone = "".join(filter(str.isdigit, to_phone))
    if len(clean_phone) > 10 and clean_phone.startswith("91"):
        clean_phone = clean_phone[2:]

    if not key:
        status = "suppressed_unconfigured"
        reason = "FAST2SMS_API_KEY is not configured."
        with db.tx() as c:
            c.execute(
                "INSERT INTO emergency_notification(id, tenant_id, incident_id, channel, "
                "recipient_id, recipient_category, message_text, status, failure_reason, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (notif_id, tenant_id, incident_id, "fast2sms", to_phone, recipient_category,
                 message_text, "failed", reason, now),
            )
        return {
            "id": notif_id,
            "channel": "fast2sms",
            "recipient": to_phone,
            "status": "unconfigured",
            "reason": reason,
        }

    try:
        # Fast2SMS Quick SMS route ('q') requires message & numbers
        payload = {
            "route": "q",
            "message": message_text[:160],  # Standard single SMS length
            "language": "english",
            "flash": 0,
            "numbers": clean_phone,
        }
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(
                FAST2SMS_QUICK_URL,
                headers={"authorization": key},
                json=payload,
            )
            data = resp.json() if resp.status_code == 200 else {}

        if resp.status_code == 200 and data.get("return") is True:
            with db.tx() as c:
                c.execute(
                    "INSERT INTO emergency_notification(id, tenant_id, incident_id, channel, "
                    "recipient_id, recipient_category, message_text, status, provider_ref, created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (notif_id, tenant_id, incident_id, "fast2sms", to_phone, recipient_category,
                     message_text, "sent", str(data.get("request_id")), now),
                )
            return {
                "id": notif_id,
                "channel": "fast2sms",
                "recipient": to_phone,
                "status": "sent",
                "request_id": data.get("request_id"),
                "message": data.get("message", ["SMS dispatched successfully"])[0],
            }
        else:
            err_msg = str(data.get("message", [f"HTTP {resp.status_code}"])[0])
            with db.tx() as c:
                c.execute(
                    "INSERT INTO emergency_notification(id, tenant_id, incident_id, channel, "
                    "recipient_id, recipient_category, message_text, status, failure_reason, created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (notif_id, tenant_id, incident_id, "fast2sms", to_phone, recipient_category,
                     message_text, "failed", err_msg, now),
                )
            return {
                "id": notif_id,
                "channel": "fast2sms",
                "recipient": to_phone,
                "status": "failed",
                "reason": err_msg,
            }
    except Exception as exc:
        log.exception("Fast2SMS dispatch failed")
        with db.tx() as c:
            c.execute(
                "INSERT INTO emergency_notification(id, tenant_id, incident_id, channel, "
                "recipient_id, recipient_category, message_text, status, failure_reason, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (notif_id, tenant_id, incident_id, "fast2sms", to_phone, recipient_category,
                 message_text, "failed", str(exc), now),
            )
        return {
            "id": notif_id,
            "channel": "fast2sms",
            "recipient": to_phone,
            "status": "failed",
            "reason": str(exc),
        }


def send_sms(to_phone: str, message_text: str) -> dict[str, Any]:
    """Send one SMS. Transport only — the caller records the outcome.

    Returns {ok, provider_ref, error}. Never raises: a failed alert send must
    not take down the dispatch loop that is trying to warn people.
    """
    key = os.environ.get("FAST2SMS_API_KEY")
    if not key:
        return {"ok": False, "provider_ref": None,
                "error": "FAST2SMS_API_KEY is not configured"}

    digits = "".join(filter(str.isdigit, to_phone))
    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) != 10:
        return {"ok": False, "provider_ref": None,
                "error": f"not a 10-digit Indian number: {to_phone}"}

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                FAST2SMS_QUICK_URL,
                headers={"authorization": key},
                json={
                    "route": "q",
                    "message": message_text[:160],
                    "language": "english",
                    "flash": 0,
                    "numbers": digits,
                },
            )
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code == 200 and data.get("return") is True:
            return {"ok": True,
                    "provider_ref": str((data.get("request_id") or "")),
                    "error": None}
        return {"ok": False, "provider_ref": None,
                "error": f"HTTP {resp.status_code}: {str(data or resp.text)[:160]}"}
    except Exception as exc:
        return {"ok": False, "provider_ref": None,
                "error": f"{type(exc).__name__}: {exc}"}
