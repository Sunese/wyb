import json
import os
import re
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pika
from fastapi import Depends, FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.instrumentation.pika import PikaInstrumentor
from pydantic import BaseModel
from sqlalchemy import Column, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, relationship, sessionmaker

from categorize.telemetry import configure_tracing

# ── Database ──────────────────────────────────────────────────────────────────

def _parse_db_path(datasource_env: str | None, conn_str: str | None) -> str:
    """Extract a SQLite file path from Aspire-injected env vars.

    Aspire provides CATEGORIZE_DB_DATASOURCE (the bare path) and/or the full
    ADO.NET-style ConnectionStrings__categorize-db value like
    "Data Source=/path/to/file.db;Cache=Shared;Mode=ReadWriteCreate".
    """
    if datasource_env:
        return datasource_env
    for part in (conn_str or "Data Source=categorize.db").split(";"):
        if part.strip().lower().startswith("data source="):
            return part.strip()[len("Data Source="):]
    return "categorize.db"


_db_path = _parse_db_path(
    os.environ.get("CATEGORIZE_DB_DATASOURCE"),
    os.environ.get("ConnectionStrings__categorize-db"),
)
engine = create_engine(f"sqlite:///{_db_path}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class CategoryRuleRow(Base):
    __tablename__ = "category_rules"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    pattern = Column(String, nullable=False)
    match_type = Column(String, nullable=False)
    category = Column(String, nullable=False)
    priority = Column(Integer, nullable=False)
    created_at = Column(String, nullable=False,
                        default=lambda: datetime.now(timezone.utc).isoformat())


class MerchantRow(Base):
    __tablename__ = "merchants"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    canonical_name = Column(String, nullable=False)
    default_category = Column(String, nullable=True)
    aliases: Mapped[list["MerchantAliasRow"]] = relationship(
        "MerchantAliasRow", back_populates="merchant", cascade="all, delete-orphan"
    )


class MerchantAliasRow(Base):
    __tablename__ = "merchant_aliases"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    merchant_id = Column(String, ForeignKey("merchants.id"), nullable=False)
    pattern = Column(String, nullable=False)
    match_type = Column(String, nullable=False)
    merchant: Mapped["MerchantRow"] = relationship("MerchantRow", back_populates="aliases")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Pure categorization logic (unit-testable) ─────────────────────────────────

def _matches(text: str, pattern: str, match_type: str) -> bool:
    text_u = text.upper()
    pattern_u = pattern.upper()
    if match_type == "Contains":
        return pattern_u in text_u
    if match_type == "Exact":
        return text_u == pattern_u
    if match_type == "StartsWith":
        return text_u.startswith(pattern_u)
    if match_type == "Regex":
        return bool(re.search(pattern, text, re.IGNORECASE))
    return False


def _apply_rules(raw_description: str, rules: list) -> str:
    for rule in sorted(rules, key=lambda r: r["priority"]):
        if _matches(raw_description, rule["pattern"], rule["matchType"]):
            return rule["category"]
    return "Uncategorized"


def _resolve_merchant(raw_description: str, aliases: list) -> dict | None:
    for alias in aliases:
        if _matches(raw_description, alias["pattern"], alias["matchType"]):
            return alias
    return None


# ── Serialization helpers ─────────────────────────────────────────────────────

def _rule_to_dict(r: CategoryRuleRow) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "pattern": r.pattern,
        "matchType": r.match_type,
        "category": r.category,
        "priority": r.priority,
        "createdAt": r.created_at,
    }


def _alias_to_dict(a: MerchantAliasRow) -> dict:
    return {
        "id": a.id,
        "merchantId": a.merchant_id,
        "pattern": a.pattern,
        "matchType": a.match_type,
    }


def _merchant_to_dict(m: MerchantRow) -> dict:
    return {
        "id": m.id,
        "canonicalName": m.canonical_name,
        "defaultCategory": m.default_category,
        "aliases": [_alias_to_dict(a) for a in m.aliases],
    }


# ── RabbitMQ consumer (runs in a background thread) ───────────────────────────

