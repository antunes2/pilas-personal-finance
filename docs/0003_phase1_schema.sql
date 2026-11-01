-- Phase 1: Banco e registros básicos - Schema Migration
-- Run this in Supabase SQL Editor

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS uuid;

-- app_users: Two authorized Telegram users
CREATE TABLE IF NOT EXISTS app_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_user_id BIGINT UNIQUE NOT NULL,
    display_name TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- categories: 16 predefined categories (13 expenses + 3 incomes)
CREATE TABLE IF NOT EXISTS categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    transaction_type TEXT NOT NULL CHECK (transaction_type IN ('EXPENSE', 'INCOME')),
    parent_id UUID REFERENCES categories(id),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Seed categories (run after table creation)
INSERT INTO categories (name, transaction_type) VALUES
('Alimentacao', 'EXPENSE'),
('Cuidados Pessoais', 'EXPENSE'),
('Eletronicos', 'EXPENSE'),
('Esporte Saude', 'EXPENSE'),
('Gastos Casa', 'EXPENSE'),
('Lazer', 'EXPENSE'),
('Pet', 'EXPENSE'),
('Presentes', 'EXPENSE'),
('Remedios', 'EXPENSE'),
('Roles', 'EXPENSE'),
('Roupas', 'EXPENSE'),
('Transporte', 'EXPENSE'),
('Viagem', 'EXPENSE'),
('Outros', 'EXPENSE'),
('Salario', 'INCOME'),
('Beneficio', 'INCOME'),
('Reembolso', 'INCOME'),
('Outras Entradas', 'INCOME')
ON CONFLICT (name, transaction_type) DO NOTHING;

-- payment_instruments: Cards, Pix, cash, benefits
CREATE TABLE IF NOT EXISTS payment_instruments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id UUID REFERENCES app_users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    institution TEXT,
    instrument_type TEXT NOT NULL DEFAULT 'OTHER',
    card_last_four TEXT,
    closing_day SMALLINT,
    due_day SMALLINT,
    is_shared BOOLEAN DEFAULT false,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- transactions: Core expense/income records
CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES app_users(id) ON DELETE CASCADE,
    category_id UUID REFERENCES categories(id),
    payment_instrument_id UUID REFERENCES payment_instruments(id),
    type TEXT NOT NULL CHECK (type IN ('EXPENSE', 'INCOME', 'TRANSFER', 'REFUND')),
    scope TEXT NOT NULL DEFAULT 'PERSONAL' CHECK (scope IN ('PERSONAL', 'SHARED')),
    amount NUMERIC(14,2) NOT NULL,
    description TEXT,
    transaction_date DATE NOT NULL,
    competence_month DATE,
    payment_status TEXT,
    source TEXT NOT NULL DEFAULT 'TELEGRAM' CHECK (source IN ('TELEGRAM', 'CSV_IMPORT', 'MANUAL')),
    external_reference TEXT,
    telegram_update_id BIGINT UNIQUE,
    ai_category_confidence NUMERIC,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- income_profiles: Salary and benefits per user
CREATE TABLE IF NOT EXISTS income_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES app_users(id) ON DELETE CASCADE,
    gross_monthly_salary NUMERIC(14,2),
    reference_net_salary NUMERIC(14,2),
    pay_day SMALLINT,
    employment_type TEXT,
    tax_dependents SMALLINT DEFAULT 0,
    other_monthly_deductions NUMERIC(14,2) DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);