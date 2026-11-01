-- Phase 3: Renda, benefícios e custos fixos - Schema Migration
-- Run this in Supabase SQL Editor after Phase 1 schema

-- benefit_rules: Regras de benefícios (VR, VA, etc.)
CREATE TABLE IF NOT EXISTS benefit_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES app_users(id) ON DELETE CASCADE,
    benefit_type TEXT NOT NULL CHECK (benefit_type IN ('MEAL', 'FOOD', 'TRANSPORT', 'OTHER')),
    calculation_type TEXT NOT NULL CHECK (calculation_type IN ('DAILY_WORKDAY', 'FIXED_MONTHLY')),
    daily_amount NUMERIC(14,2),
    monthly_amount NUMERIC(14,2),
    credit_day SMALLINT,
    policy_notes TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- recurring_expenses: Despesas recorrentes/fixas
CREATE TABLE IF NOT EXISTS recurring_expenses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id UUID REFERENCES app_users(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    category_id UUID REFERENCES categories(id),
    expected_amount NUMERIC(14,2) NOT NULL,
    frequency TEXT NOT NULL DEFAULT 'monthly' CHECK (frequency IN ('weekly', 'monthly', 'annual', 'personalized')),
    due_day SMALLINT,
    scope TEXT NOT NULL DEFAULT 'PERSONAL' CHECK (scope IN ('PERSONAL', 'SHARED')),
    payment_instrument_id UUID REFERENCES payment_instruments(id),
    start_date DATE NOT NULL,
    end_date DATE,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- recurring_expense_occurrences: Ocorrências mensais de despesas recorrentes
CREATE TABLE IF NOT EXISTS recurring_expense_occurrences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recurring_expense_id UUID REFERENCES recurring_expenses(id) ON DELETE CASCADE,
    period_month DATE NOT NULL,
    expected_amount NUMERIC(14,2) NOT NULL,
    actual_amount NUMERIC(14,2),
    due_date DATE,
    status TEXT NOT NULL DEFAULT 'EXPECTED' CHECK (status IN ('EXPECTED', 'PAID', 'OVERDUE', 'CANCELLED')),
    transaction_id UUID REFERENCES transactions(id),
    UNIQUE (recurring_expense_id, period_month)
);

-- receivables: Contas a receber ("me devem")
CREATE TABLE IF NOT EXISTS receivables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    creditor_user_id UUID REFERENCES app_users(id) ON DELETE CASCADE,
    debtor_name TEXT NOT NULL,
    description TEXT,
    original_amount NUMERIC(14,2) NOT NULL,
    received_amount NUMERIC(14,2) DEFAULT 0,
    created_date DATE NOT NULL,
    expected_date DATE,
    scope TEXT NOT NULL DEFAULT 'PERSONAL' CHECK (scope IN ('PERSONAL', 'SHARED')),
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'PARTIAL', 'PAID', 'CANCELLED')),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- receivable_payments: Pagamentos de contas a receber
CREATE TABLE IF NOT EXISTS receivable_payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    receivable_id UUID REFERENCES receivables(id) ON DELETE CASCADE,
    amount NUMERIC(14,2) NOT NULL,
    received_date DATE NOT NULL,
    transaction_id UUID REFERENCES transactions(id),
    UNIQUE (receivable_id, amount, received_date)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_benefit_rules_user_id ON benefit_rules(user_id);
CREATE INDEX IF NOT EXISTS idx_recurring_expenses_owner_id ON recurring_expenses(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_recurring_expenses_due_day ON recurring_expenses(due_day);
CREATE INDEX IF NOT EXISTS idx_recurring_expenses_active ON recurring_expenses(is_active);
CREATE INDEX IF NOT EXISTS idx_recurring_occurrences_expense_id ON recurring_expense_occurrences(recurring_expense_id);
CREATE INDEX IF NOT EXISTS idx_recurring_occurrences_status ON recurring_expense_occurrences(status);
CREATE INDEX IF NOT EXISTS idx_receivables_creditor ON receivables(creditor_user_id);
CREATE INDEX IF NOT EXISTS idx_receivables_debtor ON receivables(debtor_name);
CREATE INDEX IF NOT EXISTS idx_receivables_status ON receivables(status);
CREATE INDEX IF NOT EXISTS idx_receivable_payments_receivable_id ON receivable_payments(receivable_id);
-- Grant privileges to service_role (bot uses service_role key)
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
