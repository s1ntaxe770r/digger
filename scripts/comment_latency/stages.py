#!/usr/bin/env python3
"""Summarize opt-in comment_timing logs; stage durations are inclusive."""
import argparse
import html
import json
import math
from pathlib import Path
import shlex
import statistics
from datetime import datetime

FIELDS = ('stage', 'writer', 'span_id', 'start_utc', 'end_utc', 'duration_ms',
          'outcome', 'job_id', 'batch_id', 'comment_id', 'status', 'repo', 'pr_number', 'job_count')
NOTE = 'Inclusive stage durations overlap. Do not sum them or interpret them as exclusive critical-path time.'


def parse(line):
    if line.lstrip().startswith('{'):
        event = json.loads(line)
    else:
        event = dict(token.split('=', 1) for token in shlex.split(line) if '=' in token)
    if not isinstance(event, dict) or event.get('msg') != 'comment_timing':
        return None
    result = {key: event[key] for key in FIELDS if key in event}
    duration = result.get('duration_ms')
    if isinstance(duration, bool):
        raise ValueError('invalid duration')
    duration = float(duration)
    if not math.isfinite(duration) or duration < 0:
        raise ValueError('duration must be finite and nonnegative')
    result['duration_ms'] = duration
    for field in ('stage', 'writer', 'span_id'):
        if not isinstance(result.get(field), str) or not result[field]:
            raise ValueError(f'missing {field}')
    if result.get('outcome') not in ('success', 'error'):
        raise ValueError('invalid outcome')
    times = []
    for field in ('start_utc', 'end_utc'):
        value = datetime.fromisoformat(result[field].replace('Z', '+00:00'))
        if value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
            raise ValueError('timestamps must be UTC')
        times.append(value)
    if times[1] < times[0]:
        raise ValueError('end precedes start')
    for field in FIELDS:
        if field in result and field != 'duration_ms':
            if not isinstance(result[field], (str, int)) or isinstance(result[field], bool):
                raise ValueError(f'invalid {field}')
    return result


def select(records, **filters):
    return [record for record in records if all(
        value is None or str(record.get(key)) == value for key, value in filters.items())]


def aggregate(records):
    groups = {}
    for record in records:
        groups.setdefault((record['writer'], record['stage']), []).append(record)
    rows = []
    for (writer, stage), values in sorted(groups.items()):
        durations = [value['duration_ms'] for value in values]
        rows.append(dict(writer=writer, stage=stage, n=len(values),
                         errors=sum(value['outcome'] == 'error' for value in values),
                         median=statistics.median(durations), low=min(durations), high=max(durations)))
    return rows


def table(rows):
    lines = ['| Writer / stage | n | Errors | Median ms | Range ms |',
             '|---|---:|---:|---:|---:|']
    for row in rows:
        label = html.escape(f"{row['writer']} / {row['stage']}").replace('|', '&#124;').replace('\n', ' ')
        lines.append(f"| {label} | {row['n']} | {row['errors']} | {row['median']:.3f} | {row['low']:.3f}–{row['high']:.3f} |")
    return '\n'.join(lines) + '\n\n' + NOTE + '\n'


def svg(rows):
    height = 80 + 38 * len(rows)
    maximum = max((row['median'] for row in rows), default=1) or 1
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="{height}" viewBox="0 0 1100 {height}">',
             '<rect width="100%" height="100%" fill="white"/>',
             '<g font-family="sans-serif" font-size="12" fill="#17212b">',
             '<text x="16" y="24">Observed inclusive stage durations — median milliseconds</text>']
    for index, row in enumerate(rows):
        y = 50 + index * 38
        label = html.escape(f"{row['writer']} / {row['stage']}")
        parts.extend([f'<text x="16" y="{y + 15}">{label}</text>',
                      f'<rect x="420" y="{y}" width="{500 * row["median"] / maximum:.2f}" height="22" fill="#3268ae"/>',
                      f'<text x="935" y="{y + 15}">{row["median"]:.3f} ms (n={row["n"]})</text>'])
    parts.extend([f'<text x="16" y="{height - 8}">{html.escape(NOTE)}</text>', '</g>', '</svg>'])
    return '\n'.join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    for field in ('batch', 'job', 'comment'):
        parser.add_argument(f'--{field}-id')
    args = parser.parse_args()
    records = []
    rejected = 0
    for path in args.logs:
        for line in path.read_text().splitlines():
            try:
                record = parse(line)
            except (ValueError, TypeError, KeyError, AttributeError):
                rejected += 1
                continue
            if record:
                records.append(record)
    records = select(records, batch_id=args.batch_id, job_id=args.job_id, comment_id=args.comment_id)
    if not records:
        parser.error(f'no matching timing records ({rejected} malformed lines rejected)')
    rows = aggregate(records)
    args.output.mkdir(parents=True, exist_ok=True)
    report = table(rows)
    graphic = svg(rows)
    (args.output / 'records.jsonl').write_text(''.join(json.dumps(record) + '\n' for record in records))
    (args.output / 'stages.md').write_text(report)
    (args.output / 'stages.svg').write_text(graphic)
    (args.output / 'stages.html').write_text('<!doctype html><meta charset="utf-8"><title>Comment stage timings</title>'
                                          + '<p>' + html.escape(NOTE) + '</p>' + graphic
                                          + '<pre>' + html.escape(report) + '</pre>')
    print(report)
    print(f'{len(records)} records; {rejected} malformed lines rejected.')


if __name__ == '__main__':
    main()
