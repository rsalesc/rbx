"""How CMS compiles a grader problem's submissions.

CMS links a contestant's file with a grader stored as a manager (verified on
CMS 1.5.1): a Batch task with `compilation="grader"` compiles
`grader.<ext>` + the submission, and a Communication task with `"stub"`
compiles `stub.<ext>` + the submission. Only managers whose extension is a
source or header of the language are copied into the compilation, which for
C++ means `.h` headers only.
"""

from typing import Dict, List, Sequence

import typer

from rbx import console
from rbx.box.packaging.cms import communication
from rbx.box.schema import Package

# The grader's name under `files/` (see the Polygon packager).
GRADER_SOURCE = 'grader.cpp'

BATCH_TASK_TYPE_PARAMETERS = ['grader', ['', ''], 'comparator']


def _stored_grader_name(pkg: Package) -> str:
    return 'stub.cpp' if communication.is_communication(pkg) else 'grader.cpp'


def grader_config(pkg: Package, grader_files: Sequence[str]) -> Dict:
    """`CONFIG['grader']` of `cms_conf.py`: the managers to store, by stored name.

    Values are file names under `files/`, the grader's closure as the Polygon
    packager flattened it, plus rbx.h.
    """
    managers: Dict[str, str] = {}
    bad: List[str] = []
    for name in grader_files:
        if name == GRADER_SOURCE:
            managers[_stored_grader_name(pkg)] = name
        elif name.endswith('.h'):
            managers[name] = name
        else:
            bad.append(name)
    if bad:
        console.console.print(
            f'[error]Problem [item]{pkg.name}[/item] cannot be packaged for CMS: '
            f'its grader depends on {", ".join(bad)}, but CMS only makes `.h` '
            'headers available when it compiles a submission.[/error]'
        )
        raise typer.Exit(1)
    config: Dict = {'managers': managers}
    if not communication.is_communication(pkg):
        config['task_type'] = 'Batch'
        config['task_type_parameters'] = BATCH_TASK_TYPE_PARAMETERS
    return config
