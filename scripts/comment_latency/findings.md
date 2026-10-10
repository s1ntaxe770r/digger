# Comment latency findings

The reported post-workflow delay is **not confirmed by this sample**. Thirty usable workflows succeeded: 11 summary rows were confirmed final before workflow completion; 19 had overlapping polling bounds. No reversions were observed during the ten-second stability window. Short delays within those bounds remain possible.

[Report and graphs](evidence/live/report.html) · [raw observations and summary](evidence/live/comparison.json) · [local runbook](README.md)

## Measured before / after

Five batches per phase, three projects per batch, same test PR and pinned CLI. The candidate caches GitHub installation transports, allowing the library to reuse and refresh installation tokens.

| Backend measurement | Before median | After median | Change |
|---|---:|---:|---:|
| Final-status summary update | 1,455.741 ms | 966.360 ms | −489.381 ms / −33.6% |
| Client setup | 426.986 ms | 0.982 ms | −99.8% |
| GitHub summary edit | 992.358 ms | 970.483 ms | −2.2% |

Final-update totals have 15 samples per phase. Component timings have 30 and include running/final updates: batch-only correlation cannot safely separate overlapping child spans. These inclusive measurements must not be added. Rendering was below 0.1 ms median; database stages were a few milliseconds. GitHub edit time remains the main measured cost.

This reduces backend update work; it does **not** establish a fix for a post-workflow delay. Serial batches, shared jobs, API variability and some baseline compilation overlap limit causal percentage claims. Browser refresh, overlapping batches and production load were not tested.

## Implementation and checks

Cache keys isolate App, installation and private key. The existing library handles synchronized token refresh; HTTP 401 invalidates the entry for subsequent clients. No automatic retry or workflow-result change. Entries remain until invalidation/process exit; the cache has no size bound.

Focused tests and race checks pass for concurrent reuse, identity/key isolation, expiry, revocation and a late 401 from an old transport. Sixteen Python observer/report tests pass. The existing GitHub suite passes with `CI=true`; its installation-specific 388-repository test is skipped.

The CLI summary provider returns `NoopCommentUpdater`. Earlier claims of competing CLI/backend summary writers were incorrect for this path. The separate [synthetic renderer benchmark](evidence/synthetic-render.md) measures inactive utility code and contributes none of the live gain. Backend asynchronous writers remain unsynchronized.

## Workload profile

A separate successful three-workflow batch captured 120 seconds of CPU/runtime activity: **550 ms of CPU samples (0.46%)**, too sparse to establish a CPU hotspot. [CPU summary](evidence/live/cpu-top.txt) and [trace network waits](evidence/live/network-wait-top.txt) include profiling overhead and idle/concurrent waits; aggregate waits are not request latency. The [91.96 MB allocation profile](evidence/live/allocation-top.txt) covers process lifetime, not one batch or retained memory.

## Evidence and remaining scope

Three late baseline observations are retained but excluded. A separate diagnostic batch captures CPU/runtime profiles and is excluded from the comparison. Raw logs, credentials and profiles stay in ignored local results; published records contain timings and correlation IDs.

Fixture `929d9580`, workflow `d952ef95`, CLI `c1962300`; backend before `c1962300`, after `6de55a67`. Existing `terragrun-test` PR 21, plans only. Later batches replay its signed synchronize event through the local test tunnel; Actions, callbacks and comment writes are real. The before CLI reverses the inactive renderer patch; after retains it.

**Still blocked:** small/heavy management-policy scenarios need an EE test license. The dedicated App is installed on all three fixtures. These scenarios remain incomplete; use the same instrumentation on an actual delayed run before changing write ordering or error behavior.

Branch: `perf/action-comment-latency`. No PR created. Local setup video: [backend-setup.webm](results/local-startup/backend-setup.webm).

[Health/report recording](results/local-startup/live-review.webm) · [report screenshot](results/local-startup/live-report.png).
