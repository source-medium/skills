#!/usr/bin/env python3
"""Reconcile a Shopify order export against a SourceMedium obt_orders extract.

Matches orders by platform order id (order name as fallback), aligns the
comparison basis (POS scope, window, sign convention, day bucketing), then
attributes every unit of the net-revenue delta to a named cause. The
attribution rows sum exactly to the headline delta by construction.

The Shopify total sums export rows by their own day, which is the figure
Shopify Analytics shows for the window: a refund booked inside the window
counts there even when its order was sold on a padding day.

Inputs
  --shopify   ShopifyQL "sales by order" export CSV, or the Shopify admin
              Orders page CSV (one row per line item). Format auto-detected.
  --sm        CSV produced by the canonical extract in
              references/COMPARISON_PROTOCOL.md (MCP pages written to CSV,
              or sm_bq_query.py --format csv output).

Exit codes
  0  reconciled: headline delta within --tolerance-total, no residual, and
     any quoted figure reproduced
  1  differences remain (attributed or unexplained); read the report
  2  input or argument error (missing file, unrecognized columns, duplicate
     ids, an invalid --window)

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
    "latest_refund": ("latest_order_refund_date",),
    "canonicalized": ("is_order_currency_canonicalized",),
    "converted_currency": ("order_converted_currency_code",),
}

SM_EXCLUDED_CHANNELS = {"excluded", "draft_orders", "exchanged"}
SM_POS_CHANNELS = {"retail"}
SHOPIFY_POS_SOURCES = {"pos", "point of sale", "point_of_sale"}

# Classes that no rung explains yet: they keep the verdict at differences-remain.
RESIDUAL_CLASSES = {
    "missing-in-sm", "unexplained-sm-only", "unexplained-delta",
    "refund-missing-in-sm", "refund-missing-in-shopify", "undated",
}


class InputError(Exception):
    pass


@dataclass
class Row:
    """One export row: an order's amounts booked on one day."""

    day: Optional[date]
    money: Dict[str, Optional[Decimal]]
    orders: Optional[Decimal] = None  # ShopifyQL `orders`; 0 on a reversal-only row


@dataclass
class Order:
    key: str
    order_id: str = ""
    order_name: str = ""
    day: Optional[date] = None  # Shopify: the sale day; SM: unused (see sm_day)
    money: Dict[str, Optional[Decimal]] = field(default_factory=dict)
    rows: List[Row] = field(default_factory=list)  # Shopify only
    # SM-only attributes
    valid: Optional[bool] = None
    channel: str = ""
    processed_utc: Optional[datetime] = None
    processed_local: Optional[datetime] = None
    created_utc: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    currency: str = ""
    latest_refund: Optional[date] = None
    canonicalized: Optional[bool] = None
    converted_currency: str = ""
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
    if re.fullmatch(r"\d+(\.\d+)?([eE][+-]?\d+)?", text):
        raise InputError(
            f"cannot parse timestamp {raw!r}: it looks like epoch seconds, which is how the MCP returns a TIMESTAMP. "
            "Select it with FORMAT_TIMESTAMP('%F %T', ...) as the canonical extract does."
        )
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
    """Totals rows, and the placeholder rows TIMESERIES emits for days with no data (id "None")."""
    ident = (order_id or order_name or "").strip().lower()
    return ident in {"", "total", "totals", "grand total", "none", "null"}


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
        # ShopifyQL emits one row per order per day: a refund, cancellation, or
        # edit booked on a later day is its own row. Keep every row with its
        # day (totals follow the row's day, as Shopify's report does) and sum
        # them for the order-level comparison.
        day_value = parse_datetime(row.get(cols["day"])) if "day" in cols else None
        row_money: Dict[str, Optional[Decimal]] = {}
        for name in MONEY_FIELDS:
            if name in cols:
                value = parse_money(row.get(cols[name]))
                row_money[name] = value
                if value is not None:
                    rec.money[name] = (rec.money[name] or ZERO) + value
        count = parse_money(row.get(cols["orders"])) if "orders" in cols else None
        if count is not None:
            rec.order_count = (rec.order_count or ZERO) + count
        rec.rows.append(Row(day=day_value.date() if day_value else None, money=row_money, orders=count))
        rec.line_count += 1
    for rec in orders.values():
        # The sale day is the earliest day carrying an order (`orders` > 0);
        # without an `orders` column, the earliest day.
        dated = [r for r in rec.rows if r.day is not None]
        sales = [r for r in dated if r.orders is not None and r.orders > ZERO]
        pool = sales or dated
        rec.day = min(r.day for r in pool) if pool else None
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
        # The Orders export carries each order's current amounts on one row,
        # dated by creation; nothing is booked on a later day.
        rec.rows = [Row(day=rec.day, money=dict(rec.money))]
        orders[key] = rec
    return orders


