"""Restart the scoped local profiling backend and record its build identity."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', type=Path, required=True)
parser.add_argument('--phase', choices=('before', 'after'), required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent
startup = root / 'results' / 'local-startup'
live = root / 'results' / 'live'
binary = args.binary.resolve(strict=True)
pid_path = startup / 'backend.pid'
if pid_path.exists():
    pid = int(pid_path.read_text())
    command = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True).stdout.strip()
    if command:
        if not command.startswith(str(startup / 'backend-')):
            raise SystemExit('Recorded PID no longer belongs to the profiling backend')
        os.kill(pid, signal.SIGTERM)
        time.sleep(1)
old_log = startup / 'backend.log'
if old_log.exists():
    archive = live / 'backend-before.log'
    if archive.exists():
        raise SystemExit('Baseline log already archived; inspect before restarting again')
    old_log.rename(archive)
env = os.environ.copy()
env.update(dict(line.split('=', 1) for line in (root / 'backend.env').read_text().splitlines() if '=' in line and not line.startswith('#')))
env.update({
    'DATABASE_URL': 'postgres://digger:local-profile-only@127.0.0.1:55433/digger?sslmode=disable',
    'PORT': '3101', 'DIGGER_COMMENT_TIMING': '1', 'DIGGER_PPROF_DEBUG_ENABLED': '1',
    'DIGGER_LOG_LEVEL': 'INFO', 'HTTP_BASIC_AUTH': 'true', 'GIN_MODE': 'release',
    'DIGGER_PROFILE_SETTINGS': str(live / 'settings.json'),
})
with old_log.open('w') as log:
    old_log.chmod(0o600)
    process = subprocess.Popen([str(binary)], cwd=root.parents[1] / 'backend', env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
pid_path.write_text(str(process.pid) + '\n')
for _ in range(30):
    if process.poll() is not None:
        raise SystemExit('Backend exited; inspect the private local log')
    try:
        with urllib.request.urlopen('http://127.0.0.1:3101/health', timeout=2) as response:
            if response.status == 200:
                break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit('Backend health check timed out')
revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
diff = subprocess.check_output(['git', 'diff', '--', 'backend', 'libs'], cwd=root)
record = {'phase': args.phase, 'source_ref': revision, 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(), 'source_diff_sha256': hashlib.sha256(diff).hexdigest(), 'health_status': 200}
(live / f'backend-{args.phase}-build.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
