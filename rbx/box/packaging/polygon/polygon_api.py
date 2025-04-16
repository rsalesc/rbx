"""
https://github.com/citxx/polygon-py

Manually copied because can't add direct dependency with Poetry.
"""
# flake8: noqa

import hashlib
import json
import random
import string
import time
from enum import Enum

import requests


class Polygon:
    """ """

    # API methods
    _CONTEST_PROBLEMS = 'contest.problems'
    _PROBLEM_INFO = 'problem.info'
    _PROBLEM_UPDATE_INFO = 'problem.updateInfo'
    _PROBLEM_UPDATE_WORKING_COPY = 'problem.updateWorkingCopy'
    _PROBLEM_COMMIT_CHANGES = 'problem.commitChanges'
    _PROBLEM_STATEMENTS = 'problem.statements'
    _PROBLEM_SAVE_STATEMENT = 'problem.saveStatement'
    _PROBLEM_STATEMENT_RESOURCES = 'problem.statementResources'
    _PROBLEM_SAVE_STATEMENT_RESOURCE = 'problem.saveStatementResource'
    _PROBLEMS_LIST = 'problems.list'
    _PROBLEM_CREATE = 'problem.create'
    _PROBLEM_CHECKER = 'problem.checker'
    _PROBLEM_VALIDATOR = 'problem.validator'
    _PROBLEM_INTERACTOR = 'problem.interactor'
    _PROBLEM_FILES = 'problem.files'
    _PROBLEM_SOLUTIONS = 'problem.solutions'
    _PROBLEM_VIEW_FILE = 'problem.viewFile'
    _PROBLEM_VIEW_SOLUTION = 'problem.viewSolution'
    _PROBLEM_SCRIPT = 'problem.script'
    _PROBLEM_TESTS = 'problem.tests'
    _PROBLEM_TEST_INPUT = 'problem.testInput'
    _PROBLEM_TEST_ANSWER = 'problem.testAnswer'
    _PROBLEM_SET_VALIDATOR = 'problem.setValidator'
    _PROBLEM_SET_CHECKER = 'problem.setChecker'
    _PROBLEM_SET_INTERACTOR = 'problem.setInteractor'
    _PROBLEM_SAVE_FILE = 'problem.saveFile'
    _PROBLEM_SAVE_SOLUTION = 'problem.saveSolution'
    _PROBLEM_EDIT_SOLUTION_EXTRA_TAGS = 'problem.editSolutionExtraTags'
    _PROBLEM_SAVE_SCRIPT = 'problem.saveScript'
    _PROBLEM_SAVE_TEST = 'problem.saveTest'
    _PROBLEM_ENABLE_GROUPS = 'problem.enableGroups'
    _PROBLEM_ENABLE_POINTS = 'problem.enablePoints'
    _PROBLEM_VIEW_TEST_GROUP = 'problem.viewTestGroup'
    _PROBLEM_SAVE_TEST_GROUP = 'problem.saveTestGroup'
    _PROBLEM_VIEW_TAGS = 'problem.viewTags'
    _PROBLEM_SAVE_TAGS = 'problem.saveTags'
    _PROBLEM_VIEW_GENERAL_DESCRIPTION = 'problem.viewGeneralDescription'
    _PROBLEM_SAVE_GENERAL_DESCRIPTION = 'problem.saveGeneralDescription'
    _PROBLEM_VIEW_GENERAL_TUTORIAL = 'problem.viewGeneralTutorial'
    _PROBLEM_SAVE_GENERAL_TUTORIAL = 'problem.saveGeneralTutorial'

    def __init__(self, api_url, api_key, api_secret):
        self.request_config = RequestConfig(api_url, api_key, api_secret)

    def problems_list(self, show_deleted=None, id=None, name=None, owner=None):
        """ """
        response = self._request_ok_or_raise(
            self._PROBLEMS_LIST,
            args={
                'showDeleted': show_deleted,
                'id': id,
                'name': name,
                'owner': owner,
            },
        )
        return [Problem.from_json(self, p_json) for p_json in response.result]

    def problem_create(self, name):
        """ """
        response = self._request_ok_or_raise(
            self._PROBLEM_CREATE,
            args={
                'name': name,
            },
        )
        return Problem.from_json(self, response.result)

    def problem_info(self, problem_id):
        """ """
        response = self._request_ok_or_raise(
            self._PROBLEM_INFO,
            args={'problemId': problem_id},
        )
        return ProblemInfo.from_json(response.result)

    def problem_update_info(self, problem_id, problem_info):
        """ """
        response = self._request_ok_or_raise(
            self._PROBLEM_UPDATE_INFO,
            args={
                'problemId': problem_id,
                'inputFile': problem_info.input_file,
                'outputFile': problem_info.output_file,
                'interactive': problem_info.interactive,  # TODO
                'timeLimit': problem_info.time_limit,
                'memoryLimit': problem_info.memory_limit,
            },
        )
        return response.result

    def problem_update_working_copy(self, problem_id):
        """ """
        response = self._request_ok_or_raise(
            self._PROBLEM_UPDATE_WORKING_COPY,
            args={'problemId': problem_id},
        )
        return response.result

    def problem_commit_changes(self, problem_id, minor_changes=None, message=None):
        """ """
        response = self._request_ok_or_raise(
            self._PROBLEM_COMMIT_CHANGES,
            args={
                'problemId': problem_id,
                'minorChanges': minor_changes,
                'message': message,
            },
        )
        return response.result

    def problem_view_tags(self, problem_id):
        """ """
        response = self._request_ok_or_raise(
            self._PROBLEM_VIEW_TAGS,
            args={'problemId': problem_id},
        )
        return response.result

    def problem_save_tags(self, problem_id, tags):
        """ """
        tags_str = ','.join(tags)
        response = self._request_ok_or_raise(
            self._PROBLEM_SAVE_TAGS,
            args={
                'problemId': problem_id,
                'tags': tags_str,
            },
        )
        return response.result

    def problem_view_general_description(self, problem_id):
        """ """
        response = self._request_ok_or_raise(
            self._PROBLEM_VIEW_GENERAL_DESCRIPTION,
            args={'problemId': problem_id},
        )
        return response.result

    def problem_save_general_description(self, problem_id, description):
        """ """
        response = self._request_ok_or_raise(
            self._PROBLEM_SAVE_GENERAL_DESCRIPTION,
            args={
                'problemId': problem_id,
                'description': description,
            },
        )
        return response.result

    def problem_view_general_tutorial(self, problem_id):
        """ """
        response = self._request_ok_or_raise(
            self._PROBLEM_VIEW_GENERAL_TUTORIAL,
            args={'problemId': problem_id},
        )
        return response.result

    def problem_save_general_tutorial(self, problem_id, tutorial):
        """ """
        response = self._request_ok_or_raise(
            self._PROBLEM_SAVE_GENERAL_TUTORIAL,
            args={
                'problemId': problem_id,
                'tutorial': tutorial,
            },
        )
        return response.result

    def problem_statements(self, problem_id):
        """ """
        response = self._request_ok_or_raise(
            self._PROBLEM_STATEMENTS,
            args={
                'problemId': problem_id,
            },
        )
        return {
            lang: Statement.from_json(statement_json)
            for lang, statement_json in response.result.items()
        }

    def problem_save_statement(self, problem_id, lang, problem_statement):
        """ """
        if not isinstance(problem_statement, Statement):
            raise ValueError(
                'Expected Statement instance for problem_statement argument, but %s found'
                % type(problem_statement)
            )
        response = self._request_ok_or_raise(
            self._PROBLEM_SAVE_STATEMENT,
            args={
                'problemId': problem_id,
                'lang': lang,
                'encoding': problem_statement.encoding,
                'name': problem_statement.name,
                'legend': problem_statement.legend,
                'input': problem_statement.input,
                'output': problem_statement.output,
                'scoring': problem_statement.scoring,
                'interaction': problem_statement.interaction,
                'notes': problem_statement.notes,
                'tutorial': problem_statement.tutorial,
            },
        )
        return response.result

    def problem_statement_resources(self, problem_id):
        response = self._request_ok_or_raise(
            self._PROBLEM_STATEMENT_RESOURCES,
            args={
                'problemId': problem_id,
            },
        )
        return response.result

    def problem_save_statement_resource(
        self, problem_id, name, file, check_existing=None
    ):
        response = self._request_ok_or_raise(
            self._PROBLEM_SAVE_STATEMENT_RESOURCE,
            args={
                'problemId': problem_id,
                'name': name,
                'file': file,
                'checkExisting': check_existing,
            },
        )
        return response.result

    def problem_enable_groups(self, problem_id, testset, enable):
        """ """
        response = self._request_ok_or_raise(
            self._PROBLEM_ENABLE_GROUPS,
            args={
                'problemId': problem_id,
                'testset': testset,
                'enable': enable,
            },
        )
        return response.result

    def problem_enable_points(self, problem_id, enable):
        """ """
        response = self._request_ok_or_raise(
            self._PROBLEM_ENABLE_POINTS,
            args={
                'problemId': problem_id,
                'enable': enable,
            },
        )
        return response.result

    def problem_save_test(
        self,
        problem_id,
        testset,
        test_index,
        test_input,
        test_group=None,
        test_points=None,
        test_description=None,
        test_use_in_statements=None,
        test_input_for_statements=None,
        test_output_for_statements=None,
        verify_input_output_for_statements=None,
        check_existing=None,
    ):
        """ """
        response = self._request_ok_or_raise(
            self._PROBLEM_SAVE_TEST,
            args={
                'problemId': problem_id,
                'testset': testset,
                'testIndex': test_index,
                'testInput': test_input,
                'testGroup': test_group,
                'testPoints': test_points,
                'testDescription': test_description,
                'testUseInStatements': test_use_in_statements,
                'testInputForStatements': test_input_for_statements,
                'testOutputForStatements': test_output_for_statements,
                'verifyInputOutputForStatements': verify_input_output_for_statements,
                'checkExisting': check_existing,
            },
        )
        return response.result

    def problem_solutions(self, problem_id):
        response = self._request_ok_or_raise(
            self._PROBLEM_SOLUTIONS,
            args={
                'problemId': problem_id,
            },
        )
        return [Solution.from_json(js) for js in response.result]

    def problem_files(self, problem_id):
        response = self._request_ok_or_raise(
            self._PROBLEM_FILES,
            args={
                'problemId': problem_id,
            },
        )
        return {
            type: [File.from_json(js) for js in response.result[str(type) + 'Files']]
            for type in FileType
        }

    def problem_tests(self, problem_id, testset):
        response = self._request_ok_or_raise(
            self._PROBLEM_TESTS,
            args={
                'problemId': problem_id,
                'testset': testset,
            },
        )
        return [Test.from_json(self, problem_id, testset, js) for js in response.result]

    def problem_save_test_group(
        self,
        problem_id,
        testset,
        group,
        points_policy=None,
        feedback_policy=None,
        dependencies=None,
    ):
        if isinstance(dependencies, list):
            dependencies = ','.join(map(str, dependencies))
        elif dependencies is not None:
            dependencies = str(dependencies)
        if points_policy is not None and not isinstance(points_policy, PointsPolicy):
            raise ValueError(
                'Expected PointsPolicy instance for points_policy argument, but %s found'
                % type(points_policy)
            )
        if feedback_policy is not None and not isinstance(
            feedback_policy, FeedbackPolicy
        ):
            raise ValueError(
                'Expected FeedbackPolicy instance for feedback_policy argument, but %s found'
                % type(feedback_policy)
            )
        response = self._request_ok_or_raise(
            self._PROBLEM_SAVE_TEST_GROUP,
            args={
                'problemId': problem_id,
                'testset': testset,
                'group': group,
                'pointsPolicy': points_policy,
                'feedbackPolicy': feedback_policy,
                'dependencies': dependencies,
            },
        )
        return response.result

    def problem_view_test_group(self, testset, group):
        response = self._request_ok_or_raise(
            self._PROBLEM_VIEW_TEST_GROUP,
            args={
                'testset': testset,
                'group': group,
            },
        )
        return TestGroup.from_json(response.result)

    def problem_view_file(self, problem_id, type, name):
        response = self._request_raw(
            self._PROBLEM_VIEW_FILE,
            args={'problemId': problem_id, 'type': type, 'name': name},
        )
        return response

    def problem_save_file(
        self,
        problem_id,
        type,
        name,
        file,
        source_type=None,
        resource_advanced_properties=None,
    ):
        stages = (
            None
            if resource_advanced_properties is None
            or resource_advanced_properties.stages is None
            else ';'.join(map(str, resource_advanced_properties.stages))
        )
        assets = (
            None
            if resource_advanced_properties is None
            or resource_advanced_properties.assets is None
            else ';'.join(map(str, resource_advanced_properties.assets))
        )
        response = self._request_ok_or_raise(
            self._PROBLEM_SAVE_FILE,
            args={
                'problemId': problem_id,
                'type': type,
                'name': name,
                'file': file,
                'sourceType': source_type,
                'forTypes': None
                if resource_advanced_properties is None
                else resource_advanced_properties.for_types,
                'stages': stages,
                'assets': assets,
            },
        )
        return response.result

    def problem_save_solution(
        self, problem_id, name, file, source_type, tag, check_existing=None
    ):
        response = self._request_ok_or_raise(
            self._PROBLEM_SAVE_SOLUTION,
            args={
                'problemId': problem_id,
                'name': name,
                'file': file,
                'sourceType': source_type,
                'tag': tag,
                'checkExisting': check_existing,
            },
        )
        return response.result

    def problem_checker(self, problem_id):
        response = self._request_ok_or_raise(
            self._PROBLEM_CHECKER,
            args={
                'problemId': problem_id,
            },
        )
        return response.result

    def problem_set_checker(self, problem_id, checker):
        response = self._request_ok_or_raise(
            self._PROBLEM_SET_CHECKER,
            args={
                'problemId': problem_id,
                'checker': checker,
            },
        )
        return response.result

    def problem_validator(self, problem_id):
        response = self._request_ok_or_raise(
            self._PROBLEM_VALIDATOR,
            args={
                'problemId': problem_id,
            },
        )
        return response.result

    def problem_set_validator(self, problem_id, validator):
        response = self._request_ok_or_raise(
            self._PROBLEM_SET_VALIDATOR,
            args={
                'problemId': problem_id,
                'validator': validator,
            },
        )
        return response.result

    def problem_interactor(self, problem_id):
        response = self._request_ok_or_raise(
            self._PROBLEM_INTERACTOR,
            args={
                'problemId': problem_id,
            },
        )
        return response.result

    def problem_set_interactor(self, problem_id, interactor):
        response = self._request_ok_or_raise(
            self._PROBLEM_SET_INTERACTOR,
            args={
                'problemId': problem_id,
                'interactor': interactor,
            },
        )
        return response.result

    def contest_problems(self, contest_id):
        """ """
        response = self._request_ok_or_raise(
            self._CONTEST_PROBLEMS,
            args={'contestId': contest_id},
        )
        return {
            name: Problem.from_json(self, p_json)
            for name, p_json in response.result.items()
        }

    def _request_ok_or_raise(self, method_name, args=None):
        response = self._request(method_name, args=args)
        if response.status != Response.STATUS_OK:
            raise PolygonRequestFailedException(response.comment)
        return response

    def _request(self, method_name, args=None):
        request = Request(self.request_config, method_name, args)
        return request.issue()

    def _request_raw(self, method_name, args=None):
        request = Request(self.request_config, method_name, args)
        return request.issue_raw()


