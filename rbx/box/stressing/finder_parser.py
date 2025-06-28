import dataclasses
import pathlib
import typing
from enum import Enum
from typing import Callable, List, Optional, Union

import lark
import typer

from rbx import console
from rbx.box import package
from rbx.box.schema import CodeItem, ExpectedOutcome
from rbx.box.solutions import expand_solutions
from rbx.grading.steps import CheckerResult, Outcome, RunLog, TestcaseLog

LARK_GRAMMAR = r"""
// A bunch of words
start: disjunction

disjunction: conjunction | disjunction _OR conjunction

conjunction: _atom | conjunction _AND _atom

_atom: logical | "(" disjunction ")" | negation
negation: _NOT "(" disjunction ")"

// Expressions
logical: eval matcher expected_outcome -> matching
       | eval equality (eval | outcome) -> equating
       | eval -> eval_only

eval: "[" solution checking? "]" | solution

// Eval
solution: _solution_filename | WILDCARD
checking: "ON"i (checking_mode? checker | ":nil")
checking_mode: MODE ":"
MODE: "2" | "3"
checker: _filename | WILDCARD

// Outcomes
expected_outcome: CNAME
outcome: CNAME

// Operators
matcher: MATCHES | NOT_MATCHES
equality: EQUALS | NOT_EQUALS

MATCHES: "~"
NOT_MATCHES: "!~"
EQUALS: "=="
NOT_EQUALS: "!="
_OR: "||"
_AND: "&&"
_NOT: "!"
WILDCARD: "$"

// File name
_filename: FILENAME | "\"" FILENAME "\""
_solution_filename: _filename | "@" _filename
FILENAME: /[\/A-Za-z0-9\-_\.]/+

// Names (Variables)
LCASE_LETTER: "a".."z"
UCASE_LETTER: "A".."Z"
DIGIT: "0".."9"
LETTER: UCASE_LETTER | LCASE_LETTER
WORD: LETTER+
CNAME: ("_"|LETTER) ("_"|LETTER|DIGIT|"+")*

%ignore " "
"""

LARK_PARSER = lark.Lark(LARK_GRAMMAR)


class CheckingMode(Enum):
    THREE_WAY = 0
    TWO_WAY = 1


@dataclasses.dataclass(frozen=True)
class FinderChecker:
    path: str
    mode: CheckingMode


@dataclasses.dataclass(frozen=True)
class FinderCall:
    solution: str
    checker: Optional[FinderChecker]


@dataclasses.dataclass(frozen=True)
class FinderSolutionResult:
    output_path: pathlib.Path
    stderr_path: Optional[pathlib.Path] = None
    run_log: Optional[RunLog] = None


@dataclasses.dataclass(frozen=True)
class FinderResult:
    solution: str
    outcome: Outcome
    checker: Optional[FinderChecker]

    # Auxiliary information.
    solution_log: Optional[TestcaseLog] = None
    checker_result: Optional[CheckerResult] = None


@dataclasses.dataclass(frozen=True)
class FinderOutcome:
    truth_value: bool
    results: List[FinderResult]


def or_outcome(a: FinderOutcome, b: FinderOutcome) -> FinderOutcome:
    return FinderOutcome(
        truth_value=a.truth_value or b.truth_value, results=a.results + b.results
    )


def and_outcome(a: FinderOutcome, b: FinderOutcome) -> FinderOutcome:
    return FinderOutcome(
        truth_value=a.truth_value and b.truth_value, results=a.results + b.results
    )


def get_checking_mode_from_string(mode: Optional[str]) -> CheckingMode:
    if not mode:
        return CheckingMode.THREE_WAY
    if mode == '2':
        return CheckingMode.TWO_WAY
    return CheckingMode.THREE_WAY


def _get_main_checker() -> Optional[str]:
    pkg = package.find_problem_package_or_die()
    if not pkg.checker:
        return None
    return str(pkg.checker.path)


def _get_main_solution() -> Optional[str]:
    sol = package.get_main_solution()
    if sol is None:
        return None
    return str(sol.path)


