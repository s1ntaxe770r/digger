#!/usr/bin/env python3
"""Read-only GitHub workflow/comment observer and offline timing report."""

import argparse
import collections
import datetime as dt
import hashlib
import html
import json
import math
import re
import statistics
import subprocess
import time
from pathlib import Path


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class Transition:
    def __init__(self):
        self.lower = None
        self.upper = None
        self.last_false = None
        self.reversions = 0

    def observe(self, matches, start, end):
        if matches:
            if self.upper is None:
                self.lower, self.upper = self.last_false, end
        else:
            if self.upper is not None:
                self.reversions += 1
            self.lower = self.upper = None
            self.last_false = start


def summarize(workflow, comment, conclusion, timed_out=False):
    result = {
        "kind": "summary", "conclusion": conclusion,
        "workflow_bounds_ms": [workflow.lower, workflow.upper],
        "comment_bounds_ms": [comment.lower, comment.upper],
        "reversions": comment.reversions, "timed_out": timed_out,
        "delay_lower_ms": None, "delay_upper_ms": None,
    }
    if workflow.upper is None:
        result["outcome"] = "workflow_incomplete"
    elif comment.upper is None:
        result["outcome"] = "missing_update"
    else:
        low = None if comment.lower is None else comment.lower - workflow.upper
        high = None if workflow.lower is None else comment.upper - workflow.lower
        result.update(delay_lower_ms=low, delay_upper_ms=high)
        if timed_out:
            result["outcome"] = "unstable"
        elif comment.lower is None:
            result["outcome"] = "initial_match_unverified"
        elif high is not None and high < 0:
            result["outcome"] = "already_final"
        elif low is not None and low > 0 and high is not None:
            result["outcome"] = "delayed"
        elif workflow.lower is None:
            result["outcome"] = "late_start"
        else:
            result["outcome"] = "overlapping_bounds"
    return result


