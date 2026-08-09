# Skill Performance Analysis: transcribe-audios

> Last updated: 2026-08-09 — ElevenLabs-only implementation

## Current provider policy

`transcribe-audios` uses only ElevenLabs Speech to Text (Scribe v2). The only
accepted credential is `ELEVENLABS_API_KEY`, delegated from `ux-research` to
`ux-interview` and then injected into the skill process. A failed request is
retried only when ElevenLabs classifies it as transient; the skill does not
switch to another transcription service.

## Current performance assessment

| Category | Criterion | Before | Current | Evidence and remaining limitation |
| --- | --- | ---: | ---: | --- |
| Execution efficiency | Execution time | 8/10 | 8/10 | Configurable worker pool keeps file-level parallelism; provider retry backoff can increase time for failed files. |
| Execution efficiency | API call count | 8/10 | 9/10 | A valid, current output is skipped; every pending file makes only ElevenLabs attempts under the configured retry limit. |
| Execution efficiency | Request payload efficiency | 8/10 | 9/10 | The direct Speech to Text request sends only audio and optional keyterms, with no extra model prompt or provider handoff. |
| Execution efficiency | Resource consumption | 7/10 | 9/10 | Bounded submission enforces `max_inflight_mb`; a single oversized-in-budget file runs alone rather than accumulating uploads. |
| Output quality | Output completeness | 8/10 | 9/10 | JSON success, partial-failure, per-file attempt, duration, and cost fields are documented; transcript and metadata are atomically published. |
| Output quality | Format compliance | 8/10 | 9/10 | A completed transcript requires the named header and at least one timestamped speaker segment. |
| Output quality | Content accuracy | 7/10 | 8/10 | Word-level formatting preserves spacing and source terms; accuracy still ultimately depends on the recording and STT model. |
| Output quality | Human approval rate | 8/10 | 8/10 | Regression coverage supports review quality, but no production approval telemetry is collected. |
| Workflow fit | I/O contract adherence | 9/10 | 10/10 | Skill, child orchestrator, parent orchestrator, and README now agree on the single required key and output contract. |
| Workflow fit | Skip-logic compatibility | 6/10 | 10/10 | Skip requires valid Markdown plus a matching source fingerprint in the metadata sidecar. |
| Workflow fit | Pipeline passthrough rate | 8/10 | 9/10 | Per-file errors retain successes and unexpected future failures are normalized to `FUTURE_ERROR`. |
| Workflow fit | Idempotency | 8/10 | 10/10 | Unchanged audio skips deterministically; changed audio invalidates the prior transcript. |
| Reliability | Error rate | 7/10 | 9/10 | Local parameter validation, terminal/transient error classification, and documented dependency/duration/budget errors stop avoidable bad requests. |
| Reliability | Error recoverability | 7/10 | 9/10 | Atomic writes, per-file isolation, and clear error envelopes preserve recoverable batch state. |
| Reliability | Retry success rate | 8/10 | 9/10 | ElevenLabs-only retries use exponential backoff, jitter, `Retry-After`, and a shared local request limiter. |
| Reliability | Known-bug recurrence | 8/10 | 10/10 | Tests cover strict output validation, source freshness, bounded scheduling, cost budgets, and prior formatting defects. |
| Cost and scalability | Cost per execution | 6/10 | 9/10 | Optional orchestrator-provided pricing reports duration/cost estimates and can halt a batch before calls exceed a budget. |
| Cost and scalability | Scaling behavior | 7/10 | 9/10 | Worker, request-rate, per-file-size, and aggregate-in-flight-byte controls provide size- and quota-aware scheduling. |
| Cost and scalability | Unit-test coverage and pass rate | 8/10 | 9/10 | 22 focused tests mock external API behavior and cover success, error, freshness, budget, and scheduling paths. Coverage percentage is not measured because `pytest-cov` is unavailable. |
| Cost and scalability | Operational observability | 6/10 | 9/10 | Metadata records source fingerprint, provider, model, attempts, duration, estimated cost, and pricing version without retaining secrets. |

## Implemented improvements: previous version vs. current version

| Area | Previous version | Current version |
| --- | --- | --- |
| Provider and credential | Accepted two transcription-key paths and could change provider after an error. | Requires only `ELEVENLABS_API_KEY`; all request paths call ElevenLabs Scribe v2. |
| Failure handling | A provider switch made final provider, attempt, and cost behavior less predictable. | Keeps ElevenLabs terminal errors per file; retries only transient ElevenLabs errors with jitter and `Retry-After`. |
| Output freshness | A file could be skipped based on a weak transcript-existence check. | Requires valid named Markdown segments plus matching `stat` or `sha256` source fingerprint metadata. |
| Write safety | Transcript publication was atomic but did not have source provenance. | Atomically writes both transcript and non-secret metadata sidecar. |
| Upload pressure | Five workers could submit several very large files at once. | Limits aggregate active bytes with `--max-inflight-mb` and bounded task submission. |
| Rate control | No shared provider-wide client limiter. | Adds `--requests-per-minute` and shares a backoff window across ElevenLabs workers. |
| Cost control | No cost estimate or preflight guard. | Uses optional orchestrator-supplied ElevenLabs pricing, `ffprobe` duration probing, and `--max-estimated-cost-usd`. |
| Documentation | Provider/key instructions differed between skill, workflow, and README. | Skill, `ux-interview`, `ux-research`, and README consistently document ElevenLabs-only operation. |
| Tests | Focused on the former multi-provider execution paths. | Removes those paths and verifies the ElevenLabs-only contract, strict skip validation, freshness, size budget, and cost guard. |

## Known Bugs & Resolutions

| Bug / error | Cause | Resolution and prevention |
| --- | --- | --- |
| Header-only transcript was skipped | The prior structural check accepted a title without a completed speaker block. | `is_valid_transcript` now requires the exact source-name title plus at least one timestamped speaker segment; regression test added. |
| Replaced audio retained an old transcript | The prior skip decision did not record input provenance. | A `stat` or `sha256` source fingerprint is stored in `.meta.json` and must match before a skip; regression test added. |
| Large mixed batches could overload uploads | Worker count did not bound aggregate file bytes. | Bounded scheduler enforces `max_inflight_mb`; concurrency regression test added. |
| Batch cost was opaque | No duration or price information was captured. | Optional pricing/duration metadata and an explicit preflight budget guard were added; regression test added. |
