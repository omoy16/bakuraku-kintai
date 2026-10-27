"""Explicit, idempotent local-only seed; never run automatically in migrations."""

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert

from app.models import User
from app.postgres import create_db_engine, session_scope

# Cognito sub is a UUID; this namespace cannot be a real authenticated identity.
DEMO_COGNITO_SUB = "local:demo-user"


def seed_demo_user(engine: Engine) -> int:
    """Return the generated users.id; do not assume it is 1 or overwrite a user."""
    with session_scope(engine) as session:
        session.execute(
            insert(User)
            .values(cognito_sub=DEMO_COGNITO_SUB, display_name="デモユーザー")
            .on_conflict_do_nothing(index_elements=[User.cognito_sub])
        )
        user_id = session.scalar(select(User.id).where(User.cognito_sub == DEMO_COGNITO_SUB))
        assert user_id is not None
        return user_id


def main() -> None:
    engine = create_db_engine()
    try:
        print(f"Local demo users.id: {seed_demo_user(engine)}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
