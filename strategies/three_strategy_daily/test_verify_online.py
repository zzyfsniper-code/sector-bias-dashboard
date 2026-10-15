import json
import unittest
from unittest.mock import Mock, patch

import requests

import verify_online


BATCH = {
    "run_id": "fixture-batch",
    "strategy_center": "https://zzyfsniper-code.github.io/sector-bias-dashboard/strategies/",
    "strategies": [
        {"strategy": "growth", "page_url": "https://zzyfsniper-code.github.io/sector-bias-dashboard/growth/", "run_id": "growth-fixture"},
        {"strategy": "flow", "page_url": "https://zzyfsniper-code.github.io/sector-bias-dashboard/flow/", "run_id": "flow-fixture"},
        {"strategy": "risk", "page_url": "https://zzyfsniper-code.github.io/sector-bias-dashboard/risk/", "run_id": "risk-fixture"},
    ],
}


def response(payload=None, status=200):
    text = "<html>center</html>" if payload is None else "window.DATA=" + json.dumps(payload) + ";"
    return Mock(status_code=status, text=text)


class OnlineVerifierTest(unittest.TestCase):
    def exercise(self, responses):
        session = requests.Session()
        session.get = Mock(side_effect=responses)
        with patch.object(verify_online.requests, "Session", return_value=session):
            result = verify_online.verify(BATCH)
        self.assertFalse(session.trust_env)
        self.assertTrue(session.verify)
        self.assertEqual(session.get.call_count, 4)
        self.assertEqual(session.get_adapter("https://").max_retries.total, 0)
        return result

    def test_direct_https_keeps_tls_and_verifies_both_payload_formats(self):
        with patch.dict("os.environ", {"HTTPS_PROXY": "http://unreachable.invalid:1"}):
            result = self.exercise([
                response(), response({"meta": {"runId": "growth-fixture"}}),
                response({"run_id": "flow-fixture"}), response({"run_id": "risk-fixture"}),
            ])
        self.assertEqual(result["status"], "PASS")

    def test_center_tls_failure_still_checks_all_three_strategies(self):
        result = self.exercise([
            requests.exceptions.SSLError("fixture handshake failure"),
            response({"meta": {"runId": "growth-fixture"}}),
            response({"run_id": "flow-fixture"}), response({"run_id": "risk-fixture"}),
        ])
        self.assertEqual(result["center"]["error_type"], "tls_error")
        self.assertTrue(all(item["status"] == "PASS" for item in result["strategies"]))
        self.assertEqual(result["status"], "FAIL")

    def test_one_strategy_failure_does_not_prevent_other_checks(self):
        result = self.exercise([
            response(), response({"meta": {"runId": "growth-fixture"}}),
            requests.exceptions.Timeout("fixture timeout"), response({"run_id": "risk-fixture"}),
        ])
        self.assertEqual(result["strategies"][1]["error_type"], "timeout")
        self.assertEqual(result["strategies"][2]["status"], "PASS")

    def test_old_run_with_expected_string_elsewhere_does_not_pass(self):
        result = self.exercise([
            response(), response({"meta": {"runId": "old-growth"}, "note": "growth-fixture"}),
            response({"run_id": "flow-fixture"}), response({"run_id": "risk-fixture"}),
        ])
        self.assertEqual(result["strategies"][0]["error_type"], "run_id_mismatch")
        self.assertIsNone(result["strategies"][0]["verified_run_id"])

    def test_invalid_data_and_http_failure_are_not_success(self):
        result = self.exercise([
            response(), Mock(status_code=200, text="invalid JS"),
            response(status=503), response({"run_id": "risk-fixture"}),
        ])
        self.assertEqual(result["strategies"][0]["error_type"], "invalid_strategy_data")
        self.assertEqual(result["strategies"][1]["http_status"], 503)


if __name__ == "__main__":
    unittest.main()