class Problem:
    """
    Object representing Polygon problem
    """

    # JSON field names
    _ID_FIELD = 'id'
    _OWNER_FIELD = 'owner'
    _NAME_FIELD = 'name'
    _DELETED_FIELD = 'deleted'
    _FAVORITE_FIELD = 'favourite'
    _ACCESS_TYPE_FIELD = 'accessType'
    _REVISION_FIELD = 'revision'
    _LATEST_PACKAGE_FIELD = 'latestPackage'
    _MODIFIED_FIELD = 'modified'

    @classmethod
    def from_json(cls, polygon, problem_json):
        return cls(
            polygon=polygon,
            problem_id=problem_json.get(Problem._ID_FIELD),
            owner=problem_json.get(Problem._OWNER_FIELD),
            name=problem_json.get(Problem._NAME_FIELD),
            deleted=problem_json.get(Problem._DELETED_FIELD),
            favorite=problem_json.get(Problem._FAVORITE_FIELD),
            access_type=problem_json.get(Problem._ACCESS_TYPE_FIELD),
            revision=problem_json.get(Problem._REVISION_FIELD),
            latest_package=problem_json.get(Problem._LATEST_PACKAGE_FIELD),
            modified=problem_json.get(Problem._MODIFIED_FIELD),
        )

    def __init__(
        self,
        polygon,
        problem_id,
        owner,
        name,
        deleted,
        favorite,
        access_type,
        revision,
        latest_package,
        modified,
    ):
        self._polygon = polygon

        self.id = problem_id
        self.owner = owner
        self.name = name
        self.deleted = deleted
        self.favorite = favorite
        self.access_type = access_type
        self.revision = revision
        self.latest_package = latest_package
        self.modified = modified

    def __str__(self):
        return '{}:{}'.format(self.name, self.id)

    def info(self):
        return self._polygon.problem_info(self.id)

    def update_info(self, problem_info):
        return self._polygon.problem_update_info(self.id, problem_info)

    def update_working_copy(self):
        return self._polygon.problem_update_working_copy(self.id)

    def commit_changes(self, minor_changes=None, message=None):
        return self._polygon.problem_commit_changes(self.id, minor_changes, message)

    def tags(self):
        return self._polygon.problem_view_tags(self.id)

    def save_tags(self, tags):
        return self._polygon.problem_save_tags(self.id, tags)

    def general_description(self):
        return self._polygon.problem_view_general_description(self.id)

    def save_general_description(self, description):
        return self._polygon.problem_save_general_description(self.id, description)

    def general_tutorial(self):
        return self._polygon.problem_view_general_tutorial(self.id)

    def save_general_tutorial(self, tutorial):
        return self._polygon.problem_save_general_tutorial(self.id, tutorial)

    def statements(self):
        return self._polygon.problem_statements(self.id)

    def save_statement(self, lang, problem_statement):
        return self._polygon.problem_save_statement(self.id, lang, problem_statement)

    def statement_resources(self):
        return self._polygon.problem_statement_resources(self.id)

    def save_statement_resource(self, name, file, check_existing=None):
        return self._polygon.problem_save_statement_resource(
            self.id, name, file, check_existing
        )

    def enable_groups(self, testset, enable):
        return self._polygon.problem_enable_groups(self.id, testset, enable)

    def enable_points(self, enable):
        return self._polygon.problem_enable_points(self.id, enable)

    def save_test(
        self,
        testset,
        test_index,
        test_input,
        test_group=None,
        test_points=None,
        test_description=None,
        test_use_in_statements=None,
        test_input_for_statements=None,
        test_output_for_statements=None,
        verify_input_output_for_statements=None,
        check_existing=None,
    ):
        return self._polygon.problem_save_test(
            self.id,
            testset,
            test_index,
            test_input,
            test_group,
            test_points,
            test_description,
            test_use_in_statements,
            test_input_for_statements,
            test_output_for_statements,
            verify_input_output_for_statements,
            check_existing,
        )

    def tests(self, testset):
        return self._polygon.problem_tests(self.id, testset)

    def save_test_group(
        self,
        testset,
        group,
        points_policy=None,
        feedback_policy=None,
        dependencies=None,
    ):
        return self._polygon.problem_save_test_group(
            self.id, testset, group, points_policy, feedback_policy, dependencies
        )

    def view_test_group(self, testset, group):
        return self._polygon.problem_view_test_group(testset, group)

    def view_file(self, type, name):
        return self._polygon.problem_view_file(self.id, type, name)

    def save_file(
        self, type, name, file, source_type=None, resource_advanced_properties=None
    ):
        return self._polygon.problem_save_file(
            self.id, type, name, file, source_type, resource_advanced_properties
        )

    def save_solution(self, name, file, source_type, tag, check_existing=None):
        return self._polygon.problem_save_solution(
            self.id, name, file, source_type, tag, check_existing
        )

    def checker(self):
        return self._polygon.problem_checker(self.id)

    def set_checker(self, checker):
        return self._polygon.problem_set_checker(self.id, checker)

    def validator(self):
        return self._polygon.problem_validator(self.id)

    def set_validator(self, validator):
        return self._polygon.problem_set_validator(self.id, validator)

    def interactor(self):
        return self._polygon.problem_interactor(self.id)

    def set_interactor(self, interactor):
        return self._polygon.problem_set_interactor(self.id, interactor)

    def solutions(self):
        return self._polygon.problem_solutions(self.id)

    def files(self):
        return self._polygon.problem_files(self.id)

    def files_resource(self):
        return self.files()[FileType.RESOURCE]

    def files_source(self):
        return self.files()[FileType.SOURCE]

    def files_aux(self):
        return self.files()[FileType.AUX]


