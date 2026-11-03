-- 0011 - app_settings: configurações por usuário (alvo de guardado, etc.)

CREATE TABLE IF NOT EXISTS app_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES app_users(id) ON DELETE CASCADE,
    setting_key TEXT NOT NULL,
    setting_value TEXT,
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, setting_key)
);

GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
