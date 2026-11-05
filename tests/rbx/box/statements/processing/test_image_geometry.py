import struct
import zlib

import pytest

from rbx.box.statements.processing import image_geometry


def _chunk(kind: bytes, body: bytes) -> bytes:
    crc = zlib.crc32(kind + body) & 0xFFFFFFFF
    return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', crc)


def _png(width: int, height: int, ppm=None, unit: int = 1) -> bytes:
    data = b'\x89PNG\r\n\x1a\n'
    data += _chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
    if ppm is not None:
        data += _chunk(b'pHYs', struct.pack('>IIB', ppm, ppm, unit))
    data += _chunk(b'IDAT', zlib.compress(b'\x00' * (3 * width + 1) * height))
    return data + _chunk(b'IEND', b'')


def _jpeg(width: int, height: int, density=None, unit: int = 1) -> bytes:
    data = b'\xff\xd8'
    if density is not None:
        app0 = b'JFIF\x00\x01\x02' + struct.pack('>BHHBB', unit, density, density, 0, 0)
        data += b'\xff\xe0' + struct.pack('>H', len(app0) + 2) + app0
    sof = struct.pack('>BHHB', 8, height, width, 1) + b'\x01\x11\x00'
    data += b'\xff\xc0' + struct.pack('>H', len(sof) + 2) + sof
    return data + b'\xff\xda\x00\x02\xff\xd9'


def test_a_png_without_a_resolution_is_one_point_per_pixel():
    # pdfTeX's `\pdfimageresolution` default: 72 DPI.
    assert image_geometry.png_size_bp(_png(30, 20)) == (30.0, 20.0)


def test_a_png_is_laid_out_at_its_recorded_resolution():
    # 11811 px/m is 300 DPI.
    width, height = image_geometry.png_size_bp(_png(300, 150, ppm=11811))
    assert (width, height) == pytest.approx((72.0, 36.0), rel=1e-4)


def test_a_png_aspect_only_phys_is_no_resolution():
    assert image_geometry.png_size_bp(_png(30, 20, ppm=5, unit=0)) == (30.0, 20.0)


def test_a_jpeg_is_laid_out_at_its_jfif_density():
    assert image_geometry.jpeg_size_bp(_jpeg(300, 600, density=300)) == (72.0, 144.0)
    width, _ = image_geometry.jpeg_size_bp(_jpeg(254, 10, density=100, unit=2))
    assert width == pytest.approx(72.0)


def test_a_jpeg_without_a_density_is_one_point_per_pixel():
    assert image_geometry.jpeg_size_bp(_jpeg(40, 10)) == (40.0, 10.0)
    assert image_geometry.jpeg_size_bp(_jpeg(40, 10, density=0, unit=0)) == (
        40.0,
        10.0,
    )


def test_natural_size_dispatches_on_the_suffix(tmp_path):
    (tmp_path / 'a.png').write_bytes(_png(30, 20))
    (tmp_path / 'b.JPG').write_bytes(_jpeg(40, 10))
    (tmp_path / 'c.pdf').write_bytes(b'%PDF-1.4\n<< /MediaBox [0 0 50 25] >>\n')
    (tmp_path / 'd.svg').write_text('<svg/>')
    assert image_geometry.natural_size_bp(tmp_path / 'a.png') == (30.0, 20.0)
    assert image_geometry.natural_size_bp(tmp_path / 'b.JPG') == (40.0, 10.0)
    assert image_geometry.natural_size_bp(tmp_path / 'c.pdf') == (50.0, 25.0)
    assert image_geometry.natural_size_bp(tmp_path / 'd.svg') is None
    assert image_geometry.natural_size_bp(tmp_path / 'absent.png') is None
    assert image_geometry.natural_size_bp(None) is None


def test_what_is_not_an_image_has_no_size(tmp_path):
    assert image_geometry.png_size_bp(b'not a png') is None
    assert image_geometry.jpeg_size_bp(b'\xff\xd8\xff\xda') is None
    (tmp_path / 'e.png').write_bytes(b'\x89PNG garbage')
    assert image_geometry.natural_size_bp(tmp_path / 'e.png') is None
