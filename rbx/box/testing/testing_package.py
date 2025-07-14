import pathlib
from dataclasses import dataclass
from typing import Dict, List, Optional

from rbx import console, utils
from rbx.box import package, presets
from rbx.box.fields import Primitive
from rbx.box.schema import (
    CheckerTest,
    CodeItem,
    ExpectedOutcome,
    Generator,
    Interactor,
    Package,
    Solution,
    TaskType,
    TestcaseGroup,
    ValidatorOutcome,
    ValidatorTest,
)
from rbx.box.testing.testing_preset import TestingPreset
from rbx.box.testing.testing_shared import PathOrStr, TestingShared
from rbx.grading.steps import Evaluation
from rbx.testing_utils import print_directory_tree


@dataclass
class TestcaseArtifacts:
    output: Optional[str] = None
    log: Optional[Evaluation] = None
    interactor_input: Optional[str] = None
    interactor_output: Optional[str] = None
    interactor_pipes: Optional[str] = None


class TestingPackage(TestingShared):
    def __init__(self, root: PathOrStr):
        super().__init__(root)
        self._yml = None

        self.initialize()
        self.preset = self.initialize_preset()

    @property
    def yml_path(self) -> pathlib.Path:
        return self.root / 'problem.rbx.yml'

    def initialize(self):
        if not self.yml_path.exists():
            self.yml_path.parent.mkdir(parents=True, exist_ok=True)
            self.yml_path.touch()
            self.yml_path.write_text(
                utils.model_to_yaml(
                    Package(name='test-problem', timeLimit=1000, memoryLimit=256)
                )
            )

    def initialize_preset(self) -> TestingPreset:
        preset = presets.get_active_preset_or_null(self.root)
        if preset is None:
            preset_path = self.root / '.local.rbx'
            preset_path.mkdir(parents=True, exist_ok=True)
        else:
            preset_path = presets.get_active_preset_path(self.root)
        return TestingPreset(preset_path)

    def print_tree(self):
        print_directory_tree(self.root)

    def print_yml(self):
        console.console.print(self.yml_path.read_text(), highlight=True)

    def print_debug(self):
        self.print_yml()
        self.print_tree()

    @property
    def yml(self) -> Package:
        if self._yml is None:
            self._yml = utils.model_from_yaml(Package, self.yml_path.read_text())
        return self._yml

    def save(self):
        self.yml_path.write_text(utils.model_to_yaml(self.yml))
        # Clear internal cache and package cache to ensure the updated package is loaded fresh
        self._yml = None
        package.clear_package_cache()

    def set_type(self, type: TaskType):
        self.yml.type = type
        self.save()

    def add_solution(
        self,
        path: PathOrStr,
        outcome: ExpectedOutcome,
        language: Optional[str] = None,
    ):
        self.yml.solutions = self.yml.solutions + [
            Solution(path=pathlib.Path(path), language=language, outcome=outcome)
        ]
        self.save()
        return self.add_file(path)

    def add_generator(
        self,
        path: PathOrStr,
        language: Optional[str] = None,
        alias: Optional[str] = None,
        src: Optional[PathOrStr] = None,
    ):
        if alias is not None:
            self.yml.generators = self.yml.generators + [
                Generator(path=pathlib.Path(path), language=language, name=alias)
            ]
        self.save()
        return self.add_file(path, src=src)

    def set_validator(
        self,
        path: PathOrStr,
        language: Optional[str] = None,
        src: Optional[PathOrStr] = None,
    ):
        self.yml.validator = CodeItem(path=pathlib.Path(path), language=language)
        self.save()
        return self.add_file(path, src=src)

    def set_checker(
        self,
        path: PathOrStr,
        language: Optional[str] = None,
        src: Optional[PathOrStr] = None,
    ):
        self.yml.checker = CodeItem(path=pathlib.Path(path), language=language)
        self.save()
        return self.add_file(path, src=src)

    def set_interactor(
        self,
        path: PathOrStr,
        language: Optional[str] = None,
        src: Optional[PathOrStr] = None,
    ):
        self.yml.interactor = Interactor(path=pathlib.Path(path), language=language)
        self.save()
        return self.add_file(path, src=src)

    def set_var(self, name: str, value: Primitive):
        self.yml.vars[name] = value
        self.save()

    def set_vars(self, vars: Dict[str, Primitive]):
        self.yml.vars = vars
        self.save()

    def add_testplan(self, name: str, src: Optional[PathOrStr] = None):
        path = self.add_file(pathlib.Path('testplan') / f'{name}.txt', src)
        return path

    def add_testscript(self, name: str, src: Optional[PathOrStr] = None):
        path = self.add_file(pathlib.Path('testplan') / f'{name}.py', src)
        return path

    def add_testgroup_from_glob(
        self,
        name: str,
        glob: str,
        validator: Optional[PathOrStr] = None,
        extra_validators: Optional[List[PathOrStr]] = None,
    ):
        self.yml.testcases = self.yml.testcases + [
            TestcaseGroup(
                name=name,
                testcaseGlob=glob,
                validator=CodeItem(path=pathlib.Path(validator)) if validator else None,
                extraValidators=[
                    CodeItem(path=pathlib.Path(v)) for v in extra_validators
                ]
                if extra_validators
                else [],
            )
        ]
        self.save()

    def add_testgroup_from_plan(
        self,
        name: str,
        plan: str,
        validator: Optional[PathOrStr] = None,
        extra_validators: Optional[List[PathOrStr]] = None,
    ):
        plan_path = self.add_testplan(name)
        plan_path.write_text(plan)
        self.yml.testcases = self.yml.testcases + [
            TestcaseGroup(
                name=name,
                generatorScript=CodeItem(path=plan_path),
                validator=CodeItem(path=pathlib.Path(validator)) if validator else None,
                extraValidators=[
                    CodeItem(path=pathlib.Path(v)) for v in extra_validators
                ]
                if extra_validators
                else [],
            )
        ]
        self.save()

    def add_testgroup_from_script(
        self,
        name: str,
        script: str,
        validator: Optional[PathOrStr] = None,
        extra_validators: Optional[List[PathOrStr]] = None,
    ):
        script_path = self.add_testscript(name)
        script_path.write_text(script)
        self.yml.testcases = self.yml.testcases + [
            TestcaseGroup(
                name=name,
                generatorScript=CodeItem(path=script_path),
                validator=CodeItem(path=pathlib.Path(validator)) if validator else None,
                extraValidators=[
                    CodeItem(path=pathlib.Path(v)) for v in extra_validators
                ]
                if extra_validators
                else [],
            )
        ]
        self.save()

    def get_build_testgroup_path(self, name: str) -> pathlib.Path:
        return self.root / 'build' / 'tests' / name

    def get_testcase_contents(self, path: pathlib.Path) -> TestcaseArtifacts:
        contents = TestcaseArtifacts()
        output_path = path.with_suffix('.out')
        if output_path.exists():
            contents.output = output_path.read_text()
        log_path = path.with_suffix('.log')
        if log_path.exists():
            contents.log = Evaluation.model_validate_json(log_path.read_text())
        interactor_input_path = path.with_suffix('.pin')
        if interactor_input_path.exists():
            contents.interactor_input = interactor_input_path.read_text()
        interactor_output_path = path.with_suffix('.pout')
        if interactor_output_path.exists():
            contents.interactor_output = interactor_output_path.read_text()
        interactor_pipes_path = path.with_suffix('.pio')
        if interactor_pipes_path.exists():
            contents.interactor_pipes = interactor_pipes_path.read_text()
        return contents

    def add_validator_unit_test(
        self,
        glob: str,
        outcome: ValidatorOutcome = ValidatorOutcome.VALID,
        validator: Optional[PathOrStr] = None,
        files: Optional[Dict[str, str]] = None,
    ):
        """Add a unit test for the validator.

        Args:
            glob: Glob pattern for input files
            outcome: Expected validation outcome
            validator: Optional validator to use (if not main validator)
            files: Optional dict of {filename: content} to create test files
        """
        if files:
            for filename, content in files.items():
                self.add_file(filename).write_text(content)

        validator_test = ValidatorTest(
            glob=glob,
            outcome=outcome,
            validator=CodeItem(path=pathlib.Path(validator)) if validator else None,
        )

        # Explicitly set the unitTests field to mark it as dirty
        unit_tests = self.yml.unitTests
        unit_tests.validator = unit_tests.validator + [validator_test]
        self.yml.unitTests = unit_tests
        self.save()

    def add_checker_unit_test(
        self,
        glob: str,
        outcome: ExpectedOutcome = ExpectedOutcome.ACCEPTED,
        files: Optional[Dict[str, str]] = None,
    ):
        """Add a unit test for the checker.

        Args:
            glob: Glob pattern for test files
            outcome: Expected checker outcome
            files: Optional dict of {filename: content} to create test files
        """
        if files:
            for filename, content in files.items():
                self.add_file(filename).write_text(content)

        checker_test = CheckerTest(glob=glob, outcome=outcome)

        # Explicitly set the unitTests field to mark it as dirty
        unit_tests = self.yml.unitTests
        unit_tests.checker = unit_tests.checker + [checker_test]
        self.yml.unitTests = unit_tests
        self.save()
