"""
Business logic behind the Telegram bot's staging/referral commands.

This is a copy of the same-named module in the Homazing_Sales_Agent project
(kept there as the source of truth for its own weekly sync job). It's
duplicated here - not imported cross-repo - because this bot deploys to
Render from this repo alone; a sibling-folder import would work locally but
break in production, where that other repo isn't checked out. If you change
the logic here, mirror the change in Homazing_Sales_Agent/tools/sheet_actions.py
(and vice versa) - they're expected to drift only in their credential loading
(this one reuses google_sheets.py's _get_credentials rather than its own).

Column layout (Staging Jobs tab): A=No. B=Address C=Suburb D=Agent E=Agent
Name F=Staged Date G=Advertised Date ... J=Staging Removed Date K=Auction/
Private Sale L=Auction/Sold Date M=Price Min N=Price Max O=Sold Price ...
T=Invoice Paid (Y/N) ... U=Gross ... X=Referral(Y/N) Y=Referral Amount
Z=Referral Paid AA=Invoice No.
"""
import datetime

from googleapiclient.discovery import build

from tools.google_sheets import _get_credentials, _normalize_address

SHEET_ID = "1rSiOd_kTw2A8ynDnAcc9QvoUFQal3OidtcQ_RZRwu40"
TAB = "Staging Jobs"
SHEET_GID = 2003463793  # numeric id of the "Staging Jobs" tab - needed for row deletion
EPOCH = datetime.date(1899, 12, 30)


def _service():
    return build("sheets", "v4", credentials=_get_credentials())


def _serial(d: datetime.date) -> int:
    return (d - EPOCH).days


def _today_serial() -> int:
    return _serial(datetime.date.today())


def _get_rows(range_end="AA200", render="UNFORMATTED_VALUE"):
    resp = _service().spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!A3:{range_end}",
        valueRenderOption=render,
    ).execute()
    rows = resp.get("values", [])
    return rows[1:]  # skip header row


def _cell(row, idx):
    return row[idx] if idx < len(row) else None


def zoho_deal_id_for_address(address: str) -> str:
    """Best-effort: find the single Zoho deal for one specific address, without
    pulling every open/invoiced deal into memory. Replaces the old
    _zoho_deal_id_by_addr(), which listed the entire Zoho deal pipeline on
    every single bot menu (staging complete/removed, referral, invoice paid) -
    even for the candidates never picked - and got more expensive every week
    as the pipeline grew. That eager full-list pull was traced to the
    background worker's repeated OOM crashes (2026-09-20, 2026-09-25): each
    call left the process's memory permanently higher (CPython/glibc doesn't
    reliably return large one-off allocations to the OS), so RSS climbed in
    steps until it hit Render's 512Mi limit. Call this only for the address(es)
    a command actually needs a deal_id for (after the user has picked from a
    sheet-only candidate list), never to build the candidate list itself.

    Zoho's Deal_Name is the full address ('11 Rhubarb Rd, Manor Lakes, VIC
    3024'); the sheet stores street-only ('11 Rhubarb Rd') - so this searches
    with starts_with (a handful of matches at most) and confirms with the same
    _normalize_address() comparison the old full-list version used, rather
    than relying on Zoho's server-side equality on a partial string."""
    import requests
    from tools.zoho_auth import get_access_token

    if not address:
        return ""
    token = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    resp = requests.get(
        "https://www.zohoapis.com.au/crm/v2/Deals/search",
        headers=headers,
        params={"criteria": f"(Deal_Name:starts_with:{address})"},
    )
    if resp.status_code in (204, 404):
        return ""
    resp.raise_for_status()
    deals = resp.json().get("data", [])
    norm = _normalize_address(address)
    for d in deals:
        if _normalize_address(d.get("Deal_Name", "")) == norm:
            return d.get("id", "")
    return ""


def list_staging_complete_candidates() -> list[dict]:
    """Jobs that could still need staging: every sheet row with an address but
    no Staged Date (F) yet. Sheet-only - the moment a quote is created it gets
    its own row here, so "not yet staged" is entirely a sheet property and
    never needs a Zoho pull to determine (see zoho_deal_id_for_address, which
    resolves a deal_id lazily only for address(es) actually picked)."""
    candidates = []
    for i, row in enumerate(_get_rows(), start=4):
        addr = _cell(row, 1)
        staged_date = _cell(row, 5)
        if addr and not staged_date:
            candidates.append({"row": i, "address": addr})
    return candidates


