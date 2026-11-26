import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docautomate.app import create_app  # noqa: E402
from docautomate.render import find_soffice  # noqa: E402


@pytest.fixture
def app(tmp_path):
    return create_app(data_dir=tmp_path / "data", testing=True)


@pytest.fixture
def client(app):
    """A logged-in super user, like the office owner. Tests for plain users and anonymous access
    make their own clients."""
    c = app.test_client()
    make_user(app, "test", "Тест Тестов", is_super=True)
    r = c.post("/login", data={"username": "test", "password": "parola-123"})
    assert r.status_code == 302
    return c


def make_user(app, username, full_name="", is_super=False, password="parola-123"):
    from werkzeug.security import generate_password_hash

    from docautomate.db import connect
    conn = connect(Path(app.config["DATABASE"]))
    conn.execute("INSERT INTO app_user (username, full_name, password_hash, is_super) VALUES (?,?,?,?)",
                 (username, full_name, generate_password_hash(password), 1 if is_super else 0))
    conn.commit()
    conn.close()


needs_pdf = pytest.mark.skipif(find_soffice() is None, reason="LibreOffice not installed")
