# Copyright (c) 2025 Maxim Ivanov
# SPDX-License-Identifier: MIT

import logging

from .interfaces import SupportsRollback
from .sql_uow import SqlUnitOfWork
from .uow import RollbackError, UnitOfWork, UnitOfWorkError


# Set up null handler for the library's logger
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


__all__ = [
    'RollbackError',
    'SqlUnitOfWork',
    'SupportsRollback',
    'UnitOfWork',
    'UnitOfWorkError',
]