def run_consumer():
    tracer = trace.get_tracer("categorize")
    url = os.environ["ConnectionStrings__rabbit"]
    connection = pika.BlockingConnection(pika.URLParameters(url))
    channel = connection.channel()

    channel.exchange_declare(exchange="transaction.imported", exchange_type="fanout", durable=True)
    channel.exchange_declare(exchange="transaction.categorized", exchange_type="fanout", durable=True)
    channel.queue_declare(queue="categorize.transaction.imported", durable=True)
    channel.queue_bind(exchange="transaction.imported", queue="categorize.transaction.imported")

    def on_message(ch, method, properties, body):
        with tracer.start_as_current_span("categorize.handle_imported"):
            payload = json.loads(body)
            raw_description = payload.get("raw_description", "")

            db = SessionLocal()
            try:
                rules = [_rule_to_dict(r) for r in
                         db.query(CategoryRuleRow).order_by(CategoryRuleRow.priority).all()]
                aliases = [
                    {**_alias_to_dict(a),
                     "merchantName": a.merchant.canonical_name,
                     "defaultCategory": a.merchant.default_category}
                    for m in db.query(MerchantRow).all()
                    for a in m.aliases
                ]
            finally:
                db.close()

            rule_category = _apply_rules(raw_description, rules)
            merchant_match = _resolve_merchant(raw_description, aliases)
            merchant_name = merchant_match["merchantName"] if merchant_match else None
            merchant_default_category = merchant_match.get("defaultCategory") if merchant_match else None
            category = (rule_category if rule_category != "Uncategorized"
                        else merchant_default_category or "Uncategorized")

            print(f"[categorize] '{raw_description}' → {category}"
                  + (f" ({merchant_name})" if merchant_name else ""))

            enriched = {**payload, "category": category}
            if merchant_name is not None:
                enriched["merchant_name"] = merchant_name

            ch.basic_ack(delivery_tag=method.delivery_tag)
            channel.basic_publish(
                exchange="transaction.categorized",
                routing_key="",
                body=json.dumps(enriched),
                properties=pika.BasicProperties(headers=properties.headers),
            )

    channel.basic_consume(queue="categorize.transaction.imported", on_message_callback=on_message)
    channel.start_consuming()


# ── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_tracing()
    PikaInstrumentor().instrument()
    Base.metadata.create_all(engine)
    thread = threading.Thread(target=run_consumer, daemon=True)
    thread.start()
    yield


app = FastAPI(lifespan=lifespan)


# ── Category Rules ────────────────────────────────────────────────────────────

class CreateRuleRequest(BaseModel):
    name: str
    pattern: str
    matchType: str
    category: str
    priority: int


@app.get("/rules")
def get_rules(db: Session = Depends(get_db)):
    rules = db.query(CategoryRuleRow).order_by(CategoryRuleRow.priority).all()
    return [_rule_to_dict(r) for r in rules]


@app.post("/rules", status_code=201)
def create_rule(req: CreateRuleRequest, db: Session = Depends(get_db)):
    rule = CategoryRuleRow(
        name=req.name,
        pattern=req.pattern,
        match_type=req.matchType,
        category=req.category,
        priority=req.priority,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _rule_to_dict(rule)


@app.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: str, db: Session = Depends(get_db)):
    rule = db.query(CategoryRuleRow).filter(CategoryRuleRow.id == rule_id).first()
    if rule is None:
        raise HTTPException(status_code=404)
    db.delete(rule)
    db.commit()


# ── Merchants ─────────────────────────────────────────────────────────────────

class CreateMerchantRequest(BaseModel):
    canonicalName: str
    defaultCategory: str | None = None


class CreateAliasRequest(BaseModel):
    pattern: str
    matchType: str


@app.get("/merchants")
def get_merchants(db: Session = Depends(get_db)):
    merchants = db.query(MerchantRow).order_by(MerchantRow.canonical_name).all()
    return [_merchant_to_dict(m) for m in merchants]


@app.post("/merchants", status_code=201)
def create_merchant(req: CreateMerchantRequest, db: Session = Depends(get_db)):
    merchant = MerchantRow(canonical_name=req.canonicalName, default_category=req.defaultCategory)
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    return _merchant_to_dict(merchant)


@app.delete("/merchants/{merchant_id}", status_code=204)
def delete_merchant(merchant_id: str, db: Session = Depends(get_db)):
    merchant = db.query(MerchantRow).filter(MerchantRow.id == merchant_id).first()
    if merchant is None:
        raise HTTPException(status_code=404)
    db.delete(merchant)
    db.commit()


@app.post("/merchants/{merchant_id}/aliases", status_code=201)
def create_alias(merchant_id: str, req: CreateAliasRequest, db: Session = Depends(get_db)):
    if not db.query(MerchantRow).filter(MerchantRow.id == merchant_id).first():
        raise HTTPException(status_code=404)
    alias = MerchantAliasRow(merchant_id=merchant_id, pattern=req.pattern, match_type=req.matchType)
    db.add(alias)
    db.commit()
    db.refresh(alias)
    return _alias_to_dict(alias)


@app.delete("/aliases/{alias_id}", status_code=204)
def delete_alias(alias_id: str, db: Session = Depends(get_db)):
    alias = db.query(MerchantAliasRow).filter(MerchantAliasRow.id == alias_id).first()
    if alias is None:
        raise HTTPException(status_code=404)
    db.delete(alias)
    db.commit()
