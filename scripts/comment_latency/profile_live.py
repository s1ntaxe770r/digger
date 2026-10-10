"""Capture a separate diagnostic batch; exclude its comments from comparisons."""

from concurrent.futures import ThreadPoolExecutor
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

root = Path(__file__).resolve().parent
live = root / 'results' / 'live'
output = root / 'results' / 'live-profile'
output.mkdir(exist_ok=True)
previous = {p.name for p in live.glob('observer-*.json')}
started = datetime.datetime.now(datetime.timezone.utc).isoformat()


def capture(endpoint, filename):
    request = urllib.request.Request('http://127.0.0.1:3101/debug/pprof/' + endpoint)
    with urllib.request.urlopen(request, timeout=150) as response:
        with os.fdopen(os.open(output / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as destination:
            destination.write(response.read())


with ThreadPoolExecutor(max_workers=2) as executor:
    cpu = executor.submit(capture, 'profile?seconds=120', 'cpu.pprof')
    trace = executor.submit(capture, 'trace?seconds=120', 'runtime.trace')
    subprocess.run([sys.executable, str(root / 'run_series.py'), '--phase', 'after', '--samples', '6'], check=True)
    cpu.result()
    trace.result()
capture('heap', 'heap.pprof')
markers = [json.loads(p.read_text()) for p in live.glob('observer-*.json') if p.name not in previous]
record = {'started_at': started, 'finished_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'runs': [m['run'] for m in markers], 'excluded_comments': sorted({m['comment_id'] for m in markers}), 'purpose': 'Separate diagnostic workload; CPU and runtime trace enabled, excluded from latency comparison'}
(output / 'profile.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
