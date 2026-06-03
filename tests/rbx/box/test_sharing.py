from unittest import mock

from rbx.box import sharing


def test_detect_png_converter_prefers_rsvg(monkeypatch):
    monkeypatch.setattr(
        sharing.shutil,
        'which',
        lambda name: f'/usr/bin/{name}' if name == 'rsvg-convert' else None,
    )
    conv = sharing.detect_png_converter()
    assert conv is not None
    assert conv.tool == 'rsvg-convert'


def test_detect_png_converter_none_available(monkeypatch):
    monkeypatch.setattr(sharing.shutil, 'which', lambda name: None)
    assert sharing.detect_png_converter() is None


def test_svg_to_png_invokes_converter(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sharing.shutil,
        'which',
        lambda name: f'/usr/bin/{name}' if name == 'magick' else None,
    )
    calls = []
    monkeypatch.setattr(
        sharing.subprocess,
        'run',
        lambda *a, **k: calls.append((a, k)) or mock.Mock(returncode=0),
    )
    out = sharing.svg_to_png('<svg/>', tmp_path / 'r.png')
    assert out == tmp_path / 'r.png'
    assert calls, 'converter should have been invoked'


def test_svg_to_png_returns_none_on_converter_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sharing.shutil,
        'which',
        lambda name: f'/usr/bin/{name}' if name == 'magick' else None,
    )

    def boom(*a, **k):
        raise sharing.subprocess.CalledProcessError(1, a[0] if a else 'magick')

    monkeypatch.setattr(sharing.subprocess, 'run', boom)
    assert sharing.svg_to_png('<svg/>', tmp_path / 'r.png') is None
