
---
name: financial-logic
description: Financial domain rules for Fluxo. Use whenever implementing or modifying transactions, income, expenses, credit cards, recurring expenses, receivables, balances, budgets or financial reports.
---

# Financial Logic - Fluxo

## 1. General Principles

- Financial calculations must be deterministic.
- Never use an LLM to calculate balances, totals, percentages or projections.
- Use Python Decimal for monetary calculations.
- Store monetary values using PostgreSQL NUMERIC, never floating-point types.
- Distinguish actual, projected and uncertain values.

## 2. Transactions

- Every transaction must have a date, amount, type and category.
- Income and expenses must be distinguishable.
- Support multiple payment instruments and banks.
- Preserve the original transaction description.
- AI categorization must use predefined categories.
- AI-generated classifications must be validated before persistence.

## 3. Credit Cards

- A credit card purchase is an expense.
- Paying the credit card bill is a liability settlement, not a new expense.
- Never count both the purchase and its bill payment as expenses.
- Refunds and reversals must be represented explicitly.

## 4. Income and Benefits

- Distinguish gross salary from estimated net salary.
- Net salary estimates must use explicit and versioned tax rules.
- Actual received salary overrides estimates.
- Meal vouchers and other restricted benefits must not be treated as unrestricted cash.
- Avoid assuming that every benefit is paid in cash.

## 5. Recurring Expenses

- Recurring expenses represent expected future obligations.
- A recurring expense must not be counted as paid until confirmed.
- Each occurrence must have its own status.
- Avoid duplicating an expense when a user manually registers a payment for an existing occurrence.

## 6. Receivables

- Money owed by another person is not available cash.
- Track outstanding amounts separately.
- Support partial payments.
- Only confirmed payments increase actual available cash.

## 7. Budget and Projections

Always distinguish:

- Actual balance
- Expected income
- Expected expenses
- Outstanding receivables
- Restricted benefits
- Projected end-of-month balance

Never double-count:
- Credit card purchases and bill payments.
- Recurring expenses and their manually registered payments.
- Income already received and expected income.

Document the assumptions used in projections.

## 8. Testing Requirements

For every financial feature, test:

- Normal scenarios.
- Zero and negative values where applicable.
- Duplicate transactions.
- Partial payments.
- Missing or invalid data.
- Date and month boundaries.
- Cases where actual and projected values differ.

When modifying financial logic, check whether existing reports and calculations are affected.
