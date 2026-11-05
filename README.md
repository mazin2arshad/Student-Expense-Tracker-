# ExpenseTracker

A Python core for student expense tracking, with no external dependencies. Import
`ExpenseTracker` from `ExpenseTracker.py`. Requires Python 3.9 or newer.

Run the demonstration or tests from this directory:

```powershell
python ExpenseTracker.py
python -m unittest -v
```

If Python is not on PATH, use the full path to your interpreter. For this machine:

```powershell
& "$env:LOCALAPPDATA\Python\pythoncore-3.15-64\python.exe" -m unittest -v
```

The demonstration uses temporary in-memory example data and prints a summary.
Save your own tracker explicitly with `save_to_file()`.

## Quick start

```python
from ExpenseTracker import ExpenseTracker

tracker = ExpenseTracker()
tracker.currency = "£"
tracker.add_income(1200, "Student finance", date="2026-11-01")
tracker.set_budget(800, "monthly", {"Food": 200, "Transport": 80})
tracker.set_budget(150, "weekly", {"Food": 60})

# Omit category to use the keyword-based suggestion.
tracker.add_expense(35.50, "Tesco groceries", date="2026-11-05")
tracker.add_expense(12, "Bus pass", "Transport", "2026-11-05")
tracker.categorise_expense(0, "Food")

print(tracker.get_remaining_budget("monthly", on_date="2026-11-05"))
print(tracker.get_spending_by_category("month", on_date="2026-11-05"))
print(tracker.check_budget_alerts(on_date="2026-11-05"))
print(tracker.calculate_daily_allowance(on_date="2026-11-05"))

tracker.save_to_file("tracker.json")
restored = ExpenseTracker()
restored.load_from_file("tracker.json")
```

## Essential features

| Method | Usage and result |
| --- | --- |
| `categorise_expense(index, category)` | Assign Food, Transport, Rent, Entertainment, Shopping, Education or Other. Names are case insensitive. |
| `get_expenses_by_date(period, on_date=None, start_date=None, end_date=None)` | Return transactions for a day, week, month or custom range. The requested spelling `get_epenses_by_date` is also available. |
| `set_budget(amount, period="monthly", category_limits=None)` | Set a weekly/monthly total with optional category caps. Returns the saved budget as a copy. |
| `get_remaining_budget(period="monthly", on_date=None, category=None)` | Return the budget minus recorded spending for that period. Negative means overspent. Missing budgets or category caps raise `ValueError`. |
| `add_income(amount, source, date=None, description=None)` | Record a named income source and return its ID. `get_total_income()` optionally filters by period/range. |
| `get_spending_by_category(period=None, ...)` | Return a dictionary containing all seven category totals, suitable for charts. Defaults to all time. |
| `search_expenses(description=None, category=None, min_amount=None, max_amount=None, start_date=None, end_date=None, amount=None)` | Combine description substring, category, exact/ranged amount and date filters. All supplied conditions must match. |

```python
november = tracker.get_expenses_by_date("month", on_date="2026-11-05")
week = tracker.get_expenses_by_date("week", on_date="2026-11-05")
custom = tracker.get_expenses_by_date(
    "custom", start_date="2026-11-01", end_date="2026-11-15"
)
matches = tracker.search_expenses(
    description="tesco", category="Food", min_amount=10, max_amount=50,
    start_date="2026-11-01", end_date="2026-11-30"
)
```

Dates default to the machine's local date and are stored as `YYYY-MM-DD`. Inputs
also accept Python `date` and `datetime` objects. Date ranges include both ends;
weeks run Monday–Sunday and months follow the calendar. Day/daily, week/weekly
and month/monthly are accepted. Pass both bounds for custom ranges.

Budgets repeat each calendar period without rollover. Setting a budget replaces
that period's configuration; budget versions are not stored. Category caps may
sum to less than the overall limit, but cannot exceed it. A zero category cap
is allowed. Budget reports include all recorded transactions in the chosen
period, including future-dated ones; unposted recurring bills are excluded.

## Student features

`calculate_daily_allowance(available_funds=None, end_date=None, on_date=None,
period="monthly")` divides funds by the remaining days, including the selected
day, and rounds down. By default, funds are income less spending, savings
contributions, and unrepaid cash advanced for friends, through `on_date`. Your
own unpaid share of a bill is reserved as personal spending. A configured budget
caps the allowance. Without income or explicit funds, the result is zero. Past
end dates and exhausted funds return zero. Future income and unposted bills are
excluded; supply net `available_funds` to reserve upcoming bills. The default end
date is the end of the selected calendar budget period. Explicit funds replace
the ledger calculation but are still capped by that period's budget.

