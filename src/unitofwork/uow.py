from copy import deepcopy
from types import TracebackType
from typing import Any, Callable, Iterable, List, Optional, Tuple, Union

from .interfaces import SupportsRollback

__all__ = [
    'UnitOfWork',
]


class UnitOfWork:
    def __init__(self, *repositories: SupportsRollback):
        self._operations: List[Callable[[], Any]] = []
        self._snapshots: List[Tuple[SupportsRollback, Any]] = []
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

    def register_repository(self, repo: SupportsRollback) -> None:
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
            for operation in self._operations:
                operation()

            self._committed = True
            self._clear()

        except Exception as e:
            self.rollback()
            raise e

    def rollback(self) -> None:
        for repo, snapshot in self._snapshots:
            try:
                repo.restore(snapshot)
            except Exception:
                continue  # Continue rolling back despite individual failures

        self._clear()

    def _clear(self) -> None:
        self._operations.clear()
        self._snapshots.clear()
        self._committed = False

    def __enter__(self) -> 'UnitOfWork':
        self._in_context = True
        self._auto_register_repositories()  # Auto-register on context entry
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> bool:
        self._in_context = False

        if exc_type is not None:
            self.rollback()
            return False

        if not self._committed:
            self.commit()

        return False
