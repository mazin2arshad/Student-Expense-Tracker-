"""Regression and feature tests; run with python -m unittest -v."""

import csv
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from ExpenseTracker import ExpenseTracker


class ExpenseTrackerTests(unittest.TestCase):
    def setUp(self):
        self.tracker = ExpenseTracker()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tracker.json"

    def test_original_crud_and_copies(self):
        t = ExpenseTracker([{"amount": 5, "description": "Coffee"}])
        t.add_expense(10, "Bus")
        self.assertEqual(len(t), 2)
        self.assertEqual(t.get_expense_count(), 2)
        self.assertEqual(t.get_total_expenses(), 15)
        self.assertEqual(t.get_average_expense(), 7.5)
        t.get_expenses()[0]["amount"] = 999
        t.get_expense(0)["amount"] = 888
        self.assertEqual(t.get_total_expenses(), 15)
        t.update_expense(0, amount=6, description="Lunch", date="2026-11-05")
        self.assertEqual(t.get_expense(0)["description"], "Lunch")
        self.assertEqual(t.remove_expense(1)["amount"], 10)
        self.assertEqual(eval(repr(t), {"ExpenseTracker": ExpenseTracker}).expenses, t.expenses)
        self.assertIn("Lunch", str(t))
        t.clear_expenses()
        self.assertEqual(t.get_average_expense(), 0)

    def test_amount_validation_and_penny_rounding(self):
        t = self.tracker
        for amount in (True, "5", None):
            with self.subTest(amount=amount), self.assertRaises(TypeError):
                t.add_expense(amount, "Bad")
        for amount in (0, -1, float("inf"), float("nan"), 0.001):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                t.add_expense(amount, "Bad")
        t.add_expense(1.005, "Rounded")
        t.add_expense(Decimal("0.10"), "Decimal")
        t.add_expense(0.2, "Float")
        self.assertEqual(t.get_total_expenses(), 1.31)

    def test_invalid_updates_are_atomic(self):
        t = self.tracker
        t.add_expense(10, "Original")
        before = t.get_expenses()
        for changes in ({"amount": 20, "category": "Unknown"}, {"amount": 20, "date": "2026-02-30"}, {}):
            with self.assertRaises(ValueError):
                t.update_expense(0, **changes)
            self.assertEqual(t.expenses, before)
        with self.assertRaises(TypeError):
            t.remove_expense(True)
        with self.assertRaises(IndexError):
            t.categorise_expense(-1, "Food")

    def test_category_suggestions_and_overrides(self):
        t = self.tracker
        expected = {"TESCO groceries": "Food", "Uber ride": "Transport", "Monthly rent": "Rent",
                    "Netflix": "Entertainment", "New shoes": "Shopping", "Textbook": "Education",
                    "Unknown merchant": "Other", "Business services": "Other"}
        for description, category in expected.items():
            self.assertEqual(t.auto_categorise_expense(description), category)
        t.add_expense(10, "Groceries", "sHoPpInG")
        self.assertEqual(t.get_expense(0)["category"], "Shopping")
        t.categorise_expense(0, " food ")
        self.assertEqual(t.get_expense(0)["category"], "Food")

    def test_calendar_ranges_and_legacy_spelling(self):
        t = self.tracker
        for day in ("2024-02-25", "2024-02-26", "2024-02-29", "2024-03-03", "2024-03-04"):
            t.add_expense(1, "Coffee", date=day)
        self.assertEqual(len(t.get_expenses_by_date("day", "2024-02-29")), 1)
        self.assertEqual(len(t.get_expenses_by_date("weekly", "2024-02-29")), 3)
        self.assertEqual(len(t.get_epenses_by_date("monthly", "2024-02-29")), 3)
        self.assertEqual(len(t.get_expenses_by_date("custom", start_date="2024-02-29", end_date="2024-03-03")), 2)
        for options in ({"period": "custom"}, {"start_date": "2024-02-01"},
                        {"start_date": "2024-03-01", "end_date": "2024-02-01"}):
            with self.assertRaises(ValueError):
                t.get_expenses_by_date(**options)
        t.add_expense(1, "Coffee", date=date(2024, 3, 5))
        self.assertEqual(t.get_expense(5)["date"], "2024-03-05")

    def test_combined_search_and_category_totals(self):
        t = self.tracker
        t.add_expense(10, "Campus lunch", date="2026-11-05")
        t.add_expense(20, "Campus bus", date="2026-11-06")
        t.add_expense(30, "Dinner", date="2026-10-05")
        rows = t.search_expenses(description="CAMPUS", category="food", min_amount=5,
                                 max_amount=15, amount=10, start_date="2026-11-05", end_date="2026-11-05")
        self.assertEqual(len(rows), 1)
        rows[0]["amount"] = 999
        self.assertEqual(t.get_expense(0)["amount"], 10)
        totals = t.get_spending_by_category("month", "2026-11-05")
        self.assertEqual(totals["Food"], 10)
        self.assertEqual(totals["Transport"], 20)
        self.assertEqual(totals["Rent"], 0)
        self.assertEqual(t.get_spending_by_category()["Food"], 40)
        with self.assertRaises(ValueError):
            t.search_expenses(min_amount=20, max_amount=10)

    def test_budgets_reset_with_calendar_and_validate_atomically(self):
        t = self.tracker
        t.set_budget(100, "monthly", {"Food": 50})
        t.set_budget(40, "weekly", {"Food": 30})
        t.add_expense(60, "Groceries", date="2026-11-05")
        t.add_expense(20, "Groceries", date="2026-10-05")
        self.assertEqual(t.get_remaining_budget("month", "2026-11-05"), 40)
        self.assertEqual(t.get_remaining_budget("week", "2026-11-05"), -20)
        self.assertEqual(t.get_remaining_budget("month", "2026-11-05", "Food"), -10)
        self.assertEqual(t.get_remaining_budget("month", "2026-12-05"), 100)
        before = deepcopy(t.budgets)
        with self.assertRaises(ValueError):
            t.set_budget(20, category_limits={"Food": 30})
        self.assertEqual(t.budgets, before)
        with self.assertRaises(ValueError):
            t.get_remaining_budget(category="Rent")
        with self.assertRaises(ValueError):
            ExpenseTracker().get_remaining_budget()

    def test_income_and_daily_allowance(self):
        t = self.tracker
        t.add_income(100, "Wages", "2026-11-01")
        t.add_income(1000, "Future wages", "2026-12-01")
        t.add_expense(10, "Food", date="2026-11-02")
        goal = t.create_savings_goal("Laptop", 500)
        t.contribute_to_savings(goal, 20, "2026-11-03")
        self.assertEqual(t.get_total_income("month", "2026-11-05"), 100)
        self.assertEqual(t.calculate_daily_allowance(on_date="2026-11-05", end_date="2026-11-11"), 10)
        self.assertEqual(t.calculate_daily_allowance(100, "2026-11-07", "2026-11-05"), 33.33)
        self.assertEqual(t.calculate_daily_allowance(100, "2026-11-04", "2026-11-05"), 0)
        t.set_budget(40)
        self.assertEqual(t.calculate_daily_allowance(100, "2026-11-07", "2026-11-05"), 10)
        t.add_expense(50, "Shopping", date="2026-11-05")
        self.assertEqual(t.calculate_daily_allowance(100, on_date="2026-11-05"), 0)

    def test_daily_allowance_reserves_shared_cash_until_repaid(self):
        t = self.tracker
        t.add_income(100, "Wages", "2026-11-01")
        shared = t.track_shared_expenses(60, "Dinner", ["You", "Alex"], date="2026-11-05")
        self.assertEqual(t.get_total_expenses(), 30)
        self.assertEqual(t.calculate_daily_allowance(on_date="2026-11-05", end_date="2026-11-05"), 40)
        t.settle_shared_expense(shared, "Alex", 10, "2026-11-06")
        self.assertEqual(t.calculate_daily_allowance(on_date="2026-11-05", end_date="2026-11-05"), 40)
        self.assertEqual(t.calculate_daily_allowance(on_date="2026-11-06", end_date="2026-11-06"), 50)
        with self.assertRaises(ValueError):
            t.settle_shared_expense(shared, "Alex", 1, "2026-11-04")

    def test_daily_allowance_reserves_own_unpaid_share(self):
        t = self.tracker
        t.add_income(100, "Wages", "2026-11-01")
        shared = t.track_shared_expenses(60, "Dinner", ["You", "Alex"], paid_by="Alex", date="2026-11-05")
        self.assertEqual(t.calculate_daily_allowance(on_date="2026-11-05", end_date="2026-11-05"), 70)
        t.settle_shared_expense(shared, "You", 30, "2026-11-06")
        self.assertEqual(t.calculate_daily_allowance(on_date="2026-11-06", end_date="2026-11-06"), 70)

    def test_recurring_month_end_leap_year_and_idempotency(self):
        t = self.tracker
        recurring = t.add_recurring_expense(500, "Rent", start_date="2024-01-31")
        posted = t.process_recurring_expenses("2024-03-31")
        self.assertEqual([r["date"] for r in posted], ["2024-01-31", "2024-02-29", "2024-03-31"])
        self.assertTrue(all(r["recurring_id"] == recurring for r in posted))
        self.assertEqual(t.process_recurring_expenses("2024-03-31"), [])
        t.cancel_recurring_expense(recurring)
        self.assertEqual(t.process_recurring_expenses("2024-05-01"), [])
        self.assertEqual(t.get_total_expenses(), 1500)

    def test_recurring_weekly_end_date_and_non_leap_february(self):
        t = self.tracker
        t.add_recurring_expense(5, "Gym", "week", "2026-11-01", end_date="2026-11-08")
        self.assertEqual(len(t.process_recurring_expenses("2026-12-01")), 2)
        t.add_recurring_expense(10, "Phone", start_date="2025-01-31", end_date="2025-03-31")
        rows = t.process_recurring_expenses("2025-03-31")
        self.assertEqual([r["date"] for r in rows], ["2025-01-31", "2025-02-28", "2025-03-31"])
        with self.assertRaises(ValueError):
            t.add_recurring_expense(5, "Bad", start_date="2026-11-05", end_date="2026-11-04")

    def test_savings_progress_and_defensive_copy(self):
        t = self.tracker
        goal = t.create_savings_goal("Emergency fund", 100, "2026-12-31")
        self.assertEqual(t.contribute_to_savings(goal, 25)["progress_percent"], 25)
        progress = t.contribute_to_savings(goal, 100)
        self.assertEqual(progress["saved"], 125)
        self.assertEqual(progress["remaining"], 0)
        self.assertEqual(progress["progress_percent"], 100)
        progress["contributions"].clear()
        self.assertEqual(t.get_savings_progress(goal)["saved"], 125)
        self.assertEqual(t.get_total_expenses(), 0)

    def test_alert_warning_reached_exceeded_and_zero_cap(self):
        t = self.tracker
        t.set_budget(100, category_limits={"Food": 100, "Rent": 0})
        t.add_expense(80, "Food", date="2026-11-05")
        self.assertEqual([r["status"] for r in t.check_budget_alerts(on_date="2026-11-05")], ["warning", "warning"])
        t.add_expense(20, "Food", date="2026-11-05")
        self.assertEqual(t.check_budget_alerts(on_date="2026-11-05")[0]["status"], "reached")
        t.add_expense(1, "Rent", date="2026-11-05")
        alerts = t.check_budget_alerts(on_date="2026-11-05")
        self.assertEqual(alerts[0]["status"], "exceeded")
        self.assertEqual(alerts[-1]["category"], "Rent")
        self.assertEqual(t.check_budget_alerts(on_date="2026-12-05"), [])

    def test_alert_threshold_uses_exact_decimal_comparison(self):
        self.tracker.set_budget(1000)
        self.tracker.add_expense(140, "Food", date="2026-11-05")
        self.assertEqual(len(self.tracker.check_budget_alerts(on_date="2026-11-05", threshold=0.14)), 1)

    def test_monthly_comparison_year_rollover_and_zero_baseline(self):
        t = self.tracker
        t.add_expense(100, "Food", date="2025-12-31")
        t.add_expense(150, "Food", date="2026-01-01")
        comparison = t.get_monthly_comparison("2026-01")
        self.assertEqual(comparison["previous_month"], "2025-12")
        self.assertEqual(comparison["difference"], 50)
        self.assertEqual(comparison["percent_change"], 50)
        self.assertIsNone(comparison["categories"]["Rent"]["percent_change"])
        self.assertEqual(t.get_monthly_comparison("2026-02", "2025-12")["difference"], -100)

    def test_shared_bill_rounding_partial_settlement_and_personal_share(self):
        t = self.tracker
        shared = t.track_shared_expenses(10, "Dinner", ["You", "Alex", "Sam"], date="2026-11-05")
        self.assertEqual(t.shared_expenses[0]["shares"], {"You": 3.34, "Alex": 3.33, "Sam": 3.33})
        self.assertEqual(t.get_total_expenses(), 3.34)
        t.settle_shared_expense(shared, "Alex", 1, "2026-11-06")
        self.assertEqual(t.get_shared_balances(shared)[0]["amount"], 2.33)
        with self.assertRaises(ValueError):
            t.settle_shared_expense(shared, "Alex", 3)
        with self.assertRaises(ValueError):
            t.settle_shared_expense(shared, "You", 1)
        t.settle_shared_expense(shared, "Alex", 2.33, "2026-11-07")
        self.assertEqual(t.get_shared_balances(shared)[0]["amount"], 0)
        self.assertEqual(t.get_total_expenses(), 3.34)

    def test_shared_custom_shares_and_invalid_inputs_are_atomic(self):
        t = self.tracker
        shared = t.track_shared_expenses(30, "Taxi", ["You", "Alex"], "Alex",
                                        shares={"You": 10, "Alex": 20})
        self.assertEqual(t.get_shared_balances(shared)[0]["from"], "You")
        self.assertEqual(t.get_total_expenses(), 10)
        before = deepcopy(t.__dict__)
        for participants, shares in ((["You", "You"], None), (["You", "Alex"], {"You": 1, "Alex": 1})):
            with self.assertRaises(ValueError):
                t.track_shared_expenses(10, "Bad", participants, shares=shares)
            self.assertEqual(t.__dict__, before)

    def test_forecast_uses_zero_days_and_excludes_today_and_future(self):
        t = self.tracker
        t.add_expense(70, "Food", date="2026-11-04")
        t.add_expense(999, "Food", date="2026-11-05")
        t.add_expense(999, "Food", date="2026-12-05")
        prediction = t.predict_future_spending("week", "2026-11-05", lookback_days=7)
        self.assertEqual(prediction["estimated_total"], 70)
        self.assertEqual(prediction["sample_count"], 1)
        self.assertEqual(prediction["history_start"], "2026-10-29")
        self.assertEqual(prediction["end_date"], "2026-11-11")
        self.assertEqual(ExpenseTracker().predict_future_spending()["estimated_total"], 0)
        with self.assertRaises(ValueError):
            t.predict_future_spending(lookback_days=0)

    def test_forecast_calendar_month_at_month_end(self):
        prediction = self.tracker.predict_future_spending("month", "2025-01-31")
        self.assertEqual(prediction["days"], 28)
        self.assertEqual(prediction["end_date"], "2025-02-27")
        prediction = self.tracker.predict_future_spending("month", "2024-01-31")
        self.assertEqual(prediction["days"], 29)

    def test_unusual_spending_uses_prior_category_history(self):
        t = self.tracker
        for day in range(1, 6):
            t.add_expense(10, "Food", date=f"2026-11-{day:02}")
        t.add_expense(100, "Dinner", date="2026-11-06")
        t.add_expense(500, "Rent", date="2026-11-06")
        t.add_expense(1000, "Food", date="2026-12-06")
        unusual = t.detect_unusual_spending("2026-11-06")
        self.assertEqual(len(unusual), 1)
        self.assertEqual(unusual[0]["expense"]["description"], "Dinner")
        self.assertEqual(unusual[0]["baseline_median"], 10)
        self.assertEqual(unusual[0]["threshold"], 20)
        self.assertEqual(t.detect_unusual_spending("2026-11-05"), [])

    def test_suggestions_conserve_budget_pennies_and_do_not_mutate(self):
        t = self.tracker
        t.add_expense(10, "Food", date="2026-11-01")
        t.add_expense(20, "Bus", date="2026-11-01")
        t.set_budget(100.01)
        before = deepcopy(t.budgets)
        suggestion = t.suggest_budget_adjustments(on_date="2026-11-05", lookback_days=30)
        limits = suggestion["category_limits"]
        self.assertEqual(sum(Decimal(str(v)) for v in limits.values()), Decimal("100.01"))
        self.assertGreater(limits["Transport"], limits["Food"])
        self.assertEqual(t.budgets, before)
        t.set_budget(suggestion["suggested_total"], category_limits=limits)
        self.assertIsNone(ExpenseTracker().suggest_budget_adjustments()["suggested_total"])

    def test_csv_roundtrip_quoting_filtering_and_formula_safety(self):
        t = self.tracker
        t.add_expense(10, 'Lunch, "campus"\nwith friends', date="2026-11-05")
        t.add_expense(20, "=HYPERLINK(bad)", date="2026-11-06")
        t.add_expense(30, "Old", date="2026-10-05")
        self.assertEqual(t.export_expenses_csv(self.path, "month", "2026-11-05"), 2)
        with self.path.open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(rows[0]["description"], 'Lunch, "campus"\nwith friends')
        self.assertTrue(rows[1]["description"].startswith("'="))
        self.assertEqual(rows[0]["amount"], "10.00")
        self.assertEqual(t.export_expenses_csv(self.path, report="categories"), 7)

    def populated_tracker(self):
        t = self.tracker
        t.currency = "\u00a3"
        t.add_income(1000, "Student finance", "2026-11-01")
        t.add_expense(5, "Coffee", date="2026-11-05")
        t.set_budget(700, category_limits={"Food": 200})
        t.add_recurring_expense(500, "Rent", start_date="2026-11-01")
        t.process_recurring_expenses("2026-11-05")
        goal = t.create_savings_goal("Laptop", 1000)
        t.contribute_to_savings(goal, 50, "2026-11-05")
        shared = t.track_shared_expenses(20, "Dinner", ["You", "Alex"], date="2026-11-05")
        t.settle_shared_expense(shared, "Alex", 5, "2026-11-05")
        return t

    def test_all_state_roundtrip_and_recurring_no_duplicates_after_load(self):
        t = self.populated_tracker()
        t.save_to_file(self.path)
        restored = ExpenseTracker()
        restored.load_from_file(self.path)
        self.assertEqual(restored.__dict__, t.__dict__)
        self.assertEqual(restored.process_recurring_expenses("2026-11-30"), [])
        self.assertEqual(len(restored.process_recurring_expenses("2026-12-01")), 1)
        self.assertEqual(len(list(self.path.parent.glob("*.tmp"))), 0)

    def test_legacy_json_migration(self):
        self.path.write_text(json.dumps([{"amount": 10, "description": "Groceries"}]), encoding="utf-8")
        self.tracker.load_from_file(self.path)
        self.assertEqual(self.tracker.get_expense(0)["category"], "Food")
        self.assertEqual(self.tracker.get_expense(0)["date"], date.today().isoformat())

    def test_bad_files_never_replace_existing_state(self):
        t = self.populated_tracker()
        before = deepcopy(t.__dict__)
        t.save_to_file(self.path)
        valid = json.loads(self.path.read_text(encoding="utf-8"))
        invalid_cases = [None, {}, [{"amount": -1, "description": "Bad"}]]
        for field, value in (("incomes", [{"amount": -10}]), ("budgets", {"month": {"amount": -1}}),
                             ("savings_goals", [None]), ("shared_expenses", [None])):
            damaged = deepcopy(valid)
            damaged[field] = value
            invalid_cases.append(damaged)
        damaged = deepcopy(valid)
        damaged["recurring_expenses"][0]["next_date"] = "2026-12-02"
        invalid_cases.append(damaged)
        for contents in invalid_cases:
            self.path.write_text(json.dumps(contents), encoding="utf-8")
            with self.subTest(contents=contents), self.assertRaises(ValueError):
                t.load_from_file(self.path)
            self.assertEqual(t.__dict__, before)

    def test_corrupt_required_saved_fields_are_rejected(self):
        t = self.populated_tracker()
        t.save_to_file(self.path)
        before = deepcopy(t.__dict__)
        valid = json.loads(self.path.read_text(encoding="utf-8"))
        for collection, field, value in (("expenses", "date", None), ("expenses", "category", None),
                                         ("incomes", "date", None), ("incomes", "description", False),
                                         ("recurring_expenses", "next_date", None)):
            damaged = deepcopy(valid)
            damaged[collection][0][field] = value
            self.path.write_text(json.dumps(damaged), encoding="utf-8")
            with self.subTest(collection=collection, field=field), self.assertRaises(ValueError):
                t.load_from_file(self.path)
            self.assertEqual(t.__dict__, before)

    def test_failed_save_preserves_previous_file(self):
        t = self.populated_tracker()
        t.save_to_file(self.path)
        before = self.path.read_bytes()
        with patch("ExpenseTracker.json.dump", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                t.save_to_file(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(list(self.path.parent.glob("*.tmp"))), 0)


if __name__ == "__main__":
    unittest.main()
