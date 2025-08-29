# Copyright (c) 2025 Maxim Ivanov
# SPDX-License-Identifier: MIT

from typing import Any, Protocol


__all__ = [
    'SupportsRollback',
]


class SupportsRollback(Protocol):
    """Protocol for repositories that support rollback functionality"""

    def checkpoint(self) -> Any:
        """Return a snapshot of the current state."""
        pass

    def restore(self, snapshot: Any) -> None:
        """Restore state from a previously taken snapshot."""
        pass

    def commit(self) -> None:
        """Commit transaction, used in UnitOfWork."""
        pass
