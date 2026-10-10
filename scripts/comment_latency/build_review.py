"""Render the investigation Markdown, evidence and pinned source diffs offline."""

import base64
import html
import json
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / 'results' / 'report-tools'))
import markdown

repo = root.parents[1]
base = '1b31c38995ea6fd819e608a25f3a1d8e3bfab8a2'
revision = '5123455f'
source_url = f'https://github.com/s1ntaxe770r/digger/blob/{revision}/'
text = (root / 'investigation.md').read_text()
md = markdown.Markdown(extensions=['tables', 'fenced_code', 'toc', 'sane_lists'])
body = md.convert(text)

paths = ['backend/utils/github.go', 'backend/utils/github_transport_test.go',
         'backend/controllers/projects.go', 'backend/utils/comment_utils.go',
         'libs/ci/github/github.go', 'libs/comment_utils/latency/timing.go',
         'libs/comment_utils/latency/timing_test.go', 'libs/comment_utils/summary/updater.go',
         'libs/comment_utils/summary/updater_test.go']
descriptions = [
    'Reuses installation transports; invalidates the matching cache entry after HTTP 401.',
    'Checks concurrent token reuse, identity/key isolation, expiry, revocation and stale responses.',
    'Measures the status handler; asynchronous update scheduling remains unchanged.',
    'Measures client setup, database reads, rendering, editing and the outer job/status update.',
    'Measures GitHub comment edits with comment/repository correlation.',
    'Adds opt-in monotonic stage timing with outcome and correlation fields.',
    'Verifies the helper is disabled by default and records success/error outcomes.',
    'Adds timers and a strings.Builder experiment; inactive in the tested live CLI.',
    'Adds synthetic benchmarks and output/truncation regression coverage.'
]
source = []
for path, description in zip(paths, descriptions):
    diff = subprocess.check_output(['git', 'diff', base, revision, '--', path], cwd=repo, text=True)
    lines = []
    for line in diff.splitlines():
        cls = 'diff-added' if line.startswith('+') else 'diff-removed' if line.startswith('-') else 'diff-hunk' if line.startswith('@@') else ''
        escaped = html.escape(line).replace('\t', '&#9;')
        lines.append(f'<span class="diff-line {cls}">{escaped}</span>')
    source.append(f'<details><summary>{html.escape(path)}</summary><div class="detail-body"><p>{description} <a href="{source_url}{path}">View pinned source ↗</a></p><pre tabindex="0" aria-label="Diff for {path}"><code>{"".join(lines)}</code></pre></div></details>')
numstat = subprocess.check_output(['git', 'diff', '--numstat', base, revision], cwd=repo, text=True)
rows = []
for line in numstat.splitlines():
    added, removed, path = line.split('\t')
    rows.append(f'<tr><td><a href="{source_url}{path}">{html.escape(path)}</a></td><td>+{added}</td><td>−{removed}</td></tr>')
source.append(f'<details><summary>All {len(rows)} changed paths<span class="file-count">Includes harness, documentation and retained evidence · {base[:8]} → {revision}</span></summary><div class="table-wrap"><table><thead><tr><th>Path</th><th>Added</th><th>Removed</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></details>')
source.append(f'<p><a href="{source_url}libs/comment_utils/summary/provider.go#L11">Unchanged provider: CLI summary updates are disabled ↗</a></p>')
body = body.replace('<!-- CODE_REVIEW -->', ''.join(source))
recordings = '<div class="recording-grid">'
for file, title, description in [('backend-setup.webm', 'Local backend setup', 'Authenticated setup page; no credential entry.'), ('live-review.webm', 'Health and original timing report', 'A local health check followed by the first timing report.')]:
    recordings += f'<figure><video controls preload="none" aria-label="{title}"><source src="results/local-startup/{file}" type="video/webm"></video><figcaption><strong>{title}</strong><br>{description}</figcaption></figure>'
body = body.replace('<!-- RECORDINGS -->', recordings + '</div>')

def graph(match):
    alt, path = match.group(1), match.group(2)
    svg = (root / path).read_text()
    svg = svg.replace('fill="white"', 'fill="var(--surface)"').replace('fill="#17212b"', 'fill="var(--ink)"').replace('#3268ae', 'var(--accent)').replace('#13866b', 'var(--measured)').replace('#555', 'var(--muted)')
    svg = svg.replace('<svg ', '<svg role="img" aria-label="'+html.escape(alt, quote=True)+'" ', 1)
    caption = 'Inclusive stages; components include running and final updates. Final update total uses terminal job statuses only.' if 'stages.svg' in path else 'Negative = comment final first. Crossing zero = inconclusive. On narrow screens, scroll horizontally to read run labels.'
    return f'<figure><div class="chart-window" tabindex="0" role="region" aria-label="{alt}">{svg}</div><figcaption>{caption} <a href="{path}">Open original SVG ↗</a></figcaption></figure>'
