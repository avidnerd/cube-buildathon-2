import pytest


@pytest.fixture(autouse=True)
def default_style(tmp_path, monkeypatch):
    """Unit tests run against the default style, not whatever style the user has taught."""
    from backend.harmony import harmonizer
    monkeypatch.setattr(harmonizer, "STYLE_PATH", tmp_path / "style.json")
