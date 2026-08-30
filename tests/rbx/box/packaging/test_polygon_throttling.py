import dataclasses
import json
import time as _time
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest
import requests
import typer

from rbx.box.packaging.polygon import throttling
from rbx.box.packaging.polygon.polygon_api import (
    Polygon,
    PolygonRequestFailedException,
    Request,
    RequestConfig,
)


@pytest.fixture(autouse=True)
def no_waiting():
    """Keeps the retry loop instantaneous, and isolates the shared limiter."""
    throttling.reset_limiter()
    with mock.patch.dict(
        'os.environ',
        {'RBX_POLYGON_MIN_INTERVAL': '0', 'RBX_POLYGON_MAX_INTERVAL': '0'},
    ):
        with mock.patch('rbx.box.packaging.polygon.polygon_api.time.sleep'):
            yield
    throttling.reset_limiter()


@dataclasses.dataclass
class _FakeHttpResponse:
    """The slice of ``requests.Response`` the Polygon client actually reads."""

    status_code: int
    text: str
    headers: Dict[str, str] = dataclasses.field(default_factory=dict)


def _http(status_code: int, text: str, headers: Optional[Dict[str, str]] = None):
    return _FakeHttpResponse(status_code, text, dict(headers or {}))


def _ok(result: Any = None):
    return _http(200, json.dumps({'status': 'OK', 'result': result}))


def _failed(comment: str, status_code: int = 400):
    return _http(status_code, json.dumps({'status': 'FAILED', 'comment': comment}))


def _request() -> Request:
    return Request(
        RequestConfig('https://polygon.codeforces.com/api', 'key', 'secret'),
        'problems.list',
    )


def _patch_post(responses: List[Any]):
    remaining = list(responses)

    def post(*args, **kwargs):
        item = remaining.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return mock.patch(
        'rbx.box.packaging.polygon.polygon_api.requests.post', side_effect=post
    )


def test_retries_throttling_comment_and_succeeds():
    with _patch_post(
        [
            _failed('Too many requests. Please, wait a few seconds and try again.'),
            _ok({'ok': True}),
        ]
    ) as post:
        response = _request().issue()

    assert response.status == 'OK'
    assert response.result == {'ok': True}
    assert post.call_count == 2


def test_retries_http_429_honoring_retry_after():
    with _patch_post(
        [_http(429, 'slow down', headers={'Retry-After': '3'}), _ok({'ok': True})]
    ) as post:
        response = _request().issue()

    assert response.status == 'OK'
    assert post.call_count == 2


def test_retries_html_error_page():
    with _patch_post([_http(200, '<html>502 Bad Gateway</html>'), _ok(1)]) as post:
        assert _request().issue().result == 1
        assert post.call_count == 2


def test_retries_connection_errors():
    with _patch_post([requests.ConnectionError('boom'), _ok(1)]) as post:
        assert _request().issue().result == 1
        assert post.call_count == 2


def test_does_not_retry_genuine_failures():
    with _patch_post([_failed('problemId: Problem not found')]) as post:
        response = _request().issue()

    assert response.status == 'FAILED'
    assert response.comment == 'problemId: Problem not found'
    assert post.call_count == 1


def test_gives_up_and_surfaces_polygon_comment():
    comment = 'Too many requests. Please, wait a few seconds and try again.'
    with mock.patch.dict('os.environ', {'RBX_POLYGON_MAX_RETRIES': '2'}):
        with _patch_post([_failed(comment)] * 3) as post:
            response = _request().issue()

    assert post.call_count == 3
    assert response.comment == comment


def test_gives_up_on_unreachable_api():
    with mock.patch.dict('os.environ', {'RBX_POLYGON_MAX_RETRIES': '1'}):
        with _patch_post([requests.ConnectionError('boom')] * 2) as post:
            with pytest.raises(typer.Exit):
                _request().issue()

    assert post.call_count == 2


def test_raw_requests_are_retried_too():
    with _patch_post([_http(503, 'unavailable'), _http(200, 'file contents')]) as post:
        assert _request().issue_raw() == 'file contents'
        assert post.call_count == 2


def test_api_client_still_raises_on_failed_after_retries():
    comment = 'Too many requests, try again later'
    with mock.patch.dict('os.environ', {'RBX_POLYGON_MAX_RETRIES': '1'}):
        with _patch_post([_failed(comment)] * 2):
            with pytest.raises(PolygonRequestFailedException) as exc:
                Polygon(
                    'https://polygon.codeforces.com/api', 'key', 'secret'
                ).problems_list()

    assert exc.value.comment == comment


def test_requests_carry_a_timeout():
    with _patch_post([_ok(1)]) as post:
        _request().issue()

    assert post.call_args.kwargs['timeout'] == throttling.request_timeout()


class TestRateLimiter:
    def test_spacing_widens_on_penalty_and_decays_on_success(self):
        limiter = throttling.RateLimiter(min_interval=0.1, max_interval=1.0)
        assert limiter.interval == pytest.approx(0.1)

        limiter.penalize()
        assert limiter.interval == pytest.approx(0.2)
        limiter.penalize()
        assert limiter.interval == pytest.approx(0.4)

        for _ in range(10):
            limiter.report_success()
        assert limiter.interval == pytest.approx(0.2)

    def test_spacing_never_exceeds_the_ceiling(self):
        limiter = throttling.RateLimiter(min_interval=0.1, max_interval=0.3)
        for _ in range(10):
            limiter.penalize()
        assert limiter.interval == pytest.approx(0.3)

    def test_acquire_spaces_out_consecutive_requests(self):
        limiter = throttling.RateLimiter(min_interval=0.05, max_interval=0.05)

        start = _time.monotonic()
        for _ in range(3):
            limiter.acquire()
        assert _time.monotonic() - start >= 0.1


class TestRetryClassification:
    @pytest.mark.parametrize(
        'comment',
        [
            'Too many requests. Please, wait a few seconds and try again.',
            'Rate limit exceeded',
            'Service unavailable',
            'Internal server error',
        ],
    )
    def test_transient_comments(self, comment):
        assert throttling.is_retryable_comment(comment)

    @pytest.mark.parametrize(
        'comment',
        ['problemId: Problem not found', 'checker: compilation error', ''],
    )
    def test_permanent_comments(self, comment):
        assert not throttling.is_retryable_comment(comment)

    @pytest.mark.parametrize('status', [408, 429, 500, 502, 503])
    def test_transient_statuses(self, status):
        assert throttling.is_retryable_status(status)

    @pytest.mark.parametrize('status', [200, 400, 401, 403, 404])
    def test_permanent_statuses(self, status):
        assert not throttling.is_retryable_status(status)

    def test_backoff_grows_and_is_capped(self):
        assert throttling.backoff_delay(0) <= 1.5
        assert throttling.backoff_delay(10) <= 45.0
        assert throttling.backoff_delay(0, retry_after=7) == 7

    def test_backoff_ignores_absurd_retry_after(self):
        assert throttling.backoff_delay(0, retry_after=100000) == 120.0
