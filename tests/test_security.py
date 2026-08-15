"""Tests for API keys and rate limiting.

Written against the failure modes rather than the happy path: a gate that lets
the wrong caller through is worth less than no gate, because it is believed.
"""

from typing import Any, cast

import pytest
from fastapi import HTTPException, Request

from disclosure_rag.security import OPEN_PATHS, ApiKeys, RateLimiter, client_of


class FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class FakeURL:
    def __init__(self, path: str) -> None:
        self.path = path


class FakeRequest:
    def __init__(
        self, headers: dict[str, str], host: str = "10.0.0.1", path: str = "/query"
    ) -> None:
        self.headers = headers
        self.client = FakeClient(host)
        self.url = FakeURL(path)


def request(headers: dict[str, str], host: str = "10.0.0.1") -> Request:
    """Only the three attributes client_of reads, without a live ASGI scope."""
    return cast(Request, cast(Any, FakeRequest(headers, host)))


def test_no_configured_keys_accepts_everything() -> None:
    """The local default. A demo that needs an invented credential is a demo
    nobody runs."""
    keys = ApiKeys("")
    assert not keys.enabled
    assert keys.accepts(None)
    assert keys.accepts("anything")


def test_a_configured_key_rejects_absence_and_wrong_values() -> None:
    keys = ApiKeys("s3cret")
    assert keys.enabled
    assert keys.accepts("s3cret")
    assert not keys.accepts(None)
    assert not keys.accepts("")
    assert not keys.accepts("s3cre")
    assert not keys.accepts("s3cret ")
    assert not keys.accepts("S3CRET")


def test_several_keys_are_accepted_so_rotation_has_no_gap() -> None:
    """Add the new key, move callers, remove the old. Never a moment where
    neither works."""
    keys = ApiKeys("old-key, new-key ")
    assert keys.accepts("old-key")
    assert keys.accepts("new-key")
    assert not keys.accepts("other")


def test_blank_entries_do_not_become_a_key_that_accepts_nothing() -> None:
    """ "a,,b" must not leave an empty string in the list. It would never match
    a presented key, but it is the kind of quiet mistake that leaves a service
    looking configured when it is not."""
    assert ApiKeys("a,,b").keys == ("a", "b")
    assert ApiKeys("   ").keys == ()
    assert not ApiKeys("   ").enabled


def test_the_limiter_is_off_at_zero() -> None:
    limiter = RateLimiter(0)
    assert not limiter.enabled
    for _ in range(1000):
        limiter.check("caller")


def test_the_limiter_rejects_past_the_limit() -> None:
    limiter = RateLimiter(3, window_seconds=60)
    assert [limiter.check("caller", now=1.0) for _ in range(3)] == [2, 1, 0]
    with pytest.raises(HTTPException) as rejected:
        limiter.check("caller", now=1.0)
    assert rejected.value.status_code == 429
    assert "retry-after" in (rejected.value.headers or {})


def test_the_window_slides_rather_than_resetting_on_a_boundary() -> None:
    """A fixed bucket would allow twice the limit across a boundary: fill it
    just before the reset, then again just after."""
    limiter = RateLimiter(2, window_seconds=60)
    limiter.check("caller", now=0.0)
    limiter.check("caller", now=59.0)
    with pytest.raises(HTTPException):
        limiter.check("caller", now=60.0)  # the 0.0 hit is exactly at the edge, still counted
    limiter.check("caller", now=60.5)  # now it has aged out


def test_callers_are_counted_separately() -> None:
    limiter = RateLimiter(1, window_seconds=60)
    limiter.check("one", now=1.0)
    limiter.check("two", now=1.0)
    with pytest.raises(HTTPException):
        limiter.check("one", now=1.0)


def test_a_forwarded_header_cannot_be_used_to_dodge_the_limit() -> None:
    """x-forwarded-for is caller-controlled. Trusting it unconditionally means
    anyone who reads this file gets an unlimited quota by rotating the value."""
    first = client_of(request({"x-forwarded-for": "1.2.3.4"}))
    second = client_of(request({"x-forwarded-for": "5.6.7.8"}))
    assert first == second == "ip:10.0.0.1"


def test_a_key_identifies_the_caller_better_than_an_address() -> None:
    """Two callers behind one NAT share an address and should not share a quota."""
    assert client_of(request({"x-api-key": "abcdefghijkl"})) == "key:abcdefgh"


def test_the_client_id_does_not_carry_the_whole_key() -> None:
    """It reaches log lines and metric labels, so it holds a prefix, not the
    credential."""
    assert "abcdefghijkl" not in client_of(request({"x-api-key": "abcdefghijkl"}))


def test_liveness_and_metrics_stay_open() -> None:
    """A load balancer cannot tell unauthenticated from down, and a metrics
    scraper should not need its own credential."""
    assert "/health" in OPEN_PATHS
    assert "/metrics" in OPEN_PATHS
    assert "/query" not in OPEN_PATHS
    assert "/" not in OPEN_PATHS
