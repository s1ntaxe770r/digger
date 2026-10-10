# Findings

The reported post-workflow delay is **not yet verified**. Docker and authenticated GitHub access were restored on 2026-10-10. The local backend now runs with PostgreSQL and passes health/setup/browser checks. A dedicated test GitHub App is now installed on all three fixtures, and its webhook successfully synced them into the local backend. A local renderer optimization is measured below; it does not establish the cause of the reported delay.

## Synthetic utility benchmark (inactive in the live CLI)

`summary.GetCommentUpdater` returns `NoopCommentUpdater`, so this utility optimization does not affect the tested live summary path. Replaced repeated summary-string concatenation with `strings.Builder`. Exact-output checks preserve aliases, statuses, URLs and the 65,536-byte truncation behavior.

| Synthetic jobs | Before median | After median | Change |
|---:|---:|---:|---:|
| 10 | 0.0104 ms | 0.0096 ms | −7.6% |
| 100 | 0.1127 ms | 0.0692 ms | −38.6% |
| 1,000 | 4.6396 ms | 0.6587 ms | −85.8% |

Five samples per case and revision, Go 1.27.0 on Apple M3 Pro, instrumentation disabled, no GitHub/database calls. At 1,000 jobs, allocation fell from **54.9 MB to 3.07 MB per operation** (−94.4%). These are descriptive local benchmarks, not production latency or statistical confidence claims.

[Graph](evidence/synthetic-render.svg) · [full table](evidence/synthetic-render.md) · [before samples](evidence/before.txt) · [after samples](evidence/after.txt).

Separate allocation profiles moved the largest allocation share from the updater itself (95.2% before) to job-spec decoding (78.0% after). Compare per-operation benchmark bytes above, not total profile allocations: the faster version executes more iterations. [Before allocation profile](evidence/before.mem.txt) · [after](evidence/after.mem.txt).

## Live path and candidate

The backend writes summary comments from independent asynchronous updates. The CLI summary provider returns a no-op updater; earlier claims of competing CLI/backend summary writers were incorrect for this path.

The first three successful workflows had final summary rows before completion, with no reversions. Six backend updates spent a median 447 ms creating an installation client, 1,072 ms editing the summary, and 0.080 ms rendering it. The inclusive update total was 1,532 ms. These nested stages must not be summed.

The candidate reuses GitHub installation transports so the library can retain and refresh its token. Cache keys isolate App, installation and private key; HTTP 401 invalidates the entry for the next client. Repeated baseline and candidate runs are in progress. Polling overlaps remain inconclusive; late observations are excluded from delay estimates.

## Delivered

- Opt-in Go timing for status requests, realtime client/database/render/update stages, CLI summary rendering/editing, and GitHub comment PATCH calls.
- Read-only workflow/comment observer with attempt checks, polling bounds and reversion detection.
- Offline comparison report and standalone timing graph generation.
- Scoped local Compose setup and commands in [README.md](README.md).
- Renderer optimization with exact-output regression tests and separate profiling runs.

## Validation

- 16 Python tests pass.
- Go timing-helper and summary timing/output regression tests pass.
- Affected library packages and backend/CLI caller packages compile.
- After permissions were restored, timing and summary packages pass. The GitHub suite passes with `CI=true`; the existing test requiring a specific App installation and exactly 388 repositories is skipped. Without CI, missing `GITHUB_APP_ID` still prevents that test.

## Outstanding

- GitHub integration tests with test App credentials configured.
- Existing PR 21 now maps to real test Actions runs and summary rows. Confirmed management repos: `s1ntaxe770r/digger-small-management-repo` and `s1ntaxe770r/digger-heavy-management-repo`.
- Repeated baseline and candidate fixture runs are underway; the Docker backend image build was stopped during dependency downloads.
- Compare the transport cache on equivalent live runs and produce timing graphs. Small/heavy management-policy runs require an EE test license; none has been supplied.

No PRs created. Instrumentation does not guarantee distributed write ordering.

Local startup evidence: `results/local-startup/` contains migration/build/server logs, fixture revisions, source hashes, Chromium screenshot/video and the smoke-test result. The backend binds only to loopback; the scoped tunnel routes test webhooks and authenticated job callbacks.
