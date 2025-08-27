from __future__ import annotations

import copy
import uuid

import pytest

from unitofwork import UnitOfWork


class Entity:
    def __init__(self) -> None:
        self.id_number = uuid.uuid4()

    def __eq__(self, other: Entity) -> bool:
        if not isinstance(other, Entity):
            return NotImplemented
        return self.id_number == other.id_number


class FakeRepo:
    def __init__(self) -> None:
        self._items: dict[str, Entity] = {}

    def checkpoint(self) -> dict[str, Entity]:
        return copy.deepcopy(self._items)

    def restore(self, snapshot: dict[str, Entity]) -> None:
        self._items = snapshot

    def add(self, entity: Entity) -> None:
        self._items[entity.id_number] = entity

    def list_all(self) -> list[Entity]:
        return list(self._items.values())


def test_InsideContext_ExecuteOnExit() -> None:
    entity = Entity()
    repo = FakeRepo()

    with UnitOfWork(repo) as uow:
        uow.register_operation(lambda: repo.add(entity))
        assert repo.list_all() == []

    assert repo.list_all() == [entity]


def test_TransactionFailure_RepoOperationRolledBack() -> None:
    class FakeRepoWithFailingAdd(FakeRepo):
        def add(self, entity: Entity) -> None:
            raise ValueError('Operation failed')

    entity = Entity()
    repo = FakeRepoWithFailingAdd()

    try:
        with UnitOfWork(repo) as uow:
            uow.register_operation(lambda: repo.add(entity))
    except ValueError:
        pass

    assert repo.list_all() == []


def test_TransactionFailure_BothReposOperationRolledBack() -> None:
    class FakeRepoWithFailingAdd(FakeRepo):
        def add(self, entity: Entity) -> None:
            raise ValueError('Operation failed')

    entity = Entity()
    good_repo = FakeRepo()
    failing_repo = FakeRepoWithFailingAdd()

    try:
        with UnitOfWork(good_repo, failing_repo) as uow:
            uow.register_operation(lambda: good_repo.add(entity))
            uow.register_operation(lambda: failing_repo.add(entity))
    except ValueError:
        pass

    assert good_repo.list_all() == []
    assert failing_repo.list_all() == []


def test_SecondTransactionFailure_BothReposOperationRolledBack() -> None:
    class FakeRepoWithFailingAdd(FakeRepo):
        def add(self, entity: Entity) -> None:
            raise ValueError('Operation failed')

    entity = Entity()
    good_repo = FakeRepo()
    failing_repo = FakeRepoWithFailingAdd()

    with UnitOfWork(good_repo) as uow:
        uow.register_operation(lambda: good_repo.add(entity))

    assert good_repo.list_all() == [entity]

    try:
        with UnitOfWork(good_repo, failing_repo) as uow:
            uow.register_operation(lambda: good_repo.add(Entity()))
            uow.register_operation(lambda: failing_repo.add(Entity()))
    except ValueError:
        pass

    assert good_repo.list_all() == [entity]
    assert failing_repo.list_all() == []
