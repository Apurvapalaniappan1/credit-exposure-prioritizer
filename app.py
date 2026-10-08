"""Streamlit interface for the Credit Exposure Prioritizer MVP."""

from pathlib import Path

import pandas as pd
import streamlit as st

from risk_rules import (
    CATEGORY_NAMES,
    CustomerDataError,
    prioritize_customers,
    project_order,
    read_customers_csv,
)


st.set_page_config(
    page_title="Credit Exposure Prioritizer",
    page_icon="",
    layout="wide",
)

SAMPLE_PATH = Path(__file__).with_name("sample_customers.csv")
PRIORITY_LABELS = {
    1: "🔴 Priority 1 — Review now",
    2: "🟠 Priority 2 — Review soon",
    3: "🟢 Priority 3 — Routine monitoring",
}


def format_eur(value: float | None) -> str:
    return "Limit unavailable" if value is None or pd.isna(value) else f"€{value:,.2f}"


def format_percent(value: float | None) -> str:
    return "Limit unavailable" if value is None or pd.isna(value) else f"{value:.2f}%"


def render_account_details(account: pd.Series | dict) -> None:
    details = dict(account)
    st.markdown(f"**{PRIORITY_LABELS[details['priority']]}**")
    st.markdown("**Why this account is in this category**")
    for reason in details["review_reasons"]:
        st.write(f"- {reason}")
    st.markdown("**Suggested follow-up**")
    for action in details["follow_up_suggestions"]:
        st.write(f"- {action}")


st.title("Credit Exposure Prioritizer")
st.caption(
    "A practical review queue for customer credit exposure — not a credit decision "
    "or a prediction of financial failure."
)

source = st.radio(
    "Choose portfolio data",
    ("Fictional sample", "Upload CSV"),
    horizontal=True,
)

try:
    if source == "Fictional sample":
        portfolio = read_customers_csv(SAMPLE_PATH.read_bytes())
        st.info(
            "Fictional demonstration data only. Credit limits are illustrative, "
            "user-supplied values."
        )
    else:
        uploaded_file = st.file_uploader(
            "Upload a UTF-8 comma-separated CSV",
            type=["csv"],
            help="One row per customer. Uploaded data is processed in memory and is not saved.",
        )
        st.download_button(
            "Download sample CSV",
            data=SAMPLE_PATH.read_bytes(),
            file_name="sample_customers.csv",
            mime="text/csv",
        )
        if uploaded_file is None:
            st.info("Upload a CSV to review your portfolio. No sample data is shown.")
            st.stop()
        portfolio = read_customers_csv(uploaded_file.getvalue())
except CustomerDataError as exc:
    st.error(f"Portfolio validation failed. No rows were loaded.\n\n{exc}")
    st.stop()

ranked = prioritize_customers(portfolio)
st.subheader("Portfolio overview")
metric_columns = st.columns(4)
metric_columns[0].metric(
    "Total outstanding", format_eur(float(portfolio["outstanding_eur"].sum()))
)
metric_columns[1].metric(
    "Total overdue", format_eur(float(portfolio["overdue_eur"].sum()))
)
metric_columns[2].metric(
    "Review now accounts", int((ranked["priority"] == 1).sum())
)
metric_columns[3].metric(
    "Accounts without usable limits",
    int(ranked["credit_limit_eur"].isna().sum() + (ranked["credit_limit_eur"] == 0).sum()),
)

