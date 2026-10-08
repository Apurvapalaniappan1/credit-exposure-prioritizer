import math
from pathlib import Path

import pandas as pd
import pytest

from risk_rules import (
    CATEGORY_NAMES,
    CustomerDataError,
    prioritize_customers,
    project_order,
    read_customers_csv,
    validate_customers,
)


def portfolio_row(
    name="Account",
    outstanding=5000,
    limit=10000,
    overdue=0,
    days=0,
    business_id=None,
):
    return {
        "customer_name": name,
        "business_id": business_id,
        "outstanding_eur": outstanding,
        "credit_limit_eur": limit,
        "overdue_eur": overdue,
        "max_days_overdue": days,
    }


def test_sample_categories_and_boundary_values():
    sample = read_customers_csv(Path("sample_customers.csv").read_bytes())
    ranked = prioritize_customers(sample).set_index("customer_name")
    assert sample["outstanding_eur"].sum() == 67999
    assert sample["overdue_eur"].sum() == 3500
    assert (ranked["priority"] == 1).sum() == 3
    assert (sample["credit_limit_eur"].isna() | (sample["credit_limit_eur"] == 0)).sum() == 2
    redwood = ranked.loc["Redwood Safety Group"]
    assert redwood["category"] == CATEGORY_NAMES[1]
    assert redwood["credit_limit_eur"] == 0
    assert pd.isna(redwood["utilization_pct"])
    assert pd.isna(redwood["over_limit_eur"])
    assert any("30 days" in reason for reason in redwood["review_reasons"])
    assert ranked["category"].to_dict() == {
        "Northstar Components": CATEGORY_NAMES[1],
        "Juniper Office Supply": CATEGORY_NAMES[1],
        "Harborlight Foods": CATEGORY_NAMES[2],
        "Maple Bridge Design": CATEGORY_NAMES[2],
        "Pinecrest Tools": CATEGORY_NAMES[3],
        "Bluewater Studio": CATEGORY_NAMES[2],
        "Silver Fern Logistics": CATEGORY_NAMES[2],
        "Redwood Safety Group": CATEGORY_NAMES[1],
        "Willowbrook Textiles": CATEGORY_NAMES[2],
    }

    boundaries = pd.DataFrame(
        [
            portfolio_row("At 80", outstanding=8000),
            portfolio_row("At 100", outstanding=10000),
            portfolio_row("Above 100", outstanding=10000.01),
            portfolio_row("At 30 days", overdue=1, days=30),
        ]
    )
    categories = prioritize_customers(boundaries).set_index("customer_name")["category"]
    assert categories["At 80"] == CATEGORY_NAMES[2]
    assert categories["At 100"] == CATEGORY_NAMES[2]
    assert categories["Above 100"] == CATEGORY_NAMES[1]
    assert categories["At 30 days"] == CATEGORY_NAMES[1]


@pytest.mark.parametrize("limit", [None, 0])
def test_unavailable_limits_do_not_invent_utilization_or_exceedance(limit):
    ranked = prioritize_customers(
        pd.DataFrame([portfolio_row(limit=limit)])
    ).iloc[0]
    assert ranked["category"] == CATEGORY_NAMES[2]
    assert ranked["utilization_pct"] is None
    assert ranked["over_limit_eur"] is None
    assert any("limit unavailable" in reason.lower() for reason in ranked["review_reasons"])


def test_multiple_simultaneous_reasons_and_matched_actions():
    account = prioritize_customers(
        pd.DataFrame([portfolio_row(outstanding=12000, overdue=1000, days=30)])
    ).iloc[0]
    assert account["priority"] == 1
    assert len(account["review_reasons"]) == 3
    assert len(account["follow_up_suggestions"]) == 2
    assert any("€2,000.00" in reason for reason in account["review_reasons"])
    assert any("30 days" in reason for reason in account["review_reasons"])


def test_unavailable_limit_reason_remains_visible_in_priority_one():
    account = prioritize_customers(
        pd.DataFrame([portfolio_row(limit=None, overdue=1, days=30)])
    ).iloc[0]
    assert account["priority"] == 1
    assert any("limit unavailable" in reason.lower() for reason in account["review_reasons"])


