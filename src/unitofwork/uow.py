# Copyright (c) 2025 Maxim Ivanov
# SPDX-License-Identifier: MIT

from collections.abc import Callable
from types import TracebackType
from typing import Any, Literal

from .interfaces import SupportsRollback


__all__ = [
    'UnitOfWork',
]


class UnitOfWork:
    def __init__(self, *repositories: SupportsRollback[Any, Any]):
        self._operations: list[Callable[[], Any]] = []
        self._snapshots: list[tuple[SupportsRollback[Any, Any], Any]] = []
        self._in_context: bool = False
        self._committed: bool = False
        self._repositories = repositories

    def register_operation(self, operation: Callable[[], Any]) -> None:
        """
        Register an operation to be executed atomically.
        """
        if not self._in_context:
            operation()
        else:
            self._operations.append(operation)

    def register_repository(self, repo: SupportsRollback[Any, Any]) -> None:
        """
        Register a repository for state tracking (optional manual registration).
        """
        for existing_repo, _ in self._snapshots:
            if existing_repo is repo:
                return

        snapshot = repo.checkpoint()
        self._snapshots.append((repo, snapshot))

    def _auto_register_repositories(self) -> None:
        """Automatically register all repositories provided in constructor."""
        for repo in self._repositories:
            self.register_repository(repo)

    def commit(self) -> None:
        if self._committed:
            raise RuntimeError('UnitOfWork already committed')

        try:
            self._commit()
        except Exception as e:
            self.rollback()
            raise e

    def _commit(self) -> None:
        for operation in self._operations:
            operation()

        for repo, _ in self._snapshots:
            repo.commit()

        self._committed = True
        self._operations.clear()
        self._snapshots.clear()

    def rollback(self) -> None:
        if self._committed:
            raise RuntimeError('Cannot rollback after commit')

        for repo, snapshot in self._snapshots:
            try:
                repo.restore(snapshot)
            except Exception:
                continue

        self._operations.clear()
        self._snapshots.clear()
        self._committed = False

    def __enter__(self) -> 'UnitOfWork':
        self._in_context = True
        self._auto_register_repositories()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Literal[False]:
        self._in_context = False

        if exc_type is not None:
            self.rollback()
            return False

        if not self._committed:
            self.commit()

        return False
