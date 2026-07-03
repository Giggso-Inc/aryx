-- 0028 — Shay-as-skin shared schema on the Aryx Postgres.
--
-- Aryx remains the source of truth for partitioned ingest / graph data.
-- Shay adds auth, company, workspace, membership, app connection, datasource,
-- and chat-facing metadata on the same PostgreSQL database.

CREATE TABLE IF NOT EXISTS gg_company (
    id                  UUID PRIMARY KEY,
    name                VARCHAR(255) NOT NULL,
    domain              VARCHAR(255) UNIQUE,
    description         TEXT,
    website_url         VARCHAR(500),
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    settings            JSONB,
    subscription_plan   VARCHAR(50) NOT NULL DEFAULT 'free',
    max_users           VARCHAR(10) NOT NULL DEFAULT '10',
    max_workspaces      VARCHAR(10) NOT NULL DEFAULT '5',
    max_storage_gb      VARCHAR(10) NOT NULL DEFAULT '1',
    ai_enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    ai_provider         VARCHAR(50) NOT NULL DEFAULT 'openai',
    ai_webhook_url      VARCHAR(500),
    created_by          UUID,
    updated_by          UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gg_company_name ON gg_company(name);
CREATE INDEX IF NOT EXISTS idx_gg_company_domain ON gg_company(domain);

CREATE TABLE IF NOT EXISTS gg_users (
    id                  UUID PRIMARY KEY,
    name                VARCHAR(255),
    email_id            VARCHAR(255) UNIQUE,
    avatar_url          VARCHAR(500),
    company_id          UUID REFERENCES gg_company(id) ON DELETE SET NULL,
    role                VARCHAR(50) NOT NULL DEFAULT 'user',
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    is_verified         BOOLEAN NOT NULL DEFAULT FALSE,
    google_id           VARCHAR(255) UNIQUE,
    oauth_provider      VARCHAR(50) NOT NULL DEFAULT 'local',
    preferences         JSONB,
    last_login          TIMESTAMPTZ,
    created_datetime    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_datetime    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    password_hash       TEXT
);

CREATE INDEX IF NOT EXISTS idx_gg_users_company ON gg_users(company_id);
CREATE INDEX IF NOT EXISTS idx_gg_users_email ON gg_users(email_id);

CREATE TABLE IF NOT EXISTS subscription_plans (
    id                  UUID PRIMARY KEY,
    name                VARCHAR(255) NOT NULL,
    plan_code           VARCHAR(50) NOT NULL UNIQUE,
    description         TEXT,
    monthly_price       NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    plan_cycles         INTEGER NOT NULL DEFAULT 1,
    interval            INTEGER NOT NULL DEFAULT 1,
    interval_unit       VARCHAR(20) NOT NULL DEFAULT 'month',
    interval_count      INTEGER NOT NULL DEFAULT 1,
    features            JSONB,
    sort_order          INTEGER NOT NULL DEFAULT 0,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    zoho_plan_id        VARCHAR(255),
    zoho_product_id     VARCHAR(255),
    zoho_plan_code      VARCHAR(255),
    zoho_product_code   VARCHAR(255),
    zoho_billing_cycle  VARCHAR(50),
    platform_name       VARCHAR(50),
    created_by          UUID,
    updated_by          INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_subscription_plans_active ON subscription_plans(is_active);
CREATE INDEX IF NOT EXISTS idx_subscription_plans_platform_name ON subscription_plans(platform_name);

INSERT INTO subscription_plans (
    id, name, plan_code, description, monthly_price, plan_cycles, interval,
    interval_unit, interval_count, features, sort_order, is_active, platform_name
) VALUES (
    '00000000-0000-0000-0000-000000000001',
    'Free',
    'free',
    'Default free plan for Shay workspace onboarding',
    0.00,
    1,
    1,
    'month',
    1,
    '{"users":10,"workspaces":5}'::jsonb,
    0,
    TRUE,
    'aryx'
)
ON CONFLICT (plan_code) DO NOTHING;

CREATE TABLE IF NOT EXISTS subscriptions (
    id                          UUID PRIMARY KEY,
    company_id                  UUID NOT NULL REFERENCES gg_company(id) ON DELETE CASCADE,
    plan_id                     UUID NOT NULL REFERENCES subscription_plans(id) ON DELETE RESTRICT,
    status                      VARCHAR(50) NOT NULL DEFAULT 'active',
    subscription_status         VARCHAR(50) NOT NULL DEFAULT 'active',
    amount                      NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    currency_code               VARCHAR(3) NOT NULL DEFAULT 'USD',
    billing_cycle               VARCHAR(50) NOT NULL DEFAULT 'monthly',
    auto_collect                BOOLEAN NOT NULL DEFAULT TRUE,
    current_period_start        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    current_period_end          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    next_billing_date           TIMESTAMPTZ,
    zoho_trial_end              TIMESTAMPTZ,
    zoho_cancel_at_period_end   BOOLEAN NOT NULL DEFAULT FALSE,
    usage_limits                JSONB,
    zoho_subscription_id        VARCHAR(255) UNIQUE,
    zoho_customer_id            VARCHAR(255),
    zoho_hosted_page_id         VARCHAR(255),
    zoho_invoice_id             VARCHAR(255),
    zoho_payment_id             VARCHAR(255),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at                  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_company ON subscriptions(company_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_plan ON subscriptions(plan_id);

CREATE TABLE IF NOT EXISTS gg_workspace (
    id                  UUID PRIMARY KEY,
    name                VARCHAR(255) NOT NULL,
    description         TEXT,
    company_id          UUID NOT NULL REFERENCES gg_company(id) ON DELETE CASCADE,
    user_id             UUID REFERENCES gg_users(id) ON DELETE SET NULL,
    created_by          UUID REFERENCES gg_users(id) ON DELETE SET NULL,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    is_public           BOOLEAN NOT NULL DEFAULT FALSE,
    settings            JSONB,
    ai_enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    ai_provider         VARCHAR(50) NOT NULL DEFAULT 'openai',
    ai_model            VARCHAR(100) NOT NULL DEFAULT 'gpt-4',
    ai_webhook_url      VARCHAR(500),
    workspace_type      VARCHAR(50),
    max_messages        VARCHAR(10) NOT NULL DEFAULT '1000',
    max_attachments     VARCHAR(10) NOT NULL DEFAULT '100',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gg_workspace_company ON gg_workspace(company_id);
CREATE INDEX IF NOT EXISTS idx_gg_workspace_company_user ON gg_workspace(company_id, user_id);

CREATE TABLE IF NOT EXISTS gg_channels (
    id                  UUID PRIMARY KEY,
    name                VARCHAR(255) NOT NULL,
    description         TEXT,
    channel_tags        JSONB,
    channel_sub_tags    JSONB,
    workspace_id        UUID NOT NULL REFERENCES gg_workspace(id) ON DELETE CASCADE,
    company_id          UUID REFERENCES gg_company(id) ON DELETE CASCADE,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    is_public           BOOLEAN NOT NULL DEFAULT FALSE,
    is_archived         BOOLEAN NOT NULL DEFAULT FALSE,
    channel_type        INTEGER NOT NULL DEFAULT 1,
    channel_settings    JSONB,
    message_count       INTEGER NOT NULL DEFAULT 0,
    last_message_at     TIMESTAMPTZ,
    ai_enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    created_by          UUID REFERENCES gg_users(id) ON DELETE SET NULL,
    updated_by          UUID REFERENCES gg_users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (name, workspace_id)
);

CREATE INDEX IF NOT EXISTS idx_gg_channels_workspace ON gg_channels(workspace_id);
CREATE INDEX IF NOT EXISTS idx_gg_channels_company ON gg_channels(company_id);

CREATE TABLE IF NOT EXISTS gg_threads (
    id                  UUID PRIMARY KEY,
    title               VARCHAR(255),
    description         TEXT,
    channel_id          UUID NOT NULL REFERENCES gg_channels(id) ON DELETE CASCADE,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    is_archived         BOOLEAN NOT NULL DEFAULT FALSE,
    message_count       INTEGER NOT NULL DEFAULT 0,
    last_message_at     TIMESTAMPTZ,
    ai_enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    ai_summary          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gg_threads_channel ON gg_threads(channel_id);

CREATE TABLE IF NOT EXISTS gg_messages (
    id                  UUID PRIMARY KEY,
    content             TEXT NOT NULL,
    message_type        VARCHAR(50) NOT NULL DEFAULT 'user',
    response_text       TEXT,
    thread_id           UUID NOT NULL REFERENCES gg_threads(id) ON DELETE CASCADE,
    user_id             UUID REFERENCES gg_users(id) ON DELETE SET NULL,
    query_id            UUID,
    is_ai_processed     BOOLEAN NOT NULL DEFAULT FALSE,
    ai_provider         VARCHAR(50),
    ai_model            VARCHAR(100),
    ai_processing_time  INTEGER,
    is_visible          BOOLEAN NOT NULL DEFAULT TRUE,
    is_pinned           BOOLEAN NOT NULL DEFAULT FALSE,
    sequence_number     INTEGER NOT NULL DEFAULT 0,
    message_metadata    JSONB,
    citations           JSONB,
    usage_metrics       JSONB,
    attachment_ids      JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gg_messages_thread ON gg_messages(thread_id, created_at);

CREATE TABLE IF NOT EXISTS gg_channel_members (
    id                  UUID PRIMARY KEY,
    channel_id          UUID NOT NULL REFERENCES gg_channels(id) ON DELETE CASCADE,
    user_id             UUID NOT NULL REFERENCES gg_users(id) ON DELETE CASCADE,
    role                VARCHAR(50) NOT NULL DEFAULT 'member',
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    permissions         JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_channel_user_membership UNIQUE (channel_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_gg_channel_members_user ON gg_channel_members(user_id);

CREATE TABLE IF NOT EXISTS gg_members (
    id                  UUID PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES gg_users(id) ON DELETE CASCADE,
    workspace_id        UUID REFERENCES gg_workspace(id) ON DELETE CASCADE,
    channel_id          UUID REFERENCES gg_channels(id) ON DELETE CASCADE,
    thread_id           UUID REFERENCES gg_threads(id) ON DELETE CASCADE,
    level               VARCHAR(20) NOT NULL,
    role                VARCHAR(50) NOT NULL DEFAULT 'member',
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    permissions         JSONB,
    invited_by          UUID REFERENCES gg_users(id) ON DELETE SET NULL,
    joined_at           TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_gg_members_exclusive_arc CHECK (
        (level = 'workspace' AND workspace_id IS NOT NULL AND channel_id IS NULL AND thread_id IS NULL) OR
        (level = 'channel'   AND channel_id   IS NOT NULL AND workspace_id IS NULL AND thread_id IS NULL) OR
        (level = 'thread'    AND thread_id    IS NOT NULL AND workspace_id IS NULL AND channel_id IS NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_gg_members_workspace ON gg_members(workspace_id, user_id) WHERE level = 'workspace';
CREATE UNIQUE INDEX IF NOT EXISTS uk_gg_members_channel ON gg_members(channel_id, user_id) WHERE level = 'channel';
CREATE UNIQUE INDEX IF NOT EXISTS uk_gg_members_thread ON gg_members(thread_id, user_id) WHERE level = 'thread';

CREATE TABLE IF NOT EXISTS gg_apps (
    id                  UUID PRIMARY KEY,
    app_name            VARCHAR(255) NOT NULL,
    app_key             VARCHAR(100) NOT NULL UNIQUE,
    app_description     TEXT,
    app_image           VARCHAR(500),
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    is_public           BOOLEAN NOT NULL DEFAULT TRUE,
    settings            JSONB,
    version             VARCHAR(50),
    category            VARCHAR(100),
    tags                JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS gg_app_connections (
    id                  UUID PRIMARY KEY,
    app_id              UUID REFERENCES gg_apps(id) ON DELETE SET NULL,
    workspace_id        UUID REFERENCES gg_workspace(id) ON DELETE CASCADE,
    channel_id          UUID REFERENCES gg_channels(id) ON DELETE CASCADE,
    thread_id           UUID REFERENCES gg_threads(id) ON DELETE CASCADE,
    level               VARCHAR(20) NOT NULL,
    connected_by        UUID NOT NULL REFERENCES gg_users(id) ON DELETE CASCADE,
    connection_name     VARCHAR(255),
    connection_status   VARCHAR(50) NOT NULL DEFAULT 'active',
    connection_settings JSONB,
    api_key             VARCHAR(500),
    webhook_url         VARCHAR(500),
    callback_url        VARCHAR(500),
    last_sync_at        TIMESTAMPTZ,
    sync_status         VARCHAR(50),
    error_message       TEXT,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    auto_sync           BOOLEAN NOT NULL DEFAULT FALSE,
    sync_interval       INTEGER NOT NULL DEFAULT 3600,
    provider            VARCHAR(50),
    provider_account_id VARCHAR(255),
    auth_type           VARCHAR(50) DEFAULT 'oauth2',
    provider_metadata   JSONB,
    last_token_refresh  TIMESTAMPTZ,
    token_expires_at    TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_gg_app_connections_exclusive_arc CHECK (
        (level = 'workspace' AND workspace_id IS NOT NULL AND channel_id IS NULL AND thread_id IS NULL) OR
        (level = 'channel'   AND channel_id   IS NOT NULL AND workspace_id IS NULL AND thread_id IS NULL) OR
        (level = 'thread'    AND thread_id    IS NOT NULL AND workspace_id IS NULL AND channel_id IS NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_gg_app_connections_workspace ON gg_app_connections(workspace_id, app_id) WHERE level = 'workspace';
CREATE UNIQUE INDEX IF NOT EXISTS uk_gg_app_connections_channel ON gg_app_connections(channel_id, app_id) WHERE level = 'channel';
CREATE UNIQUE INDEX IF NOT EXISTS uk_gg_app_connections_thread ON gg_app_connections(thread_id, app_id) WHERE level = 'thread';

CREATE TABLE IF NOT EXISTS gg_vault (
    giggso_vault_id     UUID PRIMARY KEY,
    user_id             UUID,
    vault_label         VARCHAR(50),
    vault_unique_id     VARCHAR(255) UNIQUE,
    created_datetime    TIMESTAMPTZ DEFAULT NOW(),
    created_by          UUID,
    updated_datetime    TIMESTAMPTZ DEFAULT NOW(),
    updated_by          UUID,
    company_id          UUID,
    vault_type          VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS gg_invitations (
    id                  UUID PRIMARY KEY,
    email               VARCHAR(255) NOT NULL,
    role                VARCHAR(50) NOT NULL DEFAULT 'user',
    company_id          UUID NOT NULL REFERENCES gg_company(id) ON DELETE CASCADE,
    invited_by          UUID NOT NULL REFERENCES gg_users(id) ON DELETE CASCADE,
    status              VARCHAR(20) NOT NULL DEFAULT 'pending',
    message             TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gg_invitations_company ON gg_invitations(company_id);
CREATE INDEX IF NOT EXISTS idx_gg_invitations_email ON gg_invitations(email);

CREATE TABLE IF NOT EXISTS gg_email_verification_tokens (
    id                  UUID PRIMARY KEY,
    email               VARCHAR(255) NOT NULL,
    token               VARCHAR(255) NOT NULL UNIQUE,
    token_type          VARCHAR(50) NOT NULL DEFAULT 'company_signup',
    company_id          UUID REFERENCES gg_company(id) ON DELETE CASCADE,
    user_id             UUID REFERENCES gg_users(id) ON DELETE CASCADE,
    expires_at          TIMESTAMPTZ NOT NULL,
    used_at             TIMESTAMPTZ,
    is_used             BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gg_email_verification_tokens_email ON gg_email_verification_tokens(email, token_type, is_used);

-- Legacy channel-scoped datasource table used by older Shay routes.
CREATE TABLE IF NOT EXISTS gg_datasources (
    id                      UUID PRIMARY KEY,
    name                    VARCHAR(255) NOT NULL,
    filename                VARCHAR(500) NOT NULL,
    storage_type            VARCHAR(50) NOT NULL,
    provider                VARCHAR(100),
    app_type                VARCHAR(100),
    config                  JSONB,
    datasource_metadata     JSONB,
    giggso_vault_id         UUID,
    file_size               INTEGER,
    file_type               VARCHAR(255),
    file_url                VARCHAR(1000),
    log_type                VARCHAR(100),
    channel_id              UUID NOT NULL REFERENCES gg_channels(id) ON DELETE CASCADE,
    added_by                UUID NOT NULL REFERENCES gg_users(id) ON DELETE CASCADE,
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    is_connected            BOOLEAN NOT NULL DEFAULT TRUE,
    is_processed            BOOLEAN NOT NULL DEFAULT FALSE,
    processing_status       VARCHAR(50) NOT NULL DEFAULT 'pending',
    error_message           TEXT,
    is_embedding_required   BOOLEAN NOT NULL DEFAULT FALSE,
    embedding_status        INTEGER NOT NULL DEFAULT 0,
    last_processed_at       TIMESTAMPTZ,
    processing_time         INTEGER,
    record_count            INTEGER NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gg_datasources_channel ON gg_datasources(channel_id);

-- Unified datasource table used by the new GG datasource routes.
CREATE TABLE IF NOT EXISTS datasources (
    id                      UUID PRIMARY KEY,
    workspace_id            UUID REFERENCES gg_workspace(id) ON DELETE CASCADE,
    channel_id              UUID REFERENCES gg_channels(id) ON DELETE CASCADE,
    thread_id               UUID REFERENCES gg_threads(id) ON DELETE CASCADE,
    message_id              UUID REFERENCES gg_messages(id) ON DELETE CASCADE,
    level                   VARCHAR(20) NOT NULL,
    added_by                UUID REFERENCES gg_users(id) ON DELETE SET NULL,
    name                    VARCHAR(255) NOT NULL,
    filename                VARCHAR(500),
    storage_type            VARCHAR(50) NOT NULL,
    provider                VARCHAR(100),
    app_type                VARCHAR(100),
    config                  JSONB,
    datasource_metadata     JSONB,
    vault_unique_id         UUID,
    file_size               INTEGER,
    file_type               VARCHAR(255),
    file_url                VARCHAR(1000),
    log_type                VARCHAR(100),
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    is_connected            BOOLEAN NOT NULL DEFAULT TRUE,
    is_processed            BOOLEAN NOT NULL DEFAULT FALSE,
    processing_status       VARCHAR(50) NOT NULL DEFAULT 'pending',
    error_message           TEXT,
    is_embedding_required   BOOLEAN NOT NULL DEFAULT FALSE,
    embedding_status        INTEGER NOT NULL DEFAULT 0,
    last_processed_at       TIMESTAMPTZ,
    processing_time         INTEGER,
    record_count            INTEGER NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_datasources_exclusive_arc CHECK (
        (level = 'workspace' AND workspace_id IS NOT NULL AND channel_id IS NULL AND thread_id IS NULL AND message_id IS NULL) OR
        (level = 'channel'   AND channel_id   IS NOT NULL AND workspace_id IS NULL AND thread_id IS NULL AND message_id IS NULL) OR
        (level = 'thread'    AND thread_id    IS NOT NULL AND workspace_id IS NULL AND channel_id IS NULL AND message_id IS NULL) OR
        (level = 'message'   AND message_id   IS NOT NULL AND workspace_id IS NULL AND channel_id IS NULL AND thread_id IS NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_datasources_workspace ON datasources(workspace_id, name) WHERE level = 'workspace';
CREATE UNIQUE INDEX IF NOT EXISTS uk_datasources_channel ON datasources(channel_id, name) WHERE level = 'channel';
CREATE UNIQUE INDEX IF NOT EXISTS uk_datasources_thread ON datasources(thread_id, name) WHERE level = 'thread';
CREATE UNIQUE INDEX IF NOT EXISTS uk_datasources_message ON datasources(message_id, name) WHERE level = 'message';

CREATE TABLE IF NOT EXISTS aryx_shay_workspace_map (
    shay_workspace_id       UUID PRIMARY KEY,
    aryx_workspace_id       BIGINT NOT NULL UNIQUE REFERENCES aryx_workspace(id) ON DELETE CASCADE,
    company_id              UUID,
    sync_state              JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS aryx_shay_datasource_map (
    shay_datasource_id      UUID PRIMARY KEY,
    aryx_datasource_id      BIGINT NOT NULL UNIQUE REFERENCES aryx_datasource(id) ON DELETE CASCADE,
    shay_workspace_id       UUID NOT NULL REFERENCES gg_workspace(id) ON DELETE CASCADE,
    aryx_workspace_id       BIGINT NOT NULL REFERENCES aryx_workspace(id) ON DELETE CASCADE,
    ingest_job_id           TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_aryx_shay_datasource_map_workspace ON aryx_shay_datasource_map(shay_workspace_id, aryx_workspace_id);

CREATE TABLE IF NOT EXISTS aryx_shay_chat_map (
    shay_thread_id          UUID PRIMARY KEY,
    aryx_workspace_id       BIGINT NOT NULL REFERENCES aryx_workspace(id) ON DELETE CASCADE,
    shay_workspace_id       UUID NOT NULL REFERENCES gg_workspace(id) ON DELETE CASCADE,
    ask_session_key         TEXT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS aryx_shay_chat_turn (
    id                      BIGSERIAL PRIMARY KEY,
    shay_thread_id          UUID NOT NULL REFERENCES aryx_shay_chat_map(shay_thread_id) ON DELETE CASCADE,
    aryx_workspace_id       BIGINT NOT NULL REFERENCES aryx_workspace(id) ON DELETE CASCADE,
    question                TEXT NOT NULL,
    answer                  TEXT NOT NULL,
    citations               JSONB NOT NULL DEFAULT '[]'::jsonb,
    usage                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    grounding               JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_aryx_shay_chat_turn_thread ON aryx_shay_chat_turn(shay_thread_id, created_at);
