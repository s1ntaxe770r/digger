#!/usr/bin/env python3
"""Plot synthetic Go summary-render benchmark samples, not workflow latency."""
import argparse
import collections
import json
import re
import statistics
from pathlib import Path


def read(path):
    groups = collections.defaultdict(list)
    pattern = re.compile(r'^BenchmarkSummarySynthetic/jobs_(\d+)-\d+\s+\d+\s+'
                         r'([\d.]+) ns/op\s+(\d+) B/op\s+(\d+) allocs/op$')
    for line in path.read_text().splitlines():
        match = pattern.match(line.strip())
        if match:
            count, nanos, size, allocations = match.groups()
            groups[int(count)].append(dict(ms=float(nanos) / 1e6,
                                           bytes=int(size), allocations=int(allocations)))
    if not groups:
        raise ValueError(f'No benchmark samples in {path}')
    return groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    before, after = read(args.before), read(args.after)
    if before.keys() != after.keys():
        parser.error('before/after workloads differ')
    rows = ['| Jobs | Samples before/after | Before ms | After ms | Time change | Before B/op | After B/op |',
            '|---:|---:|---:|---:|---:|---:|---:|']
    width = 360 * len(before)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="300" viewBox="0 0 {width} 300">',
           '<rect width="100%" height="100%" fill="white"/>',
           '<g font-family="sans-serif" fill="#17212b">',
           '<text x="20" y="25" font-size="18">Synthetic summary rendering — no GitHub or database calls</text>',
           '<text x="20" y="48" font-size="12">Medians with observed min/max; each panel has its own millisecond scale</text>']
    for index, count in enumerate(sorted(before)):
        old, new = before[count], after[count]
        old_ms, new_ms = statistics.median(s['ms'] for s in old), statistics.median(s['ms'] for s in new)
        rows.append(f'| {count} | {len(old)}/{len(new)} | {old_ms:.4f} | {new_ms:.4f} '
                    f'| {(new_ms / old_ms - 1) * 100:+.1f}% '
                    f'| {statistics.median(s["bytes"] for s in old):,.0f} '
                    f'| {statistics.median(s["bytes"] for s in new):,.0f} |')
        left, scale_max = 20 + index * 360, max(s['ms'] for s in old + new)
        svg.append(f'<text x="{left}" y="90" font-size="15">{count} jobs</text>')
        for y, name, samples, color in [(120, 'Before', old, '#64748b'), (195, 'After', new, '#059669')]:
            values = [s['ms'] for s in samples]
            median = statistics.median(values)
            x = lambda value: left + value / scale_max * 300
            svg += [f'<text x="{left}" y="{y-8}" font-size="12">{name}: {median:.4f} ms (n={len(samples)})</text>',
                    f'<rect x="{left}" y="{y}" width="{300 * median / scale_max:.2f}" height="22" fill="{color}"/>',
                    f'<line x1="{x(min(values)):.2f}" y1="{y+11}" x2="{x(max(values)):.2f}" y2="{y+11}" stroke="black"/>']
        svg.append(f'<text x="{left}" y="260" font-size="12">Scale: 0 … {scale_max:.4f} ms</text>')
    svg += ['<text x="20" y="288" font-size="12">Timing instrumentation disabled. Output unchanged. These results do not establish post-workflow latency.</text>',
            '</g></svg>']
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'synthetic-render.svg').write_text('\n'.join(svg))
    (args.output / 'synthetic-render.md').write_text(
        '# Synthetic summary rendering\n\nNo GitHub or database calls. '
        'Timings are descriptive local samples, not fixture workflow latency.\n\n' + '\n'.join(rows) + '\n')
    (args.output / 'synthetic-render.json').write_text(json.dumps(dict(before=before, after=after), indent=2) + '\n')
    print('\n'.join(rows))


if __name__ == '__main__':
    main()
