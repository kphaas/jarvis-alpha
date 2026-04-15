-- Migration: 20260414_170000_child_rls_helper
-- Purpose: rating_allowed() helper for child RLS policies

BEGIN;

CREATE OR REPLACE FUNCTION rating_allowed(row_rating text, max_rating text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT array_position(
        ARRAY['all_ages','age_8_plus','teen','adult'],
        row_rating
    ) <= array_position(
        ARRAY['all_ages','age_8_plus','teen','adult'],
        max_rating
    );
$$;

COMMIT;
