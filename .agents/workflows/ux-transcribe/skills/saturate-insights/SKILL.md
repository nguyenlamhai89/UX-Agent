---
name: Saturate Insights
description: Extracts grounded UX insights from the canonical mapped-transcript.md produced by Map Transcript, consolidates them with bounded subagents, and deterministically publishes auditable insight reports and a saturation chart. Use after map-transcript returns a complete current canonical file or for an isolated request targeting that exact file.
---

# Saturate Insights

## Description

Read exactly one public input: the canonical `Interview/mapped-transcript.md` produced by `map-transcript`. Parse that combined table once, create isolated participant views, extract grounded insights in bounded batches, consolidate them through evidence IDs, and atomically publish the final reports.

Do not accept a project folder, per-participant mapped files, review files, partial mappings, or a caller-provided `temp_insights.json` as the skill input.

## Input

- **Type**: `dict`
- **Format**:
  - `mapped_transcript_file` (string, **required**) — Absolute path whose basename is exactly `mapped-transcript.md`.
- **Location**: `request_body`
- **Input File**:
  - `Interview/mapped-transcript.md` — Complete canonical combined output from `map-transcript`.
- **Integrity sidecar**:
  - `Interview/mapping-manifest.json` — Discovered automatically beside the input. It is not a second public input. It must report `status: success`, `canonical_current: true`, identify this canonical file, and contain its current signature.

Example:

```json
{
  "mapped_transcript_file": "/absolute/project/Interview/mapped-transcript.md"
}
```

## Output

- **Type**: `dict`
- **Format**:
  - `status`: `"success"`, `"partial"`, or `"error"`.
  - `canonical_current`: Whether the published insight set matches the canonical mapped input.
  - `input_file`: Absolute canonical input path.
  - `input_signature`: SHA-256 of `mapped-transcript.md`.
  - `output_files`: Basenames of every published artifact.
  - `manifest_file`: Absolute `saturation-manifest.json` path.
  - `interviewee_count` / `master_insight_count`: Deterministic totals.
  - `failures`: Structured extraction or consolidation failures.
- **Location**: The directory containing `mapped-transcript.md`.
- **Output Files**:
  - `insights.md` — Compiled master insights, participant reports, matrix, and chart reference.
  - `all-insights-<sanitized_alias>.md` — One participant report per mapped column.
  - `saturation-chart.png` — Marginal discovery chart in exact mapped-column order.
  - `insights-data.json` — Persistent validated evidence and master-insight data.
  - `insights-review-manifest.md` — Quote-to-row grounding audit.
  - `saturation-manifest.json` — Controller state, cache fingerprint, attempts, and output signatures.

## Runtime Contract

1. Require an absolute input path with basename `mapped-transcript.md`. Reject partial, review, and per-participant filenames.
2. Require the exact first four headers: `#`, `Theme`, `Question`, and `Observed Variable`, followed by at least one unique interviewee column.
3. Require equal row widths and a timestamp in every non-`N/A` response.
4. Verify the adjacent mapping manifest before work. Fail closed when mapping is partial, stale, missing, or signature-mismatched.
5. Derive output and controller directories from `Path(mapped_transcript_file).parent`.
6. Never overwrite the last-known-good insight outputs until every extraction and consolidation stage validates.

## Execution

### 1. Prepare and decide whether to skip

```bash
python3 <skill_path>/scripts/insights_pipeline.py prepare \
  <absolute_path>/Interview/mapped-transcript.md \
  --max-workers 4 --max-attempts 3 --max-insights-per-batch 100
```

`prepare` parses the canonical table, verifies upstream signatures, computes a fingerprint from the file SHA-256 plus schema and renderer versions, creates isolated participant views, and reuses only validated per-participant extraction caches with matching view signatures.

Skip only when `canonical_current` is `true`. File existence is never a sufficient skip signal.

### 2. Extract participant insights in bounded batches

Claim work:

```bash
python3 <skill_path>/scripts/insights_pipeline.py next-batch <mapped_transcript_file>
```

Invoke one isolated subagent per returned task. Never exceed the returned batch; the controller caps it at four. Each subagent may read only its task `input_file` and may write only its `candidate_file`.

Candidate schema:

```json
{
  "participant": "User 1",
  "insights": [
    {
      "local_id": "user-1-001",
      "theme": "Khả năng sử dụng",
      "insight": "Bực bội khi thao tác, do nút bấm khó nhìn",
      "evidence": [
        {
          "question_number": "2",
          "theme": "Trải nghiệm",
          "question": "Bạn nghĩ sao về ứng dụng",
          "observed_variable": "Tính năng dễ dùng",
          "timestamp": "00:20",
          "quote": "Nút bấm hơi khó nhìn"
        }
      ]
    }
  ]
}
```