def load_shopify(path: Path, overrides: Dict[str, str]) -> Tuple[Dict[str, Order], str, List[str], bool]:
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
    return orders, fmt, notes, "day" in cols


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
        refund_day = parse_datetime(row.get(cols["latest_refund"])) if "latest_refund" in cols else None
        rec.latest_refund = refund_day.date() if refund_day else None
        rec.canonicalized = parse_bool(row.get(cols["canonicalized"])) if "canonicalized" in cols else None
        rec.converted_currency = (row.get(cols["converted_currency"], "") if "converted_currency" in cols else "").strip().upper()
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
    """A row with no day is never in a window; it is reported as undated instead."""
    if window is None:
        return True
    return day is not None and window[0] <= day <= window[1]


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
                for row in rec.rows:
                    if row.money.get(name) is not None:
                        row.money[name] = -row.money[name]
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


@dataclass
class RowSplit:
    """An order's Shopify net split by where its rows fall against the window."""

    in_net: Decimal = ZERO
    out_net: Decimal = ZERO
    undated_net: Decimal = ZERO
    has_in: bool = False
    has_out: bool = False
    has_undated: bool = False

    @property
    def all_net(self) -> Decimal:
        return self.in_net + self.out_net + self.undated_net


def split_rows(rec: Order, window: Optional[Tuple[date, date]]) -> RowSplit:
    split = RowSplit()
    for row in rec.rows:
        net = row.money.get("net") or ZERO
        if window is not None and row.day is None:
            split.undated_net += net
            split.has_undated = True
        elif in_window(row.day, window):
            split.in_net += net
            split.has_in = True
        else:
            split.out_net += net
            split.has_out = True
    return split


def classify_delta(sh: Order, sm: Order, tol: Decimal, export_last_day: Optional[date]) -> Tuple[str, Dict[str, Decimal]]:
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
        if deltas["returns"] > ZERO:
            # Shopify booked more refund for this order inside the export than
            # SourceMedium carries. SourceMedium restates every refund onto the
            # order, so timing cannot explain it; freshness might.
            return "refund-missing-in-sm", deltas
        # SourceMedium carries more refund: timing when the refund came after
        # the last day the export covers. A refund SourceMedium dates inside the
        # export, which the export does not show, is not timing.
        if sm.latest_refund is not None and export_last_day is not None and sm.latest_refund <= export_last_day:
            return "refund-missing-in-shopify", deltas
        return "refund-attribution", deltas
    if not off("gross") and off("discounts") and not off("returns"):
        return "discount-basis", deltas
    if off("gross"):
        return "gross-delta", deltas
    return "unexplained-delta", deltas


