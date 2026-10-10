# Comment latency investigation

Read-only observation of a specific workflow attempt and PR comment, plus opt-in Go stage timings. No commands here create PRs. Use existing test PRs.

## Current setup

Branch: `perf/action-comment-latency`. Baseline source: `c1962300`; cached-transport backend: `6de55a67`. Local Go 1.27.0 on Apple M3 Pro; Actions uses Go 1.25.6 on Ubuntu.

The native backend runs on `127.0.0.1:3101`, with PostgreSQL in the scoped Compose project on port 55433. Atlas applied 156 statements. A dedicated test App is installed on exactly `s1ntaxe770r/terragrun-test`, `s1ntaxe770r/digger-small-management-repo`, and `s1ntaxe770r/digger-heavy-management-repo`. A filtered tunnel exposes test webhooks and authenticated job callbacks. Pprof stays local.

Initial network, Docker and disk failures were resolved. The Docker backend image build was stopped during dependency downloads; measurements use the native backend. Existing unrelated containers were left alone. Private credentials and raw logs live in ignored `backend.env` and `results/`; never commit them.

Five usable baseline and five comparison batches completed successfully (30 workflows). Management-policy scenarios need an EE test license. See [findings](findings.md) for results and limitations.

## Local backend

Run from the `digger` checkout. Requires Docker Compose, several GB of free disk, GitHub CLI authentication, and a dedicated test GitHub App installed on the fixture repositories. The supplied Compose project builds the current checkout, starts PostgreSQL, and uses the backend's existing Atlas migration entrypoint.

```sh
cp scripts/comment_latency/backend.env.example scripts/comment_latency/backend.env
# Fill backend.env with test credentials; it is gitignored.
export DIGGER_PROFILE_REVISION="$(git rev-parse HEAD)"
mkdir -p scripts/comment_latency/results
git diff > scripts/comment_latency/results/instrumentation.patch
docker compose -f scripts/comment_latency/compose.yaml up -d --build
curl --fail http://127.0.0.1:3101/health
docker compose -f scripts/comment_latency/compose.yaml logs --no-log-prefix backend \
  > scripts/comment_latency/results/backend.log
```

Record the revision **and diff** for each build: the revision alone does not identify uncommitted instrumentation. Register/configure the test App in the local backend and connect the test organization. Route its webhook to `/github/webhook`, and configure existing test workflows' `DIGGER_HOSTNAME` and credentials for this backend. Verify the actual workflow configuration's input names before changing it. If a public HTTPS tunnel is needed, expose only the required webhook/API paths; keep `/debug/pprof` local.

Prove routing before measuring: the local backend must log the exact test job ID, and the workflow must use the intended instrumented CLI build. Record CLI version/build, backend revision/diff, fixture commit, project count and settings. A workflow branch alone does not prove which CLI or backend ran.

Cleanup is scoped to this Compose project and preserves its database volume:

```sh
docker compose -f scripts/comment_latency/compose.yaml down
```

If existing related containers conflict, identify their project and ownership before removing only those containers. Do not use global prune or remove volumes.

## Fixture runs

Resolve the supplied names before using them:

```sh
gh repo list s1ntaxe770r --limit 200 --json nameWithOwner,description \
  --jq '.[] | select(.nameWithOwner | test("terragrun-test|digger.*management"))'
```

The supplied names were `s1ntaxe770r/terragrun-test`, `s1ntaxe770r/digger-heavy-management...`, and `s1ntaxe770r/digger-small-management.`. All three names have now been verified; see the access retry above. Management repos may be policy inputs to the reproduction repo, not independent workflow producers: record the fixture configuration for each scenario rather than inventing a run in a repo without workflows.

Identify the existing PR, workflow run/attempt, and summary comment. Start observation **while the run is still active**. Provide a final-state regex that checks the expected relevant rows and a run-specific correlation string, such as the exact workflow URL. A generic success emoji is insufficient when multiple rows exist. If the comment does not identify its run, establish a unique marker through the test setup first; do not match an old result.

```sh
python3 scripts/comment_latency/measure.py observe \
  --repo OWNER/REPO --pr PR_NUMBER --run RUN_ID --attempt ATTEMPT \
  --comment COMMENT_ID --scenario small-management --phase before \
  --revision BASELINE_SHA --environment local-fixed-config \
  --final-regex 'EXPECTED_FINAL_STATE_REGEX' \
  --correlation-text 'https://github.com/OWNER/REPO/actions/runs/RUN_ID' \
  --output scripts/comment_latency/results/before-small-01.jsonl
```

