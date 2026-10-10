# Findings

The reported post-workflow delay is **not yet verified**. Docker and authenticated GitHub access were restored on 2026-10-10. The local backend now runs with PostgreSQL and passes health/setup/browser checks. A dedicated test GitHub App is now installed on all three fixtures, and its webhook successfully synced them into the local backend. A local renderer optimization is measured below; it does not establish the cause of the reported delay.

## Measured local improvement

Replaced repeated summary-string concatenation with `strings.Builder`. Exact-output checks preserve aliases, statuses, URLs and the 65,536-byte truncation behavior.

| Synthetic jobs | Before median | After median | Change |
|---:|---:|---:|---:|
| 10 | 0.0104 ms | 0.0096 ms | −7.6% |
| 100 | 0.1127 ms | 0.0692 ms | −38.6% |
| 1,000 | 4.6396 ms | 0.6587 ms | −85.8% |

Five samples per case and revision, Go 1.27.0 on Apple M3 Pro, instrumentation disabled, no GitHub/database calls. At 1,000 jobs, allocation fell from **54.9 MB to 3.07 MB per operation** (−94.4%). These are descriptive local benchmarks, not production latency or statistical confidence claims.

[Graph](evidence/synthetic-render.svg) · [full table](evidence/synthetic-render.md) · [before samples](evidence/before.txt) · [after samples](evidence/after.txt).

Separate allocation profiles moved the largest allocation share from the updater itself (95.2% before) to job-spec decoding (78.0% after). Compare per-operation benchmark bytes above, not total profile allocations: the faster version executes more iterations. [Before allocation profile](evidence/before.mem.txt) · [after](evidence/after.mem.txt).

| Candidate | Source evidence | Next measurement |
|---|---|---|
| Competing summary writers | Backend starts independent realtime updates; CLI also updates after the status response | Correlate writes and detect final-to-stale reversions |
| Failed edits hidden by successful return | CLI summary updater logs an edit error but returns nil | Match error timing events to unchanged comment state |
| Repeated database work | Realtime updater fetches batch jobs twice, plus fresh batch | Compare database-stage times on small/heavy fixtures |
| Client setup/network wait | Backend creates an installation transport and requests its token during client setup | Compare client stage and PATCH durations |
| Rendering/group scaling | Repeated string concatenation; grouped comments perform per-job lookups and sequential edits | Targeted benchmarks and profile under representative workloads |

The normal CLI final-summary update is synchronous and precedes CLI exit. Slow synchronous processing alone does not establish a delay after workflow completion. Independent writers, failed edits, different comment types, and deployed versions need separate checks.

Returning the currently suppressed comment error would feed the CLI's failed-job path even when Terraform succeeded. This patch preserves that behavior and exposes the failure in timing data; a behavioral fix needs explicit regression coverage.

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
- Existing PR/run/comment mapping. Confirmed management repos: `s1ntaxe770r/digger-small-management-repo` and `s1ntaxe770r/digger-heavy-management-repo`.
- Repeated baseline fixture runs with the instrumented CLI. Native startup and installation-webhook routing are verified; the Docker backend image build was stopped during dependency downloads.
- Evaluate the renderer and any other evidence-backed fixes on equivalent live after-runs; produce real workflow timing graphs.

No PRs created. Instrumentation does not guarantee distributed write ordering.

Local startup evidence: `results/local-startup/` contains migration/build/server logs, fixture revisions, source hashes, Chromium screenshot/video and the smoke-test result. The backend binds only to loopback; no live workflow delay has been measured.