st.subheader("Ranked review queue")
display = ranked[
    [
        "customer_name",
        "priority",
        "outstanding_eur",
        "credit_limit_eur",
        "utilization_pct",
        "over_limit_eur",
        "overdue_eur",
        "max_days_overdue",
        "review_reasons",
    ]
].copy()
display["priority"] = display["priority"].map(PRIORITY_LABELS)
display["outstanding_eur"] = display["outstanding_eur"].map(format_eur)
display["credit_limit_eur"] = display["credit_limit_eur"].map(
    lambda value: "Limit unavailable"
    if pd.isna(value) or value == 0
    else format_eur(float(value))
)
display["utilization_pct"] = display["utilization_pct"].map(format_percent)
display["over_limit_eur"] = display["over_limit_eur"].map(format_eur)
display["overdue_eur"] = display["overdue_eur"].map(format_eur)
display["review_reasons"] = display["review_reasons"].map(
    lambda reasons: " ".join(reasons)
)
display = display.rename(
    columns={
        "customer_name": "Customer",
        "priority": "Review priority",
        "outstanding_eur": "Outstanding",
        "credit_limit_eur": "Credit limit",
        "utilization_pct": "Utilization",
        "over_limit_eur": "Over-limit amount",
        "overdue_eur": "Overdue",
        "max_days_overdue": "Oldest overdue (days)",
        "review_reasons": "Review reasons",
    }
)
st.dataframe(display, hide_index=True, width="stretch")

customer_names = ranked["customer_name"].tolist()
st.subheader("Account details")
selected_name = st.selectbox("Select a customer", customer_names, key="selected_customer")
selected = ranked.loc[ranked["customer_name"] == selected_name].iloc[0]
render_account_details(selected)

st.subheader("What-if: additional order")
st.caption(
    "The proposed order is assumed to add credit exposure immediately. Existing "
    "overdue amounts and invoice ages remain unchanged."
)
if "proposed_order_eur" not in st.session_state:
    st.session_state["proposed_order_eur"] = 0.0
if st.button("Reset proposed order"):
    st.session_state["proposed_order_eur"] = 0.0
proposed_order = st.number_input(
    "Proposed additional order (EUR)",
    min_value=0.0,
    step=1000.0,
    key="proposed_order_eur",
)

try:
    scenario = project_order(selected.to_dict(), proposed_order)
except ValueError as exc:
    st.error(str(exc))
else:
    current = scenario["current"]
    projected = scenario["projected"]
    current_column, projected_column = st.columns(2)
    for column, heading, account in (
        (current_column, "Current", current),
        (projected_column, "After proposed order", projected),
    ):
        with column:
            st.markdown(f"**{heading} — {CATEGORY_NAMES[account['priority']]}**")
            st.write(f"Outstanding: {format_eur(account['outstanding_eur'])}")
            limit_text = (
                "Limit unavailable"
                if account["credit_limit_eur"] is None
                or pd.isna(account["credit_limit_eur"])
                or account["credit_limit_eur"] == 0
                else format_eur(float(account["credit_limit_eur"]))
            )
            st.write(f"Credit limit: {limit_text}")
            st.write(f"Utilization: {format_percent(account['utilization_pct'])}")
            st.write(f"Over-limit amount: {format_eur(account['over_limit_eur'])}")
            st.write(f"Overdue: {format_eur(account['overdue_eur'])}")
            st.write(f"Oldest overdue: {account['max_days_overdue']} days")
            st.markdown("**Review reasons**")
            for reason in account["review_reasons"]:
                st.write(f"- {reason}")

st.divider()
st.subheader("Rules and limitations")
st.markdown(
    """
These **illustrative prototype assumptions** prioritize operational review; they
are not official Valuatum criteria, lending recommendations, a bankruptcy
prediction, or a credit approval. Priority 1 applies when exposure is strictly
above a usable limit or a positive overdue balance is at least 30 days old.
Priority 2 applies otherwise when any balance is overdue, utilization is at
least 80%, or a usable limit is unavailable. Remaining accounts are Priority 3.
Exactly 100% utilization is not over limit. Accounts are ranked by priority,
over-limit amount, overdue amount, overdue days, outstanding balance, then
customer name; no weighted risk score is used. Limits are user-supplied and
should be confirmed. The simulator changes projected exposure only and does
not alter the portfolio metrics.
"""
)
st.markdown(
    "For further company-credit information, visit [luottoriskit.fi](https://www.luottoriskit.fi/)."
)