class ProblemInfo:
    """
    Object representing Polygon problem info
    """

    # JSON field names
    _INPUT_FILE = 'inputFile'
    _OUTPUT_FILE = 'outputFile'
    _INTERACTIVE = 'interactive'
    _TIME_LIMIT = 'timeLimit'
    _MEMORY_LIMIT = 'memoryLimit'

    @classmethod
    def from_json(cls, problem_info_json):
        return cls(
            input_file=problem_info_json[ProblemInfo._INPUT_FILE],
            output_file=problem_info_json[ProblemInfo._OUTPUT_FILE],
            interactive=problem_info_json[ProblemInfo._INTERACTIVE],
            time_limit=problem_info_json[ProblemInfo._TIME_LIMIT],
            memory_limit=problem_info_json[ProblemInfo._MEMORY_LIMIT],
        )

    def __init__(
        self,
        input_file=None,
        output_file=None,
        interactive=None,
        time_limit=None,
        memory_limit=None,
    ):
        self.input_file = input_file
        self.output_file = output_file
        self.interactive = interactive
        self.time_limit = time_limit
        self.memory_limit = memory_limit


class Test:
    _INDEX = 'index'
    _MANUAL = 'manual'
    _INPUT = 'input'
    _DESCRIPTION = 'description'
    _USE_IN_STATEMENTS = 'useInStatements'
    _SCRIPT_LINE = 'scriptLine'
    _GROUP = 'group'
    _POINTS = 'points'
    _INPUT_FOR_STATEMENTS = 'inputForStatements'
    _OUTPUT_FOR_STATEMENTS = 'outputForStatements'
    _VERIFY_INPUT_OUTPUT_FOR_STATEMENTS = 'verifyInputOutputForStatements'

    @classmethod
    def from_json(cls, polygon, problem_id, testset, test_json):
        if test_json['manual']:
            return ManualTest.from_json(polygon, problem_id, testset, test_json)
        else:
            return GeneratedTest.from_json(polygon, problem_id, testset, test_json)

    def __init__(
        self,
        polygon,
        problem_id,
        testset,
        index,
        group,
        points,
        description,
        use_in_statements,
        input_for_statements,
        output_for_statements,
        verify_input_output_for_statements,
    ):
        self._polygon = polygon
        self._problem_id = problem_id
        self.testset = testset
        self.index = index
        self.group = group
        self.points = points
        self.description = description
        self.use_in_statements = use_in_statements
        self.input_for_statements = input_for_statements
        self.output_for_statements = output_for_statements
        self.verify_input_output_for_statements = verify_input_output_for_statements