def mark_staged(row: int) -> None:
    _service().spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!F{row}",
        valueInputOption="RAW",
        body={"values": [[_today_serial()]]},
    ).execute()


def resort_by_staged_date() -> None:
    """Re-sort every data row by Staged Date (F) ascending, with the original
    No. (A) as a tiebreak. Google Sheets' native sort always pushes blank
    cells to the end regardless of sort order, so this makes completed jobs
    bubble up in the order they were actually finished while everything
    still awaiting staging drops to the bottom - instead of staying wherever
    it happened to land when the quote was first sent. Self-referencing
    per-row formulas (the FORMULA_COLUMNS in google_sheets.py) survive a
    native sort correctly - Sheets re-points them to the row's new position,
    same as a manual row drag - so they don't need to be rewritten here.

    Call this once *after* marking every selected row in a multi-select
    'staging complete' batch, not inside mark_staged itself - resorting
    between each mark would invalidate the row numbers still queued in that
    same batch."""
    rows = _get_rows()
    if not rows:
        return
    last_row = 3 + len(rows)
    service = _service()
    service.spreadsheets().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"requests": [{
            "sortRange": {
                "range": {
                    "sheetId": SHEET_GID,
                    "startRowIndex": 3,       # row 4, 0-indexed
                    "endRowIndex": last_row,
                    "startColumnIndex": 0,    # A
                    "endColumnIndex": 27,     # through AA
                },
                "sortSpecs": [
                    {"dimensionIndex": 5, "sortOrder": "ASCENDING"},  # F = Staged Date
                    {"dimensionIndex": 0, "sortOrder": "ASCENDING"},  # A = No. (stable tiebreak)
                ],
            }
        }]},
    ).execute()

    # The physical reorder leaves column A out of sequence - rewrite it to a
    # clean 1..N run matching the new top-to-bottom order (same approach as
    # _remove_rows_and_renumber after a quote-declined deletion).
    values = [[i + 1] for i in range(len(_get_rows()))]
    service.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!A4:A{last_row}",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def list_staging_removed_candidates() -> list[dict]:
    """Jobs with Staged Date (F) filled but Staging Removed Date (J) blank -
    currently staged, awaiting pickup. Sheet-only: an earlier version also
    required the matching Zoho deal to be in 'Invoiced' stage, but that
    silently hid older jobs whose deal had already moved past Invoiced (e.g.
    Closed Won) even though the staging itself hadn't been picked up yet.
    The sheet, not Zoho's stage, is the source of truth for what's
    physically staged. No Zoho pull here - deal_id is resolved lazily (see
    zoho_deal_id_for_address) only for the address(es) actually picked."""
    candidates = []
    for i, row in enumerate(_get_rows(), start=4):
        addr = _cell(row, 1)
        staged_date = _cell(row, 5)
        removed_date = _cell(row, 9)
        if addr and staged_date and not removed_date:
            candidates.append({"row": i, "address": addr})
    return candidates


def mark_staging_removed(row: int) -> None:
    _service().spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!J{row}",
        valueInputOption="RAW",
        body={"values": [[_today_serial()]]},
    ).execute()


def list_referral_candidates() -> list[dict]:
    """Jobs where a referral is owed (X=Y) and not yet paid (Z blank).
    Sheet-only, same reasoning as list_staging_removed_candidates - gating
    on Zoho's Invoiced stage hid older jobs whose deal had already moved
    past Invoiced. deal_id (needed so mark_referral_paid can also flip that
    deal to Closed Won) is resolved lazily - see zoho_deal_id_for_address -
    only for the address(es) actually picked, not eagerly for this whole
    list."""
    unformatted = _get_rows(render="UNFORMATTED_VALUE")
    formatted = _get_rows(render="FORMATTED_VALUE")
    candidates = []
    for i, (row, frow) in enumerate(zip(unformatted, formatted), start=4):
        addr = _cell(row, 1)
        referral_yn = _cell(row, 23)
        referral_paid = _cell(row, 25)
        if addr and referral_yn == "Y" and not referral_paid:
            amount_display = (_cell(frow, 24) or "$0").strip()
            candidates.append({
                "row": i, "address": addr,
                "amount_display": amount_display,
            })
    return candidates


def mark_referral_paid(row: int, deal_id: str = "") -> None:
    _service().spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!Z{row}",
        valueInputOption="RAW",
        body={"values": [["Y"]]},
    ).execute()
    if deal_id:
        from tools.zoho_update_quote import mark_deal_closed_won
        mark_deal_closed_won(deal_id)


