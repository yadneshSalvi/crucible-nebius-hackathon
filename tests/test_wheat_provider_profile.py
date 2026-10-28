"""Mocked transport tests; these are not provider-qualification evidence."""
import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from api.config import Settings
from api.providers import ProviderError
from api.wheat_providers import ExtractedField, WheatGateway, WheatSources


def test_source_schema_excludes_ambiguous_math_and_invented_narrative():
    good = {"field": "original_learning_rate", "source_id": "fixture-source", "value": "1e-4", "status": "source_supported"}
    assert ExtractedField.model_validate(good).value == "1e-4"
    with pytest.raises(ValidationError):
        ExtractedField.model_validate({**good, "value": "10−4"})
    with pytest.raises(ValidationError):
        WheatSources.model_validate({"fields": [good] * 6, "conflict_classification": "different_original_and_current_settings",
            "executed_settings": "not_established_by_excerpts", "conflict_resolution": "The experiment used current defaults."})


def settings(tmp_path):
    return Settings(tmp_path, "nebius", "nvidia/Nemotron-3-Ultra-550b-a55b",
                    "https://api.tokenfactory.us-central1.nebius.com/v1", "fixture-only", "", True, None)


def test_nebius_profile_and_bounded_final_receipt(tmp_path, monkeypatch):
    sent, receipts = [], []
    answer = {"fields": [{"field": f"field_{i}", "source_id": "fixture-source", "value": "10", "status": "source_supported"} for i in range(6)],
              "conflict_classification": "different_original_and_current_settings", "executed_settings": "not_established_by_excerpts"}
    real_client = httpx.AsyncClient

    async def respond(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "mock-request", "model": settings(tmp_path).model,
            "usage": {"prompt_tokens": 100, "completion_tokens": 200}, "choices": [{"finish_reason": "stop",
                "message": {"content": json.dumps(answer), "reasoning_content": "MUST_NOT_BE_RETAINED"}}]})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    result = asyncio.run(WheatGateway(settings(tmp_path), receipts.append).model("mocked-source-role", {}, WheatSources, nominal_ceiling_usd=.12))
    assert result == answer and len(sent) == 1
    assert sent[0]["chat_template_kwargs"] == {"enable_thinking": True, "force_nonempty_content": True}
    assert sent[0]["temperature"] == 1 and sent[0]["top_p"] == .95 and sent[0]["max_tokens"] == 32000
    assert "response_format" not in sent[0] and "reasoning_effort" not in sent[0]
    assert "MUST_NOT_BE_RETAINED" not in json.dumps(receipts)
    assert receipts[-1]["status"] == "succeeded" and receipts[-1]["estimated_cost_usd"] == .0007
    assert receipts[-1]["budget_admission"]["estimated_request_bound_usd"] <= .12


def test_nebius_local_request_bound_fails_before_transmission(tmp_path, monkeypatch):
    receipts = []
    def forbidden(**kwargs):
        pytest.fail("No transport should be created after budget rejection")
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    with pytest.raises(ProviderError) as error:
        asyncio.run(WheatGateway(settings(tmp_path), receipts.append).model("mocked-over-budget", {}, WheatSources, nominal_ceiling_usd=.001))
    assert error.value.code == "request_budget_exceeded"
    assert receipts[-1]["status"] == "failed" and receipts[-1]["estimated_cost_usd"] == 0
