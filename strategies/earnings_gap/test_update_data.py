import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, call, patch

import requests
import update_data as u
import monitoring as m


class FetchTest(unittest.TestCase):
    def test_success_is_not_repeated(self):
        response = Mock()
        response.json.return_value = {'ok': True}
        with patch.object(u.SESSION, 'get', return_value=response) as get, patch.object(u.time, 'sleep') as sleep:
            self.assertEqual(u.get_json('https://example.invalid/', params={'page': 2}), {'ok': True})
        get.assert_called_once_with('https://example.invalid/', timeout=25, params={'page': 2})
        sleep.assert_not_called()

    def test_transient_failures_repeat_only_the_same_read(self):
        response = Mock()
        response.json.return_value = {'rows': [1]}
        failures = [requests.ReadTimeout('slow'), requests.ConnectionError('disconnected'), response]
        with patch.object(u.SESSION, 'get', side_effect=failures) as get, patch.object(u.time, 'sleep') as sleep:
            self.assertEqual(u.get_json('https://example.invalid/', params={'page': 2}), {'rows': [1]})
        self.assertEqual(get.call_args_list, [call('https://example.invalid/', timeout=25, params={'page': 2})] * 3)
        self.assertEqual(sleep.call_args_list, [call(2), call(4)])

    def test_continuous_timeout_stops_after_three_attempts(self):
        error = requests.ReadTimeout('still unavailable')
        with patch.object(u.SESSION, 'get', side_effect=error) as get, patch.object(u.time, 'sleep') as sleep:
            with self.assertRaises(requests.ReadTimeout) as result:
                u.get_json('https://example.invalid/')
        self.assertIs(result.exception, error)
        self.assertEqual(get.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(2), call(4)])

    def test_http_errors_including_rate_limits_are_not_retried(self):
        for status in [403, 429, 500]:
            with self.subTest(status=status):
                response = Mock()
                response.raise_for_status.side_effect = requests.HTTPError(str(status))
                with patch.object(u.SESSION, 'get', return_value=response) as get, patch.object(u.time, 'sleep') as sleep:
                    with self.assertRaises(requests.HTTPError): u.get_json('https://example.invalid/')
                self.assertEqual(get.call_count, 1)
                sleep.assert_not_called()

    def test_invalid_json_is_not_retried_or_accepted(self):
        response = Mock()
        response.json.side_effect = ValueError('invalid JSON')
        with patch.object(u.SESSION, 'get', return_value=response) as get, patch.object(u.time, 'sleep') as sleep:
            with self.assertRaises(ValueError): u.get_json('https://example.invalid/')
        self.assertEqual(get.call_count, 1)
        sleep.assert_not_called()

    def test_exhausted_fetch_preserves_live_and_records_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / 'live.json').write_text('{"records":[]}', encoding='utf-8')
            (data / 'stock_metadata.json').write_text('{}', encoding='utf-8')
            before = (data / 'live.json').read_bytes()
            with patch.object(u, 'DATA', data), patch.object(m, 'DATA', data), patch.object(u.time, 'sleep'), \
                 patch.object(u.SESSION, 'get', side_effect=requests.ReadTimeout('offline')) as get:
                with self.assertRaises(requests.ReadTimeout): u.monitored_update()
            self.assertEqual(get.call_count, 3)
            self.assertEqual((data / 'live.json').read_bytes(), before)
            self.assertEqual(json.loads((data / 'monitor.json').read_text('utf-8'))['status'], 'FAILED')


if __name__ == '__main__': unittest.main()
