from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib.parse import quote
from typing import TYPE_CHECKING, Protocol
from urllib import error, request

from contextpr.enrichment.history import HistoricalContext
from contextpr.models import SonarIssue

if TYPE_CHECKING:
    from contextpr.enrichment.nlp import DeveloperGuidance

logger = logging.getLogger(__name__)
HEDGING_MARKERS = ("usually", "often", "split", "small set", "leaned toward")
BANNED_CERTAINTY_MARKERS = ("always", "definitely", "clearly", "proves", "guarantees")
JSON_MIME_TYPE = "application/json"


class GuidanceVerbalizer(Protocol):
    def rewrite(
        self,
        issue: SonarIssue,
        guidance: DeveloperGuidance,
        historical_context: HistoricalContext | None,
    ) -> DeveloperGuidance:
        ...


@dataclass(frozen=True, slots=True)
class LLMVerbalizerSettings:
    api_url: str
    api_key: str
    model: str
    timeout_seconds: float = 15.0


class LightweightLLMGuidanceVerbalizer:
    def __init__(self, settings: LLMVerbalizerSettings) -> None:
        self._settings = settings

    def rewrite(
        self,
        issue: SonarIssue,
        guidance: DeveloperGuidance,
        historical_context: HistoricalContext | None,
    ) -> DeveloperGuidance:
        rewrite_targets = self._rewrite_targets(guidance)
        if not any(rewrite_targets.values()):
            return guidance

        payload = self._build_request_payload(
            issue,
            guidance,
            rewrite_targets,
            historical_context,
        )
        rewritten = self._call_model(payload)
        if rewritten is None:
            return guidance

        from contextpr.enrichment.nlp import DeveloperGuidance

        return DeveloperGuidance(
            level=guidance.level,
            explanation=self._pick_rewrite(
                rewritten,
                "explanation",
                guidance.explanation,
            ),
            next_step=guidance.next_step,
            evidence_note=self._pick_rewrite(
                rewritten,
                "evidence_note",
                guidance.evidence_note,
            ),
        )

    def _build_request_payload(
        self,
        issue: SonarIssue,
        guidance: DeveloperGuidance,
        rewrite_targets: dict[str, str | None],
        historical_context: HistoricalContext | None,
    ) -> dict[str, object]:
        facts = {
            "rule": issue.rule,
            "severity": issue.severity,
            "issue_type": issue.issue_type,
            "message": issue.message,
            "path": issue.location.path,
            "review_goal": self._review_goal(issue, guidance, historical_context),
            "first_check": guidance.next_step,
            "history": {
                "sample_size": historical_context.sample_size if historical_context else 0,
                "same_rule_matches": (
                    historical_context.same_rule_matches if historical_context else 0
                ),
<<<<<<< HEAD
                "same_exact_path_matches": (
                    historical_context.same_exact_path_matches if historical_context else 0
                ),
=======
>>>>>>> origin/main
                "same_scope_matches": (
                    historical_context.same_scope_matches if historical_context else 0
                ),
                "same_path_family_matches": (
                    historical_context.same_path_family_matches if historical_context else 0
                ),
<<<<<<< HEAD
                "same_rule_share": (
                    historical_context.same_rule_share if historical_context else 0.0
                ),
                "same_path_family_share": (
                    historical_context.same_path_family_share if historical_context else 0.0
                ),
                "same_exact_path_share": (
                    historical_context.same_exact_path_share if historical_context else 0.0
                ),
=======
>>>>>>> origin/main
                "dominant_maintenance": (
                    historical_context.dominant_maintenance if historical_context else None
                ),
                "dominant_disposition": (
                    historical_context.dominant_disposition if historical_context else None
                ),
                "historical_note": guidance.evidence_note,
            },
            "rewrite_targets": rewrite_targets,
        }
        instruction = (
<<<<<<< HEAD
            "You rewrite historically grounded pull request guidance for developers as a maintainability assistant. "
            "Do not restate Sonar's warning. "
            "Preserve uncertainty markers such as usually, often, split, or in a small set. "
            "Do not add claims, statistics, causes, or advice that are not present in the facts. "
            "When the facts mention recurrence, debt, hotspots, or later refactor burden, keep that emphasis. "
            "Make the explanation concrete and decision-oriented by telling the reviewer what to verify or pay down first. "
=======
            "You rewrite repository-grounded pull request guidance for developers. "
            "Do not restate Sonar's warning. "
            "Preserve uncertainty markers such as usually, often, split, or in a small set. "
            "Do not add claims, statistics, causes, or advice that are not present in the facts. "
            "Make the explanation concrete and decision-oriented by telling the reviewer what to verify first. "
>>>>>>> origin/main
            "Keep each returned field to one concise sentence. "
            "Return JSON only, using the same keys as rewrite_targets."
        )
        if self._is_gemini_api():
            return self._build_gemini_payload(instruction, facts)

        return self._build_openai_payload(instruction, facts)

    def _build_openai_payload(
        self,
        instruction: str,
        facts: dict[str, object],
    ) -> dict[str, object]:
        return {
            "model": self._settings.model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": instruction,
                },
                {
                    "role": "user",
                    "content": json.dumps(facts, ensure_ascii=True),
                },
            ],
        }

    def _build_gemini_payload(
        self,
        instruction: str,
        facts: dict[str, object],
    ) -> dict[str, object]:
        return {
            "system_instruction": {
                "parts": [
                    {
                        "text": instruction,
                    }
                ]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": json.dumps(facts, ensure_ascii=True),
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 160,
                "responseMimeType": JSON_MIME_TYPE,
            },
        }

    @staticmethod
    def _rewrite_targets(guidance: DeveloperGuidance) -> dict[str, str | None]:
        return {
            "explanation": guidance.explanation,
            "evidence_note": guidance.evidence_note,
        }

    @staticmethod
    def _review_goal(
        issue: SonarIssue,
        guidance: DeveloperGuidance,
        historical_context: HistoricalContext | None,
    ) -> str:
        if issue.issue_type == "BUG":
            return "Help the reviewer decide whether the warning may reflect a behavior change risk."