def gh_api(endpoint):
    result = subprocess.run(
        ["gh", "api", "--method", "GET", endpoint],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if result.returncode:
        # Do not copy arbitrary CLI output, URLs, or credentials into artifacts.
        raise RuntimeError(f"gh api failed with exit code {result.returncode}")
    return json.loads(result.stdout)


def validate_identity(run, comment, args):
    if run["id"] != args.run or run["run_attempt"] != args.attempt:
        raise ValueError("Workflow run/attempt does not match the requested observation")
    expected_issue = f"https://api.github.com/repos/{args.repo}/issues/{args.pr}"
    if comment["id"] != args.comment or comment["issue_url"].lower() != expected_issue.lower():
        raise ValueError("Comment does not belong to the requested repository and PR")
    prs = run.get("pull_requests", [])
    if prs and args.pr not in [pr["number"] for pr in prs]:
        raise ValueError("Workflow lists different pull requests")


def observe(args):
    final_pattern = re.compile(args.final_regex, re.MULTILINE)
    workflow, comment_state = Transition(), Transition()
    origin = time.monotonic()
    conclusion = None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite or append another observation under the same filename.
    with args.output.open("x") as output:
        def emit(record):
            output.write(json.dumps(record, sort_keys=True) + "\n")
            output.flush()

        def fetch(endpoint):
            start = (time.monotonic() - origin) * 1000
            response = gh_api(endpoint)
            end = (time.monotonic() - origin) * 1000
            return response, start, end

        emit({
            "kind": "metadata", "schema": 1, "started_at": utc_now(),
            "repo": args.repo, "pr": args.pr, "run": args.run,
            "attempt": args.attempt, "comment": args.comment,
            "scenario": args.scenario, "phase": args.phase,
            "revision": args.revision, "environment": args.environment,
            "poll_seconds": args.poll, "stable_seconds": args.stable,
            "timeout_seconds": args.timeout,
            "final_regex": args.final_regex, "correlation_text": args.correlation_text,
        })
        try:
            while True:
                run, wstart, wend = fetch(
                    f"repos/{args.repo}/actions/runs/{args.run}/attempts/{args.attempt}"
                )
                comment, cstart, cend = fetch(
                    f"repos/{args.repo}/issues/comments/{args.comment}"
                )
                validate_identity(run, comment, args)
                body = comment.get("body") or ""
                matches = args.correlation_text in body and bool(final_pattern.search(body))
                workflow.observe(run["status"] == "completed", wstart, wend)
                comment_state.observe(matches, cstart, cend)
                conclusion = run.get("conclusion")
                emit({
                    "kind": "observation", "observed_at": utc_now(),
                    "workflow_request_ms": [wstart, wend],
                    "comment_request_ms": [cstart, cend],
                    "status": run["status"], "conclusion": conclusion,
                    "head_sha": run["head_sha"], "final_match": matches,
                    "comment_updated_at": comment.get("updated_at"),
                    "comment_sha256": hashlib.sha256(body.encode()).hexdigest(),
                })
                elapsed = time.monotonic() - origin
                stable_since = max(workflow.upper or 0, comment_state.upper or 0) / 1000
                if (workflow.upper is not None and comment_state.upper is not None
                        and elapsed - stable_since >= args.stable):
                    emit(summarize(workflow, comment_state, conclusion))
                    return 0
                if elapsed >= args.timeout:
                    emit(summarize(workflow, comment_state, conclusion, timed_out=True))
                    return 2
                time.sleep(min(args.poll, args.timeout - elapsed))
        except (RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            emit({"kind": "error", "error_type": type(exc).__name__})
            summary = summarize(workflow, comment_state, conclusion)
            summary["outcome"] = "collection_error"
            emit(summary)
            return 2


def read_sample(path):
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    metadata = [r for r in records if r.get("kind") == "metadata"]
    summaries = [r for r in records if r.get("kind") == "summary"]
    if len(metadata) != 1 or metadata[0].get("schema") != 1:
        raise ValueError(f"Invalid metadata: {path}")
    if len(summaries) > 1:
        raise ValueError(f"Multiple summaries: {path}")
    summary = summaries[0] if summaries else {
        "outcome": "interrupted", "delay_lower_ms": None, "delay_upper_ms": None,
        "reversions": 0, "conclusion": None,
    }
    for key in ("delay_lower_ms", "delay_upper_ms"):
        value = summary.get(key)
        if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError(f"Invalid timing: {path}")
    return dict(metadata[0], **summary, file=str(path))


def interval_graph(samples):
    bounded = [s for s in samples if s['outcome'] in ('delayed', 'already_final', 'overlapping_bounds')
               and s.get("delay_lower_ms") is not None
               and s.get("delay_upper_ms") is not None]
    width, label_width = 1100, 430
    height = max(100, len(bounded) * 32 + 65)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           'role="img" aria-label="Observed delay bounds in milliseconds">']
    svg.append('<rect width="100%" height="100%" fill="white"/>')
    if bounded:
        minimum = min(0, min(s["delay_lower_ms"] for s in bounded))
        maximum = max(1, max(s["delay_upper_ms"] for s in bounded))
        def x(value):
            return label_width + (value - minimum) / (maximum - minimum) * (width - label_width - 40)
        svg.append(f'<line x1="{x(0):.2f}" y1="25" x2="{x(0):.2f}" y2="{height-30}" stroke="#888"/>')
        for i, sample in enumerate(bounded):
            y = 43 + i * 32
            label = html.escape(f'{sample["scenario"]} {sample["phase"]} run {sample["run"]}/{sample["attempt"]}')
            color = '#2563eb' if sample["phase"] == 'before' else '#059669'
            low, high = sample["delay_lower_ms"], sample["delay_upper_ms"]
            svg.append(f'<text x="8" y="{y+4}" font-size="12">{label}</text>')
            svg.append(f'<line x1="{x(low):.2f}" y1="{y}" x2="{x(high):.2f}" y2="{y}" '
                       f'stroke="{color}" stroke-width="5"><title>{low:.1f} to {high:.1f} ms</title></line>')
        svg.append(f'<text x="{label_width}" y="{height-8}" font-size="12">'
                   f'{minimum:.1f} to {maximum:.1f} ms; bounded stable samples only; see table for other outcomes</text>')
    else:
        svg.append('<text x="12" y="40">No observations with finite delay bounds.</text>')
    svg.append('</svg>')
    return '\n'.join(svg)


def comparisons(groups):
    pairs = collections.defaultdict(dict)
    for (repo, scenario, environment, phase, revision), group in groups.items():
        pairs[(repo, scenario, environment)].setdefault(phase, []).append((revision, group))
    rows = []
    for key, phases in sorted(pairs.items()):
        if any(len(phases.get(phase, [])) != 1 for phase in ('before', 'after')):
            continue
        before_revision, before = phases['before'][0]
        after_revision, after = phases['after'][0]
        protocols = {(s.get('poll_seconds'), s.get('stable_seconds'), s.get('timeout_seconds'),
                      s.get('final_regex')) for s in before + after}
        if len(protocols) != 1:
            continue
        valid = lambda s: (s['outcome'] in ('delayed', 'already_final', 'overlapping_bounds')
                           and s.get('delay_lower_ms') is not None and s.get('delay_upper_ms') is not None)
        old, new = [s for s in before if valid(s)], [s for s in after if valid(s)]
        if not old or not new:
            continue
        old_low = statistics.median(s['delay_lower_ms'] for s in old)
        old_high = statistics.median(s['delay_upper_ms'] for s in old)
        new_low = statistics.median(s['delay_lower_ms'] for s in new)
        new_high = statistics.median(s['delay_upper_ms'] for s in new)
        delta_low, delta_high = new_low - old_high, new_high - old_low
        percent = '—'
        if old_low > 0 and new_low >= 0:
            percent = f'{100 * (new_low / old_high - 1):.1f} … {100 * (new_high / old_low - 1):.1f}'
        values = (*key, f'{before_revision} → {after_revision}', f'{len(old)} / {len(new)}',
                  f'{delta_low:.1f} … {delta_high:.1f}', percent)
        rows.append('<tr>' + ''.join(f'<td>{html.escape(str(v))}</td>' for v in values) + '</tr>')
    if not rows:
        return '<p>No comparable bounded before/after samples yet.</p>'
    return ('<p>After minus before: negative is faster. Bounds crossing zero do not establish improvement. '
            'These are descriptive sample comparisons, not statistical confidence intervals. '
            'Excluded outcomes remain in the table above.</p><table><tr><th>Repo</th><th>Scenario</th>'
            '<th>Environment</th><th>Revisions</th><th>Bounded n before / after</th>'
            '<th>Median change bounds (ms)</th><th>Change bounds (%)</th></tr>' + ''.join(rows) + '</table>')


def report(args):
    samples = [read_sample(path) for path in args.inputs]
    seen = set()
    for s in samples:
        identity = (s["repo"], s["run"], s["attempt"], s["comment"])
        if identity in seen:
            raise ValueError("Duplicate run/attempt/comment observation; do not inflate sample counts")
        seen.add(identity)
    groups = collections.defaultdict(list)
    for s in samples:
        key = (s["repo"], s["scenario"], s["environment"], s["phase"], s["revision"])
        groups[key].append(s)
    rows = []
    for key, group in sorted(groups.items()):
        bounded = [s for s in group if s["outcome"] in ("delayed", "already_final", "overlapping_bounds")
                   and s.get("delay_lower_ms") is not None and s.get("delay_upper_ms") is not None]
        counts = ', '.join(f'{name}: {count}' for name, count in sorted(
            collections.Counter(s["outcome"] for s in group).items()))
        median = observed_range = '—'
        if bounded:
            lows, highs = [s["delay_lower_ms"] for s in bounded], [s["delay_upper_ms"] for s in bounded]
            median = f'{statistics.median(lows):.1f} … {statistics.median(highs):.1f}'
            observed_range = f'{min(lows):.1f} … {max(highs):.1f}'
        values = (*key, len(group), len(bounded), median, observed_range, counts,
                  sum(s['reversions'] for s in group))
        rows.append('<tr>' + ''.join(f'<td>{html.escape(str(v))}</td>' for v in values) + '</tr>')
    headers = ('Repo', 'Scenario', 'Environment', 'Phase', 'Revision', 'n', 'Bounded n',
               'Median bounds (ms)', 'Observed range (ms)', 'Outcomes', 'Reversions')
    table = '<table><tr>' + ''.join(f'<th>{h}</th>' for h in headers) + '</tr>' + ''.join(rows) + '</table>'
    svg = interval_graph(samples)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'samples.json').write_text(json.dumps(samples, indent=2) + '\n')
    (args.output / 'timings.svg').write_text(svg)
    (args.output / 'report.html').write_text(
        '<!doctype html><meta charset="utf-8"><title>Comment latency</title>'
        '<style>body{font:14px system-ui;margin:24px}table{border-collapse:collapse}'
        'td,th{padding:8px;border:1px solid #ddd;text-align:left}svg{max-width:100%;height:auto}</style>'
        '<h1>Workflow-to-comment observations</h1>'
        '<p>Bounds include polling and request duration, not an exact completion timestamp. '
        'Negative bounds mean the comment was ready first. API visibility can lag browser visibility. '
        'Initial matches, late-start, interrupted, failed collections, missing and unstable updates are not zero-latency samples. '
        'Compare phases only with matching scenarios, workloads, environment and instrumentation. '
        'No tail percentiles or causal claims are inferred.</p>' + table + comparisons(groups) + svg
    )
    print(args.output / 'report.html')
    return 0


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('must be a finite positive number')
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    watch = commands.add_parser('observe', help='Read-only polling; never starts or changes a workflow')
    watch.add_argument('--repo', required=True)
    for name in ('pr', 'run', 'attempt', 'comment'):
        watch.add_argument('--' + name, type=int, required=True)
    for name in ('scenario', 'revision', 'environment', 'final-regex', 'correlation-text'):
        watch.add_argument('--' + name, required=True)
    watch.add_argument('--phase', choices=('before', 'after'), required=True)
    watch.add_argument('--output', type=Path, required=True)
    watch.add_argument('--poll', type=positive, default=2)
    watch.add_argument('--stable', type=positive, default=10)
    watch.add_argument('--timeout', type=positive, default=600)
    watch.set_defaults(func=observe)
    summary = commands.add_parser('report', help='Generate standalone HTML/SVG from observations')
    summary.add_argument('inputs', type=Path, nargs='+')
    summary.add_argument('--output', type=Path, required=True)
    summary.set_defaults(func=report)
    args = parser.parse_args()
    if args.command == 'observe':
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repo):
            parser.error('--repo must be owner/name')
        if not args.correlation_text or any(getattr(args, name) <= 0 for name in ('pr', 'run', 'attempt', 'comment')):
            parser.error('IDs must be positive and correlation text must not be empty')
    try:
        return args.func(args)
    except (OSError, ValueError, re.error) as exc:
        parser.exit(2, f'{type(exc).__name__}: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
