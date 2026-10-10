import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import measure


class TimingTests(unittest.TestCase):
    def test_delay_includes_request_and_polling_bounds(self):
        workflow, comment = measure.Transition(), measure.Transition()
        workflow.observe(False, 0, 100)
        workflow.observe(True, 1000, 1100)
        comment.observe(False, 1200, 1300)
        comment.observe(True, 2000, 2100)
        summary = measure.summarize(workflow, comment, 'success')
        self.assertEqual(summary['outcome'], 'delayed')
        self.assertEqual(summary['delay_lower_ms'], 100)
        self.assertEqual(summary['delay_upper_ms'], 2100)

    def test_ready_before_workflow_and_late_start(self):
        workflow, comment = measure.Transition(), measure.Transition()
        comment.observe(False, 0, 10)
        comment.observe(True, 20, 100)
        workflow.observe(False, 200, 300)
        workflow.observe(True, 400, 500)
        self.assertEqual(measure.summarize(workflow, comment, 'success')['outcome'], 'already_final')
        workflow = measure.Transition()
        workflow.observe(True, 0, 100)
        self.assertEqual(measure.summarize(workflow, comment, 'success')['outcome'], 'late_start')

    def test_initial_match_could_be_previous_attempt(self):
        workflow, comment = measure.Transition(), measure.Transition()
        comment.observe(True, 0, 10)
        workflow.observe(False, 20, 30)
        workflow.observe(True, 40, 50)
        self.assertEqual(measure.summarize(workflow, comment, 'success')['outcome'], 'initial_match_unverified')

    def test_overlapping_bounds_are_not_proof_of_delay(self):
        workflow, comment = measure.Transition(), measure.Transition()
        workflow.observe(False, 0, 100)
        comment.observe(False, 200, 300)
        workflow.observe(True, 400, 500)
        comment.observe(True, 600, 700)
        self.assertEqual(measure.summarize(workflow, comment, 'success')['outcome'], 'overlapping_bounds')

    def test_reversion_resets_final_interval(self):
        comment = measure.Transition()
        comment.observe(False, 0, 10)
        comment.observe(True, 20, 30)
        comment.observe(False, 40, 50)
        self.assertIsNone(comment.upper)
        self.assertEqual(comment.reversions, 1)
        comment.observe(True, 60, 70)
        self.assertEqual([comment.lower, comment.upper], [40, 70])

    def test_missing_and_incomplete_are_not_zero_latency(self):
        workflow, comment = measure.Transition(), measure.Transition()
        self.assertEqual(measure.summarize(workflow, comment, None, True)['outcome'], 'workflow_incomplete')
        workflow.observe(True, 0, 10)
        summary = measure.summarize(workflow, comment, 'failure', True)
        self.assertEqual(summary['outcome'], 'missing_update')
        self.assertIsNone(summary['delay_lower_ms'])
        self.assertEqual(summary['conclusion'], 'failure')

    def test_identity_checks_attempt_and_pr(self):
        args = argparse.Namespace(repo='owner/repo', pr=2, run=7, attempt=3, comment=10)
        run = {'id': 7, 'run_attempt': 3, 'pull_requests': [{'number': 2}]}
        comment = {'id': 10, 'issue_url': 'https://api.github.com/repos/owner/repo/issues/2'}
        measure.validate_identity(run, comment, args)
        run['run_attempt'] = 2
        with self.assertRaises(ValueError):
            measure.validate_identity(run, comment, args)
        run['run_attempt'] = 3
        comment['issue_url'] = comment['issue_url'].replace('/2', '/99')
        with self.assertRaises(ValueError):
            measure.validate_identity(run, comment, args)

    def test_observer_is_read_only_and_keeps_bodies_out_of_artifacts(self):
        class Clock:
            value = 0

            def now(self):
                self.value += .01
                return self.value

            def sleep(self, seconds):
                self.value += seconds

        clock = Clock()
        endpoints = []

        def api(endpoint):
            endpoints.append(endpoint)
            if '/actions/runs/' in endpoint:
                return {'id': 7, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'success',
                        'head_sha': 'abc', 'pull_requests': []}
            return {'id': 10, 'issue_url': 'https://api.github.com/repos/owner/repo/issues/2',
                    'body': 'run-7 FINAL private payload', 'updated_at': '2026-01-01T00:00:00Z'}

        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(repo='owner/repo', pr=2, run=7, attempt=1, comment=10,
                                      scenario='small', revision='abc', environment='test', phase='before',
                                      output=Path(tmp) / 'sample.jsonl', poll=.1, stable=.1, timeout=1,
                                      final_regex='FINAL', correlation_text='run-7')
            with patch.object(measure, 'gh_api', api), patch.object(measure.time, 'monotonic', clock.now), \
                    patch.object(measure.time, 'sleep', clock.sleep):
                self.assertEqual(measure.observe(args), 0)
            content = args.output.read_text()
            self.assertNotIn('private payload', content)
            self.assertEqual(measure.read_sample(args.output)['outcome'], 'initial_match_unverified')
            self.assertTrue(all('/attempts/1' in ep or '/issues/comments/10' in ep for ep in endpoints))
            with self.assertRaises(FileExistsError):
                measure.observe(args)

    def test_api_failure_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(repo='owner/repo', pr=2, run=7, attempt=1, comment=10,
                                      scenario='small', revision='abc', environment='test', phase='before',
                                      output=Path(tmp) / 'sample.jsonl', poll=.1, stable=.1, timeout=1,
                                      final_regex='FINAL', correlation_text='run-7')
            with patch.object(measure, 'gh_api', side_effect=RuntimeError('private error')):
                self.assertEqual(measure.observe(args), 2)
            self.assertEqual(measure.read_sample(args.output)['outcome'], 'collection_error')
            self.assertNotIn('private error', args.output.read_text())

    def test_before_after_comparison_uses_conservative_bounds(self):
        groups = {
            ('owner/repo', 'small', 'local', 'before', 'base'): [
                dict(outcome='delayed', delay_lower_ms=100, delay_upper_ms=200)],
            ('owner/repo', 'small', 'local', 'after', 'fix'): [
                dict(outcome='delayed', delay_lower_ms=20, delay_upper_ms=50)],
        }
        report = measure.comparisons(groups)
        self.assertIn('-180.0 … -50.0', report)
        self.assertIn('-90.0 … -50.0', report)
        groups[('owner/repo', 'small', 'local', 'after', 'fix')][0]['poll_seconds'] = 9
        self.assertIn('No comparable', measure.comparisons(groups))

    def test_graph_excludes_unstable_and_failed_collections(self):
        samples = [dict(outcome=outcome, delay_lower_ms=10, delay_upper_ms=20)
                   for outcome in ('unstable', 'collection_error', 'initial_match_unverified')]
        self.assertIn('No observations with finite delay bounds', measure.interval_graph(samples))

    def test_report_retains_interrupted_samples_and_escapes_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / 'input.jsonl'
            metadata = dict(kind='metadata', schema=1, repo='owner/repo', run=1, attempt=1,
                            comment=1, phase='before', scenario='<script>x</script>',
                            environment='local', revision='abc')
            sample.write_text(json.dumps(metadata) + '\n')
            args = argparse.Namespace(inputs=[sample], output=Path(tmp) / 'report')
            with contextlib.redirect_stdout(io.StringIO()):
                measure.report(args)
            report = (args.output / 'report.html').read_text()
            self.assertIn('interrupted: 1', report)
            self.assertNotIn('<script>x</script>', report)
            self.assertIn('&lt;script&gt;', report)
            self.assertIn('No observations with finite delay bounds', (args.output / 'timings.svg').read_text())
            args.inputs.append(sample)
            with self.assertRaises(ValueError):
                measure.report(args)


if __name__ == '__main__':
    unittest.main()
