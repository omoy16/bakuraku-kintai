"""Execute the real migration and integrity checks against PostgreSQL.

Each run uses its own random schema. Existing schemas and SQLite files are untouched.
"""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models import AttendanceAuditLog, AttendanceRecord, User
from app.postgres import create_db_engine, get_database_url, session_scope
from app.seed_demo_user import DEMO_COGNITO_SUB, seed_demo_user

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[2]
START = datetime(2026, 10, 27, tzinfo=timezone.utc)


def migrate(engine, action="upgrade", revision="head"):
    config = Config(str(ROOT / "backend" / "alembic.ini"))
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        if action == "check":
            command.check(config)
        else:
            getattr(command, action)(config, revision)


@pytest.fixture(scope="module")
def postgres():
    value = os.environ.get("BAKURAKU_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set BAKURAKU_TEST_DATABASE_URL to run PostgreSQL integration tests")
    url = get_database_url(value)
    admin = create_db_engine(url)
    schema = "wbs12_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_db_engine(url.update_query_dict({"options": f"-csearch_path={schema},public"}))
    try:
        migrate(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def db_engine(postgres):
    with postgres.begin() as connection:
        connection.execute(text(
            "TRUNCATE attendance_audit_logs, attendance_records, users RESTART IDENTITY"
        ))
    return postgres


@pytest.fixture
def user_id(db_engine):
    with session_scope(db_engine) as session:
        user = User(cognito_sub="test:user", display_name="テスト利用者")
        session.add(user)
        session.flush()
        return user.id


def add_record(session, user_id, start=0, end=8, **values):
    record = AttendanceRecord(
        user_id=user_id, clock_in_at=START + timedelta(hours=start),
        clock_out_at=None if end is None else START + timedelta(hours=end), **values,
    )
    session.add(record)
    session.flush()
    return record


def snapshot(record):
    return {
        "clock_in_at": record.clock_in_at.astimezone(timezone.utc).isoformat(),
        "clock_out_at": record.clock_out_at.astimezone(timezone.utc).isoformat()
        if record.clock_out_at is not None else None,
        "cancelled_at": record.cancelled_at.astimezone(timezone.utc).isoformat()
        if record.cancelled_at is not None else None,
    }


def test_migration_creates_three_tables_constraints_and_indexes(db_engine):
    inspector = inspect(db_engine)
    assert set(inspector.get_table_names()) == {
        "users", "attendance_records", "attendance_audit_logs", "alembic_version",
    }
    with db_engine.connect() as connection:
        assert connection.scalar(text(
            "SELECT extname FROM pg_extension WHERE extname = 'btree_gist'"
        )) == "btree_gist"
        definitions = dict(connection.execute(text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE connamespace = current_schema()::regnamespace"
        )).all())
    assert "EXCLUDE USING gist" in definitions["ex_attendance_overlap"]
    assert "cancelled_at IS NULL" in definitions["ex_attendance_overlap"]
    for name in ("fk_attendance_user", "fk_audit_attendance", "fk_audit_actor"):
        assert "ON DELETE RESTRICT" in definitions[name]
    indexes = {i["name"]: i for i in inspector.get_indexes("attendance_records")}
    assert indexes["uq_attendance_active_user"]["unique"]
    assert "ix_attendance_user_history" in indexes
    assert "ix_audit_record_history" in {
        i["name"] for i in inspector.get_indexes("attendance_audit_logs")
    }


def test_model_and_migration_have_no_autogenerate_diff(db_engine):
    # Alembic does not compare every CHECK / exclusion constraint; test them below too.
    migrate(db_engine, action="check")


def test_online_cli_uses_environment_from_another_directory(db_engine, tmp_path):
    env = {**os.environ, "BAKURAKU_DATABASE_URL":
           db_engine.url.render_as_string(hide_password=False)}
    outputs = []
    for arguments in (("upgrade", "head"), ("current",), ("check",)):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c",
             str(ROOT / "backend" / "alembic.ini"), *arguments],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        outputs.append(result.stdout)
    assert "0001_attendance_schema (head)" in outputs[1]
    assert "No new upgrade operations detected." in outputs[2]


def test_migration_is_repeatable_and_can_be_reversed(db_engine):
    migrate(db_engine)
    migrate(db_engine, action="downgrade", revision="base")
    try:
        assert inspect(db_engine).get_table_names() == ["alembic_version"]
        with db_engine.connect() as connection:
            assert connection.scalar(text(
                "SELECT count(*) FROM pg_extension WHERE extname = 'btree_gist'"
            )) == 1
    finally:
        migrate(db_engine)
    migrate(db_engine, action="check")


