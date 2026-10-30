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


if __name__ == "__main__":
    unittest.main()
