from abc import abstractmethod
from typing import Generic, Protocol, TypeVar


ID = TypeVar('ID')
T = TypeVar('T')


class SupportsRollback(Protocol, Generic[ID, T]):
    """Protocol for repositories that support rollback functionality"""

    @abstractmethod
    def checkpoint(self) -> dict[ID, T]:
        """Return a snapshot of the current state"""
        pass

    @abstractmethod
    def restore(self, snapshot: dict[ID, T]) -> None:
        """Restore state from a previously taken snapshot"""
        pass
