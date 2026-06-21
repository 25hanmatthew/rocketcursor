# RocketCursor Procurement MCP Server

A [FastMCP](https://github.com/jlowin/fastmcp) server that lets Poke send RFQ
emails through **your own SMTP account**. Because the email is sent by this
server (not by Poke's built-in email integration), delivery is deterministic and
does not depend on Poke's account linkage.

## Tools exposed

| Tool | Purpose |
|------|---------|
| `send_rfq_email(to, subject, body)` | Send one RFQ email |
| `send_rfq_emails(emails)` | Send a batch; `emails` = `[{to, subject, body}, ...]` |
| `send_test_email(to)` | Quick end-to-end test |
| `get_server_info()` | Report SMTP config health + allowlist |

## Safety

If `ALLOWED_RECIPIENTS` is set, the server refuses to send to any address not in
that comma-separated list. Keep it set to your test inbox while testing so the
deployed endpoint can't be abused to email arbitrary people.

## 1. Get a Gmail App Password

1. Enable 2-Step Verification on the Google account.
2. Go to https://myaccount.google.com/apppasswords and create an app password.
3. Use that 16-character value as `SMTP_PASSWORD` (not your normal password).

## 2. Test locally

```bash
cd tools/procurement/mcp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in SMTP_USERNAME / SMTP_PASSWORD
set -a && source .env && set +a
python server.py
```

In another terminal, inspect it:

```bash
npx @modelcontextprotocol/inspector
# connect to http://localhost:8000/mcp  (Streamable HTTP transport — note the /mcp)
```

Call `send_test_email` with your test address to confirm delivery.

## 3. Deploy to Render

1. Push this repo to GitHub.
2. Create a new Web Service on Render pointing at this `tools/procurement/mcp`
   directory (or use the `render.yaml`).
3. Set env vars in the Render dashboard: `SMTP_USERNAME`, `SMTP_PASSWORD`,
   `SMTP_FROM` (optional), `ALLOWED_RECIPIENTS`.
4. Your server will be live at `https://<service>.onrender.com/mcp`.

## 4. Connect to Poke

1. Go to https://poke.com/settings/connections/integrations/new
2. Add your server URL (must end in `/mcp`).
3. Name the connection (e.g. `RocketCursor Procurement`). If you use a different
   name, set `POKE_MCP_CONNECTION` in the repo `.env` to match.
4. Test from iMessage:
   `Tell the subagent to use the "RocketCursor Procurement" integration's send_test_email tool with to=you@example.com`

If Poke keeps calling the wrong tool after renaming, send `clearhistory` to Poke.

## 5. Send RFQs

Run the procurement send step as usual:

```bash
cd tools/procurement
npm run send-rfqs -- ../../results/procurement_runs/smoke_test_v8
```

This writes `poke_mcp_instruction.txt` into the run directory. Paste its contents
into your iMessage Poke chat — it instructs Poke to call `send_rfq_emails` with
the prepared emails. The MCP server sends them via your SMTP account to
`RFQ_TEST_EMAIL`.
