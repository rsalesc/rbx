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


def test_copy_text_macos_uses_pbcopy(monkeypatch):
    monkeypatch.setattr(sharing.sys, 'platform', 'darwin')
    captured = {}

    def fake_run(argv, input=None, **k):
        captured['argv'] = argv
        captured['input'] = input
        return mock.Mock(returncode=0)

    monkeypatch.setattr(sharing.subprocess, 'run', fake_run)
    monkeypatch.setattr(sharing.shutil, 'which', lambda n: '/usr/bin/pbcopy')
    assert sharing.copy_text_to_clipboard('hello') is True
    assert captured['argv'] == ['pbcopy']
    assert captured['input'] == b'hello'


def test_copy_text_linux_wayland_uses_wl_copy(monkeypatch):
    monkeypatch.setattr(sharing.sys, 'platform', 'linux')
    monkeypatch.setenv('WAYLAND_DISPLAY', 'wayland-0')
    monkeypatch.setattr(
        sharing.shutil,
        'which',
        lambda n: '/usr/bin/wl-copy' if n == 'wl-copy' else None,
    )
    seen = {}
    monkeypatch.setattr(
        sharing.subprocess,
        'run',
        lambda argv, input=None, **k: seen.update(argv=argv) or mock.Mock(returncode=0),
    )
    assert sharing.copy_text_to_clipboard('x') is True
    assert seen['argv'][0] == 'wl-copy'


def test_copy_image_unsupported_returns_false(monkeypatch):
    monkeypatch.setattr(sharing.sys, 'platform', 'win32')
    assert sharing.copy_image_to_clipboard(sharing.Path('/tmp/x.png')) is False


def test_copy_image_macos_escapes_path_quotes(monkeypatch, tmp_path):
    monkeypatch.setattr(sharing.sys, 'platform', 'darwin')
    seen = {}

    def fake_run(argv, **k):
        seen['argv'] = argv
        return mock.Mock(returncode=0)

    monkeypatch.setattr(sharing.subprocess, 'run', fake_run)
    weird = tmp_path / 'a"b.png'
    weird.write_bytes(b'x')
    assert sharing.copy_image_to_clipboard(weird) is True
    script = seen['argv'][-1]
    # the raw quote must be backslash-escaped inside the AppleScript string
    assert '\\"' in script


def test_copy_image_linux_missing_tool_does_not_read(monkeypatch, tmp_path):
    monkeypatch.setattr(sharing.sys, 'platform', 'linux')
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    monkeypatch.setattr(sharing.shutil, 'which', lambda n: None)
    missing = tmp_path / 'does-not-exist.png'  # never created
    assert sharing.copy_image_to_clipboard(missing) is False


def test_copy_text_oserror_returns_false(monkeypatch):
    monkeypatch.setattr(sharing.sys, 'platform', 'darwin')
    monkeypatch.setattr(sharing.shutil, 'which', lambda n: '/usr/bin/pbcopy')

    def boom(*a, **k):
        raise OSError('exec failed')

    monkeypatch.setattr(sharing.subprocess, 'run', boom)
    assert sharing.copy_text_to_clipboard('x') is False
