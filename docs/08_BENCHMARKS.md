# Benchmarks

The benchmark system measures what the test suite cannot: real model quality,
full-workflow correctness against real PostgreSQL, and the latency and cost of
the deployed cloud service. It is layered so that the expensive parts run
rarely and the deterministic parts gate every change.

| Layer | What it measures | Cost | Where it runs |
| --- | --- | --- | --- |
| L1 extraction quality | Live Azure OpenAI output scored against golden labels through the production prompt, schema, and validator | Tokens | Local CLI, weekly CI, manual CI dispatch |
| L1 replay | Dataset and harness health with recorded reference outputs | Free | Every `pytest` run (integrity tests), CI benchmark job |
| L2 pipeline correctness | The real LangGraph against real PostgreSQL: final applications, events, actions, reviews, and checkpoint privacy | Free (Docker) | CI benchmark job, gated integration test |
| L3 cloud telemetry | Production stage latency, run outcomes, review pressure, LLM tokens and cost | Free | Application Insights KQL over live traffic |

## Layout

```text
benchmarks/
  cli.py                     CLI entry point (python -m benchmarks.cli)
  datasets/extraction/v1/    manifest.json, companies.json, cases/*.json
  harness/                   loader, scorers, suites, report, gate
  baselines/extraction_v1.json  committed baseline metrics per suite/mode
  results/                   run artifacts (gitignored)
  kql/                       production telemetry queries
```

## Running

```powershell
# Free: replay the recorded reference outputs through the real validator.
uv run python -m benchmarks.cli run extraction --mode replay

# Spends tokens: call the real Azure OpenAI deployment (needs LLM_ENABLED=true,
# AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT, and Azure credentials).
uv run python -m benchmarks.cli run extraction --mode live

# Docker required: full workflow against a disposable PostgreSQL container.
uv run python -m benchmarks.cli run pipeline

# Re-evaluate or record a stored report.
uv run python -m benchmarks.cli gate --report benchmarks/results/<file>.json
uv run python -m benchmarks.cli update-baseline --report benchmarks/results/<file>.json
```

Useful options: `--tags interview,zh` and `--limit 5` subset a run;
`--concurrency` bounds parallel live calls;
`--input-token-price-per-1m` / `--output-token-price-per-1m` add a cost
estimate; `--no-gate` skips gating. Reports are written to
`benchmarks/results/` as JSON plus a Markdown summary, and are appended to
`GITHUB_STEP_SUMMARY` in CI.

## Golden dataset

`benchmarks/datasets/extraction/v1/` holds 60 fully synthetic cases (no real
PII, no secret-bearing URLs) covering the scenario matrix: Chinese and English
mail, explicit and missing timezones, relative datetimes, 126 forward
wrappers, assessments with deadlines, reschedules, offers, rejections,
application acknowledgements, standalone deadlines, action-required mail,
results, general updates, ambiguous-but-relevant mail, and eleven hard
non-recruitment negatives.

Each case file contains:

- `input` - the sanitized model input (`received_at`, `sanitized_text`,
  `allowed_link_refs`, optional `sender_domain` and `prefilter_decision`).
  The schema enforces the production privacy boundary: no plaintext URLs, no
  secret query fragments, only allowlisted `ACTION_LINK_NN` references.
- `recorded_response` - the reference `RecruitmentExtraction` used by replay
  and pipeline modes.
- `expected` - field-level golden labels plus the expected deterministic
  validation status and issues.
- `expected_domain` (21 cases) - the final domain state the workflow must
  reach: outcome (`completed` / `needs_review` / `ignored`), application
  status, event row, action-item count, or review type.

Authoring rules are enforced by `tests/benchmarks/test_dataset_integrity.py`,
which runs in the default `pytest` suite: every non-null evidence string must
appear verbatim in `sanitized_text`, every recorded response must replay to
exactly the expected validation outcome, and completed pipeline cases must
reference companies seeded in `companies.json`. Grow the dataset by adding a
case file named after its `case_id` and bumping `case_count` in
`manifest.json`; cut a new dataset version (`v2/`) for incompatible relabels.