def _get_default_checker_for_finder() -> Optional[FinderChecker]:
    main_checker = _get_main_checker()
    if main_checker is None:
        return None
    return FinderChecker(path=main_checker, mode=CheckingMode.THREE_WAY)


def _get_solution_from_token(token: lark.Token) -> str:
    path = str(token)
    if path == '$':
        main_path = _get_main_solution()
        assert main_path is not None
        return main_path
    return path


def _get_checker_from_token(token: lark.Token) -> str:
    path = str(token)
    if path == '$':
        main_path = _get_main_checker()
        assert main_path is not None
        return main_path
    return path


def _get_eval_checker(eval: lark.ParseTree) -> Optional[FinderChecker]:
    checking_nodes = list(eval.find_data('checking'))
    if not checking_nodes:
        return _get_default_checker_for_finder()
    (checking,) = checking_nodes

    if not checking.children:
        # Checking is nil
        return None

    if len(checking.children) == 1:
        checker = typing.cast(lark.ParseTree, checking.children[0])
        return FinderChecker(
            path=_get_checker_from_token(typing.cast(lark.Token, checker.children[0])),
            mode=CheckingMode.THREE_WAY,
        )

    mode = typing.cast(lark.ParseTree, checking.children[0])
    checker = typing.cast(lark.ParseTree, checking.children[1])

    return FinderChecker(
        path=_get_checker_from_token(typing.cast(lark.Token, checker.children[0])),
        mode=get_checking_mode_from_string(
            typing.cast(lark.Token, mode.children[0]).value
        ),
    )


def get_all_solutions(tree: lark.ParseTree) -> List[str]:
    solution_nodes = tree.find_data('solution')
    res = set(
        [
            _get_solution_from_token(typing.cast(lark.Token, node.children[0]))
            for node in solution_nodes
        ]
    )

    if needs_expected_output(tree):
        main_solution = package.get_main_solution()
        assert main_solution is not None
        res.add(str(main_solution.path))
    return list(res)


def get_all_solution_items(tree: lark.ParseTree) -> List[CodeItem]:
    solution_names = get_all_solutions(tree)
    res = typing.cast(List[CodeItem], expand_solutions(solution_names))

    main_solution = package.get_main_solution()
    if main_solution is None:
        return res

    for i, sol in enumerate(res):
        if main_solution.path == sol.path:
            res[i], res[0] = res[0], res[i]
    return res


def _get_all_finder_checkers(tree: lark.ParseTree) -> List[FinderChecker]:
    eval_nodes = tree.find_data('eval')
    res = []

    for eval_node in eval_nodes:
        finder_checker = _get_eval_checker(eval_node)
        if finder_checker is not None:
            res.append(finder_checker)

    return res


def get_all_checkers(tree: lark.ParseTree) -> List[str]:
    return [finder_checker.path for finder_checker in _get_all_finder_checkers(tree)]


def get_all_checker_items(tree: lark.ParseTree) -> List[CodeItem]:
    checker_names = get_all_checkers(tree)
    res = []

    for checker_name in checker_names:
        main_checker = package.get_checker()
        if str(main_checker.path) == checker_name:
            res.append(main_checker)
            continue
        res.append(
            CodeItem(
                path=pathlib.Path(checker_name),
                language=None,
                compilationFiles=None,
            )
        )
    return res


def needs_expected_output(tree: lark.ParseTree) -> bool:
    finder_checkers = _get_all_finder_checkers(tree)
    for finder_checker in finder_checkers:
        if finder_checker.mode == CheckingMode.THREE_WAY:
            return True
    return False


