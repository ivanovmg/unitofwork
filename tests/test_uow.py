import copy
import uuid

from unitofwork import UnitOfWork


class Entity:
    def __init__(self) -> None:
        self.id_number = uuid.uuid4()


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
        def add(self) -> None:
            raise ValueError('Operation failed')

    entity = Entity()
    repo = FakeRepoWithFailingAdd()

    with UnitOfWork(repo) as uow:
        uow.register_operation(lambda: repo.add(entity))

    assert repo.list_all() == []
