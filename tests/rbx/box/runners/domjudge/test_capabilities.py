"""What the DOMjudge backend claims it can report.

Capabilities are *declared*, not discovered, so a wrong one is not caught by
anything at runtime -- it silently produces a report answering a different
question. These pin the two that were actually established by running against a
live server, in the direction that would otherwise regress quietly.
"""

from rbx.box.runners.domjudge.runner import DomjudgeRunner


def test_interactive_problems_are_supported():
    """Verified end-to-end on a real DOMjudge, in both shapes the packager emits.

    A modern interactor becomes DOMjudge's `run` script directly. A legacy
    interactor is chained with its checker, which was confirmed by a solution the
    interactor accepts and only the checker rejects (12 queries against a
    10-query budget) coming back WA.
    """
    assert DomjudgeRunner.caps.supports_interactive


def test_what_the_api_cannot_report_is_declared_as_such():
    """A consumer that read a `None` as zero would call an unmeasured run
    instantaneous, so these have to stay false rather than be guessed at."""
    caps = DomjudgeRunner.caps

    assert not caps.measures_memory
    assert not caps.captures_artifacts
    assert not caps.reports_checker_messages


def test_a_batch_backend_is_not_gated():
    """DOMjudge has already judged everything by the time rbx reads the
    judgement, so gating would overwrite real verdicts with SKIPPED."""
    assert not DomjudgeRunner.caps.supports_abort