def test_utc_and_server_generated_defaults(db_engine, user_id):
    jst_time = datetime(2026, 10, 27, 22, tzinfo=ZoneInfo("Asia/Tokyo"))
    with session_scope(db_engine) as session:
        assert session.scalar(text("SHOW TIME ZONE")) == "UTC"
        before = session.scalar(select(func.clock_timestamp()))
        record = AttendanceRecord(user_id=user_id, clock_in_at=jst_time)
        session.add(record)
        session.flush()
        after = session.scalar(select(func.clock_timestamp()))
        assert record.id > 0
        assert before <= record.created_at <= after
        assert before <= record.updated_at <= after
        session.refresh(record)
        assert record.clock_in_at.utcoffset() == timedelta(0)
        assert record.clock_in_at == jst_time


def test_identity_cannot_be_supplied_by_a_normal_insert(db_engine):
    with pytest.raises(DBAPIError) as error:
        with session_scope(db_engine) as session:
            session.add(User(id=42, cognito_sub="test:manual", display_name="manual"))
    assert error.value.orig.sqlstate == "428C9"


def test_cognito_sub_is_unique(db_engine, user_id):
    with pytest.raises(IntegrityError) as error:
        with session_scope(db_engine) as session:
            session.add(User(cognito_sub="test:user", display_name="duplicate"))
    assert error.value.orig.sqlstate == "23505"


def test_attendance_owner_must_exist(db_engine):
    with pytest.raises(IntegrityError) as error:
        with session_scope(db_engine) as session:
            add_record(session, 999)
    assert error.value.orig.sqlstate == "23503"


@pytest.mark.parametrize("missing", ["attendance_record_id", "actor_user_id"])
def test_audit_foreign_keys(db_engine, user_id, missing):
    with session_scope(db_engine) as session:
        record_id = add_record(session, user_id).id
    values = {"attendance_record_id": record_id, "actor_user_id": user_id}
    values[missing] = 999
    with pytest.raises(IntegrityError) as error:
        with session_scope(db_engine) as session:
            session.add(AttendanceAuditLog(**values, operation="clock_in", after_values={}))
    assert error.value.orig.sqlstate == "23503"


@pytest.mark.parametrize("target", ["user", "attendance"])
def test_referenced_rows_cannot_be_deleted(db_engine, user_id, target):
    with session_scope(db_engine) as session:
        record = add_record(session, user_id)
        record_id = record.id
        session.add(AttendanceAuditLog(
            attendance_record_id=record.id, actor_user_id=user_id,
            operation="clock_in", after_values=snapshot(record),
        ))
    with pytest.raises(IntegrityError) as error:
        with session_scope(db_engine) as session:
            obj = session.get(User, user_id) if target == "user" else session.get(AttendanceRecord, record_id)
            session.delete(obj)
    assert error.value.orig.sqlstate == "23503"


def test_clock_out_before_clock_in_is_rejected(db_engine, user_id):
    with pytest.raises(IntegrityError) as error:
        with session_scope(db_engine) as session:
            add_record(session, user_id, start=8, end=7)
    assert error.value.orig.sqlstate == "23514"


def test_adjacent_same_day_and_zero_length_shifts_are_allowed(db_engine, user_id):
    with session_scope(db_engine) as session:
        add_record(session, user_id, start=0, end=3)
        add_record(session, user_id, start=3, end=8)
        add_record(session, user_id, start=5, end=5)
        assert session.scalar(select(func.count()).select_from(AttendanceRecord)) == 3


def test_overnight_active_shift_has_no_date_boundary(db_engine, user_id):
    with session_scope(db_engine) as session:
        record = add_record(session, user_id, start=14, end=None)  # 23:00 JST
        record.clock_out_at = START + timedelta(hours=22)  # next day 07:00 JST
    with session_scope(db_engine) as session:
        saved = session.get(AttendanceRecord, record.id)
        assert saved.clock_in_at.astimezone(ZoneInfo("Asia/Tokyo")).date().isoformat() == "2026-10-27"
        assert saved.clock_out_at.astimezone(ZoneInfo("Asia/Tokyo")).date().isoformat() == "2026-10-28"


@pytest.mark.parametrize("end", [None, 9])
def test_overlapping_insert_is_rejected(db_engine, user_id, end):
    with session_scope(db_engine) as session:
        add_record(session, user_id)
    with pytest.raises(IntegrityError) as error:
        with session_scope(db_engine) as session:
            add_record(session, user_id, start=7, end=end)
    assert error.value.orig.sqlstate == "23P01"


