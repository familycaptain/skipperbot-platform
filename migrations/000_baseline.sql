-- =============================================================================
-- Skipperbot Platform — 000_baseline.sql
-- =============================================================================
-- Single baseline migration. Replaces the 67 historical numbered migrations
-- from pre-public development.
--
-- Contains only PLATFORM-INFRASTRUCTURE tables in the public schema.
-- App-owned tables (recipes, goals, lists, schedules, reminders, etc.) live
-- in their respective app_<id> schemas and are created by each app's own
-- migrations under apps/<id>/migrations/ when the app is loaded.
--
-- Generated from a pg_dump --schema-only of a working production-state
-- database (with app-migrated tables filtered out), plus seed inserts for:
--   - 11 platform-owned entity_type rows
--   - 4 platform-level thinking_domain rows
--   - default scope='platform' app_config rows
--
-- This file is idempotent — every CREATE uses IF NOT EXISTS where supported.
-- Re-running against an already-baseline'd database is a no-op.
--
-- PRE-REQUIREMENT: the pgvector extension must already be installed in
-- the target database. This is a superuser action and is documented as
-- step 3 of docs/01-base-platform-setup.md:
--     psql -d skipperbot -c 'CREATE EXTENSION vector;'
-- The baseline does NOT include CREATE EXTENSION because non-superuser
-- DB roles (like skipperbot_user) can't run it. Native + Docker setup
-- paths both ensure the extension exists before this migration runs.

--
-- PostgreSQL database dump
--



SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_table_access_method = heap;

--
-- Name: app_event_deliveries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.app_event_deliveries (
    event_id text NOT NULL,
    subscriber text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    last_attempt timestamp with time zone,
    error text DEFAULT ''::text NOT NULL,
    CONSTRAINT app_event_deliveries_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'delivered'::text, 'failed'::text])))
);


--
-- Name: app_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.app_events (
    id text NOT NULL,
    event_type text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    emitted_by text NOT NULL,
    emitted_at timestamp with time zone DEFAULT now() NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    CONSTRAINT app_events_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'dispatched'::text, 'completed'::text])))
);


--
-- Name: app_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.app_migrations (
    app_id text NOT NULL,
    filename text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL,
    checksum text DEFAULT ''::text NOT NULL
);


--
-- Name: app_registry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.app_registry (
    app_id text NOT NULL,
    version text DEFAULT '0.0.0'::text NOT NULL,
    installed_at timestamp with time zone DEFAULT now() NOT NULL,
    installed_by text DEFAULT 'human'::text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    safety_tier text DEFAULT 'core'::text NOT NULL,
    manifest jsonb DEFAULT '{}'::jsonb NOT NULL,
    error_message text DEFAULT ''::text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT app_registry_safety_tier_check CHECK ((safety_tier = ANY (ARRAY['core'::text, 'verified'::text, 'sandbox'::text]))),
    CONSTRAINT app_registry_status_check CHECK ((status = ANY (ARRAY['active'::text, 'disabled'::text, 'error'::text, 'uninstalled'::text])))
);


