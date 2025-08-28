# Copyright (c) 2025 Maxim Ivanov
# SPDX-License-Identifier: MIT

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from enum import Enum, auto
from types import TracebackType
from typing import Any, Literal, final

from .interfaces import SupportsRollback


__all__ = [
    'RollbackError',
    'UnitOfWork',
    'UnitOfWorkError',
]

logger = logging.getLogger(__name__)


class UnitOfWorkState(Enum):
    INITIAL = auto()
    IN_PROGRESS = auto()
    COMMITTED = auto()
    ROLLED_BACK = auto()


class UnitOfWorkError(Exception):
    """Base exception for UnitOfWork errors"""

    pass


class RollbackError(UnitOfWorkError):
    """Exception raised when rollback fails"""

    def __init__(
        self, message: str, failures: list[tuple[SupportsRollback, Exception]]
    ):
        super().__init__(message)
        self.failures = failures


@final
class UnitOfWork(AbstractContextManager['UnitOfWork']):
    def __init__(self, *repositories: SupportsRollback):
        self._operations: list[Callable[[], Any]] = []
        self._snapshots: list[tuple[SupportsRollback, Any]] = []
        self._state = UnitOfWorkState.INITIAL
        self._repositories = repositories

    def register_operation(self, operation: Callable[[], Any]) -> None:
        if self._state in (
            UnitOfWorkState.COMMITTED,
            UnitOfWorkState.ROLLED_BACK,
        ):
            raise UnitOfWorkError(
                f'Cannot register operation in state: {self._state}'
            )

        if self._state == UnitOfWorkState.INITIAL:
            operation()
        else:
            self._operations.append(operation)

    def _take_snapshots(self) -> None:
        """Take snapshots of all repositories"""
        self._snapshots.clear()
        for repo in self._repositories:
            try:
                snapshot = repo.checkpoint()
                self._snapshots.append((repo, snapshot))
            except Exception as e:
                logger.warning(
                    'Failed to take snapshot for repository %s: %s', repo, e
                )

    def commit(self) -> None:
        if self._state != UnitOfWorkState.IN_PROGRESS:
            raise UnitOfWorkError(f'Cannot commit in state: {self._state}')

        try:
            for operation in self._operations:
                operation()

            for repo, _ in self._snapshots:
                repo.commit()

            self._state = UnitOfWorkState.COMMITTED
            self._cleanup()

        except Exception as e:
            self.rollback()
            raise UnitOfWorkError('Commit failed, rolled back') from e

    def rollback(self) -> None:
        if self._state != UnitOfWorkState.IN_PROGRESS:
            raise UnitOfWorkError(f'Cannot rollback in state: {self._state}')

        failures: list[tuple[SupportsRollback, Exception]] = []
        for repo, snapshot in self._snapshots:
            try:
                repo.restore(snapshot)
            except Exception as e:
                failures.append((repo, e))
                logger.error('Failed to restore repository %s: %s', repo, e)

        self._state = UnitOfWorkState.ROLLED_BACK
        self._cleanup()

        if failures:
            raise RollbackError(
                'Failed to restore some repositories', failures
            )

    def _cleanup(self) -> None:
        """Clean up internal state"""
        self._operations.clear()
        self._snapshots.clear()

    def __enter__(self) -> UnitOfWork:
        if self._state != UnitOfWorkState.INITIAL:
            raise UnitOfWorkError('UnitOfWork can only be entered once')

        self._state = UnitOfWorkState.IN_PROGRESS
        self._take_snapshots()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Literal[False]:
        cleanup_error = None

        try:
            if exc_type is not None:
                if self._state == UnitOfWorkState.IN_PROGRESS:
                    self.rollback()
            elif self._state == UnitOfWorkState.IN_PROGRESS:
                self.commit()
        except Exception as e:
            logger.error('Error during UnitOfWork cleanup: %s', e)
            cleanup_error = e

        # If rollback failed with RollbackError, that should take precedence
        # over the original exception
        if isinstance(cleanup_error, RollbackError):
            raise cleanup_error from exc_val

        # If there was both an original exception and a different cleanup error,
        # log the cleanup error but don't mask the original exception
        if exc_type is not None and cleanup_error is not None:
            logger.error(
                'Cleanup failed during exception handling: %s', cleanup_error
            )
            return False

        # If there was only a cleanup error (no original exception), re-raise it
        if cleanup_error is not None:
            raise cleanup_error

        return False
