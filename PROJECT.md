# Homazing Automated Quoting — Telegram Bot

A Telegram bot that runs Homazing's quoting, invoicing, and staging workflow end to end, wired into Zoho CRM, QuickBooks Online (invoice creation only), Twilio (SMS), and the "Homazing projects" Google Sheet. Deployed as a background worker on Render (long-polls Telegram; auto-redeploys on push to `master`).

## What it can do

- **New quote** — walks through collecting the property address, room list, and referral status; calculates pricing; creates the Account/Contact/Deal/Quote in Zoho CRM; emails the quote to the customer or agent.
- **Edit / resend a quote** — adjust price or details on an already-sent quote and resend it.
- **Send invoice** — lists Zoho deals sitting in "Quote Approved," raises the QuickBooks invoice for the picked one, and moves the Zoho deal to "Invoiced."
- **Staging complete** — lists jobs from Zoho still open (Quote Awaiting Approval / Quote Approved / Invoiced, excluding Closed Won/Lost) that don't have a Staged Date yet in the sheet; marking one records today's date and texts agent, customer (if a Contact exists), and assistant (if the account has one on file).
- **Staging removed** — lists sheet rows that have a Staged Date but no Staging Removed Date yet (sheet is the source of truth here, not Zoho's stage); marking one records today's date and sends the same three-way SMS (with a "congratulations on the sale" framing).
- **Invoice paid** — lists sheet rows with a Gross amount entered but not yet marked paid, independent of Staged Date. Replaces the retired QuickBooks weekly-poll check (see below): you already know when you've been paid, so you tell the bot directly. Marks Invoice Paid (T)=Y and moves the matching Zoho deal to "Closed Won."
- **Quote declined** — lists deals still in "Quote Awaiting Approval." Picking one asks for an explicit **YES** before acting (irreversible), then moves the Zoho deal to "Closed Lost" and **deletes the row from the sheet entirely**, renumbering column A (No.) so it stays a clean sequential run.
- **Referral tracking** — lists sheet rows with a referral owed and unpaid, shows the amount on request, and marks it paid; paying a referral also best-effort moves the matching Zoho deal to "Closed Won" and texts the agent a thank-you.
- **"hi" / "help" menu** — greets with a numbered list of all the above so commands don't need to be remembered exactly; reply with a number to jump straight into that flow.
- Understands both digits and spelled-out numbers ("2" or "two") when picking from a list, and accepts commands with or without a leading slash/underscore ("staging complete" or "/staging_complete").

## SMS notifications (Twilio)

Four trigger points send SMS via Twilio: staging complete, staging removed, referral paid (agent only), and a Google review request from the Sales Agent project's weekly scraper when a listing first goes live (customer only, skipped if no Zoho Contact exists - i.e. the agent approved the quote on the customer's behalf).

All sends are currently **paused** by an `SMS_ENABLED` env var (must be `1`/`true`/`yes` - anything else, including unset, logs instead of sending). This is deliberate: Homazing's "Homazing" alphanumeric sender ID is still pending Twilio's approval, so sends currently go out under a generic "Unverified" label. Once approved, flip `SMS_ENABLED=true` in Render's environment variables (no redeploy needed) to go live.

Phone numbers are pulled from Zoho (Account = agent + optional `Assistant_Mobile`/`Assistant_Name`/`Assistant_Email`; Contact = customer, absent when the agent approved on the customer's behalf) and normalized from AU local format to E.164 before sending.

## Integrations

- **Zoho CRM** — Deals/Quotes/Accounts/Contacts (create, search by stage, update stage, resolve agent/customer/assistant contact details for SMS).
- **QuickBooks Online** — invoice creation only (via "Send invoice"). The separate weekly invoice-*payment* check has been retired - see Related project below.
- **Twilio** — SMS notifications (see above), currently paused pending sender ID verification.
- **Google Sheets** ("Homazing projects" → Staging Jobs tab) — the operational record for staged/removed dates, referral payment status, invoice paid status, and invoice numbers.
- **Telegram Bot API** — long-polling, per-chat session state stored as local JSON files.

## Related project

`Homazing_Sales_Agent` (sibling repo) runs a separate weekly scheduled job (GitHub Actions, Wednesdays) that scrapes onthehouse.com.au for listing/sold updates and texts a Google review request when a listing first goes live. It used to also poll QuickBooks for invoice payment status, but that was retired 2026-09-02 after a QBO API timeout failed an entire scheduled run - invoice paid is now tracked manually via this bot's "Invoice paid" command instead. The two repos don't share code - each is self-contained for its own deployment target (Render vs. GitHub Actions).
