# Copyright (c) 2025 Maxim Ivanov
# SPDX-License-Identifier: MIT

from collections.abc import Iterable
from typing import Any
from unittest import mock
from uuid import uuid4

import pytest
import sqlalchemy
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, row

from unitofwork import SqlUnitOfWork, UnitOfWork, UnitOfWorkError


@pytest.fixture
def in_memory_db() -> Iterable[Connection]:
    """Create in-memory SQLite database for testing"""
    engine = create_engine('sqlite:///:memory:')
    with engine.connect() as conn:
        conn.execute(
            text("""
            CREATE TABLE test_table (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )
        """)
        )
        conn.commit()

        # Ensure we start with clean transaction state
        if conn.in_transaction():
            conn.rollback()

        yield conn
        conn.rollback()


class SqlRepositoryUnderTest:
    def __init__(self, connection: Connection) -> None:
        self.conn = connection
        self._savepoint: str | None = None

    def checkpoint(self) -> str:
        """Create a database savepoint"""
        if not self.conn.in_transaction():
            self.conn.begin()
        self._savepoint = f'savepoint_{id(self)}'
        statement = sqlalchemy.text(f'SAVEPOINT {self._savepoint}')
        self.conn.execute(statement)
        return self._savepoint

    def restore(self, savepoint: str) -> None:
        """Rollback to savepoint"""
        if not self._savepoint or savepoint != self._savepoint:
            return

        try:
            statement = sqlalchemy.text(f'ROLLBACK TO SAVEPOINT {savepoint}')
            self.conn.execute(statement)
        except sqlalchemy.exc.OperationalError as e:
            if 'no such savepoint' in str(e).lower():
                # Savepoint was already released (maybe automatically by SQLite)
                # This is OK - means work was already committed
                pass
            else:
                raise

    def commit(self) -> None:
        """Release savepoint"""
        self._release_savepoint()

    def _release_savepoint(self):
        if self._savepoint:
            try:
                self.conn.execute(
                    sqlalchemy.text(f'RELEASE SAVEPOINT {self._savepoint}')
                )
            except Exception as err:
                print(f'Error releasing savepoint: {err}')
            self._savepoint = None

    def insert_record(self, record_id: str, name: str) -> None:
        self.conn.execute(
            text('INSERT INTO test_table (id, name) VALUES (:id, :name)'),
            {'id': record_id, 'name': name},
        )

    def get_by_id(self, record_id: str) -> row.Row[Any] | None:
        return self.conn.execute(
            text('SELECT id, name FROM test_table WHERE id = :id'),
            {'id': record_id},
        ).fetchone()


def test_OneTransactionAddRecord_Ok(in_memory_db: Connection) -> None:
    good_repo = SqlRepositoryUnderTest(in_memory_db)
    id1 = str(uuid4())

    with SqlUnitOfWork(UnitOfWork(good_repo), in_memory_db) as uow:
        uow.register_operation(lambda: good_repo.insert_record(id1, 'first'))

    item = good_repo.get_by_id(id1)
    assert item is not None
    assert item.id == id1
    assert item.name == 'first'


def test_OneTransactionFails_RollbackOk(in_memory_db: Connection) -> None:
    class BrokenRepo(SqlRepositoryUnderTest):
        def insert_record(self, record_id: str, name: str) -> None:
            raise RuntimeError('Something happened')

    good_repo = SqlRepositoryUnderTest(in_memory_db)
    broken_repo = BrokenRepo(in_memory_db)
    id1 = str(uuid4())
    with UnitOfWork(good_repo) as uow:
        uow.register_operation(lambda: good_repo.insert_record(id1, 'first'))

    id2 = str(uuid4())
    id3 = str(uuid4())
    with pytest.raises(UnitOfWorkError, match='Commit failed, rolled back'):
        with SqlUnitOfWork(
            UnitOfWork(good_repo, broken_repo),
            connection=in_memory_db,
        ) as uow:
            uow.register_operation(
                lambda: broken_repo.insert_record(id3, 'bad')
            )
            uow.register_operation(
                lambda: good_repo.insert_record(id2, 'good')
            )

    assert good_repo.get_by_id(id1) is not None
    assert good_repo.get_by_id(id2) is None
    assert broken_repo.get_by_id(id3) is None


