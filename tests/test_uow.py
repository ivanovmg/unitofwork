# Copyright (c) 2025 Maxim Ivanov
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from unittest.mock import Mock

import pytest

from unitofwork import UnitOfWork


@dataclass
class Entity:
    id_number: uuid.UUID = field(init=False)

    def __post_init__(self) -> None:
        self.id_number = uuid.uuid4()


class FakeRepo:
    def __init__(self) -> None:
        self._items: dict[uuid.UUID, Entity] = {}

    def checkpoint(self) -> dict[uuid.UUID, Entity]:
        return copy.deepcopy(self._items)

    def restore(self, snapshot: dict[uuid.UUID, Entity]) -> None:
        self._items = snapshot

    def add(self, entity: Entity) -> None:
        self._items[entity.id_number] = entity

    def list_all(self) -> list[Entity]:
        return list(self._items.values())


class FailingToRestoreRepo(FakeRepo):
    def restore(self, snapshot: dict[uuid.UUID, Entity]) -> None:
        raise RuntimeError('Failed to restore')


class FailingToAddRepo(FakeRepo):
    def add(self, entity: Entity) -> None:
        raise ValueError('Failed to add')


def test_RegisterOperationOutsideContext_ExecutesImmeditely() -> None:
    entity = Entity()
    repo = FakeRepo()
    uow = UnitOfWork(repo)

    uow.register_operation(lambda: repo.add(entity))

    assert repo.list_all() == [entity]


def test_InsideContext_ExecuteOnExit() -> None:
    entity = Entity()
    repo = FakeRepo()

    with UnitOfWork(repo) as uow:
        uow.register_operation(lambda: repo.add(entity))
        assert repo.list_all() == []

    assert repo.list_all() == [entity]


def test_TransactionFailure_RepoOperationRolledBack() -> None:
    entity = Entity()
    repo = FailingToAddRepo()

    try:
        with UnitOfWork(repo) as uow:
            uow.register_operation(lambda: repo.add(entity))
    except ValueError:
        pass

    assert repo.list_all() == []


def test_TransactionFailure_BothReposOperationRolledBack() -> None:
    entity = Entity()
    good_repo = FakeRepo()
    failing_repo = FailingToAddRepo()

    try:
        with UnitOfWork(good_repo, failing_repo) as uow:
            uow.register_operation(lambda: good_repo.add(entity))
            uow.register_operation(lambda: failing_repo.add(entity))
    except ValueError:
        pass

    assert good_repo.list_all() == []
    assert failing_repo.list_all() == []


def test_SecondTransactionFailure_BothReposOperationRolledBack() -> None:
    entity = Entity()
    good_repo = FakeRepo()
    failing_repo = FailingToAddRepo()

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


def test_MultipleRepos_AutoRegistrationInContextManager() -> None:
    repo1 = FakeRepo()
    repo2 = FakeRepo()
    entity1 = Entity()
    entity2 = Entity()

    with UnitOfWork(repo1, repo2) as uow:
        uow.register_operation(lambda: repo1.add(entity1))
        uow.register_operation(lambda: repo2.add(entity2))

    assert repo1.list_all() == [entity1]
    assert repo2.list_all() == [entity2]


def test_Rollback_PreservesOriginalState() -> None:
    original_entity = Entity()
    repo = FakeRepo()
    repo.add(original_entity)

    try:
        with UnitOfWork(repo) as uow:
            uow.register_operation(lambda: repo.add(Entity()))
            uow.register_operation(lambda: repo.add(Entity()))
            raise ValueError('Force rollback')
    except ValueError:
        pass

    assert repo.list_all() == [original_entity]


def test_ManuallyRegisterRepository_Ok() -> None:
    repo = FakeRepo()
    with UnitOfWork() as uow:
        uow.register_repository(repo)
        uow.register_operation(lambda: repo.add(Entity()))
    assert len(repo.list_all()) == 1


def test_ManuallyRegisterRepository_RollbackOk() -> None:
    repo = FakeRepo()
    failing_repo = FailingToAddRepo()

    try:
        with UnitOfWork() as uow:
            uow.register_repository(repo)
            uow.register_repository(failing_repo)
            uow.register_operation(lambda: failing_repo.add(Entity()))
            uow.register_operation(lambda: repo.add(Entity()))
    except ValueError:
        pass

    assert repo.list_all() == []


def test_SkipRegistration_OperationPersistsDespiteFailure() -> None:
    """
    Test that operations on unregistered repositories execute immediately
    and persist even if the transaction fails.
    """
    repo = FakeRepo()

    uow = UnitOfWork()
    uow.register_operation(lambda: repo.add(Entity()))

    try:
        with uow:
            # Register another operation that won't execute due to failure
            uow.register_operation(lambda: repo.add(Entity()))
            raise ValueError('Transaction fails')
    except ValueError:
        pass

    assert len(repo.list_all()) == 1


def test_SkipRegistration_TransactionIsNotHandledByUnitOfWork() -> None:
    repo = FakeRepo()
    failing_repo = FailingToAddRepo()

    try:
        with UnitOfWork() as uow:
            uow.register_operation(lambda: repo.add(Entity()))
            uow.register_operation(lambda: failing_repo.add(Entity()))
    except ValueError:
        pass

    assert len(repo.list_all()) == 1


def test_ExplicitlyRaiseExceptionInContext_OperationIsNotExecuted() -> None:
    operation = Mock()

    try:
        with UnitOfWork() as uow:
            uow.register_operation(operation)
            raise RuntimeError('Operation will not be executed')
    except RuntimeError:
        pass

    operation.assert_not_called()


def test_RegisterDuplicateRepository_SkipsDuplicates() -> None:
    repo = FakeRepo()
    with UnitOfWork(repo) as uow:
        uow.register_repository(repo)  # register same repo once again OK
        uow.register_operation(lambda: repo.add(Entity()))
    assert len(repo.list_all()) == 1


def test_OperationWithReturnValue_Ok() -> None:
    def operation_with_return() -> str:
        return 'success'

    with UnitOfWork() as uow:
        uow.register_operation(operation_with_return)


def test_CommitTwice_RaisesRuntimeError() -> None:
    repo = FakeRepo()

    with UnitOfWork(repo) as uow:
        uow.register_operation(lambda: repo.add(Entity()))
        uow.commit()

        with pytest.raises(RuntimeError, match='already committed'):
            uow.commit()

    assert len(repo.list_all()) == 1


def test_RollbackAfterCommit_RaisesRuntimeError() -> None:
    repo = FakeRepo()

    with UnitOfWork(repo) as uow:
        uow.register_operation(lambda: repo.add(Entity()))
        uow.register_operation(lambda: repo.add(Entity()))
        uow.commit()

        with pytest.raises(RuntimeError, match='Cannot rollback after commit'):
            uow.rollback()

    assert len(repo.list_all()) == 2


def test_OneRepoFailsToRestoreOnRollback_GoodRepoStillRestoresOk() -> None:
    good_repo = FakeRepo()
    bad_repo = FailingToRestoreRepo()
    entity = Entity()

    good_repo.add(entity)
    bad_repo.add(entity)

    try:
        with UnitOfWork(good_repo, bad_repo) as uow:
            uow.register_operation(lambda: good_repo.add(Entity()))
            uow.register_operation(lambda: bad_repo.add(Entity()))
            raise ValueError('Force rollback')
    except ValueError:
        pass

    # Good repo should be restored despite bad repo failure
    assert good_repo.list_all() == [entity]  # Back to original state
