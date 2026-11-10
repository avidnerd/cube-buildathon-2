import pytest


@pytest.fixture(autouse=True)
def default_style(tmp_path, monkeypatch):
    """Unit tests run against the default rule style: no trained model, no personal style."""
    from backend.harmony import harmonizer, neural
    monkeypatch.setattr(harmonizer, "STYLE_PATH", tmp_path / "style.json")
    monkeypatch.setattr(neural, "MODEL_PATH", tmp_path / "harmony_net.npz")
    monkeypatch.setattr(neural, "PERSONAL_PATH", tmp_path / "personal_style.json")