```python
print(tracker.calculate_daily_allowance(
    available_funds=200, end_date="2026-11-30", on_date="2026-11-05"
))

rent = tracker.add_recurring_expense(
    500, "Rent", frequency="monthly", start_date="2026-11-01",
    category="Rent", end_date="2027-06-30"
)
posted = tracker.process_recurring_expenses(until_date="2026-11-05")
tracker.cancel_recurring_expense(rent)

goal = tracker.create_savings_goal("Emergency fund", 500, target_date="2027-06-30")
tracker.contribute_to_savings(goal, 50, date="2026-11-05")
print(tracker.get_savings_progress(goal))

alerts = tracker.check_budget_alerts("monthly", "2026-11-05", threshold=0.8)
comparison = tracker.get_monthly_comparison("2026-11", previous_month="2026-10")

bill = tracker.track_shared_expenses(
    30, "Dinner", ["You", "Alex", "Sam"], paid_by="You", user="You",
    category="Food", date="2026-11-05"
)
print(tracker.get_shared_balances(bill))
tracker.settle_shared_expense(bill, "Alex", 10, date="2026-11-06")
```

- Recurring bills support weekly and monthly schedules. Creating a schedule
  does not post a payment; explicitly process due bills through an inclusive
  date. Processing the same range again creates no duplicates, even after
  saving/loading. Month-end anchors survive February and leap years. Cancelling
  stops future posting and keeps already recorded payments.
- Savings contributions are separate transfers, excluded from expenditure.
  Progress includes all recorded contributions, permits exceeding the target,
  and caps the displayed percentage at 100%.
- Alerts return dictionaries with warning/reached/exceeded status and a message.
  They do not send desktop notifications. Monthly comparisons include totals,
  category differences and percentage changes; a zero previous total yields
  `None` for percentage change. Comparisons use whole recorded months, so a
  partially recorded current month is not normalised against a complete one.
- Shared bills post only your share as an expense. Equal splits distribute spare
  pennies in participant order. Supply `shares={"You": 10, "Alex": 20}` for a
  custom split; it must name every participant and sum to the bill. The payer
  and user must be participants. Balances show who owes the payer for each bill.
  Partial settlements reduce debts without creating extra expenses; overpayment
  and settlements dated before the bill are rejected. Record a shared bill with
  this method instead of also adding the full bill via `add_expense()`.

## Advanced features

```python
forecast = tracker.predict_future_spending("week", on_date="2026-11-05", lookback_days=90)
unusual = tracker.detect_unusual_spending(on_date="2026-11-05")
suggestion = tracker.suggest_budget_adjustments("monthly", on_date="2026-11-05")
category = tracker.auto_categorise_expense("Tesco groceries")

tracker.export_expenses_csv("expenses.csv", period="month", on_date="2026-11-05")
tracker.export_expenses_csv("category_report.csv", report="categories")
```

- Forecasts use daily averages over the previous 90 days, counting days without
  spending. Today and future transactions are excluded. Weekly forecasts cover
  seven days starting on `on_date`; monthly forecasts span from `on_date` up to
  the same day next month, exclusive, clamping month ends. Results include the
  date window, sample count, category estimates and total. With no history the
  estimate is zero. Incomplete recorded history can underestimate spending.
- Unusual spending detection compares each transaction with earlier transactions
  in its category, using the median and median absolute deviation. At least five
  earlier samples are required by default. The threshold is the larger of twice
  the median and median plus three scaled deviations. It flags transactions,
  not fraud, and skips categories with insufficient history.
- Budget suggestions allocate an existing budget proportionally to recent
  spending. Without one, they suggest projected expenditure plus a 10% buffer.
  Penny allocation keeps category caps equal to the suggested total. Sparse or
  unrecorded commitments need review. Suggestions never modify your budget.
- CSV exports support transactions and category reports, with optional date
  filters. They use UTF-8 with BOM for Excel, proper quoting and protection
  against text being interpreted as formulas. The return value is the row count.
- Automatic categorisation uses whole-word keyword rules, with `Other` as the
  fallback. Explicit categories override suggestions. Updating a description
  preserves its category; call `categorise_expense()` to change it.

## Compatibility and persistence

The original add/update/remove/clear, count, total, average, string and index-based
methods remain available. `add_expense(amount, description)` still works; each
expense now also has `category` and `date`. Public query methods return copies.
Treat the underlying collection attributes as internal data; direct mutations
bypass validation. `clear_expenses()` clears posted expenses only; it keeps
income, budgets, savings, shared debts and schedules, including schedule posting
positions. Clearing/removing a recurring payment does not repost it automatically.
Likewise, editing/removing a personal share does not rewrite the shared debt record.

Amounts must be positive finite numbers, with zero permitted for limits and
search bounds. Inputs round half up to pennies, while allowance rounds down.
The API returns floats; totals use decimal arithmetic to avoid accumulation
errors on ordinary currency amounts. The currency symbol is cosmetic: there
is no currency conversion, bank connection or opening balance. Record starting
funds as income if you want them included in the allowance.

JSON saves include every collection and the currency symbol in a versioned
object. Saves replace the destination atomically. Loads validate a replacement
tracker before changing the current one. Original JSON lists remain readable:
missing dates become the local date on import, and missing categories are
suggested from descriptions. New saves use the expanded format. `repr()`
reconstructs expense data only; JSON is the full-state persistence interface.
