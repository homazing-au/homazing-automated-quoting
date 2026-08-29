"""Append a new row to the 'Staging Jobs' Google Sheet whenever a quote is delivered.

Reuses the same Google OAuth credentials as the Homazing Sales Agent project
(spreadsheets read/write + drive readonly scopes, already granted).
"""

import json
import os
import re

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
TAB = os.getenv("GOOGLE_SHEET_TAB", "Staging Jobs")
TOKEN_PATH = os.getenv("GOOGLE_OAUTH_TOKEN_PATH", "token.json")

# Formula cells that must carry down to every new row so the sheet's existing
# calculations (Month, Proposed Completion, Uplift, Uplift %, Sold in Weeks,
# GST, Net, Referral Amount) keep working once the rest of the row is filled
# in later.
FORMULA_COLUMNS = {
    "H": '=IF(F{r}="","",TEXT(F{r},"MMM"))',
    "I": "=F{r}+56",
    "P": "=IF(O{r}=0,0,O{r}-M{r})",
    "Q": "=IF(O{r}=0,0,IF((O{r}/M{r}-1)<0,0,O{r}/M{r}-1))",
    "R": '=IF(L{r}="","",(L{r}-G{r})/7)',
    "V": '=IF(U{r}="","",IF(S{r}="EFT",U{r}/11,""))',
    "W": '=IF(V{r}="",U{r},U{r}-V{r})',
    "Y": '=IF(X{r}="Y",W{r}*0.1,"")',
}


def _get_credentials() -> Credentials:
    # Render has no local token.json (it's gitignored) — load from an env var there.
    token_json_env = os.getenv("GOOGLE_TOKEN_JSON")
    if token_json_env:
        return Credentials.from_authorized_user_info(json.loads(token_json_env), SCOPES)
    return Credentials.from_authorized_user_file(TOKEN_PATH)


STATE_POSTCODE = r"(VIC|NSW|QLD|SA|WA|TAS|NT|ACT)\s*\d{4}"


def _parse_suburb(address: str) -> str:
    """Extract the suburb from a formatted address, handling both
    'Street, Suburb VIC 3000' and 'Street, Suburb, VIC 3000' layouts."""
    parts = [p.strip() for p in address.split(",")]
    if len(parts) < 2:
        return ""
    last = parts[-1]
    # "Street, Suburb, VIC 3000" — last segment is just the state+postcode,
    # so the suburb is the segment before it.
    if re.fullmatch(STATE_POSTCODE, last, flags=re.IGNORECASE) and len(parts) >= 3:
        return parts[-2]
    # "Street, Suburb VIC 3000" — state+postcode is appended to the suburb segment.
    return re.sub(rf"\s+{STATE_POSTCODE}\s*$", "", last, flags=re.IGNORECASE).strip()


def _parse_street(address: str) -> str:
    """Extract just the street number + name, e.g. '344 Huntingdale Rd' from
    '344 Huntingdale Rd, Oakleigh South, VIC 3167' - matches the sheet's
    existing convention of keeping Address (B) and Suburb (C) separate."""
    return address.split(",", 1)[0].strip()


def append_staging_job(address: str, agency: str, agent_name: str, gross: float, has_referral: bool) -> dict:
    """
    Append a new row for a newly-delivered quote. Fills A (job #), B (address),
    C (suburb), D (agency — blank for a direct customer with no linked agency),
    E (agent name — the agency's name for an agency-sourced quote, or the
    customer's own name for a direct customer), U (gross), X (referral Y/N).
    Copies the formula cells from the row above so the new row's formulas keep working.
    """
    creds = _get_credentials()
    service = build("sheets", "v4", credentials=creds)

    col_a = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!A4:A2000",
    ).execute().get("values", [])

    last_row_idx = 3 + len(col_a)  # row 4 is the first data row
    last_job_no = 0
    for row in reversed(col_a):
        if row and str(row[0]).strip().isdigit():
            last_job_no = int(row[0])
            break

    new_row_num = last_row_idx + 1
    new_job_no = last_job_no + 1
    suburb = _parse_suburb(address)
    street = _parse_street(address)

    values = {
        "A": new_job_no,
        "B": street,
        "C": suburb,
        "D": agency,
        "E": agent_name,
        "S": "EFT",
        "U": round(gross, 2),
        "X": "Y" if has_referral else "N",
    }
    for col, formula_template in FORMULA_COLUMNS.items():
        values[col] = formula_template.format(r=new_row_num)

    data = [
        {"range": f"'{TAB}'!{col}{new_row_num}", "values": [[val]]}
        for col, val in values.items()
    ]

    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"valueInputOption": "USER_ENTERED", "data": data},
    ).execute()

    return {"row": new_row_num, "job_no": new_job_no, "suburb": suburb}


def set_invoice_number(address: str, invoice_number: str) -> dict:
    """Write the QuickBooks invoice number into column AA of the row matching
    `address` (exact match against column B), so the Sales Agent's weekly
    QuickBooks payment check knows which invoice to look up.

    Matches the *most recent* row with this exact address, in case the same
    property was staged more than once. Returns {"row": n} on success, or
    {"row": None, "reason": "..."} if no matching row was found - callers
    should treat that as non-fatal (the invoice itself is unaffected).
    """
    creds = _get_credentials()
    service = build("sheets", "v4", credentials=creds)

    col_b = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!B4:B2000",
    ).execute().get("values", [])

    target = address.strip().lower()
    match_row = None
    for i, row in enumerate(col_b):
        if row and row[0].strip().lower() == target:
            match_row = 4 + i  # keep scanning - later rows win (most recent job)

    if match_row is None:
        return {"row": None, "reason": f"no sheet row found for address '{address}'"}

    service.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!AA{match_row}",
        valueInputOption="RAW",
        body={"values": [[invoice_number]]},
    ).execute()

    return {"row": match_row}