class ManualTest(Test):
    @classmethod
    def from_json(cls, polygon, problem_id, testset, test_json):
        verify = test_json.get(Test._VERIFY_INPUT_OUTPUT_FOR_STATEMENTS, None)
        return cls(
            polygon=polygon,
            problem_id=problem_id,
            testset=testset,
            index=int(test_json[Test._INDEX]),
            input=test_json[Test._INPUT],
            group=test_json.get(Test._GROUP, ''),
            points=int(test_json.get(Test._POINTS, '0')),
            description=test_json.get(Test._DESCRIPTION, None),
            use_in_statements=test_json[Test._USE_IN_STATEMENTS],
            input_for_statements=test_json.get(Test._INPUT_FOR_STATEMENTS, None),
            output_for_statements=test_json.get(Test._OUTPUT_FOR_STATEMENTS, None),
            verify_input_output_for_statements=None
            if verify is None
            else (verify == 'true'),
        )

    def __init__(
        self,
        polygon,
        problem_id,
        testset,
        index,
        input,
        group=None,
        points=None,
        description=None,
        use_in_statements=None,
        input_for_statements=None,
        output_for_statements=None,
        verify_input_output_for_statements=None,
    ):
        super().__init__(
            polygon,
            problem_id,
            testset,
            index,
            group,
            points,
            description,
            use_in_statements,
            input_for_statements,
            output_for_statements,
            verify_input_output_for_statements,
        )
        self.input = input

    def save(self):
        return self._polygon.problem_save_test(
            self._problem_id,
            self.testset,
            self.index,
            self.input,
            self.group,
            self.points,
            self.description,
            self.use_in_statements,
            self.input_for_statements,
            self.output_for_statements,
            self.verify_input_output_for_statements,
        )


