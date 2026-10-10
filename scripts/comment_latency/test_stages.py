import json
import unittest

import stages


class StagesTest(unittest.TestCase):
    def event(self, **changes):
        event = dict(msg='comment_timing', stage='render', writer='backend', span_id='one',
                     start_utc='2026-10-10T00:00:00.000000001Z',
                     end_utc='2026-10-10T00:00:00.001000001Z', duration_ms=1,
                     outcome='success', batch_id='b', secret='not retained')
        event.update(changes)
        return event

    def test_json_and_text(self):
        event = self.event()
        parsed = stages.parse(json.dumps(event))
        self.assertNotIn('secret', parsed)
        text = ' '.join(f'{key}={json.dumps(value)}' for key, value in event.items())
        self.assertEqual(parsed, stages.parse(text))
        self.assertIsNone(stages.parse('time=now msg="ordinary log"'))

    def test_filters_and_aggregation(self):
        records = [stages.parse(json.dumps(self.event())),
                   stages.parse(json.dumps(self.event(duration_ms=3, outcome='error', batch_id='c')))]
        self.assertEqual(1, len(stages.select(records, batch_id='b', job_id=None)))
        row = stages.aggregate(records)[0]
        self.assertEqual((2, 1, 2, 1, 3), (row['n'], row['errors'], row['median'], row['low'], row['high']))

    def test_invalid_values(self):
        for value in [True, -1, float('nan'), float('inf'), None, 'bad']:
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                stages.parse(json.dumps(self.event(duration_ms=value)))
        for changes in [dict(start_utc='invalid'), dict(end_utc='2026-10-09T00:00:00Z'),
                        dict(start_utc='2026-10-10T00:00:00'), dict(outcome='unknown')]:
            with self.assertRaises(ValueError):
                stages.parse(json.dumps(self.event(**changes)))

    def test_escaping(self):
        records = [stages.parse(json.dumps(self.event(stage='<script>alert(1)</script>|bad')))]
        rows = stages.aggregate(records)
        self.assertNotIn('<script>', stages.svg(rows))
        self.assertIn('&lt;script&gt;', stages.svg(rows))
        self.assertIn('&#124;', stages.table(rows))
        self.assertIn('Do not sum', stages.table(rows))


if __name__ == '__main__':
    unittest.main()
