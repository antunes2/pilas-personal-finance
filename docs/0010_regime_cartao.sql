-- 0010 - Regime cartão: pagamento de fatura NÃO é despesa (é saída de caixa).
-- Compras no crédito contam na data da compra; quando você "paga a fatura",
-- o registro sai do eixo caixa sem somar em despesas (evita contagem dupla).

ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS is_card_invoice_payment BOOLEAN DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_transactions_invoice_payment
    ON transactions(is_card_invoice_payment)
    WHERE is_card_invoice_payment IS TRUE;

GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
