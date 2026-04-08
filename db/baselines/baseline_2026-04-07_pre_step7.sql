--
-- PostgreSQL database dump
--

\restrict NhWdsYDjMFp0042UcSXrXQ3vsUjf04SOUCygnPhlc2DxK4ZsZOuc9m9yWfM8qVf

-- Dumped from database version 16.13 (Homebrew)
-- Dumped by pg_dump version 16.13 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: enforce_child_step_tier(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_child_step_tier() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM alpha_task_graphs
        WHERE id = NEW.graph_id
          AND user_type = 'child'
    ) AND NEW.content_tier != 'child_safe' THEN
        RAISE EXCEPTION
            'Child graph % — step content_tier must be child_safe, got %',
            NEW.graph_id, NEW.content_tier;
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: rating_level(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.rating_level(r text) RETURNS integer
    LANGUAGE sql IMMUTABLE
    AS $$
    SELECT CASE r
        WHEN 'all_ages'   THEN 1
        WHEN 'age_8_plus' THEN 2
        WHEN 'teen'       THEN 3
        WHEN 'adult'      THEN 4
        ELSE 0
    END;
$$;


--
-- Name: sync_profile_to_user(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sync_profile_to_user() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
BEGIN
    IF (TG_OP = 'INSERT') THEN
        INSERT INTO alpha_users (id, email, role, is_child, child_age, created_at)
        VALUES (
            NEW.id,
            NEW.id || '@jarvis.local',
            CASE WHEN NEW.role = 'admin' THEN 'workspace_admin' ELSE 'workspace_user' END,
            (NEW.role = 'child'),
            NEW.child_age,
            COALESCE(NEW.created_at, now())
        )
        ON CONFLICT (id) DO UPDATE SET
            role = EXCLUDED.role,
            is_child = EXCLUDED.is_child,
            child_age = EXCLUDED.child_age;
        RETURN NEW;
    ELSIF (TG_OP = 'UPDATE') THEN
        UPDATE alpha_users
        SET 
            role = CASE WHEN NEW.role = 'admin' THEN 'workspace_admin' ELSE 'workspace_user' END,
            is_child = (NEW.role = 'child'),
            child_age = NEW.child_age
        WHERE id = NEW.id;
        RETURN NEW;
    ELSIF (TG_OP = 'DELETE') THEN
        DELETE FROM alpha_users WHERE id = OLD.id;
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$$;


--
-- Name: update_task_timestamp(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_task_timestamp() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: alpha_approval_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_approval_audit (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    approval_id uuid,
    action_class text[] NOT NULL,
    risk_tier text NOT NULL,
    actor_sub text NOT NULL,
    actor_type text NOT NULL,
    description text NOT NULL,
    parameters_hash text NOT NULL,
    nonce text NOT NULL,
    decision text NOT NULL,
    decided_by text,
    decided_at timestamp with time zone DEFAULT now() NOT NULL,
    overnight boolean DEFAULT false NOT NULL,
    CONSTRAINT alpha_approval_audit_decision_check CHECK ((decision = ANY (ARRAY['approved'::text, 'denied'::text, 'expired'::text, 'auto'::text])))
);


--
-- Name: alpha_approval_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_approval_queue (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    action_class text[] NOT NULL,
    risk_tier text NOT NULL,
    actor_sub text NOT NULL,
    actor_type text NOT NULL,
    actor_node text,
    description text NOT NULL,
    parameters_hash text NOT NULL,
    parameters_preview text,
    nonce text NOT NULL,
    notification_sent boolean DEFAULT false NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    requested_at timestamp with time zone DEFAULT now() NOT NULL,
    decided_by text,
    decided_at timestamp with time zone,
    executed_at timestamp with time zone,
    expires_at timestamp with time zone NOT NULL,
    overnight boolean DEFAULT false NOT NULL,
    CONSTRAINT alpha_approval_queue_actor_type_check CHECK ((actor_type = ANY (ARRAY['user'::text, 'service'::text, 'agent'::text]))),
    CONSTRAINT alpha_approval_queue_risk_tier_check CHECK ((risk_tier = ANY (ARRAY['T1'::text, 'T2'::text, 'T3'::text, 'T4'::text, 'T5'::text]))),
    CONSTRAINT alpha_approval_queue_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'approved'::text, 'denied'::text, 'expired'::text, 'executed'::text])))
);


--
-- Name: alpha_briefings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_briefings (
    id integer NOT NULL,
    batch_run_id text NOT NULL,
    briefing_date date NOT NULL,
    started_at timestamp with time zone NOT NULL,
    source text NOT NULL,
    summary jsonb NOT NULL,
    results jsonb NOT NULL,
    markdown text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: alpha_briefings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.alpha_briefings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alpha_briefings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.alpha_briefings_id_seq OWNED BY public.alpha_briefings.id;


--
-- Name: alpha_buddy_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_buddy_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id text,
    event_type text NOT NULL,
    title text NOT NULL,
    body text,
    priority integer DEFAULT 2 NOT NULL,
    read boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    source text,
    payload jsonb,
    CONSTRAINT alpha_buddy_events_event_type_check CHECK ((event_type = ANY (ARRAY['alert'::text, 'reminder'::text, 'suggestion'::text, 'system'::text])))
);


--
-- Name: alpha_budget_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_budget_config (
    id integer NOT NULL,
    provider text NOT NULL,
    monthly_limit_usd numeric(10,2) DEFAULT 50.00,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: alpha_budget_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.alpha_budget_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alpha_budget_config_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.alpha_budget_config_id_seq OWNED BY public.alpha_budget_config.id;


--
-- Name: alpha_cloud_costs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_cloud_costs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    prompt_tokens integer DEFAULT 0,
    completion_tokens integer DEFAULT 0,
    total_tokens integer DEFAULT 0,
    cost_usd numeric(10,6) DEFAULT 0,
    session_type text,
    key_name text,
    intent text,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT alpha_cloud_costs_provider_check CHECK ((provider = ANY (ARRAY['anthropic'::text, 'gemini'::text, 'perplexity'::text]))),
    CONSTRAINT alpha_cloud_costs_session_type_check CHECK ((session_type = ANY (ARRAY['ask'::text, 'overnight'::text, 'forge'::text, 'other'::text])))
);


--
-- Name: alpha_conversation_memory; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_conversation_memory (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workspace_id text,
    user_id text NOT NULL,
    session_id text NOT NULL,
    role text NOT NULL,
    content text NOT NULL,
    embedding public.vector(768),
    memory_type text DEFAULT 'conversation'::text NOT NULL,
    persistent boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    tier text DEFAULT 'working'::text NOT NULL,
    importance_score double precision DEFAULT 0.5 NOT NULL,
    last_accessed_at timestamp with time zone DEFAULT now() NOT NULL,
    summary text,
    access_count integer DEFAULT 0 NOT NULL,
    content_rating text DEFAULT 'adult'::text NOT NULL,
    CONSTRAINT alpha_conversation_memory_content_rating_check CHECK ((content_rating = ANY (ARRAY['all_ages'::text, 'age_8_plus'::text, 'teen'::text, 'adult'::text]))),
    CONSTRAINT alpha_conversation_memory_role_check CHECK ((role = ANY (ARRAY['user'::text, 'assistant'::text, 'system'::text])))
);