def test_overlapping_update_is_rejected_and_rolled_back(db_engine, user_id):
    with session_scope(db_engine) as session:
        add_record(session, user_id, start=0, end=3)
        second_id = add_record(session, user_id, start=4, end=8).id
    with pytest.raises(IntegrityError) as error:
        with session_scope(db_engine) as session:
            session.get(AttendanceRecord, second_id).clock_in_at = START + timedelta(hours=2)
    assert error.value.orig.sqlstate == "23P01"
    with session_scope(db_engine) as session:
        assert session.get(AttendanceRecord, second_id).clock_in_at == START + timedelta(hours=4)


def test_cancelled_rows_and_other_users_do_not_block_shifts(db_engine, user_id):
    with session_scope(db_engine) as session:
        add_record(session, user_id, end=None, cancelled_at=START + timedelta(seconds=30))
        add_record(session, user_id)
        other = User(cognito_sub="test:other", display_name="別の利用者")
        session.add(other)
        session.flush()
        add_record(session, other.id)


def test_duplicate_active_shift_is_rejected_even_at_different_start_times(db_engine, user_id):
    with session_scope(db_engine) as session:
        add_record(session, user_id, end=None)
    with pytest.raises(IntegrityError) as error:
        with session_scope(db_engine) as session:
            add_record(session, user_id, start=10, end=None)
    assert error.value.orig.sqlstate in ("23505", "23P01")


@pytest.mark.parametrize("end", [None, 8])
def test_concurrent_overlapping_inserts_allow_exactly_one(db_engine, user_id, end):
    barrier = Barrier(2)

    def insert_shift(_):
        try:
            with session_scope(db_engine) as session:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                barrier.wait(timeout=10)
                add_record(session, user_id, end=end)
            return "committed"
        except DBAPIError as error:
            # Simultaneous GiST checks may choose a deadlock victim. In each
            # case the failed transaction must be rolled back in its entirety.
            assert error.orig.sqlstate in ("23505", "23P01", "40P01")
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(insert_shift, range(2)))
    assert sorted(results) == ["committed", "conflict"]
    with session_scope(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(AttendanceRecord)) == 1


def test_audit_jsonb_sql_null_and_change_reason(db_engine, user_id):
    with session_scope(db_engine) as session:
        record = add_record(session, user_id)
        audit = AttendanceAuditLog(
            attendance_record_id=record.id, actor_user_id=user_id, operation="clock_in",
            before_values=None, after_values=snapshot(record), change_reason="打刻時刻の入力誤り",
        )
        session.add(audit)
        session.flush()
        audit_id = audit.id
        assert audit.operated_at.tzinfo is not None
    with session_scope(db_engine) as session:
        saved = session.get(AttendanceAuditLog, audit_id)
        assert saved.after_values["clock_in_at"].endswith("+00:00")
        assert saved.change_reason == "打刻時刻の入力誤り"
        assert session.scalar(select(AttendanceAuditLog.before_values.is_(None)))


@pytest.mark.parametrize("update_existing", [False, True])
def test_failed_audit_rolls_back_attendance_and_history(db_engine, user_id, update_existing):
    record_id = None
    if update_existing:
        with session_scope(db_engine) as session:
            record_id = add_record(session, user_id, end=None).id
    with pytest.raises(IntegrityError) as error:
        with session_scope(db_engine) as session:
            if update_existing:
                record = session.get(AttendanceRecord, record_id)
                record.clock_out_at = START + timedelta(hours=8)
                record.updated_at = func.clock_timestamp()
                session.flush()
            else:
                record = add_record(session, user_id)
            session.add(AttendanceAuditLog(
                attendance_record_id=record.id, actor_user_id=user_id,
                operation="invalid_operation", after_values=snapshot(record),
            ))
    assert error.value.orig.sqlstate == "23514"
    with session_scope(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(AttendanceAuditLog)) == 0
        assert session.scalar(select(func.count()).select_from(AttendanceRecord)) == int(update_existing)
        if update_existing:
            assert session.get(AttendanceRecord, record_id).clock_out_at is None


def test_demo_seed_returns_stable_generated_id_without_overwriting(db_engine, user_id):
    first_id = seed_demo_user(db_engine)
    assert first_id != user_id
    with session_scope(db_engine) as session:
        session.get(User, first_id).display_name = "変更した名前"
    assert seed_demo_user(db_engine) == first_id
    with session_scope(db_engine) as session:
        user = session.get(User, first_id)
        assert user.cognito_sub == DEMO_COGNITO_SUB
        assert user.display_name == "変更した名前"