<<<<<<< HEAD
        if issue.issue_type == "CODE_SMELL":
            if (
                historical_context is not None
                and historical_context.dominant_disposition == "persistent"
            ):
                return (
                    "Help the reviewer judge whether this debt tends to linger in this area "
                    "and whether it is worth paying down now."
                )
            return (
                "Help the reviewer judge whether this smell is recurring maintenance debt "
                "and whether fixing it now avoids a later cleanup pass."
            )
=======
>>>>>>> origin/main
        if historical_context is not None and historical_context.dominant_disposition == "persistent":
            return "Help the reviewer decide whether this warning should be addressed now or safely deferred."
        if guidance.evidence_note is not None:
            return "Help the reviewer decide whether this is a straightforward refactor or needs closer review."
        return "Help the reviewer decide what to inspect first."

    def _call_model(self, payload: dict[str, object]) -> dict[str, str] | None:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            self._request_url(),
            data=body,
            headers=self._request_headers(),
            method="POST",
        )
        try:
            with request.urlopen(
                http_request,
                timeout=self._settings.timeout_seconds,
            ) as response:
                raw_response = response.read().decode("utf-8")
        except (error.HTTPError, error.URLError, TimeoutError, ValueError) as exc:
            logger.warning(
                "LLM verbalizer request failed.",
                extra={
                    "error": str(exc),
                    "model": self._settings.model,
                    "api_url": self._request_url(),
                },
            )
            return None

        try:
            parsed = json.loads(raw_response)
            content_payload = self._parse_response_payload(parsed)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            logger.warning(
                "LLM verbalizer response was not parseable.",
                extra={
                    "error": str(exc),
                    "model": self._settings.model,
                    "response_preview": self._response_preview(raw_response),
                },
            )
            return None

        return {
            key: value
            for key, value in content_payload.items()
            if isinstance(value, str) and value.strip()
        }

    def _request_url(self) -> str:
        api_url = self._settings.api_url.rstrip("/")
        if not self._is_gemini_api():
            return api_url

        if "{model}" in api_url:
            return api_url.replace("{model}", quote(self._settings.model, safe=""))
        if api_url.endswith(":generateContent"):
            return api_url
        if api_url.endswith("/v1beta") or api_url.endswith("/v1"):
            return f"{api_url}/models/{self._settings.model}:generateContent"
        return f"{api_url}/models/{self._settings.model}:generateContent"

    def _request_headers(self) -> dict[str, str]:
        if self._is_gemini_api():
            return {
                "Content-Type": JSON_MIME_TYPE,
                "X-goog-api-key": self._settings.api_key,
            }

        return {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Content-Type": JSON_MIME_TYPE,
        }

    def _parse_response_payload(self, parsed: dict[str, object]) -> dict[str, object]:
        if self._is_gemini_api():
            return self._parse_gemini_response(parsed)

        content = parsed["choices"][0]["message"]["content"]
        return self._parse_json_text(content)

    def _parse_gemini_response(self, parsed: dict[str, object]) -> dict[str, object]:
        candidates = parsed["candidates"]
        first_candidate = candidates[0]
        candidate_content = first_candidate["content"]
        parts = candidate_content["parts"]
        text = "".join(
            str(part.get("text", ""))
            for part in parts
            if isinstance(part, dict)
        )
        return self._parse_json_text(text)

    @staticmethod
    def _parse_json_text(content: object) -> dict[str, object]:
        if not isinstance(content, str):
            raise TypeError("Expected text content from LLM response.")

        stripped = content.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()

        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            extracted = LightweightLLMGuidanceVerbalizer._extract_json_object(stripped)
            if extracted is None:
                raise
            return json.loads(extracted)

    def _is_gemini_api(self) -> bool:
        return "generativelanguage.googleapis.com" in self._settings.api_url

    @staticmethod
    def _extract_json_object(text: str) -> str | None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        return text[start : end + 1]

    @staticmethod
    def _response_preview(raw_response: str, *, limit: int = 240) -> str:
        compact = " ".join(raw_response.split())
        if len(compact) <= limit:
            return compact
        return f"{compact[:limit]}..."

    @staticmethod
    def _pick_rewrite(
        rewritten: dict[str, str],
        key: str,
        fallback: str | None,
    ) -> str | None:
        candidate = rewritten.get(key)
        if candidate is None:
            return fallback
        if fallback is None:
            return None

        normalized = candidate.strip()
        if not normalized:
            return fallback
        if not LightweightLLMGuidanceVerbalizer._is_safe_rewrite(
            key=key,
            candidate=normalized,
            fallback=fallback,
        ):
            return fallback
        return normalized

    @staticmethod
    def _is_safe_rewrite(
        *,
        key: str,
        candidate: str,
        fallback: str | None,
    ) -> bool:
        lowered = candidate.lower()
        if len(candidate) > 220:
            return False
        if any(marker in lowered for marker in BANNED_CERTAINTY_MARKERS):
            return False
        if key == "explanation" and lowered.startswith("sonar "):
            return False
        if key == "evidence_note" and fallback is not None:
            fallback_lower = fallback.lower()
            if any(marker in fallback_lower for marker in HEDGING_MARKERS):
                if not any(marker in lowered for marker in HEDGING_MARKERS):
                    return False
        return True
