"""Compare retained live observations and correlated backend stages."""

import argparse
from collections import Counter
import html
import json
from pathlib import Path
import shutil

from stages import aggregate, parse, NOTE

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--input', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--backend-before', type=Path, required=True)
parser.add_argument('--backend-after', type=Path, required=True)
parser.add_argument('--exclude-comment', action='append', default=[])
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
observations = args.output / 'observations'
observations.mkdir(exist_ok=True)
phases = {}
all_results = []
for phase in ('before', 'after'):
    markers = [json.loads(p.read_text()) for p in args.input.glob('observer-*.json')]
    markers = [m for m in markers if m['phase'] == phase and str(m['comment_id']) not in args.exclude_comment]
    results, valid_jobs = [], set()
    for marker in sorted(markers, key=lambda m: m['run']):
        path = args.input / f"{phase}-{marker['run']}.jsonl"
        records = [json.loads(line) for line in path.read_text().splitlines()]
        summary = next(r for r in records if r['kind'] == 'summary')
        result = {**marker, **summary}
        result.pop('pid', None)
        results.append(result)
        if summary['outcome'] in ('already_final', 'overlapping_bounds', 'delayed'):
            valid_jobs.add(marker['job_id'])
        shutil.copyfile(path, observations / path.name)
    backend_records = []
    for line in getattr(args, 'backend_' + phase).read_text().splitlines():
        if 'comment_timing' not in line:
            continue
        record = parse(line)
        if record:
            backend_records.append(record)
    batches = {r['batch_id'] for r in backend_records if r.get('job_id') in valid_jobs and r.get('batch_id')}
    selected = [r for r in backend_records if r.get('batch_id') in batches or r.get('job_id') in valid_jobs]
    (args.output / f'{phase}-stages.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in selected))
    terminal = [r for r in selected if r['stage'] == 'job_comment_update' and r.get('status') in ('succeeded', 'failed')]
    final_rows = aggregate(terminal)
    for row in final_rows:
        row['stage'] = 'final_update_total'
    phases[phase] = {'outcomes': dict(Counter(r['outcome'] for r in results)), 'valid_runs': len(valid_jobs), 'batches': len(batches), 'stages': aggregate(selected) + final_rows}
    all_results.extend(results)
report = {'phases': phases, 'runs': all_results, 'excluded_comments': args.exclude_comment, 'note': NOTE}
(args.output / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
selected_stages = ('client', 'summary_edit', 'summary_render', 'jobs_initial', 'jobs_refresh', 'final_update_total')
rows = []
for stage in selected_stages:
    pair = [next(r for r in phases[p]['stages'] if r['writer'] == 'backend' and r['stage'] == stage) for p in ('before','after')]
    before, after = pair
    rows.append({'stage':stage, 'before':before, 'after':after, 'change_percent':100*(after['median']/before['median']-1)})
lines = ['| Stage | Before median ms | After median ms | Change | n before / after |', '|---|---:|---:|---:|---:|']
for row in rows:
    b,a=row['before'],row['after']
    lines.append(f"| {row['stage']} | {b['median']:.3f} | {a['median']:.3f} | {row['change_percent']:+.1f}% | {b['n']} / {a['n']} |")
(args.output / 'comparison.md').write_text('\n'.join(lines)+'\n\n'+NOTE+'\n')
height = 90 + len(rows)*66
maximum = max(r[p]['median'] for r in rows for p in ('before','after'))
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="{height}" viewBox="0 0 1000 {height}">', '<rect width="100%" height="100%" fill="white"/>','<g font-family="sans-serif" font-size="13" fill="#17212b">','<text x="20" y="25">Backend stage medians · before (blue), cached transport (green)</text>']
for i,row in enumerate(rows):
    y=50+i*66
    svg.append(f'<text x="20" y="{y+20}">{row["stage"]}</text>')
    for j,(phase,color) in enumerate((('before','#3268ae'),('after','#13866b'))):
        value=row[phase]['median']; yy=y+j*25
        svg.extend([f'<rect x="180" y="{yy}" width="{value/maximum*590:.3f}" height="20" fill="{color}"/>',f'<text x="790" y="{yy+15}">{value:.3f} ms (n={row[phase]["n"]})</text>'])
svg.extend(['</g></svg>'])
(args.output/'stages.svg').write_text('\n'.join(svg))
# Each horizontal interval bounds one observed final-row transition minus workflow completion.
bounded = [r for r in all_results if r['delay_lower_ms'] is not None and r['delay_upper_ms'] is not None]
low=min(0,min(r['delay_lower_ms'] for r in bounded))/1000
high=max(0,max(r['delay_upper_ms'] for r in bounded))/1000
scale=lambda ms: 230+(ms/1000-low)/(high-low)*650
svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="{95+len(bounded)*23}">','<rect width="100%" height="100%" fill="white"/>','<g font-family="sans-serif" font-size="11" fill="#17212b">','<text x="20" y="22">Final summary row − workflow completion · polling bounds (seconds)</text>',f'<line x1="{scale(0)}" y1="35" x2="{scale(0)}" y2="{60+len(bounded)*23}" stroke="#555"/>']
for i,r in enumerate(bounded):
    y=52+i*23; color='#3268ae' if r['phase']=='before' else '#13866b'
    svg.extend([f'<text x="20" y="{y+4}">{r["phase"]} · {r["run"]}</text>',f'<line x1="{scale(r["delay_lower_ms"])}" y1="{y}" x2="{scale(r["delay_upper_ms"])}" y2="{y}" stroke="{color}" stroke-width="5"/>'])
svg.extend([f'<text x="230" y="{80+len(bounded)*23}">{low:.1f} s</text>',f'<text x="{scale(0)-10}" y="{80+len(bounded)*23}">0</text>',f'<text x="880" y="{80+len(bounded)*23}">{high:.1f} s</text>','</g></svg>'])
(args.output/'delay-bounds.svg').write_text('\n'.join(svg))
print('\n'.join(lines))
print(json.dumps({p:{k:v for k,v in phases[p].items() if k not in ('stages', 'all_update_stages')} for p in phases},indent=2))

outcome_rows = ''.join(
    '<tr><td>' + phase + '</td><td>' + str(phases[phase]['batches']) + '</td><td>' + str(phases[phase]['valid_runs']) + '</td><td>' + html.escape(', '.join(f'{key}: {value}' for key,value in phases[phase]['outcomes'].items())) + '</td></tr>'
    for phase in ('before', 'after'))
stage_rows = ''.join(
    f'<tr><td>{row["stage"]}</td><td>{row["before"]["median"]:.3f}</td><td>{row["after"]["median"]:.3f}</td><td>{row["change_percent"]:+.1f}%</td><td>{row["before"]["low"]:.3f}–{row["before"]["high"]:.3f}</td><td>{row["after"]["low"]:.3f}–{row["after"]["high"]:.3f}</td></tr>' for row in rows)
reversions = sum(r['reversions'] for r in all_results)
delayed = sum(r['outcome'] == 'delayed' for r in all_results)
errors = sum(r['errors'] for phase in phases.values() for r in phase['stages'] if r['stage'] != 'final_update_total')
page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Digger comment latency</title>
<style>body{{font:16px/1.55 system-ui,sans-serif;color:#17212b;background:#f2f5f8;margin:0}}main{{max-width:1120px;margin:auto;padding:36px}}section{{background:white;padding:24px;margin:20px 0;border-radius:10px}}h1{{font-size:32px;margin:0}}h2{{font-size:21px}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #dce3e9}}img{{max-width:100%;height:auto}}a{{color:#245ea6}}.note{{border-left:4px solid #d99b27;padding-left:16px}}code{{background:#edf1f5;padding:2px 5px}}.muted{{color:#526171}}</style>
<main><h1>Digger comment latency</h1><p class="muted">Local backend + real GitHub Actions · existing test PR 21 · 2026-10-10 · no PR created</p>
<section><h2>What the runs establish</h2><p><b>{delayed} confirmed delayed rows; {reversions} observed reversions.</b> Overlapping polling bounds cannot rule out a short delay. This is API-visible summary-row timing, not browser refresh latency.</p><p class="note">Standard three-project fixture measured. Small/heavy management-policy scenarios remain blocked on an EE test license.</p>
<table><thead><tr><th>Phase</th><th>Usable batches</th><th>Usable workflows</th><th>All recorded outcomes</th></tr></thead><tbody>{outcome_rows}</tbody></table><p>Three late baseline observations are retained and excluded from stage/delay comparisons. Each batch contains three related workflows; these are not independent samples.</p></section>
<section><h2>Before / after: backend milliseconds</h2><p>The candidate reuses GitHub installation transports and their synchronized token cache. First acquisition still needs GitHub; subsequent comment updates reuse it. GitHub edit latency remains.</p><img src="stages.svg" alt="Before and after backend stage medians"><table><thead><tr><th>Stage</th><th>Before median</th><th>After median</th><th>Change</th><th>Before range</th><th>After range</th></tr></thead><tbody>{stage_rows}</tbody></table><p>{NOTE} Final update total uses only succeeded/failed job updates. Component timings include both running and final updates because batch-only correlation cannot safely separate overlapping child spans. Observed timing-event errors: {errors}. Serial exploratory batches, not randomized trials or reliable tail estimates; overlapping batches and browser refresh were not tested. Some baseline runs overlapped local compilation/race checks; network and host variability remain possible confounders.</p></section>
<section><h2>Workflow completion versus final row</h2><p>Entire interval left of zero: row confirmed final before workflow completion. An interval crossing zero is inconclusive. Poll interval is two seconds plus API request time, with ten seconds of final-state observation.</p><img src="delay-bounds.svg" alt="Polling-bounded comment delay for every usable workflow"></section>
<section><h2>Separate workload profile</h2><p>A separate three-workflow diagnostic batch captures 120 seconds of CPU and runtime activity: 550 ms of CPU samples (0.46%), too sparse to establish a CPU hotspot. The heap allocation snapshot covers process lifetime, not this batch. It is excluded from the latency comparison.</p><p><a href="cpu-top.txt">CPU profile</a> · <a href="allocation-top.txt">Cumulative allocation profile</a> · <a href="network-wait-top.txt">Aggregate network waits (includes idle/concurrent waits)</a> · <a href="profile.json">Diagnostic run IDs</a></p></section><section><h2>Scope and correctness</h2><p>The CLI summary provider returns <code>NoopCommentUpdater</code>. Its synthetic renderer improvement is inactive in this live path and is not a cause of these results. Backend asynchronous updates remain unsynchronized; this cache does not fix ordering races.</p><p>Cache tests and race checks cover concurrent reuse, App/install/key isolation, expiry and HTTP 401 invalidation. Sixteen observer/report tests pass. Cache entries live until invalidation or process exit; there is no size bound.</p><p>Fixture: <code>929d9580</code>; workflow: <code>d952ef95</code>; CLI: <code>c1962300</code> in both phases. Backend before: <code>c1962300</code>; after: <code>6de55a67</code>. Plans only; later batches use signed local replay of the existing PR event. Before CLI reverses the inactive renderer patch; after retains it.</p><p><a href="comparison.json">Summary data</a> · <a href="comparison.md">Timing table</a> · <a href="before-stages.jsonl">Before stage records</a> · <a href="after-stages.jsonl">After stage records</a> · <a href="../../README.md">Runbook</a> · <a href="../../findings.md">Findings</a> · <a href="../../results/local-startup/backend-setup.webm">Local startup recording</a> · <a href="../../results/local-startup/live-review.webm">Health and report recording</a></p></section></main></html>'''
(args.output/'report.html').write_text(page)
