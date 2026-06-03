from prompt_toolkit.formatted_text import ANSI, to_formatted_text

from rbx.box.environment import LanguageGroupFallback
from rbx.box.timing import build_preview_renderer


def _text(ansi: ANSI) -> str:
    return ''.join(t for _, t in to_formatted_text(ansi))


def test_preview_renders_estimated_table():
    render = build_preview_renderer(
        timing_per_solution_per_language={
            'cpp': {'a.cpp': 100, 'b.cpp': 200},
            'python': {'p.py': 900},
        },
        formula='slowest * 3',
        env_groups=[],
        all_languages=['cpp', 'python'],
        width=80,
    )
    out = _text(render({'cpp': 1, 'python': 2}))
    assert 'Time Limit' in out  # the table header
    assert 'cpp' in out and 'python' in out


def test_preview_reflects_forced_relative():
    render = build_preview_renderer(
        timing_per_solution_per_language={'cpp': {'sol.cpp': 200}},
        formula='slowest',
        env_groups=[],
        all_languages=['cpp', 'python'],
        width=80,
    )
    out = _text(
        render(
            {'cpp': 1, 'python': 2},
            {'g2': LanguageGroupFallback(relativeTo='cpp', multiplier=2.0)},
        )
    )
    # python's group (g2) is forced relative to cpp x2.0; cpp estimate = 200 ->
    # python = 400ms must appear in the rendered table.
    assert '400' in out


def test_preview_reports_invalid_grouping_inline():
    # Two picker groups whose forced relatives reference each other -> cycle.
    render = build_preview_renderer(
        timing_per_solution_per_language={},
        formula='slowest * 3',
        env_groups=[],
        all_languages=['a', 'b'],
        width=80,
    )
    # The forced relatives make g1 -> b and g2 -> a, forming a cycle, so
    # validate_partition raises and the preview renders the inline warning.
    out = _text(
        render(
            {'a': 1, 'b': 2},
            {
                'g1': LanguageGroupFallback(relativeTo='b', multiplier=2.0),
                'g2': LanguageGroupFallback(relativeTo='a', multiplier=2.0),
            },
        )
    )
    assert 'Invalid grouping' in out


async def test_prompt_repartition_wires_a_working_preview(monkeypatch):
    from rbx.box import timing, timing_group_picker

    captured = {}

    async def fake_picker(languages, default_number, preview=None, **kwargs):
        captured['preview'] = preview
        return default_number

    monkeypatch.setattr(timing_group_picker, 'prompt_group_assignment', fake_picker)

    await timing._prompt_repartition(  # noqa: SLF001
        all_languages=['cpp', 'python'],
        env_groups=[],
        timing_per_solution_per_language={
            'cpp': {'a.cpp': 100},
            'python': {'p.py': 900},
        },
        formula='slowest * 3',
    )

    # The picker received a preview callback that renders the resolved table.
    out = _text(captured['preview']({'cpp': 1, 'python': 2}))
    assert 'Time Limit' in out
    assert 'cpp' in out and 'python' in out


def test_preview_memoizes_by_assignment():
    real = build_preview_renderer(
        timing_per_solution_per_language={'cpp': {'a.cpp': 100}},
        formula='slowest * 3',
        env_groups=[],
        all_languages=['cpp'],
        width=80,
    )

    # Same assignment dict (different identity) must hit the cache.
    first = real({'cpp': 1})
    second = real({'cpp': 1})
    assert first is second
