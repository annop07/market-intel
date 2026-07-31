"""A failure at the LLM endpoint should read like one — not like a crash here."""
from __future__ import annotations

import httpx
import pytest
from fastapi import HTTPException
from openai import APIStatusError

from app.main import _find_api_error, llm_errors


def quota_error() -> APIStatusError:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(401, request=request, json={"error": "This model reached daily limit."})
    return APIStatusError("This model reached daily limit.", response=response, body=None)


def test_finds_the_provider_error_through_a_wrapper():
    wrapped = RuntimeError("instructor gave up after 2 retries")
    wrapped.__cause__ = quota_error()

    assert _find_api_error(wrapped) is wrapped.__cause__


def test_returns_none_for_unrelated_errors():
    assert _find_api_error(ValueError("bad input")) is None


def test_survives_a_self_referencing_cause_chain():
    # A cycle here would otherwise hang the request instead of failing it.
    first = RuntimeError("a")
    second = RuntimeError("b")
    first.__cause__ = second
    second.__cause__ = first

    assert _find_api_error(first) is None


def test_provider_quota_becomes_a_502_with_the_reason():
    with pytest.raises(HTTPException) as caught:
        with llm_errors():
            raise quota_error()

    assert caught.value.status_code == 502
    assert "daily limit" in caught.value.detail


def test_our_own_bugs_are_not_disguised_as_provider_failures():
    with pytest.raises(KeyError):
        with llm_errors():
            raise KeyError("a real bug in this service")


def test_existing_http_exceptions_pass_through_untouched():
    with pytest.raises(HTTPException) as caught:
        with llm_errors():
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")

    assert caught.value.status_code == 503