def test_deterministic_sorting_and_ties():
    customers = pd.DataFrame(
        [
            portfolio_row("same", 12000, 10000, 100, 5),
            portfolio_row("Beta", 11000, 10000, 100, 5),
            portfolio_row("alpha", 11000, 10000, 100, 5),
            portfolio_row("Zero", 12000, 0, 0, 0),
            portfolio_row("Other", 12000, None, 0, 0),
        ]
    )
    first = prioritize_customers(customers)["customer_name"].tolist()
    second = prioritize_customers(customers.sample(frac=1, random_state=42))[
        "customer_name"
    ].tolist()
    assert first == second
    assert first[:3] == ["same", "alpha", "Beta"]
    assert first[-2:] == ["Other", "Zero"]


@pytest.mark.parametrize(
    "rows, expected",
    [
        ([], "at least one customer"),
        ([{"customer_name": "Only"}], "Missing required column"),
        ([portfolio_row(name="  ")], "customer_name"),
        ([portfolio_row(outstanding="bad")], "outstanding_eur"),
        ([portfolio_row(outstanding=float("inf"))], "outstanding_eur"),
        ([portfolio_row(outstanding=-1)], "outstanding_eur"),
        ([portfolio_row(limit=-1)], "credit_limit_eur"),
        ([portfolio_row(overdue=-1)], "overdue_eur"),
        ([portfolio_row(days=-1, overdue=1)], "max_days_overdue"),
        ([portfolio_row(days=1.5)], "max_days_overdue"),
        ([portfolio_row(overdue=2, outstanding=1, days=1)], "overdue_eur"),
        ([portfolio_row(days=1)], "max_days_overdue"),
        ([portfolio_row(overdue=1, days=0)], "max_days_overdue"),
        (
            [portfolio_row(" Acme "), portfolio_row("acme")],
            "duplicate customer name",
        ),
        (
            [portfolio_row(business_id=" 001 "), portfolio_row(business_id="001")],
            "duplicate business ID",
        ),
    ],
)
def test_invalid_portfolios_are_rejected_with_field_context(rows, expected):
    frame = pd.DataFrame(rows)
    if not rows:
        frame = pd.DataFrame(columns=["customer_name"])
    with pytest.raises(CustomerDataError, match=expected):
        validate_customers(frame)


def test_csv_preserves_business_id_leading_zeroes_and_utf8_bom():
    csv_bytes = (
        "\ufeffcustomer_name,business_id,outstanding_eur,credit_limit_eur,"
        "overdue_eur,max_days_overdue,extra\n"
        "Ångström AB,000123,100,200,0,0,ignored\n"
    ).encode("utf-8")
    customers = read_customers_csv(csv_bytes)
    assert customers.loc[0, "business_id"] == "000123"
    assert "extra" in customers.columns


def test_example_i_plus_2000_projects_to_11000_and_review_now():
    account = portfolio_row(
        "Willowbrook Textiles", 9000, 10000, 0, 0
    )
    result = project_order(account, 2000)
    assert result["projected"]["outstanding_eur"] == 11000
    assert result["projected"]["category"] == CATEGORY_NAMES[1]


def test_zero_order_leaves_classification_unchanged_and_source_is_unmodified():
    account = portfolio_row("At limit", 10000, 10000, 0, 0)
    original = dict(account)
    result = project_order(account, 0)
    assert result["current"]["category"] == result["projected"]["category"]
    assert result["projected"]["outstanding_eur"] == 10000
    assert account == original


@pytest.mark.parametrize("order", [-0.01, math.inf, -math.inf, math.nan, "not a number"])
def test_invalid_proposed_orders_are_rejected(order):
    with pytest.raises(ValueError, match="finite, nonnegative"):
        project_order(portfolio_row(), order)


def test_validation_does_not_mutate_input_data():
    customers = pd.DataFrame([portfolio_row()])
    original = customers.copy(deep=True)
    validate_customers(customers)
    pd.testing.assert_frame_equal(customers, original)
