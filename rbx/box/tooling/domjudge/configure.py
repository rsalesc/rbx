"""Applying a `Plan` to a DOMjudge instance, and saying what happened.

The order is fixed and matters: languages first, then compile scripts, then
configuration. A compile script can only be pushed to a language DOMjudge can
find, and a language rbx just enabled is the one whose script it is about to
replace.

Every write here is instance-wide. Nothing in DOMjudge's API scopes a language
or a limit to a contest, so this reconfigures the whole server for everyone on
it -- which is why the summary names the server it is pointed at before the
changes rather than after.
"""

from typing import Any, Dict, List

from rich.table import Table

from rbx import console
from rbx.box.runners.domjudge.api import DomjudgeApi
from rbx.box.tooling.domjudge.plan import WRAPPER_REASON, Plan, config_payload


def print_plan(api: DomjudgeApi, plan: Plan) -> None:
    console.console.print(
        f'Configuring DOMjudge at [item]{api.server}[/item]. '
        'Languages and limits are [warning]instance-wide[/warning] on DOMjudge: '
        'this affects every contest on that server.'
    )
    console.console.print()

    if plan.languages:
        table = Table(title='Languages', title_justify='left')
        table.add_column('rbx')
        table.add_column('DOMjudge')
        table.add_column('Matched by')
        table.add_column('Extensions')
        table.add_column('Time factor')
        table.add_column('Compile script')
        for language in plan.languages:
            if language.compile_script is not None:
                compile_cell = (
                    f'[success]push[/success] {language.compile_script.command}'
                )
            else:
                compile_cell = f'[info]keep — {language.compile_skipped}[/info]'
            if language.added_extensions:
                extensions = '[success]+{}[/success] {}'.format(
                    ', '.join(language.added_extensions),
                    ', '.join(language.all_extensions),
                )
            elif not language.known:
                extensions = '[info]unknown, left alone[/info]'
            else:
                extensions = '[info]unchanged[/info]'
            table.add_row(
                language.name,
                language.language_id,
                'name' if language.explicit else 'extension',
                extensions,
                'unchanged'
                if language.time_factor is None
                else str(language.time_factor),
                compile_cell,
            )
        console.console.print(table)

    # Said once, under the table, rather than in every row it applies to: it is
    # the same sentence for three languages in a typical environment, and the
    # two languages actually being changed are what the table is for.
    if any(language.compile_skipped == WRAPPER_REASON for language in plan.languages):
        console.console.print(
            '[info]DOMjudge execs whatever the compile script leaves at '
            '`$DEST`, so a language rbx runs through an interpreter or a jar '
            "keeps the server's own script -- that script is what writes the "
            'wrapper DOMjudge runs.[/info]'
        )

    if plan.preserved:
        console.console.print(
            'Kept enabled, untouched: '
            + ', '.join(f'[item]{item}[/item]' for item in sorted(plan.preserved))
        )
    if plan.unmatched:
        console.console.print(
            '[warning]No DOMjudge language matched[/warning] '
            + ', '.join(f'[item]{item}[/item]' for item in plan.unmatched)
            + '. Name one with `extensions.domjudge.languages` if the server has '
            'it disabled.'
        )

    if plan.config:
        table = Table(title='Configuration', title_justify='left')
        table.add_column('Key')
        table.add_column('Current')
        table.add_column('New')
        for change in plan.config:
            table.add_row(change.key, str(change.current), str(change.desired))
        console.console.print(table)
    console.console.print()


async def apply_plan(api: DomjudgeApi, plan: Plan) -> bool:
    """Runs the plan, returning whether everything it asked for landed."""
    ok = True
    if plan.languages:
        result = await api.configure_languages(plan.languages_payload())
        ok = _report_languages(plan, result) and ok
        ok = await _push_compile_scripts(api, plan) and ok
    if plan.config:
        config_result = await api.update_config(config_payload(plan.config))
        ok = _report_config(plan, config_result) and ok

    if ok:
        console.console.print('[success]DOMjudge is configured.[/success]')
    return ok


def _report_languages(plan: Plan, result: Any) -> bool:
    """Check the languages actually took, since DOMjudge will not say so.

    An id that matches no `externalid` is dropped without a word, and the
    response is just the resulting language list. Comparing against it is the
    only way to catch a typo -- which matters more here than usual, because the
    same call has already disabled every language not in the payload.
    """
    if not isinstance(result, list):
        return True
    enabled = {
        str(language['id']) for language in result if language.get('id') is not None
    }
    missing = [
        language_id for language_id in plan.managed_ids if language_id not in enabled
    ]
    console.console.print(
        f'Enabled [item]{len(enabled)}[/item] languages on the server.'
    )
    if not missing:
        return True
    console.console.print(
        '[error]DOMjudge ignored[/error] '
        + ', '.join(f'[item]{item}[/item]' for item in missing)
        + ': no language on the server has that `externalid`. Note DOMjudge '
        'matches the external id, not the id in the admin UI (`py3` is '
        '`python3`, `pas` is `pascal`).'
    )
    return False


async def _push_compile_scripts(api: DomjudgeApi, plan: Plan) -> bool:
    for language in plan.languages:
        if language.compile_script is None:
            continue
        await api.update_language_executable(
            language.language_id, language.compile_script.zip_bytes()
        )
        console.console.print(
            f'Pushed the compile script for [item]{language.language_id}[/item]: '
            f'[status]{language.compile_script.command}[/status]'
        )
    return True


def _report_config(plan: Plan, result: Dict[str, Any]) -> bool:
    """Read the answer back: DOMjudge accepts an unknown key with a 200."""
    if not isinstance(result, dict):
        return True
    stale: List[str] = []
    for change in plan.config:
        if result.get(change.key) != change.desired:
            stale.append(change.key)
        else:
            console.console.print(
                f'Set [item]{change.key}[/item] to [status]{change.desired}[/status].'
            )
    if not stale:
        return True
    console.console.print(
        '[error]DOMjudge did not store[/error] '
        + ', '.join(f'[item]{item}[/item]' for item in stale)
        + '. The server may be running a version that does not know these keys.'
    )
    return False
