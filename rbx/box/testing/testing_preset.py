import pathlib

from rbx import utils
from rbx.box.presets.schema import Preset
from rbx.box.testing.testing_shared import PathOrStr, TestingShared


class TestingPreset(TestingShared):
    def __init__(self, root: PathOrStr):
        super().__init__(root)
        self._yml = None

    def initialize(self):
        if not self.yml_path.exists():
            self.yml_path.parent.mkdir(parents=True, exist_ok=True)
            self.yml_path.touch()
            self.yml_path.write_text(
                utils.model_to_yaml(
                    Preset(uri='rsalesc/test-preset', env=pathlib.Path('env.rbx.yml'))
                )
            )
            self.add_from_resources(
                pathlib.Path('env.rbx.yml'), pathlib.Path('presets/default/env.rbx.yml')
            )

    def yml_path(self) -> pathlib.Path:
        return self.root / 'preset.rbx.yml'

    @property
    def yml(self) -> Preset:
        if self._yml is None:
            self._yml = utils.model_from_yaml(Preset, self.yml_path.read_text())
        return self._yml

    def save(self):
        self.yml_path.write_text(utils.model_to_yaml(self.yml))
