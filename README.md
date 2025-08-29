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

## Installation (PENDING)

``` bash
$ pip install unitofwork
```

## Quick Start

``` python
import copy
from dataclasses import dataclass
from typing import TypeVar

from unitofwork import UnitOfWork

@dataclass(frozen=True)
class User:
    id: int
    name: str
    email: str

@dataclass(frozen=True)
class Product:
    sku: str
    title: str
    price: float

ID = TypeVar('ID')
T = TypeVar('T')

class InMemoryRepository[ID, T]:
    """In-memory repository implementation with rollback support."""

    def __init__(self, id_field: str = 'id'):
        self._data: dict[ID, T] = {}
        self._id_field = id_field
        self._snapshots: list[dict[ID, T]] = []

    def checkpoint(self) -> dict[ID, T]:
        """Create a deep copy snapshot of current data."""
        snapshot = copy.deepcopy(self._data)
        self._snapshots.append(snapshot)
        return snapshot

    def restore(self, snapshot: dict[ID, T]) -> None:
        """Restore data from snapshot."""
        self._data = copy.deepcopy(snapshot)

    def commit(self) -> None:
        """Clear snapshots after successful commit."""
        self._snapshots.clear()

    def add(self, entity: T) -> None:
        """Add an entity to the repository."""
        entity_id = getattr(entity, self._id_field)
        if entity_id in self._data:
            raise ValueError(f'Entity with ID {entity_id} already exists')
        self._data[entity_id] = entity


# Create repositories
user_repo = InMemoryRepository[int, User](id_field='id')
product_repo = InMemoryRepository[str, Product](id_field='sku')

# Atomic transaction across multiple repositories
with UnitOfWork(user_repo, product_repo) as uow:
    uow.register_operation(lambda: user_repo.add(User(1, 'Alice', 'alice@example.com')))
    uow.register_operation(lambda: product_repo.add(Product('laptop-123', 'Laptop', 999.99)))
# Both operations commit together or roll back together!
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
from unitofwork import UnitOfWork, InMemoryRepository

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

``` python
from unitofwork import UnitOfWork, InMemoryRepository, SupportsRollback
from sqlalchemy.orm import Session
from your_app.repositories import SQLUserRepository, FileLogRepository

# Mix different repository types
sql_user_repo = SQLUserRepository(session)
in_memory_cache = InMemoryRepository[str, CachedData](id_field="key")
file_log_repo = FileLogRepository("/path/to/logs")

with UnitOfWork(sql_user_repo, in_memory_cache, file_log_repo) as uow:
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

Core Components
- `UnitOfWork`: Main coordinator class managing transactions
- `SupportsRollback`: Protocol defining repository interface
- `InMemoryRepository`: Reference implementation with rollback support

Design Principles
- Database Agnostic: Works with any persistence mechanism
- Type Safe: Full static type checking support
- Minimal API: Simple, intuitive interface
- Extensible: Easy to adapt existing repositories
- Thread Safe: Designed for concurrent usage

## Advanced Usage

### Partial Rollback

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
