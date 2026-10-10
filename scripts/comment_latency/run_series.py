"""Run serial three-project fixture batches and retain every observation."""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


root = Path(__file__).resolve().parent
output = root / 'results' / 'live'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--phase', choices=('before', 'after'), required=True)
parser.add_argument('--samples', nargs='+', type=int, required=True)
args = parser.parse_args()


def discover():
    subprocess.run([sys.executable, str(root / 'observe_dispatches.py')], check=True)


def wait_for_jobs(job_ids):
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        discover()
        markers = [json.loads(p.read_text()) for p in output.glob('observer-*.json')]
        selected = [m for m in markers if m['job_id'] in job_ids]
        finished = []
        for marker in selected:
            path = output / f"{marker['phase']}-{marker['run']}.jsonl"
            if not path.exists():
                continue
            records = [json.loads(line) for line in path.read_text().splitlines()]
            summary = next((r for r in records if r['kind'] == 'summary'), None)
            if summary:
                finished.append((marker, summary))
        if len(finished) == len(job_ids):
            for marker, summary in finished:
                log_path = output / f"{marker['run']}-cli.log"
                if not log_path.exists():
                    with log_path.open('w') as log:
                        subprocess.run(['gh', 'run', 'view', str(marker['run']), '--repo', 's1ntaxe770r/terragrun-test', '--log'], stdout=log, check=True)
                    log_path.chmod(0o600)
                print(json.dumps({'run': marker['run'], **summary}), flush=True)
            if any(s['conclusion'] != 'success' for _, s in finished):
                raise SystemExit('A workflow failed; retained evidence and stopped the series')
            return
        time.sleep(5)
    raise SystemExit('Observation deadline reached; retained evidence and stopped the series')


existing = {p.stem for p in (output / 'dispatch').glob('*.json')}
if existing:
    wait_for_jobs(existing)
for sample in args.samples:
    previous = {p.stem for p in (output / 'dispatch').glob('*.json')}
    subprocess.run([sys.executable, str(root / 'replay_pr.py'), '--phase', args.phase, '--sample', str(sample)], check=True)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        discover()
        jobs = {p.stem for p in (output / 'dispatch').glob('*.json')} - previous
        if len(jobs) == 3:
            break
        time.sleep(3)
    else:
        raise SystemExit('Expected three dispatches; inspect backend log before retrying')
    wait_for_jobs(jobs)
