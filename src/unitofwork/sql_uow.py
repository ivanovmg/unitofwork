# Copyright (c) 2025 Maxim Ivanov
# SPDX-License-Identifier: MIT

from __future__ import annotations

import logging
from typing import Any, Protocol

from .uow import UnitOfWork


__all__ = [
    'SqlUnitOfWork',
]


logger = logging.getLogger(__name__)


class Connection(Protocol):
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def in_transaction(self) -> bool: ...
    def begin(self) -> Any: ...


class SqlUnitOfWork:
    """Decorator that wraps UnitOfWork to manage database connection transactions"""

    def __init__(
        self,
        base_uow: UnitOfWork,
        connection: Connection,
    ) -> None:
        self._base_uow = base_uow
        self._connection = connection
        self._should_commit = False

    def register_operation(self, operation) -> None:
        return self._base_uow.register_operation(operation)

    def __enter__(self) -> SqlUnitOfWork:
        if not self._connection.in_transaction():
            self._connection.begin()
            self._should_commit = True
        else:
            self._should_commit = False

        self._base_uow.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        base_exception = None

        try:
            result = self._base_uow.__exit__(exc_type, exc_val, exc_tb)
        except Exception as exc:
            # Store the exception to re-raise later
            base_exception = exc
            result = False

        # Handle transaction based on both the original exception AND base_uow failure
        if self._should_commit:
            self._commit(exc_type, base_exception)

        # If base_uow.__exit__ raised an exception, re-raise it
        if base_exception is not None:
            raise base_exception

        return result

    def _commit(self, exc_type, base_exception):
        if exc_type is not None or base_exception is not None:
            # Either the original operation failed OR base_uow.__exit__ failed - rollback
            try:
                self._connection.rollback()
            except Exception as exc:
                logger.error(
                    'Failed to rollback database transaction in SqlUnitOfWork: %s',
                    exc,
                    extra={
                        'base_exception': str(base_exception)
                        if base_exception
                        else None
                    },
                )
        else:
            # Everything succeeded - commit
            self._connection.commit()
