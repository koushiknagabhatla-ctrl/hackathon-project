"""Twilio SMS Provider Adapter.

Sends SMS notifications strictly to authorized emergency responders and consenting
registered emergency contacts during verified critical incidents.

Keeps all credentials server-side.
Zero-fabrication rule: If Twilio credentials are not supplied, the adapter reports
'unconfigured' and suppresses transmission. It never pretends an SMS was sent.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from services.api.core import db

log = logging.getLogger(__name__)


def send_emergency_sms(
    to_phone: str,
    message_text: str,
    incident_id: str,
    recipient_category: str = "disaster_officer",
    tenant_id: str = "ten_vijayawada",
) -> dict[str, Any]:
    """Send an emergency SMS via Twilio API, recording the result in the audit ledger."""
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_FROM_NUMBER") or os.environ.get("TWILIO_MESSAGING_SERVICE_SID")

    notif_id = f"sms_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    if not (account_sid and auth_token and from_number):
        # Explicit unconfigured state - fail honestly
        status = "suppressed_unconfigured"
        reason = "Twilio credentials (TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN) not configured."
        with db.tx() as c:
            c.execute(
                "INSERT INTO emergency_notification(id, tenant_id, incident_id, channel, "
                "recipient_id, recipient_category, message_text, status, failure_reason, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (notif_id, tenant_id, incident_id, "twilio_sms", to_phone, recipient_category,
                 message_text, "failed", reason, now),
            )
        return {
            "id": notif_id,
            "channel": "twilio_sms",
            "recipient": to_phone,
            "status": "unconfigured",
            "reason": reason,
        }

    # Live Twilio Send
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    data = {
        "To": to_phone,
        "Body": message_text,
    }
    if from_number.startswith("MG"):
        data["MessagingServiceSid"] = from_number
    else:
        data["From"] = from_number

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, data=data, auth=(account_sid, auth_token))
            res_json = resp.json()

            if resp.status_code in (200, 201):
                sid = res_json.get("sid")
                with db.tx() as c:
                    c.execute(
                        "INSERT INTO emergency_notification(id, tenant_id, incident_id, channel, "
                        "recipient_id, recipient_category, message_text, status, provider_ref, created_at, delivered_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (notif_id, tenant_id, incident_id, "twilio_sms", to_phone, recipient_category,
                         message_text, "sent", sid, now, now),
                    )
                return {
                    "id": notif_id,
                    "channel": "twilio_sms",
                    "recipient": to_phone,
                    "status": "sent",
                    "provider_ref": sid,
                }
            else:
                err_msg = res_json.get("message", resp.text)
                with db.tx() as c:
                    c.execute(
                        "INSERT INTO emergency_notification(id, tenant_id, incident_id, channel, "
                        "recipient_id, recipient_category, message_text, status, failure_reason, created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (notif_id, tenant_id, incident_id, "twilio_sms", to_phone, recipient_category,
                         message_text, "failed", err_msg, now),
                    )
                return {
                    "id": notif_id,
                    "channel": "twilio_sms",
                    "recipient": to_phone,
                    "status": "failed",
                    "reason": err_msg,
                }
    except Exception as exc:
        log.error("Twilio SMS transmission failed: %s", exc)
        with db.tx() as c:
            c.execute(
                "INSERT INTO emergency_notification(id, tenant_id, incident_id, channel, "
                "recipient_id, recipient_category, message_text, status, failure_reason, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (notif_id, tenant_id, incident_id, "twilio_sms", to_phone, recipient_category,
                 message_text, "failed", str(exc), now),
            )
        return {
            "id": notif_id,
            "channel": "twilio_sms",
            "recipient": to_phone,
            "status": "failed",
            "reason": str(exc),
        }
