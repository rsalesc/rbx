from unittest import mock

import rich.text

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


def test_recording_console_is_not_a_terminal():
    rec = sharing.recording_console(width=80)
    assert rec.record is True
    assert rec.is_terminal is False  # so rich.live.Live won't animate


def test_recording_console_does_not_write_to_real_stdout(capsys):
    # The recording console must swallow its visible output (it writes to an
    # in-memory buffer) so re-rendering a report for capture does not print it
    # to the user's terminal a second time.
    rec = sharing.recording_console(width=80)
    rec.print('should not appear on stdout')
    captured = capsys.readouterr()
    assert captured.out == ''
    assert 'should not appear on stdout' in sharing.export_text(rec)


def test_export_svg_preserves_report_colors():
    # A non-terminal recording console would otherwise drop colors; the exported
    # SVG must keep the report's styling (e.g. the bold-green 'success' style).
    rec = sharing.recording_console(width=80)
    rec.print(rich.text.Text('AC', style='success'))
    svg = sharing.export_svg(rec, title='t')
    assert 'fill: #98a84b' in svg  # theme 'success' resolves to bold green


def test_export_text_captures_rendered_content():
    rec = sharing.recording_console(width=80)
    rec.print(rich.text.Text('Timing summary: 123 ms'))
    text = sharing.export_text(rec)
    assert 'Timing summary: 123 ms' in text


def test_share_report_text_copies_to_clipboard(monkeypatch, tmp_path):
    rec = sharing.recording_console(width=80)
    rec.print('hello world')
    monkeypatch.setattr(sharing, 'copy_text_to_clipboard', lambda t: True)
    result = sharing.share_report(rec, fmt='text', title='t', out_dir=tmp_path)
    assert result.copied is True
    assert result.fmt == 'text'
    assert result.file_path is None


def test_share_report_text_falls_back_to_file(monkeypatch, tmp_path):
    rec = sharing.recording_console(width=80)
    rec.print('hello world')
    monkeypatch.setattr(sharing, 'copy_text_to_clipboard', lambda t: False)
    result = sharing.share_report(rec, fmt='text', title='t', out_dir=tmp_path)
    assert result.copied is False
    assert result.file_path is not None and result.file_path.exists()
    assert 'hello world' in result.file_path.read_text()


def test_share_report_png_copies_to_clipboard(monkeypatch, tmp_path):
    rec = sharing.recording_console(width=80)
    rec.print('hi')

    def fake_convert(svg, png_path):
        png_path.write_bytes(b'\x89PNG')
        return png_path

    monkeypatch.setattr(sharing, 'svg_to_png', fake_convert)
    monkeypatch.setattr(sharing, 'copy_image_to_clipboard', lambda p: True)
    result = sharing.share_report(rec, fmt='png', title='t', out_dir=tmp_path)
    assert result.copied is True
    assert result.fmt == 'png'
    assert result.file_path == tmp_path / 'report.png'


def test_share_report_png_copy_fails_keeps_png(monkeypatch, tmp_path):
    rec = sharing.recording_console(width=80)
    rec.print('hi')

    def fake_convert(svg, png_path):
        png_path.write_bytes(b'\x89PNG')
        return png_path

    monkeypatch.setattr(sharing, 'svg_to_png', fake_convert)
    monkeypatch.setattr(sharing, 'copy_image_to_clipboard', lambda p: False)
    result = sharing.share_report(rec, fmt='png', title='t', out_dir=tmp_path)
    assert result.copied is False
    assert result.file_path == tmp_path / 'report.png'
    assert result.file_path.exists()


def test_share_report_png_no_converter_falls_back_to_svg(monkeypatch, tmp_path):
    rec = sharing.recording_console(width=80)
    rec.print('hi')
    monkeypatch.setattr(sharing, 'svg_to_png', lambda svg, png_path: None)
    result = sharing.share_report(rec, fmt='png', title='t', out_dir=tmp_path)
    assert result.copied is False
    assert result.file_path == tmp_path / 'report.svg'
    assert result.file_path.exists()
    assert '<svg' in result.file_path.read_text()