The collector only sends GET requests. It does not dispatch jobs, edit comments, or change repository configuration. It checks run/attempt and comment/PR identity, polls every two seconds, and watches for ten seconds after both completion and final state are seen. Use `--stable`, `--poll`, and `--timeout` to change those settings. Transient reversions between polls can be missed; a stability window does not prove permanent correctness.

Start with five runs per fixture configuration. Keep identical workloads, resources and instrumentation for before/after runs; change only the candidate fix. Preserve failed/missing observations. Expand sampling only if the results require it.

```sh
python3 scripts/comment_latency/measure.py report \
  scripts/comment_latency/results/*.jsonl \
  --output scripts/comment_latency/results/comparison
```

Outputs: `report.html`, `timings.svg`, and `samples.json`. The report keeps outcomes and sample counts alongside median/range **bounds** and comparable before/after deltas. It never substitutes a workflow's generic `updated_at` for completion time. A run already complete when observation begins cannot provide a fully bounded delay. A comment matching on the first poll is unverified, since it could belong to an earlier attempt; observe a nonfinal-to-final transition to establish attribution. API-observed timing is not a measurement of browser refresh latency.

## Go timing and profiling

Set `DIGGER_COMMENT_TIMING=1` in backend **and CLI** environments. Other values disable it. Events named `comment_timing` include writer, stage, span ID, UTC start/end, monotonic duration, success/error, and correlation IDs. Existing application logs still follow their normal policy; the new events contain no bodies or error text. Nested stage durations overlap: do not add totals and child spans together.

Generate inclusive stage tables/graphs from backend JSON or CLI text logs:

```sh
python3 scripts/comment_latency/stages.py scripts/comment_latency/results/backend.log \
  --output scripts/comment_latency/results/stages
```

Optional `--batch-id`, `--job-id`, and `--comment-id` filters match only records carrying that ID. They do not infer parent-child links. Stages are inclusive and can overlap; graphs do not imply exclusive attribution or a complete critical path.

Collect CPU and runtime traces in separate diagnostic runs, not the unprofiled before/after comparison:

```sh
curl --fail 'http://127.0.0.1:3101/debug/pprof/profile?seconds=20' \
  -o scripts/comment_latency/results/cpu.pprof
go tool pprof -top scripts/comment_latency/results/cpu.pprof
curl --fail 'http://127.0.0.1:3101/debug/pprof/trace?seconds=5' \
  -o scripts/comment_latency/results/runtime.trace
go tool trace scripts/comment_latency/results/runtime.trace
```

Trigger the representative workload during collection. CPU profiles exclude waiting; stage timings separate database/client/render/edit waits. The existing pprof switch is enabled by **presence**, including a value of `false`; unset it to disable. Block/mutex profiles need explicit runtime sampling configuration and are not enabled by this patch.

## Checks

```sh
python3 -m unittest discover -s scripts/comment_latency -p 'test_*.py' -v
cd libs
go test ./comment_utils/latency ./comment_utils/summary ./ci/github
cd ../backend
go test ./utils ./controllers
```

When full dependencies cannot compile, the timing helper has a standard-library-only check. This does **not** validate its integration into backend/CLI packages:

```sh
cd libs/comment_utils/latency
GOWORK=off go test -p 1 timing.go timing_test.go
```

See [findings.md](findings.md) for actual results and remaining work.

## Synthetic renderer benchmark

The live CLI provider returns NoopCommentUpdater, so this renderer is inactive in the measured workflow path. This benchmark isolates summary rendering with an in-memory comment sink; it does not use the test repositories or measure workflow latency. Run baseline and candidate with the same toolchain and configuration, without concurrent builds. Capture five samples per job count:

```sh
cd libs
go test -p 2 ./comment_utils/summary -run 'Test(UpdateCommentTiming|SummaryOutputGolden)' \
  -bench BenchmarkSummarySynthetic -benchmem -benchtime=300ms -count=5
```

Save stdout as `before.txt` and `after.txt`, then generate the standalone graph and data from the checkout root:

