#!/usr/bin/env python3
"""
seed_pricing.py — Idempotent pricing seed for alpha_model_pricing.

Usage (run on Brain only):
    python3 ~/jarvis-alpha/scripts/seed_pricing.py

Safe to re-run: uses ON CONFLICT DO NOTHING.
Add new models by appending rows to PRICING_DATA, then re-run.

Pricing verified 2026-04-16 from official provider documentation.
"""

import subprocess
import sys

PSQL = "/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql"
DB = "jarvis_alpha"

# fmt: off
# (provider, model, input_per_1m, output_per_1m, ctx_threshold, input_long, output_long, effective_from, source, notes)
PRICING_DATA = [
    # Anthropic — platform.claude.com/pricing verified 2026-04-16
    ("anthropic", "claude-opus-4-6",            5.00,  25.00, None,   None, None, "2026-02-04", "platform.claude.com/pricing", "1M ctx standard rate"),
    ("anthropic", "claude-sonnet-4-6",          3.00,  15.00, None,   None, None, "2026-02-04", "platform.claude.com/pricing", "1M ctx standard rate"),
    ("anthropic", "claude-haiku-4-5-20251001",  1.00,   5.00, None,   None, None, "2025-10-01", "platform.claude.com/pricing", "200K ctx"),
    ("anthropic", "claude-haiku-4-5",           1.00,   5.00, None,   None, None, "2025-10-01", "platform.claude.com/pricing", "Alias"),
    ("anthropic", "claude-sonnet-4-5-20250929", 3.00,  15.00, None,   None, None, "2025-09-29", "platform.claude.com/pricing", "200K ctx, 1M beta with surcharge"),

    # Gemini — ai.google.dev/gemini-api/docs/pricing verified 2026-04-16
    ("gemini", "gemini-2.5-pro",        1.25, 10.00, 200000, 2.50, 15.00, "2025-06-17", "ai.google.dev/gemini-api/docs/pricing", "2x input above 200K"),
    ("gemini", "gemini-2.5-flash",      0.30,  2.50,   None, None,  None, "2025-06-17", "ai.google.dev/gemini-api/docs/pricing", "Flat rate"),
    ("gemini", "gemini-2.5-flash-lite", 0.10,  0.40,   None, None,  None, "2025-06-17", "ai.google.dev/gemini-api/docs/pricing", "Cheapest Gemini"),
    ("gemini", "gemini-3.1-pro",        2.00, 12.00, 200000, 4.00, 18.00, "2026-03-09", "ai.google.dev/gemini-api/docs/pricing", "Replaces Gemini 3 Pro Preview"),
    ("gemini", "gemini-3-flash",        0.50,  3.00,   None, None,  None, "2026-02-01", "ai.google.dev/gemini-api/docs/pricing", "Preview"),

    # Perplexity — docs.perplexity.ai/docs/getting-started/pricing verified 2026-04-16
    ("perplexity", "sonar",               1.00,  1.00, None, None, None, "2025-01-27", "docs.perplexity.ai/docs/getting-started/pricing", "127K ctx, flat rate"),
    ("perplexity", "sonar-pro",           3.00, 15.00, None, None, None, "2025-03-07", "docs.perplexity.ai/docs/getting-started/pricing", "200K ctx"),
    ("perplexity", "sonar-reasoning",     1.00,  5.00, None, None, None, "2025-03-07", "docs.perplexity.ai/docs/getting-started/pricing", "DeepSeek R1 backed"),
    ("perplexity", "sonar-reasoning-pro", 2.00,  8.00, None, None, None, "2025-03-07", "docs.perplexity.ai/docs/getting-started/pricing", "Premium reasoning"),
]
# fmt: on


def seed():
    inserted = 0
    skipped = 0

    for row in PRICING_DATA:
        (
            provider,
            model,
            inp,
            out,
            ctx_thresh,
            inp_long,
            out_long,
            eff_from,
            source,
            notes,
        ) = row

        ctx_val = str(ctx_thresh) if ctx_thresh is not None else "NULL"
        inp_long_val = str(inp_long) if inp_long is not None else "NULL"
        out_long_val = str(out_long) if out_long is not None else "NULL"

        sql = (
            f"INSERT INTO alpha_model_pricing "
            f"(provider, model, input_per_1m_usd, output_per_1m_usd, "
            f"context_threshold_tokens, input_per_1m_usd_long_context, "
            f"output_per_1m_usd_long_context, effective_from, source, notes) "
            f"VALUES ('{provider}', '{model}', {inp}, {out}, "
            f"{ctx_val}, {inp_long_val}, {out_long_val}, "
            f"'{eff_from}', '{source}', '{notes}') "
            f"ON CONFLICT (provider, model, effective_from) DO NOTHING;"
        )

        result = subprocess.run(
            [PSQL, "-d", DB, "-X", "-A", "-t", "-c", sql],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"  ERROR {provider}/{model}: {result.stderr.strip()}")
            sys.exit(1)

        if "INSERT 0 0" in result.stderr or result.stdout.strip() == "":
            skipped += 1
            print(f"  skip {provider}/{model} (exists)")
        else:
            inserted += 1
            print(f"  + {provider}/{model} @ ${inp}/${out}")

    print(f"\nDone: {inserted} inserted, {skipped} skipped (already existed)")


if __name__ == "__main__":
    print("Seeding alpha_model_pricing...\n")
    seed()
