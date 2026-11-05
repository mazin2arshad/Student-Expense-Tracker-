"""Student expense tracker. Standard library only; dates use ISO YYYY-MM-DD."""

import calendar
import csv
import json
import math
import re
import statistics
from copy import deepcopy
from datetime import date as Date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional
from uuid import uuid4


class ExpenseTracker:
    """Track personal spending with calendar budgets and explicit recurring posting.

    Amounts are rounded to pennies on entry. Queries return copies. Index-based
    expense methods remain compatible with the original tracker.
    """

    currency = "$"
    CATEGORIES = ("Food", "Transport", "Rent", "Entertainment", "Shopping", "Education", "Other")
    CATEGORY_KEYWORDS = {
        "Rent": ("rent", "accommodation", "landlord"),
        "Education": ("tuition", "textbook", "textbooks", "stationery", "course", "university"),
        "Transport": ("bus", "train", "uber", "taxi", "fuel", "petrol", "transport", "tram"),
        "Food": ("groceries", "grocery", "supermarket", "tesco", "aldi", "lidl", "food", "coffee", "cafe", "restaurant", "lunch", "dinner", "takeaway"),
        "Entertainment": ("cinema", "netflix", "spotify", "gym", "concert", "gaming", "pub", "subscription"),
        "Shopping": ("clothes", "clothing", "shoes", "shopping", "amazon"),
    }

    def __init__(self, expenses: Optional[list] = None) -> None:
        self.expenses = []
        self.incomes = []
        self.budgets = {}
        self.recurring_expenses = []
        self.savings_goals = []
        self.shared_expenses = []
        if expenses is not None and not isinstance(expenses, list):
            raise TypeError("expenses must be a list.")
        for item in expenses or []:
            self.expenses.append(self._clean_expense(item))

    @staticmethod
    def _money(value) -> float:
        return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    @staticmethod
    def _sum(values) -> float:
        return float(sum((Decimal(str(value)) for value in values), Decimal("0")))

    @classmethod
    def _validate_amount(cls, amount, allow_zero=False) -> float:
        if isinstance(amount, bool) or not isinstance(amount, (int, float, Decimal)):
            raise TypeError("Amount must be a number.")
        try:
            number = Decimal(str(amount))
            if not number.is_finite() or number < 0 or (number == 0 and not allow_zero):
                raise ValueError("Amount must be finite and positive (or zero where allowed).")
            result = cls._money(number)
        except (InvalidOperation, OverflowError) as error:
            raise ValueError("Amount is outside the supported range.") from error
        if not math.isfinite(result) or (result == 0 and not allow_zero):
            raise ValueError("Amount must be at least 0.01.")
        return result

    @staticmethod
    def _validate_description(description) -> str:
        if not isinstance(description, str) or not description.strip():
            raise ValueError("Description must be a non-empty string.")
        return description.strip()

    @staticmethod
    def _date(value=None) -> Date:
        if value is None:
            return Date.today()
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, Date):
            return value
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            try:
                return Date.fromisoformat(value)
            except ValueError:
                pass
        raise ValueError("Date must be a date object or an ISO date (YYYY-MM-DD).")

    @classmethod
    def _category(cls, category) -> str:
        if isinstance(category, str):
            for name in cls.CATEGORIES:
                if category.strip().casefold() == name.casefold():
                    return name
        raise ValueError(f"Category must be one of: {', '.join(cls.CATEGORIES)}.")

    @staticmethod
    def _period(period) -> str:
        names = {"day": "day", "daily": "day", "week": "week", "weekly": "week",
                 "month": "month", "monthly": "month", "custom": "custom"}
        if not isinstance(period, str) or period.lower() not in names:
            raise ValueError("Period must be day, week, month, or custom.")
        return names[period.lower()]

    @classmethod
    def _budget_period(cls, period) -> str:
        period = cls._period(period)
        if period not in ("week", "month"):
            raise ValueError("Budget period must be weekly or monthly.")
        return period

    @classmethod
    def _range(cls, period="month", on_date=None, start_date=None, end_date=None):
        period = cls._period(period)
        if period == "custom" or start_date is not None or end_date is not None:
            if start_date is None or end_date is None:
                raise ValueError("Custom ranges need both start_date and end_date.")
            start, end = cls._date(start_date), cls._date(end_date)
        else:
            reference = cls._date(on_date)
            if period == "day":
                start = end = reference
            elif period == "week":
                start = reference - timedelta(days=reference.weekday())
                end = start + timedelta(days=6)
            else:
                start = reference.replace(day=1)
                end = reference.replace(day=calendar.monthrange(reference.year, reference.month)[1])
        if start > end:
            raise ValueError("start_date must not be after end_date.")
        return start, end

    def _validate_index(self, index) -> None:
        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError("Index must be an integer.")
        if not 0 <= index < len(self.expenses):
            raise IndexError("Expense index out of range.")

    @staticmethod
    def _find(records, record_id):
        for record in records:
            if record["id"] == record_id:
                return record
        raise ValueError(f"Unknown record ID: {record_id}")

    def auto_categorise_expense(self, description: str) -> str:
        """Suggest a category using whole-word keywords; unknown descriptions are Other."""
        words = set(re.findall(r"\w+", self._validate_description(description).casefold()))
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            if words.intersection(keywords):
                return category
        return "Other"

    def _clean_expense(self, item):
        if not isinstance(item, dict) or "amount" not in item or "description" not in item:
            raise ValueError("Each expense needs amount and description.")
        description = self._validate_description(item["description"])
        result = {"amount": self._validate_amount(item["amount"]), "description": description,
                  "category": self._category(item["category"]) if item.get("category") is not None else self.auto_categorise_expense(description),
                  "date": self._date(item.get("date")).isoformat()}
        for key in ("recurring_id", "shared_id"):
            if key in item:
                result[key] = self._validate_description(item[key])
        return result

    def add_expense(self, amount: float, description: str, category=None, date=None) -> None:
        self.expenses.append(self._clean_expense(
            {"amount": amount, "description": description, "category": category, "date": date}))

    def update_expense(self, index: int, amount=None, description=None, category=None, date=None) -> None:
        """Validate every supplied field before changing the expense."""
        self._validate_index(index)
        changes = {key: value for key, value in locals().items()
                   if key in ("amount", "description", "category", "date") and value is not None}
        if not changes:
            raise ValueError("Provide an amount, description, category, or date.")
        self.expenses[index] = self._clean_expense({**self.expenses[index], **changes})

    def categorise_expense(self, index: int, category: str) -> None:
        self.update_expense(index, category=category)

    def remove_expense(self, index: int) -> dict:
        self._validate_index(index)
        return self.expenses.pop(index)

    def clear_expenses(self) -> None:
        """Clear posted expenses; keep budgets, income, and recurring schedules."""
        self.expenses.clear()

    def get_expenses(self) -> list:
        return deepcopy(self.expenses)

    def get_expense(self, index: int) -> dict:
        self._validate_index(index)
        return deepcopy(self.expenses[index])

    def get_expense_count(self) -> int:
        return len(self.expenses)

    def get_total_expenses(self) -> float:
        return self._sum(e["amount"] for e in self.expenses)

    def get_average_expense(self) -> float:
        return self._money(self.get_total_expenses() / len(self.expenses)) if self.expenses else 0.0

    def get_expenses_by_date(self, period="month", on_date=None, start_date=None, end_date=None) -> list:
        """Return expenses in an inclusive calendar day/week/month or custom range."""
        start, end = self._range(period, on_date, start_date, end_date)
        return [deepcopy(e) for e in self.expenses if start <= self._date(e["date"]) <= end]

    # Keep the spelling in the original feature request usable as well.
    get_epenses_by_date = get_expenses_by_date

    def search_expenses(self, description=None, category=None, min_amount=None,
                        max_amount=None, start_date=None, end_date=None, amount=None) -> list:
        """Combine optional filters with AND; description is a case-insensitive substring."""
        if description is not None:
            description = self._validate_description(description).casefold()
        category = self._category(category) if category is not None else None
        lower = self._validate_amount(min_amount, True) if min_amount is not None else None
        upper = self._validate_amount(max_amount, True) if max_amount is not None else None
        exact = self._validate_amount(amount, True) if amount is not None else None
        start = self._date(start_date) if start_date is not None else Date.min
        end = self._date(end_date) if end_date is not None else Date.max
        if start > end or (lower is not None and upper is not None and lower > upper):
            raise ValueError("Filter lower bound must not exceed its upper bound.")
        return [deepcopy(e) for e in self.expenses
                if (description is None or description in e["description"].casefold())
                and (category is None or category == e["category"])
                and (lower is None or e["amount"] >= lower)
                and (upper is None or e["amount"] <= upper)
                and (exact is None or e["amount"] == exact)
                and start <= self._date(e["date"]) <= end]

    def get_spending_by_category(self, period=None, on_date=None, start_date=None, end_date=None) -> dict:
        """Return all seven categories, including those with zero expenditure."""
        records = self.expenses if period is None and start_date is None and end_date is None else self.get_expenses_by_date(period or "custom", on_date, start_date, end_date)
        return {category: self._sum(e["amount"] for e in records if e["category"] == category)
                for category in self.CATEGORIES}

    def set_budget(self, amount, period="monthly", category_limits=None) -> dict:
        """Set a repeating calendar budget. Category caps may total less than the budget."""
        period = self._budget_period(period)
        amount = self._validate_amount(amount)
        if category_limits is not None and not isinstance(category_limits, dict):
            raise TypeError("category_limits must be a dictionary.")
        limits = {}
        for category, limit in (category_limits or {}).items():
            name = self._category(category)
            if name in limits:
                raise ValueError("Duplicate category limit.")
            limits[name] = self._validate_amount(limit, True)
        if self._sum(limits.values()) > amount:
            raise ValueError("Category limits must not total more than the overall budget.")
        budget = {"amount": amount, "category_limits": limits}
        self.budgets[period] = budget
        return deepcopy(budget)

    def get_remaining_budget(self, period="monthly", on_date=None, category=None) -> float:
        period = self._budget_period(period)
        if period not in self.budgets:
            raise ValueError(f"No {period} budget has been set.")
        budget = self.budgets[period]
        records = self.get_expenses_by_date(period, on_date)
        if category is None:
            limit = budget["amount"]
        else:
            category = self._category(category)
            if category not in budget["category_limits"]:
                raise ValueError(f"No limit has been set for {category}.")
            limit = budget["category_limits"][category]
            records = [e for e in records if e["category"] == category]
        return self._money(Decimal(str(limit)) - Decimal(str(self._sum(e["amount"] for e in records))))

    def add_income(self, amount, source, date=None, description=None) -> str:
        """Record wages, student finance, allowance, or any other named source."""
        record = {"id": uuid4().hex, "amount": self._validate_amount(amount),
                  "source": self._validate_description(source), "date": self._date(date).isoformat(),
                  "description": self._validate_description(description) if description is not None else ""}
        self.incomes.append(record)
        return record["id"]

    def get_total_income(self, period=None, on_date=None, start_date=None, end_date=None) -> float:
        records = self.incomes
        if period is not None or start_date is not None or end_date is not None:
            start, end = self._range(period or "custom", on_date, start_date, end_date)
            records = [r for r in records if start <= self._date(r["date"]) <= end]
        return self._sum(r["amount"] for r in records)

    def calculate_daily_allowance(self, available_funds=None, end_date=None,
                                  on_date=None, period="monthly") -> float:
        """Divide spendable funds by remaining days, including today, rounding down.

        Without explicit funds, use income minus expenses and savings contributions
        through on_date, capped by any budget for the selected calendar period.
        Future income/bills are excluded; pass net available_funds to reserve them.
        Unrepaid cash advanced for friends is reserved until they repay it.
        """
        period = self._budget_period(period)
        today = self._date(on_date)
        end = self._date(end_date) if end_date is not None else self._range(period, today)[1]
        if available_funds is None:
            income = self._sum(r["amount"] for r in self.incomes if self._date(r["date"]) <= today)
            spent = self._sum(r["amount"] for r in self.expenses if self._date(r["date"]) <= today)
            saved = self._sum(c["amount"] for g in self.savings_goals for c in g["contributions"] if self._date(c["date"]) <= today)
            advanced = Decimal("0")
            for bill in self.shared_expenses:
                if bill["paid_by"] == bill["user"] and self._date(bill["date"]) <= today:
                    # Personal spending already includes the user's share; reserve
                    # the rest of the cash paid, less repayments received to date.
                    advanced += Decimal(str(bill["amount"])) - Decimal(str(bill["shares"][bill["user"]]))
                    advanced -= sum((Decimal(str(p["amount"])) for p in bill["settlements"]
                                     if self._date(p["date"]) <= today), Decimal("0"))
            funds = self._money(Decimal(str(income)) - Decimal(str(spent)) - Decimal(str(saved)) - advanced)
        else:
            funds = self._validate_amount(available_funds, True)
        if period in self.budgets:
            funds = min(funds, self.get_remaining_budget(period, today))
        days = (end - today).days + 1
        return float((Decimal(str(max(0, funds))) / days).quantize(Decimal("0.01"), rounding=ROUND_DOWN)) if days > 0 else 0.0

    def add_recurring_expense(self, amount, description, frequency="monthly", start_date=None,
                              category=None, end_date=None) -> str:
        """Create a schedule; call process_recurring_expenses to post due bills."""
        frequency = self._budget_period(frequency)
        expense = self._clean_expense({"amount": amount, "description": description,
                                       "category": category, "date": start_date})
        end = self._date(end_date).isoformat() if end_date is not None else None
        if end is not None and end < expense["date"]:
            raise ValueError("Recurring end date must not precede start date.")
        record = {"id": uuid4().hex, "amount": expense["amount"], "description": expense["description"],
                  "category": expense["category"], "frequency": frequency, "start_date": expense["date"],
                  "next_date": expense["date"], "end_date": end, "active": True}
        self.recurring_expenses.append(record)
        return record["id"]

    def cancel_recurring_expense(self, recurring_id) -> None:
        self._find(self.recurring_expenses, recurring_id)["active"] = False

    @staticmethod
    def _next_due(record, due):
        if record["frequency"] == "week":
            return due + timedelta(days=7)
        month_number = due.year * 12 + due.month
        year, month = divmod(month_number, 12)
        month += 1
        anchor = Date.fromisoformat(record["start_date"]).day
        return Date(year, month, min(anchor, calendar.monthrange(year, month)[1]))

    def process_recurring_expenses(self, until_date=None) -> list:
        """Post every due occurrence once, including until_date; retain month-end anchors."""
        until = self._date(until_date)
        schedules = deepcopy(self.recurring_expenses)
        posted = []
        for record in schedules:
            due = self._date(record["next_date"])
            end = self._date(record["end_date"]) if record["end_date"] else Date.max
            while record["active"] and due <= min(until, end):
                posted.append(self._clean_expense({**record, "date": due, "recurring_id": record["id"]}))
                due = self._next_due(record, due)
            record["next_date"] = due.isoformat()
        self.expenses.extend(posted)
        self.recurring_expenses = schedules
        return deepcopy(posted)

    def create_savings_goal(self, name, target_amount, target_date=None) -> str:
        record = {"id": uuid4().hex, "name": self._validate_description(name),
                  "target_amount": self._validate_amount(target_amount),
                  "target_date": self._date(target_date).isoformat() if target_date is not None else None,
                  "contributions": []}
        self.savings_goals.append(record)
        return record["id"]

    def contribute_to_savings(self, goal_id, amount, date=None) -> dict:
        goal = self._find(self.savings_goals, goal_id)
        contribution = {"amount": self._validate_amount(amount), "date": self._date(date).isoformat()}
        goal["contributions"].append(contribution)
        return self.get_savings_progress(goal_id)

    def get_savings_progress(self, goal_id) -> dict:
        goal = self._find(self.savings_goals, goal_id)
        saved = self._sum(c["amount"] for c in goal["contributions"])
        return {**deepcopy(goal), "saved": saved,
                "remaining": max(0.0, self._money(goal["target_amount"] - saved)),
                "progress_percent": min(100.0, round(saved / goal["target_amount"] * 100, 2))}

    def check_budget_alerts(self, period="monthly", on_date=None, threshold=0.8) -> list:
        """Return structured alerts at/above threshold; nothing is sent externally."""
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < threshold <= 1:
            raise ValueError("Threshold must be greater than zero and at most one.")
        period = self._budget_period(period)
        if period not in self.budgets:
            raise ValueError(f"No {period} budget has been set.")
        budget = self.budgets[period]
        totals = self.get_spending_by_category(period, on_date)
        alerts = []
        for category, limit in [(None, budget["amount"]), *budget["category_limits"].items()]:
            spent = self._sum(totals.values()) if category is None else totals[category]
            at_threshold = Decimal(str(spent)) >= Decimal(str(limit)) * Decimal(str(threshold))
            if (limit > 0 and at_threshold) or (limit == 0 and spent > 0):
                status = "exceeded" if spent > limit else "reached" if spent == limit else "warning"
                label = category or "Overall"
                alerts.append({"category": category, "period": period, "limit": limit, "spent": spent,
                               "remaining": self._money(limit - spent), "status": status,
                               "message": f"{label} budget {status}: {self.currency}{spent:.2f} of {self.currency}{limit:.2f} spent."})
        return alerts

    @classmethod
    def _month(cls, value):
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}", value):
            value += "-01"
        return cls._date(value).replace(day=1)

    def get_monthly_comparison(self, month=None, previous_month=None) -> dict:
        """Compare whole calendar months; None percent means no previous baseline."""
        current = self._month(month)
        previous = self._month(previous_month) if previous_month is not None else (current - timedelta(days=1)).replace(day=1)
        current_totals = self.get_spending_by_category("month", current)
        previous_totals = self.get_spending_by_category("month", previous)

        def compare(now, before):
            return {"current": now, "previous": before, "difference": self._money(now - before),
                    "percent_change": round((now - before) / before * 100, 2) if before else None}

        return {"month": current.strftime("%Y-%m"), "previous_month": previous.strftime("%Y-%m"),
                **compare(self._sum(current_totals.values()), self._sum(previous_totals.values())),
                "categories": {c: compare(current_totals[c], previous_totals[c]) for c in self.CATEGORIES}}

    def track_shared_expenses(self, amount, description, participants, paid_by="You",
                              user="You", shares=None, category=None, date=None) -> str:
        """Record each person's share and post only the user's share as personal spending.

        Equal splits allocate spare pennies in participant order. Custom shares must
        sum exactly to the bill. Balances represent debts to the person who paid.
        """
        expense = self._clean_expense({"amount": amount, "description": description, "category": category, "date": date})
        if not isinstance(participants, (list, tuple)) or not participants:
            raise ValueError("Provide a non-empty list of participants.")
        names = [self._validate_description(p) for p in participants]
        paid_by, user = self._validate_description(paid_by), self._validate_description(user)
        if len(set(names)) != len(names) or paid_by not in names or user not in names:
            raise ValueError("Participants must be unique and include paid_by and user.")
        if shares is None:
            pennies = int(Decimal(str(expense["amount"])) * 100)
            base, extra = divmod(pennies, len(names))
            allocated = {name: (base + (i < extra)) / 100 for i, name in enumerate(names)}
        else:
            if not isinstance(shares, dict) or set(shares) != set(names):
                raise ValueError("Custom shares must name every participant exactly once.")
            allocated = {name: self._validate_amount(shares[name], True) for name in names}
            if self._sum(allocated.values()) != expense["amount"]:
                raise ValueError("Shares must sum to the bill amount.")
        record = {**expense, "id": uuid4().hex, "participants": names, "paid_by": paid_by,
                  "user": user, "shares": allocated, "settlements": []}
        if allocated[user] > 0:
            self.expenses.append({**expense, "amount": allocated[user], "shared_id": record["id"]})
        self.shared_expenses.append(record)
        return record["id"]

    def get_shared_balances(self, shared_id=None) -> list:
        records = [self._find(self.shared_expenses, shared_id)] if shared_id is not None else self.shared_expenses
        balances = []
        for record in records:
            for person in record["participants"]:
                if person == record["paid_by"]:
                    continue
                paid = self._sum(s["amount"] for s in record["settlements"] if s["participant"] == person)
                balances.append({"shared_id": record["id"], "from": person, "to": record["paid_by"],
                                 "amount": self._money(record["shares"][person] - paid)})
        return balances

    def settle_shared_expense(self, shared_id, participant, amount, date=None) -> None:
        record = self._find(self.shared_expenses, shared_id)
        amount = self._validate_amount(amount)
        paid_on = self._date(date).isoformat()
        if paid_on < record["date"]:
            raise ValueError("Settlement date cannot precede the shared expense.")
        outstanding = next((b["amount"] for b in self.get_shared_balances(shared_id) if b["from"] == participant), None)
        if outstanding is None or amount > outstanding:
            raise ValueError("Payment must be from a debtor and cannot exceed their balance.")
        record["settlements"].append({"participant": participant, "amount": amount, "date": paid_on})

    def _history(self, on_date, lookback_days):
        if isinstance(lookback_days, bool) or not isinstance(lookback_days, int) or lookback_days <= 0:
            raise ValueError("lookback_days must be a positive integer.")
        end = self._date(on_date) - timedelta(days=1)
        start = end - timedelta(days=lookback_days - 1)
        records = self.get_expenses_by_date("custom", start_date=start, end_date=end)
        return records, start, end

    def predict_future_spending(self, period="week", on_date=None, lookback_days=90) -> dict:
        """Estimate the next 7 days or one calendar month from prior daily averages.

        Zero-spend days count; today/future records are excluded. This descriptive
        estimate assumes the recorded history covers the entire lookback window.
        """
        period = self._budget_period(period)
        today = self._date(on_date)
        records, start, end = self._history(today, lookback_days)
        if period == "week":
            days = 7
        else:
            next_month = self._next_due({"frequency": "month", "start_date": today.isoformat()}, today)
            days = (next_month - today).days
        totals = {c: self._sum(e["amount"] for e in records if e["category"] == c) for c in self.CATEGORIES}
        categories = {c: self._money(value / lookback_days * days) for c, value in totals.items()}
        return {"period": period, "days": days, "start_date": today.isoformat(),
                "end_date": (today + timedelta(days=days - 1)).isoformat(),
                "history_start": start.isoformat(), "history_end": end.isoformat(),
                "sample_count": len(records), "estimated_total": self._sum(categories.values()),
                "by_category": categories}

    def detect_unusual_spending(self, on_date=None, lookback_days=90, min_samples=5, multiplier=3.0) -> list:
        """Flag high transactions against earlier same-category history using median/MAD.

        Each transaction is compared only to earlier dates, avoiding self-influence.
        Sparse histories are skipped. A 2x-median floor avoids tiny baselines.
        """
        if isinstance(min_samples, bool) or not isinstance(min_samples, int) or min_samples < 3:
            raise ValueError("min_samples must be at least three.")
        if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)) or not math.isfinite(multiplier) or multiplier <= 0:
            raise ValueError("multiplier must be positive and finite.")
        today = self._date(on_date)
        self._history(today, lookback_days)  # validate the window
        start = today - timedelta(days=lookback_days - 1)
        alerts = []
        for index, expense in enumerate(self.expenses):
            occurred = self._date(expense["date"])
            if not start <= occurred <= today:
                continue
            baseline = [e["amount"] for e in self.expenses if e["category"] == expense["category"]
                        and occurred - timedelta(days=lookback_days) <= self._date(e["date"]) < occurred]
            if len(baseline) < min_samples:
                continue
            median = statistics.median(baseline)
            mad = statistics.median(abs(value - median) for value in baseline)
            limit = max(median * 2, median + multiplier * 1.4826 * mad)
            if expense["amount"] > limit:
                alerts.append({"index": index, "expense": deepcopy(expense), "baseline_median": self._money(median),
                               "threshold": self._money(limit), "reason": "Unusually high for this category's earlier transactions."})
        return alerts

    def suggest_budget_adjustments(self, period="monthly", on_date=None, lookback_days=90,
                                    buffer_percent=10) -> dict:
        """Suggest category limits from recent spending; never change saved budgets.

        With an existing budget, allocate its total proportionally. Without one,
        suggest the projected spend plus the requested percentage buffer.
        """
        if isinstance(buffer_percent, bool) or not isinstance(buffer_percent, (int, float)) or not math.isfinite(buffer_percent) or buffer_percent < 0:
            raise ValueError("buffer_percent must be finite and non-negative.")
        period = self._budget_period(period)
        prediction = self.predict_future_spending(period, on_date, lookback_days)
        total = prediction["estimated_total"]
        if not prediction["sample_count"]:
            return {"period": period, "suggested_total": None, "category_limits": {}, "reason": "Not enough recorded history."}
        budget = self.budgets.get(period)
        target = budget["amount"] if budget else self._money(total * (1 + buffer_percent / 100))
        weights = prediction["by_category"]
        # Largest-remainder allocation keeps rounded limits within the total.
        pennies = int(Decimal(str(target)) * 100)
        weight_total = sum(Decimal(str(w)) for w in weights.values())
        if weight_total == 0:
            return {"period": period, "suggested_total": None, "category_limits": {}, "reason": "Recorded spending is too small for this projection."}
        raw = {c: Decimal(str(w)) / weight_total * pennies for c, w in weights.items()}
        allocated = {c: int(value) for c, value in raw.items()}
        remaining = pennies - sum(allocated.values())
        for category in sorted(raw, key=lambda c: raw[c] - allocated[c], reverse=True)[:remaining]:
            allocated[category] += 1
        return {"period": period, "suggested_total": target,
                "category_limits": {c: value / 100 for c, value in allocated.items()},
                "reason": "Based on prior daily spending averages; review upcoming commitments before applying."}

    @staticmethod
    def _csv_cell(value):
        # Prevent text descriptions being interpreted as spreadsheet formulas.
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    def export_expenses_csv(self, filename, period=None, on_date=None, start_date=None,
                            end_date=None, report="transactions") -> int:
        """Export transactions or a category summary; return number of data rows."""
        if report not in ("transactions", "categories"):
            raise ValueError("report must be transactions or categories.")
        if report == "categories":
            totals = self.get_spending_by_category(period, on_date, start_date, end_date)
            fields, rows = ["category", "amount"], [{"category": c, "amount": f"{v:.2f}"} for c, v in totals.items()]
        else:
            records = self.expenses if period is None and start_date is None and end_date is None else self.get_expenses_by_date(period or "custom", on_date, start_date, end_date)
            fields = ["date", "description", "category", "amount"]
            rows = [{**{key: self._csv_cell(e[key]) for key in fields}, "amount": f"{e['amount']:.2f}"} for e in records]
        with open(filename, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return len(rows)

    def save_to_file(self, filename: str) -> None:
        """Atomically save all tracker data as versioned JSON."""
        data = {"version": 2, "currency": self.currency, "expenses": self.expenses,
                "incomes": self.incomes, "budgets": self.budgets, "recurring_expenses": self.recurring_expenses,
                "savings_goals": self.savings_goals, "shared_expenses": self.shared_expenses}
        path = Path(filename)
        temporary = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.resolve().parent,
                                    prefix=path.name + ".", suffix=".tmp", delete=False) as file:
                temporary = Path(file.name)
                json.dump(data, file, indent=2, allow_nan=False)
            temporary.replace(path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    @staticmethod
    def _restore_id(record, item, seen):
        identifier = item["id"]
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            raise ValueError("Record IDs must be non-empty and unique within each collection.")
        seen.add(identifier)
        record["id"] = identifier

    @classmethod
    def _check_saved_dates(cls, record, required, optional=()):
        """Stored dates cannot silently default to today as new transaction dates do."""
        for key in (*required, *optional):
            value = record[key]
            if value is None and key in optional:
                continue
            if not isinstance(value, str):
                raise ValueError(f"Saved {key} must be an ISO date string.")
            cls._date(value)

    def load_from_file(self, filename: str) -> None:
        """Load all data atomically, also accepting the original list-only JSON format.

        Legacy undated expenses receive today's date and a suggested category.
        Malformed files never replace existing data.
        """
        with open(filename, "r", encoding="utf-8") as file:
            data = json.load(file)
        try:
            if isinstance(data, list):
                candidate = ExpenseTracker(data)
                candidate.currency = self.currency
            else:
                if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 2:
                    raise ValueError("Expected legacy expense list or tracker version 2.")
                for key in ("expenses", "incomes", "recurring_expenses", "savings_goals", "shared_expenses"):
                    if not isinstance(data[key], list):
                        raise ValueError(f"{key} must be a list.")
                if not isinstance(data["budgets"], dict):
                    raise ValueError("budgets must be a dictionary.")
                for expense in data["expenses"]:
                    self._check_saved_dates(expense, ("date",))
                    self._category(expense["category"])
                candidate = ExpenseTracker(data["expenses"])
                candidate.currency = self._validate_description(data["currency"])
                for period, budget in data["budgets"].items():
                    if period not in ("week", "month"):
                        raise ValueError("Invalid saved budget period.")
                    candidate.set_budget(budget["amount"], period, budget["category_limits"])
                seen = set()
                for item in data["incomes"]:
                    self._check_saved_dates(item, ("date",))
                    description = item["description"]
                    if not isinstance(description, str):
                        raise ValueError("Income description must be a string.")
                    candidate.add_income(item["amount"], item["source"], item["date"], description if description != "" else None)
                    self._restore_id(candidate.incomes[-1], item, seen)
                seen = set()
                for item in data["recurring_expenses"]:
                    self._check_saved_dates(item, ("start_date", "next_date"), ("end_date",))
                    candidate.add_recurring_expense(item["amount"], item["description"], item["frequency"],
                                                     item["start_date"], item["category"], item["end_date"])
                    record = candidate.recurring_expenses[-1]
                    self._restore_id(record, item, seen)
                    due = self._date(item["next_date"])
                    start = self._date(record["start_date"])
                    if type(item["active"]) is not bool or due < start:
                        raise ValueError("Invalid recurring schedule state.")
                    if record["frequency"] == "week":
                        valid_due = (due - start).days % 7 == 0
                    else:
                        valid_due = due.day == min(start.day, calendar.monthrange(due.year, due.month)[1])
                    if not valid_due:
                        raise ValueError("Next due date does not match the recurrence.")
                    record.update(next_date=due.isoformat(), active=item["active"])
                seen = set()
                for item in data["savings_goals"]:
                    self._check_saved_dates(item, (), ("target_date",))
                    candidate.create_savings_goal(item["name"], item["target_amount"], item["target_date"])
                    record = candidate.savings_goals[-1]
                    self._restore_id(record, item, seen)
                    if not isinstance(item["contributions"], list):
                        raise ValueError("Contributions must be a list.")
                    for contribution in item["contributions"]:
                        self._check_saved_dates(contribution, ("date",))
                        candidate.contribute_to_savings(record["id"], contribution["amount"], contribution["date"])
                seen = set()
                for item in data["shared_expenses"]:
                    self._check_saved_dates(item, ("date",))
                    before = len(candidate.expenses)
                    candidate.track_shared_expenses(item["amount"], item["description"], item["participants"],
                        item["paid_by"], item["user"], item["shares"], item["category"], item["date"])
                    del candidate.expenses[before:]  # Personal shares are already in saved expenses.
                    record = candidate.shared_expenses[-1]
                    self._restore_id(record, item, seen)
                    if not isinstance(item["settlements"], list):
                        raise ValueError("Settlements must be a list.")
                    for payment in item["settlements"]:
                        self._check_saved_dates(payment, ("date",))
                        candidate.settle_shared_expense(record["id"], payment["participant"], payment["amount"], payment["date"])
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"Invalid tracker data: {error}") from error
        self.__dict__.update(candidate.__dict__)

    def __len__(self) -> int:
        return len(self.expenses)

    def __str__(self) -> str:
        lines = [f"{e['date']} | {e['category']} | {e['description']}: {self.currency}{e['amount']:.2f}" for e in self.expenses]
        details = "\n".join(lines) if lines else "No expenses recorded."
        return f"Total Expenses: {self.currency}{self.get_total_expenses():.2f}\nExpenses:\n{details}"

    def __repr__(self) -> str:
        """Reconstruct expense data; use JSON persistence to preserve the full ledger."""
        return f"ExpenseTracker(expenses={self.expenses!r})"


def main() -> None:
    """Run a small demonstration without writing files."""
    tracker = ExpenseTracker()
    tracker.currency = "\u00a3"
    tracker.add_income(1200, "Student finance")
    tracker.set_budget(800, category_limits={"Food": 200, "Transport": 80})
    tracker.add_expense(35.50, "Groceries")
    tracker.add_expense(12, "Bus pass")
    goal = tracker.create_savings_goal("Emergency fund", 500)
    tracker.contribute_to_savings(goal, 50)
    print(tracker)
    print(f"\nMonthly budget remaining: {tracker.currency}{tracker.get_remaining_budget():.2f}")
    print(f"Daily allowance: {tracker.currency}{tracker.calculate_daily_allowance():.2f}")
    print(f"Savings progress: {tracker.get_savings_progress(goal)['progress_percent']}%")


if __name__ == "__main__":
    main()
