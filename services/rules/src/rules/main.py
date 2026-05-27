import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from sqlmodel import Field, Relationship, Session, SQLModel, create_engine, select

from rules.categories import TransactionCategory
from rules.telemetry import configure_tracing


def _parse_pg_url(conn_str: str) -> str:
    params = {k.strip().lower(): v.strip() for part in conn_str.split(";") if "=" in part for k, v in [part.split("=", 1)]}
    host = params.get("host", "localhost")
    port = params.get("port", "5432")
    db = params.get("database", "rules-db")
    user = params.get("username", "postgres")
    pwd = params.get("password", "")
    return f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{db}"


_db_url = _parse_pg_url(os.environ.get("ConnectionStrings__rules-db", ""))
engine = create_engine(_db_url)


def get_session():
    with Session(engine) as session:
        yield session


# ── Models ────────────────────────────────────────────────────────────────────

class CategoryRule(SQLModel, table=True):
    __tablename__ = "category_rules"
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str
    pattern: str
    matchType: str
    category: str
    priority: int
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Merchant(SQLModel, table=True):
    __tablename__ = "merchants"
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    canonicalName: str
    defaultCategory: Optional[str] = None
    aliases: list["MerchantAlias"] = Relationship(
        back_populates="merchant",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class MerchantAlias(SQLModel, table=True):
    __tablename__ = "merchant_aliases"
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    merchantId: str = Field(foreign_key="merchants.id")
    pattern: str
    matchType: str
    merchant: Optional[Merchant] = Relationship(back_populates="aliases")


# ── Request schemas ───────────────────────────────────────────────────────────

class CreateRuleRequest(SQLModel):
    name: str
    pattern: str
    matchType: str
    category: TransactionCategory
    priority: int


class CreateMerchantRequest(SQLModel):
    canonicalName: str
    defaultCategory: Optional[TransactionCategory] = None


class CreateAliasRequest(SQLModel):
    pattern: str
    matchType: str


# ── App ───────────────────────────────────────────────────────────────────────

def _load_seed(session: Session) -> None:
    if session.exec(select(CategoryRule)).first() or session.exec(select(Merchant)).first():
        print("Database already has data, skipping seed load")
        return
    
    seed_path = Path(__file__).parent.parent.parent / "seed.json"
    if not seed_path.exists():
        print("Seed file not found, skipping seed load")
        return
    print(f"Loading seed data from {seed_path}")
    data = json.loads(seed_path.read_text())
    for r in data.get("rules", []):
        session.add(CategoryRule(**r))
    for m in data.get("merchants", []):
        aliases = m.pop("aliases", [])
        merchant = Merchant(**m)
        session.add(merchant)
        session.flush()
        for a in aliases:
            session.add(MerchantAlias(merchantId=merchant.id, **a))
    print("Seed data loaded successfully")
    session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_tracing()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _load_seed(session)
    yield


app = FastAPI(lifespan=lifespan)


# ── Rules ─────────────────────────────────────────────────────────────────────

@app.get("/rules")
def get_rules(session: Session = Depends(get_session)):
    return session.exec(select(CategoryRule).order_by(CategoryRule.priority)).all()


@app.post("/rules", status_code=201)
def create_rule(req: CreateRuleRequest, session: Session = Depends(get_session)):
    rule = CategoryRule(**req.model_dump())
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


@app.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: str, session: Session = Depends(get_session)):
    rule = session.get(CategoryRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404)
    session.delete(rule)
    session.commit()


# ── Merchants ─────────────────────────────────────────────────────────────────

def _merchant_response(m: Merchant) -> dict:
    return {
        "id": m.id,
        "canonicalName": m.canonicalName,
        "defaultCategory": m.defaultCategory,
        "aliases": [
            {"id": a.id, "merchantId": a.merchantId, "pattern": a.pattern, "matchType": a.matchType}
            for a in m.aliases
        ],
    }


@app.get("/merchants")
def get_merchants(session: Session = Depends(get_session)):
    merchants = session.exec(select(Merchant).order_by(Merchant.canonicalName)).all()
    return [_merchant_response(m) for m in merchants]


@app.post("/merchants", status_code=201)
def create_merchant(req: CreateMerchantRequest, session: Session = Depends(get_session)):
    merchant = Merchant(**req.model_dump())
    session.add(merchant)
    session.commit()
    session.refresh(merchant)
    return _merchant_response(merchant)


@app.delete("/merchants/{merchant_id}", status_code=204)
def delete_merchant(merchant_id: str, session: Session = Depends(get_session)):
    merchant = session.get(Merchant, merchant_id)
    if not merchant:
        raise HTTPException(status_code=404)
    session.delete(merchant)
    session.commit()


@app.post("/merchants/{merchant_id}/aliases", status_code=201)
def create_alias(merchant_id: str, req: CreateAliasRequest, session: Session = Depends(get_session)):
    if not session.get(Merchant, merchant_id):
        raise HTTPException(status_code=404)
    alias = MerchantAlias(merchantId=merchant_id, **req.model_dump())
    session.add(alias)
    session.commit()
    session.refresh(alias)
    return {"id": alias.id, "merchantId": alias.merchantId, "pattern": alias.pattern, "matchType": alias.matchType}


@app.delete("/aliases/{alias_id}", status_code=204)
def delete_alias(alias_id: str, session: Session = Depends(get_session)):
    alias = session.get(MerchantAlias, alias_id)
    if not alias:
        raise HTTPException(status_code=404)
    session.delete(alias)
    session.commit()
