import os
import sys
import unittest

# Ensure web module can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web")))

import noc_web


class TestNocWebTemplatesAndStatic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        noc_web.app.config["TESTING"] = True
        cls.client = noc_web.app.test_client()

    def test_app_folders_configured(self):
        """Ensure template and static folders point to web/templates and web/static."""
        template_folder = noc_web.app.template_folder
        static_folder = noc_web.app.static_folder
        self.assertTrue(os.path.isdir(template_folder), f"Template folder missing: {template_folder}")
        self.assertTrue(os.path.isdir(static_folder), f"Static folder missing: {static_folder}")
        self.assertTrue(os.path.isfile(os.path.join(template_folder, "login.html")))
        self.assertTrue(os.path.isfile(os.path.join(template_folder, "dashboard.html")))
        self.assertTrue(os.path.isfile(os.path.join(static_folder, "css", "login.css")))
        self.assertTrue(os.path.isfile(os.path.join(static_folder, "css", "dashboard.css")))
        self.assertTrue(os.path.isfile(os.path.join(static_folder, "js", "dashboard.js")))

    def test_login_page_renders_with_template(self):
        """GET /login should render login.html and link to static/css/login.css."""
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("REGTECHES NOC", html)
        self.assertIn("Network Operations Center", html)
        self.assertIn("/static/css/login.css", html)
        self.assertIn('name="username"', html)
        self.assertIn('name="password"', html)

    def test_login_invalid_credentials_renders_error(self):
        """POST /login with invalid credentials should show error message."""
        response = self.client.post("/login", data={"username": "wrong", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Invalid credentials", html)

    def test_login_success_and_authenticated_dashboard(self):
        """POST /login with valid credentials redirects and enables dashboard access."""
        auth_user = noc_web.AUTH_USER
        auth_pass = noc_web.AUTH_PASS

        # Prior to login, GET / should redirect to /login
        unauth_resp = self.client.get("/")
        self.assertEqual(unauth_resp.status_code, 302)
        self.assertIn("/login", unauth_resp.headers["Location"])

        # Authenticate
        with self.client:
            login_resp = self.client.post("/login", data={"username": auth_user, "password": auth_pass})
            self.assertEqual(login_resp.status_code, 302)

            # Access dashboard
            dash_resp = self.client.get("/")
            self.assertEqual(dash_resp.status_code, 200)
            dash_html = dash_resp.get_data(as_text=True)
            self.assertIn("REGTECHES NOC", dash_html)
            self.assertIn(f"v{noc_web.APP_VERSION}", dash_html)
            self.assertIn("/static/css/dashboard.css", dash_html)
            self.assertIn("/static/js/dashboard.js", dash_html)
            self.assertIn("cardsArea", dash_html)
            self.assertIn("logPanel", dash_html)

    def test_static_files_served_successfully(self):
        """Verify static CSS and JS assets are served with HTTP 200."""
        css_login_resp = self.client.get("/static/css/login.css")
        self.assertEqual(css_login_resp.status_code, 200)
        self.assertIn(".login-card", css_login_resp.get_data(as_text=True))

        css_dash_resp = self.client.get("/static/css/dashboard.css")
        self.assertEqual(css_dash_resp.status_code, 200)
        self.assertIn(".header", css_dash_resp.get_data(as_text=True))

        js_dash_resp = self.client.get("/static/js/dashboard.js")
        self.assertEqual(js_dash_resp.status_code, 200)
        self.assertIn("fetchStatus", js_dash_resp.get_data(as_text=True))


class TestOverview(unittest.TestCase):
    """Overview page and /api/overview, using temporary in-memory state only."""

    def setUp(self):
        noc_web.app.config["TESTING"] = True
        self.client = noc_web.app.test_client()
        self._saved = (noc_web.nodes, noc_web.node_statuses, set(noc_web.maintenance_ips),
                       list(noc_web.metrics_history))
        noc_web.nodes = [
            {"name": "A", "ip": "192.0.2.1", "group": "Servers"},
            {"name": "B", "ip": "192.0.2.2", "group": "Servers"},
            {"name": "C", "ip": "192.0.2.3", "group": "Network"},
            {"name": "D", "ip": "192.0.2.4", "group": "Network"},
        ]
        noc_web.node_statuses = {
            "192.0.2.1": {"online": True,  "ms": 10},
            "192.0.2.2": {"online": True,  "ms": 30},
            "192.0.2.3": {"online": False, "ms": 0},
            "192.0.2.4": {"online": False, "ms": 0},   # in maintenance below
        }
        noc_web.maintenance_ips = {"192.0.2.4"}
        noc_web.metrics_history.clear()

    def tearDown(self):
        noc_web.nodes, noc_web.node_statuses = self._saved[0], self._saved[1]
        noc_web.maintenance_ips = self._saved[2]
        noc_web.metrics_history.clear()
        noc_web.metrics_history.extend(self._saved[3])

    def _login(self):
        resp = self.client.post("/login", data={"username": noc_web.AUTH_USER, "password": noc_web.AUTH_PASS})
        self.assertEqual(resp.status_code, 302)

    def test_overview_requires_login(self):
        for path in ("/overview", "/api/overview"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 302, path)
            self.assertIn("/login", resp.headers["Location"])

    def test_compute_overview_counts_and_health(self):
        ov = noc_web._compute_overview()
        self.assertEqual((ov["online"], ov["offline"], ov["maintenance"], ov["total"]), (2, 1, 1, 4))
        self.assertEqual(ov["health"], "warn")
        self.assertEqual(ov["avg_ms"], 20.0)   # only online servers count

    def test_compute_overview_all_down_and_all_up(self):
        noc_web.maintenance_ips = set()
        for st in noc_web.node_statuses.values():
            st["online"], st["ms"] = False, 0
        ov = noc_web._compute_overview()
        self.assertEqual((ov["health"], ov["avg_ms"]), ("bad", None))
        for st in noc_web.node_statuses.values():
            st["online"], st["ms"] = True, 5
        self.assertEqual(noc_web._compute_overview()["health"], "good")

    def test_record_metrics_snapshot_appends_a_point(self):
        noc_web._record_metrics_snapshot()
        self.assertEqual(len(noc_web.metrics_history), 1)
        point = noc_web.metrics_history[-1]
        self.assertEqual((point["online"], point["offline"], point["total"]), (2, 1, 4))
        self.assertIn("ts", point)

    def test_api_overview_payload(self):
        noc_web._record_metrics_snapshot()
        with self.client:
            self._login()
            resp = self.client.get("/api/overview")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
        self.assertEqual(set(data), {"summary", "metrics_history", "nodes"})
        self.assertEqual(data["summary"]["online"], 2)
        self.assertEqual(data["summary"]["health"], "warn")
        self.assertEqual(len(data["metrics_history"]), 1)
        by_name = {n["name"]: n for n in data["nodes"]}
        self.assertTrue(by_name["A"]["online"])
        self.assertFalse(by_name["C"]["online"])
        self.assertTrue(by_name["D"]["in_maintenance"])

    def test_overview_page_renders_and_links(self):
        with self.client:
            self._login()
            resp = self.client.get("/overview")
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertIn("/static/js/overview.js", html)
            self.assertIn("/static/css/overview.css", html)
            self.assertIn("chStatus", html)
            # The dashboard links to it
            self.assertIn('href="/overview"', self.client.get("/").get_data(as_text=True))
        for static_path in ("/static/js/overview.js", "/static/css/overview.css"):
            static_resp = self.client.get(static_path)
            self.assertEqual(static_resp.status_code, 200, static_path)
            static_resp.close()


if __name__ == "__main__":
    unittest.main()