--
-- Name: alpha_credit_balance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_credit_balance (
    id integer NOT NULL,
    balance_usd numeric(10,2) DEFAULT 0,
    spent_usd numeric(10,6) DEFAULT 0,
    pending_usd numeric(10,2) DEFAULT 0,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: alpha_credit_balance_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.alpha_credit_balance_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alpha_credit_balance_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.alpha_credit_balance_id_seq OWNED BY public.alpha_credit_balance.id;


--
-- Name: alpha_dream_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_dream_sessions (
    id bigint NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    trigger text DEFAULT 'scheduled'::text NOT NULL,
    cost_budget_usd numeric(8,4) DEFAULT 5.0000 NOT NULL,
    cost_actual_usd numeric(8,4) DEFAULT 0.0000 NOT NULL,
    max_duration_s integer DEFAULT 14400 NOT NULL,
    step_count integer DEFAULT 0 NOT NULL,
    steps_completed integer DEFAULT 0 NOT NULL,
    steps_failed integer DEFAULT 0 NOT NULL,
    steps_blocked integer DEFAULT 0 NOT NULL,
    kill_reason text,
    summary text,
    created_at timestamp with time zone DEFAULT now(),
    owner_profile text,
    CONSTRAINT alpha_dream_sessions_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'completed'::text, 'failed'::text, 'aborted'::text, 'killed'::text]))),
    CONSTRAINT alpha_dream_sessions_trigger_check CHECK ((trigger = ANY (ARRAY['scheduled'::text, 'manual'::text, 'dry_run'::text])))
);


--
-- Name: alpha_dream_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.alpha_dream_sessions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alpha_dream_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.alpha_dream_sessions_id_seq OWNED BY public.alpha_dream_sessions.id;


--
-- Name: alpha_dream_steps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_dream_steps (
    id bigint NOT NULL,
    session_id bigint NOT NULL,
    step_index integer NOT NULL,
    name text NOT NULL,
    description text,
    status text DEFAULT 'pending'::text NOT NULL,
    depends_on integer[] DEFAULT '{}'::integer[],
    retry_count integer DEFAULT 0 NOT NULL,
    max_retries integer DEFAULT 3 NOT NULL,
    agent_type text,
    model_used text,
    input_hash text,
    output_summary text,
    verification text,
    cost_usd numeric(8,4) DEFAULT 0.0000 NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    error_message text,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT alpha_dream_steps_agent_type_check CHECK ((agent_type = ANY (ARRAY['llm'::text, 'code'::text, 'tool'::text, 'cloud'::text, 'canary'::text]))),
    CONSTRAINT alpha_dream_steps_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'completed'::text, 'failed'::text, 'blocked'::text, 'skipped'::text])))
);


--
-- Name: alpha_dream_steps_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.alpha_dream_steps_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alpha_dream_steps_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.alpha_dream_steps_id_seq OWNED BY public.alpha_dream_steps.id;


--
-- Name: alpha_hardware_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_hardware_config (
    id integer NOT NULL,
    node_name text NOT NULL,
    cost_usd numeric(10,2) NOT NULL,
    years integer DEFAULT 4 NOT NULL,
    monthly_usd numeric(10,2) GENERATED ALWAYS AS ((cost_usd / ((years * 12))::numeric)) STORED,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: alpha_hardware_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.alpha_hardware_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alpha_hardware_config_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.alpha_hardware_config_id_seq OWNED BY public.alpha_hardware_config.id;


--
-- Name: alpha_honeypot_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_honeypot_events (
    id bigint NOT NULL,
    trap_path text NOT NULL,
    source_ip text NOT NULL,
    method text NOT NULL,
    user_agent text,
    headers jsonb DEFAULT '{}'::jsonb,
    captured_at timestamp with time zone DEFAULT now()
);


--
-- Name: alpha_honeypot_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.alpha_honeypot_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alpha_honeypot_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.alpha_honeypot_events_id_seq OWNED BY public.alpha_honeypot_events.id;


--
-- Name: alpha_node_registry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_node_registry (
    id integer NOT NULL,
    name text NOT NULL,
    display_name text NOT NULL,
    role text NOT NULL,
    node_type text NOT NULL,
    tailscale_ip text,
    health_endpoint text,
    cert_issued_at timestamp with time zone,
    cert_expires_at timestamp with time zone,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT alpha_node_registry_node_type_check CHECK ((node_type = ANY (ARRAY['service'::text, 'storage'::text, 'dev'::text, 'network'::text, 'mobile'::text])))
);


--
-- Name: alpha_node_registry_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.alpha_node_registry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alpha_node_registry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.alpha_node_registry_id_seq OWNED BY public.alpha_node_registry.id;


--
-- Name: alpha_overnight_approvals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_overnight_approvals (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    pattern text NOT NULL,
    max_tier text NOT NULL,
    budget_usd numeric(10,2),
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    revoked_by text,
    CONSTRAINT alpha_overnight_approvals_max_tier_check CHECK ((max_tier = ANY (ARRAY['T1'::text, 'T2'::text, 'T3'::text])))
);


--
-- Name: alpha_perplexity_credit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_perplexity_credit (
    id integer NOT NULL,
    balance_usd numeric(10,2) DEFAULT 0,
    spent_usd numeric(10,6) DEFAULT 0,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: alpha_perplexity_credit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.alpha_perplexity_credit_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alpha_perplexity_credit_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.alpha_perplexity_credit_id_seq OWNED BY public.alpha_perplexity_credit.id;


--
-- Name: alpha_power_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_power_config (
    id integer NOT NULL,
    rate_per_kwh numeric(6,4) DEFAULT 0.13,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: alpha_power_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.alpha_power_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alpha_power_config_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.alpha_power_config_id_seq OWNED BY public.alpha_power_config.id;


--
-- Name: alpha_power_daily; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_power_daily (
    id bigint NOT NULL,
    node_name text NOT NULL,
    day_start date NOT NULL,
    avg_watts numeric(8,3) NOT NULL,
    sample_count integer DEFAULT 0
);


--
-- Name: alpha_power_daily_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.alpha_power_daily_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alpha_power_daily_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.alpha_power_daily_id_seq OWNED BY public.alpha_power_daily.id;


--
-- Name: alpha_power_hourly; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_power_hourly (
    id bigint NOT NULL,
    node_name text NOT NULL,
    hour_start timestamp with time zone NOT NULL,
    avg_watts numeric(8,3) NOT NULL,
    sample_count integer DEFAULT 0
);


--
-- Name: alpha_power_hourly_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.alpha_power_hourly_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alpha_power_hourly_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.alpha_power_hourly_id_seq OWNED BY public.alpha_power_hourly.id;


--
-- Name: alpha_power_readings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_power_readings (
    id bigint NOT NULL,
    node_name text NOT NULL,
    watts numeric(8,3) NOT NULL,
    cpu_pct numeric(5,2),
    source text DEFAULT 'psutil'::text,
    recorded_at timestamp with time zone DEFAULT now(),
    CONSTRAINT alpha_power_readings_source_check CHECK ((source = ANY (ARRAY['powermetrics'::text, 'psutil'::text, 'static'::text])))
);


--
-- Name: alpha_power_readings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.alpha_power_readings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alpha_power_readings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.alpha_power_readings_id_seq OWNED BY public.alpha_power_readings.id;


--
-- Name: alpha_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_profiles (
    id text NOT NULL,
    display_name text NOT NULL,
    role text NOT NULL,
    child_age integer,
    max_rating text DEFAULT 'all_ages'::text NOT NULL,
    pin_hash text NOT NULL,
    active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT alpha_profiles_max_rating_check CHECK ((max_rating = ANY (ARRAY['all_ages'::text, 'age_8_plus'::text, 'teen'::text, 'adult'::text]))),
    CONSTRAINT alpha_profiles_role_check CHECK ((role = ANY (ARRAY['admin'::text, 'child'::text])))
);


--
-- Name: alpha_projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_projects (
    id integer NOT NULL,
    name text NOT NULL,
    project_type text NOT NULL,
    repo_slug text,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT alpha_projects_project_type_check CHECK ((project_type = ANY (ARRAY['forge'::text, 'personal'::text, 'problem'::text])))
);


--
-- Name: alpha_projects_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.alpha_projects_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alpha_projects_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.alpha_projects_id_seq OWNED BY public.alpha_projects.id;


--
-- Name: alpha_prompt_registry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_prompt_registry (
    id integer NOT NULL,
    prompt_id text NOT NULL,
    version integer NOT NULL,
    system_prompt text NOT NULL,
    model_hint text,
    scope text NOT NULL,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT alpha_prompt_registry_scope_check CHECK ((scope = ANY (ARRAY['alpha'::text, 'forge'::text, 'global'::text])))
);


--
-- Name: alpha_prompt_registry_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.alpha_prompt_registry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alpha_prompt_registry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.alpha_prompt_registry_id_seq OWNED BY public.alpha_prompt_registry.id;


--
-- Name: alpha_semantic_memory; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_semantic_memory (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    fact text NOT NULL,
    category text NOT NULL,
    source text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT alpha_semantic_memory_category_check CHECK ((category = ANY (ARRAY['preference'::text, 'person'::text, 'project'::text, 'constraint'::text, 'health'::text, 'child_profile'::text]))),
    CONSTRAINT alpha_semantic_memory_source_check CHECK ((source = ANY (ARRAY['promoted'::text, 'explicit'::text, 'buddy'::text])))
);


--
-- Name: alpha_subscriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_subscriptions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    url text,
    cost_usd numeric(10,2) NOT NULL,
    billing text NOT NULL,
    next_renewal date NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT alpha_subscriptions_billing_check CHECK ((billing = ANY (ARRAY['monthly'::text, 'yearly'::text])))
);


--
-- Name: alpha_task_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_task_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    event_type text NOT NULL,
    graph_id uuid,
    step_id uuid,
    message text DEFAULT ''::text NOT NULL,
    severity text DEFAULT 'normal'::text NOT NULL,
    title text,
    detail jsonb DEFAULT '{}'::jsonb,
    source text DEFAULT 'system'::text,
    read boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT alpha_task_events_severity_check CHECK ((severity = ANY (ARRAY['low'::text, 'normal'::text, 'warning'::text, 'critical'::text])))
);


--
-- Name: alpha_task_graphs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_task_graphs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id text NOT NULL,
    title text NOT NULL,
    description text,
    graph_type text DEFAULT 'user_request'::text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    priority integer DEFAULT 5 NOT NULL,
    user_type text DEFAULT 'adult'::text NOT NULL,
    content_tier text DEFAULT 'unrestricted'::text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    checkpoint jsonb DEFAULT '{}'::jsonb NOT NULL,
    max_retries integer DEFAULT 2 NOT NULL,
    timeout_seconds integer DEFAULT 3600 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    owner_profile text,
    source text DEFAULT 'manual'::text NOT NULL,
    ci_required boolean DEFAULT false NOT NULL,
    ci_passed boolean,
    CONSTRAINT alpha_task_graphs_content_tier_check CHECK ((content_tier = ANY (ARRAY['unrestricted'::text, 'filtered'::text, 'child_safe'::text]))),
    CONSTRAINT alpha_task_graphs_graph_type_check CHECK ((graph_type = ANY (ARRAY['overnight'::text, 'user_request'::text, 'agent'::text, 'maintenance'::text]))),
    CONSTRAINT alpha_task_graphs_priority_check CHECK (((priority >= 1) AND (priority <= 10))),
    CONSTRAINT alpha_task_graphs_source_check CHECK ((source = ANY (ARRAY['manual'::text, 'agent'::text]))),
    CONSTRAINT alpha_task_graphs_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'completed'::text, 'failed'::text, 'stuck'::text, 'needs_approval'::text, 'cancelled'::text]))),
    CONSTRAINT alpha_task_graphs_user_type_check CHECK ((user_type = ANY (ARRAY['adult'::text, 'child'::text]))),
    CONSTRAINT chk_child_content_tier CHECK (((user_type = 'adult'::text) OR ((user_type = 'child'::text) AND (content_tier = 'child_safe'::text))))
);


