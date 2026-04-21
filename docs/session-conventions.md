# DB Session Conventions

This project uses two session patterns with different responsibilities.

## 1) FastAPI routers and services

Use `get_session` as a dependency:

```python
from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from src.db.database import get_session

async def endpoint(session: AsyncSession = Depends(get_session)):
    ...
```

Rules:
- `get_session` owns transaction lifecycle (`commit`/`rollback`/`close`).
- Do not wrap it in `async with`.
- Treat it as request-scoped.

## 2) Bot runtime code (Discord events, commands, background tasks, views)

Use `get_async_session` explicitly:

```python
from src.db.database import get_async_session

async with get_async_session() as session:
    ...
```

Rules:
- Use this pattern anywhere outside FastAPI DI.
- Call `await session.commit()` when you want changes persisted.
- Rollback/close is handled by the context manager on error.

## 3) Helper function design

For reusable DB helpers:
- Accept `session: AsyncSession` as an argument.
- Do not create nested sessions inside helpers unless isolation is required.
- Prefer one transaction per event/command flow.

## 4) Anti-patterns to avoid

- Using `get_session` with `async with`.
- Mixing both session factories in the same flow.
- Opening a new session inside loops when one shared session is enough.
