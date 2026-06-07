import enum
from typing import Set


class LanguageKind(enum.Enum):
    """A coarse language family a command or language belongs to.

    A single command/language can have more than one kind: a C++ command is both
    ``CXX`` and ``CPP``; a C command is both ``CXX`` and ``C``; Java and Kotlin are
    both ``JVM`` plus their specific kind. ``CXX`` and ``JVM`` are the umbrella kinds.
    """

    CXX = 'cxx'
    CPP = 'cpp'
    C = 'c'
    JVM = 'jvm'
    JAVA = 'java'
    KOTLIN = 'kotlin'
    PYTHON = 'python'


def command_kinds(exe_command: str) -> Set[LanguageKind]:
    """The set of language kinds a command (or its bare executable) belongs to.

    Detection is purely substring-based on the command's executable, mirroring the
    historical ``is_*_command`` predicates this replaces. ``g++``/``clang++`` imply
    ``{CPP, CXX}``; ``gcc``/``clang`` imply ``{C, CXX}``; ``javac``/``java`` imply
    ``{JAVA, JVM}``; ``kotlinc``/``kotlin`` imply ``{KOTLIN, JVM}``;
    ``python``/``pypy`` imply ``{PYTHON}``.
    """
    kinds: Set[LanguageKind] = set()
    if 'g++' in exe_command or 'clang++' in exe_command:
        kinds |= {LanguageKind.CPP, LanguageKind.CXX}
    if 'gcc' in exe_command or 'clang' in exe_command:
        kinds |= {LanguageKind.C, LanguageKind.CXX}
    if 'javac' in exe_command or 'java' in exe_command:
        kinds |= {LanguageKind.JAVA, LanguageKind.JVM}
    if 'kotlinc' in exe_command or 'kotlin' in exe_command:
        kinds |= {LanguageKind.KOTLIN, LanguageKind.JVM}
    if 'python' in exe_command or 'pypy' in exe_command:
        kinds |= {LanguageKind.PYTHON}
    return kinds
