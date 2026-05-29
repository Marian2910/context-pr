from __future__ import annotations

import fcntl
import hashlib
import threading
import time
from pathlib import Path
from typing import BinaryIO, Self


class HistoryStoreError(RuntimeError):
    """Raised when the local history store cannot be used safely."""


class RepositoryLockError(HistoryStoreError):
    """Raised when a repository lock cannot be acquired."""


class SchemaVersionError(HistoryStoreError):
    """Raised when the on-disk schema is newer than the current code expects."""


_THREAD_LOCKS: dict[Path, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class RepositoryLock:
    def __init__(
        self,
        *,
        repository_key: str,
        thread_lock: threading.Lock,
        lock_file: Path,
        handle: BinaryIO,
    ) -> None:
        self.repository_key = repository_key
        self._thread_lock = thread_lock
        self._lock_file = lock_file
        self._handle = handle
        self._released = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()

    @property
    def lock_file(self) -> Path:
        return self._lock_file

    def release(self) -> None:
        if self._released:
            return

        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._thread_lock.release()
        self._released = True


class RepositoryLockManager:
    def __init__(self, lock_dir: Path) -> None:
        self._lock_dir = lock_dir.expanduser()

    def acquire(
        self,
        repository_key: str,
        *,
        blocking: bool = True,
        timeout_seconds: float | None = None,
    ) -> RepositoryLock:
        self._lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = self._lock_dir / repository_lock_filename(repository_key)
        thread_lock = thread_lock_for(lock_file)
        if not acquire_thread_lock(
            thread_lock,
            blocking=blocking,
            timeout_seconds=timeout_seconds,
        ):
            raise RepositoryLockError(
                f"Could not acquire in-process lock for repository {repository_key!r}."
            )

        handle = lock_file.open("a+b")
        try:
            acquire_file_lock(
                handle,
                blocking=blocking,
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            handle.close()
            thread_lock.release()
            raise

        return RepositoryLock(
            repository_key=repository_key,
            thread_lock=thread_lock,
            lock_file=lock_file,
            handle=handle,
        )


def repository_lock_filename(repository_key: str) -> str:
    digest = hashlib.sha256(repository_key.encode("utf-8")).hexdigest()[:12]
    slug = repository_key.replace("/", "__").replace(":", "_")
    return f"{slug}-{digest}.lock"


def thread_lock_for(lock_file: Path) -> threading.Lock:
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(lock_file)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[lock_file] = lock
        return lock


def acquire_thread_lock(
    thread_lock: threading.Lock,
    *,
    blocking: bool,
    timeout_seconds: float | None,
) -> bool:
    if not blocking:
        return thread_lock.acquire(blocking=False)
    if timeout_seconds is None:
        thread_lock.acquire()
        return True
    return thread_lock.acquire(timeout=timeout_seconds)


def acquire_file_lock(
    handle: BinaryIO,
    *,
    blocking: bool,
    timeout_seconds: float | None,
) -> None:
    if blocking and timeout_seconds is None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return

    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError as exc:
            if not blocking:
                raise RepositoryLockError("Repository lock is already held.") from exc
            if deadline is not None and time.monotonic() >= deadline:
                raise RepositoryLockError("Timed out while waiting for repository lock.") from exc
            time.sleep(0.05)

