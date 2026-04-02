--
-- PostgreSQL database dump
--

\restrict ienNfznQkhEO7TY24mML4hnF0ae1ZlxAQP5bgFKNLRwRxbOBNs1rYzK9FQmn9jN

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
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


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
    CONSTRAINT alpha_buddy_events_event_type_check CHECK ((event_type = ANY (ARRAY['alert'::text, 'reminder'::text, 'suggestion'::text, 'system'::text])))
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
    CONSTRAINT alpha_conversation_memory_role_check CHECK ((role = ANY (ARRAY['user'::text, 'assistant'::text, 'system'::text])))
);


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
-- Name: alpha_task_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_task_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    event_type text NOT NULL,
    graph_id uuid,
    step_id uuid,
    message text NOT NULL,
    priority text DEFAULT 'normal'::text NOT NULL,
    read boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT alpha_task_events_event_type_check CHECK ((event_type = ANY (ARRAY['graph_complete'::text, 'graph_halted'::text, 'step_failed'::text, 'step_retrying'::text, 'ci_required'::text, 'approval_required'::text]))),
    CONSTRAINT alpha_task_events_priority_check CHECK ((priority = ANY (ARRAY['low'::text, 'normal'::text, 'high'::text, 'critical'::text])))
);


--
-- Name: alpha_task_graphs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_task_graphs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    title text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    priority integer DEFAULT 3 NOT NULL,
    created_by uuid NOT NULL,
    workspace_id text,
    parent_graph_id uuid,
    checkpoint_step_id uuid,
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    interrupted_at timestamp without time zone,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    CONSTRAINT alpha_task_graphs_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'completed'::text, 'failed'::text, 'interrupted'::text])))
);


--
-- Name: alpha_task_steps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alpha_task_steps (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    graph_id uuid NOT NULL,
    step_type text NOT NULL,
    step_index integer NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    input jsonb DEFAULT '{}'::jsonb,
    output jsonb DEFAULT '{}'::jsonb,
    error text,
    agent_label text,
    model_used text,
    tokens_used integer,
    requires_approval boolean DEFAULT false NOT NULL,
    approved_by text,
    approved_at timestamp without time zone,
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    retry_count integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    CONSTRAINT alpha_task_steps_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'completed'::text, 'failed'::text, 'interrupted'::text, 'awaiting_approval'::text]))),
    CONSTRAINT alpha_task_steps_step_type_check CHECK ((step_type = ANY (ARRAY['llm'::text, 'code'::text, 'tool'::text, 'human_approval'::text, 'memory_read'::text, 'memory_write'::text, 'subgraph'::text, 'notification'::text])))
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
    workspace_id text,
    uploaded_by text,
    filename text NOT NULL,
    content_type text NOT NULL,
    size_bytes integer,
    classification text DEFAULT '40_PRIVATE'::text NOT NULL,
    storage_tier text DEFAULT 'hot'::text NOT NULL,
    local_path text,
    archive_path text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: vault_pipeline; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vault_pipeline (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workspace_id text,
    uploaded_by text,
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


--
-- Name: alpha_node_registry id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_node_registry ALTER COLUMN id SET DEFAULT nextval('public.alpha_node_registry_id_seq'::regclass);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: alpha_buddy_events alpha_buddy_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_buddy_events
    ADD CONSTRAINT alpha_buddy_events_pkey PRIMARY KEY (id);


--
-- Name: alpha_conversation_memory alpha_conversation_memory_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_conversation_memory
    ADD CONSTRAINT alpha_conversation_memory_pkey PRIMARY KEY (id);


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
-- Name: alpha_semantic_memory alpha_semantic_memory_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_semantic_memory
    ADD CONSTRAINT alpha_semantic_memory_pkey PRIMARY KEY (id);


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
-- Name: jarvis_request_log jarvis_request_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jarvis_request_log
    ADD CONSTRAINT jarvis_request_log_pkey PRIMARY KEY (id);


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
-- Name: idx_asm_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_asm_user ON public.alpha_semantic_memory USING btree (user_id);


--
-- Name: idx_buddy_events_unread; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_buddy_events_unread ON public.alpha_buddy_events USING btree (read, created_at DESC) WHERE (read = false);


--
-- Name: idx_buddy_events_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_buddy_events_user ON public.alpha_buddy_events USING btree (user_id, read, created_at DESC);


--
-- Name: idx_node_registry_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_node_registry_active ON public.alpha_node_registry USING btree (is_active);


--
-- Name: idx_node_registry_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_node_registry_name ON public.alpha_node_registry USING btree (name);


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
-- Name: idx_task_events_graph_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_events_graph_id ON public.alpha_task_events USING btree (graph_id);


--
-- Name: idx_task_events_read_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_events_read_created_at ON public.alpha_task_events USING btree (read, created_at);


--
-- Name: idx_task_graphs_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_graphs_created_by ON public.alpha_task_graphs USING btree (created_by);


--
-- Name: idx_task_graphs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_graphs_status ON public.alpha_task_graphs USING btree (status);


--
-- Name: idx_task_steps_graph; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_steps_graph ON public.alpha_task_steps USING btree (graph_id);


--
-- Name: idx_task_steps_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_steps_status ON public.alpha_task_steps USING btree (status);


--
-- Name: idx_task_steps_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_steps_type ON public.alpha_task_steps USING btree (step_type);


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
-- Name: alpha_conversation_memory alpha_conversation_memory_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_conversation_memory
    ADD CONSTRAINT alpha_conversation_memory_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.alpha_workspaces(id);


--
-- Name: alpha_task_graphs alpha_task_graphs_parent_graph_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alpha_task_graphs
    ADD CONSTRAINT alpha_task_graphs_parent_graph_id_fkey FOREIGN KEY (parent_graph_id) REFERENCES public.alpha_task_graphs(id);


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
-- Name: alpha_task_graphs graph_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY graph_isolation ON public.alpha_task_graphs USING (((created_by)::text = current_setting('jarvis.current_user'::text, true)));


--
-- Name: alpha_semantic_memory semantic_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY semantic_isolation ON public.alpha_semantic_memory USING ((((user_id)::text = current_setting('jarvis.current_user'::text)) OR (current_setting('jarvis.is_admin'::text, true) = 'true'::text)));


--
-- Name: alpha_task_steps step_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY step_isolation ON public.alpha_task_steps USING ((graph_id IN ( SELECT alpha_task_graphs.id
   FROM public.alpha_task_graphs
  WHERE ((alpha_task_graphs.created_by)::text = current_setting('jarvis.current_user'::text, true)))));


--
-- Name: alpha_task_events task_events_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY task_events_isolation ON public.alpha_task_events USING ((current_setting('jarvis.current_user'::text, true) = 'admin'::text));


--
-- Name: vault_documents vault_child_filter; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY vault_child_filter ON public.vault_documents FOR SELECT USING ((NOT (( SELECT alpha_users.is_child
   FROM public.alpha_users
  WHERE (alpha_users.id = current_setting('jarvis.current_user'::text, true))) AND (classification <> ALL (ARRAY['10_PUBLIC'::text, '20_PROJECTS'::text])))));


--
-- Name: vault_documents; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.vault_documents ENABLE ROW LEVEL SECURITY;

--
-- PostgreSQL database dump complete
--

\unrestrict ienNfznQkhEO7TY24mML4hnF0ae1ZlxAQP5bgFKNLRwRxbOBNs1rYzK9FQmn9jN

