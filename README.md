# unitofwork

A lightweight, database-agnostic implementation of the Unit of Work pattern for Python applications.
Designed for clean architecture, type safety, and atomic transactions across mixed repository types.

## Features

- Atomic Transactions: Ensure all operations succeed or fail together
- Mixed Repository Support: Works with SQL, in-memory, file-based, and custom repositories
- Type Safety: Full mypy support with generics and protocols
- Simple API: Intuitive context manager interface
- No Dependencies: Pure Python implementation
- Comprehensive Testing: 100% test coverage with extensive test suite
- Rollback Support: Automatic rollback for in-memory repositories
- Protocol-Based: Uses structural typing with `SupportsRollback` interface

## Installation

``` bash
$ pip install unitofwork
```

## Quick Start

``` python
import copy
from dataclasses import dataclass
from uuid import UUID, uuid4

from unitofwork import UnitOfWork

# Your repositories must implement the SupportsRollback interface
class InMemoryUserRepository:
    def __init__(self):
        self._users: dict[UUID, User] = {}
        self._snapshots: list[dict[UUID, User]] = []

    def checkpoint(self) -> dict[UUID, User]:
        snapshot = copy.deepcopy(self._users)
        self._snapshots.append(snapshot)
        return snapshot

    def restore(self, snapshot: dict[UUID, User]) -> None:
        self._users = snapshot

    def commit(self) -> None:
        self._snapshots.clear()

    def add(self, user: User) -> None:
        self._users[user.id] = user

@dataclass
class User:
    id: UUID
    name: str
    email: str

# Create repository that follows SupportsRollback interface
user_repo = InMemoryUserRepository()

# Atomic transaction
with UnitOfWork(user_repo) as uow:
    user = User(uuid4(), "Alice", "alice@example.com")
    uow.register_operation(lambda: user_repo.add(user))

# Operation is committed automatically on successful exit
```

## SupportsRollback interface

All repositories must implement three essential methods:

``` python
from typing import Any, Protocol

class SupportsRollback(Protocol):
    """Protocol that all repositories must follow to work with UnitOfWork"""
    
    def checkpoint(self) -> Any:
        """Return a snapshot of the current state for potential rollback"""
        ...
    
    def restore(self, snapshot: Any) -> None:
        """Restore state from a previously taken snapshot"""
        ...
    
    def commit(self) -> None:
        """Finalize the transaction after successful operations"""
        ...
```

### Implementing the interface

#### In-memory repository example

For in-memory repo we simply make a deep copy of the repo content
before the transaction (``checkpoint``).
On failure we can `restore` using this deep copy of the repo content
as shown below:

``` python
class InMemoryRepository:
    def __init__(self):
        self._data = {}
        self._snapshots = []
    
    def checkpoint(self) -> dict:
        return copy.deepcopy(self._data)
    
    def restore(self, snapshot: dict) -> None:
        self._data = snapshot
    
    def commit(self) -> None:
        self._snapshots.clear()
```

#### SQL repository example

