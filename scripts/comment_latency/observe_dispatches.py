"""Start read-only observers for jobs dispatched by the local profiling backend."""

import json
import re
import subprocess
import sys
from pathlib import Path

from measure import gh_api


root = Path(__file__).resolve().parent
output = root / 'results' / 'live'
repo = 's1ntaxe770r/terragrun-test'
metadata = {}
for path in (output / 'dispatch').glob('*.json'):
    item = json.loads(path.read_text())
    metadata[item['job_id']] = item
runs = gh_api(f'repos/{repo}/actions/runs?branch=perf/comment-latency-20261010&per_page=100')['workflow_runs']
for run in runs:
    marker = output / f"observer-{run['id']}.json"
    if marker.exists():
        continue
    jobs = gh_api(f"repos/{repo}/actions/runs/{run['id']}/jobs")['jobs']
    matches = [metadata[step['name']] for job in jobs for step in job['steps'] if step['name'] in metadata]
    if len(matches) != 1:
        continue
    item = matches[0]
    url = run['html_url']
    pattern = r"^\|[^\n]*href='" + re.escape(url) + r"'>(?:succeeded|failed)</a>"
    command = [
        sys.executable, str(root / 'measure.py'), 'observe',
        '--repo', repo, '--pr', '21', '--run', str(run['id']),
        '--attempt', str(run['run_attempt']), '--comment', item['comment_id'],
        '--scenario', 'standard-three-projects', '--phase', item['phase'],
        '--revision', item['source_ref'], '--environment', 'local-native-github-ubuntu',
        '--final-regex', pattern, '--correlation-text', url, '--timeout', '1800',
        '--output', str(output / f"{item['phase']}-{run['id']}.jsonl"),
    ]
    with (output / f"{run['id']}-observer.log").open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
    marker.write_text(json.dumps({
        'run': run['id'], 'job_id': item['job_id'], 'comment_id': item['comment_id'],
        'phase': item['phase'], 'pid': process.pid, 'workflow_sha': run['head_sha'],
    }, indent=2) + '\n')
    print(f"Observing {run['id']}, job {item['job_id']}, comment {item['comment_id']}")
