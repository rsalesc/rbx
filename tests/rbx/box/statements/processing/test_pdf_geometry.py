import pathlib
import zlib

import pytest

from rbx.box.statements.processing import pdf_geometry


def _pdf(page_dict: bytes, compressed: bool) -> bytes:
    """A skeletal PDF whose page dictionary is either plain or inside a
    compressed object stream, the way pdfTeX writes PDF 1.5."""
    if not compressed:
        return b'%PDF-1.4\n1 0 obj\n' + page_dict + b'\nendobj\ntrailer\n%%EOF\n'
    payload = zlib.compress(b'1 0 ' + page_dict)
    return (
        b'%PDF-1.5\n2 0 obj\n<< /Type /ObjStm /Filter /FlateDecode >>\nstream\n'
        + payload
        + b'\nendstream\nendobj\n%%EOF\n'
    )


@pytest.mark.parametrize('compressed', [False, True])
def test_media_box_reads_plain_and_compressed_pages(compressed):
    data = _pdf(b'<< /Type /Page /MediaBox [0 0 41.577 13.295] >>', compressed)
    assert pdf_geometry.media_box(data) == pytest.approx((41.577, 13.295))


def test_page_height_is_in_big_points(tmp_path: pathlib.Path):
    path = tmp_path / 'fig.pdf'
    path.write_bytes(_pdf(b'<< /MediaBox [0 -3.2 72 68.8] >>', compressed=True))
    assert pdf_geometry.page_height_bp(path) == pytest.approx(72.0)


@pytest.mark.parametrize(
    'data', [b'not a pdf', b'%PDF-1.5\nstream\n\x00garbage\nendstream\n', b'']
)
def test_unreadable_pdfs_have_no_height(tmp_path: pathlib.Path, data):
    path = tmp_path / 'fig.pdf'
    path.write_bytes(data)
    assert pdf_geometry.page_height_bp(path) is None


def test_missing_file_has_no_height(tmp_path: pathlib.Path):
    assert pdf_geometry.page_height_bp(tmp_path / 'absent.pdf') is None


def test_page_size_is_the_media_box(tmp_path: pathlib.Path):
    path = tmp_path / 'figure.pdf'
    path.write_bytes(_pdf(b'<< /MediaBox [0 -3.2 41.5 68.8] >>', compressed=True))
    assert pdf_geometry.page_size_bp(path) == pytest.approx((41.5, 72.0))


def test_page_size_of_a_degenerate_page_is_unknown(tmp_path: pathlib.Path):
    path = tmp_path / 'figure.pdf'
    path.write_bytes(_pdf(b'<< /MediaBox [0 0 0 10] >>', compressed=False))
    assert pdf_geometry.page_size_bp(path) is None
    assert pdf_geometry.page_size_bp(tmp_path / 'absent.pdf') is None