--
-- Name: artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.artifacts (
    id text NOT NULL,
    name text NOT NULL,
    mime_type text DEFAULT ''::text NOT NULL,
    size_bytes integer DEFAULT 0 NOT NULL,
    content text DEFAULT ''::text NOT NULL,
    file_data bytea,
    related_entity_id text DEFAULT ''::text NOT NULL,
    tags text[] DEFAULT '{}'::text[] NOT NULL,
    created_by text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: chat_turns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.chat_turns (
    id text NOT NULL,
    user_id text NOT NULL,
    user_message text NOT NULL,
    assistant_message text DEFAULT ''::text NOT NULL,
    embedding public.vector(1536),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    system_prompt text,
    selected_tools jsonb,
    matched_guides jsonb
);


--
-- Name: entity_types; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.entity_types (
    prefix text NOT NULL,
    name text NOT NULL,
    id_format text NOT NULL,
    table_name text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: images; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.images (
    id text NOT NULL,
    title text DEFAULT ''::text NOT NULL,
    filename text NOT NULL,
    mime_type text DEFAULT 'image/jpeg'::text NOT NULL,
    size_bytes integer DEFAULT 0 NOT NULL,
    storage_path text NOT NULL,
    uploaded_by text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: job_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.job_logs (
    id bigint NOT NULL,
    job_id text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    level text DEFAULT 'INFO'::text NOT NULL,
    message text DEFAULT ''::text NOT NULL
);


--
-- Name: job_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE IF NOT EXISTS public.job_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: job_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.job_logs_id_seq OWNED BY public.job_logs.id;


--
-- Name: jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.jobs (
    id text NOT NULL,
    name text NOT NULL,
    job_type text DEFAULT 'shell'::text NOT NULL,
    command text DEFAULT ''::text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    scheduled_for text DEFAULT ''::text NOT NULL,
    notify_user text DEFAULT ''::text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    created_by text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_run_at timestamp with time zone,
    last_result text DEFAULT ''::text NOT NULL,
    run_count integer DEFAULT 0 NOT NULL,
    progress text DEFAULT ''::text NOT NULL,
    cancelled boolean DEFAULT false NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    output jsonb DEFAULT '{}'::jsonb NOT NULL,
    progress_pct integer DEFAULT 0 NOT NULL,
    schedule_expr jsonb DEFAULT '{}'::jsonb NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    claimed_by text DEFAULT ''::text NOT NULL,
    max_retries integer DEFAULT 0 NOT NULL,
    retry_count integer DEFAULT 0 NOT NULL,
    parent_job_id text DEFAULT ''::text NOT NULL,
    error text DEFAULT ''::text NOT NULL,
    CONSTRAINT jobs_status_check CHECK ((status = ANY (ARRAY['active'::text, 'paused'::text, 'completed'::text, 'failed'::text, 'queued'::text, 'running'::text, 'cancelled'::text])))
);


--
-- Name: knowledge_chunks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.knowledge_chunks (
    id text NOT NULL,
    source_id text NOT NULL,
    chunk_index integer DEFAULT 0 NOT NULL,
    text text NOT NULL,
    embedding public.vector(1536),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: knowledge_crawls; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.knowledge_crawls (
    id text NOT NULL,
    name text NOT NULL,
    root_url text DEFAULT ''::text NOT NULL,
    source_ids text[] DEFAULT '{}'::text[] NOT NULL,
    pages_crawled integer DEFAULT 0 NOT NULL,
    pages_failed integer DEFAULT 0 NOT NULL,
    total_chunks integer DEFAULT 0 NOT NULL,
    crawled_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: knowledge_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.knowledge_sources (
    id text NOT NULL,
    name text NOT NULL,
    url text DEFAULT ''::text NOT NULL,
    chunk_count integer DEFAULT 0 NOT NULL,
    crawl_id text DEFAULT ''::text NOT NULL,
    ingested_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.links (
    id text NOT NULL,
    source_id text NOT NULL,
    target_id text NOT NULL,
    source_type text DEFAULT ''::text NOT NULL,
    target_type text DEFAULT ''::text NOT NULL,
    relation text DEFAULT ''::text NOT NULL,
    created_by text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: memories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.memories (
    id text NOT NULL,
    content text NOT NULL,
    tags text[] DEFAULT '{}'::text[] NOT NULL,
    about text DEFAULT ''::text NOT NULL,
    saved_by text DEFAULT ''::text NOT NULL,
    related_entities text[] DEFAULT '{}'::text[] NOT NULL,
    source_chat_id text DEFAULT ''::text NOT NULL,
    embedding public.vector(1536),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: memory_ingestion_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.memory_ingestion_queue (
    id text NOT NULL,
    source_type text NOT NULL,
    payload jsonb NOT NULL,
    entity_key text,
    status text DEFAULT 'pending'::text NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    processed_at timestamp with time zone
);


--
-- Name: mobile_devices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.mobile_devices (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id text NOT NULL,
    device_id text NOT NULL,
    fcm_token text NOT NULL,
    device_name text DEFAULT ''::text,
    app_version text DEFAULT ''::text,
    registered_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.notifications (
    id text NOT NULL,
    recipient text NOT NULL,
    message text NOT NULL,
    source_type text DEFAULT ''::text NOT NULL,
    source_id text DEFAULT ''::text NOT NULL,
    channel text DEFAULT ''::text NOT NULL,
    delivered boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: skipper_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.skipper_state (
    id text NOT NULL,
    domain text NOT NULL,
    state_type text NOT NULL,
    subject_id text NOT NULL,
    subject_type text NOT NULL,
    content text NOT NULL,
    priority text,
    status text DEFAULT 'active'::text NOT NULL,
    due_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    resolved_at timestamp with time zone
);


--
-- Name: thinking_domains; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.thinking_domains (
    name text NOT NULL,
    description text,
    observe_tool text NOT NULL,
    evaluate_tool text NOT NULL,
    act_tool text NOT NULL,
    knowledge_refs jsonb DEFAULT '{}'::jsonb,
    cadence jsonb DEFAULT '{}'::jsonb,
    budget_priority text DEFAULT 'standard'::text NOT NULL,
    enabled boolean DEFAULT true,
    created_by text DEFAULT 'system'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone
);


--
-- Name: thinking_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.thinking_log (
    id text NOT NULL,
    cycle_at timestamp with time zone DEFAULT now(),
    domain text,
    trigger text,
    input_summary text,
    context_snapshot jsonb,
    reasoning text,
    actions_taken jsonb,
    memories_extracted jsonb,
    model_used text,
    tokens_used integer DEFAULT 0
);


--
-- Name: trello_item_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.trello_item_history (
    normalized_key text NOT NULL,
    board text NOT NULL,
    list_name text NOT NULL,
    title text NOT NULL,
    last_seen timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.users (
    name text NOT NULL,
    display_name text NOT NULL,
    password_hash text,
    discord_id text,
    role text DEFAULT 'member'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    focus_nag_enabled boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 99 NOT NULL,
    CONSTRAINT users_role_check CHECK ((role ~ '^(admin|member|kid|bot|parent|primary)(,(admin|member|kid|bot|parent|primary))*$'::text))
);


--
-- Name: job_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_logs ALTER COLUMN id SET DEFAULT nextval('public.job_logs_id_seq'::regclass);


--
-- Name: app_event_deliveries app_event_deliveries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.app_event_deliveries
    ADD CONSTRAINT app_event_deliveries_pkey PRIMARY KEY (event_id, subscriber);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: app_events app_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.app_events
    ADD CONSTRAINT app_events_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: app_migrations app_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.app_migrations
    ADD CONSTRAINT app_migrations_pkey PRIMARY KEY (app_id, filename);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: app_registry app_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.app_registry
    ADD CONSTRAINT app_registry_pkey PRIMARY KEY (app_id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: artifacts artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: chat_turns chat_turns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.chat_turns
    ADD CONSTRAINT chat_turns_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: entity_types entity_types_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.entity_types
    ADD CONSTRAINT entity_types_pkey PRIMARY KEY (prefix);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: images images_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.images
    ADD CONSTRAINT images_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: job_logs job_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.job_logs
    ADD CONSTRAINT job_logs_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: jobs jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: knowledge_chunks knowledge_chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT knowledge_chunks_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: knowledge_crawls knowledge_crawls_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.knowledge_crawls
    ADD CONSTRAINT knowledge_crawls_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: knowledge_sources knowledge_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.knowledge_sources
    ADD CONSTRAINT knowledge_sources_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: links links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.links
    ADD CONSTRAINT links_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: memories memories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.memories
    ADD CONSTRAINT memories_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: memory_ingestion_queue memory_ingestion_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.memory_ingestion_queue
    ADD CONSTRAINT memory_ingestion_queue_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: mobile_devices mobile_devices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.mobile_devices
    ADD CONSTRAINT mobile_devices_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: mobile_devices mobile_devices_user_id_device_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.mobile_devices
    ADD CONSTRAINT mobile_devices_user_id_device_id_key UNIQUE (user_id, device_id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: skipper_state skipper_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.skipper_state
    ADD CONSTRAINT skipper_state_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: thinking_domains thinking_domains_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.thinking_domains
    ADD CONSTRAINT thinking_domains_pkey PRIMARY KEY (name);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: thinking_log thinking_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.thinking_log
    ADD CONSTRAINT thinking_log_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: trello_item_history trello_item_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.trello_item_history
    ADD CONSTRAINT trello_item_history_pkey PRIMARY KEY (normalized_key);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: users users_discord_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_discord_id_key UNIQUE (discord_id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (name);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: idx_app_event_deliveries_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_app_event_deliveries_pending ON public.app_event_deliveries USING btree (status) WHERE (status = 'pending'::text);


--
-- Name: idx_app_events_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_app_events_status ON public.app_events USING btree (status) WHERE (status <> 'completed'::text);


--
-- Name: idx_app_events_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_app_events_type ON public.app_events USING btree (event_type);


--
-- Name: idx_chat_turns_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_chat_turns_created_at ON public.chat_turns USING btree (user_id, created_at DESC);


--
-- Name: idx_chat_turns_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_chat_turns_embedding ON public.chat_turns USING ivfflat (embedding public.vector_cosine_ops) WITH (lists='10');


--
-- Name: idx_chat_turns_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_chat_turns_user_id ON public.chat_turns USING btree (user_id);


--
-- Name: idx_chunks_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON public.knowledge_chunks USING ivfflat (embedding public.vector_cosine_ops) WITH (lists='10');


--
-- Name: idx_chunks_source_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_chunks_source_id ON public.knowledge_chunks USING btree (source_id);


--
-- Name: idx_item_history_board_list; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_item_history_board_list ON public.trello_item_history USING btree (board, list_name);


--
-- Name: idx_job_logs_job_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_job_logs_job_id ON public.job_logs USING btree (job_id);


--
-- Name: idx_job_logs_job_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_job_logs_job_time ON public.job_logs USING btree (job_id, created_at);


--
-- Name: idx_jobs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_jobs_status ON public.jobs USING btree (status);


--
-- Name: idx_jobs_type_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_jobs_type_status ON public.jobs USING btree (job_type, status);


--
-- Name: idx_links_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_links_source ON public.links USING btree (source_id);


--
-- Name: idx_links_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_links_target ON public.links USING btree (target_id);


--
-- Name: idx_memories_about; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_memories_about ON public.memories USING btree (about) WHERE (about <> ''::text);


--
-- Name: idx_memories_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_memories_embedding ON public.memories USING ivfflat (embedding public.vector_cosine_ops) WITH (lists='10');


--
-- Name: idx_memories_tags; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_memories_tags ON public.memories USING gin (tags);


--
-- Name: idx_miq_entity_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX IF NOT EXISTS idx_miq_entity_key ON public.memory_ingestion_queue USING btree (entity_key) WHERE ((entity_key IS NOT NULL) AND (status = 'pending'::text));


--
-- Name: idx_miq_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_miq_status_created ON public.memory_ingestion_queue USING btree (status, created_at) WHERE (status = ANY (ARRAY['pending'::text, 'processing'::text]));


--
-- Name: idx_mobile_devices_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_mobile_devices_user ON public.mobile_devices USING btree (user_id);


--
-- Name: idx_notifications_recipient; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_notifications_recipient ON public.notifications USING btree (recipient);


--
-- Name: idx_notifications_source_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_notifications_source_id ON public.notifications USING btree (source_id) WHERE (source_id <> ''::text);


--
-- Name: idx_skipper_state_domain_status_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_skipper_state_domain_status_priority ON public.skipper_state USING btree (domain, status, priority);


--
-- Name: idx_skipper_state_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_skipper_state_due ON public.skipper_state USING btree (due_at) WHERE ((due_at IS NOT NULL) AND (status = 'active'::text));


--
-- Name: idx_skipper_state_subject; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_skipper_state_subject ON public.skipper_state USING btree (subject_id);


--
-- Name: idx_skipper_state_type_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_skipper_state_type_status ON public.skipper_state USING btree (state_type, status);


--
-- Name: idx_thinking_log_cycle; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_thinking_log_cycle ON public.thinking_log USING btree (cycle_at DESC);


--
-- Name: idx_thinking_log_domain_cycle; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_thinking_log_domain_cycle ON public.thinking_log USING btree (domain, cycle_at DESC);


--
-- Name: idx_users_discord_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_users_discord_id ON public.users USING btree (discord_id) WHERE (discord_id IS NOT NULL);


--
-- Name: uq_links_source_target_relation; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX IF NOT EXISTS uq_links_source_target_relation ON public.links USING btree (source_id, target_id, relation);


--
-- Name: app_event_deliveries app_event_deliveries_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.app_event_deliveries
    ADD CONSTRAINT app_event_deliveries_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.app_events(id) ON DELETE CASCADE;
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: app_migrations app_migrations_app_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.app_migrations
    ADD CONSTRAINT app_migrations_app_id_fkey FOREIGN KEY (app_id) REFERENCES public.app_registry(app_id) ON DELETE CASCADE;
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: knowledge_chunks knowledge_chunks_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT knowledge_chunks_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.knowledge_sources(id) ON DELETE CASCADE;
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: mobile_devices mobile_devices_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.mobile_devices
    ADD CONSTRAINT mobile_devices_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(name) ON DELETE CASCADE;
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: skipper_state skipper_state_domain_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.skipper_state
    ADD CONSTRAINT skipper_state_domain_fkey FOREIGN KEY (domain) REFERENCES public.thinking_domains(name);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- Name: thinking_log thinking_log_domain_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
ALTER TABLE ONLY public.thinking_log
    ADD CONSTRAINT thinking_log_domain_fkey FOREIGN KEY (domain) REFERENCES public.thinking_domains(name);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;


--
-- PostgreSQL database dump complete
--

-- =============================================================================
-- app_config — scoped settings storage for platform + per-app preferences.
-- =============================================================================
-- Scope 'platform' for platform-level settings (timezone, model names, etc.)
-- Scope 'app:<id>'  for per-app preferences declared in each app's manifest.
-- An app may only read/write its own scope; the platform.config.* service
-- enforces this by inferring scope from the caller's module path.
CREATE TABLE IF NOT EXISTS public.app_config (
    scope       text NOT NULL,
    key         text NOT NULL,
    value       jsonb NOT NULL,
    updated_at  timestamp with time zone NOT NULL DEFAULT now(),
    updated_by  text NOT NULL DEFAULT '',
    PRIMARY KEY (scope, key)
);

CREATE INDEX IF NOT EXISTS app_config_scope_idx ON public.app_config(scope);


-- =============================================================================
-- Seed: platform-owned entity types
-- =============================================================================
-- App-owned entity types (re-, p-, t-, etc.) are NOT seeded here; each app's
-- manifest declares them and the loader registers them when the app loads.
-- Only true platform-infra prefixes go here.
INSERT INTO public.entity_types (prefix, name, id_format, table_name) VALUES
    ('a',   'artifact',         'a-',   'artifacts'),
    ('c',   'chat log',         'c-',   'chat_turns'),
    ('i',   'image',             'i-',   'images'),
    ('j',   'job',                'j-',   'jobs'),
    ('k',   'knowledge',          'k-',   'knowledge_sources'),
    ('kc',  'knowledge crawl',    'kc-',  'knowledge_crawls'),
    ('lnk', 'link',               'lnk-', 'links'),
    ('m',   'memory',             'm-',   'memories'),
    ('n',   'notification',       'n-',   'notifications'),
    ('ss',  'skipper state',      'ss-',  'skipper_state'),
    ('tl',  'thinking log',       'tl-',  'thinking_log')
ON CONFLICT (prefix) DO NOTHING;

-- =============================================================================
-- Seed: platform-level thinking domains
-- =============================================================================
-- These run as part of the agent's continuous-thinking loop. App-owned
-- thinking domains (e.g. 'goals/pm', 'evolve') are registered by each app
-- via their manifest; they are NOT seeded here.
--
-- All shipped as 'enabled=false' by default. The onboarding wizard and the
-- Settings app give the user explicit opt-in for autonomous reasoning that
-- spends real OpenAI tokens.
INSERT INTO public.thinking_domains (name, description, observe_tool, evaluate_tool, act_tool, knowledge_refs, cadence, budget_priority, enabled, created_by) VALUES
    ('chat',
     'Interactive Chat — priority-0 event-driven domain for user conversations.',
     '', '', '', '[]'::jsonb, '{"trigger": "event"}'::jsonb, 'critical', true, ''),
    ('memory',
     'Memory Ingestion — digest queued chat turns and app records into searchable memories.',
     '', '', '', '[]'::jsonb, '{"trigger": "queue"}'::jsonb, 'high', true, ''),
    ('document',
     'Knowledge Organization — reflect on memories and organize into readable documents.',
     '', '', '', '[]'::jsonb, '{"trigger": "schedule", "cron": "0 3 * * *"}'::jsonb, 'low', false, ''),
    ('self',
     'Self-awareness — cross-domain observations, self-directed thinking.',
     '', '', '', '[]'::jsonb, '{"trigger": "schedule", "cron": "0 */6 * * *"}'::jsonb, 'low', false, '')
ON CONFLICT (name) DO NOTHING;

-- =============================================================================
-- Seed: default scope='platform' app_config values
-- =============================================================================
-- Onboarding overrides most of these; defaults are conservative.
INSERT INTO public.app_config (scope, key, value, updated_by) VALUES
    ('platform', 'timezone',                '"Etc/UTC"'::jsonb,        'baseline'),
    ('platform', 'smart_model',             '"gpt-5.2"'::jsonb,        'baseline'),
    ('platform', 'dumb_model',              '"gpt-5-mini"'::jsonb,     'baseline'),
    ('platform', 'reminder_lead_minutes',   '120'::jsonb,              'baseline'),
    ('platform', 'max_session_turns',       '20'::jsonb,               'baseline'),
    ('platform', 'nag_wake_hour',           '8'::jsonb,                'baseline'),
    ('platform', 'nag_sleep_hour',          '21'::jsonb,               'baseline'),
    ('platform', 'nag_morning_start',       '7'::jsonb,                'baseline'),
    ('platform', 'nag_morning_end',         '12'::jsonb,               'baseline'),
    ('platform', 'nag_afternoon_start',     '12'::jsonb,               'baseline'),
    ('platform', 'nag_afternoon_end',       '17'::jsonb,               'baseline'),
    ('platform', 'nag_evening_start',       '17'::jsonb,               'baseline'),
    ('platform', 'nag_evening_end',         '21'::jsonb,               'baseline'),
    ('platform', 'show_entity_ids',         'false'::jsonb,            'baseline'),
    ('platform', 'pm_quiet_mode',           'false'::jsonb,            'baseline'),
    ('platform', 'onboarding_complete',     'false'::jsonb,            'baseline')
ON CONFLICT (scope, key) DO NOTHING;