In case of an SQL repository,
we can use [SAVEPOINT](https://www.sqltutorial.net/savepoint.html)
to save the transaction checkpoint.
It allows us to ``ROLLBACK to SAVEPOINT`` if the transaction fails.

``` python
from sqlalchemy.engine import Connection

# Example: SQLAlchemy repository
class SQLUserRepository:
    def __init__(self, connection: Connection):
        self.conn = connection
        self._savepoint = None
    
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
        if self._savepoint:
            try:
                self.conn.execute(
                    sqlalchemy.text(f'RELEASE SAVEPOINT {self._savepoint}')
                )
            except Exception as err:
                print(f'Error releasing savepoint: {err}')
            self._savepoint = None
```

## Why Unit of Work?

The Unit of Work pattern maintains a list of objects affected by a business transaction
and coordinates the writing out of changes and the resolution of concurrency problems.

### Without Unit of Work

``` python
# Risk: Partial failures
user_repo.add(user)        # Success
product_repo.add(product)  # Failure - database error
# Now user exists but product doesn't - inconsistent state, not OK!
```

### With Unit of Work

``` python
# Safe: Atomic operations
with UnitOfWork(user_repo, product_repo) as uow:
    uow.register_operation(lambda: user_repo.add(user))
    uow.register_operation(lambda: product_repo.add(product))
# Both succeed or both fail - guaranteed consistency, now it's OK!
```

## Usage Guide

### Basic Usage

``` python
from unitofwork import UnitOfWork

# Create repository with custom ID field
class Product:
    def __init__(self, sku: str, name: str, price: float):
        self.sku = sku
        self.name = name
        self.price = price

product_repo = InMemoryRepository[str, Product](id_field="sku")

# Simple transaction
with UnitOfWork(product_repo) as uow:
    uow.register_operation(
        lambda: product_repo.add(
            Product("laptop-123", "Premium Laptop", 1299.99),
        ),
    )
```

### Mixed Repository Types

Provided you have multiple repositories
implementing `SupportsRollback` interface,
the same `UnitOfWork` pattern can be applied to all of them.

``` python
from unitofwork import SqlUnitOfWork, UnitOfWork
from your_app.repositories import SQLUserRepository, FileLogRepository

# Mix different repository types
sql_user_repo = SQLUserRepository(connection)
in_memory_cache = InMemoryRepository[str, CachedData](id_field="key")
file_log_repo = FileLogRepository("/path/to/logs")

with SqlUnitOfWork(  # use for SQL-involved operations
    UnitOfWork(sql_user_repo, in_memory_cache, file_log_repo),
    connection,
) as uow:
    uow.register_operation(lambda: sql_user_repo.add_user(new_user))
    uow.register_operation(lambda: in_memory_cache.add(cached_data))
    uow.register_operation(lambda: file_log_repo.log_operation("user_created"))
```

### Custom Repositories

``` python
from typing import Dict, Any
from unitofwork import SupportsRollback

class CustomRepository(SupportsRollback[str, str]):
    def __init__(self):
        self._data: Dict[str, str] = {}
    
    def checkpoint(self) -> Dict[str, str]:
        return self._data.copy()
    
    def restore(self, snapshot: Dict[str, str]) -> None:
        self._data = snapshot
    
    def add(self, key: str, value: str) -> None:
        self._data[key] = value
    
    def get(self, key: str) -> str:
        return self._data[key]

# Use your custom repository
custom_repo = CustomRepository()
with UnitOfWork(custom_repo) as uow:
    uow.register_operation(lambda: custom_repo.add("test_key", "test_value"))
```

### Error handling

``` python
try:
    with UnitOfWork(user_repo, order_repo) as uow:
        uow.register_operation(lambda: user_repo.add(user))
        uow.register_operation(lambda: order_repo.add(order))
        
        # Simulate business rule violation
        if not user.can_purchase():
            raise ValueError("User cannot make purchase")
            
except ValueError as e:
    print(f"Transaction failed: {e}")
    # Both user_repo and order_repo are automatically rolled back!
```

## Architecture

### Core Components

- `UnitOfWork`: Main coordinator class managing transactions
- `SupportsRollback`: Protocol defining repository interface
- `UnitOfWorkError`: Base exception for `UnitOfWork` errors
- `RollbackError`: Exception raised when rollback fails partially

### Design Principles

- Database Agnostic: Works with any persistence mechanism
- Type Safe: Full static type checking support
- Minimal API: Simple, intuitive interface
- Extensible: Easy to adapt existing repositories
- Thread Safe: Designed for concurrent usage

### Key Principle: Structural Typing
Your repositories do not need to inherit from SupportsRollback ---
they just need to implement:

``` python
checkpoint() -> Any
restore(snapshot: Any) -> None
commit() -> None
```

This enables seamless integration with any persistence mechanism,
provided it allows for creating a checkpoint and makes it technically possible
to revert to this checkpoint.

## Advanced Usage

### Manual Rollback

``` python
with UnitOfWork(user_repo, product_repo) as uow:
    # These will commit if no exception
    uow.register_operation(lambda: user_repo.add(user))
    uow.register_operation(lambda: product_repo.add(product))
    
    # Manual rollback if needed
    if some_condition:
        uow.rollback()
        # Additional cleanup...
```

## Acknowledgements

- Inspired by Domain-Driven Design patterns
- Based on concepts from ["Architecture Patterns with Python"](https://www.cosmicpython.com)
- Built with type safety and reliability as first-class citizens
