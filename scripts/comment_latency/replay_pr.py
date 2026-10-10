"""Replay the existing test PR event through the local test App webhook."""

import argparse
import datetime
import hashlib
import hmac
import json
import urllib.request
from pathlib import Path

from measure import gh_api


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--phase', choices=('before', 'after'), required=True)
parser.add_argument('--sample', type=int, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent
output = root / 'results' / 'live'
record_path = output / f'{args.phase}-{args.sample:02}-trigger.json'
if record_path.exists():
    raise SystemExit(f'Observation already exists: {record_path}')
env = dict(line.split('=', 1) for line in (root / 'backend.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
app = json.loads((root / 'results' / 'app-setup' / 'app.json').read_text())
settings_path = output / 'settings.json'
settings = json.loads(settings_path.read_text())
settings['phase'] = args.phase
settings_path.write_text(json.dumps(settings, indent=2) + '\n')
repo = 's1ntaxe770r/terragrun-test'
pr = gh_api(f'repos/{repo}/pulls/21')
assert pr['state'] == 'open' and not pr['merged'], 'Fixture PR must be open'
payload = {
    'action': 'synchronize', 'number': 21, 'pull_request': pr,
    'repository': gh_api(f'repos/{repo}'), 'sender': gh_api('user'),
    'installation': {'id': app['installation_id']},
}
body = json.dumps(payload).encode()
signature = 'sha256=' + hmac.new(env['GITHUB_WEBHOOK_SECRET'].encode(), body, hashlib.sha256).hexdigest()
request = urllib.request.Request(env['PUBLIC_BASE_URL'] + '/github/webhook', data=body, headers={
    'Content-Type': 'application/json', 'X-GitHub-Event': 'pull_request',
    'X-GitHub-Hook-Installation-Target-ID': env['GITHUB_APP_ID'],
    'X-Hub-Signature-256': signature,
}, method='POST')
record = {
    'repo': repo, 'pr': 21, 'pr_sha': pr['head']['sha'], 'phase': args.phase,
    'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'trigger': 'signed local replay of synchronize event through test tunnel',
}
try:
    with urllib.request.urlopen(request, timeout=180) as response:
        record['http_status'] = response.status
except Exception as error:
    record['error_type'] = type(error).__name__
    raise
finally:
    record_path.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