Extraction rules:

- Use the exact `<behavior/emotion/action>, <cause>` format.
- Provide a non-empty descriptive theme.
- Copy quote text verbatim from the assigned participant cell; exclude markup but do not paraphrase.
- Identify the exact canonical row and timestamp for every quote.
- Return an empty `insights` list when no qualified insight exists; never fabricate one.

Record success in the parent:

```bash
python3 <skill_path>/scripts/insights_pipeline.py record-success \
  <mapped_transcript_file> "<participant>"
```

The controller rejects wrong rows, wrong participants, missing timestamps, fabricated quotes, malformed insight phrasing, duplicate IDs, and invalid nested types. Validation failures retry with exact diagnostics and bounded exponential backoff.

For tool or subagent failures, call `record-failure` with a stable code and add `--transient` only for retryable failures. Repeat `next-batch` until no task remains.

### 3. Consolidate in bounded semantic batches

```bash
python3 <skill_path>/scripts/insights_pipeline.py prepare-consolidation <mapped_transcript_file>
python3 <skill_path>/scripts/insights_pipeline.py next-consolidation-batch <mapped_transcript_file>
```

Each consolidation subagent reads its task input and groups semantically equivalent local insights. It may rewrite only the master `theme` and `insight`; it must preserve and cover every provided evidence ID exactly once.

Candidate schema:

```json
{
  "master_insights": [
    {
      "theme": "Khả năng sử dụng",
      "insight": "Bực bội khi thao tác, do nút bấm khó nhìn",
      "evidence_ids": ["ev-abc", "ev-def"]
    }
  ]
}
```

Record each batch with `record-consolidation-success` or `record-consolidation-failure`. The controller validates unknown, missing, and duplicate evidence IDs.

### 4. Merge consolidation batches when needed

```bash
python3 <skill_path>/scripts/insights_pipeline.py prepare-final-consolidation <mapped_transcript_file>
```

Zero or one semantic batch is finalized automatically. For multiple batches, loop over `next-final-consolidation`, write the same master-candidate schema, and call `record-final-consolidation-success` or `record-final-consolidation-failure`. The final candidate must cover all grounded evidence exactly once.

### 5. Derive statuses and publish

```bash
python3 <skill_path>/scripts/insights_pipeline.py finalize <mapped_transcript_file>
```

Python derives statuses in exact interviewee-column order:

- First participant containing evidence for a master insight: `new`.
- Later participant containing evidence: `repeated`.
- Participant without evidence: `absent`.

The renderer never sorts participants by discovery count. It escapes Markdown table cells, requires Matplotlib, writes the complete set into a workspace-local staging directory, validates every artifact, then promotes the set with rollback protection. It prunes only stale files recorded as controller-owned outputs.

Always run cleanup in a `finally` path:

```bash
python3 <skill_path>/scripts/insights_pipeline.py cleanup <mapped_transcript_file>
```

Cleanup removes only controller-owned views, candidates, and interrupted staging/backup directories. Validated extraction caches and canonical outputs remain.

## Error Handling

| Error Code | Meaning | Behavior |
| --- | --- | --- |
| `INVALID_MAPPED_TRANSCRIPT` | Path, filename, UTF-8, heading, headers, widths, aliases, or timestamps are invalid. | Terminal; repair or regenerate canonical mapping. |
| `UPSTREAM_MANIFEST_MISSING` / `UPSTREAM_MANIFEST_INVALID` | Mapping integrity metadata is unavailable. | Terminal; rerun `map-transcript`. |
| `UPSTREAM_MAPPING_NOT_SUCCESS` | Mapping is partial or not current. | Halt before insights; preserve prior outputs. |
| `UPSTREAM_OUTPUT_MISMATCH` / `UPSTREAM_SIGNATURE_MISMATCH` | The file is not the canonical artifact recorded by mapping. | Halt and rerun mapping preflight. |
| `UPSTREAM_CHANGED_DURING_EXTRACTION` / `UPSTREAM_CHANGED_DURING_CONSOLIDATION` | Canonical input changed after prepare. | Terminal for this run; prepare again. |
| `EXTRACTION_VALIDATION_FAILED` | Candidate schema or quote grounding failed. | Retry with validator diagnostic, maximum three attempts. |
| `PARTIAL_EXTRACTION` | One or more participants failed or remain incomplete. | Return partial; never update canonical insight outputs. |
| `CONSOLIDATION_VALIDATION_FAILED` / `FINAL_CONSOLIDATION_VALIDATION_FAILED` | Semantic grouping lost, duplicated, or invented evidence. | Retry with diagnostics; preserve outputs. |
| `PARTIAL_CONSOLIDATION` | Consolidation is incomplete or exhausted. | Return partial; do not publish. |
| `MISSING_DEPENDENCY` | Required Matplotlib renderer is unavailable. | Fail before promotion and preserve outputs. |
| `OUTPUT_VALIDATION_ERROR` / `ATOMIC_PROMOTION_ERROR` | Staging or publication failed. | Roll back last-known-good artifacts. |
| `PERMISSION_ERROR` / `ENCODING_ERROR` / `WRITE_FAILURE` | Filesystem operation failed. | Return a structured terminal error. |

