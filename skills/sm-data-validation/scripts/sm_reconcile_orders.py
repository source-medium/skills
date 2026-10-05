#!/usr/bin/env python3
"""Reconcile a Shopify order export against a SourceMedium obt_orders extract.

Matches orders by platform order id (order name as fallback), aligns the
comparison basis (POS scope, window, sign convention, day bucketing), then
attributes every unit of the net-revenue delta to a named cause. The
attribution rows sum exactly to the headline delta by construction.

Inputs
  --shopify   ShopifyQL "sales by order" export CSV, or the Shopify admin
              Orders page CSV (one row per line item). Format auto-detected.
  --sm        CSV produced by the canonical extract in
              references/COMPARISON_PROTOCOL.md (bq --format=csv output).

Exit codes
  0  reconciled: headline delta within --tolerance-total and no residual
  1  differences remain (attributed or unexplained); read the report
  2  input error (missing file, unrecognized columns, duplicate ids)

Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

EXIT_OK = 0
EXIT_DIFFERENCES = 1
EXIT_INPUT = 2

ZERO = Decimal("0")
CENT = Decimal("0.01")

MONEY_FIELDS = ("gross", "discounts", "returns", "net", "shipping", "taxes", "total")

# Header aliases after normalization (lowercase, non-alphanumerics -> "_").
SHOPIFY_ALIASES: Dict[str, Tuple[str, ...]] = {
    "order_id": ("order_id", "id"),
    "order_name": ("order_name", "name", "order"),
    "day": ("day", "date", "processed_at", "created_at"),
    "gross": ("gross_sales",),
    "discounts": ("discounts", "discount_amount"),
    "returns": ("sales_reversals", "returns", "refunds", "refunded_amount"),
    "net": ("net_sales",),
    "shipping": ("shipping_charges", "shipping"),
    "taxes": ("taxes", "tax"),
    "total": ("total_sales", "total"),
    "subtotal": ("subtotal",),
    "lineitem_price": ("lineitem_price",),
    "lineitem_quantity": ("lineitem_quantity",),
    "financial_status": ("financial_status",),
    "cancelled_at": ("cancelled_at",),
    "source": ("source", "source_name"),
    "currency": ("currency",),
    "orders": ("orders",),
}

SM_ALIASES: Dict[str, Tuple[str, ...]] = {
    "order_id": ("order_id",),
    "order_name": ("order_name",),
    "store": ("sm_store_id",),
    "channel": ("sm_channel",),
    "valid": ("is_order_sm_valid",),
    "processed_utc": ("order_processed_at",),
    "processed_local": ("order_processed_at_local_datetime",),
    "created_utc": ("order_created_at",),
    "cancelled_at": ("order_cancelled_at",),
    "currency": ("order_currency_code",),
    "gross": ("order_gross_revenue",),
    "discounts": ("order_discounts",),
    "returns": ("order_refunds",),
    "net": ("order_net_revenue",),
    "shipping": ("order_net_shipping", "order_gross_shipping"),
    "taxes": ("order_total_taxes",),
    "total": ("order_total_revenue",),
}

SM_EXCLUDED_CHANNELS = {"excluded", "draft_orders"}
SM_POS_CHANNELS = {"retail"}
SHOPIFY_POS_SOURCES = {"pos", "point of sale", "point_of_sale"}


class InputError(Exception):
    pass


@dataclass
class Order:
    key: str
    order_id: str = ""
    order_name: str = ""
    day: Optional[date] = None
    money: Dict[str, Optional[Decimal]] = field(default_factory=dict)
    # SM-only attributes
    valid: Optional[bool] = None
    channel: str = ""
    processed_utc: Optional[datetime] = None
    processed_local: Optional[datetime] = None
    created_utc: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    currency: str = ""
    # Shopify Orders-CSV attributes
    financial_status: str = ""
    source: str = ""
    approx_net: bool = False
    line_count: int = 0
    order_count: Optional[Decimal] = None  # ShopifyQL `orders`; 0 marks a return-only row

    def amount(self, name: str) -> Decimal:
        value = self.money.get(name)
        return value if value is not None else ZERO

    def has(self, name: str) -> bool:
        return self.money.get(name) is not None


# ---------------------------------------------------------------- parsing ---


def normalize_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")


def parse_money(raw: Optional[str]) -> Optional[Decimal]:
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "" or text.lower() in {"null", "none", "nan"}:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    text = re.sub(r"[^0-9.\-]", "", text)
    if text in {"", "-", "."}:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise InputError(f"cannot parse amount {raw!r}") from exc
    return -value if negative else value


_DT_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f %Z",
    "%Y-%m-%d %H:%M:%S %Z",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
)


def parse_datetime(raw: Optional[str]) -> Optional[datetime]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in {"null", "none"}:
        return None
    # Shopify CSV timestamps look like "2026-08-01 09:15:02 -0700"; bq CSV
    # timestamps look like "2026-08-01 16:15:02 UTC" or ISO with "Z".
    text = re.sub(r"\s[+-]\d{4}$", "", text)
    text = text.replace("Z", "") if text.endswith("Z") else text
    text = text.replace("+00:00", "")
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise InputError(f"cannot parse timestamp {raw!r}")


def parse_bool(raw: Optional[str]) -> Optional[bool]:
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text in {"true", "t", "1", "yes", "y"}:
        return True
    if text in {"false", "f", "0", "no", "n"}:
        return False
    if text == "":
        return None
    raise InputError(f"cannot parse boolean {raw!r}")


def normalize_order_id(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^gid://shopify/Order/", "", text, flags=re.IGNORECASE)
    if re.fullmatch(r"\d+(\.0+)?", text):
        text = text.split(".")[0]
    return text


def normalize_order_name(raw: str) -> str:
    return (raw or "").strip().lstrip("#").upper()


def read_csv(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    if not path.exists():
        raise InputError(f"file not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = [normalize_header(h) for h in (reader.fieldnames or [])]
        if not headers:
            raise InputError(f"no header row in {path}")
        rows = []
        for raw in reader:
            rows.append({normalize_header(k): (v if v is not None else "") for k, v in raw.items() if k is not None})
    return headers, rows


def resolve_columns(headers: List[str], aliases: Dict[str, Tuple[str, ...]], overrides: Dict[str, str]) -> Dict[str, str]:
    present = set(headers)
    resolved: Dict[str, str] = {}
    for logical, candidates in aliases.items():
        if logical in overrides and overrides[logical] in present:
            resolved[logical] = overrides[logical]
            continue
        for candidate in candidates:
            if candidate in present:
                resolved[logical] = candidate
                break
    return resolved


def parse_overrides(pairs: Iterable[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for pair in pairs or ():
        if "=" not in pair:
            raise InputError(f"--shopify-map expects <header>=<field>, got {pair!r}")
        header, logical = pair.split("=", 1)
        out[logical.strip()] = normalize_header(header)
    return out


# ------------------------------------------------------- shopify loaders ---


def detect_shopify_format(cols: Dict[str, str], headers: List[str]) -> str:
    if "lineitem_quantity" in cols or "financial_status" in cols or "subtotal" in cols:
        return "orders_export"
    if ("gross" in cols or "net" in cols or "total" in cols) and ("order_id" in cols or "order_name" in cols):
        return "shopifyql"
    raise InputError(
        "unrecognized Shopify export: need ShopifyQL columns (order_id/order_name + gross_sales/net_sales) "
        "or Orders-page columns (Name + Lineitem quantity / Financial Status). "
        f"Headers seen: {headers}"
    )


def is_totals_row(order_id: str, order_name: str) -> bool:
    ident = (order_id or order_name or "").strip().lower()
    return ident in {"", "total", "totals", "grand total"}


def make_key(order_id: str, order_name: str) -> str:
    oid = normalize_order_id(order_id)
    if oid:
        return f"id:{oid}"
    name = normalize_order_name(order_name)
    if name:
        return f"name:{name}"
    return ""


def load_shopifyql(rows: List[Dict[str, str]], cols: Dict[str, str]) -> Dict[str, Order]:
    orders: Dict[str, Order] = {}
    for row in rows:
        order_id = row.get(cols.get("order_id", ""), "") if "order_id" in cols else ""
        order_name = row.get(cols.get("order_name", ""), "") if "order_name" in cols else ""
        if is_totals_row(order_id, order_name):
            continue
        key = make_key(order_id, order_name)
        if not key:
            continue
        rec = orders.get(key)
        if rec is None:
            rec = Order(key=key, order_id=normalize_order_id(order_id), order_name=normalize_order_name(order_name))
            orders[key] = rec
            for name in MONEY_FIELDS:
                rec.money[name] = None
        # ShopifyQL may emit several rows per order when a return lands on a
        # different day than the sale; sum them and keep the earliest day,
        # which is the sale day.
        day_value = parse_datetime(row.get(cols["day"])) if "day" in cols else None
        if day_value is not None:
            day = day_value.date()
            rec.day = day if rec.day is None or day < rec.day else rec.day
        for name in MONEY_FIELDS:
            if name in cols:
                value = parse_money(row.get(cols[name]))
                if value is not None:
                    rec.money[name] = (rec.money[name] or ZERO) + value
        if "orders" in cols:
            count = parse_money(row.get(cols["orders"]))
            if count is not None:
                rec.order_count = (rec.order_count or ZERO) + count
        rec.line_count += 1
    return orders


def return_only(rec: Order) -> bool:
    """A Shopify row that carries a refund of an order sold outside the window.

    ShopifyQL books sales_reversals on the refund day under the original
    order id with `orders` = 0 and no gross. SourceMedium restates the
    original order instead, so these rows never have an in-window SM twin.
    """
    if rec.order_count is not None:
        return rec.order_count == ZERO
    return rec.amount("gross") == ZERO and rec.amount("returns") < ZERO


def load_orders_export(rows: List[Dict[str, str]], cols: Dict[str, str]) -> Dict[str, Order]:
    if "order_name" not in cols:
        raise InputError("Orders-page export needs a Name column")
    grouped: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    order_keys: Dict[str, str] = {}
    for row in rows:
        name = row.get(cols["order_name"], "")
        order_id = row.get(cols["order_id"], "") if "order_id" in cols else ""
        if is_totals_row(order_id, name):
            continue
        group_key = normalize_order_name(name) or normalize_order_id(order_id)
        if not group_key:
            continue
        grouped[group_key].append(row)
        if group_key not in order_keys or not order_keys[group_key].startswith("id:"):
            key = make_key(order_id, name)
            if key:
                order_keys[group_key] = key

    def first_non_empty(group: List[Dict[str, str]], column: Optional[str]) -> str:
        if not column:
            return ""
        for row in group:
            value = (row.get(column) or "").strip()
            if value:
                return value
        return ""

    orders: Dict[str, Order] = {}
    for group_key, group in grouped.items():
        key = order_keys.get(group_key) or f"name:{group_key}"
        rec = Order(key=key)
        rec.order_id = normalize_order_id(first_non_empty(group, cols.get("order_id")))
        rec.order_name = normalize_order_name(first_non_empty(group, cols.get("order_name")))
        created = parse_datetime(first_non_empty(group, cols.get("day")) or None)
        rec.day = created.date() if created else None
        rec.financial_status = first_non_empty(group, cols.get("financial_status")).lower()
        rec.source = first_non_empty(group, cols.get("source")).lower()
        rec.currency = first_non_empty(group, cols.get("currency")).upper()
        cancelled = first_non_empty(group, cols.get("cancelled_at"))
        rec.cancelled_at = parse_datetime(cancelled) if cancelled else None
        rec.line_count = len(group)

        gross = ZERO
        have_lines = "lineitem_price" in cols and "lineitem_quantity" in cols
        if have_lines:
            for row in group:
                price = parse_money(row.get(cols["lineitem_price"]))
                qty = parse_money(row.get(cols["lineitem_quantity"]))
                if price is not None and qty is not None:
                    gross += price * qty
        subtotal = parse_money(first_non_empty(group, cols.get("subtotal")) or None)
        discounts = parse_money(first_non_empty(group, cols.get("discounts")) or None)
        refunded = parse_money(first_non_empty(group, cols.get("returns")) or None)
        shipping = parse_money(first_non_empty(group, cols.get("shipping")) or None)
        taxes = parse_money(first_non_empty(group, cols.get("taxes")) or None)
        total = parse_money(first_non_empty(group, cols.get("total")) or None)

        rec.money["gross"] = gross if have_lines else (subtotal + (discounts or ZERO) if subtotal is not None else None)
        rec.money["discounts"] = -abs(discounts) if discounts is not None else ZERO
        rec.money["returns"] = -abs(refunded) if refunded is not None else ZERO
        if subtotal is not None:
            rec.money["net"] = subtotal + rec.money["returns"]
            rec.approx_net = bool(refunded)
        else:
            rec.money["net"] = None
        rec.money["shipping"] = shipping
        rec.money["taxes"] = taxes
        rec.money["total"] = total
        orders[key] = rec
    return orders


def load_shopify(path: Path, overrides: Dict[str, str]) -> Tuple[Dict[str, Order], str, List[str]]:
    headers, rows = read_csv(path)
    cols = resolve_columns(headers, SHOPIFY_ALIASES, overrides)
    fmt = detect_shopify_format(cols, headers)
    orders = load_shopifyql(rows, cols) if fmt == "shopifyql" else load_orders_export(rows, cols)
    notes: List[str] = []
    if fmt == "orders_export":
        notes.append(
            "Shopify Orders-page export detected: one row per line item, created-time basis, "
            "net sales approximated as Subtotal minus Refunded Amount (refunds may include shipping/tax)."
        )
    if "order_id" not in cols:
        notes.append("Shopify export has no order id column; matching on order name only.")
    return orders, fmt, notes


# ------------------------------------------------------------ sm loader ---


def load_sm(path: Path) -> Tuple[Dict[str, Order], List[str]]:
    headers, rows = read_csv(path)
    cols = resolve_columns(headers, SM_ALIASES, {})
    missing = [name for name in ("order_id", "net") if name not in cols]
    if missing:
        raise InputError(
            f"SourceMedium extract is missing required columns {missing}; run the canonical extract from "
            f"references/COMPARISON_PROTOCOL.md. Headers seen: {headers}"
        )
    notes: List[str] = []
    if "valid" not in cols:
        notes.append("SM extract has no is_order_sm_valid column; every SM row is treated as valid.")
    if "channel" not in cols:
        notes.append("SM extract has no sm_channel column; basis filtering by channel is disabled.")
    orders: Dict[str, Order] = {}
    for row in rows:
        order_id = row.get(cols["order_id"], "")
        order_name = row.get(cols["order_name"], "") if "order_name" in cols else ""
        key = make_key(order_id, order_name)
        if not key:
            continue
        if key in orders:
            raise InputError(f"duplicate order id in SM extract: {key}; obt_orders is one row per order, check the query")
        rec = Order(key=key, order_id=normalize_order_id(order_id), order_name=normalize_order_name(order_name))
        rec.valid = parse_bool(row.get(cols["valid"])) if "valid" in cols else True
        if rec.valid is None:
            rec.valid = True
        rec.channel = (row.get(cols["channel"], "") if "channel" in cols else "").strip().lower()
        rec.processed_utc = parse_datetime(row.get(cols["processed_utc"])) if "processed_utc" in cols else None
        rec.processed_local = parse_datetime(row.get(cols["processed_local"])) if "processed_local" in cols else None
        rec.created_utc = parse_datetime(row.get(cols["created_utc"])) if "created_utc" in cols else None
        rec.cancelled_at = parse_datetime(row.get(cols["cancelled_at"])) if "cancelled_at" in cols else None
        rec.currency = (row.get(cols["currency"], "") if "currency" in cols else "").strip().upper()
        for name in MONEY_FIELDS:
            rec.money[name] = parse_money(row.get(cols[name])) if name in cols else None
        orders[key] = rec
    return orders, notes


# ------------------------------------------------------------- analysis ---


def sm_day(rec: Order, mode: str, shopify_offset_hours: Optional[Decimal]) -> Optional[date]:
    if shopify_offset_hours is not None and rec.processed_utc is not None:
        return (rec.processed_utc + timedelta(hours=float(shopify_offset_hours))).date()
    if mode == "utc":
        return rec.processed_utc.date() if rec.processed_utc else None
    if rec.processed_local is not None:
        return rec.processed_local.date()
    return rec.processed_utc.date() if rec.processed_utc else None


def in_window(day: Optional[date], window: Optional[Tuple[date, date]]) -> bool:
    if window is None:
        return True
    if day is None:
        return True  # cannot exclude what we cannot date; reported separately
    return window[0] <= day <= window[1]


def align_signs(orders: Dict[str, Order], side: str, notes: List[str]) -> None:
    """Discounts and returns are negative on both sides by convention; flip a side that is positive."""
    for name in ("discounts", "returns"):
        values: List[Decimal] = []
        for rec in orders.values():
            value = rec.money.get(name)
            if value is not None:
                values.append(value)
        if not values:
            continue
        total = sum(values, ZERO)
        if total > ZERO and all(v >= ZERO for v in values):
            for rec in orders.values():
                value = rec.money.get(name)
                if value is not None:
                    rec.money[name] = -value
            notes.append(f"{side}: {name} were positive; sign flipped to the negative convention.")


def money_str(value: Optional[Decimal]) -> str:
    if value is None:
        return "n/a"
    return f"{value.quantize(CENT):,}"


def q2(value: Optional[Decimal]) -> str:
    """Plain two-decimal string for CSV cells and per-order tables."""
    return "" if value is None else str(value.quantize(CENT))


@dataclass
class Attribution:
    cls: str
    orders: int = 0
    net_effect: Decimal = ZERO
    keys: List[str] = field(default_factory=list)

    def add(self, key: str, effect: Decimal) -> None:
        self.orders += 1
        self.net_effect += effect
        self.keys.append(key)


def classify_delta(sh: Order, sm: Order, tol: Decimal) -> Tuple[str, Dict[str, Decimal]]:
    deltas: Dict[str, Decimal] = {}
    for name in MONEY_FIELDS:
        if sh.has(name) and sm.has(name):
            deltas[name] = sm.amount(name) - sh.amount(name)

    def off(name: str) -> bool:
        return name in deltas and abs(deltas[name]) > tol

    if not off("net") and not off("gross") and not off("discounts") and not off("returns"):
        if off("total") or off("shipping") or off("taxes"):
            return "shipping-tax-delta", deltas
        return "match", deltas
    if not off("gross") and not off("discounts") and off("returns"):
        return "refund-attribution", deltas
    if not off("gross") and off("discounts") and not off("returns"):
        return "discount-basis", deltas
    if off("gross"):
        return "gross-delta", deltas
    if off("net") and "gross" not in deltas and "returns" not in deltas:
        # Only net available on one side (Orders CSV without lines): cannot decompose.
        return "unexplained-delta", deltas
    return "unexplained-delta", deltas


def run(args: argparse.Namespace) -> int:
    notes: List[str] = []
    overrides = parse_overrides(args.shopify_map)
    shopify, fmt, sh_notes = load_shopify(Path(args.shopify), overrides)
    sm, sm_notes = load_sm(Path(args.sm))
    notes.extend(sh_notes)
    notes.extend(sm_notes)
    align_signs(shopify, "Shopify", notes)
    align_signs(sm, "SourceMedium", notes)

    window: Optional[Tuple[date, date]] = None
    if args.window:
        start, end = (datetime.strptime(d, "%Y-%m-%d").date() for d in args.window)
        if end < start:
            raise InputError("--window END precedes START")
        window = (start, end)
    tol_order = Decimal(str(args.tolerance_order))
    tol_total = Decimal(str(args.tolerance_total))
    offset = Decimal(str(args.shopify_utc_offset)) if args.shopify_utc_offset is not None else None
    if offset is not None and not any(rec.processed_utc for rec in sm.values()):
        notes.append("--shopify-utc-offset given but the SM extract has no order_processed_at; falling back to local days.")
        offset = None

    # Default basis is every order on both sides. exclude-pos exists only to
    # reproduce an operator's POS-excluded figure; it sets POS aside on both sides.
    basis_pos = args.basis == "exclude-pos"
    channel_basis = Attribution("channel-basis")
    pos_set_aside: set = set()
    if basis_pos:
        for key, rec in list(shopify.items()):
            if rec.source and rec.source in SHOPIFY_POS_SOURCES:
                channel_basis.add(key, ZERO)
                pos_set_aside.add(key)
                del shopify[key]

    # Name-only fallback keys: if one side has ids and the other only names, bridge by name.
    name_index_sm = {rec.order_name: key for key, rec in sm.items() if rec.order_name}
    rekeyed: Dict[str, Order] = {}
    for key, rec in shopify.items():
        if key.startswith("name:") and rec.order_name in name_index_sm:
            rekeyed[name_index_sm[rec.order_name]] = rec
        else:
            rekeyed[key] = rec
    shopify = rekeyed
    name_index_sh = {rec.order_name: key for key, rec in shopify.items() if rec.order_name}
    rekeyed_sm: Dict[str, Order] = {}
    for key, rec in sm.items():
        if key.startswith("name:") and rec.order_name in name_index_sh:
            rekeyed_sm[name_index_sh[rec.order_name]] = rec
        else:
            rekeyed_sm[key] = rec
    sm = rekeyed_sm

    # Day bucketing.
    sm_days = {key: sm_day(rec, args.sm_day, offset) for key, rec in sm.items()}
    sh_in = {key: in_window(rec.day, window) for key, rec in shopify.items()}
    sm_in = {key: in_window(sm_days[key], window) for key in sm}

    # Headline totals on the aligned basis.
    def sm_basis_ok(key: str) -> bool:
        rec = sm[key]
        if not rec.valid:
            return False
        if rec.channel in SM_EXCLUDED_CHANNELS:
            return False
        if basis_pos and rec.channel in SM_POS_CHANNELS:
            return False
        return True

    def sm_counts_in_total(key: str) -> bool:
        return sm_in[key] and sm_basis_ok(key)

    sh_total = {name: ZERO for name in MONEY_FIELDS}
    sm_total = {name: ZERO for name in MONEY_FIELDS}
    sh_count = sm_count = 0
    sh_fields_present = {name for name in MONEY_FIELDS if any(rec.has(name) for rec in shopify.values())}
    sm_fields_present = {name for name in MONEY_FIELDS if any(rec.has(name) for rec in sm.values())}
    for key, rec in shopify.items():
        if sh_in[key]:
            if not return_only(rec):
                sh_count += 1
            for name in MONEY_FIELDS:
                sh_total[name] += rec.amount(name)
    for key in sm:
        if sm_counts_in_total(key):
            sm_count += 1
            for name in MONEY_FIELDS:
                sm_total[name] += sm[key].amount(name)

    # Attribution of the NET delta: sm_total.net - sh_total.net.
    attributions: Dict[str, Attribution] = {}

    def attr(cls: str) -> Attribution:
        if cls not in attributions:
            attributions[cls] = Attribution(cls)
        return attributions[cls]

    matched_rows: List[Dict[str, str]] = []
    shopify_only_rows: List[Dict[str, str]] = []
    sm_only_rows: List[Dict[str, str]] = []
    daily: Dict[date, Dict[str, Decimal]] = defaultdict(lambda: {"sh_net": ZERO, "sm_net": ZERO, "sh_n": ZERO, "sm_n": ZERO})

    # The by-day view keeps padded days so boundary spill is visible.
    for key, rec in shopify.items():
        if rec.day is not None:
            daily[rec.day]["sh_net"] += rec.amount("net")
            daily[rec.day]["sh_n"] += 1
    for key in sm:
        day = sm_days[key]
        if sm_basis_ok(key) and day is not None:
            daily[day]["sm_net"] += sm[key].amount("net")
            daily[day]["sm_n"] += 1

    all_keys = set(shopify) | set(sm)
    for key in sorted(all_keys):
        sh = shopify.get(key)
        smr = sm.get(key)
        sm_day_value = sm_days.get(key)
        sm_day_text = sm_day_value.isoformat() if sm_day_value is not None else ""
        if sh is not None and smr is not None:
            sh_counts = sh_in[key]
            sm_counts = sm_counts_in_total(key)
            cls, deltas = classify_delta(sh, smr, tol_order)
            effect = ZERO
            if sh_counts and sm_counts:
                effect = smr.amount("net") - sh.amount("net")
                final_cls = cls
            elif sh_counts and not sm_counts:
                effect = -sh.amount("net")
                if return_only(sh):
                    final_cls = "prior-period-return"
                elif not smr.valid:
                    final_cls = "sm-invalid"
                elif smr.channel in SM_EXCLUDED_CHANNELS:
                    final_cls = "sm-channel"
                elif basis_pos and smr.channel in SM_POS_CHANNELS:
                    final_cls = "channel-basis"
                else:
                    final_cls = "day-shift"
            elif sm_counts and not sh_counts:
                effect = smr.amount("net")
                final_cls = "day-shift"
            else:
                final_cls = "outside-window"
            if final_cls != "outside-window":
                attr(final_cls).add(key, effect)
            matched_rows.append(
                {
                    "key": key,
                    "order_name": sh.order_name or smr.order_name,
                    "class": final_cls,
                    "amount_class": cls,
                    "shopify_day": sh.day.isoformat() if sh.day else "",
                    "sm_day": sm_day_text,
                    "sm_valid": str(smr.valid),
                    "sm_channel": smr.channel,
                    "shopify_net": q2(sh.amount("net")),
                    "sm_net": q2(smr.amount("net")),
                    "net_effect": q2(effect),
                    **{f"delta_{name}": q2(value) for name, value in deltas.items()},
                }
            )
        elif sh is not None:
            if not sh_in[key]:
                continue
            cls = "prior-period-return" if return_only(sh) else "missing-in-sm"
            effect = -sh.amount("net")
            attr(cls).add(key, effect)
            shopify_only_rows.append(
                {
                    "key": key,
                    "order_name": sh.order_name,
                    "class": cls,
                    "shopify_day": sh.day.isoformat() if sh.day else "",
                    "shopify_net": q2(sh.amount("net")),
                    "financial_status": sh.financial_status,
                    "source": sh.source,
                    "net_effect": q2(effect),
                }
            )
        else:
            assert smr is not None
            if not sm_in[key]:
                continue
            if not smr.valid:
                cls, effect = "sm-invalid-unmatched", ZERO
            elif smr.channel in SM_EXCLUDED_CHANNELS:
                cls, effect = "sm-channel-unmatched", ZERO
            elif basis_pos and smr.channel in SM_POS_CHANNELS:
                cls, effect = "channel-basis", ZERO
            else:
                cls, effect = "unexplained-sm-only", smr.amount("net")
            if not (cls == "channel-basis" and key in pos_set_aside):
                attr(cls).add(key, effect)
            sm_only_rows.append(
                {
                    "key": key,
                    "order_name": smr.order_name,
                    "class": cls,
                    "sm_day": sm_day_text,
                    "sm_valid": str(smr.valid),
                    "sm_channel": smr.channel,
                    "sm_cancelled_at": smr.cancelled_at.isoformat(sep=" ") if smr.cancelled_at else "",
                    "sm_net": q2(smr.amount("net")),
                    "net_effect": q2(effect),
                }
            )
    if channel_basis.orders:
        existing = attr("channel-basis")
        existing.orders += channel_basis.orders
        existing.keys.extend(channel_basis.keys)

    headline_delta = sm_total["net"] - sh_total["net"]
    attributed = sum((a.net_effect for a in attributions.values()), ZERO)
    identity_ok = abs(headline_delta - attributed) <= CENT
    residual_classes = {"missing-in-sm", "unexplained-sm-only", "unexplained-delta"}
    residual = sum((a.net_effect for cls, a in attributions.items() if cls in residual_classes), ZERO)
    residual_orders = sum(a.orders for cls, a in attributions.items() if cls in residual_classes)

    reconciled = abs(headline_delta) <= tol_total and residual_orders == 0 and sh_count == sm_count
    verdict = "reconciled" if reconciled else ("explained" if residual_orders == 0 else "differences-remain")

    # ------------------------------------------------------------ report ---
    out: List[str] = []
    p = out.append
    p(f"# Reconciliation: Shopify vs SourceMedium")
    p("")
    p(f"**Verdict:** `{verdict}`  ")
    p(f"Shopify export format: `{fmt}`; basis: `{args.basis}`; window: "
      f"{window[0].isoformat() + ' to ' + window[1].isoformat() if window else 'none (all rows)'}; "
      f"SM day: {'UTC' + format(offset, '+') + 'h (Shopify offset)' if offset is not None else args.sm_day}.")
    if notes:
        p("")
        p("Notes:")
        for note in notes:
            p(f"- {note}")
    p("")
    p("## Totals on the aligned basis")
    p("")
    p("| Metric | Shopify | SourceMedium | SM - Shopify |")
    p("|---|---:|---:|---:|")
    p(f"| Orders | {sh_count} | {sm_count} | {sm_count - sh_count:+d} |")
    for name in MONEY_FIELDS:
        if name in sh_fields_present or name in sm_fields_present:
            shv = sh_total[name] if name in sh_fields_present else None
            smv = sm_total[name] if name in sm_fields_present else None
            delta = (smv - shv) if (shv is not None and smv is not None) else None
            p(f"| {name} | {money_str(shv)} | {money_str(smv)} | {money_str(delta)} |")
    p("")
    p(f"Headline net delta (SM - Shopify): **{money_str(headline_delta)}**; "
      f"attributed: {money_str(attributed)}; residual (unexplained classes): **{money_str(residual)}** across {residual_orders} orders.")
    if not identity_ok:
        p("")
        p(f"WARNING: attribution ({money_str(attributed)}) does not sum to the headline delta ({money_str(headline_delta)}). "
          "Inputs are malformed (duplicate ids, totals row, or mixed stores). Treat the report as inconclusive.")

    p("")
    p("## Attribution of the net delta")
    p("")
    p("| Class | Orders | Net effect | Sample ids |")
    p("|---|---:|---:|---|")
    order_of_classes = [
        "match", "day-shift", "refund-attribution", "prior-period-return", "discount-basis", "gross-delta",
        "shipping-tax-delta", "sm-invalid", "sm-channel", "channel-basis", "sm-invalid-unmatched", "sm-channel-unmatched",
        "missing-in-sm", "unexplained-sm-only", "unexplained-delta",
    ]
    for cls in order_of_classes + sorted(set(attributions) - set(order_of_classes)):
        if cls in attributions:
            a = attributions[cls]
            sample = ", ".join(k.split(":", 1)[1] for k in a.keys[:5])
            more = f" (+{len(a.keys) - 5} more)" if len(a.keys) > 5 else ""
            p(f"| `{cls}` | {a.orders} | {money_str(a.net_effect)} | {sample}{more} |")
    p("")
    p("Classes `missing-in-sm`, `unexplained-sm-only`, and `unexplained-delta` are the residual. "
      "`sm-invalid-unmatched` and `sm-channel-unmatched` are SM rows Shopify did not export and SM does not count; zero effect, listed for completeness.")

    if daily:
        p("")
        p("## By day")
        p("")
        p("| Day | Shopify orders | SM orders | Shopify net | SM net | SM - Shopify |")
        p("|---|---:|---:|---:|---:|---:|")
        for day in sorted(daily):
            row = daily[day]
            flag = "" if window is None or (window[0] <= day <= window[1]) else " (outside window)"
            p(f"| {day.isoformat()}{flag} | {int(row['sh_n'])} | {int(row['sm_n'])} | {money_str(row['sh_net'])} | {money_str(row['sm_net'])} | {money_str(row['sm_net'] - row['sh_net'])} |")

    delta_rows = [r for r in matched_rows if r["class"] not in {"match", "outside-window"}]
    if delta_rows:
        p("")
        p("## Matched orders with differences (first 25)")
        p("")
        p("| Order | Class | Shopify day | SM day | SM valid | SM channel | Shopify net | SM net | Effect |")
        p("|---|---|---|---|---|---|---:|---:|---:|")
        for r in delta_rows[:25]:
            p(f"| {r['order_name'] or r['key']} | `{r['class']}` | {r['shopify_day']} | {r['sm_day']} | {r['sm_valid']} | {r['sm_channel']} | {r['shopify_net']} | {r['sm_net']} | {r['net_effect']} |")
    if shopify_only_rows:
        p("")
        p("## Shopify orders with no SourceMedium row (first 25)")
        p("")
        p("| Order | Shopify day | Financial status | Source | Shopify net |")
        p("|---|---|---|---|---:|")
        for r in shopify_only_rows[:25]:
            p(f"| {r['order_name'] or r['key']} | {r['shopify_day']} | {r['financial_status']} | {r['source']} | {r['shopify_net']} |")
    if sm_only_rows:
        p("")
        p("## SourceMedium rows Shopify did not export (first 25)")
        p("")
        p("| Order | Class | SM day | SM valid | SM channel | Cancelled at | SM net |")
        p("|---|---|---|---|---|---|---:|")
        for r in sm_only_rows[:25]:
            p(f"| {r['order_name'] or r['key']} | `{r['class']}` | {r['sm_day']} | {r['sm_valid']} | {r['sm_channel']} | {r['sm_cancelled_at']} | {r['sm_net']} |")

    p("")
    p("## Next rung")
    p("")
    hints = []
    if "day-shift" in attributions:
        hints.append("`day-shift` present: run the store timezone offset check; retry with `--shopify-utc-offset` to test it.")
    if "sm-invalid" in attributions:
        hints.append("`sm-invalid` present: these are counted by Shopify and excluded by `is_order_sm_valid` (cancelled/voided/test/fully refunded). Definition, not defect.")
    if "refund-attribution" in attributions:
        hints.append("`refund-attribution` present: Shopify books returns on the refund day; SM restates the order. Expected at by-day grain.")
    if "prior-period-return" in attributions:
        hints.append("`prior-period-return` present: refunds of orders sold before the window, booked by Shopify on the refund day (orders = 0). SM carries them on the original order. Definition, not defect.")
    if "missing-in-sm" in attributions:
        hints.append("`missing-in-sm` present: compare these orders' times with obt_orders table_last_data_date (freshness) and confirm the store mapping before escalating.")
    if "unexplained-sm-only" in attributions:
        hints.append("`unexplained-sm-only` present: SM has valid in-scope orders Shopify did not export; check the Shopify export filters and the store handle.")
    if "unexplained-delta" in attributions:
        hints.append("`unexplained-delta` present: open these orders in Shopify admin and compare the timeline (edits, partial refunds) with the SM row.")
    if not hints:
        hints.append("Nothing left to explain at order grain.")
    for h in hints:
        p(f"- {h}")

    print("\n".join(out))

    if args.out_dir:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        write_rows(out_dir / "matched_deltas.csv", delta_rows)
        write_rows(out_dir / "shopify_only.csv", shopify_only_rows)
        write_rows(out_dir / "sm_only.csv", sm_only_rows)
        write_rows(
            out_dir / "attribution.csv",
            [{"class": cls, "orders": a.orders, "net_effect": q2(a.net_effect), "ids": ";".join(a.keys)} for cls, a in attributions.items()],
        )
        print(f"\nWrote per-category CSVs to {out_dir}", file=sys.stderr)

    if not identity_ok:
        return EXIT_INPUT
    return EXIT_OK if reconciled else EXIT_DIFFERENCES


def write_rows(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    fieldnames: List[str] = []
    for row in rows:
        for name in row:
            if name not in fieldnames:
                fieldnames.append(name)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or ["key"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shopify", required=True, help="Shopify export CSV (ShopifyQL sales by order, or Orders page export).")
    parser.add_argument("--sm", required=True, help="SourceMedium obt_orders extract CSV (canonical query).")
    parser.add_argument("--window", nargs=2, metavar=("START", "END"), help="Claimed window, YYYY-MM-DD inclusive. Rows outside it are matched but not totaled.")
    parser.add_argument("--basis", choices=["all", "exclude-pos"], default="all", help="Default all: every order on both sides, POS included. Use exclude-pos only to reproduce a figure quoted from a POS-excluded report.")
    parser.add_argument("--sm-day", choices=["local", "utc"], default="local", help="Which SM timestamp buckets the SM day. Default local.")
    parser.add_argument("--shopify-utc-offset", type=float, default=None, help="Re-bucket SM days from order_processed_at (UTC) into this offset, e.g. -7 for Pacific daylight time.")
    parser.add_argument("--tolerance-order", type=float, default=0.01, help="Per-order amount tolerance. Default 0.01.")
    parser.add_argument("--tolerance-total", type=float, default=1.00, help="Headline net delta tolerance for a reconciled verdict. Default 1.00.")
    parser.add_argument("--shopify-map", action="append", default=[], metavar="HEADER=FIELD", help="Map a Shopify header to a logical field (gross, discounts, returns, net, shipping, taxes, total, order_id, order_name, day, source, financial_status).")
    parser.add_argument("--out-dir", help="Write matched_deltas.csv, shopify_only.csv, sm_only.csv, attribution.csv here.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    try:
        return run(args)
    except InputError as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return EXIT_INPUT


if __name__ == "__main__":
    raise SystemExit(main())