def test_OneTransactionFailsWithoutExplicitReleaseSavepoint_RollbackOk(
    in_memory_db: Connection,
) -> None:
    class RepoWithNoOpReleaseSavepoint(SqlRepositoryUnderTest):
        def _release_savepoint(self) -> None:
            pass

    class BrokenRepo(SqlRepositoryUnderTest):
        def insert_record(self, record_id: str, name: str) -> None:
            raise RuntimeError('Something happened')

    good_repo = RepoWithNoOpReleaseSavepoint(in_memory_db)
    broken_repo = BrokenRepo(in_memory_db)
    id1 = str(uuid4())
    with UnitOfWork(good_repo) as uow:
        uow.register_operation(lambda: good_repo.insert_record(id1, 'first'))

    id2 = str(uuid4())
    id3 = str(uuid4())
    with pytest.raises(UnitOfWorkError, match='Commit failed, rolled back'):
        with SqlUnitOfWork(
            UnitOfWork(good_repo, broken_repo),
            connection=in_memory_db,
        ) as uow:
            uow.register_operation(
                lambda: broken_repo.insert_record(id3, 'bad')
            )
            uow.register_operation(
                lambda: good_repo.insert_record(id2, 'good')
            )

    assert good_repo.get_by_id(id1) is not None
    assert good_repo.get_by_id(id2) is None
    assert broken_repo.get_by_id(id3) is None


def test_BaseUoWExceptionOnExit_Rollback(in_memory_db: Connection) -> None:
    class FailingUnitOfWork(UnitOfWork):
        def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
            raise UnitOfWorkError('Base UoW failed')

    repo = SqlRepositoryUnderTest(in_memory_db)
    with pytest.raises(UnitOfWorkError, match='Base UoW failed'):
        with SqlUnitOfWork(
            FailingUnitOfWork(repo),
            in_memory_db,
        ) as uow:
            uow.register_operation(lambda: repo.insert_record('id1', 'item'))

    assert repo.get_by_id('id1') is None


def test_OriginalException_Rollback(in_memory_db: Connection) -> None:
    # Simulate the scenario where base_uow.__exit__ doesn't raise an exception
    # but there was an original exception that caused us to enter this path
    repo = SqlRepositoryUnderTest(in_memory_db)
    with pytest.raises(RuntimeError, match='Original error'):
        with SqlUnitOfWork(UnitOfWork(repo), in_memory_db) as uow:
            uow.register_operation(lambda: repo.insert_record('id1', 'item'))
            raise RuntimeError('Original error')

    assert repo.get_by_id('id1') is None


class FailingRollbackConnection:
    """Wrapper that makes rollback fail"""

    def __init__(self, real_connection: Connection):
        self._conn = real_connection
        self.rollback_called = False

    def __getattr__(self, name):
        # Delegate all undefined attributes/methods to the real connection
        return getattr(self._conn, name)

    def rollback(self):
        self.rollback_called = True
        raise RuntimeError('Rollback failed')

    def __eq__(self, other):
        return self._conn == other

    def __repr__(self):
        return f'FailingRollbackConnection({self._conn!r})'


def test_RollbackFailure_HandlesGracefully(in_memory_db: Connection) -> None:
    class FailingUnitOfWork(UnitOfWork):
        def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
            raise UnitOfWorkError('Base UoW cleanup failed')

    connection = FailingRollbackConnection(in_memory_db)
    repo = SqlRepositoryUnderTest(connection)
    with pytest.raises(UnitOfWorkError, match='Base UoW cleanup failed'):
        with SqlUnitOfWork(FailingUnitOfWork(repo), connection):
            pass

    assert connection.rollback_called


def test_CommitActuallyHappensWithoutRollback(
    in_memory_db: Connection,
) -> None:
    """Test that commit is called when everything succeeds"""
    repo = SqlRepositoryUnderTest(in_memory_db)

    with mock.patch.object(in_memory_db, 'commit') as mock_commit:
        with mock.patch.object(in_memory_db, 'rollback') as mock_rollback:
            with SqlUnitOfWork(UnitOfWork(repo), in_memory_db) as uow:
                uow.register_operation(
                    lambda: repo.insert_record('test', 'item')
                )

            mock_commit.assert_called_once()
            mock_rollback.assert_not_called()
