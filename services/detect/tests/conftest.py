import os
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

import detect.main as main_module
from detect.main import app, get_db


@pytest.fixture
def client(tmp_path):
    db_url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    @asynccontextmanager
    async def mock_lifespan(_app):
        main_module._engine = engine
        yield

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    with patch.object(app.router, "lifespan_context", mock_lifespan):
        with TestClient(app) as c:
            yield c, engine

    app.dependency_overrides.clear()
