from contextpr.integrations.sonarqube import SonarQubeClient


def test_map_issue_preserves_text_range_end_line() -> None:
    issue = SonarQubeClient._map_issue(
        {
            "key": "issue-1",
            "rule": "python:S3923",
            "severity": "MAJOR",
            "message": "Remove this if statement.",
            "type": "CODE_SMELL",
            "component": "project:src/app.py",
            "textRange": {
                "startLine": 154,
                "endLine": 157,
            },
        }
    )

    assert issue is not None
    assert issue.location.path == "src/app.py"
    assert issue.location.line == 154
    assert issue.location.end_line == 157


def test_map_issue_reads_location_from_flows_when_text_range_is_missing() -> None:
    issue = SonarQubeClient._map_issue(
        {
            "key": "issue-2",
            "rule": "python:S1172",
            "severity": "MINOR",
            "message": "Remove unused parameter.",
            "type": "CODE_SMELL",
            "component": "project:src/app.py",
            "flows": [
                {
                    "locations": [
                        {
                            "textRange": {
                                "startLine": 40,
                                "endLine": 42,
                            }
                        }
                    ]
                }
            ],
        }
    )

    assert issue is not None
    assert issue.location.line == 40
    assert issue.location.end_line == 42


def test_map_issue_rejects_payload_without_component_path() -> None:
    issue = SonarQubeClient._map_issue(
        {
            "key": "issue-3",
            "rule": "python:S1172",
            "severity": "MINOR",
            "message": "Remove unused parameter.",
            "type": "CODE_SMELL",
            "component": "src/app.py",
        }
    )

    assert issue is None


def test_map_issue_rejects_payload_with_missing_required_strings() -> None:
    issue = SonarQubeClient._map_issue(
        {
            "key": "issue-4",
            "rule": "python:S1172",
            "severity": "MINOR",
            "type": "CODE_SMELL",
            "component": "project:src/app.py",
        }
    )

    assert issue is None