## Metrics and gates

Quality metrics: relevant-classification precision/recall/F1 (hard negatives
must not become applications), event-type accuracy with a confusion breakdown,
per-field match rates (company, role, datetimes with timezone semantics,
action fields), validation status agreement, and exact-case match.

Safety metrics get hard gates because they guard the human-review boundary:

| Gate | Threshold | Kind |
| --- | --- | --- |
| Missed reviews (ambiguous case judged valid) | 0 | absolute fail |
| Schema failure rate (strict output refused/errored) | <= 2% | absolute fail |
| Pipeline pass rate | 100% | absolute fail |
| Checkpoint privacy violations (URL bytes in checkpoints) | 0 | absolute fail |
| Relevant F1 / event-type accuracy / validation match vs baseline | drop <= 2pt | relative fail |
| Field match rates vs baseline | drop <= 5pt | relative fail |
| p95 latency vs baseline | rise > 1.5x | warning only |

Relative gates compare against `benchmarks/baselines/extraction_v1.json` for
the same suite, mode, and dataset version; without a matching baseline entry
the gate applies absolute thresholds and warns.

## Baselines

After reviewing a good run, record it and commit the result:

```powershell
uv run python -m benchmarks.cli update-baseline --report benchmarks/results/<file>.json
```

The replay baseline is committed. Record the first live baseline after the
first accepted live run (locally or from the CI artifact); until then the
weekly live job gates on absolute thresholds only.

## CI

`.github/workflows/benchmark.yml`:

- `offline` job - replay extraction plus the full pipeline benchmark on the
  Docker-enabled runner. Runs on manual dispatch and the weekly schedule.
- `live` job - the live Azure OpenAI evaluation. Runs on the weekly schedule,
  or on manual dispatch with `run_live=true`. Uses the `production`
  environment with OIDC sign-in.

Requirements for the live job, once, in the GitHub `production` environment:
`AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT` variables (and
optionally `AZURE_OPENAI_API_VERSION`), plus the deploy service principal
holding the `Cognitive Services OpenAI User` role on the Azure OpenAI
resource. Dataset integrity and harness unit tests already run in the
`quality` workflow on every push, so a broken dataset never reaches the
benchmark jobs.

## Production telemetry (the cloud benchmark)

The deployed Function App emits privacy-validated metric events as
`RA_METRIC {json}` log lines, which the existing Application Insights wiring
stores in the `traces` table. No new telemetry SDK, no canary mail, no
synthetic domain rows.

| Metric | Dimensions | Source |
| --- | --- | --- |
| `workflow_stage_duration_ms` | `stage` | persistence decorator around every node transition |
| `workflow_run_finalized` | `status`, `stage` | run completion, including resumed runs |
| `workflow_run_duration_ms` | `status` | end-to-end duration for runs finished in one process |
| `workflow_review_opened` | `review_type` | human-review pressure |
| `llm_extraction_latency_ms` / `llm_prompt_tokens` / `llm_completion_tokens` | `prompt_version` | LangChain adapter usage capture |

Ready-made queries live in `benchmarks/kql/`: stage latency percentiles, run
outcomes, token volume and cost, review-rate trend, and cold-start
visibility. Token counts and latency are also persisted per extraction on
`app.llm_extractions` (`prompt_tokens`, `completion_tokens`, `latency_ms`;
Alembic `20260815_0012`) for SQL-side cost auditing.

Dimension values that fail a conservative identifier pattern are replaced
with `redacted`; email content, subjects, URLs, and tokens can never enter a
metric. The dedicated tests in `tests/unit/test_observability_metrics.py`
pin this behavior.

## Deliberately out of scope (future phases)

- Production replay flywheel: exporting sanitized production extractions for
  human labeling into the golden dataset.
- Active canary mail injected into the production mailbox; passive telemetry
  was chosen instead to keep domain data clean.