body = re.sub(r'<p><img alt="([^"]*)" src="([^"]+\.svg)"\s*/?></p>', graph, body)
body = re.sub(r'<table>(.*?)</table>', r'<div class="table-wrap" tabindex="0"><table>\1</table></div>', body, flags=re.S)
body = re.sub(r'<h2 id="([^"]+)">', r'</section><section id="\1"><h2>', body)
heading, rest = body.split('</section>', 1)
body = '<header><div class="eyebrow">Engineering investigation · draft</div>'+heading+'<div class="meta"><span>10 October 2026</span><span>Branch: perf/action-comment-latency</span><span>No PR created</span></div></header>'+rest+'</section>'
data = json.loads((root / 'evidence/live/comparison.json').read_text())
values = [next(r['median'] for r in data['phases'][p]['stages'] if r['stage']=='final_update_total') for p in ('before','after')]
chart = '<div class="signature" role="group" aria-label="Final-summary processing comparison"><h3>Less time preparing the final summary.</h3><p>Backend final-status update · median · 15 observations per phase</p>'
for phase,value in zip(('Before','After'),values):
    chart += f'<div class="bar-row"><span>{phase}</span><div class="bar-track" aria-hidden="true"><div class="bar {phase.lower()}" style="width:{value/1600*100:.5f}%"></div></div><span class="value">{value:,.3f} ms</span></div>'
chart += f'<div class="delta"><strong>{values[0]-values[1]:.3f} ms less · {(1-values[1]/values[0])*100:.1f}% reduction</strong><span>Original intermittent delay: unconfirmed</span></div></div>'
body = body.replace('<h2>Executive findings</h2>', '<h2>Executive findings</h2>'+chart)
# Link code paths in the narrative to the reviewed revision.
for path in paths:
    body = body.replace(f'<code>{path}</code>', f'<a href="{source_url}{path}"><code>{path.replace("/", "/<wbr>")}</code></a>')
tokens = md.toc_tokens[0]['children']
nav = ''.join(f'<a href="#{t["id"]}">{html.escape(t["name"])}</a>' for t in tokens)
css = (root / 'review.css').read_text()
markdown_b64 = base64.b64encode(text.encode()).decode()
script = '''
const source = new TextDecoder().decode(Uint8Array.from(atob(document.getElementById('markdown-source').textContent),c=>c.charCodeAt(0)));
const download = document.getElementById('download');
download.href = URL.createObjectURL(new Blob([source],{type:'text/markdown;charset=utf-8'}));
document.getElementById('copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(source);document.getElementById('copy-status').textContent='Markdown copied';}catch{document.getElementById('copy-status').textContent='Use Download Markdown to save the source';}});
document.getElementById('print').addEventListener('click',()=>window.print());
const links = [...document.querySelectorAll('.rail nav a')];
function markSection(){let active=links[0]?.hash;for(const s of document.querySelectorAll('main section[id]')){if(s.getBoundingClientRect().top<180)active='#'+s.id;}for(const a of links){a.setAttribute('aria-current',String(a.hash===active));}}
window.addEventListener('scroll',markSection,{passive:true});markSection();
for(const a of document.querySelectorAll('.mobile-toc a'))a.addEventListener('click',()=>document.querySelector('.mobile-toc').open=false);
'''
page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="Digger comment latency: measured before and after, profiling methodology, changed code and remaining scope."><title>Digger · Comment latency investigation</title><style>{css}</style></head><body><a class="skip" href="#article">Skip to investigation</a><div class="shell"><aside class="rail"><div class="brand"><span class="mark" aria-hidden="true">D</span>Digger</div><div class="rail-subtitle">Engineering notes / Performance</div><nav aria-label="Investigation sections">{nav}</nav><div class="rail-note">Standard fixture measured.<br>Management fixtures pending.<br><br><a href="evidence/live/comparison.json">Explore the evidence ↗</a></div></aside><main class="main"><div class="toolbar"><span class="toolbar-label">Investigation draft</span><button id="copy">Copy Markdown</button><a id="download" class="button" href="investigation.md" download="digger-comment-latency.md">Download Markdown</a><button id="print">Print</button><span id="copy-status" class="copy-status" role="status"></span></div><details class="mobile-toc"><summary>On this page</summary><nav aria-label="Investigation sections">{nav}</nav></details><article id="article" class="paper">{body}<footer class="footer">Rendered from <a href="investigation.md">investigation.md</a>. Source diffs pinned to {revision}; raw evidence remains unchanged. Design informed by <a href="https://github.com/dickwu/apple-design-skill">Apple Design Skill</a>, applied to web accessibility, typography and layout rather than native macOS controls.</footer></article></main></div><script type="text/plain" id="markdown-source">{markdown_b64}</script><script>{script}</script></body></html>'''
(root / 'review.html').write_text(page)
print(f'Rendered {len(tokens)} sections, {len(paths)} focused diffs and {len(rows)} changed paths to {root / "review.html"}')
