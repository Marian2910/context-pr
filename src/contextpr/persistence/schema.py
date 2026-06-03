from __future__ import annotations

import sqlite3

from contextpr.persistence.locking import SchemaVersionError

SCHEMA_VERSION = 2


def apply_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS repositories (
            repository_id INTEGER PRIMARY KEY AUTOINCREMENT,
            repository_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sync_state (
            repository_id INTEGER NOT NULL,
            source_name TEXT NOT NULL,
            cursor TEXT,
            updated_at TEXT,
            metadata_json TEXT,
            PRIMARY KEY (repository_id, source_name),
            FOREIGN KEY (repository_id) REFERENCES repositories(repository_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS sonar_issues (
            repository_id INTEGER NOT NULL,
            issue_key TEXT NOT NULL,
            rule TEXT NOT NULL,
            issue_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            component TEXT NOT NULL,
            message TEXT NOT NULL,
            tags_json TEXT,
            clean_code_attribute TEXT,
            clean_code_attribute_category TEXT,
            status TEXT,
            resolution TEXT,
            created_at TEXT,
            updated_at TEXT,
            branch TEXT,
            line INTEGER,
            end_line INTEGER,
            PRIMARY KEY (repository_id, issue_key),
            FOREIGN KEY (repository_id) REFERENCES repositories(repository_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS sonar_issue_observations (
            observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            repository_id INTEGER NOT NULL,
            issue_key TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            status TEXT,
            resolution TEXT,
            severity TEXT,
            component TEXT,
            branch TEXT,
            message TEXT,
            FOREIGN KEY (repository_id) REFERENCES repositories(repository_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS git_commits (
            repository_id INTEGER NOT NULL,
            commit_sha TEXT NOT NULL,
            authored_at TEXT NOT NULL,
            message TEXT NOT NULL,
            classification TEXT NOT NULL,
            PRIMARY KEY (repository_id, commit_sha),
            FOREIGN KEY (repository_id) REFERENCES repositories(repository_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS git_file_touches (
            touch_id INTEGER PRIMARY KEY AUTOINCREMENT,
            repository_id INTEGER NOT NULL,
            commit_sha TEXT NOT NULL,
            file_path TEXT NOT NULL,
            module_family TEXT,
            FOREIGN KEY (repository_id) REFERENCES repositories(repository_id) ON DELETE CASCADE,
            FOREIGN KEY (repository_id, commit_sha)
                REFERENCES git_commits(repository_id, commit_sha) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS pull_requests (
            repository_id INTEGER NOT NULL,
            pr_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT,
            state TEXT,
            merged_at TEXT,
            updated_at TEXT,
            PRIMARY KEY (repository_id, pr_number),
            FOREIGN KEY (repository_id) REFERENCES repositories(repository_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS pull_request_files (
            pull_request_file_id INTEGER PRIMARY KEY AUTOINCREMENT,
            repository_id INTEGER NOT NULL,
            pr_number INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            FOREIGN KEY (repository_id) REFERENCES repositories(repository_id) ON DELETE CASCADE,
            FOREIGN KEY (repository_id, pr_number)
                REFERENCES pull_requests(repository_id, pr_number) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS pull_request_review_comments (
            repository_id INTEGER NOT NULL,
            comment_id INTEGER NOT NULL,
            pr_number INTEGER NOT NULL,
            body TEXT NOT NULL,
            file_path TEXT,
            line INTEGER,
            author_role TEXT,
            created_at TEXT,
            updated_at TEXT,
            PRIMARY KEY (repository_id, comment_id),
            FOREIGN KEY (repository_id) REFERENCES repositories(repository_id) ON DELETE CASCADE,
            FOREIGN KEY (repository_id, pr_number)
                REFERENCES pull_requests(repository_id, pr_number) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_sync_state_source
            ON sync_state(repository_id, source_name);
        CREATE INDEX IF NOT EXISTS idx_sonar_issue_rule
            ON sonar_issues(repository_id, rule);
        CREATE INDEX IF NOT EXISTS idx_sonar_issue_component
            ON sonar_issues(repository_id, component);
        CREATE INDEX IF NOT EXISTS idx_sonar_observation_issue
            ON sonar_issue_observations(repository_id, issue_key, observed_at);
        CREATE INDEX IF NOT EXISTS idx_git_touch_file
            ON git_file_touches(repository_id, file_path);
        CREATE INDEX IF NOT EXISTS idx_pull_request_file
            ON pull_request_files(repository_id, pr_number, file_path);
        CREATE INDEX IF NOT EXISTS idx_pull_request_comment_pr
            ON pull_request_review_comments(repository_id, pr_number);
        """
    )
    _ensure_column(connection, "sonar_issues", "line", "INTEGER")
    _ensure_column(connection, "sonar_issues", "end_line", "INTEGER")
    version = read_schema_version(connection)
    if version > SCHEMA_VERSION:
        raise SchemaVersionError(
            f"History store schema version {version} is newer than supported version "
            f"{SCHEMA_VERSION}."
        )
    connection.execute(
        """
        INSERT INTO schema_metadata (key, value)
        VALUES ('schema_version', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (str(SCHEMA_VERSION),),
    )


def read_schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        """
        SELECT value
        FROM schema_metadata
        WHERE key = 'schema_version'
        """
    ).fetchone()
    if row is None:
        return 0
    return int(row["value"])


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    if any(str(row["name"]) == column_name for row in rows):
        return
    connection.execute(
        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
    )