```sh
python3 scripts/comment_latency/benchmark_report.py BEFORE.txt AFTER.txt \
  --output scripts/comment_latency/results/synthetic-comparison
```

The retained [evidence](evidence/synthetic-render.md) uses unprofiled samples. CPU/memory profiling runs were separate, so profiler overhead is not included in the comparison.

To reproduce a diagnostic profile from `libs/` (repeat with distinct output names for each renderer):

```sh
go test -p 2 ./comment_utils/summary -run '^$' \
  -bench 'BenchmarkSummarySynthetic/jobs_1000$' -benchtime=1s \
  -cpuprofile /tmp/digger-summary.cpu.pprof -memprofile /tmp/digger-summary.mem.pprof \
  -o /tmp/digger-summary-profile.test
go tool pprof -top /tmp/digger-summary-profile.test /tmp/digger-summary.cpu.pprof
go tool pprof -top -alloc_space /tmp/digger-summary-profile.test /tmp/digger-summary.mem.pprof
```

The [renderer-only patch](evidence/renderer.patch) isolates the optimization from timing instrumentation. On a scratch branch containing these changes, `git apply -R scripts/comment_latency/evidence/renderer.patch` restores the measured baseline renderer; applying the patch forward restores the candidate. Keep output tests and timing settings identical for both. Do not reverse the patch over unrelated edits.

## Browser recording

The local smoke recorder uses Python Playwright and an installed Chromium. It requests `/health`, opens the authenticated `/github/setup` page and saves a screenshot, WebM video and JSON result. It does not submit the GitHub App form.

```sh
python3 scripts/comment_latency/browser_smoke.py --chromium /path/to/chromium
```

Artifacts go in ignored `results/local-startup/`: `compose.log`, `source-manifest.json`, `source.patch`, `fixtures.json`, `github-tests.txt`, `python-tests.txt`, `backend-setup.png`, `backend-setup.webm`, and `browser-smoke.json`. The source manifest hashes the uncommitted files as well as recording the base revision. Credentials and generated artifacts are excluded from the Docker build context.

## Successful native startup: 2026-10-10

PostgreSQL 16 runs in `digger-comment-latency-postgres-1`, bound to `127.0.0.1:55433`. Atlas applied the existing migrations (156 SQL statements). The native backend runs in the background on `127.0.0.1:3101`, with Basic auth, timing and pprof enabled. `local_main.go` calls the same Bootstrap/controller as `backend/main.go`, loads templates from the backend working directory and binds explicitly to loopback. This is a local diagnostic runner, not the production Docker image.

Repeat from the checkout root after creating `backend.env`:

```sh
export DIGGER_PROFILE_REVISION="$(git rev-parse HEAD)"
docker compose -f scripts/comment_latency/compose.yaml up -d postgres
atlas migrate apply --url 'postgres://digger:local-profile-only@127.0.0.1:55433/digger?sslmode=disable' --dir file://backend/migrations
cd backend
GOCACHE=/tmp/digger-latency-go-build go build -p 2 -o ../scripts/comment_latency/results/local-startup/backend-local ../scripts/comment_latency/local_main.go
set -a
source ../scripts/comment_latency/backend.env
set +a
DATABASE_URL='postgres://digger:local-profile-only@127.0.0.1:55433/digger?sslmode=disable' HTTP_BASIC_AUTH=true DIGGER_COMMENT_TIMING=1 DIGGER_PPROF_DEBUG_ENABLED=1 DIGGER_LOG_LEVEL=INFO GIN_MODE=release nohup ../scripts/comment_latency/results/local-startup/backend-local > ../scripts/comment_latency/results/local-startup/backend.log 2>&1 &
echo $! > ../scripts/comment_latency/results/local-startup/backend.pid
```

Stop that recorded backend process before starting another; Compose `down` only stops the database in this mode. Both database and backend were left running for continuation.

Verified: health HTTP 200, authenticated setup HTTP 200, Chromium screenshot/video saved, CPU-profile endpoint produces a readable profile. The idle one-second profile has zero CPU samples: it only checks profiling access and is not workload evidence. Health reports `dev`; use the retained source manifest and binary hash for identity.

## Test App connected: 2026-10-10

Created private App `digger-latency-s1ntaxe-1791592697` (App ID 5257586, installation 169783930) through the authenticated headless browser. Installed only on terragrun-test, digger-small-management-repo and digger-heavy-management-repo. Credentials went directly to ignored, mode-0600 `backend.env`; no credential screenshots or video were captured.