def run(args: argparse.Namespace) -> int:
    notes: List[str] = []
    overrides = parse_overrides(args.shopify_map)
    shopify, fmt, sh_notes, has_day = load_shopify(Path(args.shopify), overrides)
    sm, sm_notes = load_sm(Path(args.sm))
    notes.extend(sh_notes)
    notes.extend(sm_notes)
    align_signs(shopify, "Shopify", notes)
    align_signs(sm, "SourceMedium", notes)

    window: Optional[Tuple[date, date]] = tuple(args.window) if args.window else None  # type: ignore[assignment]
    if window is not None and not has_day:
        raise InputError(
            "--window needs a day on every Shopify row, and this export has no day column. "
            "Re-export with TIMESERIES day (or GROUP BY ..., day), or run without --window."
        )
    tol_order = Decimal(str(args.tolerance_order))
    tol_total = Decimal(str(args.tolerance_total))
    offset = Decimal(str(args.shopify_utc_offset)) if args.shopify_utc_offset is not None else None
    if offset is not None and not any(rec.processed_utc for rec in sm.values()):
        notes.append("--shopify-utc-offset given but the SM extract has no order_processed_at; falling back to local days.")
        offset = None
    # The Orders-page export shows each order's amounts as of the export, not
    # as of a day, so it has no last covered day to date a refund against.
    dated_days = [row.day for rec in shopify.values() for row in rec.rows if row.day is not None]
    export_last_day = max(dated_days) if fmt == "shopifyql" and dated_days else None

    canonicalized = [rec for rec in sm.values() if rec.canonicalized]
    if canonicalized:
        currencies = sorted({rec.converted_currency for rec in canonicalized if rec.converted_currency}) or ["unknown"]
        notes.append(
            f"{len(canonicalized)} SM rows are currency-converted (is_order_currency_canonicalized) into "
            f"{', '.join(currencies)}: their order_* amounts are not in the order's own currency. "
            "See the currency rung before comparing amounts."
        )

    # Default basis is every order on both sides. exclude-pos exists only to
    # reproduce an operator's POS-excluded figure; it sets POS aside on both sides.
    basis_pos = args.basis == "exclude-pos"
    if basis_pos and fmt == "shopifyql":
        notes.append(
            "--basis exclude-pos with the Analytics export: the export has no channel column, so only SM retail rows "
            "are set aside. Shopify's total still includes POS, and matched POS orders show as channel-basis."
        )
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
    sm_in = {key: in_window(sm_days[key], window) for key in sm}
    splits = {key: split_rows(rec, window) for key, rec in shopify.items()}

    def sh_sale_in(rec: Order) -> bool:
        """The order's sale is in the window. A refund-only order has no sale in the export."""
        return not return_only(rec) and (window is None or in_window(rec.day, window))

    def sm_undated(key: str) -> bool:
        return window is not None and sm_days[key] is None

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

    def sm_set_aside_class(key: str) -> str:
        """Why an SM order Shopify counts is not in the SM total."""
        rec = sm[key]
        if rec.channel in SM_EXCLUDED_CHANNELS:
            return "sm-channel"
        if not rec.valid:
            return "sm-invalid"
        if basis_pos and rec.channel in SM_POS_CHANNELS:
            return "channel-basis"
        if sm_undated(key):
            return "undated"
        return "day-shift"

    # Headline totals on the aligned basis. Shopify rows count on their own day.
    sh_total = {name: ZERO for name in MONEY_FIELDS}
    sm_total = {name: ZERO for name in MONEY_FIELDS}
    sh_count = ZERO
    sm_count = 0
    sh_fields_present = {name for name in MONEY_FIELDS if any(rec.has(name) for rec in shopify.values())}
    sm_fields_present = {name for name in MONEY_FIELDS if any(rec.has(name) for rec in sm.values())}
    for key, rec in shopify.items():
        has_orders = any(row.orders is not None for row in rec.rows)
        for row in rec.rows:
            if in_window(row.day, window):
                for name in MONEY_FIELDS:
                    sh_total[name] += row.money.get(name) or ZERO
                if row.orders is not None:
                    sh_count += row.orders
        if not has_orders and sh_sale_in(rec):
            sh_count += 1
    for key in sm:
        if sm_counts_in_total(key):
            sm_count += 1
            for name in MONEY_FIELDS:
                sm_total[name] += sm[key].amount(name)

    # Attribution of the NET delta: sm_total.net - sh_total.net. For each order
    # the delta is (SM net if counted) - (its Shopify rows dated in the window).
    attributions: Dict[str, Attribution] = {}

    def attr(cls: str) -> Attribution:
        if cls not in attributions:
            attributions[cls] = Attribution(cls)
        return attributions[cls]

    matched_rows: List[Dict[str, str]] = []
    shopify_only_rows: List[Dict[str, str]] = []
    sm_only_rows: List[Dict[str, str]] = []
    undated_rows: List[Dict[str, str]] = []
    daily: Dict[date, Dict[str, Decimal]] = defaultdict(lambda: {"sh_net": ZERO, "sm_net": ZERO, "sh_n": ZERO, "sm_n": ZERO})

    # The by-day view keeps padded days so boundary spill is visible.
    for key, rec in shopify.items():
        has_orders = any(row.orders is not None for row in rec.rows)
        for row in rec.rows:
            if row.day is not None:
                daily[row.day]["sh_net"] += row.money.get("net") or ZERO
                if row.orders is not None:
                    daily[row.day]["sh_n"] += row.orders
        if not has_orders and rec.day is not None and not return_only(rec):
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
        sm_counts = smr is not None and sm_counts_in_total(key)
        sm_net = smr.amount("net") if sm_counts and smr is not None else ZERO
        sm_day_value = sm_days.get(key)
        sm_day_text = sm_day_value.isoformat() if sm_day_value is not None else ""
        effects: List[Tuple[str, Decimal]] = []

        if sh is not None:
            split = splits[key]
            amount_cls, deltas = classify_delta(sh, smr, tol_order, export_last_day) if smr is not None else ("", {})
            if sh_sale_in(sh):
                # delta = (SM - whole Shopify order) + rows dated after the
                # window edge + rows with no day.
                if smr is None:
                    main_cls = "missing-in-sm"
                elif sm_counts:
                    main_cls = amount_cls
                else:
                    main_cls = sm_set_aside_class(key)
                effects.append((main_cls, sm_net - split.all_net))
                if split.out_net != ZERO:
                    effects.append(("edge-reversal", split.out_net))
            else:
                # The sale is outside the window (a padding day), the order is
                # refund-only, or no row has a day. Its in-window rows count on
                # the Shopify side alone.
                if split.has_in:
                    effects.append(("prior-period-return" if return_only(sh) else "edge-reversal", -split.in_net))
                if sm_counts:
                    effects.append(("undated" if sh.day is None and not return_only(sh) else "day-shift", sm_net))
            if split.has_undated and not any(cls == "undated" for cls, _ in effects):
                effects.append(("undated", split.undated_net if sh_sale_in(sh) else ZERO))
            if split.has_undated:
                undated_rows.append({"key": key, "side": "shopify", "order_name": sh.order_name, "net": q2(split.undated_net)})
        else:
            assert smr is not None
            amount_cls, deltas = "", {}
            if sm_counts:
                effects.append(("unexplained-sm-only", sm_net))
            elif sm_undated(key):
                effects.append(("undated", ZERO))
            elif sm_in[key]:
                if smr.channel in SM_EXCLUDED_CHANNELS:
                    effects.append(("sm-channel-unmatched", ZERO))
                elif not smr.valid:
                    effects.append(("sm-invalid-unmatched", ZERO))
                elif basis_pos and smr.channel in SM_POS_CHANNELS and key not in pos_set_aside:
                    # A POS twin already set aside on the Shopify side is counted there once.
                    effects.append(("channel-basis", ZERO))
        if smr is not None and sm_undated(key):
            undated_rows.append({"key": key, "side": "sourcemedium", "order_name": smr.order_name, "net": q2(smr.amount("net"))})

        for cls, effect in effects:
            attr(cls).add(key, effect)
        primary = effects[0][0] if effects else "outside-window"
        total_effect = sum((effect for _, effect in effects), ZERO)
        other = ";".join(f"{cls}={q2(effect)}" for cls, effect in effects[1:])

        if sh is not None and smr is not None:
            matched_rows.append(
                {
                    "key": key,
                    "order_name": sh.order_name or smr.order_name,
                    "class": primary,
                    "other_classes": other,
                    "amount_class": amount_cls,
                    "shopify_day": sh.day.isoformat() if sh.day else "",
                    "sm_day": sm_day_text,
                    "sm_valid": str(smr.valid),
                    "sm_channel": smr.channel,
                    "sm_latest_refund": smr.latest_refund.isoformat() if smr.latest_refund else "",
                    "shopify_net": q2(sh.amount("net")),
                    "sm_net": q2(smr.amount("net")),
                    "net_effect": q2(total_effect),
                    **{f"delta_{name}": q2(value) for name, value in deltas.items()},
                }
            )
        elif sh is not None and effects:
            shopify_only_rows.append(
                {
                    "key": key,
                    "order_name": sh.order_name,
                    "class": primary,
                    "other_classes": other,
                    "shopify_day": sh.day.isoformat() if sh.day else "",
                    "shopify_net": q2(sh.amount("net")),
                    "financial_status": sh.financial_status,
                    "source": sh.source,
                    "net_effect": q2(total_effect),
                }
            )
        elif smr is not None and sh is None and effects:
            sm_only_rows.append(
                {
                    "key": key,
                    "order_name": smr.order_name,
                    "class": primary,
                    "sm_day": sm_day_text,
                    "sm_valid": str(smr.valid),
                    "sm_channel": smr.channel,
                    "sm_cancelled_at": smr.cancelled_at.isoformat(sep=" ") if smr.cancelled_at else "",
                    "sm_net": q2(smr.amount("net")),
                    "net_effect": q2(total_effect),
                }
            )
    if channel_basis.orders:
        existing = attr("channel-basis")
        existing.orders += channel_basis.orders
        existing.keys.extend(channel_basis.keys)

    headline_delta = sm_total["net"] - sh_total["net"]
    attributed = sum((a.net_effect for a in attributions.values()), ZERO)
    identity_ok = abs(headline_delta - attributed) <= CENT
    residual = sum((a.net_effect for cls, a in attributions.items() if cls in RESIDUAL_CLASSES), ZERO)
    residual_orders = sum(a.orders for cls, a in attributions.items() if cls in RESIDUAL_CLASSES)

    # The operator's quoted figures against what the inputs reproduce.
    quote_lines: List[str] = []
    quotes_ok = True
    for label, quoted, computed in (
        ("Shopify", args.quoted_shopify_net, sh_total["net"]),
        ("SourceMedium", args.quoted_sm_net, sm_total["net"]),
    ):
        if quoted is None:
            continue
        gap = quoted - computed
        ok = abs(gap) <= tol_total
        quotes_ok = quotes_ok and ok
        quote_lines.append(
            f"| {label} | {money_str(quoted)} | {money_str(computed)} | {money_str(gap)} | {'yes' if ok else 'no'} |"
        )

    sh_count_int = int(sh_count)
    reconciled = abs(headline_delta) <= tol_total and residual_orders == 0 and sh_count_int == sm_count and quotes_ok
    if reconciled:
        verdict = "reconciled"
    elif residual_orders == 0 and quotes_ok:
        verdict = "explained"
    else:
        verdict = "differences-remain"

    # ------------------------------------------------------------ report ---
    out: List[str] = []
    p = out.append
    p(f"# Reconciliation: Shopify vs SourceMedium")
    p("")
    p(f"**Verdict:** `{verdict}`  ")
    p(f"Shopify export format: `{fmt}`; basis: `{args.basis}`; window: "
      f"{window[0].isoformat() + ' to ' + window[1].isoformat() if window else 'none (all rows)'}; "
      f"SM day: {'UTC' + format(offset, '+') + 'h (Shopify offset)' if offset is not None else args.sm_day}.")
    if undated_rows:
        sh_undated = sum(1 for r in undated_rows if r["side"] == "shopify")
        sm_undated_n = len(undated_rows) - sh_undated
        notes.append(
            f"Undated rows: {sh_undated} Shopify order(s) and {sm_undated_n} SM order(s) have rows with no day. "
            "They are left out of the window totals and listed under Undated rows; re-export with a day on every row."
        )
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
    p(f"| Orders | {sh_count_int} | {sm_count} | {sm_count - sh_count_int:+d} |")
    for name in MONEY_FIELDS:
        if name in sh_fields_present or name in sm_fields_present:
            shv = sh_total[name] if name in sh_fields_present else None
            smv = sm_total[name] if name in sm_fields_present else None
            delta = (smv - shv) if (shv is not None and smv is not None) else None
            p(f"| {name} | {money_str(shv)} | {money_str(smv)} | {money_str(delta)} |")
    p("")
    p("The Shopify column sums export rows by their own day: it is the figure Shopify shows for the window.")
    p("")
    p(f"Headline net delta (SM - Shopify): **{money_str(headline_delta)}**; "
      f"attributed: {money_str(attributed)}; residual (unexplained classes): **{money_str(residual)}** across {residual_orders} orders.")
    if not identity_ok:
        p("")
        p(f"WARNING: attribution ({money_str(attributed)}) does not sum to the headline delta ({money_str(headline_delta)}). "
          "Inputs are malformed (duplicate ids, totals row, or mixed stores). Treat the report as inconclusive.")
    if quote_lines:
        p("")
        p("## Quoted figures")
        p("")
        p("| Side | Quoted net | From the inputs | Gap | Reproduced |")
        p("|---|---:|---:|---:|---|")
        for line in quote_lines:
            p(line)
        p("")
        p("A gap is not explained by anything below: the quote and the inputs differ in window, store, a filter on the "
          "quoted report (for example POS excluded), or the metric quoted.")

    p("")
    p("## Attribution of the net delta")
    p("")
    p("| Class | Orders | Net effect | Sample ids |")
    p("|---|---:|---:|---|")
    order_of_classes = [
        "match", "day-shift", "edge-reversal", "refund-attribution", "prior-period-return", "discount-basis", "gross-delta",
        "shipping-tax-delta", "sm-invalid", "sm-channel", "channel-basis", "sm-invalid-unmatched", "sm-channel-unmatched",
        "missing-in-sm", "unexplained-sm-only", "refund-missing-in-sm", "refund-missing-in-shopify", "unexplained-delta",
        "undated",
    ]
    for cls in order_of_classes + sorted(set(attributions) - set(order_of_classes)):
        if cls in attributions:
            a = attributions[cls]
            sample = ", ".join(k.split(":", 1)[1] for k in a.keys[:5])
            more = f" (+{len(a.keys) - 5} more)" if len(a.keys) > 5 else ""
            p(f"| `{cls}` | {a.orders} | {money_str(a.net_effect)} | {sample}{more} |")
    p("")
    p("Classes `" + "`, `".join(c for c in order_of_classes if c in RESIDUAL_CLASSES) + "` are the residual. "
      "`sm-invalid-unmatched` and `sm-channel-unmatched` are SM rows Shopify did not export and SM does not count; zero effect, listed for completeness. "
      "An order can carry more than one class (a sale and a refund on either side of the window edge).")

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

    delta_rows = [r for r in matched_rows if r["class"] not in {"match", "outside-window"} or r["other_classes"]]
    if delta_rows:
        p("")
        p("## Matched orders with differences (first 25)")
        p("")
        p("| Order | Class | Shopify day | SM day | SM valid | SM channel | Shopify net | SM net | Effect |")
        p("|---|---|---|---|---|---|---:|---:|---:|")
        for r in delta_rows[:25]:
            label = f"`{r['class']}`" + (f" + {r['other_classes']}" if r["other_classes"] else "")
            p(f"| {r['order_name'] or r['key']} | {label} | {r['shopify_day']} | {r['sm_day']} | {r['sm_valid']} | {r['sm_channel']} | {r['shopify_net']} | {r['sm_net']} | {r['net_effect']} |")
    if shopify_only_rows:
        p("")
        p("## Shopify orders with no SourceMedium row (first 25)")
        p("")
        p("| Order | Class | Shopify day | Financial status | Source | Shopify net |")
        p("|---|---|---|---|---|---:|")
        for r in shopify_only_rows[:25]:
            p(f"| {r['order_name'] or r['key']} | `{r['class']}` | {r['shopify_day']} | {r['financial_status']} | {r['source']} | {r['shopify_net']} |")
    if sm_only_rows:
        p("")
        p("## SourceMedium rows Shopify did not export (first 25)")
        p("")
        p("| Order | Class | SM day | SM valid | SM channel | Cancelled at | SM net |")
        p("|---|---|---|---|---|---|---:|")
        for r in sm_only_rows[:25]:
            p(f"| {r['order_name'] or r['key']} | `{r['class']}` | {r['sm_day']} | {r['sm_valid']} | {r['sm_channel']} | {r['sm_cancelled_at']} | {r['sm_net']} |")
    if undated_rows:
        p("")
        p("## Undated rows (first 25)")
        p("")
        p("| Order | Side | Undated net |")
        p("|---|---|---:|")
        for r in undated_rows[:25]:
            p(f"| {r['order_name'] or r['key']} | {r['side']} | {r['net']} |")

    p("")
    p("## Next rung")
    p("")
    hints = []
    if quote_lines and not quotes_ok:
        hints.append("A quoted figure is not reproduced by the inputs: fix the window, store, or report filter (or name the metric) before reading the attribution as the answer to the claim.")
    if "day-shift" in attributions:
        hints.append("`day-shift` present: run the store timezone offset check; retry with `--shopify-utc-offset` to test it.")
    if "edge-reversal" in attributions:
        hints.append("`edge-reversal` present: refunds, cancellations, or edits Shopify booked on the other side of the window edge from the sale. Shopify counts them on their own day; SM restates the order. Definition, not defect.")
    if "sm-invalid" in attributions:
        hints.append("`sm-invalid` present: Shopify counts the order (a cancelled order keeps its gross sale and books an equal sales_reversals, so its net is 0 but orders = 1); `is_order_sm_valid` excludes it. Definition, not defect.")
    if "refund-attribution" in attributions:
        hints.append("`refund-attribution` present: SM carries a refund Shopify books after the export's last day. Expected at by-day grain.")
    if "prior-period-return" in attributions:
        hints.append("`prior-period-return` present: refunds of orders sold before the export, booked by Shopify on the refund day (orders = 0). SM carries them on the original order. Definition, not defect.")
    if "refund-missing-in-sm" in attributions:
        refund_hint = "`refund-missing-in-sm` present: Shopify booked a refund inside the export that SM does not carry. Check freshness (table_last_data_date) before escalating with the order ids."
        if fmt == "orders_export":
            refund_hint += " The Orders export's Refunded Amount also includes shipping and tax refunds; get the Analytics export before escalating."
        hints.append(refund_hint)
    if "refund-missing-in-shopify" in attributions:
        hints.append("`refund-missing-in-shopify` present: SM dates a refund inside the export (latest_order_refund_date) that the export does not show. Check for a custom refund, which Analytics does not book as a reversal, before escalating.")
    if "missing-in-sm" in attributions:
        hints.append("`missing-in-sm` present: compare these orders' times with obt_orders table_last_data_date (freshness) and confirm the store mapping before escalating.")
    if "unexplained-sm-only" in attributions:
        hints.append("`unexplained-sm-only` present: SM has valid in-scope orders Shopify did not export; check the Shopify export filters and the store handle.")
    if "unexplained-delta" in attributions:
        hints.append("`unexplained-delta` present: open these orders in Shopify admin and compare the timeline (edits, partial refunds) with the SM row.")
    if "undated" in attributions:
        hints.append("`undated` present: rows with no day cannot be placed in the window. Re-export with a day on every row and rerun.")
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
        write_rows(out_dir / "undated.csv", undated_rows)
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


