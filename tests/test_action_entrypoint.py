from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path


def test_action_entrypoint_reads_input_names(tmp_path: Path) -> None:
    capture_path = tmp_path / "capture.json"
    fake_contextpr = tmp_path / "contextpr"
    fake_contextpr.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "python3 - \"$@\" <<'PY'",
                "import json",
                "import os",
                "from pathlib import Path",
                f"Path({str(capture_path)!r}).write_text(json.dumps({{",
                "    'argv': os.sys.argv[1:],",
                "    'env': {",
                "        'CONTEXTPR_SONAR_TOKEN': os.environ.get('CONTEXTPR_SONAR_TOKEN'),",
                "        'CONTEXTPR_SONAR_PROJECT_KEY': "
                "os.environ.get('CONTEXTPR_SONAR_PROJECT_KEY'),",
                "        'CONTEXTPR_GITHUB_REPOSITORY': "
                "os.environ.get('CONTEXTPR_GITHUB_REPOSITORY'),",
                "        'CONTEXTPR_GITHUB_APP_ID': os.environ.get('CONTEXTPR_GITHUB_APP_ID'),",
                "        'CONTEXTPR_GITHUB_INSTALLATION_ID': "
                "os.environ.get('CONTEXTPR_GITHUB_INSTALLATION_ID'),",
                "    },",
                "} ))",
                "PY",
            ]
        )
    )
    fake_contextpr.chmod(fake_contextpr.stat().st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    env["INPUT_SONAR_TOKEN"] = "sonar-token"
    env["INPUT_SONAR_PROJECT_KEY"] = "project-key"
    env["INPUT_GITHUB_REPOSITORY"] = "octo/example"
    env["INPUT_GITHUB_APP_ID"] = "12345"
    env["INPUT_GITHUB_INSTALLATION_ID"] = "67890"
    env["INPUT_PR_NUMBER"] = "42"
    env["INPUT_DRY_RUN"] = "false"

    subprocess.run(
        ["/bin/sh", "scripts/action-entrypoint.sh"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=True,
    )

    payload = json.loads(capture_path.read_text())
    assert payload["argv"] == ["analyze", "--pr-number", "42", "--no-dry-run"]
    assert payload["env"] == {
        "CONTEXTPR_SONAR_TOKEN": "sonar-token",
        "CONTEXTPR_SONAR_PROJECT_KEY": "project-key",
        "CONTEXTPR_GITHUB_REPOSITORY": "octo/example",
        "CONTEXTPR_GITHUB_APP_ID": "12345",
        "CONTEXTPR_GITHUB_INSTALLATION_ID": "67890",
    }


def test_action_entrypoint_falls_back_to_contextpr_env_vars(tmp_path: Path) -> None:
    capture_path = tmp_path / "capture.json"
    fake_contextpr = tmp_path / "contextpr"
    fake_contextpr.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "python3 - \"$@\" <<'PY'",
                "import json",
                "import os",
                "from pathlib import Path",
                f"Path({str(capture_path)!r}).write_text(json.dumps({{",
                "    'argv': os.sys.argv[1:],",
                "    'env': {",
                "        'CONTEXTPR_SONAR_TOKEN': os.environ.get('CONTEXTPR_SONAR_TOKEN'),",
                "        'CONTEXTPR_SONAR_PROJECT_KEY': "
                "os.environ.get('CONTEXTPR_SONAR_PROJECT_KEY'),",
                "        'CONTEXTPR_GITHUB_REPOSITORY': "
                "os.environ.get('CONTEXTPR_GITHUB_REPOSITORY'),",
                "        'CONTEXTPR_GITHUB_APP_ID': os.environ.get('CONTEXTPR_GITHUB_APP_ID'),",
                "        'CONTEXTPR_GITHUB_INSTALLATION_ID': "
                "os.environ.get('CONTEXTPR_GITHUB_INSTALLATION_ID'),",
                "    },",
                "} ))",
                "PY",
            ]
        )
    )
    fake_contextpr.chmod(fake_contextpr.stat().st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    env["CONTEXTPR_SONAR_TOKEN"] = "sonar-token"
    env["CONTEXTPR_SONAR_PROJECT_KEY"] = "project-key"
    env["CONTEXTPR_GITHUB_REPOSITORY"] = "octo/example"
    env["CONTEXTPR_GITHUB_APP_ID"] = "12345"
    env["CONTEXTPR_GITHUB_INSTALLATION_ID"] = "67890"
    env["CONTEXTPR_PR_NUMBER"] = "42"
    env["CONTEXTPR_DRY_RUN"] = "false"

    subprocess.run(
        ["/bin/sh", "scripts/action-entrypoint.sh"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=True,
    )

    payload = json.loads(capture_path.read_text())
    assert payload["argv"] == ["analyze", "--pr-number", "42", "--no-dry-run"]
    assert payload["env"] == {
        "CONTEXTPR_SONAR_TOKEN": "sonar-token",
        "CONTEXTPR_SONAR_PROJECT_KEY": "project-key",
        "CONTEXTPR_GITHUB_REPOSITORY": "octo/example",
        "CONTEXTPR_GITHUB_APP_ID": "12345",
        "CONTEXTPR_GITHUB_INSTALLATION_ID": "67890",
    }
