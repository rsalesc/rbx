import pathlib

from rbx import utils
from rbx.box.presets.schema import Preset, TrackedAsset, Tracking
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
                    Preset(
                        name='test-preset',
                        uri='rsalesc/test-preset',
                        env=pathlib.Path('env.rbx.yml'),
                        tracking=Tracking(),  # Explicitly include tracking
                    )
                )
            )
            self.add_from_resources(
                pathlib.Path('env.rbx.yml'), pathlib.Path('presets/default/env.rbx.yml')
            )

    @property
    def yml_path(self) -> pathlib.Path:
        return self.root / 'preset.rbx.yml'

    @property
    def yml(self) -> Preset:
        if self._yml is None:
            self._yml = utils.model_from_yaml(Preset, self.yml_path.read_text())
        return self._yml

    def save(self):
        self.yml_path.write_text(utils.model_to_yaml(self.yml))
        self._yml = None

    def set_name(self, name: str):
        """Set the preset name."""
        self.yml.name = name
        self.save()

    def set_uri(self, uri: str):
        """Set the preset URI."""
        self.yml.uri = uri
        self.save()

    def set_env(self, env_path: PathOrStr):
        """Set the environment file path."""
        self.yml.env = pathlib.Path(env_path)
        self.save()

    def set_problem_path(self, path: PathOrStr):
        """Set the problem package path."""
        self.yml.problem = pathlib.Path(path)
        self.save()

    def set_contest_path(self, path: PathOrStr):
        """Set the contest package path."""
        self.yml.contest = pathlib.Path(path)
        self.save()

    def add_problem_tracked_asset(self, path: PathOrStr, symlink: bool = False):
        """Add a tracked asset to the problem tracking list."""
        # Create a new tracking object with the updated problem list
        current_tracking = self.yml.tracking
        new_problem_list = current_tracking.problem + [
            TrackedAsset(path=pathlib.Path(path), symlink=symlink)
        ]
        self.yml.tracking = Tracking(
            problem=new_problem_list, contest=current_tracking.contest
        )
        self.save()

    def add_contest_tracked_asset(self, path: PathOrStr, symlink: bool = False):
        """Add a tracked asset to the contest tracking list."""
        # Create a new tracking object with the updated contest list
        current_tracking = self.yml.tracking
        new_contest_list = current_tracking.contest + [
            TrackedAsset(path=pathlib.Path(path), symlink=symlink)
        ]
        self.yml.tracking = Tracking(
            problem=current_tracking.problem, contest=new_contest_list
        )
        self.save()

    def create_problem_package(self):
        """Create a basic problem package structure."""
        if self.yml.problem:
            problem_dir = self.root / self.yml.problem
            problem_dir.mkdir(parents=True, exist_ok=True)

            # Create a basic problem.rbx.yml
            problem_yml = problem_dir / 'problem.rbx.yml'
            if not problem_yml.exists():
                problem_yml.write_text("""---
name: "test-problem"
timeLimit: 1000
memoryLimit: 256
""")

    def create_contest_package(self):
        """Create a basic contest package structure."""
        if self.yml.contest:
            contest_dir = self.root / self.yml.contest
            contest_dir.mkdir(parents=True, exist_ok=True)

            # Create a basic contest.rbx.yml
            contest_yml = contest_dir / 'contest.rbx.yml'
            if not contest_yml.exists():
                contest_yml.write_text("""---
name: "Test Contest"
duration: 180
""")

    def create_symlink(self, link_path: PathOrStr, target_path: PathOrStr):
        """Create a symlink from link_path to target_path relative to the preset root."""
        link = self.root / link_path
        target = pathlib.Path(target_path)

        # Ensure parent directory exists
        link.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing file/symlink if present
        if link.exists() or link.is_symlink():
            link.unlink()

        # Create symlink
        link.symlink_to(target)

    def verify_file_exists(self, path: PathOrStr) -> bool:
        """Verify that a file exists in the preset."""
        return (self.root / path).exists()

    def verify_symlink(self, path: PathOrStr, expected_target: PathOrStr) -> bool:
        """Verify that a symlink exists and points to the expected target."""
        link = self.root / path
        if not link.is_symlink():
            return False
        return link.readlink() == pathlib.Path(expected_target)

    def get_file_content(self, path: PathOrStr) -> str:
        """Get the content of a file in the preset."""
        return (self.root / path).read_text()

    def get_problem_dir(self) -> pathlib.Path:
        """Get the problem package directory."""
        if not self.yml.problem:
            raise ValueError('No problem package defined in preset')
        return self.root / self.yml.problem

    def get_contest_dir(self) -> pathlib.Path:
        """Get the contest package directory."""
        if not self.yml.contest:
            raise ValueError('No contest package defined in preset')
        return self.root / self.yml.contest