def list_invoice_paid_candidates() -> list[dict]:
    """Jobs with a Gross amount (U) entered but Invoice Paid (T) not yet Y -
    independent of Staged Date, since a job can be invoiced/paid before or
    after staging happens. Replaces the old QuickBooks-polling weekly check
    (retired for being an unreliable dependency - a slow/unreachable QBO API
    call would fail the whole weekly sync) with a manual confirmation the
    same way referral-paid works: you already know when you've been paid,
    so just tell the bot. deal_id is resolved lazily (see
    zoho_deal_id_for_address) only for the address(es) actually picked."""
    candidates = []
    for i, row in enumerate(_get_rows(), start=4):
        addr = _cell(row, 1)
        gross = _cell(row, 20)
        invoice_paid = _cell(row, 19)
        if addr and gross and invoice_paid != "Y":
            candidates.append({"row": i, "address": addr})
    return candidates


def mark_invoice_paid(row: int, deal_id: str = "") -> None:
    _service().spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!T{row}",
        valueInputOption="RAW",
        body={"values": [["Y"]]},
    ).execute()
    if deal_id:
        from tools.zoho_update_quote import mark_deal_closed_won
        mark_deal_closed_won(deal_id)


def list_quote_declined_candidates() -> list[dict]:
    """Jobs from the Google Sheet with no Staged Date (F) yet - same sheet-only
    filter as list_staging_complete_candidates(). This is deliberately broader
    than "still awaiting approval": a blank Staged Date also covers jobs already
    approved (or even invoiced) but not yet staged, since the sheet has no
    separate approval-status column. Traded off for simplicity - manually
    declining a job here is a fallback for a verbal/phone decline anyway (the
    normal path is automatic: the customer/agent's own decline on the approval
    web form already moves the Zoho deal to Closed Lost and pings the bot on
    its own, see homazing-website's /api/decline route), and the caller already
    knows which address they mean to decline before picking a number. deal_id
    is resolved lazily (see zoho_deal_id_for_address) only for the address(es)
    actually picked."""
    return list_staging_complete_candidates()


def _remove_rows_and_renumber(rows: list[int]) -> None:
    """Deletes the given sheet rows entirely (not just clearing cells) so
    every row below shifts up, then rewrites column A (No.) as a clean
    sequential run 1, 2, 3... - otherwise a deleted row leaves a gap or a
    duplicate number. Rows are deleted highest-first within one batch so
    each deletion's index is still valid when it's applied (a delete only
    shifts rows *below* it, never rows still queued above)."""
    service = _service()
    requests = [
        {"deleteDimension": {"range": {
            "sheetId": SHEET_GID, "dimension": "ROWS",
            "startIndex": r - 1, "endIndex": r,
        }}}
        for r in sorted(rows, reverse=True)
    ]
    service.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={"requests": requests}).execute()

    remaining = _get_rows()
    if not remaining:
        return
    values = [[i + 1] for i in range(len(remaining))]
    service.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!A4:A{3 + len(remaining)}",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def mark_quotes_declined(candidates: list[dict]) -> None:
    """candidates: [{'row', 'deal_id', 'address', ...}, ...]. Moves each
    matching Zoho deal to Closed Lost (and its linked Quote's Quote_Stage,
    looked up by address, to Closed Lost too - so quote-side reporting
    doesn't show a declined quote as still 'Delivered'), then removes all
    the given sheet rows and renumbers column A in one batch - must be done
    together, since deleting rows one at a time would invalidate the row
    numbers of the ones still queued. deal_id is resolved lazily here (see
    zoho_deal_id_for_address), one Zoho lookup per address actually being
    declined, not eagerly for the whole candidate list."""
    from tools.zoho_update_quote import mark_deal_closed_lost
    from tools.zoho_create_quote import get_quote_by_subject
    for c in candidates:
        deal_id = zoho_deal_id_for_address(c.get("address", ""))
        if deal_id:
            quote = get_quote_by_subject(c["address"]) if c.get("address") else None
            mark_deal_closed_lost(deal_id, quote_id=quote["id"] if quote else "")
    _remove_rows_and_renumber([c["row"] for c in candidates])


def get_referral_amount_display(row: int) -> str:
    resp = _service().spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!Y{row}",
        valueRenderOption="FORMATTED_VALUE",
    ).execute()
    values = resp.get("values", [])
    return values[0][0].strip() if values and values[0] else "$0"
