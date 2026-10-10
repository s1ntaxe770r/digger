# Synthetic summary rendering

No GitHub or database calls. Timings are descriptive local samples, not fixture workflow latency.

| Jobs | Samples before/after | Before ms | After ms | Time change | Before B/op | After B/op |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 5/5 | 0.0104 | 0.0096 | -7.6% | 34,597 | 31,096 |
| 100 | 5/5 | 0.1127 | 0.0692 | -38.6% | 779,635 | 283,746 |
| 1000 | 5/5 | 4.6396 | 0.6587 | -85.8% | 54,868,752 | 3,071,919 |