class GeneratedTest(Test):
    @classmethod
    def from_json(cls, polygon, problem_id, testset, test_json):
        verify = test_json.get(Test._VERIFY_INPUT_OUTPUT_FOR_STATEMENTS, None)
        return cls(
            polygon=polygon,
            problem_id=problem_id,
            testset=testset,
            index=int(test_json[Test._INDEX]),
            group=test_json.get(Test._GROUP, ''),
            points=int(test_json.get(Test._POINTS, '0')),
            description=test_json.get(Test._DESCRIPTION, None),
            use_in_statements=test_json[Test._USE_IN_STATEMENTS],
            script_line=test_json[Test._SCRIPT_LINE],
            input_for_statements=test_json.get(Test._INPUT_FOR_STATEMENTS, None),
            output_for_statements=test_json.get(Test._OUTPUT_FOR_STATEMENTS, None),
            verify_input_output_for_statements=None
            if verify is None
            else (verify == 'true'),
        )

    def __init__(
        self,
        polygon,
        problem_id,
        testset,
        index,
        group,
        points,
        description,
        use_in_statements,
        script_line,
        input_for_statements,
        output_for_statements,
        verify_input_output_for_statements,
    ):
        super().__init__(
            polygon,
            problem_id,
            testset,
            index,
            group,
            points,
            description,
            use_in_statements,
            input_for_statements,
            output_for_statements,
            verify_input_output_for_statements,
        )
        self.script_line = script_line


