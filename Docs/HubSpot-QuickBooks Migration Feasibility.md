# Feasibility Assessment: Migrating Homazing Quoting System from Zoho → HubSpot + QuickBooks

_Assessed 2026-06-07. Revisit if pricing/feature gaps below change._

## Context
Evaluating whether to subscribe to HubSpot's "Small Business Bundle" so the Homazing Automated Quoting system could run on HubSpot CRM + QuickBooks instead of Zoho CRM + Zoho Invoices — keeping the same pricing engine, Telegram bot conversation flow, approval pages, and PDF/email delivery.

**Bottom line up front: technically possible, but two blockers make this a bad trade today.** Recommend staying on Zoho unless one of the blockers below changes.

---

## What's reusable as-is (~80% of the system, zero rewrite)
Confirmed Zoho-agnostic — these have no CRM/invoicing coupling and would carry over untouched:
- **Pricing engine** (`tools/calculate_price.py`) — pure room-cost/GST/rounding logic
- **Telegram bot conversation flow** (`tools/quote_agent.py`) — Claude-driven state machine collecting rooms, referral %, agent details
- **PDF generation** (`tools/generate_invoice_pdf.py`, `homazing-website/lib/generateInvoicePdf.ts`)
- **Approval token codec + Telegram alerting** (`decodeToken`/`sendTelegram` in the website route)

## What's tightly coupled to Zoho (the ~20% that would need a full rewrite)
- `tools/zoho_auth.py` — OAuth2 token flow (would be replaced by **two separate** OAuth2 integrations: HubSpot's + Intuit/QuickBooks' own developer app, each with its own client ID/secret/refresh-token plumbing)
- `tools/zoho_create_account.py`, `zoho_create_contact.py`, `zoho_lookup_contact.py` — Account/Contact CRUD incl. DUPLICATE_DATA handling → HubSpot Contacts/Companies API
- `tools/zoho_create_quote.py` — Quote + linked Deal creation, Product unit-price trick for tax calc → HubSpot Deals + Quotes objects
- `tools/zoho_create_invoice.py`, `homazing-website/lib/zoho.ts` (`createContact`, `createInvoice`, `updateDealStage`) and the Deal-stage automation in `app/api/approve/[token]/route.ts` → HubSpot Deals + QuickBooks Invoices, two systems instead of one
- Email senders (`zoho_send_quote_email.py`, `zoho_send_invoice_email.py`) — not Zoho-specific (SMTP/Resend), no change needed

---

## The two blockers

### 1. HubSpot "Quotes" is no longer in the Starter bundle for new customers
The Small Business Bundle ("Starter Customer Platform", ~$15–20/seat/mo) bundles Starter-tier Hubs. As of HubSpot's 2025 licensing overhaul, the **Quotes tool was pulled out of Sales Hub Starter** and now sits behind **Commerce Hub Professional (~$85/user/month extra)** for any new signup. Existing customers keep it grandfathered — you would not, since this is a fresh subscription. That roughly **5–6x's the monthly cost** versus what the bundle pricing implies.
*(Workaround: you don't strictly need HubSpot's native Quotes object — the system could create a "Deal" only and generate the quote PDF itself, same as today. This blocker is avoidable by design, but it means HubSpot's CRM contributes less than it would for Zoho, which natively models Quotes.)*

### 2. The native HubSpot ↔ QuickBooks sync doesn't support tax on invoices
HubSpot's official "QuickBooks Online — Data Sync" app (free, all tiers) can push invoices from HubSpot into QuickBooks — **but HubSpot invoices cannot be created with tax**, and QuickBooks accounts that require invoice tax (which an Australian GST-registered business does) **cannot use this feature**. This is a hard blocker for the core deliverable (a GST-compliant invoice), not a workaround-able inconvenience — it would force either a fully custom QuickBooks Online API integration (bypassing HubSpot's invoice object entirely, similar effort to what Zoho already does today) or abandoning HubSpot-side invoice creation.

**Secondary frictions** (workable but add real engineering cost):
- Deals don't sync to QuickBooks at all — any link between pipeline stage and invoice needs custom glue (you'd be writing this anyway, similar to the current `updateDealStage` pattern)
- Two independent OAuth2 app registrations to build/maintain (HubSpot dev account + Intuit developer account) instead of Zoho's single app
- QuickBooks sandbox accounts can't be connected to the sync — testing happens against production

---

## Recommendation
**Don't migrate now.** The current Zoho-based system is feature-complete, working end-to-end, and the Deal-pipeline automation was just finished and tested. Swapping to HubSpot + QuickBooks would mean:
- Paying significantly more than the bundle's advertised price once Quotes are factored in (or dropping HubSpot's Quotes feature and replicating what Zoho already gives you for free)
- Still writing a fully custom QuickBooks Online API integration for GST-compliant invoicing — i.e., redoing the hardest 20% of the current system rather than buying it off the shelf
- Maintaining two OAuth integrations instead of one

If a future trigger changes the calculus — e.g., Homazing outgrows Zoho's CRM features, or HubSpot/Intuit ship AU-tax support in the native sync, or there's a non-quoting reason to be on HubSpot (marketing, service tickets) — revisit then. At that point the ~80% reusable core (pricing engine, Telegram flow, PDF/email, approval pages) means a future migration is a **rewrite of the integration layer only**, not a rebuild of the product.

## Sources
- HubSpot Starter Customer Platform: https://www.hubspot.com/products/crm/starter
- HubSpot Quotes pricing change discussion: https://community.hubspot.com/t5/Sales-Hub-Tools/It-now-costs-77-Month-per-Salesperson-to-access-Quotes-not/m-p/1209267
- HubSpot 2025 pricing/license changes: https://simplestrat.com/blog/hubspots-2025-pricing-license-changes-what-you-need-to-know
- HubSpot APIs by tier: https://developers.hubspot.com/apisbytier
- Connect HubSpot and QuickBooks Online (official docs): https://knowledge.hubspot.com/integrations/connect-hubspot-and-quickbooks-online
- QuickBooks Online data sync — invoices (tax limitation): https://knowledge.hubspot.com/integrations/using-the-quickbooks-online-data-sync-integration-for-invoices
- HubSpot OAuth tokens guide: https://developers.hubspot.com/docs/guides/api/app-management/oauth-tokens
- Intuit Developer OAuth 2.0: https://developer.intuit.com/app/developer/qbo/docs/develop/authentication-and-authorization/oauth-2.0
