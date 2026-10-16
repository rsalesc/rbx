"""Naming tests on the command line: ``[group]/[index]`` or ``[script]:[line]``."""

import pathlib
from typing import List, Tuple

from rbx import utils
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.testcase_extractors import (
    extract_generation_testcases_from_groups,
    extract_generation_testcases_from_patterns,
)
from rbx.box.testcase_utils import TestcasePattern


class SelectorError(Exception):
    """A selector that names nothing; the message says so, for the setter."""


def is_script_selector(selector: str) -> bool:
    return ':' in selector


def parse_script_selector(selector: str) -> Tuple[pathlib.Path, int]:
    path, _, line = selector.rpartition(':')
    if not path or not line.isdigit() or int(line) < 1:
        raise SelectorError(
            f'Invalid test selector [item]{selector}[/item]: expected '
            '[group]/[index] or [script]:[line].'
        )
    return utils.abspath(pathlib.Path(path)), int(line)


async def entries_for_selectors(
    selectors: List[str],
) -> List[GenerationTestcaseEntry]:
    """Resolve ``[group]/[index]`` patterns and ``[script]:[line]`` selectors.

    A ``[script]:[line]`` selector names the test whose statement starts at that
    line of a generator script, so an editor can address a test by where it is
    written, before the testset is ever built. Each script selector must match a
    test. Pattern matches come first, then script matches, each test once.

    A statement of a script shared by several groups (a problem-level
    ``generatorScript``, or one plan imported twice) makes a test in each of
    them. Its selector still names one statement, so it resolves to the first
    of those tests, in testset order: promoting it writes one file, not a copy
    per group.
    """
    patterns = [
        TestcasePattern.parse(s) for s in selectors if not is_script_selector(s)
    ]
    script_selectors = {
        s: parse_script_selector(s) for s in selectors if is_script_selector(s)
    }
    wanted = set(script_selectors.values())

    entries: List[GenerationTestcaseEntry] = []
    if patterns:
        entries.extend(await extract_generation_testcases_from_patterns(patterns))
    if wanted:
        seen = {entry.group_entry.key() for entry in entries}
        found = set()
        for entry in await extract_generation_testcases_from_groups():
            gse = entry.metadata.generator_script
            if gse is None:
                continue
            key = (utils.abspath(gse.path), gse.line)
            if key not in wanted or key in found:
                continue
            found.add(key)
            if entry.group_entry.key() not in seen:
                seen.add(entry.group_entry.key())
                entries.append(entry)
        for selector, key in script_selectors.items():
            if key not in found:
                raise SelectorError(
                    f'No test starts at [item]{selector}[/item]: it must be the '
                    'first line of a statement in a generator script of this '
                    'problem, outside any @testgroup naming a group it lacks.'
                )
    return entries
