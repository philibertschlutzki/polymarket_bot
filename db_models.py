from typing import Any, Dict, Type
from sqlalchemy import create_engine, Column, Integer, String, Numeric, DateTime, Boolean, Text, CheckConstraint, JSON, BigInteger
from sqlalchemy.orm import sessionmaker, declarative_base, DeclarativeMeta
from sqlalchemy.sql import func
from contextlib import contextmanager
import os
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/polymarket_bot")

engine_args: Dict[str, Any] = {
    "pool_pre_ping": True,
    "echo": False
}

if DATABASE_URL.startswith("postgresql"):
    engine_args.update({
        "pool_size": 5,
        "max_overflow": 10
    })

engine = create_engine(DATABASE_URL, **engine_args)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base: Any = declarative_base()

@contextmanager
def session_scope():
    """Thread-safe session context manager with automatic rollback on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

class ActiveBet(Base):
    __tablename__ = 'active_bets'
    bet_id = Column(BigInteger, primary_key=True, autoincrement=True)
    market_slug = Column(Text, nullable=False, unique=True)
    url_slug = Column(Text, nullable=False)
    question = Column(Text, nullable=False)
    action = Column(Text, nullable=False)
    stake_usdc = Column(Numeric(10, 2), nullable=False)
    entry_price = Column(Numeric(5, 4), nullable=False)
    ai_probability = Column(Numeric(5, 4), nullable=False)
    confidence_score = Column(Numeric(5, 4), nullable=False)
    expected_value = Column(Numeric(10, 2), nullable=False)
    edge = Column(Numeric(6, 4))
    ai_reasoning = Column(Text)
    end_date = Column(DateTime(timezone=True))
    timestamp_created = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status = Column(Text, nullable=False, server_default='OPEN')
    version = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("action IN ('YES', 'NO')"),
        CheckConstraint("stake_usdc > 0"),
        CheckConstraint("entry_price BETWEEN 0 AND 1"),
        CheckConstraint("ai_probability BETWEEN 0 AND 1"),
        CheckConstraint("confidence_score BETWEEN 0 AND 1"),
        CheckConstraint("status IN ('OPEN', 'PENDING_RESOLUTION')"),
    )

class ArchivedBet(Base):
    __tablename__ = 'archived_bets'
    archive_id = Column(BigInteger, primary_key=True, autoincrement=True)
    original_bet_id = Column(BigInteger, nullable=False, unique=True)
    market_slug = Column(Text, nullable=False)
    url_slug = Column(Text, nullable=False)
    question = Column(Text, nullable=False)
    action = Column(Text, nullable=False)
    stake_usdc = Column(Numeric(10, 2), nullable=False)
    entry_price = Column(Numeric(5, 4), nullable=False)
    ai_probability = Column(Numeric(5, 4), nullable=False)
    confidence_score = Column(Numeric(5, 4), nullable=False)
    edge = Column(Numeric(6, 4))
    ai_reasoning = Column(Text)
    timestamp_created = Column(DateTime(timezone=True), nullable=False)
    timestamp_archived = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    end_date = Column(DateTime(timezone=True))
    actual_outcome = Column(Text)
    profit_loss = Column(Numeric(10, 2))
    roi = Column(Numeric(6, 4))
    timestamp_resolved = Column(DateTime(timezone=True))
    version = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("action IN ('YES', 'NO')"),
        CheckConstraint("stake_usdc > 0"),
        CheckConstraint("entry_price BETWEEN 0 AND 1"),
        CheckConstraint("ai_probability BETWEEN 0 AND 1"),
        CheckConstraint("confidence_score BETWEEN 0 AND 1"),
        CheckConstraint("actual_outcome IN ('YES', 'NO', 'UNRESOLVED')"),
    )

class RejectedMarket(Base):
    __tablename__ = 'rejected_markets'
    rejection_id = Column(BigInteger, primary_key=True, autoincrement=True)
    market_slug = Column(Text, nullable=False)
    url_slug = Column(Text, nullable=False)
    question = Column(Text, nullable=False)
    market_price = Column(Numeric(5, 4), nullable=False)
    volume = Column(Numeric(15, 2), nullable=False)
    ai_probability = Column(Numeric(5, 4), nullable=False)
    confidence_score = Column(Numeric(5, 4), nullable=False)
    edge = Column(Numeric(6, 4), nullable=False)
    rejection_reason = Column(Text, nullable=False)
    ai_reasoning = Column(Text)
    timestamp_analyzed = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    end_date = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("market_price BETWEEN 0 AND 1"),
        CheckConstraint("ai_probability BETWEEN 0 AND 1"),
        CheckConstraint("confidence_score BETWEEN 0 AND 1"),
    )

class ApiUsage(Base):
    __tablename__ = 'api_usage'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    api_name = Column(Text, nullable=False)
    endpoint = Column(Text)
    calls = Column(Integer, default=1)
    tokens_prompt = Column(Integer, default=0)
    tokens_response = Column(Integer, default=0)
    tokens_total = Column(Integer, default=0)
    response_time_ms = Column(Integer, default=0)

class PortfolioState(Base):
    __tablename__ = 'portfolio_state'
    id = Column(Integer, primary_key=True)
    total_capital = Column(Numeric(15, 2), nullable=False)
    last_updated = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_dashboard_update = Column(DateTime(timezone=True))
    last_run_timestamp = Column(DateTime(timezone=True))
    version = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("id = 1"),
    )

class GitSyncState(Base):
    __tablename__ = 'git_sync_state'
    id = Column(Integer, primary_key=True)
    last_git_push = Column(DateTime(timezone=True))
    pending_changes_count = Column(Integer, default=0)
    has_new_bets = Column(Boolean, default=False)
    has_new_rejections = Column(Boolean, default=False)
    has_bet_resolutions = Column(Boolean, default=False)

    __table_args__ = (
        CheckConstraint("id = 1"),
    )

class BetAnalysis(Base):
    __tablename__ = 'bet_analysis'
    analysis_id = Column(BigInteger, primary_key=True, autoincrement=True)
    archive_id = Column(BigInteger, nullable=False) # ForeignKey would be good, but prompt just said references. I'll stick to simple column to avoid complex relationship setups unless needed, but I should add FK if I want referential integrity. Let's add it.
    # Actually, let's keep it simple as per prompt SQL which had REFERENCES but here I am defining ORM.
    # I'll add ForeignKey to keep it clean.
    from sqlalchemy import ForeignKey
    archive_id = Column(BigInteger, ForeignKey('archived_bets.archive_id'), nullable=False)

    ai_model = Column(Text, nullable=False)
    predicted_outcome = Column(Text, nullable=False)
    confidence = Column(Numeric(5, 4), nullable=False)
    reasoning = Column(Text)
    timestamp_analyzed = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    raw_response = Column(JSON)

    __table_args__ = (
        CheckConstraint("predicted_outcome IN ('YES', 'NO')"),
        CheckConstraint("confidence BETWEEN 0 AND 1"),
    )

class FinalPredictions(Base):
    __tablename__ = 'final_predictions'
    prediction_id = Column(BigInteger, primary_key=True, autoincrement=True)
    from sqlalchemy import ForeignKey, ARRAY
    archive_id = Column(BigInteger, ForeignKey('archived_bets.archive_id'), nullable=False, unique=True)
    aggregated_outcome = Column(Text, nullable=False)
    weighted_confidence = Column(Numeric(5, 4), nullable=False)
    models_used = Column(ARRAY(Text))  # type: ignore # Using ARRAY for TEXT[]
    weights_applied = Column(JSON)
    timestamp_created = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    version = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("aggregated_outcome IN ('YES', 'NO')"),
        CheckConstraint("weighted_confidence BETWEEN 0 AND 1"),
    )
