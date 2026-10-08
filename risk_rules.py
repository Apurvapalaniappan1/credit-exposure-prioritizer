"""Validation and illustrative account-review rules for the MVP."""

from __future__ import annotations

from io import StringIO
import math
from typing import Any, Mapping

import pandas as pd


REQUIRED_COLUMNS = (
    "customer_name",
    "outstanding_eur",
    "credit_limit_eur",
    "overdue_eur",
    "max_days_overdue",
)
NUMERIC_COLUMNS = (
    "outstanding_eur",
    "credit_limit_eur",
    "overdue_eur",
    "max_days_overdue",
)
CATEGORY_NAMES = {
    1: "Review now",
    2: "Review soon",
    3: "Routine monitoring",
}


class CustomerDataError(ValueError):
    """Raised when the complete customer portfolio is invalid."""


def read_customers_csv(content: str | bytes) -> pd.DataFrame:
    """Read a UTF-8 CSV while preserving optional business IDs as text."""
    try:
        if isinstance(content, bytes):
            content = content.decode("utf-8-sig")
        else:
            content = content.lstrip("\ufeff")
        customers = pd.read_csv(
            StringIO(content),
            dtype={"business_id": "string"},
        )
    except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise CustomerDataError(f"Could not read the CSV: {exc}") from exc
    return validate_customers(customers)


def validate_customers(customers: pd.DataFrame) -> pd.DataFrame:
    """Validate a whole portfolio and return a coerced, independent copy."""
    if customers.empty:
        raise CustomerDataError("The portfolio must contain at least one customer row.")

    missing = [column for column in REQUIRED_COLUMNS if column not in customers.columns]
    if missing:
        raise CustomerDataError(
            "Missing required column(s): " + ", ".join(missing)
        )

    result = customers.copy(deep=True)
    errors: list[str] = []
    normalized_names: dict[str, int] = {}
    normalized_ids: dict[str, int] = {}

    for position, (_, row) in enumerate(result.iterrows(), start=2):
        name_value = row["customer_name"]
        if pd.isna(name_value) or not str(name_value).strip():
            errors.append(f"Row {position}, field 'customer_name': name must not be blank.")
        else:
            normalized_name = str(name_value).strip().casefold()
            if normalized_name in normalized_names:
                errors.append(
                    f"Row {position}, field 'customer_name': duplicate customer name "
                    f"(also on row {normalized_names[normalized_name]})."
                )
            else:
                normalized_names[normalized_name] = position

        for column in NUMERIC_COLUMNS:
            value = row[column]
            blank = pd.isna(value) or (
                isinstance(value, str) and not value.strip()
            )
            if column == "credit_limit_eur" and blank:
                result.at[result.index[position - 2], column] = float("nan")
                continue
            if blank:
                errors.append(
                    f"Row {position}, field '{column}': a finite number is required."
                )
                continue
            if isinstance(value, bool):
                errors.append(
                    f"Row {position}, field '{column}': a finite number is required."
                )
                continue
            try:
                number = float(value)
            except (TypeError, ValueError, OverflowError):
                errors.append(
                    f"Row {position}, field '{column}': a finite number is required."
                )
                continue
            if not math.isfinite(number):
                errors.append(
                    f"Row {position}, field '{column}': value must be finite."
                )
                continue
            result.at[result.index[position - 2], column] = number
            if number < 0:
                errors.append(
                    f"Row {position}, field '{column}': value must not be negative."
                )
            if column == "max_days_overdue" and not number.is_integer():
                errors.append(
                    f"Row {position}, field 'max_days_overdue': value must be a whole number."
                )

        if "business_id" in result.columns:
            business_id = row["business_id"]
            if not pd.isna(business_id) and str(business_id).strip():
                normalized_id = str(business_id).strip()
                if normalized_id in normalized_ids:
                    errors.append(
                        f"Row {position}, field 'business_id': duplicate business ID "
                        f"(also on row {normalized_ids[normalized_id]})."
                    )
                else:
                    normalized_ids[normalized_id] = position

    if not errors:
        for position, (_, row) in enumerate(result.iterrows(), start=2):
            outstanding = float(row["outstanding_eur"])
            overdue = float(row["overdue_eur"])
            days = float(row["max_days_overdue"])
            if overdue > outstanding:
                errors.append(
                    f"Row {position}, field 'overdue_eur': overdue amount must not "
                    "exceed outstanding balance."
                )
            if overdue == 0 and days != 0:
                errors.append(
                    f"Row {position}, field 'max_days_overdue': must be 0 when "
                    "overdue_eur is 0."
                )
            if overdue > 0 and days < 1:
                errors.append(
                    f"Row {position}, field 'max_days_overdue': must be at least 1 "
                    "when overdue_eur is positive."
                )

    if errors:
        raise CustomerDataError("\n".join(errors))

    result["max_days_overdue"] = result["max_days_overdue"].astype("int64")
    return result


