# Copyright (c) 2025 Maxim Ivanov
# SPDX-License-Identifier: MIT

from __future__ import annotations

import logging
from typing import Protocol

from .uow import UnitOfWork


__all__ = [
    'SqlUnitOfWork',
]


logger = logging.getLogger(__name__)


class Connection(Protocol):
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class SqlUnitOfWork:
    """Decorator that wraps UnitOfWork to manage database connection transactions"""

    def __init__(
        self,
        base_uow: UnitOfWork,
        connection: Connection,
    ) -> None:
        self._base_uow = base_uow
        self._connection = connection

    def register_operation(self, operation) -> None:
        return self._base_uow.register_operation(operation)

    def __enter__(self) -> SqlUnitOfWork:
        self._base_uow.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        try:
            result = self._base_uow.__exit__(exc_type, exc_val, exc_tb)

            # Manage the actual database transaction
            if exc_type is not None:
                self._connection.rollback()
            else:
                self._connection.commit()

            return result
        except Exception as exc:
            logger.exception(
                'Error during SqlUnitOfWork cleanup: %s',
                exc,
            )
            logger.error(
                'Attempting to rollback database transaction as fallback'
            )
            try:
                self._connection.rollback()
            except Exception as rollback_error:
                logger.error(
                    'Failed to rollback database transaction: %s',
                    rollback_error,
                )
            raise
