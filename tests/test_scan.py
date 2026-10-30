import os
import socket
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web")))

import noc_web


class TestCheckPort(unittest.TestCase):
    def test_open_port_is_online(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            online, ms = noc_web.check_port("127.0.0.1", srv.getsockname()[1], timeout=2)
        self.assertTrue(online)
        self.assertGreaterEqual(ms, 1)

    def test_closed_port_is_offline(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        online, ms = noc_web.check_port("127.0.0.1", port, timeout=1)
        self.assertEqual((online, ms), (False, 0))


class TestPingHost(unittest.TestCase):
    @staticmethod
    def _result(returncode, stdout=""):
        return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")

    def test_parses_ms_from_output(self):
        out = "64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=12.7 ms\n"
        with mock.patch("subprocess.run", return_value=self._result(0, out)):
            self.assertEqual(noc_web.ping_host("10.0.0.1"), (True, 12))

    def test_sub_millisecond_rounds_up_to_one(self):
        out = "64 bytes from 127.0.0.1: icmp_seq=1 ttl=64 time=0.04 ms\n"
        with mock.patch("subprocess.run", return_value=self._result(0, out)):
            self.assertEqual(noc_web.ping_host("127.0.0.1"), (True, 1))

    def test_success_without_time_field_is_online(self):
        with mock.patch("subprocess.run", return_value=self._result(0, "reply received\n")):
            self.assertEqual(noc_web.ping_host("10.0.0.1"), (True, 1))

    def test_nonzero_exit_is_offline(self):
        with mock.patch("subprocess.run", return_value=self._result(1)):
            self.assertEqual(noc_web.ping_host("10.0.0.1"), (False, 0))

    def test_timeout_or_missing_binary_is_offline(self):
        for exc in (subprocess.TimeoutExpired("ping", 1), FileNotFoundError()):
            with mock.patch("subprocess.run", side_effect=exc):
                self.assertEqual(noc_web.ping_host("10.0.0.1"), (False, 0))

    def test_port_suffix_is_stripped_from_host(self):
        with mock.patch("subprocess.run", return_value=self._result(1)) as run:
            noc_web.ping_host("10.0.0.1:8080")
        self.assertEqual(run.call_args[0][0][-1], "10.0.0.1")


class TestScanUptime(unittest.TestCase):
    """do_scan() should record history and uptime from the check results."""

    KEY = "192.0.2.10"

    def setUp(self):
        self._saved = {name: getattr(noc_web, name) for name in
                       ("nodes", "node_statuses", "prev_statuses", "ping_history",
                        "uptime_data", "maintenance_ips")}
        noc_web.nodes = [{"name": "Test", "ip": self.KEY, "port": 80}]
        noc_web.node_statuses = {}
        noc_web.prev_statuses = {}
        noc_web.ping_history = {}
        noc_web.uptime_data = {}
        noc_web.maintenance_ips = set()
        patches = [
            mock.patch.object(noc_web, "_write_status_json"),
            mock.patch.object(noc_web, "fetch_all_service_stats"),
            mock.patch.object(noc_web, "log_event"),
            mock.patch.object(noc_web, "send_sms_for_ip"),
            mock.patch.object(noc_web, "ping_host", return_value=(False, 0)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(noc_web, name, value)

    def _scan(self, online, ms=5):
        with mock.patch.object(noc_web, "check_port", return_value=(online, ms)):
            noc_web.do_scan()

    def test_uptime_counts_up_and_total(self):
        for state in (True, True, False, True):
            self._scan(state)
        self.assertEqual(noc_web.uptime_data[self.KEY], {"up": 3, "total": 4})

    def test_history_records_ms_and_minus_one_when_offline(self):
        self._scan(True, 7)
        self._scan(False)
        self.assertEqual(list(noc_web.ping_history[self.KEY]), [7, -1])

    def test_history_is_capped(self):
        for _ in range(noc_web.HISTORY_SIZE + 5):
            self._scan(True)
        self.assertEqual(len(noc_web.ping_history[self.KEY]), noc_web.HISTORY_SIZE)

    def test_status_updated_and_icmp_fallback_used(self):
        with mock.patch.object(noc_web, "check_port", return_value=(False, 0)), \
                mock.patch.object(noc_web, "ping_host", return_value=(True, 3)) as ping:
            noc_web.do_scan()
        ping.assert_called_once()
        self.assertTrue(noc_web.node_statuses[self.KEY]["online"])
        self.assertEqual(noc_web.node_statuses[self.KEY]["ms"], 3)

    def test_status_change_is_alerted_but_not_in_maintenance(self):
        noc_web.sms_config["alert_offline"] = True
        self.addCleanup(noc_web.sms_config.pop, "alert_offline", None)
        self._scan(True)
        self._scan(False)
        noc_web.send_sms_for_ip.assert_called_once()

        noc_web.send_sms_for_ip.reset_mock()
        noc_web.maintenance_ips.add(self.KEY)
        self._scan(True)
        self._scan(False)
        noc_web.send_sms_for_ip.assert_not_called()

    def test_api_status_reports_uptime_percentage(self):
        for state in (True, False, True, True):
            self._scan(state)
        noc_web.app.config["TESTING"] = True
        with noc_web.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["logged_in"] = True
                sess["user"] = "admin"
            data = client.get("/api/status").get_json()
        node = next(n for n in data["nodes"] if n["ip"] == self.KEY)
        self.assertEqual(node["uptime_pct"], 75.0)


if __name__ == "__main__":
    unittest.main()