## Known Bugs & Resolutions

| Bug / Error | Cause | Resolution |
| --- | --- | --- |
| Saturation Matrix table used wrong format | The table included unnecessary columns and lacked the cumulative new-insight row. | The deterministic renderer emits the required matrix and count row. |
| AI-generated counts were inaccurate | AI assigned symbols and chart counts. | Python derives statuses and counts from grounded evidence in mapped-column order. |
| Dependency on API Key / SDK | The earlier runtime coupled extraction to an external SDK. | Built-in subagents perform semantic work; Python performs validation and rendering. No API key is required. |
| Context overload and hallucinated quotes | One agent processed every interviewee and quote grounding was prompt-only. | The controller creates isolated views, caps batches at four, and verifies each quote against the exact canonical cell. |
| Ambiguous input contract | Documentation alternated between a folder, combined mapping, per-user mappings, and `temp_insights.json`. | The only public input is now the absolute canonical `mapped-transcript.md`. |
| Misleading chart sequence | Participants were sorted by new-insight count while the axis claimed interview sequence. | The renderer preserves the exact canonical column order. |
| Incomplete schema validation | Missing themes, participant mappings, nested types, and duplicate IDs passed validation. | Strict extraction, evidence, consolidation, and renderer schemas fail closed. |
| Reruns and generation failures left inconsistent files | The renderer deleted its input and wrote outputs sequentially in place. | Fingerprinted manifests, reusable caches, staging, rollback, and owned-output pruning make reruns safe. |
| Unbounded extraction and global consolidation | One subagent per participant and one large merge caused concurrency and token spikes. | Extraction is limited to four workers and consolidation is hierarchical and size-bounded. |

## Performance Improvement Solutions

### ⚡ Execution Efficiency
- [x] Limit extraction and consolidation to deterministic batches of at most four tasks with resumable per-task completion.
- [x] Consolidate compact evidence-linked records in bounded semantic batches and perform a final merge only when multiple batches exist.

### 🎯 Output Quality & Accuracy
- [x] Require complete nested schemas, unique IDs, non-empty themes, exact participant coverage, and valid evidence.
- [x] Escape aliases, insight text, and quotes in Markdown tables and create collision-safe report filenames.
- [x] Verify every quote against the exact participant and row in canonical `mapped-transcript.md`.
- [x] Preserve mapped-column order for deterministic statuses and chart rendering.
- [x] Generate `insights-review-manifest.md` for human grounding review.

### 🔗 Workflow Fit
- [x] Accept only the canonical `mapped-transcript.md` output from `map-transcript`; treat all intermediate JSON as controller-owned state.
- [x] Use a source fingerprint and output signatures for safe skip decisions.
- [x] Define structured extraction, consolidation, upstream, dependency, and promotion error codes.
- [x] Support safe cached reruns, incremental participant extraction reuse, and stale owned-output pruning.

### 🛡️ Reliability & Error Handling
- [x] Validate every nested type before access and return structured schema errors.
- [x] Render in staging and atomically promote with rollback protection.
- [x] Enforce bounded retry, exponential backoff, transient/terminal classification, and partial fail-closed behavior.
- [x] Add regression coverage for malformed inputs, grounding, ordering, retries, cache, rollback, and canonical-only handoff.

### 💰 Cost & Scalability
- [x] Cap subagent concurrency, bound consolidation size, and render large-cohort labels without changing interview order.
- [x] Cover the complete 20-interviewee workflow, five extraction batches, hierarchical consolidation, and canonical outputs.
