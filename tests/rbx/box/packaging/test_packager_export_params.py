from rbx.box.packaging.boca.packager import BocaPackager
from rbx.box.packaging.polygon.packager import PolygonPackager
from rbx.box.statements.schema import ConversionType


def test_polygon_packager_forces_externalize_and_demacro():
    poly = PolygonPackager(testcase_entries=[])
    by_type = {step.type: step for step in poly.statement_export_params()}
    assert by_type[ConversionType.rbxToTex].externalize is True
    assert by_type[ConversionType.TexToPDF].externalize is True
    assert by_type[ConversionType.TexToPDF].demacro is True


def test_non_polygon_packager_has_no_export_params():
    boca = BocaPackager(testcase_entries=[])
    assert boca.statement_export_params() == []
