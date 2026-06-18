-- ADR-0027: explicit semantic memory provenance and review lane.
-- Adds durable provenance metadata for explicit saves and marks health /
-- child-profile facts for higher-visibility review without blocking retrieval.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260618120000);

ALTER TABLE public.alpha_semantic_memory
    ADD COLUMN IF NOT EXISTS provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS review_reason TEXT,
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS reviewed_by TEXT;

ALTER TABLE public.alpha_semantic_memory
    DROP CONSTRAINT IF EXISTS alpha_semantic_memory_review_status_check;

ALTER TABLE public.alpha_semantic_memory
    ADD CONSTRAINT alpha_semantic_memory_review_status_check
    CHECK (review_status IN ('active', 'pending_review', 'rejected', 'archived'));

CREATE INDEX IF NOT EXISTS idx_asm_user_review_status
    ON public.alpha_semantic_memory(user_id, review_status, updated_at DESC);

UPDATE public.alpha_semantic_memory
   SET provenance = jsonb_build_object(
           'source_surface', COALESCE(NULLIF(source, ''), 'unknown'),
           'backfilled_by', '20260618_120000_semantic_memory_provenance_review'
       )
 WHERE provenance = '{}'::jsonb;

CREATE OR REPLACE FUNCTION public.save_semantic_memory_with_provenance(
    p_user_id UUID,
    p_fact TEXT,
    p_category TEXT,
    p_provenance JSONB,
    p_review_status TEXT DEFAULT NULL,
    p_review_reason TEXT DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
    v_memory_id UUID;
    v_buddy_event_id UUID;
    v_review_status TEXT;
    v_review_reason TEXT;
    v_provenance JSONB;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    v_review_status := COALESCE(
        NULLIF(p_review_status, ''),
        CASE
            WHEN p_category IN ('health', 'child_profile') THEN 'pending_review'
            ELSE 'active'
        END
    );
    v_review_reason := COALESCE(
        NULLIF(p_review_reason, ''),
        CASE
            WHEN p_category IN ('health', 'child_profile') THEN 'sensitive_category'
            ELSE NULL
        END
    );
    v_provenance := COALESCE(p_provenance, '{}'::jsonb)
        || jsonb_build_object(
            'explicit', true,
            'semantic_save_version', 2,
            'review_lane', CASE
                WHEN v_review_status = 'pending_review' THEN 'high_visibility'
                ELSE 'standard'
            END
        );

    IF v_review_status NOT IN ('active', 'pending_review', 'rejected', 'archived') THEN
        RAISE EXCEPTION 'save_semantic_memory_with_provenance: invalid review status %', v_review_status
            USING ERRCODE = '22023';
    END IF;

    INSERT INTO public.alpha_semantic_memory (
        user_id,
        fact,
        category,
        source,
        provenance,
        review_status,
        review_reason
    )
    SELECT
        p_user_id,
        p_fact,
        p_category,
        'explicit',
        v_provenance,
        v_review_status,
        v_review_reason
    WHERE (
        SELECT COUNT(*)
          FROM public.alpha_semantic_memory
         WHERE user_id = p_user_id
           AND review_status <> 'archived'
    ) < 50
    RETURNING id INTO v_memory_id;

    IF v_memory_id IS NULL THEN
        RETURN jsonb_build_object('saved', false, 'reason', 'cap_reached');
    END IF;

    IF v_review_status = 'pending_review' THEN
        BEGIN
            SELECT public.record_buddy_event(
                p_user_id::text,
                'alert',
                'Memory review needed',
                'A health or child-profile memory was saved and needs review.',
                3,
                'semantic_memory_review',
                jsonb_build_object(
                    'memory_id', v_memory_id::text,
                    'category', p_category,
                    'review_status', v_review_status,
                    'review_reason', v_review_reason,
                    'source_surface', COALESCE(v_provenance->>'source_surface', 'unknown'),
                    'contains_fact', false
                )
            )
            INTO v_buddy_event_id;
        EXCEPTION
            WHEN OTHERS THEN
                RAISE WARNING 'semantic memory review event failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
                v_buddy_event_id := NULL;
        END;
    END IF;

    RETURN jsonb_build_object(
        'saved', true,
        'id', v_memory_id::text,
        'fact', p_fact,
        'category', p_category,
        'review_status', v_review_status,
        'review_required', v_review_status = 'pending_review',
        'review_reason', v_review_reason,
        'buddy_event_id', CASE WHEN v_buddy_event_id IS NULL THEN NULL ELSE v_buddy_event_id::text END
    );
EXCEPTION
    WHEN integrity_constraint_violation THEN
        RAISE;
    WHEN transaction_rollback THEN
        RAISE;
    WHEN SQLSTATE '57014' OR SQLSTATE '55P03' THEN
        RAISE;
    WHEN OTHERS THEN
        RAISE WARNING 'save_semantic_memory_with_provenance failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
        RETURN jsonb_build_object('saved', false, 'reason', 'error');
END;
$function$;

CREATE OR REPLACE FUNCTION public.save_semantic_memory(
    p_user_id UUID,
    p_fact TEXT,
    p_category TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $function$
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    RETURN public.save_semantic_memory_with_provenance(
        p_user_id,
        p_fact,
        p_category,
        jsonb_build_object('source_surface', 'legacy_function'),
        NULL,
        NULL
    );
END;
$function$;

CREATE OR REPLACE FUNCTION public.review_semantic_memory(
    p_user_id UUID,
    p_memory_id UUID,
    p_action TEXT,
    p_reviewed_by TEXT,
    p_note TEXT DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
    v_status TEXT;
    v_row RECORD;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    v_status := CASE p_action
        WHEN 'approve' THEN 'active'
        WHEN 'reject' THEN 'rejected'
        WHEN 'archive' THEN 'archived'
        ELSE NULL
    END;

    IF v_status IS NULL THEN
        RAISE EXCEPTION 'review_semantic_memory: invalid action %', p_action
            USING ERRCODE = '22023';
    END IF;

    UPDATE public.alpha_semantic_memory
       SET review_status = v_status,
           review_reason = NULLIF(p_note, ''),
           reviewed_at = NOW(),
           reviewed_by = COALESCE(NULLIF(p_reviewed_by, ''), 'unknown'),
           updated_at = NOW(),
           provenance = provenance || jsonb_build_object(
               'last_review_action', p_action,
               'last_reviewed_by', COALESCE(NULLIF(p_reviewed_by, ''), 'unknown')
           )
     WHERE id = p_memory_id
       AND user_id = p_user_id
     RETURNING
        id::text,
        fact,
        category,
        source,
        review_status,
        review_reason,
        reviewed_at,
        reviewed_by
      INTO v_row;

    IF NOT FOUND THEN
        RETURN jsonb_build_object('status', 'not_found', 'memory_id', p_memory_id::text);
    END IF;

    RETURN jsonb_build_object(
        'status', 'reviewed',
        'memory_id', v_row.id,
        'category', v_row.category,
        'review_status', v_row.review_status,
        'review_reason', v_row.review_reason,
        'reviewed_at', v_row.reviewed_at,
        'reviewed_by', v_row.reviewed_by
    );
EXCEPTION
    WHEN integrity_constraint_violation THEN
        RAISE;
    WHEN transaction_rollback THEN
        RAISE;
    WHEN SQLSTATE '57014' OR SQLSTATE '55P03' THEN
        RAISE;
    WHEN OTHERS THEN
        RAISE WARNING 'review_semantic_memory failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
        RETURN jsonb_build_object('status', 'error', 'memory_id', p_memory_id::text);
END;
$function$;

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT SELECT, UPDATE ON public.alpha_semantic_memory TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.save_semantic_memory_with_provenance(UUID, TEXT, TEXT, JSONB, TEXT, TEXT) TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.save_semantic_memory(UUID, TEXT, TEXT) TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.review_semantic_memory(UUID, UUID, TEXT, TEXT, TEXT) TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT SELECT, UPDATE ON public.alpha_semantic_memory TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.save_semantic_memory_with_provenance(UUID, TEXT, TEXT, JSONB, TEXT, TEXT) TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.save_semantic_memory(UUID, TEXT, TEXT) TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.review_semantic_memory(UUID, UUID, TEXT, TEXT, TEXT) TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMENT ON COLUMN public.alpha_semantic_memory.provenance IS
    'Structured provenance for explicit semantic saves: surface, route, thread/message ids, and reviewed-write metadata.';
COMMENT ON COLUMN public.alpha_semantic_memory.review_status IS
    'Review lane state. active and pending_review are injectable; rejected and archived are excluded from retrieval.';
COMMENT ON FUNCTION public.save_semantic_memory_with_provenance(UUID, TEXT, TEXT, JSONB, TEXT, TEXT) IS
    'Explicit semantic memory writer with provenance metadata and sensitive-category review lane.';
COMMENT ON FUNCTION public.review_semantic_memory(UUID, UUID, TEXT, TEXT, TEXT) IS
    'Review or archive one semantic memory row owned by the target user.';

DO $postcheck$
DECLARE
    v_missing INTEGER;
BEGIN
    SELECT count(*)::INTEGER
      INTO v_missing
      FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name = 'alpha_semantic_memory'
       AND column_name IN ('provenance', 'review_status', 'review_reason', 'reviewed_at', 'reviewed_by');

    IF COALESCE(v_missing, 0) <> 5 THEN
        RAISE EXCEPTION 'semantic memory provenance postcheck failed';
    END IF;
END
$postcheck$;

COMMIT;
