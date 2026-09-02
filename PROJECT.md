# Homazing Automated Quoting — Telegram Bot

A Telegram bot that runs Homazing's quoting, invoicing, and staging workflow end to end, wired into Zoho CRM, QuickBooks Online, and the "Homazing projects" Google Sheet. Deployed as a background worker on Render (long-polls Telegram; auto-redeploys on push to `master`).

## What it can do

- **New quote** — walks through collecting the property address, room list, and referral status; calculates pricing; creates the Account/Contact/Deal/Quote in Zoho CRM; emails the quote to the customer or agent.
- **Edit / resend a quote** — adjust price or details on an already-sent quote and resend it.
- **Send invoice** — lists Zoho deals sitting in "Quote Approved," raises the QuickBooks invoice for the picked one, and moves the Zoho deal to "Invoiced."
- **Staging complete** — lists jobs from Zoho still open (Quote Awaiting Approval / Quote Approved / Invoiced, excluding Closed Won/Lost) that don't have a Staged Date yet in the sheet; marking one records today's date in the sheet.
- **Staging removed** — lists sheet rows that have a Staged Date but no Staging Removed Date yet (sheet is the source of truth here, not Zoho's stage); marking one records today's date.
- **Referral tracking** — lists sheet rows with a referral owed and unpaid, shows the amount on request, and marks it paid; paying a referral also best-effort moves the matching Zoho deal to "Closed Won."
- **"hi" / "help" menu** — greets with a numbered list of the above so commands don't need to be remembered exactly; reply with a number to jump straight into that flow.
- Understands both digits and spelled-out numbers ("2" or "two") when picking from a list, and accepts commands with or without a leading slash/underscore ("staging complete" or "/staging_complete").

## Integrations

- **Zoho CRM** — Deals/Quotes/Accounts/Contacts (create, search by stage, update stage).
- **QuickBooks Online** — invoice creation, refresh-token rotation shared with the Homazing Sales Agent project via Upstash Redis.
- **Google Sheets** ("Homazing projects" → Staging Jobs tab) — the operational record for staged/removed dates, referral payment status, and invoice numbers.
- **Telegram Bot API** — long-polling, per-chat session state stored as local JSON files.

## Related project

`Homazing_Sales_Agent` (sibling repo) runs a separate weekly scheduled job (GitHub Actions, Wednesdays) that scrapes onthehouse.com.au for listing/sold updates and checks QuickBooks invoice payment status, writing both back to the same Google Sheet. It does not share code with this bot — each repo is self-contained for its own deployment target (Render vs. GitHub Actions).
