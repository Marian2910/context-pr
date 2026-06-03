from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from contextpr.models import IssueLocation, SonarIssue
from contextpr.persistence import SonarIssueRecord


def map_issue(payload: Mapping[str, object]) -> SonarIssue | None:
    component = payload.get("component")
    if not isinstance(component, str) or ":" not in component:
        return None

    fields = extract_issue_fields(payload)
    if fields is None:
        return None

    path = component.split(":", maxsplit=1)[1]
    issue_key, rule, severity, message, line, end_line, issue_type = fields

    return SonarIssue(
        key=issue_key,
        rule=rule,
        severity=severity,
        message=message,
        location=IssueLocation(path=path, line=line, end_line=end_line),
        issue_type=issue_type,
        tags=extract_tags(payload),
        clean_code_attribute=extract_string(payload, "cleanCodeAttribute"),
        clean_code_attribute_category=extract_string(
            payload,
            "cleanCodeAttributeCategory",
        ),
        effort=optional_string(payload, "effort") or optional_string(payload, "debt"),
    )


def map_issue_record(payload: Mapping[str, object]) -> SonarIssueRecord | None:
    issue = map_issue(payload)
    if issue is None:
        return None

    return SonarIssueRecord(
        issue_key=issue.key,
        rule=issue.rule,
        issue_type=issue.issue_type,
        severity=issue.severity,
        component=issue.location.path,
        message=issue.message,
        tags_json=json.dumps(list(issue.tags)) if issue.tags else None,
        clean_code_attribute=issue.clean_code_attribute or None,
        clean_code_attribute_category=issue.clean_code_attribute_category or None,
        status=optional_string(payload, "status"),
        resolution=optional_string(payload, "resolution"),
        created_at=optional_string(payload, "creationDate"),
        updated_at=optional_string(payload, "updateDate"),
        branch=optional_string(payload, "branch"),
        line=issue.location.line,
        end_line=issue.location.end_line,
    )


def optional_string(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def extract_issue_fields(
    payload: Mapping[str, object],
) -> tuple[str, str, str, str, int | None, int | None, str] | None:
    issue_key = payload.get("key")
    rule = payload.get("rule")
    severity = payload.get("severity")
    message = payload.get("message")
    issue_type = payload.get("type")

    if not all(
        isinstance(value, str)
        for value in (issue_key, rule, severity, message, issue_type)
    ):
        return None

    return (
        cast(str, issue_key),
        cast(str, rule),
        cast(str, severity),
        cast(str, message),
        extract_start_line(payload),
        extract_end_line(payload),
        cast(str, issue_type),
    )


def extract_tags(payload: Mapping[str, object]) -> tuple[str, ...]:
    tags = payload.get("tags")
    if not isinstance(tags, list):
        return ()

    return tuple(tag for tag in tags if isinstance(tag, str))


def extract_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value

    return ""


def extract_start_line(payload: Mapping[str, object]) -> int | None:
    return line_from_text_range(payload) or line_from_flows(payload)


def extract_end_line(payload: Mapping[str, object]) -> int | None:
    return end_line_from_text_range(payload) or end_line_from_flows(payload)


def line_from_text_range(payload: Mapping[str, object]) -> int | None:
    return get_start_line(payload.get("textRange"))


def end_line_from_text_range(payload: Mapping[str, object]) -> int | None:
    return get_end_line(payload.get("textRange"))


def line_from_flows(payload: Mapping[str, object]) -> int | None:
    flows = payload.get("flows")
    if not isinstance(flows, list):
        return None

    for flow in flows:
        line = line_from_flow(flow)
        if line is not None:
            return line

    return None


def end_line_from_flows(payload: Mapping[str, object]) -> int | None:
    flows = payload.get("flows")
    if not isinstance(flows, list):
        return None

    for flow in flows:
        line = end_line_from_flow(flow)
        if line is not None:
            return line

    return None


def line_from_flow(flow: object) -> int | None:
    if not isinstance(flow, Mapping):
        return None

    locations = flow.get("locations")
    if not isinstance(locations, list):
        return None

    for location in locations:
        line = line_from_location(location)
        if line is not None:
            return line

    return None


def end_line_from_flow(flow: object) -> int | None:
    if not isinstance(flow, Mapping):
        return None

    locations = flow.get("locations")
    if not isinstance(locations, list):
        return None

    for location in locations:
        line = end_line_from_location(location)
        if line is not None:
            return line

    return None


def line_from_location(location: object) -> int | None:
    if not isinstance(location, Mapping):
        return None

    return get_start_line(location.get("textRange"))


def end_line_from_location(location: object) -> int | None:
    if not isinstance(location, Mapping):
        return None

    return get_end_line(location.get("textRange"))


def get_start_line(text_range: object) -> int | None:
    if isinstance(text_range, Mapping):
        start_line = text_range.get("startLine")
        if isinstance(start_line, int):
            return start_line
    return None


def get_end_line(text_range: object) -> int | None:
    if isinstance(text_range, Mapping):
        end_line = text_range.get("endLine")
        if isinstance(end_line, int):
            return end_line
    return None
