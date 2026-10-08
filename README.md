# Credit Exposure Prioritizer

A small Streamlit dashboard to help finance and credit-control staff review customer credit exposure and
see how a proposed order would change it. It is an operational review aid, not a
credit approval, bankruptcy prediction, lending recommendation, or Valuatum
credit-risk model.

[Try the live demo](https://credit-exposure-prioritizer.streamlit.app/)

The demo opens with fictional sample data.

## Run

Python 3.10 is supported. Install the dependencies in `requirements.txt`, then:

```text
python -m streamlit run app.py
```

Run the logic tests with:

```text
python -m pytest
```

## CSV input

Use UTF-8 (with or without BOM), comma-separated data and one row per customer.
Required columns are `customer_name`, `outstanding_eur`, `credit_limit_eur`,
`overdue_eur`, and `max_days_overdue`. Optional `business_id` is treated as text,
including leading zeros. Extra columns are ignored. Monetary values must be
plain decimal-point numbers without currency symbols or thousands separators.
Only the credit limit may be blank; a blank or zero limit means unavailable.

The whole upload is rejected if any row is invalid. Names must be nonblank and
unique ignoring case and surrounding whitespace; nonblank business IDs must be
unique after trimming. Monetary values cannot be negative or nonfinite, overdue
cannot exceed outstanding, and overdue days must be a nonnegative whole number.
Days must be zero when nothing is overdue and at least one when overdue is
positive. Uploaded data is processed in memory and is not saved to disk.

## Illustrative review rules

Priority 1 — Review now: outstanding is strictly above a positive limit, or a
positive overdue balance has an oldest invoice at least 30 days overdue.
Priority 2 — Review soon: absent Priority 1, a positive overdue balance exists,
utilization is at least 80%, or the limit is unavailable. Priority 3 — Routine
monitoring: no overdue balance, a usable limit, and utilization below 80%.
Exactly 100% is not above the limit; any value above 100% is. Reasons and
suggested actions are tied to applicable conditions.

Ranking is deterministic: priority, over-limit amount, overdue amount, overdue
days, outstanding balance, then case-insensitive customer name. No weighted
risk score is calculated. An unavailable limit has no utilization or over-limit
amount and uses zero only for ranking.

The simulator assumes the additional order adds exposure immediately; overdue
amount and days stay unchanged. It does not change portfolio metrics or the
source data. Limits are user-supplied internal or indicative values and must be
confirmed. All thresholds are illustrative prototype assumptions, not official
Valuatum criteria or lending recommendations. For general company-credit
information, see [luottoriskit.fi](https://www.luottoriskit.fi/).
