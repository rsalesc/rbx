import pathlib
from typing import List

from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.schema import Testcase
from rbx.box.testcase_schema import TestcaseEntry


def build_entries(
    tmp_path: pathlib.Path, groups: List[str]
) -> List[GenerationTestcaseEntry]:
    """One built test per item of `groups`, in order, in that group."""
    entries = []
    for group in groups:
        index = sum(entry.group_entry.group == group for entry in entries)
        path = tmp_path / group / f'{index}.in'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('1\n')
        entries.append(
            GenerationTestcaseEntry(
                group_entry=TestcaseEntry(group=group, index=index),
                subgroup_entry=TestcaseEntry(group=group, index=index),
                metadata=GenerationMetadata(copied_to=Testcase(inputPath=path)),
            )
        )
    return entries
