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
    return app.test_client()


needs_pdf = pytest.mark.skipif(find_soffice() is None, reason="LibreOffice not installed")