def _derive_account(customer: Mapping[str, Any]) -> dict[str, Any]:
    outstanding = float(customer["outstanding_eur"])
    limit_value = customer["credit_limit_eur"]
    limit_available = not pd.isna(limit_value) and float(limit_value) > 0
    limit = float(limit_value) if limit_available else None
    overdue = float(customer["overdue_eur"])
    days = int(customer["max_days_overdue"])

    utilization = outstanding / limit * 100 if limit is not None else None
    over_limit = max(outstanding - limit, 0.0) if limit is not None else None
    reasons: list[str] = []
    if limit is None:
        reasons.append("Credit limit unavailable; confirm a usable limit.")
    elif over_limit > 0:
        reasons.append(
            f"Outstanding balance exceeds the limit by €{over_limit:,.2f} "
            f"({utilization:.2f}% utilization)."
        )
    if overdue > 0:
        if days >= 30:
            reasons.append(
                f"€{overdue:,.2f} is overdue; the oldest overdue invoice is "
                f"{days} days old (30-day review threshold reached)."
            )
        else:
            reasons.append(
                f"€{overdue:,.2f} is overdue; the oldest overdue invoice is "
                f"{days} days old."
            )
    if utilization is not None and utilization >= 80:
        reasons.append(f"Utilization is {utilization:.2f}% (80% review threshold reached).")

    if (over_limit is not None and over_limit > 0) or (overdue > 0 and days >= 30):
        priority = 1
    elif overdue > 0 or utilization is None or utilization >= 80:
        priority = 2
    else:
        priority = 3
        reasons.append("No current review trigger; continue routine monitoring.")

    actions: list[str] = []
    if over_limit is not None and over_limit > 0:
        actions.append("Review the limit and additional credit exposure.")
    if overdue > 0:
        actions.append("Follow up on the unpaid invoices.")
    if (
        utilization is not None
        and utilization >= 80
        and (over_limit is None or over_limit == 0)
    ):
        actions.append("Review available headroom before another credit order.")
    if limit is None:
        actions.append("Obtain or confirm a usable credit limit.")
    if priority == 3:
        actions.append("Continue routine monitoring.")

    return {
        "priority": priority,
        "category": CATEGORY_NAMES[priority],
        "utilization_pct": utilization,
        "over_limit_eur": over_limit,
        "review_reasons": reasons,
        "follow_up_suggestions": actions,
    }


def prioritize_customers(customers: pd.DataFrame) -> pd.DataFrame:
    """Validate, classify, explain, and deterministically rank a portfolio."""
    result = validate_customers(customers)
    derived = pd.DataFrame(
        [_derive_account(row) for row in result.to_dict(orient="records")],
        index=result.index,
    )
    result = pd.concat([result, derived], axis=1)
    result["_over_limit_sort"] = result["over_limit_eur"].map(
        lambda value: 0.0 if pd.isna(value) else float(value)
    )
    result["_customer_name_sort"] = result["customer_name"].map(
        lambda name: str(name).casefold()
    )
    result = result.sort_values(
        [
            "priority",
            "_over_limit_sort",
            "overdue_eur",
            "max_days_overdue",
            "outstanding_eur",
            "_customer_name_sort",
        ],
        ascending=[True, False, False, False, False, True],
        kind="mergesort",
    )
    return result.drop(columns=["_over_limit_sort", "_customer_name_sort"]).reset_index(
        drop=True
    )


def project_order(
    customer: Mapping[str, Any], proposed_order_eur: float
) -> dict[str, Any]:
    """Return current and projected account details without mutating the input."""
    if isinstance(proposed_order_eur, bool):
        raise ValueError("Proposed order must be a finite, nonnegative amount.")
    try:
        order = float(proposed_order_eur)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            "Proposed order must be a finite, nonnegative amount."
        ) from exc
    if not math.isfinite(order) or order < 0:
        raise ValueError("Proposed order must be a finite, nonnegative amount.")

    validated = validate_customers(pd.DataFrame([dict(customer)])).iloc[0].to_dict()
    current = _derive_account(validated)
    projected_customer = dict(validated)
    projected_customer["outstanding_eur"] += order
    projected = _derive_account(projected_customer)
    return {
        "proposed_order_eur": order,
        "current": {**validated, **current},
        "projected": {**projected_customer, **projected},
    }
