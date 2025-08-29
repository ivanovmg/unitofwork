# Copyright (c) 2025 Maxim Ivanov
# SPDX-License-Identifier: MIT

"""
Note: We use # type: ignore[misc] to inherit from final classes in tests.
This is a pragmatic exception for test readability
and should not be used in production code.
"""

from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import dataclass, field
from unittest.mock import Mock

import pytest

from unitofwork import RollbackError, UnitOfWork, UnitOfWorkError


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

    def commit(self) -> None:
        pass

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


class UnitOfWorkWithFailingRollback(UnitOfWork):  # type: ignore [misc]
    def rollback(self) -> None:
        raise RuntimeError('Unexpected cleanup error')


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
    except UnitOfWorkError:
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
    except UnitOfWorkError:
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
    except UnitOfWorkError:
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
    except UnitOfWorkError:
        pass

    assert len(repo.list_all()) == 1


def test_RegisterOperationAfterCommit_RaisesError() -> None:
    repo = FakeRepo()

    match = 'Cannot register operation in state.*COMMITTED'
    with pytest.raises(UnitOfWorkError, match=match):
        with UnitOfWork() as uow:
            uow.register_operation(lambda: repo.add(Entity()))
            uow.commit()
            uow.register_operation(lambda: repo.add(Entity()))

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

        match = 'Cannot commit in state.*COMMITTED'
        with pytest.raises(UnitOfWorkError, match=match):
            uow.commit()

    assert len(repo.list_all()) == 1


def test_RollbackAfterCommit_RaisesRuntimeError() -> None:
    repo = FakeRepo()

    with UnitOfWork(repo) as uow:
        uow.register_operation(lambda: repo.add(Entity()))
        uow.register_operation(lambda: repo.add(Entity()))
        uow.commit()

        match = 'Cannot rollback in state.*COMMITTED'
        with pytest.raises(UnitOfWorkError, match=match):
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
    except RollbackError:
        pass

    # Good repo should be restored despite bad repo failure
    assert good_repo.list_all() == [entity]  # Back to original state


def test_RollbackError_RaisedWhenRestorationFails() -> None:
    """Test that RollbackError is raised with failure details when restoration fails"""
    good_repo = FakeRepo()
    bad_repo = FailingToRestoreRepo()
    entity = Entity()

    good_repo.add(entity)
    bad_repo.add(entity)

    with pytest.raises(RollbackError) as exc_info:
        with UnitOfWork(good_repo, bad_repo) as uow:
            uow.register_operation(lambda: good_repo.add(Entity()))
            uow.register_operation(lambda: bad_repo.add(Entity()))
            raise ValueError('Force rollback')

    # Verify the RollbackError contains the expected information
    assert 'Failed to restore some repositories' in str(exc_info.value)

    # Verify the failure details are included
    assert len(exc_info.value.failures) == 1
    failed_repo, failure_exception = exc_info.value.failures[0]
    assert failed_repo is bad_repo
    assert isinstance(failure_exception, RuntimeError)
    assert 'Failed to restore' in str(failure_exception)

    # Verify good repo was still restored successfully
    assert good_repo.list_all() == [entity]


def test_EnterUnitOfWorkTwice_Raises() -> None:
    op = Mock()
    uow = UnitOfWork()
    with uow:
        uow.register_operation(op)
        match = 'UnitOfWork can only be entered once'
        with pytest.raises(UnitOfWorkError, match=match):
            with uow:
                uow.register_operation(op)


def test_OriginalExceptionAndCleanupError_PropagatesOriginal() -> None:
    repo = FakeRepo()
    entity = Entity()
    repo.add(entity)

    with pytest.raises(ValueError, match='Original error'):
        with UnitOfWorkWithFailingRollback(repo) as uow:
            uow.register_operation(lambda: repo.add(Entity()))
            raise ValueError('Original error')

    assert repo.list_all() == [entity]