class TestGroup:
    """ """

    _NAME = 'name'
    _POINTS_POLICY = 'pointsPolicy'
    _FEEDBACK_POLICY = 'feedbackPolicy'
    _DEPENDENCIES = 'dependencies'

    @classmethod
    def from_json(cls, test_group_json):
        return cls(
            name=test_group_json[TestGroup._NAME],
            points_policy=PointsPolicy[test_group_json[TestGroup._POINTS_POLICY]],
            feedback_policy=FeedbackPolicy[test_group_json[TestGroup._FEEDBACK_POLICY]],
            dependencies=test_group_json[TestGroup._DEPENDENCIES],
        )

    def __init__(
        self, name, points_policy=None, feedback_policy=None, dependencies=None
    ):
        self.name = name
        if points_policy is not None and not isinstance(points_policy, PointsPolicy):
            raise TypeError(
                'Expected PointsPolicy instance for points_policy argument, but %s found'
                % type(points_policy)
            )
        if feedback_policy is not None and not isinstance(
            feedback_policy, FeedbackPolicy
        ):
            raise TypeError(
                'Expected FeedbackPolicy instance for feedback_policy argument, but %s found'
                % type(feedback_policy)
            )
        self.points_policy = points_policy
        self.feedback_policy = feedback_policy
        self.dependencies = dependencies


