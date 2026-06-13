import os

from sqlmodel import Session, SQLModel, create_engine

from detect.models import Subscription  # noqa: F401 — registers the table


def _parse_pg_url(conn_str: str) -> str:
    params = {
        k.strip().lower(): v.strip()
        for part in conn_str.split(";")
        if "=" in part
        for k, v in [part.split("=", 1)]
    }
    host = params.get("host", "localhost")
    port = params.get("port", "5432")
    db = params.get("database", "detect-db")
    user = params.get("username", "postgres")
    pwd = params.get("password", "")
    return f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{db}"


def make_engine(conn_str: str | None = None):
    url = _parse_pg_url(conn_str or os.environ.get("ConnectionStrings__detect-db", ""))
    return create_engine(url)


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)


def get_session(engine):
    with Session(engine) as session:
        yield session
