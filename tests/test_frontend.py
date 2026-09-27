
from pathlib import Path

import pytest


FRONTEND = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "static"
    / "index.html"
)


@pytest.fixture(scope="module")
def html():
    return FRONTEND.read_text(encoding="utf-8")


def test_login_does_not_contain_default_password(html):
    """The login form must not contain a fixed password."""

    assert 'value="Alphaik123!"' not in html
    assert 'autocomplete="current-password"' in html


def test_logout_button_exists(html):
    """Users must have a visible logout control."""

    assert 'id="logoutBtn"' in html
    assert "خروج از حساب" in html


def test_logout_calls_backend(html):
    """The logout button must call the backend API."""

    assert '"/api/logout"' in html
    assert '"POST"' in html
    assert "resetSession(" in html


def test_expired_sessions_are_handled(html):
    """The interface must handle expired sessions."""

    assert "scheduleExpiry(data.expires_in)" in html
    assert "response.status === 401" in html
    assert "expireSession()" in html


def test_untrusted_data_is_escaped(html):
    """Project data must be escaped before HTML rendering."""

    assert "function escapeHTML(" in html

    assert "escapeHTML(project.name)" in html
    assert "escapeHTML(upload.filename)" in html
    assert "escapeHTML(issue.message)" in html
    assert "escapeHTML(activity.activity_name)" in html


def test_existing_project_features_remain(html):
    """Security changes must preserve the main application views."""

    required_ids = [
        "login",
        "app",
        "projectsView",
        "dashboardView",
        "scheduleView",
        "projectList",
        "uploadBtn",
        "versions",
        "rows",
    ]

    for element_id in required_ids:
        assert f'id="{element_id}"' in html


def test_token_is_not_saved_in_browser_storage(html):
    """The session token must not be persisted in browser storage."""

    assert "localStorage.setItem" not in html
    assert "sessionStorage.setItem" not in html