def validate(tree: lark.ParseTree):
    if needs_expected_output(tree):
        if package.get_main_solution() is None:
            console.console.print(
                '[error]Finder expression requires three-way checking, but problem has no main solution.[/error]'
            )
            console.console.print(
                'Either provide an ACCEPTED solution at your problem.rbx.yml, or use two-way checking in your finder expression by providing the `2:` parameter before the checker name.'
            )
            raise typer.Exit(1)

    all_checkers = get_all_checkers(tree)
    for checker in all_checkers:
        if not pathlib.Path(checker).is_file():
            console.console.print(
                f'[error]Finder expression references non-existing checker [item]{checker}[/item][/error]'
            )
            raise typer.Exit(1)

    all_solutions = get_all_solutions(tree)
    for solution in all_solutions:
        if not pathlib.Path(solution).is_file():
            console.console.print(
                f'[error]Finder expression references non-existing solution [item]{solution}[/item][/error]'
            )
            raise typer.Exit(1)


@lark.v_args(inline=True)
class FinderTreeRunner(lark.Transformer):
    def __init__(
        self,
        runner: Callable[[FinderCall], FinderResult],
    ):
        self.run_fn = runner

    def solution(self, token: lark.Token) -> str:
        return _get_solution_from_token(token)

    def outcome(self, token: lark.Token) -> Outcome:
        try:
            outcome = Outcome(token.value)
        except ValueError:
            try:
                expected_outcome = self.expected_outcome(token)
            except ValueError:
                raise ValueError(f'"{token.value}" is not a valid Outcome.') from None
            outcomes = expected_outcome.get_matches()
            if len(outcomes) != 1:
                raise ValueError(
                    f'"{token.value}" is not a valid Outcome. You are trying to specify an ExpectedOutcome, instead of a single Outcome.'
                ) from None
            return outcomes[0]
        return outcome

    def expected_outcome(self, token: lark.Token) -> ExpectedOutcome:
        return ExpectedOutcome(token.value)

    def matcher(self, op: lark.Token) -> bool:
        return op.value == '~'

    def equality(self, op: lark.Token) -> bool:
        return op.value == '=='

    @lark.v_args(inline=False, tree=True)
    def eval(self, tree: lark.ParseTree) -> FinderResult:
        solution = typing.cast(str, tree.children[0])
        checker: Optional[FinderChecker] = _get_eval_checker(tree)

        call = FinderCall(solution, checker=checker)
        return self.run_fn(call)

    def matching(
        self,
        eval_result: FinderResult,
        is_positive: bool,
        expected_outcome: ExpectedOutcome,
    ) -> FinderOutcome:
        truth_value = expected_outcome.match(eval_result.outcome)
        if not is_positive:
            truth_value = not truth_value

        return FinderOutcome(truth_value=truth_value, results=[eval_result])

    def equating(
        self,
        eval_result: FinderResult,
        is_positive: bool,
        result_or_outcome: Union[FinderResult, Outcome],
    ) -> FinderOutcome:
        results = [eval_result]
        truth_value = True

        if isinstance(result_or_outcome, Outcome):
            outcome: Outcome = result_or_outcome
            truth_value = eval_result.outcome == outcome
        else:
            result: FinderResult = result_or_outcome
            truth_value = eval_result.outcome == result.outcome
            results.append(result)

        if not is_positive:
            truth_value = not truth_value

        return FinderOutcome(truth_value=truth_value, results=results)

    def eval_only(self, eval_result: FinderResult) -> FinderOutcome:
        return self.matching(
            eval_result, is_positive=True, expected_outcome=ExpectedOutcome.INCORRECT
        )

    def negation(self, value: FinderOutcome) -> FinderOutcome:
        return dataclasses.replace(value, truth_value=not value.truth_value)

    @lark.v_args(inline=False)
    def conjunction(self, values: List[FinderOutcome]) -> FinderOutcome:
        res = FinderOutcome(truth_value=True, results=[])
        for value in values:
            res = and_outcome(res, value)
        return res

    @lark.v_args(inline=False)
    def disjunction(self, values: List[FinderOutcome]) -> FinderOutcome:
        res = FinderOutcome(truth_value=False, results=[])
        for value in values:
            res = or_outcome(res, value)
        return res

    def start(self, value: FinderOutcome) -> FinderOutcome:
        return value


def parse(expression: str) -> lark.ParseTree:
    tree = LARK_PARSER.parse(expression)
    validate(tree)
    return tree