class Statement:
    """
    Object: representing Polygon problem statement
    """

    _ENCODING = 'encoding'
    _NAME = 'name'
    _LEGEND = 'legend'
    _INPUT = 'input'
    _OUTPUT = 'output'
    _SCORING = 'scoring'
    _INTERACTION = 'interaction'
    _NOTES = 'notes'
    _TUTORIAL = 'tutorial'

    @classmethod
    def from_json(cls, statement_json):
        return cls(
            encoding=statement_json[Statement._ENCODING],
            name=statement_json[Statement._NAME],
            legend=statement_json[Statement._LEGEND],
            input=statement_json[Statement._INPUT],
            output=statement_json[Statement._OUTPUT],
            scoring=statement_json.get(Statement._SCORING, None),
            interaction=statement_json.get(Statement._INTERACTION, None),
            notes=statement_json[Statement._NOTES],
            tutorial=statement_json[Statement._TUTORIAL],
        )

    def __init__(
        self,
        encoding=None,
        name=None,
        legend=None,
        input=None,
        output=None,
        scoring=None,
        interaction=None,
        notes=None,
        tutorial=None,
    ):
        self.encoding = encoding
        self.name = name
        self.legend = legend
        self.input = input
        self.output = output
        self.scoring = scoring
        self.interaction = interaction
        self.notes = notes
        self.tutorial = tutorial


class Solution:
    """
    Object: representing Polygon problem solution
    """

    _NAME = 'name'
    _MODIFICATION_TIME_SECONDS = 'modificationTimeSeconds'
    _LENGTH = 'length'
    _SOURCE_TYPE = 'sourceType'
    _TAG = 'tag'

    @classmethod
    def from_json(cls, solution_json):
        return cls(
            name=solution_json[Solution._NAME],
            modification_time_seconds=solution_json[
                Solution._MODIFICATION_TIME_SECONDS
            ],
            length=solution_json[Solution._LENGTH],
            source_type=solution_json[Solution._SOURCE_TYPE],
            tag=SolutionTag[solution_json[Solution._TAG]],
        )

    def __init__(self, name, modification_time_seconds, length, source_type, tag):
        self.name = name
        self.modification_time_seconds = modification_time_seconds
        self.length = length
        self.source_type = source_type
        self.tag = tag


class File:
    """
    Object: representing Polygon file (resource, source, or aux, not solutions)
    """

    _NAME = 'name'
    _MODIFICATION_TIME_SECONDS = 'modificationTimeSeconds'
    _LENGTH = 'length'
    _SOURCE_TYPE = 'sourceType'
    _RESOURCE_ADVANCED_PROPERTIES = 'resourceAdvancedProperties'

    @classmethod
    def from_json(cls, file_json):
        return cls(
            name=file_json[File._NAME],
            modification_time_seconds=file_json[File._MODIFICATION_TIME_SECONDS],
            length=file_json[File._LENGTH],
            source_type=file_json.get(File._SOURCE_TYPE, None),
            resource_advanced_properties=ResourceAdvancedProperties.from_json(
                file_json[File._RESOURCE_ADVANCED_PROPERTIES]
            )
            if File._RESOURCE_ADVANCED_PROPERTIES in file_json.keys()
            else None,
        )

    def __init__(
        self,
        name,
        modification_time_seconds,
        length,
        source_type,
        resource_advanced_properties,
    ):
        self.name = name
        self.modification_time_seconds = modification_time_seconds
        self.length = length
        self.source_type = source_type
        self.resource_advanced_properties = resource_advanced_properties


class ResourceAdvancedProperties:
    """ """

    _FOR_TYPES = 'forTypes'
    _MAIN = 'main'
    _STAGES = 'stages'
    _ASSETS = 'assets'

    @classmethod
    def from_json(cls, resource_advanced_properties):
        return cls(
            for_types=resource_advanced_properties[
                ResourceAdvancedProperties._FOR_TYPES
            ],
            main=resource_advanced_properties[ResourceAdvancedProperties._MAIN],
            stages=[
                Stage[stage]
                for stage in resource_advanced_properties[
                    ResourceAdvancedProperties._STAGES
                ]
            ],
            assets=[
                Asset[asset]
                for asset in resource_advanced_properties[
                    ResourceAdvancedProperties._ASSETS
                ]
            ],
        )

    def __init__(self, for_types=None, main=None, stages=None, assets=None):
        self.for_types = for_types
        self.main = main
        self.stages = stages
        self.assets = assets


ResourceAdvancedProperties.DELETE = ResourceAdvancedProperties(for_types='')