def iso_date(text: str) -> date:
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {text!r}: use YYYY-MM-DD") from exc


def money_arg(text: str) -> Decimal:
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"invalid amount {text!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shopify", required=True, help="Shopify export CSV (ShopifyQL sales by order, or Orders page export).")
    parser.add_argument("--sm", required=True, help="SourceMedium obt_orders extract CSV (canonical query).")
    parser.add_argument("--window", nargs=2, type=iso_date, metavar=("START", "END"), help="Claimed window, YYYY-MM-DD inclusive. Rows outside it are matched but not totaled.")
    parser.add_argument("--basis", choices=["all", "exclude-pos"], default="all", help="Default all: every order on both sides, POS included. Use exclude-pos only to reproduce a figure quoted from a POS-excluded report.")
    parser.add_argument("--sm-day", choices=["local", "utc"], default="local", help="Which SM timestamp buckets the SM day. Default local.")
    parser.add_argument("--shopify-utc-offset", type=float, default=None, help="Re-bucket SM days from order_processed_at (UTC) into this offset, e.g. -7 for Pacific daylight time.")
    parser.add_argument("--tolerance-order", type=float, default=0.01, help="Per-order amount tolerance. Default 0.01.")
    parser.add_argument("--tolerance-total", type=float, default=1.00, help="Headline net delta tolerance for a reconciled verdict. Default 1.00.")
    parser.add_argument("--shopify-map", action="append", default=[], metavar="HEADER=FIELD", help="Map a Shopify header to a logical field (gross, discounts, returns, net, shipping, taxes, total, order_id, order_name, day, source, financial_status).")
    parser.add_argument("--quoted-shopify-net", type=money_arg, metavar="AMOUNT", help="The Shopify net sales figure the operator quoted; the report shows its gap to the export rows in the window.")
    parser.add_argument("--quoted-sm-net", type=money_arg, metavar="AMOUNT", help="The SourceMedium net revenue figure the operator quoted; the report shows its gap to the extract.")
    parser.add_argument("--out-dir", help="Write matched_deltas.csv, shopify_only.csv, sm_only.csv, undated.csv, attribution.csv here.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.window and args.window[1] < args.window[0]:
        parser.error("--window END precedes START")
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
