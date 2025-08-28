# Copyright (c) 2025 Maxim Ivanov
# SPDX-License-Identifier: MIT

import logging

from .uow import RollbackError, UnitOfWork, UnitOfWorkError


# Set up null handler for the library's logger
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


__all__ = [
    'RollbackError',
    'UnitOfWork',
    'UnitOfWorkError',
]
