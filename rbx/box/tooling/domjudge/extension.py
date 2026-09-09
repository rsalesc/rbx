"""What `env.rbx.yml` says about a DOMjudge instance.

Two models, mirroring the split every other backend uses: an environment-level
one for what is true of the whole server, and a language-level one for what is
true of one language.

Both are deliberately thin. DOMjudge's language and limit settings are
**instance-global** -- there is no contest-scoped equivalent for any of them --
so every field here reconfigures a server other people may share. That is why
nothing here defaults to a value: an unset field means "leave whatever the
server has", never "push rbx's local default".
"""

import typing

from pydantic import ConfigDict, Field

from rbx.utils import RejectsRemovedFields


class DomjudgeExtension(RejectsRemovedFields):
    """Environment-level extensions for DOMjudge tooling.

    The four limits DOMjudge keeps in its own configuration that rbx has an
    opinion about. Spelled in rbx's units and converted on the way out.
    """

    model_config = ConfigDict(extra='forbid')

    memoryLimit: typing.Optional[int] = Field(
        default=None,
        gt=0,
        description='Default memory limit (in MiB) for submissions on the server, '
        "written to DOMjudge's `memory_limit`. A problem package carries its own "
        'memory limit, so this is only the fallback for problems that do not. '
        'Leave unset to keep whatever the server has.',
    )
    outputLimit: typing.Optional[int] = Field(
        default=None,
        gt=0,
        description="Default output limit (in KiB), written to DOMjudge's "
        '`output_limit`. Leave unset to keep whatever the server has.',
    )
    processLimit: typing.Optional[int] = Field(
        default=None,
        gt=0,
        description='Maximum number of processes a submission may run, written to '
        "DOMjudge's `process_limit`. Leave unset to keep whatever the server has.",
    )
    sourceSizeLimit: typing.Optional[int] = Field(
        default=None,
        gt=0,
        description='Maximum size (in KiB) of a submitted source file, written to '
        "DOMjudge's `sourcesize_limit`. Leave unset to keep whatever the server has.",
    )


class DomjudgeLanguageExtension(RejectsRemovedFields):
    """Language-level extensions for DOMjudge tooling."""

    model_config = ConfigDict(extra='forbid')

    languages: typing.Optional[typing.List[str]] = Field(
        default=None,
        description='DOMjudge language ids this rbx language maps to. Leave unset to '
        "let rbx match by file extension against the server's own language list. "
        'Set it when the match is wrong, or when the language is currently disabled '
        'on the server -- a disabled language is invisible to the API. DOMjudge '
        "matches these against a language's `externalid`, which is not always the id "
        'shown in the admin UI (`py3` is externalid `python3`, `pas` is `pascal`).',
    )
    timeFactor: typing.Optional[float] = Field(
        default=None,
        gt=0,
        description="Multiplier DOMjudge applies to every problem's time limit for "
        'this language (`time_factor`). Leave unset to keep the factor the server '
        'has. rbx has no environment setting that means the same thing, so this is '
        'never derived: `timing.wallTimeMultiplier` is about wall versus CPU time, '
        "and a timing group's `whenEmpty.multiplier` only estimates a limit for a "
        'group that has no solutions.',
    )
    compile: bool = Field(
        default=True,
        description="Whether to push this language's compile script to the server, "
        "built from `compileCommand` or from the language's own "
        '`compilation.commands`. Set to false to enable the language but leave the '
        "server's compile script alone.",
    )
    compileCommand: typing.Optional[str] = Field(
        default=None,
        description='Compilation command to send to DOMjudge instead of the '
        "language's `compilation.commands`. Same placeholders (`{compilable}`, "
        '`{executable}`). Useful when the judge needs flags the local environment '
        'does not want, `-static` being the usual one.',
    )
