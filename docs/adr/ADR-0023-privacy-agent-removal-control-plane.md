# ADR-0023: Privacy Agent Removal Control Plane

## Status

Proposed

## Context

Privacy Agent MVP v0.1 is local-only and human-approved. It can intake a
subject, select targets, draft review packets, hand approved actions to an
operator, record disposition, record verification, and produce local evidence
reports.

The next industry gap is not another manual note field. Services such as
Incogni and DeleteMe set the product benchmark around broad broker coverage,
signed authorization, per-broker status, recurring follow-up, privacy reports,
custom removals, search-result handling, and clear separation of public records
from legal process.

Alpha still needs to maintain four constraints:

- Product coverage: support the full removal lifecycle, not only a one-time
  target list.
- Legal safety: require authorization and keep public-record legal work
  separate from broker copies and search-result deindexing.
- Security/privacy: store sensitive artifacts as encrypted payloads and hashes,
  never as plaintext console data.
- Operations/evidence: make status, due work, and proof material measurable.

## Decision

Add a P4 removal control plane inside Alpha.

This phase adds storage and dashboard status for:

- P4-A Discovery coverage
- P4-B Authorization vault
- P4-C Broker adapter profiles
- P4-D Evidence dashboard
- P4-E Recurring monitor metadata
- P4-F Search deindex candidates
- P4-G Public-record triage

The control plane remains outbound-disabled. It does not submit broker forms,
send email, perform public search automation, file court records, or schedule
public-internet work. Those behaviors require a later executor ADR, explicit
target allowlists, approval-gateway rules, legal review, and egress controls.

Add a guarded operator seed action for an existing subject. The seed action is
an authenticated local write that creates one encrypted/digest-only starter row
for authorization, evidence, recurring monitor, search deindex, and
public-record triage. The operator must confirm that authorization exists; the
seed action records that attestation but still does not contact any target.

## Consequences

- Alpha can show an Incogni/DeleteMe-style operating map without pretending
  live removals are already automated.
- The operator can see coverage gaps, authorization state, evidence counts, due
  recurrence, search deindex candidates, and public-record triage in one place.
- Sensitive authorization, evidence, search, and triage details remain
  encrypted or digest-only.
- P4 creates the data contracts required for a later low-touch executor phase.
- MVP hardening remains testable without sending personal data to third parties.
- Repeated smoke tests can seed the same subject without duplicating rows.
