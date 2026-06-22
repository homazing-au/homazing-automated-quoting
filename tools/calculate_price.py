"""
Homazing pricing engine.
All unit costs are inc. GST. MROUND rounds total to nearest $10.
"""

import math

UNIT_COSTS = {
    "master_bedroom": 450,
    "guest_bedroom":  350,
    "kids_bedroom":   350,
    "living":         450,
    "dining":         350,
    "kitchen":        100,
    "alfresco":       150,
    "bath":            50,
    "hallway_table":  100,
    "study":          300,
    "small_living":   300,
}

ROOM_LABELS = {
    "master_bedroom": "Master Bedroom",
    "guest_bedroom":  "Guest Bedroom",
    "kids_bedroom":   "Kids Bedroom",
    "living":         "Living",
    "dining":         "Dining",
    "kitchen":        "Kitchen",
    "alfresco":       "Alfresco",
    "bath":           "Bath",
    "hallway_table":  "Hallway Table",
    "study":          "Study",
    "small_living":   "Small Living",
}


def mround(value, multiple):
    return round(value / multiple) * multiple


def calculate_price(
    rooms: dict,
    referral_pct: float = 0.0,
    added_pct: float = 0.0,
    reduced_pct: float = 0.0,
) -> dict:
    """
    Args:
        rooms: dict of room_key -> quantity, e.g. {"master_bedroom": 1, "living": 2}
        referral_pct: referral commission as a decimal (e.g. 0.05 for 5%)
        added_pct:    uplift as a decimal
        reduced_pct:  discount as a decimal

    Returns dict with all pricing components.
    """
    unknown = [k for k in rooms if k not in UNIT_COSTS]
    if unknown:
        raise ValueError(f"Unknown room type(s): {unknown}. Valid: {list(UNIT_COSTS)}")

    line_items = []
    subtotal = 0.0
    for room_key, qty in rooms.items():
        if qty <= 0:
            continue
        unit = UNIT_COSTS[room_key]
        amount = unit * qty
        subtotal += amount
        line_items.append({
            "room":   room_key,
            "label":  ROOM_LABELS[room_key],
            "qty":    qty,
            "unit":   unit,
            "amount": amount,
        })

    referral = subtotal * referral_pct
    added    = subtotal * added_pct
    reduced  = subtotal * reduced_pct
    total_inc_gst   = mround(subtotal + referral + added - reduced, 10)
    gst             = round(total_inc_gst / 11, 2)
    subtotal_ex_gst = round(total_inc_gst - gst, 2)

    return {
        "line_items":      line_items,
        "referral":        round(referral, 2),
        "added":           round(added, 2),
        "reduced":         round(reduced, 2),
        "total_inc_gst":   total_inc_gst,
        "gst":             gst,
        "subtotal_ex_gst": subtotal_ex_gst,
    }


def format_result(result: dict) -> str:
    lines = ["Line Items:"]
    for item in result["line_items"]:
        lines.append(f"  {item['label']:20s} x{item['qty']}  ${item['amount']:,.2f}")
    lines.append(f"\nSubtotal (inc. GST):    ${result['subtotal']:,.2f}")
    if result["added"]:
        lines.append(f"Added:                  ${result['added']:,.2f}")
    if result["reduced"]:
        lines.append(f"Reduced:               -${result['reduced']:,.2f}")
    if result["referral"]:
        lines.append(f"Referral:               ${result['referral']:,.2f}")
    lines.append(f"\nTotal (inc. GST):       ${result['total_inc_gst']:,.2f}")
    lines.append(f"GST (÷11):              ${result['gst']:,.2f}")
    lines.append(f"Subtotal (ex. GST):     ${result['subtotal_ex_gst']:,.2f}")
    return "\n".join(lines)


if __name__ == "__main__":
    # Sample: 3 bed, 2 bath, living, dining, kitchen — 5% referral
    sample_rooms = {
        "master_bedroom": 1,
        "guest_bedroom":  2,
        "living":         1,
        "dining":         1,
        "kitchen":        1,
        "bath":           2,
    }
    result = calculate_price(sample_rooms, referral_pct=0.05)
    print(format_result(result))

    print("\n--- with 10% discount ---")
    result2 = calculate_price(sample_rooms, referral_pct=0.05, reduced_pct=0.10)
    print(format_result(result2))