--
-- Name: alpha_task_steps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_task_steps (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    graph_id uuid NOT NULL,
    user_id text NOT NULL,
    step_name text NOT NULL,
    step_type text NOT NULL,
    step_order integer DEFAULT 0 NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    depends_on uuid[] DEFAULT '{}'::uuid[] NOT NULL,
    content_tier text DEFAULT 'unrestricted'::text NOT NULL,
    input jsonb DEFAULT '{}'::jsonb NOT NULL,
    output jsonb DEFAULT '{}'::jsonb NOT NULL,
    checkpoint jsonb DEFAULT '{}'::jsonb NOT NULL,
    approval_required boolean DEFAULT false NOT NULL,
    approval_status text,
    approved_by text,
    approved_at timestamp with time zone,
    retry_count integer DEFAULT 0 NOT NULL,
    max_retries integer DEFAULT 2 NOT NULL,
    timeout_seconds integer DEFAULT 300 NOT NULL,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    CONSTRAINT alpha_task_steps_approval_status_check CHECK ((approval_status = ANY (ARRAY['pending'::text, 'approved'::text, 'denied'::text]))),
    CONSTRAINT alpha_task_steps_content_tier_check CHECK ((content_tier = ANY (ARRAY['unrestricted'::text, 'filtered'::text, 'child_safe'::text]))),
    CONSTRAINT alpha_task_steps_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'queued'::text, 'running'::text, 'completed'::text, 'failed'::text, 'stuck'::text, 'skipped'::text, 'cancelled'::text]))),
    CONSTRAINT alpha_task_steps_step_type_check CHECK ((step_type = ANY (ARRAY['llm'::text, 'code'::text, 'tool'::text, 'approval'::text, 'condition'::text, 'parallel_gate'::text])))
);


--
-- Name: alpha_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_users (
    id text NOT NULL,
    email text NOT NULL,
    role text DEFAULT 'workspace_user'::text NOT NULL,
    is_child boolean DEFAULT false,
    child_age integer,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: alpha_watchdog_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_watchdog_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    service_name text NOT NULL,
    node text NOT NULL,
    event_type text NOT NULL,
    previous_state text,
    current_state text,
    consecutive_failures integer DEFAULT 0,
    latency_ms numeric(10,2),
    http_status integer,
    error_message text,
    action_taken text,
    trace_id uuid,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT watchdog_event_type_check CHECK ((event_type = ANY (ARRAY['down'::text, 'restored'::text, 'degraded'::text, 'restart_triggered'::text, 'restart_succeeded'::text, 'restart_failed'::text, 'check_error'::text])))
);


