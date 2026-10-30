"""Request validation.

Validation never raises: it returns the cleaned values plus a field → message
map. The API turns that map into a 400 with a stable shape, and the tests assert
on the exact field names, so a caller can tell the UI which input was wrong.
"""

from __future__ import annotations

MAX_NAME = 200
MAX_CATEGORY = 80
MAX_REASON = 500

FIELDS = ("name", "category", "quantity", "unit_price", "reorder_level")


def _as_int(value):
    """Accept ints and integer-strings; reject bools, floats and junk."""
    if isinstance(value, bool):
        raise ValueError("must be a whole number")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise ValueError("must be a whole number")


def _as_float(value):
    if isinstance(value, bool):
        raise ValueError("must be a number")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            raise ValueError("must be a number") from None
    raise ValueError("must be a number")


def validate_product(payload, partial: bool = False):
    """Return (data, errors). `partial=True` is for PATCH-style updates."""
    data: dict = {}
    errors: dict = {}

    if not isinstance(payload, dict):
        return {}, {"_body": "expected a JSON object"}

    def present(field: str) -> bool:
        return field in payload and payload[field] is not None

    for field in ("name", "category"):
        if not present(field):
            if not partial:
                errors[field] = "is required"
            continue
        value = payload[field]
        if not isinstance(value, str) or not value.strip():
            errors[field] = "must be a non-empty string"
            continue
        limit = MAX_NAME if field == "name" else MAX_CATEGORY
        if len(value.strip()) > limit:
            errors[field] = f"must be at most {limit} characters"
            continue
        data[field] = value.strip()

    for field in ("quantity", "reorder_level"):
        if not present(field):
            if not partial and field == "quantity":
                data["quantity"] = 0          # a new product starts empty
            continue
        try:
            value = _as_int(payload[field])
        except ValueError as err:
            errors[field] = str(err)
            continue
        if value < 0:
            errors[field] = "must not be negative"
            continue
        data[field] = value

    if not present("unit_price"):
        if not partial:
            errors["unit_price"] = "is required"
    else:
        try:
            price = _as_float(payload["unit_price"])
        except ValueError as err:
            errors["unit_price"] = str(err)
        else:
            if price < 0:
                errors["unit_price"] = "must not be negative"
            elif price > 1_000_000_000:
                errors["unit_price"] = "is implausibly large"
            else:
                data["unit_price"] = round(price, 2)

    if not partial and "reorder_level" not in data:
        data["reorder_level"] = 0
    return data, errors


def validate_movement(payload):
    """Return (data, errors) for a stock movement."""
    data: dict = {}
    errors: dict = {}
    if not isinstance(payload, dict):
        return {}, {"_body": "expected a JSON object"}

    kind = payload.get("movement_type")
    if kind not in ("in", "out", "adjust"):
        errors["movement_type"] = "must be one of: in, out, adjust"
    else:
        data["movement_type"] = kind

    try:
        change = _as_int(payload.get("quantity_change"))
    except ValueError as err:
        errors["quantity_change"] = str(err)
    else:
        if change == 0:
            errors["quantity_change"] = "must not be zero"
        elif abs(change) > 1_000_000:
            errors["quantity_change"] = "is implausibly large"
        else:
            data["quantity_change"] = change

    reason = payload.get("reason", "")
    if reason is None:
        reason = ""
    if not isinstance(reason, str):
        errors["reason"] = "must be a string"
    elif len(reason) > MAX_REASON:
        errors["reason"] = f"must be at most {MAX_REASON} characters"
    else:
        data["reason"] = reason.strip()

    # An 'in' movement adds stock, an 'out' movement removes it. 'adjust' takes
    # the sign the caller supplied.
    if "movement_type" in data and "quantity_change" in data:
        change = data["quantity_change"]
        if data["movement_type"] == "in" and change < 0:
            data["quantity_change"] = abs(change)
        elif data["movement_type"] == "out" and change > 0:
            data["quantity_change"] = -abs(change)
    return data, errors
