-- ADR-0029: temporal graph memory first slice.
-- Adds reviewed, append-first node/edge graph storage with proposal-bound
-- writes, audit provenance, bounded read functions, and FORCE RLS.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260622100000);

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.alpha_memory_graph_nodes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    principal_id        UUID NOT NULL,
    node_type           TEXT NOT NULL
                        CHECK (node_type IN (
                            'person',
                            'project',
                            'place',
                            'organization',
                            'preference',
                            'fact',
                            'task',
                            'relationship',
                            'other'
                        )),
    external_ref_type   TEXT,
    external_ref_id     TEXT,
    label_hash          TEXT NOT NULL,
    label_preview       TEXT NOT NULL,
    properties          JSONB NOT NULL DEFAULT '{}'::jsonb,
    source              TEXT NOT NULL DEFAULT 'operator'
                        CHECK (source IN (
                            'operator',
                            'explicit',
                            'dream',
                            'buddy',
                            'spark',
                            'import'
                        )),
    provenance          JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence          DOUBLE PRECISION NOT NULL DEFAULT 0.8
                        CHECK (confidence >= 0 AND confidence <= 1),
    review_status       TEXT NOT NULL DEFAULT 'active'
                        CHECK (review_status IN (
                            'active',
                            'pending_review',
                            'rejected',
                            'archived'
                        )),
    valid_from          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_to            TIMESTAMPTZ,
    superseded_by       UUID REFERENCES public.alpha_memory_graph_nodes(id)
                        ON DELETE RESTRICT,
    created_by          TEXT NOT NULL,
    reviewed_by         TEXT,
    reviewed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_memory_graph_nodes_label_hash_check
        CHECK (label_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT alpha_memory_graph_nodes_label_preview_check
        CHECK (char_length(btrim(label_preview)) BETWEEN 1 AND 160),
    CONSTRAINT alpha_memory_graph_nodes_created_by_check
        CHECK (char_length(btrim(created_by)) BETWEEN 1 AND 128),
    CONSTRAINT alpha_memory_graph_nodes_valid_window_check
        CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE TABLE IF NOT EXISTS public.alpha_memory_graph_edges (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    principal_id        UUID NOT NULL,
    from_node_id        UUID NOT NULL REFERENCES public.alpha_memory_graph_nodes(id)
                        ON DELETE RESTRICT,
    to_node_id          UUID NOT NULL REFERENCES public.alpha_memory_graph_nodes(id)
                        ON DELETE RESTRICT,
    edge_type           TEXT NOT NULL
                        CHECK (edge_type IN (
                            'knows',
                            'works_on',
                            'belongs_to',
                            'prefers',
                            'related_to',
                            'parent_of',
                            'child_of',
                            'depends_on',
                            'owns',
                            'other'
                        )),
    properties          JSONB NOT NULL DEFAULT '{}'::jsonb,
    source              TEXT NOT NULL DEFAULT 'operator'
                        CHECK (source IN (
                            'operator',
                            'explicit',
                            'dream',
                            'buddy',
                            'spark',
                            'import'
                        )),
    provenance          JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence          DOUBLE PRECISION NOT NULL DEFAULT 0.8
                        CHECK (confidence >= 0 AND confidence <= 1),
    review_status       TEXT NOT NULL DEFAULT 'active'
                        CHECK (review_status IN (
                            'active',
                            'pending_review',
                            'rejected',
                            'archived'
                        )),
    valid_from          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_to            TIMESTAMPTZ,
    superseded_by       UUID REFERENCES public.alpha_memory_graph_edges(id)
                        ON DELETE RESTRICT,
    created_by          TEXT NOT NULL,
    reviewed_by         TEXT,
    reviewed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_memory_graph_edges_distinct_nodes_check
        CHECK (from_node_id <> to_node_id),
    CONSTRAINT alpha_memory_graph_edges_created_by_check
        CHECK (char_length(btrim(created_by)) BETWEEN 1 AND 128),
    CONSTRAINT alpha_memory_graph_edges_valid_window_check
        CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE TABLE IF NOT EXISTS public.alpha_memory_graph_proposals (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    principal_id        UUID NOT NULL,
    proposed_action     TEXT NOT NULL
                        CHECK (proposed_action IN (
                            'create_node',
                            'create_edge',
                            'archive_node',
                            'archive_edge'
                        )),
    object_type         TEXT NOT NULL CHECK (object_type IN ('node', 'edge')),
    payload             JSONB NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending_review'
                        CHECK (status IN (
                            'pending_review',
                            'queued',
                            'approved',
                            'executed',
                            'rejected',
                            'stale'
                        )),
    approval_queue_id   UUID REFERENCES public.alpha_approval_queue(id)
                        ON DELETE RESTRICT,
    parameters_hash     TEXT NOT NULL,
    source_surface      TEXT NOT NULL DEFAULT 'helm',
    reason              TEXT,
    created_by          TEXT NOT NULL,
    executed_by         TEXT,
    executed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_memory_graph_proposals_hash_check
        CHECK (parameters_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT alpha_memory_graph_proposals_payload_object_check
        CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT alpha_memory_graph_proposals_action_type_check
        CHECK (
            (object_type = 'node' AND proposed_action IN ('create_node', 'archive_node'))
            OR
            (object_type = 'edge' AND proposed_action IN ('create_edge', 'archive_edge'))
        ),
    CONSTRAINT alpha_memory_graph_proposals_created_by_check
        CHECK (char_length(btrim(created_by)) BETWEEN 1 AND 128)
);

CREATE TABLE IF NOT EXISTS public.alpha_memory_graph_audit (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    principal_id        UUID NOT NULL,
    object_type         TEXT NOT NULL CHECK (object_type IN ('node', 'edge')),
    object_id           UUID NOT NULL,
    operation           TEXT NOT NULL
                        CHECK (operation IN (
                            'create_node',
                            'create_edge',
                            'archive_node',
                            'archive_edge',
                            'supersede_node',
                            'supersede_edge'
                        )),
    proposal_id         UUID REFERENCES public.alpha_memory_graph_proposals(id)
                        ON DELETE RESTRICT,
    approval_queue_id   UUID REFERENCES public.alpha_approval_queue(id)
                        ON DELETE RESTRICT,
    actor               TEXT NOT NULL,
    source_surface      TEXT NOT NULL,
    reason              TEXT,
    old_version         JSONB,
    new_version         JSONB,
    rollback_payload    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_memory_graph_audit_actor_check
        CHECK (char_length(btrim(actor)) BETWEEN 1 AND 128)
);

CREATE INDEX IF NOT EXISTS idx_alpha_memory_graph_nodes_current
    ON public.alpha_memory_graph_nodes(
        principal_id,
        node_type,
        updated_at DESC
    )
    WHERE review_status = 'active' AND valid_to IS NULL;
CREATE INDEX IF NOT EXISTS idx_alpha_memory_graph_nodes_asof
    ON public.alpha_memory_graph_nodes(principal_id, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_alpha_memory_graph_nodes_superseded
    ON public.alpha_memory_graph_nodes(superseded_by)
    WHERE superseded_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_alpha_memory_graph_edges_current
    ON public.alpha_memory_graph_edges(
        principal_id,
        edge_type,
        updated_at DESC
    )
    WHERE review_status = 'active' AND valid_to IS NULL;
CREATE INDEX IF NOT EXISTS idx_alpha_memory_graph_edges_asof
    ON public.alpha_memory_graph_edges(principal_id, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_alpha_memory_graph_edges_nodes
    ON public.alpha_memory_graph_edges(principal_id, from_node_id, to_node_id);
CREATE INDEX IF NOT EXISTS idx_alpha_memory_graph_proposals_status
    ON public.alpha_memory_graph_proposals(principal_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_memory_graph_proposals_queue
    ON public.alpha_memory_graph_proposals(approval_queue_id)
    WHERE approval_queue_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_alpha_memory_graph_audit_object
    ON public.alpha_memory_graph_audit(principal_id, object_type, object_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_memory_graph_audit_created
    ON public.alpha_memory_graph_audit(created_at DESC);

ALTER TABLE public.alpha_memory_graph_nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_memory_graph_nodes FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_memory_graph_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_memory_graph_edges FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_memory_graph_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_memory_graph_proposals FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_memory_graph_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_memory_graph_audit FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS alpha_memory_graph_nodes_isolation
    ON public.alpha_memory_graph_nodes;
CREATE POLICY alpha_memory_graph_nodes_isolation
    ON public.alpha_memory_graph_nodes
    FOR ALL
    USING (
        principal_id::text = current_setting('rls.user_id', true)
        OR current_setting('rls.role', true) = 'platform_admin'
    )
    WITH CHECK (
        principal_id::text = current_setting('rls.user_id', true)
        OR current_setting('rls.role', true) = 'platform_admin'
    );

DROP POLICY IF EXISTS alpha_memory_graph_edges_isolation
    ON public.alpha_memory_graph_edges;
CREATE POLICY alpha_memory_graph_edges_isolation
    ON public.alpha_memory_graph_edges
    FOR ALL
    USING (
        principal_id::text = current_setting('rls.user_id', true)
        OR current_setting('rls.role', true) = 'platform_admin'
    )
    WITH CHECK (
        principal_id::text = current_setting('rls.user_id', true)
        OR current_setting('rls.role', true) = 'platform_admin'
    );

DROP POLICY IF EXISTS alpha_memory_graph_proposals_isolation
    ON public.alpha_memory_graph_proposals;
CREATE POLICY alpha_memory_graph_proposals_isolation
    ON public.alpha_memory_graph_proposals
    FOR ALL
    USING (
        principal_id::text = current_setting('rls.user_id', true)
        OR current_setting('rls.role', true) = 'platform_admin'
    )
    WITH CHECK (
        principal_id::text = current_setting('rls.user_id', true)
        OR current_setting('rls.role', true) = 'platform_admin'
    );

DROP POLICY IF EXISTS alpha_memory_graph_audit_isolation
    ON public.alpha_memory_graph_audit;
CREATE POLICY alpha_memory_graph_audit_isolation
    ON public.alpha_memory_graph_audit
    FOR ALL
    USING (
        principal_id::text = current_setting('rls.user_id', true)
        OR current_setting('rls.role', true) = 'platform_admin'
    )
    WITH CHECK (
        principal_id::text = current_setting('rls.user_id', true)
        OR current_setting('rls.role', true) = 'platform_admin'
    );

CREATE OR REPLACE FUNCTION public.propose_memory_graph_write(
    p_principal_id uuid,
    p_proposed_action text,
    p_object_type text,
    p_payload jsonb,
    p_source_surface text,
    p_created_by text,
    p_reason text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
    v_action text := lower(btrim(p_proposed_action));
    v_object_type text := lower(btrim(p_object_type));
    v_payload jsonb := COALESCE(p_payload, '{}'::jsonb);
    v_source_surface text := COALESCE(NULLIF(btrim(p_source_surface), ''), 'helm');
    v_created_by text := COALESCE(NULLIF(btrim(p_created_by), ''), 'unknown');
    v_parameters_hash text;
    v_proposal_id uuid;
    v_queue_id uuid;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    IF v_action NOT IN ('create_node', 'create_edge', 'archive_node', 'archive_edge') THEN
        RETURN jsonb_build_object('status', 'not_queued', 'reason', 'invalid_action');
    END IF;
    IF v_object_type NOT IN ('node', 'edge') THEN
        RETURN jsonb_build_object('status', 'not_queued', 'reason', 'invalid_object_type');
    END IF;
    IF jsonb_typeof(v_payload) <> 'object' OR octet_length(v_payload::text) > 8192 THEN
        RETURN jsonb_build_object('status', 'not_queued', 'reason', 'invalid_payload');
    END IF;
    IF (v_object_type = 'node' AND v_action NOT IN ('create_node', 'archive_node'))
       OR (v_object_type = 'edge' AND v_action NOT IN ('create_edge', 'archive_edge')) THEN
        RETURN jsonb_build_object('status', 'not_queued', 'reason', 'action_object_mismatch');
    END IF;

    v_parameters_hash := encode(digest(
        jsonb_build_object(
            'version', 1,
            'principal_id', p_principal_id::text,
            'action', v_action,
            'object_type', v_object_type,
            'payload', v_payload
        )::text,
        'sha256'
    ), 'hex');

    INSERT INTO public.alpha_memory_graph_proposals (
        principal_id,
        proposed_action,
        object_type,
        payload,
        status,
        parameters_hash,
        source_surface,
        reason,
        created_by
    )
    VALUES (
        p_principal_id,
        v_action,
        v_object_type,
        v_payload,
        'pending_review',
        v_parameters_hash,
        v_source_surface,
        NULLIF(btrim(COALESCE(p_reason, '')), ''),
        v_created_by
    )
    RETURNING id INTO v_proposal_id;

    BEGIN
        SELECT public.enqueue_approval_request(
            ARRAY['memory_graph_reviewed_write']::text[],
            'T5',
            v_created_by,
            'user',
            'Temporal graph memory reviewed write: ' || v_action,
            v_parameters_hash,
            'memory-graph:' || v_proposal_id::text || ':' || gen_random_uuid()::text
        )
        INTO v_queue_id;
    EXCEPTION
        WHEN unique_violation THEN
            SELECT id
              INTO v_queue_id
              FROM public.alpha_approval_queue
             WHERE actor_sub = v_created_by
               AND parameters_hash = v_parameters_hash
               AND status = 'pending'
             ORDER BY requested_at DESC
             LIMIT 1;
    END;

    IF v_queue_id IS NULL THEN
        RAISE EXCEPTION 'MEMORY_GRAPH_APPROVAL_QUEUE_FAILED proposal_id=%', v_proposal_id
            USING ERRCODE = 'P0040';
    END IF;

    UPDATE public.alpha_memory_graph_proposals
       SET approval_queue_id = v_queue_id,
           status = 'queued',
           updated_at = NOW()
     WHERE id = v_proposal_id;

    RETURN jsonb_build_object(
        'status', 'queued',
        'proposal_id', v_proposal_id::text,
        'approval_queue_id', v_queue_id::text,
        'parameters_hash', v_parameters_hash
    );
END;
$function$;

CREATE OR REPLACE FUNCTION public.execute_memory_graph_proposal(
    p_proposal_id uuid,
    p_approval_queue_id uuid,
    p_executed_by text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
    v_proposal public.alpha_memory_graph_proposals%ROWTYPE;
    v_approval public.alpha_approval_queue%ROWTYPE;
    v_payload jsonb;
    v_actor text := COALESCE(NULLIF(btrim(p_executed_by), ''), 'unknown');
    v_node public.alpha_memory_graph_nodes%ROWTYPE;
    v_edge public.alpha_memory_graph_edges%ROWTYPE;
    v_old jsonb;
    v_new jsonb;
    v_object_id uuid;
    v_label_preview text;
    v_label_hash text;
    v_properties jsonb;
    v_provenance jsonb;
    v_source text;
    v_confidence double precision;
    v_valid_from timestamptz;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    SELECT *
      INTO v_proposal
      FROM public.alpha_memory_graph_proposals
     WHERE id = p_proposal_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'MEMORY_GRAPH_PROPOSAL_NOT_FOUND proposal_id=%', p_proposal_id
            USING ERRCODE = 'P0041';
    END IF;

    IF v_proposal.status = 'executed' THEN
        RAISE EXCEPTION 'MEMORY_GRAPH_PROPOSAL_ALREADY_EXECUTED proposal_id=%', p_proposal_id
            USING ERRCODE = 'P0042';
    END IF;

    IF v_proposal.status IN ('rejected', 'stale') THEN
        RAISE EXCEPTION 'MEMORY_GRAPH_PROPOSAL_TERMINAL proposal_id=% status=%',
            p_proposal_id,
            v_proposal.status
            USING ERRCODE = 'P0043';
    END IF;

    IF v_proposal.approval_queue_id IS DISTINCT FROM p_approval_queue_id THEN
        RAISE EXCEPTION 'MEMORY_GRAPH_APPROVAL_TOKEN_MISMATCH proposal_id=%', p_proposal_id
            USING ERRCODE = 'P0044';
    END IF;

    SELECT *
      INTO v_approval
      FROM public.alpha_approval_queue
     WHERE id = p_approval_queue_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'MEMORY_GRAPH_APPROVAL_NOT_FOUND proposal_id=% queue_id=%',
            p_proposal_id,
            p_approval_queue_id
            USING ERRCODE = 'P0045';
    END IF;

    IF v_approval.status <> 'approved'
       OR v_approval.parameters_hash <> v_proposal.parameters_hash
       OR v_approval.risk_tier <> 'T5'
       OR NOT ('memory_graph_reviewed_write' = ANY(v_approval.action_class))
       OR v_approval.expires_at IS NULL
       OR v_approval.expires_at <= NOW() THEN
        RAISE EXCEPTION 'MEMORY_GRAPH_APPROVAL_NOT_USABLE proposal_id=% queue_id=% status=%',
            p_proposal_id,
            p_approval_queue_id,
            v_approval.status
            USING ERRCODE = 'P0046';
    END IF;

    v_payload := v_proposal.payload;
    v_properties := CASE
        WHEN jsonb_typeof(v_payload->'properties') = 'object' THEN v_payload->'properties'
        ELSE '{}'::jsonb
    END;
    v_provenance := CASE
        WHEN jsonb_typeof(v_payload->'provenance') = 'object' THEN v_payload->'provenance'
        ELSE '{}'::jsonb
    END || jsonb_build_object(
        'proposal_id', p_proposal_id::text,
        'approval_queue_id', p_approval_queue_id::text
    );
    v_source := COALESCE(NULLIF(lower(btrim(v_payload->>'source')), ''), 'operator');
    v_confidence := COALESCE((v_payload->>'confidence')::double precision, 0.8);
    v_valid_from := COALESCE((v_payload->>'valid_from')::timestamptz, NOW());

    IF v_proposal.proposed_action = 'create_node' THEN
        v_label_preview := btrim(v_payload->>'label_preview');
        IF v_label_preview IS NULL OR char_length(v_label_preview) < 1 THEN
            RAISE EXCEPTION 'MEMORY_GRAPH_NODE_LABEL_REQUIRED proposal_id=%', p_proposal_id
                USING ERRCODE = 'P0047';
        END IF;
        v_label_hash := COALESCE(
            NULLIF(lower(btrim(v_payload->>'label_hash')), ''),
            encode(digest(lower(v_label_preview), 'sha256'), 'hex')
        );

        INSERT INTO public.alpha_memory_graph_nodes (
            principal_id,
            node_type,
            external_ref_type,
            external_ref_id,
            label_hash,
            label_preview,
            properties,
            source,
            provenance,
            confidence,
            review_status,
            valid_from,
            created_by,
            reviewed_by,
            reviewed_at
        )
        VALUES (
            v_proposal.principal_id,
            lower(btrim(v_payload->>'node_type')),
            NULLIF(btrim(COALESCE(v_payload->>'external_ref_type', '')), ''),
            NULLIF(btrim(COALESCE(v_payload->>'external_ref_id', '')), ''),
            v_label_hash,
            v_label_preview,
            v_properties,
            v_source,
            v_provenance,
            v_confidence,
            'active',
            v_valid_from,
            v_actor,
            v_actor,
            NOW()
        )
        RETURNING * INTO v_node;
        v_object_id := v_node.id;
        v_new := to_jsonb(v_node);
    ELSIF v_proposal.proposed_action = 'create_edge' THEN
        IF NOT EXISTS (
            SELECT 1
              FROM public.alpha_memory_graph_nodes n
             WHERE n.id = (v_payload->>'from_node_id')::uuid
               AND n.principal_id = v_proposal.principal_id
               AND n.review_status = 'active'
               AND n.valid_to IS NULL
        ) OR NOT EXISTS (
            SELECT 1
              FROM public.alpha_memory_graph_nodes n
             WHERE n.id = (v_payload->>'to_node_id')::uuid
               AND n.principal_id = v_proposal.principal_id
               AND n.review_status = 'active'
               AND n.valid_to IS NULL
        ) THEN
            UPDATE public.alpha_memory_graph_proposals
               SET status = 'stale',
                   updated_at = NOW()
             WHERE id = p_proposal_id;
            RETURN jsonb_build_object(
                'status', 'stale',
                'proposal_id', p_proposal_id::text,
                'reason', 'node_boundary_or_state_drift'
            );
        END IF;

        INSERT INTO public.alpha_memory_graph_edges (
            principal_id,
            from_node_id,
            to_node_id,
            edge_type,
            properties,
            source,
            provenance,
            confidence,
            review_status,
            valid_from,
            created_by,
            reviewed_by,
            reviewed_at
        )
        VALUES (
            v_proposal.principal_id,
            (v_payload->>'from_node_id')::uuid,
            (v_payload->>'to_node_id')::uuid,
            lower(btrim(v_payload->>'edge_type')),
            v_properties,
            v_source,
            v_provenance,
            v_confidence,
            'active',
            v_valid_from,
            v_actor,
            v_actor,
            NOW()
        )
        RETURNING * INTO v_edge;
        v_object_id := v_edge.id;
        v_new := to_jsonb(v_edge);
    ELSIF v_proposal.proposed_action = 'archive_node' THEN
        SELECT *
          INTO v_node
          FROM public.alpha_memory_graph_nodes
         WHERE id = (v_payload->>'target_id')::uuid
           AND principal_id = v_proposal.principal_id
           AND review_status = 'active'
         FOR UPDATE;
        IF NOT FOUND THEN
            UPDATE public.alpha_memory_graph_proposals
               SET status = 'stale',
                   updated_at = NOW()
             WHERE id = p_proposal_id;
            RETURN jsonb_build_object(
                'status', 'stale',
                'proposal_id', p_proposal_id::text,
                'reason', 'node_not_active'
            );
        END IF;
        v_old := to_jsonb(v_node);
        UPDATE public.alpha_memory_graph_nodes
           SET review_status = 'archived',
               valid_to = COALESCE(valid_to, NOW()),
               updated_at = NOW(),
               reviewed_by = v_actor,
               reviewed_at = NOW()
         WHERE id = v_node.id
         RETURNING * INTO v_node;
        v_object_id := v_node.id;
        v_new := to_jsonb(v_node);
    ELSIF v_proposal.proposed_action = 'archive_edge' THEN
        SELECT *
          INTO v_edge
          FROM public.alpha_memory_graph_edges
         WHERE id = (v_payload->>'target_id')::uuid
           AND principal_id = v_proposal.principal_id
           AND review_status = 'active'
         FOR UPDATE;
        IF NOT FOUND THEN
            UPDATE public.alpha_memory_graph_proposals
               SET status = 'stale',
                   updated_at = NOW()
             WHERE id = p_proposal_id;
            RETURN jsonb_build_object(
                'status', 'stale',
                'proposal_id', p_proposal_id::text,
                'reason', 'edge_not_active'
            );
        END IF;
        v_old := to_jsonb(v_edge);
        UPDATE public.alpha_memory_graph_edges
           SET review_status = 'archived',
               valid_to = COALESCE(valid_to, NOW()),
               updated_at = NOW(),
               reviewed_by = v_actor,
               reviewed_at = NOW()
         WHERE id = v_edge.id
         RETURNING * INTO v_edge;
        v_object_id := v_edge.id;
        v_new := to_jsonb(v_edge);
    ELSE
        RAISE EXCEPTION 'MEMORY_GRAPH_UNSUPPORTED_ACTION action=%', v_proposal.proposed_action
            USING ERRCODE = 'P0048';
    END IF;

    INSERT INTO public.alpha_memory_graph_audit (
        principal_id,
        object_type,
        object_id,
        operation,
        proposal_id,
        approval_queue_id,
        actor,
        source_surface,
        reason,
        old_version,
        new_version,
        rollback_payload
    )
    VALUES (
        v_proposal.principal_id,
        v_proposal.object_type,
        v_object_id,
        v_proposal.proposed_action,
        p_proposal_id,
        p_approval_queue_id,
        v_actor,
        v_proposal.source_surface,
        v_proposal.reason,
        v_old,
        v_new,
        jsonb_build_object('old_version', v_old, 'new_version', v_new)
    );

    UPDATE public.alpha_memory_graph_proposals
       SET status = 'executed',
           executed_by = v_actor,
           executed_at = NOW(),
           updated_at = NOW()
     WHERE id = p_proposal_id;

    PERFORM public.consume_approved_queue_item(p_approval_queue_id);

    RETURN jsonb_build_object(
        'status', 'executed',
        'proposal_id', p_proposal_id::text,
        'object_type', v_proposal.object_type,
        'object_id', v_object_id::text,
        'operation', v_proposal.proposed_action
    );
END;
$function$;

CREATE OR REPLACE FUNCTION public.list_memory_graph_current(
    p_principal_id uuid,
    p_as_of timestamptz DEFAULT NULL,
    p_limit integer DEFAULT 100
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
    v_as_of timestamptz := COALESCE(p_as_of, NOW());
    v_limit integer := LEAST(GREATEST(COALESCE(p_limit, 100), 1), 500);
    v_result jsonb;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    WITH active_nodes AS (
        SELECT *
          FROM public.alpha_memory_graph_nodes n
         WHERE n.principal_id = p_principal_id
           AND n.review_status = 'active'
           AND n.valid_from <= v_as_of
           AND (n.valid_to IS NULL OR n.valid_to > v_as_of)
         ORDER BY n.updated_at DESC, n.created_at DESC
         LIMIT v_limit
    ),
    active_edges AS (
        SELECT e.*
          FROM public.alpha_memory_graph_edges e
          JOIN active_nodes from_node ON from_node.id = e.from_node_id
          JOIN active_nodes to_node ON to_node.id = e.to_node_id
         WHERE e.principal_id = p_principal_id
           AND e.review_status = 'active'
           AND e.valid_from <= v_as_of
           AND (e.valid_to IS NULL OR e.valid_to > v_as_of)
         ORDER BY e.updated_at DESC, e.created_at DESC
         LIMIT v_limit * 3
    )
    SELECT jsonb_build_object(
        'principal_id', p_principal_id::text,
        'as_of', v_as_of,
        'nodes', COALESCE((
            SELECT jsonb_agg(
                jsonb_build_object(
                    'id', n.id::text,
                    'node_type', n.node_type,
                    'label_hash', n.label_hash,
                    'label_preview', n.label_preview,
                    'external_ref_type', n.external_ref_type,
                    'external_ref_id', n.external_ref_id,
                    'properties', n.properties,
                    'source', n.source,
                    'confidence', n.confidence,
                    'valid_from', n.valid_from,
                    'valid_to', n.valid_to,
                    'created_at', n.created_at,
                    'updated_at', n.updated_at
                )
                ORDER BY n.updated_at DESC, n.created_at DESC
            )
            FROM active_nodes n
        ), '[]'::jsonb),
        'edges', COALESCE((
            SELECT jsonb_agg(
                jsonb_build_object(
                    'id', e.id::text,
                    'from_node_id', e.from_node_id::text,
                    'to_node_id', e.to_node_id::text,
                    'edge_type', e.edge_type,
                    'properties', e.properties,
                    'source', e.source,
                    'confidence', e.confidence,
                    'valid_from', e.valid_from,
                    'valid_to', e.valid_to,
                    'created_at', e.created_at,
                    'updated_at', e.updated_at
                )
                ORDER BY e.updated_at DESC, e.created_at DESC
            )
            FROM active_edges e
        ), '[]'::jsonb)
    )
    INTO v_result;

    RETURN v_result;
END;
$function$;

CREATE OR REPLACE FUNCTION public.list_memory_graph_history(
    p_principal_id uuid,
    p_object_id uuid,
    p_limit integer DEFAULT 50
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
    v_limit integer := LEAST(GREATEST(COALESCE(p_limit, 50), 1), 200);
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    RETURN (
        SELECT jsonb_build_object(
            'principal_id', p_principal_id::text,
            'object_id', p_object_id::text,
            'events', COALESCE(jsonb_agg(
                jsonb_build_object(
                    'id', a.id::text,
                    'object_type', a.object_type,
                    'operation', a.operation,
                    'proposal_id', a.proposal_id::text,
                    'approval_queue_id', a.approval_queue_id::text,
                    'actor', a.actor,
                    'source_surface', a.source_surface,
                    'reason', a.reason,
                    'created_at', a.created_at
                )
                ORDER BY a.created_at DESC
            ), '[]'::jsonb)
        )
        FROM (
            SELECT *
              FROM public.alpha_memory_graph_audit a
             WHERE a.principal_id = p_principal_id
               AND a.object_id = p_object_id
             ORDER BY a.created_at DESC
             LIMIT v_limit
        ) a
    );
END;
$function$;

CREATE OR REPLACE FUNCTION public.list_memory_graph_proposals(
    p_principal_id uuid DEFAULT NULL,
    p_state text DEFAULT 'open',
    p_limit integer DEFAULT 50
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
    v_state text := COALESCE(NULLIF(lower(btrim(p_state)), ''), 'open');
    v_limit integer := LEAST(GREATEST(COALESCE(p_limit, 50), 1), 200);
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    RETURN (
        SELECT jsonb_build_object(
            'state', v_state,
            'proposals', COALESCE(jsonb_agg(
                jsonb_build_object(
                    'proposal_id', p.id::text,
                    'principal_id', p.principal_id::text,
                    'proposed_action', p.proposed_action,
                    'object_type', p.object_type,
                    'status', p.status,
                    'approval_queue_id', p.approval_queue_id::text,
                    'approval_status', q.status,
                    'approval_expires_at', q.expires_at,
                    'parameters_hash', p.parameters_hash,
                    'source_surface', p.source_surface,
                    'created_by', p.created_by,
                    'executed_by', p.executed_by,
                    'created_at', p.created_at,
                    'updated_at', p.updated_at,
                    'executed_at', p.executed_at
                )
                ORDER BY p.updated_at DESC, p.created_at DESC
            ), '[]'::jsonb)
        )
        FROM (
            SELECT *
              FROM public.alpha_memory_graph_proposals p
             WHERE (p_principal_id IS NULL OR p.principal_id = p_principal_id)
               AND (
                   v_state = 'all'
                   OR (
                       v_state = 'open'
                       AND p.status IN ('pending_review', 'queued', 'approved')
                   )
                   OR p.status = v_state
               )
             ORDER BY p.updated_at DESC, p.created_at DESC
             LIMIT v_limit
        ) p
        LEFT JOIN public.alpha_approval_queue q ON q.id = p.approval_queue_id
    );
END;
$function$;

CREATE OR REPLACE FUNCTION public.memory_graph_health()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $function$
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    RETURN (
        SELECT jsonb_build_object(
            'node_count', (SELECT COUNT(*)::int FROM public.alpha_memory_graph_nodes),
            'edge_count', (SELECT COUNT(*)::int FROM public.alpha_memory_graph_edges),
            'active_node_count', (
                SELECT COUNT(*)::int
                  FROM public.alpha_memory_graph_nodes
                 WHERE review_status = 'active'
                   AND valid_to IS NULL
            ),
            'active_edge_count', (
                SELECT COUNT(*)::int
                  FROM public.alpha_memory_graph_edges
                 WHERE review_status = 'active'
                   AND valid_to IS NULL
            ),
            'open_proposals', (
                SELECT COUNT(*)::int
                  FROM public.alpha_memory_graph_proposals
                 WHERE status IN ('pending_review', 'queued', 'approved')
            ),
            'stale_proposals', (
                SELECT COUNT(*)::int
                  FROM public.alpha_memory_graph_proposals
                 WHERE status = 'stale'
            ),
            'audit_rows', (
                SELECT COUNT(*)::int FROM public.alpha_memory_graph_audit
            ),
            'last_activity_at', (
                SELECT MAX(value)
                  FROM (
                    SELECT MAX(updated_at) AS value FROM public.alpha_memory_graph_nodes
                    UNION ALL
                    SELECT MAX(updated_at) AS value FROM public.alpha_memory_graph_edges
                    UNION ALL
                    SELECT MAX(updated_at) AS value FROM public.alpha_memory_graph_proposals
                    UNION ALL
                    SELECT MAX(created_at) AS value FROM public.alpha_memory_graph_audit
                  ) activity
            )
        )
    );
END;
$function$;

REVOKE ALL ON FUNCTION public.propose_memory_graph_write(
    uuid, text, text, jsonb, text, text, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.execute_memory_graph_proposal(uuid, uuid, text)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION public.list_memory_graph_current(uuid, timestamptz, integer)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION public.list_memory_graph_history(uuid, uuid, integer)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION public.list_memory_graph_proposals(uuid, text, integer)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION public.memory_graph_health() FROM PUBLIC;

DO $owner$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvisbrain') THEN
        EXECUTE 'ALTER FUNCTION public.propose_memory_graph_write(uuid, text, text, jsonb, text, text, text) OWNER TO jarvisbrain';
        EXECUTE 'ALTER FUNCTION public.execute_memory_graph_proposal(uuid, uuid, text) OWNER TO jarvisbrain';
        EXECUTE 'ALTER FUNCTION public.list_memory_graph_current(uuid, timestamptz, integer) OWNER TO jarvisbrain';
        EXECUTE 'ALTER FUNCTION public.list_memory_graph_history(uuid, uuid, integer) OWNER TO jarvisbrain';
        EXECUTE 'ALTER FUNCTION public.list_memory_graph_proposals(uuid, text, integer) OWNER TO jarvisbrain';
        EXECUTE 'ALTER FUNCTION public.memory_graph_health() OWNER TO jarvisbrain';
    END IF;
END
$owner$;

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT SELECT ON public.alpha_memory_graph_nodes TO jarvis_alpha_app;
        GRANT SELECT ON public.alpha_memory_graph_edges TO jarvis_alpha_app;
        GRANT SELECT ON public.alpha_memory_graph_proposals TO jarvis_alpha_app;
        GRANT SELECT ON public.alpha_memory_graph_audit TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.propose_memory_graph_write(
            uuid, text, text, jsonb, text, text, text
        ) TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.execute_memory_graph_proposal(
            uuid, uuid, text
        ) TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.list_memory_graph_current(
            uuid, timestamptz, integer
        ) TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.list_memory_graph_history(
            uuid, uuid, integer
        ) TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.list_memory_graph_proposals(
            uuid, text, integer
        ) TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.memory_graph_health()
            TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT SELECT ON public.alpha_memory_graph_nodes TO jarvis_alpha_writer;
        GRANT SELECT ON public.alpha_memory_graph_edges TO jarvis_alpha_writer;
        GRANT SELECT ON public.alpha_memory_graph_proposals TO jarvis_alpha_writer;
        GRANT SELECT ON public.alpha_memory_graph_audit TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.propose_memory_graph_write(
            uuid, text, text, jsonb, text, text, text
        ) TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.execute_memory_graph_proposal(
            uuid, uuid, text
        ) TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.list_memory_graph_current(
            uuid, timestamptz, integer
        ) TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.list_memory_graph_history(
            uuid, uuid, integer
        ) TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.list_memory_graph_proposals(
            uuid, text, integer
        ) TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.memory_graph_health()
            TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMENT ON TABLE public.alpha_memory_graph_nodes IS
    'ADR-0029 temporal graph memory nodes. Current facts are valid_to NULL; history remains audit-visible.';
COMMENT ON TABLE public.alpha_memory_graph_edges IS
    'ADR-0029 temporal graph memory relationships between approved graph nodes.';
COMMENT ON TABLE public.alpha_memory_graph_proposals IS
    'ADR-0029 reviewed-write queue for temporal graph memory mutations.';
COMMENT ON TABLE public.alpha_memory_graph_audit IS
    'ADR-0029 append-only audit ledger for temporal graph memory writes.';
COMMENT ON FUNCTION public.propose_memory_graph_write(uuid, text, text, jsonb, text, text, text) IS
    'Queues a reviewed temporal graph memory write and binds it to an approval hash.';
COMMENT ON FUNCTION public.execute_memory_graph_proposal(uuid, uuid, text) IS
    'Executes an approved temporal graph proposal only when the exact T5 approval queue row is usable.';
COMMENT ON FUNCTION public.list_memory_graph_current(uuid, timestamptz, integer) IS
    'Bounded current/as-of temporal graph read for one principal.';
COMMENT ON FUNCTION public.memory_graph_health() IS
    'Aggregate temporal graph memory health counters. Does not return graph content.';

DO $postcheck$
DECLARE
    v_missing INTEGER;
    v_public_execute INTEGER;
BEGIN
    SELECT COUNT(*)::INTEGER
      INTO v_missing
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relname IN (
           'alpha_memory_graph_nodes',
           'alpha_memory_graph_edges',
           'alpha_memory_graph_proposals',
           'alpha_memory_graph_audit'
       )
       AND NOT (c.relrowsecurity AND c.relforcerowsecurity);

    IF COALESCE(v_missing, 0) <> 0 THEN
        RAISE EXCEPTION 'Temporal graph memory RLS postcheck failed';
    END IF;

    WITH expected(identity) AS (
        VALUES
            ('public.propose_memory_graph_write(uuid,text,text,jsonb,text,text,text)'),
            ('public.execute_memory_graph_proposal(uuid,uuid,text)'),
            ('public.list_memory_graph_current(uuid,timestamp with time zone,integer)'),
            ('public.list_memory_graph_history(uuid,uuid,integer)'),
            ('public.list_memory_graph_proposals(uuid,text,integer)'),
            ('public.memory_graph_health()')
    ),
    resolved AS (
        SELECT to_regprocedure(identity) AS oid FROM expected
    )
    SELECT COUNT(*)::INTEGER
      INTO v_public_execute
      FROM pg_proc p
      JOIN resolved r ON r.oid = p.oid
     WHERE has_function_privilege('PUBLIC', p.oid, 'EXECUTE');

    IF COALESCE(v_public_execute, 0) <> 0 THEN
        RAISE EXCEPTION 'Temporal graph memory public EXECUTE postcheck failed';
    END IF;
END
$postcheck$;

COMMIT;