def test_OriginalExceptionAndCleanupError_LogsCleanupError(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repo = FakeRepo()
    entity = Entity()
    repo.add(entity)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(ValueError, match='Original error'):
            with UnitOfWorkWithFailingRollback(repo) as uow:
                uow.register_operation(lambda: repo.add(Entity()))
                raise ValueError('Original error')

    assert 'Cleanup failed during exception handling' in caplog.text
    assert 'Unexpected cleanup error' in caplog.text
    assert repo.list_all() == [entity]


@pytest.mark.parametrize(
    'error_type',
    [
        RuntimeError('Runtime cleanup error'),
        ValueError('Value cleanup error'),
        OSError('IO cleanup error'),
    ],
)
def test_VariousCleanupErrorTypes_AllPropagateOriginal(
    error_type: Exception,
) -> None:
    repo = FakeRepo()
    entity = Entity()
    repo.add(entity)

    class SpecificErrorUOW(UnitOfWork):  # type: ignore [misc]
        def rollback(self) -> None:
            raise error_type

    with pytest.raises(ValueError, match='Original error'):
        with SpecificErrorUOW(repo) as uow:
            uow.register_operation(lambda: repo.add(Entity()))
            raise ValueError('Original error')

    # State should be preserved
    assert repo.list_all() == [entity]


def test_CleanupErrorWithoutOriginalException_PropagatesCleanupError() -> None:
    repo = FakeRepo()
    error_message = 'Unexpected cleanup error during commit'

    class UnitOfWorkWithFailingCommit(UnitOfWork):  # type: ignore [misc]
        def commit(self) -> None:
            raise RuntimeError(error_message)

    with pytest.raises(RuntimeError, match=error_message):
        with UnitOfWorkWithFailingCommit(repo) as uow:
            uow.register_operation(lambda: repo.add(Entity()))

    # No operations should have been committed
    assert repo.list_all() == []


def test_RollbackError_TakesPrecedenceOverOriginalException() -> None:
    repo = FailingToRestoreRepo()  # raises RollbackError during rollback
    entity = Entity()
    repo.add(entity)

    with pytest.raises(RollbackError) as exc_info:
        with UnitOfWork(repo) as uow:
            uow.register_operation(lambda: repo.add(Entity()))
            raise ValueError('Original error')

    # Verify it's a RollbackError, not the original ValueError
    assert 'Failed to restore some repositories' in str(exc_info.value)


def test_FailedSnapshot_LogsWarning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingSnapshotRepo(FakeRepo):
        def checkpoint(self) -> dict[uuid.UUID, Entity]:
            raise RuntimeError('Snapshot failed')

    good_repo = FakeRepo()
    failing_repo = FailingSnapshotRepo()

    try:
        with UnitOfWork(good_repo, failing_repo) as uow:
            uow.register_operation(lambda: good_repo.add(Entity()))
            uow.register_operation(lambda: failing_repo.add(Entity()))
            raise ValueError('Force rollback')
    except ValueError:
        pass

    # Verify warning was logged for failed snapshot
    assert 'Failed to take snapshot for repository' in caplog.text
    assert 'Snapshot failed' in caplog.text


def test_SuccessfulSnapshots_NoWarningsLogged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repo1 = FakeRepo()
    repo2 = FakeRepo()

    with caplog.at_level(logging.WARNING):
        with UnitOfWork(repo1, repo2) as uow:
            uow.register_operation(lambda: repo1.add(Entity()))
            uow.register_operation(lambda: repo2.add(Entity()))

    assert not caplog.text


def test_ManualRollback() -> None:
    first_repo = FakeRepo()
    second_repo = FakeRepo()

    with UnitOfWork(first_repo, second_repo) as uow:
        uow.register_operation(lambda: first_repo.add(Entity()))
        uow.register_operation(lambda: second_repo.add(Entity()))
        if True:  # some condition to trigger manual rollback
            uow.rollback()

    assert first_repo.list_all() == []
    assert second_repo.list_all() == []
