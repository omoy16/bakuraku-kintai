"""Isolated PostgreSQL API fixtures. Never use a development database implicitly."""

import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.dependencies import get_db_engine
from app.main import create_app
from app.models import User
from app.postgres import create_db_engine, get_database_url, session_scope
from app.seed_demo_user import seed_demo_user


@pytest.fixture(scope="session")
def api_engine():
    value = os.environ.get("BAKURAKU_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set BAKURAKU_TEST_DATABASE_URL for PostgreSQL API tests")
    url = get_database_url(value)
    admin = create_db_engine(url)
    schema = "wbs14_" + uuid4().hex
    engine = None
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        engine = create_db_engine(url.update_query_dict({"options": f"-csearch_path={schema},public"}))
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def api_db(api_engine):
    with api_engine.begin() as connection:
        connection.execute(text(
            "TRUNCATE attendance_audit_logs, attendance_records, users RESTART IDENTITY"
        ))
    return api_engine


@pytest.fixture
def demo_id(api_db):
    return seed_demo_user(api_db)


@pytest.fixture
def other_id(api_db):
    with session_scope(api_db) as session:
        user = User(cognito_sub="test:other-user", display_name="別の利用者")
        session.add(user)
        session.flush()
        return user.id


@pytest.fixture
def client_factory(api_db):
    @contextmanager
    def factory():
        application = create_app()
        application.dependency_overrides[get_db_engine] = lambda: api_db
        with TestClient(application) as client:
            yield client
    return factory


@pytest.fixture
def client(client_factory, demo_id):
    with client_factory() as client:
        yield client