class Request:
    """
    Request to Polygon API.
    TODO: update
    Usage example:
    >>> request = Request(Request.CONTEST_PROBLEMS,
    ...                   args={'contestId': contest_id})
    >>> response = request.issue()
    >>> problems = response["result"]
    """

    @staticmethod
    def _encoded_args(args):
        return [
            (Request._value_to_utf8_bytes(key), Request._value_to_utf8_bytes(value))
            for key, value in args
        ]

    @staticmethod
    def _value_to_utf8_bytes(value):
        if isinstance(value, bytes):
            return value
        if isinstance(value, bytearray):
            return bytes(value)
        return str(value).encode('utf-8')

    def __init__(self, config, method_name, args=None):
        if args is None:
            args = {}
        args = {key: value for key, value in args.items() if value is not None}
        for key in args:
            if isinstance(args[key], bool):
                args[key] = 'true' if args[key] else 'false'
        self.args = []
        for key, value in args.items():
            if isinstance(value, list):
                for it in value:
                    self.args.append((key, it))
            else:
                self.args.append((key, value))
        self.config = config
        self.method_name = method_name

    def issue(self):
        """Issues request and returns parsed JSON response"""

        return Response(json.loads(self.issue_raw()))

    def issue_raw(self):
        """Issues request and returns raw response (useful e.g. for files)"""

        args = list(self.args)
        args.append(('apiKey', self.config.api_key))
        args.append(('time', str(int(time.time()))))
        args = Request._encoded_args(args)
        args.append(
            (
                b'apiSig',
                self.get_api_signature(
                    args, Request._value_to_utf8_bytes(self.config.api_secret)
                ),
            )
        )
        response = requests.post(self.config.api_url + self.method_name, files=args)
        return response.text

    def get_api_signature(self, args, api_secret):
        rand_bit = Request._value_to_utf8_bytes(
            ''.join(
                random.choice(string.ascii_lowercase + string.digits) for _ in range(6)
            )
        )

        arg_tuples = list(sorted(args))
        args_bit = b'&'.join(key + b'=' + value for key, value in arg_tuples)
        api_signature_string = (
            rand_bit
            + b'/'
            + self.method_name.encode('utf-8')
            + b'?'
            + args_bit
            + b'#'
            + api_secret
        )
        api_signature = rand_bit + Request._value_to_utf8_bytes(
            hashlib.sha512(api_signature_string).hexdigest()
        )
        return api_signature


class Response:
    """ """

    # JSON field names
    FIELD_STATUS = 'status'
    FIELD_COMMENT = 'comment'
    FIELD_RESULT = 'result'

    # Status values
    STATUS_OK = 'OK'
    STATUS_FAILED = 'FAILED'
    STATUS_UNKNOWN = 'UNKNOWN'

    def __init__(self, response_json):
        self.status = response_json.get(Response.FIELD_STATUS)
        if self.status not in [Response.STATUS_OK, Response.STATUS_FAILED]:
            self.status = Response.STATUS_UNKNOWN

        self.comment = response_json.get(Response.FIELD_COMMENT, '')
        self.result = response_json.get(Response.FIELD_RESULT)


class RequestConfig:
    def __init__(self, api_url, api_key, api_secret):
        if not api_url.endswith('/'):
            api_url += '/'
        self.api_url = api_url
        self.api_key = api_key
        self.api_secret = api_secret


class PolygonRequestFailedException(Exception):
    """Exception raised when Polygon returns FAILED as request status"""

    def __init__(self, comment):
        self.comment = comment


class PointsPolicy(Enum):
    COMPLETE_GROUP = 0
    EACH_TEST = 1

    def __str__(self):
        return self.name


class FeedbackPolicy(Enum):
    NONE = 0
    POINTS = 1
    ICPC = 2
    COMPLETE = 3

    def __str__(self):
        return self.name


class FileType(Enum):
    RESOURCE = 0
    SOURCE = 1
    AUX = 2

    def __str__(self):
        return self.name.lower()


class SolutionTag(Enum):
    MA = 0  # Main correct solution
    OK = 1  # Accepted
    RJ = 2  # Rejected, Incorrect
    TL = 3  # Time limit exceeded
    TO = 4  # Time limit exceeded or accepted
    WA = 5  # Wrong answer
    PE = 6  # Presentation error
    ML = 7  # Memory limit exceeded
    RE = 8  # Runtime error
    TM = 9  # Time limit exceeded or memory limit exceeded
    NR = 10  # Do not run

    def __str__(self):
        return self.name


class Asset(Enum):
    VALIDATOR = 0
    INTERACTOR = 1
    CHECKER = 2
    SOLUTION = 3

    def __str__(self):
        return self.name


class Stage(Enum):
    COMPILE = 0
    RUN = 1

    def __str__(self):
        return self.name
