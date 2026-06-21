#!/usr/bin/env python3
"""RocketCursor procurement MCP server for Poke.

Exposes email-send tools that deliver RFQs through our own SMTP account, so
delivery does not depend on Poke's built-in email integration. Connect this
server to Poke at https://poke.com/settings/connections and then ask Poke to
use the integration's send tool.

Safety: when ALLOWED_RECIPIENTS is set, the server refuses to send to any
address outside that allowlist. Keep it set to your test inbox while testing.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage

from fastmcp import FastMCP

mcp = FastMCP("RocketCursor Procurement")


def _allowed_recipients() -> set[str]:
    raw = os.environ.get("ALLOWED_RECIPIENTS", "").strip()
    if not raw:
        return set()
    return {addr.strip().lower() for addr in raw.split(",") if addr.strip()}


def _check_recipient(to: str) -> str | None:
    """Return an error string if the recipient is not allowed, else None."""
    allowlist = _allowed_recipients()
    if allowlist and to.strip().lower() not in allowlist:
        return (
            f"Recipient {to} is not in ALLOWED_RECIPIENTS. "
            "Sending blocked for safety. Allowed: " + ", ".join(sorted(allowlist))
        )
    return None


def _smtp_send(to: str, subject: str, body: str) -> dict:
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    sender = os.environ.get("SMTP_FROM", "").strip() or username
    # Implicit SSL on 465; STARTTLS otherwise. Some networks block 587, so 465 is the default.
    use_ssl = os.environ.get("SMTP_USE_SSL", "").strip().lower() in {"1", "true", "yes"} or port == 465

    if not username or not password:
        return {
            "ok": False,
            "error": "SMTP_USERNAME / SMTP_PASSWORD not configured on the MCP server.",
        }

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    context = ssl.create_default_context()
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=30, context=context) as server:
                server.login(username, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(username, password)
                server.send_message(msg)
    except Exception as exc:  # noqa: BLE001 - surface any SMTP failure to Poke
        return {"ok": False, "error": f"SMTP send failed: {exc}"}

    return {"ok": True, "to": to, "subject": subject, "from": sender}


@mcp.tool(
    description=(
        "Send a single RFQ (request-for-quote) email via the RocketCursor SMTP "
        "account. Use this to deliver a procurement RFQ. Provide the recipient "
        "email, subject line, and full plain-text body."
    )
)
def send_rfq_email(to: str, subject: str, body: str) -> dict:
    blocked = _check_recipient(to)
    if blocked:
        return {"ok": False, "error": blocked}
    return _smtp_send(to=to, subject=subject, body=body)


@mcp.tool(
    description=(
        "Send multiple RFQ emails in one call. Each item must be an object with "
        "'to', 'subject', and 'body' string fields. Returns a per-email result list."
    )
)
def send_rfq_emails(emails: list[dict]) -> dict:
    results = []
    for item in emails:
        to = str(item.get("to", "")).strip()
        subject = str(item.get("subject", "")).strip()
        body = str(item.get("body", ""))
        if not to or not subject:
            results.append({"ok": False, "error": "Missing 'to' or 'subject'", "item": item})
            continue
        blocked = _check_recipient(to)
        if blocked:
            results.append({"ok": False, "error": blocked, "to": to})
            continue
        results.append(_smtp_send(to=to, subject=subject, body=body))
    return {"ok": all(r.get("ok") for r in results), "count": len(results), "results": results}


@mcp.tool(
    description=(
        "Send a quick test email to confirm the RocketCursor SMTP integration "
        "works end to end. Provide the recipient email."
    )
)
def send_test_email(to: str) -> dict:
    blocked = _check_recipient(to)
    if blocked:
        return {"ok": False, "error": blocked}
    return _smtp_send(
        to=to,
        subject="RocketCursor MCP test email",
        body="This is a test email sent via the RocketCursor procurement MCP server. "
        "If you received this, direct send is working.",
    )


@mcp.tool(
    description="Get RocketCursor procurement MCP server status and SMTP configuration health."
)
def get_server_info() -> dict:
    username = os.environ.get("SMTP_USERNAME", "").strip()
    return {
        "server_name": "RocketCursor Procurement",
        "version": "1.0.0",
        "smtp_host": os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": os.environ.get("SMTP_PORT", "587"),
        "smtp_configured": bool(username and os.environ.get("SMTP_PASSWORD", "").strip()),
        "smtp_from": os.environ.get("SMTP_FROM", "").strip() or username,
        "allowed_recipients": sorted(_allowed_recipients()) or "ANY (no allowlist set)",
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0"
    print(f"Starting RocketCursor Procurement MCP server on {host}:{port}")
    mcp.run(transport="http", host=host, port=port, stateless_http=True)
