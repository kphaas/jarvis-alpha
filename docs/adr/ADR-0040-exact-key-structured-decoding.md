# ADR-0040: Exact-Key Structured Decoding

Date: 2026-07-15

Status: Proposed

Related: Phase 29 Local Output Contract Hardening, Phase 30 Deterministic Local
Decoding, Phase 33 Contract Feasibility Preflight, Phase 34 Exact-Key Structured
Decoding

## Context

Alpha already compiles exact top-level JSON keys, requests deterministic local
decoding, enables Ollama JSON mode, validates the final key set, repairs once at most,
and fails closed. Generic JSON mode constrains syntax but does not prevent omitted or
extra keys during generation. The validator catches those failures only after the model
has spent the call.

Alpha knows the exact key set before generation, but it does not know the value types.
The generation policy must therefore constrain object shape without inventing types,
moving provider details into the output contract, or replacing final validation.

## Decision

- Version the provider-neutral generation policy as `chat_generation_policy.v2` and
  carry exact JSON keys as an immutable tuple.
- Reject internally inconsistent policies where exact keys are present without JSON
  mode or where keys are duplicated.
- Compile exact keys into a standard JSON Schema object:
  - top-level type is `object`;
  - every requested key is required;
  - additional top-level properties are forbidden;
  - each value may be any standard JSON value type because the user supplied no value
    type contract.
- The Ollama adapter sends that schema through the native `format` field. Generic JSON
  mode remains the provider-neutral fallback when exact keys are absent or a future
  adapter does not implement schema translation.
- Keep Alpha's deterministic exact-key validator authoritative after generation.
  Provider-native schema enforcement is an optimization, not proof of correctness.
- Apply the same generation policy to initial local calls, one bounded local repair,
  Council synthesis, and the local stability benchmark through existing call paths.
- Record schema-applied state and key count only. Do not emit key names in policy
  metadata or logs.

```text
Exact-key output contract
    -> generation policy v2
    -> provider-neutral object schema
    -> Ollama native structured decoding
    -> Alpha exact-key validation
    -> bounded repair or quality fallback
```

Ollama documents that `/api/generate` accepts either `"json"` or a JSON Schema object
in `format`: https://docs.ollama.com/api/generate

## Four-Lens Rationale

- **Big Tech:** schema intent stays provider-neutral while translation remains in the
  adapter; validation is independent of provider claims.
- **CIO:** future providers can translate the same policy or retain generic JSON mode
  without changing the compiler.
- **Big Finance:** exact-key enforcement reduces malformed downstream records, while
  metadata excludes user-supplied key names and raw output.
- **Designer:** users receive the requested shape more often instead of seeing a repair
  delay or generic quality fallback for avoidable key errors.

## Boundaries

- Phase 34 does not infer string, number, date, enum, nested-object, or array item types.
- It does not activate schema decoding for explicit cloud routes, mutate routing scores,
  change calibrated routing, or add paid egress.
- It does not trust provider output without Alpha validation.
- It does not add a retry for provider schema errors; existing route, repair, and quality
  failure behavior remains bounded.
- The schema contains user-requested key names only in the in-memory provider request.
  They are not added to logs, outcome metadata, benchmark metadata, or eval output.

## Verification and Operations

1. Unit-test generation-policy validation and exact schema construction.
2. Assert the Ollama adapter sends required keys and `additionalProperties: false` while
   preserving deterministic temperature and seed controls.
3. Assert generic JSON mode and non-JSON policies remain unchanged.
4. Assert router and benchmark metadata prove exact-key schema application without raw
   keys.
5. Require the zero-call output-contract eval to report exact-key schema use.
6. After deploy, rerun the three-sample local stability benchmark. Treat model, Ollama,
   quantization, or hardware changes as new evidence.

## Rollback

Revert generation policy v2 and restore Ollama `format: "json"` for exact-key
contracts. No migration, secret, corpus, routing policy, model, or stored-data rewrite is
required. Alpha's existing validator and quality fallback remain available throughout.

## Consequences

- Local models receive exact top-level key constraints before token generation.
- Repair calls should decline for omitted or extra key failures; deployed benchmark
  evidence is required before claiming an improvement.
- Value semantics remain model-generated and validator-limited until explicit typed
  contracts are supported by evidence.
