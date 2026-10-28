"""Typed reasoning/retrieval roles; none supplies labels, measurements, or verdicts."""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from typing import Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .providers import Gateway, ProviderError
from .store import now


SOURCE_EXTRACTION_PROFILE = "atomic_source_fields_v3"
SOURCE_EXTRACTION_RULES = (
    "Read the actual bounded primary excerpts. Extract exactly the SIX required_fields, preserving field name and source_id, "
    "with numeric value AS A STRING in ASCII decimal or e-notation and status source_supported. Unicode mathematical notation "
    "is not accepted numeric syntax. Expected answers are not provided as a separate answer map. Do not add atomic fields. "
    "Classify whether original supplement settings and pinned current defaults differ. Do not infer any executed setting from "
    "these source versions: the actual experiment is separately authored and its execution settings are not established by these "
    "excerpts. Return no narrative, recommendations, execution choices or inferred outcomes. Trusted code supplies the scope narrative. "
    "Conform exactly to the JSON schema."
)


class CompetingPrediction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    explanation: str = Field(min_length=10, max_length=500)
    prediction: str = Field(min_length=10, max_length=700)


class WheatPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    cell_id: str = Field(min_length=3, max_length=80)
    question: str = Field(min_length=15, max_length=600)
    rationale: str = Field(min_length=20, max_length=1200)
    unchanged_controls: list[str] = Field(min_length=3, max_length=10)
    competing_predictions: list[CompetingPrediction] = Field(min_length=2, max_length=3)
    source_basis: list[str] = Field(min_length=1, max_length=5)
    resource_requirement: str = Field(min_length=15, max_length=600)
    remain_unresolved_if: str = Field(min_length=15, max_length=700)
    efficiency_claim: Literal["not_established"]


class ExtractedField(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    field: str = Field(min_length=2, max_length=100)
    source_id: str = Field(min_length=2, max_length=150)
    value: str = Field(min_length=1, max_length=100, pattern=r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")
    status: Literal["source_supported"]


class WheatSources(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    fields: list[ExtractedField] = Field(min_length=6, max_length=6)
    conflict_classification: Literal["different_original_and_current_settings", "same_original_and_current_settings", "insufficient_source_evidence"]
    executed_settings: Literal["not_established_by_excerpts"]


class WheatGateway(Gateway):
    async def retrieve_wheat(self) -> dict:
        if not self.settings.tavily_key:
            raise ProviderError("retrieval_unconfigured", "Tavily is not configured. No recorded source was substituted.")
        parameters = {
            "query": "SAHI official get_sliced_prediction slice_height overlap_height_ratio small objects inference",
            "search_depth": "advanced", "max_results": 5, "include_answer": False,
            "include_raw_content": False, "include_domains": ["obss.github.io", "github.com/obss/sahi", "arxiv.org"],
        }
        receipt = {"id": str(uuid.uuid4()), "kind": "retrieval", "provider": "tavily", "model": None,
                   "purpose": "Source-to-recipe change: enable documented native and degraded-input SAHI baselines",
                   "status": "pending", "request_id": None, "started_at": now(), "elapsed_ms": None,
                   "input_tokens": None, "output_tokens": None, "estimated_cost_usd": None,
                   "error": None, "query": parameters["query"], "parameters": parameters, "results": [], "credits": None}
        self.save_receipt(receipt.copy())
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15), follow_redirects=False) as client:
                response = await client.post("https://api.tavily.com/search", headers={"Authorization": "Bearer " + self.settings.tavily_key}, json=parameters)
            receipt["http_status"] = response.status_code
            if response.status_code != 200:
                raise ProviderError("retrieval_http_error", f"Tavily returned HTTP {response.status_code}. The recipe family was not changed.")
            data = response.json()
            receipt["request_id"] = data.get("request_id") or response.headers.get("x-request-id")
            receipt["credits"] = (data.get("usage") or {}).get("credits")
            receipt["returned_result_count"] = len(data.get("results", []))
            approved = []
            for raw in data.get("results", [])[:5]:
                url = str(raw.get("url", ""))
                parsed = urlparse(url)
                if parsed.scheme != "https" or parsed.username or parsed.password:
                    continue
                primary = ((parsed.hostname == "obss.github.io" and parsed.path.startswith("/sahi/")) or
                           (parsed.hostname == "github.com" and parsed.path.startswith("/obss/sahi")) or
                           (parsed.hostname == "arxiv.org" and parsed.path in {"/abs/2202.06934", "/html/2202.06934v1"}))
                content = re.sub(r"\s+", " ", str(raw.get("content", ""))).strip()
                supported = primary and any(term in content.lower() for term in ("sliced", "slicing", "get_sliced_prediction"))
                words = content.split()
                at = next((index for index, word in enumerate(words) if "slic" in word.lower()), 0)
                excerpt = " ".join(words[max(0, at - 6):max(0, at - 6) + 24])
                item = {"title": str(raw.get("title", "Returned source"))[:250], "url": url,
                        "excerpt": excerpt, "score": raw.get("score"), "eligible": supported,
                        "selection_reason": "Primary SAHI source supports sliced inference" if supported else "Context only: source identity or sliced-inference support did not pass the fixed check"}
                receipt["results"].append(item)
                if supported:
                    approved.append(item)
            receipt["status"] = "succeeded"
            source = next((item for item in approved if "obss.github.io/sahi/" in item["url"]), approved[0] if approved else None)
            return {"source": source, "receipt": receipt, "query": parameters["query"], "queried_at": receipt["started_at"]}
        except asyncio.CancelledError:
            receipt.update(status="cancelled", error="Local retrieval cancelled; remote billing/termination may be unknown.")
            raise
        except ProviderError as exc:
            receipt.update(status="failed", error=exc.message)
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            receipt.update(status="failed", error="Retrieval failed or returned invalid JSON. No recipe was enabled.")
            raise ProviderError("retrieval_failed", receipt["error"]) from exc
        finally:
            receipt["elapsed_ms"] = round((time.monotonic() - started) * 1000)
            self.last_receipt = receipt.copy()
            self.save_receipt(receipt)
