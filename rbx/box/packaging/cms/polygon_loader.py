"""What CMS's Polygon importer (`cmscontrib/loaders/polygon.py`) reads.

The Polygon packager writes these under `--cms`, on top of a regular Polygon
package. They live here, not in the Polygon packager, because they describe
CMS: Polygon and Codeforces ignore all of them.
"""

import pathlib
from typing import List, Optional, Sequence

from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.lang import code_to_langs
from rbx.box.packaging.cms import communication, scoring, settings, testlib_cms
from rbx.box.packaging.cms.extension import CmsExtension
from rbx.box.packaging.packager import BuiltStatement
from rbx.box.schema import Package
from rbx.config import get_resources_file, get_testlib

CONF_FILE = 'cms_conf.py'
# Where the Polygon packager puts the checker, and the importer looks for it.
CHECKER_SOURCE = 'check.cpp'
_CONFIG_LINE = 'CONFIG = {}  # rbx:config'


def render_conf(
    pkg: Package,
    entries: Sequence[GenerationTestcaseEntry],
    cms_settings: Optional[CmsExtension] = None,
) -> str:
    """`files/cms_conf.py`: what CMS cannot read from `problem.xml`.

    The importer scores every test equally, marks every test public and imports
    every task as Batch, but runs this file and merges its `general` into the
    task and its `datasets` into the task's dataset. It sets rbx's group
    scoring, the task settings of `cms_settings` (see `settings`) and which
    tests are public, and for an interactive problem compiles and stores rbx's
    CMS manager (see `communication`), which needs the sources `write_files`
    ships next to it.
    """
    task = cms_settings.task if cms_settings is not None else None
    general = settings.task_keys(task)
    config = {
        'general': general,
        'durations': sorted(settings.DURATION_KEYS & general.keys()),
        'public': settings.public_testcases(task, entries),
        'score_type': scoring.SCORE_TYPE,
        'score_type_parameters': scoring.group_min_parameters(pkg, entries),
    }
    if not communication.is_communication(pkg):
        # The importer would build the checker against its own testlib, which
        # reads `quitp` as a fraction rather than rbx's percentage.
        config['checker'] = {
            'source': CHECKER_SOURCE,
            'testlib': testlib_cms.CMS_TESTLIB_FILE,
        }
    if communication.is_communication(pkg):
        config['communication'] = {
            'task_type': communication.TASK_TYPE,
            'task_type_parameters': communication.TASK_TYPE_PARAMETERS,
            'manager': communication.MANAGER_SOURCE,
            'checker_runner': communication.CHECKER_RUNNER_SOURCE
            if communication.needs_checker(pkg)
            else None,
        }
    template = get_resources_file(
        pathlib.Path('packagers') / 'cms' / 'polygon_cms_conf.py'
    ).read_text()
    assert template.count(_CONFIG_LINE) == 1
    return template.replace(_CONFIG_LINE, f'CONFIG = {config!r}')


def write_files(
    pkg: Package,
    entries: Sequence[GenerationTestcaseEntry],
    files_path: pathlib.Path,
    cms_settings: Optional[CmsExtension] = None,
):
    """Write `cms_conf.py`, and the sources it compiles, into `files/`."""
    (files_path / CONF_FILE).write_text(render_conf(pkg, entries, cms_settings))
    if communication.is_communication(pkg):
        communication.write_sources(files_path)
    else:
        (files_path / testlib_cms.CMS_TESTLIB_FILE).write_text(
            testlib_cms.patch(get_testlib().read_text())
        )


def write_statements(built_statements: List[BuiltStatement], into_path: pathlib.Path):
    """Write each language's statement where the importer finds it.

    It reads `statements/.pdf/<language>/problem.pdf` straight from disk, never
    from `problem.xml`, so the PDF is written but not declared: the Codeforces
    Gym cannot serve a declared one, and its taskbook drops dot-directories.
    """
    root = into_path / 'statements' / '.pdf'
    for built_statement in built_statements:
        language = code_to_langs([built_statement.statement.language])[0]
        path = root / language / 'problem.pdf'
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(built_statement.path.read_bytes())
