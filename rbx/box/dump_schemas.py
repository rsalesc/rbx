import pathlib

import mkdocs_gen_files

from rbx.box.schema_export import MODELS
from rbx.utils import dump_schema_str

for model in MODELS:
    path = pathlib.Path('schemas') / f'{model.__name__}.json'
    with mkdocs_gen_files.open(str(path), 'w') as f:
        f.write(dump_schema_str(model))