The backend was restarted with those credentials. Its installation webhook succeeded and synced all three repositories. The initial creation ping arrived before the credentials were loaded and was rejected; installation after restart succeeded.

A temporary Cloudflare tunnel forwards to `webhook_proxy.py` on 127.0.0.1:3102. The proxy exposes only `/github/webhook` and authenticated `/repos/` and `/orgs/` APIs; public pprof returns 404, unauthenticated APIs return 403. Browser OAuth/setup callbacks remain local. The tunnel URL and process IDs are in ignored `results/app-setup/`; both tunnel and proxy remain running. Restarting a quick tunnel may change its URL, requiring the App webhook and backend PUBLIC_BASE_URL to be updated.

App metadata/scope verification: `results/app-setup/app.json`, with `installed.png` showing the three selected repos. The original browser startup smoke result predates App creation; live experiment details follow.

## Recorded live experiment

The existing `terragrun-test` PR 21 supplies three plain Terraform projects. Its fixture config was corrected from `root_dir: infra/` to `include: infra/**` (commit `929d9580`). This changed only the existing test branch; no PR was created. The workflow definition is isolated on `perf/comment-latency-20261010` (`d952ef95`). Its checked-in copy is [fixture-workflow.yml](fixture-workflow.yml).

The local runner's `DIGGER_PROFILE_SETTINGS` adapter selects that workflow definition while preserving the PR branch in each job payload. The CLI source is pinned to `c1962300` in both phases. The before workflow reverses the synthetic renderer patch; that updater is inactive because `summary.GetCommentUpdater` returns `NoopCommentUpdater`. The live comparison therefore exercises the backend transport cache. Each workflow prints its source and binary hash.

The first successful batch came from the test PR synchronize event. Subsequent batches replay the signed current synchronize event through the test tunnel; backend dispatch, Actions execution, status callbacks and comment edits remain real. All commands are guarded to allow only `digger plan`.

```sh
# settings.json contains workflow_ref, source_ref, phase and an absolute dispatch results path.
# Run only one series at a time; the script waits for each three-project batch.
python3 scripts/comment_latency/run_series.py --phase before --samples 3 4 5 6

# Build from backend/; stop the old backend only after its observers finish.
cd backend
GOCACHE=/tmp/digger-latency-go-build go build -p 2 \
  -o ../scripts/comment_latency/results/local-startup/backend-cached \
  ../scripts/comment_latency/local_main.go
cd ..
python3 scripts/comment_latency/start_backend.py --phase after \
  --binary scripts/comment_latency/results/local-startup/backend-cached
python3 scripts/comment_latency/run_series.py --phase after --samples 1 2 3 4 5

python3 scripts/comment_latency/live_report.py \
  --input scripts/comment_latency/results/live \
  --backend-before scripts/comment_latency/results/live/backend-before.log \
  --backend-after scripts/comment_latency/results/local-startup/backend.log \
  --output scripts/comment_latency/evidence/live \
  --exclude-comment DIAGNOSTIC_COMMENT_ID
```

These are the recorded series IDs, not commands to rerun over existing results. Trigger and observation scripts refuse to overwrite prior observations. The restart helper archives the baseline log once; inspect existing logs before a later restart. Stage comparisons include only batches with usable transition observations. Three late baseline observations are retained and excluded.

Browser evidence is in `results/local-startup/backend-setup.webm` and `backend-setup.png`. The recording covers local health/setup verification, not private credential pages. App installation scope was checked separately. Raw backend/CLI logs remain mode 0600; published timing records contain correlation IDs and durations only.

## Separate diagnostic profile

After the comparison series finishes, `python3 scripts/comment_latency/profile_live.py` runs sample 6 with 120-second CPU and runtime-trace captures, then saves a heap profile. It records its run/comment IDs in `results/live-profile/profile.json`; pass its `excluded_comments` to `live_report.py --exclude-comment`. Do not combine profiled runs with the before/after sample. Raw profiles remain private local artifacts.

```sh
go tool pprof -top scripts/comment_latency/results/live-profile/cpu.pprof
go tool pprof -top -alloc_space scripts/comment_latency/results/live-profile/heap.pprof
go tool trace scripts/comment_latency/results/live-profile/runtime.trace
```