--
-- Name: alpha_workspace_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_workspace_users (
    workspace_id text NOT NULL,
    user_id text NOT NULL,
    role text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: alpha_workspaces; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_workspaces (
    id text NOT NULL,
    name text NOT NULL,
    slug text NOT NULL,
    enabled boolean DEFAULT false,
    config jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: chat_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_messages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    thread_id uuid NOT NULL,
    role text NOT NULL,
    content text NOT NULL,
    model_used text,
    council_detail jsonb,
    memory_injected boolean DEFAULT false NOT NULL,
    latency_ms integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    content_rating text DEFAULT 'adult'::text NOT NULL,
    CONSTRAINT chat_messages_content_rating_check CHECK ((content_rating = ANY (ARRAY['all_ages'::text, 'age_8_plus'::text, 'teen'::text, 'adult'::text]))),
    CONSTRAINT chat_messages_role_check CHECK ((role = ANY (ARRAY['user'::text, 'assistant'::text, 'system'::text])))
);


--
-- Name: chat_threads; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_threads (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id text NOT NULL,
    title text DEFAULT 'New conversation'::text NOT NULL,
    mode text DEFAULT 'realtime'::text NOT NULL,
    model_used text,
    project_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    archived_at timestamp with time zone,
    owner_profile text,
    content_rating text DEFAULT 'adult'::text NOT NULL,
    CONSTRAINT chat_threads_content_rating_check CHECK ((content_rating = ANY (ARRAY['all_ages'::text, 'age_8_plus'::text, 'teen'::text, 'adult'::text]))),
    CONSTRAINT chat_threads_mode_check CHECK ((mode = ANY (ARRAY['realtime'::text, 'overnight'::text])))
);


--
-- Name: jarvis_request_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jarvis_request_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    trace_id uuid NOT NULL,
    workspace_id text,
    user_id text NOT NULL,
    node text NOT NULL,
    route text NOT NULL,
    method text NOT NULL,
    status_code integer NOT NULL,
    latency_ms integer NOT NULL,
    model text,
    cost_usd numeric(10,6),
    error text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: pipeline_lessons; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pipeline_lessons (
    id integer NOT NULL,
    feature_id text NOT NULL,
    category text NOT NULL,
    files_touched text[] NOT NULL,
    lesson_summary text NOT NULL,
    failure_reasons text[],
    iteration_count integer NOT NULL,
    outcome text,
    embedding public.vector(768),
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT pipeline_lessons_outcome_check CHECK ((outcome = ANY (ARRAY['success'::text, 'partial'::text, 'reverted'::text])))
);


--
-- Name: pipeline_lessons_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pipeline_lessons_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pipeline_lessons_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pipeline_lessons_id_seq OWNED BY public.pipeline_lessons.id;


--
-- Name: pipeline_metrics_brain; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pipeline_metrics_brain (
    id integer NOT NULL,
    metric_name text NOT NULL,
    metric_value real NOT NULL,
    category text,
    feature_id text,
    recorded_at timestamp with time zone DEFAULT now()
);


--
-- Name: pipeline_metrics_brain_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pipeline_metrics_brain_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pipeline_metrics_brain_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pipeline_metrics_brain_id_seq OWNED BY public.pipeline_metrics_brain.id;


--
-- Name: pipeline_trust_scores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pipeline_trust_scores (
    category text NOT NULL,
    trust_score real NOT NULL,
    recent_success_rate real,
    avg_iterations real,
    avg_risk_score real,
    sample_size integer,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: secret_access_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.secret_access_log (
    id bigint NOT NULL,
    key_name text NOT NULL,
    source text NOT NULL,
    accessed_at timestamp with time zone NOT NULL,
    node text NOT NULL,
    flushed_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: secret_access_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.secret_access_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: secret_access_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.secret_access_log_id_seq OWNED BY public.secret_access_log.id;


--
-- Name: vault_access_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vault_access_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    document_id uuid,
    user_id text,
    action text NOT NULL,
    query text,
    result_count integer,
    ip_address text,
    created_at timestamp with time zone DEFAULT now()
);

ALTER TABLE ONLY public.vault_access_log FORCE ROW LEVEL SECURITY;


--
-- Name: vault_chunks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vault_chunks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    document_id uuid,
    chunk_index integer NOT NULL,
    content text NOT NULL,
    embedding public.vector(384),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: vault_document_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vault_document_permissions (
    document_id uuid NOT NULL,
    user_id text NOT NULL,
    can_read boolean DEFAULT false,
    can_search boolean DEFAULT false,
    granted_by text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: vault_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vault_documents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workspace_id text NOT NULL,
    uploaded_by text NOT NULL,
    filename text NOT NULL,
    content_type text NOT NULL,
    size_bytes integer,
    classification text DEFAULT '40_PRIVATE'::text NOT NULL,
    storage_tier text DEFAULT 'hot'::text NOT NULL,
    local_path text,
    archive_path text,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT vault_documents_classification_check CHECK ((classification = ANY (ARRAY['10_PUBLIC'::text, '15_KIDS'::text, '20_PROJECTS'::text, '30_FINANCE'::text, '40_PRIVATE'::text, '50_SECRETS'::text])))
);

ALTER TABLE ONLY public.vault_documents FORCE ROW LEVEL SECURITY;


--
-- Name: vault_pipeline; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vault_pipeline (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workspace_id text NOT NULL,
    uploaded_by text NOT NULL,
    filename text NOT NULL,
    content_type text NOT NULL,
    size_bytes integer,
    local_path text NOT NULL,
    stage text DEFAULT 'inbox'::text NOT NULL,
    ai_classification text,
    ai_confidence numeric(4,3),
    confirmed_classification text,
    confirmed_by text,
    confirmed_at timestamp with time zone,
    error text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

ALTER TABLE ONLY public.vault_pipeline FORCE ROW LEVEL SECURITY;


--
-- Name: alpha_briefings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_briefings ALTER COLUMN id SET DEFAULT nextval('public.alpha_briefings_id_seq'::regclass);


--
-- Name: alpha_budget_config id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_budget_config ALTER COLUMN id SET DEFAULT nextval('public.alpha_budget_config_id_seq'::regclass);


--
-- Name: alpha_credit_balance id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_credit_balance ALTER COLUMN id SET DEFAULT nextval('public.alpha_credit_balance_id_seq'::regclass);


--
-- Name: alpha_dream_sessions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_dream_sessions ALTER COLUMN id SET DEFAULT nextval('public.alpha_dream_sessions_id_seq'::regclass);


--
-- Name: alpha_dream_steps id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_dream_steps ALTER COLUMN id SET DEFAULT nextval('public.alpha_dream_steps_id_seq'::regclass);


--
-- Name: alpha_hardware_config id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_hardware_config ALTER COLUMN id SET DEFAULT nextval('public.alpha_hardware_config_id_seq'::regclass);


--
-- Name: alpha_honeypot_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_honeypot_events ALTER COLUMN id SET DEFAULT nextval('public.alpha_honeypot_events_id_seq'::regclass);


--
-- Name: alpha_node_registry id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_node_registry ALTER COLUMN id SET DEFAULT nextval('public.alpha_node_registry_id_seq'::regclass);


--
-- Name: alpha_perplexity_credit id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_perplexity_credit ALTER COLUMN id SET DEFAULT nextval('public.alpha_perplexity_credit_id_seq'::regclass);


--
-- Name: alpha_power_config id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_power_config ALTER COLUMN id SET DEFAULT nextval('public.alpha_power_config_id_seq'::regclass);


--
-- Name: alpha_power_daily id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_power_daily ALTER COLUMN id SET DEFAULT nextval('public.alpha_power_daily_id_seq'::regclass);


--
-- Name: alpha_power_hourly id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_power_hourly ALTER COLUMN id SET DEFAULT nextval('public.alpha_power_hourly_id_seq'::regclass);


--
-- Name: alpha_power_readings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_power_readings ALTER COLUMN id SET DEFAULT nextval('public.alpha_power_readings_id_seq'::regclass);


--
-- Name: alpha_projects id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_projects ALTER COLUMN id SET DEFAULT nextval('public.alpha_projects_id_seq'::regclass);


--
-- Name: alpha_prompt_registry id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_prompt_registry ALTER COLUMN id SET DEFAULT nextval('public.alpha_prompt_registry_id_seq'::regclass);


--
-- Name: pipeline_lessons id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_lessons ALTER COLUMN id SET DEFAULT nextval('public.pipeline_lessons_id_seq'::regclass);


--
-- Name: pipeline_metrics_brain id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_metrics_brain ALTER COLUMN id SET DEFAULT nextval('public.pipeline_metrics_brain_id_seq'::regclass);


--
-- Name: secret_access_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.secret_access_log ALTER COLUMN id SET DEFAULT nextval('public.secret_access_log_id_seq'::regclass);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: alpha_approval_audit alpha_approval_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_approval_audit
    ADD CONSTRAINT alpha_approval_audit_pkey PRIMARY KEY (id);


--
-- Name: alpha_approval_queue alpha_approval_queue_nonce_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_approval_queue
    ADD CONSTRAINT alpha_approval_queue_nonce_key UNIQUE (nonce);


--
-- Name: alpha_approval_queue alpha_approval_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_approval_queue
    ADD CONSTRAINT alpha_approval_queue_pkey PRIMARY KEY (id);


--
-- Name: alpha_briefings alpha_briefings_batch_run_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_briefings
    ADD CONSTRAINT alpha_briefings_batch_run_id_key UNIQUE (batch_run_id);


--
-- Name: alpha_briefings alpha_briefings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_briefings
    ADD CONSTRAINT alpha_briefings_pkey PRIMARY KEY (id);


--
-- Name: alpha_buddy_events alpha_buddy_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_buddy_events
    ADD CONSTRAINT alpha_buddy_events_pkey PRIMARY KEY (id);


--
-- Name: alpha_budget_config alpha_budget_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_budget_config
    ADD CONSTRAINT alpha_budget_config_pkey PRIMARY KEY (id);


--
-- Name: alpha_budget_config alpha_budget_config_provider_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_budget_config
    ADD CONSTRAINT alpha_budget_config_provider_key UNIQUE (provider);


--
-- Name: alpha_cloud_costs alpha_cloud_costs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_cloud_costs
    ADD CONSTRAINT alpha_cloud_costs_pkey PRIMARY KEY (id);


--
-- Name: alpha_conversation_memory alpha_conversation_memory_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_conversation_memory
    ADD CONSTRAINT alpha_conversation_memory_pkey PRIMARY KEY (id);


--
-- Name: alpha_credit_balance alpha_credit_balance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_credit_balance
    ADD CONSTRAINT alpha_credit_balance_pkey PRIMARY KEY (id);


--
-- Name: alpha_dream_sessions alpha_dream_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_dream_sessions
    ADD CONSTRAINT alpha_dream_sessions_pkey PRIMARY KEY (id);


--
-- Name: alpha_dream_steps alpha_dream_steps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_dream_steps
    ADD CONSTRAINT alpha_dream_steps_pkey PRIMARY KEY (id);


--
-- Name: alpha_hardware_config alpha_hardware_config_node_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_hardware_config
    ADD CONSTRAINT alpha_hardware_config_node_name_key UNIQUE (node_name);


--
-- Name: alpha_hardware_config alpha_hardware_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_hardware_config
    ADD CONSTRAINT alpha_hardware_config_pkey PRIMARY KEY (id);


--
-- Name: alpha_honeypot_events alpha_honeypot_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_honeypot_events
    ADD CONSTRAINT alpha_honeypot_events_pkey PRIMARY KEY (id);


--
-- Name: alpha_node_registry alpha_node_registry_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_node_registry
    ADD CONSTRAINT alpha_node_registry_name_key UNIQUE (name);


--
-- Name: alpha_node_registry alpha_node_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_node_registry
    ADD CONSTRAINT alpha_node_registry_pkey PRIMARY KEY (id);


--
-- Name: alpha_overnight_approvals alpha_overnight_approvals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_overnight_approvals
    ADD CONSTRAINT alpha_overnight_approvals_pkey PRIMARY KEY (id);


--
-- Name: alpha_perplexity_credit alpha_perplexity_credit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_perplexity_credit
    ADD CONSTRAINT alpha_perplexity_credit_pkey PRIMARY KEY (id);


--
-- Name: alpha_power_config alpha_power_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_power_config
    ADD CONSTRAINT alpha_power_config_pkey PRIMARY KEY (id);


--
-- Name: alpha_power_daily alpha_power_daily_node_name_day_start_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_power_daily
    ADD CONSTRAINT alpha_power_daily_node_name_day_start_key UNIQUE (node_name, day_start);


--
-- Name: alpha_power_daily alpha_power_daily_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_power_daily
    ADD CONSTRAINT alpha_power_daily_pkey PRIMARY KEY (id);


--
-- Name: alpha_power_hourly alpha_power_hourly_node_name_hour_start_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_power_hourly
    ADD CONSTRAINT alpha_power_hourly_node_name_hour_start_key UNIQUE (node_name, hour_start);


--
-- Name: alpha_power_hourly alpha_power_hourly_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_power_hourly
    ADD CONSTRAINT alpha_power_hourly_pkey PRIMARY KEY (id);


--
-- Name: alpha_power_readings alpha_power_readings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_power_readings
    ADD CONSTRAINT alpha_power_readings_pkey PRIMARY KEY (id);


--
-- Name: alpha_profiles alpha_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_profiles
    ADD CONSTRAINT alpha_profiles_pkey PRIMARY KEY (id);


--
-- Name: alpha_projects alpha_projects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_projects
    ADD CONSTRAINT alpha_projects_pkey PRIMARY KEY (id);


--
-- Name: alpha_prompt_registry alpha_prompt_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_prompt_registry
    ADD CONSTRAINT alpha_prompt_registry_pkey PRIMARY KEY (id);


--
-- Name: alpha_prompt_registry alpha_prompt_registry_prompt_id_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_prompt_registry
    ADD CONSTRAINT alpha_prompt_registry_prompt_id_version_key UNIQUE (prompt_id, version);


--
-- Name: alpha_semantic_memory alpha_semantic_memory_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_semantic_memory
    ADD CONSTRAINT alpha_semantic_memory_pkey PRIMARY KEY (id);


--
-- Name: alpha_subscriptions alpha_subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_subscriptions
    ADD CONSTRAINT alpha_subscriptions_pkey PRIMARY KEY (id);


--
-- Name: alpha_task_events alpha_task_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_task_events
    ADD CONSTRAINT alpha_task_events_pkey PRIMARY KEY (id);


--
-- Name: alpha_task_graphs alpha_task_graphs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_task_graphs
    ADD CONSTRAINT alpha_task_graphs_pkey PRIMARY KEY (id);


--
-- Name: alpha_task_steps alpha_task_steps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_task_steps
    ADD CONSTRAINT alpha_task_steps_pkey PRIMARY KEY (id);


--
-- Name: alpha_users alpha_users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_users
    ADD CONSTRAINT alpha_users_email_key UNIQUE (email);


--
-- Name: alpha_users alpha_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_users
    ADD CONSTRAINT alpha_users_pkey PRIMARY KEY (id);


--
-- Name: alpha_watchdog_events alpha_watchdog_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_watchdog_events
    ADD CONSTRAINT alpha_watchdog_events_pkey PRIMARY KEY (id);


--
-- Name: alpha_workspace_users alpha_workspace_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_workspace_users
    ADD CONSTRAINT alpha_workspace_users_pkey PRIMARY KEY (workspace_id, user_id);


--
-- Name: alpha_workspaces alpha_workspaces_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_workspaces
    ADD CONSTRAINT alpha_workspaces_pkey PRIMARY KEY (id);


--
-- Name: alpha_workspaces alpha_workspaces_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_workspaces
    ADD CONSTRAINT alpha_workspaces_slug_key UNIQUE (slug);


--
-- Name: chat_messages chat_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_messages
    ADD CONSTRAINT chat_messages_pkey PRIMARY KEY (id);


--
-- Name: chat_threads chat_threads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_threads
    ADD CONSTRAINT chat_threads_pkey PRIMARY KEY (id);


--
-- Name: jarvis_request_log jarvis_request_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jarvis_request_log
    ADD CONSTRAINT jarvis_request_log_pkey PRIMARY KEY (id);


--
-- Name: pipeline_lessons pipeline_lessons_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_lessons
    ADD CONSTRAINT pipeline_lessons_pkey PRIMARY KEY (id);


--
-- Name: pipeline_metrics_brain pipeline_metrics_brain_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_metrics_brain
    ADD CONSTRAINT pipeline_metrics_brain_pkey PRIMARY KEY (id);


--
-- Name: pipeline_trust_scores pipeline_trust_scores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_trust_scores
    ADD CONSTRAINT pipeline_trust_scores_pkey PRIMARY KEY (category);


--
-- Name: secret_access_log secret_access_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.secret_access_log
    ADD CONSTRAINT secret_access_log_pkey PRIMARY KEY (id);


--
-- Name: alpha_semantic_memory uq_semantic_user_fact; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_semantic_memory
    ADD CONSTRAINT uq_semantic_user_fact UNIQUE (user_id, fact);


--
-- Name: vault_access_log vault_access_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_access_log
    ADD CONSTRAINT vault_access_log_pkey PRIMARY KEY (id);


--
-- Name: vault_chunks vault_chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_chunks
    ADD CONSTRAINT vault_chunks_pkey PRIMARY KEY (id);


--
-- Name: vault_document_permissions vault_document_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_document_permissions
    ADD CONSTRAINT vault_document_permissions_pkey PRIMARY KEY (document_id, user_id);


--
-- Name: vault_documents vault_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_documents
    ADD CONSTRAINT vault_documents_pkey PRIMARY KEY (id);


--
-- Name: vault_pipeline vault_pipeline_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_pipeline
    ADD CONSTRAINT vault_pipeline_pkey PRIMARY KEY (id);


--
-- Name: hnsw_alpha_memory_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX hnsw_alpha_memory_embedding ON public.alpha_conversation_memory USING hnsw (embedding public.vector_cosine_ops) WITH (m='16', ef_construction='64');


--
-- Name: idx_acm_tier_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_acm_tier_user ON public.alpha_conversation_memory USING btree (user_id, tier);


--
-- Name: idx_alpha_briefings_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alpha_briefings_date ON public.alpha_briefings USING btree (briefing_date DESC);


--
-- Name: idx_alpha_briefings_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alpha_briefings_source ON public.alpha_briefings USING btree (source);


--
-- Name: idx_alpha_briefings_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alpha_briefings_started_at ON public.alpha_briefings USING btree (started_at DESC);


--
-- Name: idx_alpha_memory_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alpha_memory_session ON public.alpha_conversation_memory USING btree (session_id);


--
-- Name: idx_alpha_memory_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alpha_memory_user ON public.alpha_conversation_memory USING btree (user_id);


--
-- Name: idx_alpha_memory_workspace; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alpha_memory_workspace ON public.alpha_conversation_memory USING btree (workspace_id);


--
-- Name: idx_approval_actor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_approval_actor ON public.alpha_approval_queue USING btree (actor_sub);


--
-- Name: idx_approval_pending_dedup; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_approval_pending_dedup ON public.alpha_approval_queue USING btree (actor_sub, parameters_hash) WHERE (status = 'pending'::text);


--
-- Name: idx_approval_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_approval_status ON public.alpha_approval_queue USING btree (status);


--
-- Name: idx_asm_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_asm_user ON public.alpha_semantic_memory USING btree (user_id);


--
-- Name: idx_audit_approval_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_approval_id ON public.alpha_approval_audit USING btree (approval_id);


--
-- Name: idx_audit_decided_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_decided_at ON public.alpha_approval_audit USING btree (decided_at);


--
-- Name: idx_buddy_events_unread; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_buddy_events_unread ON public.alpha_buddy_events USING btree (read, created_at DESC) WHERE (read = false);


--
-- Name: idx_buddy_events_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_buddy_events_user ON public.alpha_buddy_events USING btree (user_id, read, created_at DESC);


--
-- Name: idx_chat_messages_rating; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_messages_rating ON public.chat_messages USING btree (content_rating);


--
-- Name: idx_chat_messages_thread; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_messages_thread ON public.chat_messages USING btree (thread_id);


--
-- Name: idx_chat_threads_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_threads_owner ON public.chat_threads USING btree (owner_profile);


--
-- Name: idx_chat_threads_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_threads_user ON public.chat_threads USING btree (user_id) WHERE (archived_at IS NULL);


--
-- Name: idx_cloud_costs_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cloud_costs_created ON public.alpha_cloud_costs USING btree (created_at);


--
-- Name: idx_cloud_costs_provider; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cloud_costs_provider ON public.alpha_cloud_costs USING btree (provider);


--
-- Name: idx_cloud_costs_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cloud_costs_session ON public.alpha_cloud_costs USING btree (session_type);


--
-- Name: idx_dream_sessions_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dream_sessions_created ON public.alpha_dream_sessions USING btree (created_at DESC);


--
-- Name: idx_dream_sessions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dream_sessions_status ON public.alpha_dream_sessions USING btree (status);


--
-- Name: idx_dream_steps_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dream_steps_session ON public.alpha_dream_steps USING btree (session_id);


--
-- Name: idx_dream_steps_session_index; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_dream_steps_session_index ON public.alpha_dream_steps USING btree (session_id, step_index);


--
-- Name: idx_dream_steps_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dream_steps_status ON public.alpha_dream_steps USING btree (status);


--
-- Name: idx_honeypot_captured_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_honeypot_captured_at ON public.alpha_honeypot_events USING btree (captured_at DESC);


--
-- Name: idx_honeypot_trap_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_honeypot_trap_path ON public.alpha_honeypot_events USING btree (trap_path);


--
-- Name: idx_lessons_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lessons_category ON public.pipeline_lessons USING btree (category);


--
-- Name: idx_lessons_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lessons_embedding ON public.pipeline_lessons USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: idx_lessons_feature; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lessons_feature ON public.pipeline_lessons USING btree (feature_id);


--
-- Name: idx_metrics_name_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_metrics_name_time ON public.pipeline_metrics_brain USING btree (metric_name, recorded_at DESC);


--
-- Name: idx_node_registry_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_node_registry_active ON public.alpha_node_registry USING btree (is_active);


--
-- Name: idx_node_registry_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_node_registry_name ON public.alpha_node_registry USING btree (name);


--
-- Name: idx_power_daily_node_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_power_daily_node_time ON public.alpha_power_daily USING btree (node_name, day_start DESC);


--
-- Name: idx_power_hourly_node_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_power_hourly_node_time ON public.alpha_power_hourly USING btree (node_name, hour_start DESC);


--
-- Name: idx_power_readings_node_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_power_readings_node_time ON public.alpha_power_readings USING btree (node_name, recorded_at DESC);


--
-- Name: idx_profiles_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profiles_role ON public.alpha_profiles USING btree (role);


--
-- Name: idx_prompt_registry_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_prompt_registry_active ON public.alpha_prompt_registry USING btree (prompt_id, is_active) WHERE (is_active = true);


--
-- Name: idx_request_log_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_request_log_created ON public.jarvis_request_log USING btree (created_at DESC);


--
-- Name: idx_request_log_node; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_request_log_node ON public.jarvis_request_log USING btree (node);


--
-- Name: idx_request_log_route; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_request_log_route ON public.jarvis_request_log USING btree (route);


--
-- Name: idx_request_log_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_request_log_user ON public.jarvis_request_log USING btree (user_id);


--
-- Name: idx_request_log_workspace; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_request_log_workspace ON public.jarvis_request_log USING btree (workspace_id);


--
-- Name: idx_sal_accessed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sal_accessed ON public.secret_access_log USING btree (accessed_at DESC);


--
-- Name: idx_sal_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sal_key ON public.secret_access_log USING btree (key_name);


--
-- Name: idx_task_events_graph; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_events_graph ON public.alpha_task_events USING btree (graph_id);


--
-- Name: idx_task_events_unread; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_events_unread ON public.alpha_task_events USING btree (read, created_at);


--
-- Name: idx_tg_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tg_status ON public.alpha_task_graphs USING btree (status);


--
-- Name: idx_tg_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tg_type ON public.alpha_task_graphs USING btree (graph_type);


--
-- Name: idx_tg_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tg_user_status ON public.alpha_task_graphs USING btree (user_id, status);


--
-- Name: idx_ts_graph; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ts_graph ON public.alpha_task_steps USING btree (graph_id);


--
-- Name: idx_ts_graph_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ts_graph_order ON public.alpha_task_steps USING btree (graph_id, step_order);


--
-- Name: idx_ts_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ts_status ON public.alpha_task_steps USING btree (status);


--
-- Name: idx_vault_access_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vault_access_created ON public.vault_access_log USING btree (created_at DESC);


--
-- Name: idx_vault_access_doc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vault_access_doc ON public.vault_access_log USING btree (document_id);


--
-- Name: idx_vault_access_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vault_access_user ON public.vault_access_log USING btree (user_id);


--
-- Name: idx_vault_chunks_doc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vault_chunks_doc ON public.vault_chunks USING btree (document_id);


--
-- Name: idx_vault_chunks_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vault_chunks_embedding ON public.vault_chunks USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: idx_vault_pipeline_stage; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vault_pipeline_stage ON public.vault_pipeline USING btree (stage);


--
-- Name: idx_vault_pipeline_workspace; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vault_pipeline_workspace ON public.vault_pipeline USING btree (workspace_id);


--
-- Name: idx_watchdog_events_node; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_watchdog_events_node ON public.alpha_watchdog_events USING btree (node, created_at DESC);


--
-- Name: idx_watchdog_events_service_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_watchdog_events_service_time ON public.alpha_watchdog_events USING btree (service_name, created_at DESC);


--
-- Name: idx_watchdog_events_type_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_watchdog_events_type_time ON public.alpha_watchdog_events USING btree (event_type, created_at DESC);


--
-- Name: alpha_task_steps trg_enforce_child_step_tier; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_enforce_child_step_tier BEFORE INSERT OR UPDATE ON public.alpha_task_steps FOR EACH ROW EXECUTE FUNCTION public.enforce_child_step_tier();


--
-- Name: alpha_task_graphs trg_graphs_updated; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_graphs_updated BEFORE UPDATE ON public.alpha_task_graphs FOR EACH ROW EXECUTE FUNCTION public.update_task_timestamp();


--
-- Name: alpha_task_steps trg_steps_updated; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_steps_updated BEFORE UPDATE ON public.alpha_task_steps FOR EACH ROW EXECUTE FUNCTION public.update_task_timestamp();


--
-- Name: alpha_profiles trg_sync_profile_to_user; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_sync_profile_to_user AFTER INSERT OR DELETE OR UPDATE ON public.alpha_profiles FOR EACH ROW EXECUTE FUNCTION public.sync_profile_to_user();


--
-- Name: alpha_approval_audit alpha_approval_audit_approval_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_approval_audit
    ADD CONSTRAINT alpha_approval_audit_approval_id_fkey FOREIGN KEY (approval_id) REFERENCES public.alpha_approval_queue(id);


--
-- Name: alpha_conversation_memory alpha_conversation_memory_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_conversation_memory
    ADD CONSTRAINT alpha_conversation_memory_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.alpha_workspaces(id);


--
-- Name: alpha_dream_sessions alpha_dream_sessions_owner_profile_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_dream_sessions
    ADD CONSTRAINT alpha_dream_sessions_owner_profile_fkey FOREIGN KEY (owner_profile) REFERENCES public.alpha_profiles(id);


--
-- Name: alpha_dream_steps alpha_dream_steps_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_dream_steps
    ADD CONSTRAINT alpha_dream_steps_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.alpha_dream_sessions(id) ON DELETE CASCADE;


--
-- Name: alpha_task_events alpha_task_events_graph_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_task_events
    ADD CONSTRAINT alpha_task_events_graph_id_fkey FOREIGN KEY (graph_id) REFERENCES public.alpha_task_graphs(id) ON DELETE SET NULL;


--
-- Name: alpha_task_events alpha_task_events_step_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_task_events
    ADD CONSTRAINT alpha_task_events_step_id_fkey FOREIGN KEY (step_id) REFERENCES public.alpha_task_steps(id) ON DELETE SET NULL;


--
-- Name: alpha_task_graphs alpha_task_graphs_owner_profile_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_task_graphs
    ADD CONSTRAINT alpha_task_graphs_owner_profile_fkey FOREIGN KEY (owner_profile) REFERENCES public.alpha_profiles(id);


--
-- Name: alpha_task_steps alpha_task_steps_graph_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_task_steps
    ADD CONSTRAINT alpha_task_steps_graph_id_fkey FOREIGN KEY (graph_id) REFERENCES public.alpha_task_graphs(id) ON DELETE CASCADE;


--
-- Name: alpha_workspace_users alpha_workspace_users_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_workspace_users
    ADD CONSTRAINT alpha_workspace_users_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.alpha_users(id);


--
-- Name: alpha_workspace_users alpha_workspace_users_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_workspace_users
    ADD CONSTRAINT alpha_workspace_users_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.alpha_workspaces(id);


--
-- Name: chat_messages chat_messages_thread_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_messages
    ADD CONSTRAINT chat_messages_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES public.chat_threads(id) ON DELETE CASCADE;


--
-- Name: chat_threads chat_threads_owner_profile_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_threads
    ADD CONSTRAINT chat_threads_owner_profile_fkey FOREIGN KEY (owner_profile) REFERENCES public.alpha_profiles(id);


--
-- Name: vault_access_log vault_access_log_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_access_log
    ADD CONSTRAINT vault_access_log_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.vault_documents(id);


--
-- Name: vault_access_log vault_access_log_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_access_log
    ADD CONSTRAINT vault_access_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.alpha_users(id);


--
-- Name: vault_chunks vault_chunks_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_chunks
    ADD CONSTRAINT vault_chunks_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.vault_documents(id);


--
-- Name: vault_document_permissions vault_document_permissions_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_document_permissions
    ADD CONSTRAINT vault_document_permissions_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.vault_documents(id);


--
-- Name: vault_document_permissions vault_document_permissions_granted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_document_permissions
    ADD CONSTRAINT vault_document_permissions_granted_by_fkey FOREIGN KEY (granted_by) REFERENCES public.alpha_users(id);


--
-- Name: vault_document_permissions vault_document_permissions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_document_permissions
    ADD CONSTRAINT vault_document_permissions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.alpha_users(id);


--
-- Name: vault_documents vault_documents_uploaded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_documents
    ADD CONSTRAINT vault_documents_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES public.alpha_users(id);


--
-- Name: vault_documents vault_documents_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_documents
    ADD CONSTRAINT vault_documents_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.alpha_workspaces(id);


--
-- Name: vault_pipeline vault_pipeline_confirmed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_pipeline
    ADD CONSTRAINT vault_pipeline_confirmed_by_fkey FOREIGN KEY (confirmed_by) REFERENCES public.alpha_users(id);


--
-- Name: vault_pipeline vault_pipeline_uploaded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_pipeline
    ADD CONSTRAINT vault_pipeline_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES public.alpha_users(id);


--
-- Name: vault_pipeline vault_pipeline_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_pipeline
    ADD CONSTRAINT vault_pipeline_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.alpha_workspaces(id);


--
-- Name: alpha_conversation_memory; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.alpha_conversation_memory ENABLE ROW LEVEL SECURITY;

--
-- Name: alpha_dream_sessions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.alpha_dream_sessions ENABLE ROW LEVEL SECURITY;

--
-- Name: alpha_dream_steps; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.alpha_dream_steps ENABLE ROW LEVEL SECURITY;

--
-- Name: alpha_conversation_memory alpha_memory_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY alpha_memory_isolation ON public.alpha_conversation_memory USING (((user_id = current_setting('jarvis.current_user'::text, true)) OR (current_setting('jarvis.role'::text, true) = 'platform_admin'::text)));


--
-- Name: alpha_semantic_memory; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.alpha_semantic_memory ENABLE ROW LEVEL SECURITY;

--
-- Name: alpha_task_events; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.alpha_task_events ENABLE ROW LEVEL SECURITY;

--
-- Name: alpha_task_graphs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.alpha_task_graphs ENABLE ROW LEVEL SECURITY;

--
-- Name: alpha_task_steps; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.alpha_task_steps ENABLE ROW LEVEL SECURITY;

--
-- Name: alpha_watchdog_events; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.alpha_watchdog_events ENABLE ROW LEVEL SECURITY;

--
-- Name: chat_messages; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;

--
-- Name: chat_messages chat_messages_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY chat_messages_isolation ON public.chat_messages USING ((thread_id IN ( SELECT chat_threads.id
   FROM public.chat_threads
  WHERE (chat_threads.user_id = current_setting('rls.user_id'::text, true))))) WITH CHECK ((thread_id IN ( SELECT chat_threads.id
   FROM public.chat_threads
  WHERE (chat_threads.user_id = current_setting('rls.user_id'::text, true)))));


--
-- Name: chat_threads; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.chat_threads ENABLE ROW LEVEL SECURITY;

--
-- Name: chat_threads chat_threads_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY chat_threads_isolation ON public.chat_threads USING ((user_id = current_setting('rls.user_id'::text, true))) WITH CHECK ((user_id = current_setting('rls.user_id'::text, true)));


--
-- Name: chat_messages child_content_rating; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY child_content_rating ON public.chat_messages FOR SELECT USING (((current_setting('app.profile_role'::text, true) = 'admin'::text) OR (public.rating_level(content_rating) <= public.rating_level(current_setting('app.max_rating'::text, true)))));


--
-- Name: alpha_dream_sessions child_dream_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY child_dream_isolation ON public.alpha_dream_sessions USING ((current_setting('app.profile_role'::text, true) = 'admin'::text));


--
-- Name: alpha_dream_steps child_dream_step_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY child_dream_step_isolation ON public.alpha_dream_steps USING ((current_setting('app.profile_role'::text, true) = 'admin'::text));


--
-- Name: alpha_conversation_memory child_memory_rating; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY child_memory_rating ON public.alpha_conversation_memory FOR SELECT USING (((current_setting('app.profile_role'::text, true) = 'admin'::text) OR (public.rating_level(content_rating) <= public.rating_level(current_setting('app.max_rating'::text, true)))));


--
-- Name: alpha_conversation_memory child_memory_write; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY child_memory_write ON public.alpha_conversation_memory FOR INSERT WITH CHECK ((current_setting('app.profile_role'::text, true) = 'admin'::text));


--
-- Name: chat_messages child_message_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY child_message_isolation ON public.chat_messages USING (((current_setting('app.profile_role'::text, true) = 'admin'::text) OR (thread_id IN ( SELECT chat_threads.id
   FROM public.chat_threads
  WHERE (chat_threads.owner_profile = current_setting('app.profile_id'::text, true)))))) WITH CHECK (((current_setting('app.profile_role'::text, true) = 'admin'::text) OR (thread_id IN ( SELECT chat_threads.id
   FROM public.chat_threads
  WHERE (chat_threads.owner_profile = current_setting('app.profile_id'::text, true))))));


--
-- Name: alpha_task_graphs child_task_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY child_task_isolation ON public.alpha_task_graphs USING ((current_setting('app.profile_role'::text, true) = 'admin'::text));


--
-- Name: chat_threads child_thread_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY child_thread_isolation ON public.chat_threads USING (((current_setting('app.profile_role'::text, true) = 'admin'::text) OR (owner_profile = current_setting('app.profile_id'::text, true)))) WITH CHECK (((current_setting('app.profile_role'::text, true) = 'admin'::text) OR (owner_profile = current_setting('app.profile_id'::text, true))));


--
-- Name: alpha_semantic_memory semantic_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY semantic_isolation ON public.alpha_semantic_memory USING ((((user_id)::text = current_setting('jarvis.current_user'::text)) OR (current_setting('jarvis.is_admin'::text, true) = 'true'::text)));


--
-- Name: alpha_task_events task_events_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY task_events_read ON public.alpha_task_events USING (((current_setting('jarvis.role'::text, true) = 'platform_admin'::text) OR (current_setting('jarvis.current_user'::text, true) IS NOT NULL)));


--
-- Name: alpha_task_graphs task_graph_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY task_graph_isolation ON public.alpha_task_graphs USING (((user_id = current_setting('jarvis.current_user'::text, true)) OR (current_setting('jarvis.role'::text, true) = 'platform_admin'::text)));


--
-- Name: alpha_task_steps task_step_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY task_step_isolation ON public.alpha_task_steps USING (((user_id = current_setting('jarvis.current_user'::text, true)) OR (current_setting('jarvis.role'::text, true) = 'platform_admin'::text)));


--
-- Name: vault_access_log; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.vault_access_log ENABLE ROW LEVEL SECURITY;

--
-- Name: vault_access_log vault_access_log_admin; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY vault_access_log_admin ON public.vault_access_log USING ((current_setting('app.profile_role'::text, true) = 'admin'::text)) WITH CHECK ((current_setting('app.profile_role'::text, true) = 'admin'::text));


--
-- Name: vault_documents; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.vault_documents ENABLE ROW LEVEL SECURITY;

--
-- Name: vault_documents vault_documents_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY vault_documents_read ON public.vault_documents FOR SELECT USING (((classification <> '50_SECRETS'::text) AND (((current_setting('app.profile_role'::text, true) = 'admin'::text) AND (classification = ANY (ARRAY['10_PUBLIC'::text, '15_KIDS'::text, '20_PROJECTS'::text, '30_FINANCE'::text, '40_PRIVATE'::text]))) OR ((current_setting('app.profile_role'::text, true) = 'child'::text) AND (classification = ANY (ARRAY['10_PUBLIC'::text, '15_KIDS'::text]))))));


--
-- Name: vault_documents vault_documents_write; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY vault_documents_write ON public.vault_documents USING ((current_setting('app.profile_role'::text, true) = 'admin'::text)) WITH CHECK ((current_setting('app.profile_role'::text, true) = 'admin'::text));


--
-- Name: vault_pipeline; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.vault_pipeline ENABLE ROW LEVEL SECURITY;

--
-- Name: vault_pipeline vault_pipeline_admin; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY vault_pipeline_admin ON public.vault_pipeline USING ((current_setting('app.profile_role'::text, true) = 'admin'::text)) WITH CHECK ((current_setting('app.profile_role'::text, true) = 'admin'::text));


--
-- Name: alpha_watchdog_events watchdog_events_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY watchdog_events_read ON public.alpha_watchdog_events FOR SELECT USING (true);


--
-- Name: alpha_watchdog_events watchdog_events_system_write; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY watchdog_events_system_write ON public.alpha_watchdog_events FOR INSERT WITH CHECK ((current_setting('rls.user_id'::text, true) = 'system'::text));


--
-- PostgreSQL database dump complete
--

\unrestrict NhWdsYDjMFp0042UcSXrXQ3vsUjf04SOUCygnPhlc2DxK4ZsZOuc9m9yWfM8qVf

