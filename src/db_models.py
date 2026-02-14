import logging
import os
from contextlib import contextmanager
from typing import Any, Dict

from sqlalchemy import (
    ARRAY,
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func


class BetStatus:
    """Bet status constants"""

    OPEN = "OPEN"
    EXPIRED_PENDING = "EXPIRED_PENDING"  # Expired < 7 days
    UNRESOLVED = "UNRESOLVED"  # Expired > 7 days, not resolved
    DISPUTED = "DISPUTED"  # Price 0.1-0.9, < 7 days
    DISPUTED_LOSS = "DISPUTED_LOSS"  # Price 0.1-0.9, > 7 days → auto-loss
    AUTO_LOSS = "AUTO_LOSS"  # > 30 days unresolved → total loss
    WON = "WON"
    LOST = "LOST"
    ANNULLED = "ANNULLED"  # Market cancelled, stake returned


logger = logging.getLogger(__name__)

# Default to SQLite if DATABASE_URL is not set
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///database/polymarket.db"

engine_args: Dict[str, Any] = {
    "pool_pre_ping": True,
    "echo": False,
}

# Add PostgreSQL specific arguments only if using PostgreSQL
if DATABASE_URL.startswith("postgresql"):
    engine_args.update({"pool_size": 5, "max_overflow": 10})
else:
    # SQLite: Allow multi-threaded access
    engine_args.update({"connect_args": {"check_same_thread": False}})

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
    __tablename__ = "active_bets"
    bet_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    market_slug = Column(Text, nullable=False)
    parent_event_slug = Column(Text, nullable=True, index=True)
    outcome_variant_id = Column(Text, nullable=True)
    is_multi_outcome = Column(Boolean, default=False, nullable=False)
    parent_analysis_id = Column(Integer)
    full_distribution = Column(Text)
    alternative_outcomes_count = Column(Integer, default=0)
    url_slug = Column(Text, nullable=False)
    question = Column(Text, nullable=False)
    action = Column(Text, nullable=False)
    stake_usdc = Column(Numeric(10, 2), nullable=False)
    entry_price = Column(Numeric(5, 4), nullable=False)
    # Execution fields
    order_id = Column(Text, nullable=True)
    fill_price = Column(Numeric(5, 4), nullable=True)

    ai_probability = Column(Numeric(5, 4), nullable=False)
    confidence_score = Column(Numeric(5, 4), nullable=False)
    expected_value = Column(Numeric(10, 2), nullable=False)
    edge = Column(Numeric(6, 4))
    ai_reasoning = Column(Text)
    end_date = Column(DateTime(timezone=True))
    timestamp_created = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status = Column(Text, nullable=False, server_default="OPEN")
    version = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("action IN ('YES', 'NO')"),
        CheckConstraint("stake_usdc > 0"),
        CheckConstraint("entry_price BETWEEN 0 AND 1"),
        CheckConstraint("ai_probability BETWEEN 0 AND 1"),
        CheckConstraint("confidence_score BETWEEN 0 AND 1"),
        CheckConstraint("status IN ('OPEN', 'PENDING_RESOLUTION')"),
        {"sqlite_autoincrement": True},
    )


class ArchivedBet(Base):
    __tablename__ = "archived_bets"
    archive_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    original_bet_id = Column(BigInteger, nullable=False, unique=True)
    market_slug = Column(Text, nullable=False)
    parent_event_slug = Column(Text, nullable=True, index=True)
    outcome_variant_id = Column(Text, nullable=True)
    is_multi_outcome = Column(Boolean, default=False, nullable=False)
    parent_analysis_id = Column(Integer)
    full_distribution = Column(Text)
    alternative_outcomes_count = Column(Integer, default=0)
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
    timestamp_archived = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
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
        CheckConstraint(
            "actual_outcome IN ('YES', 'NO', 'UNRESOLVED', 'AUTO_LOSS', 'DISPUTED', 'DISPUTED_LOSS', 'ANNULLED')"
        ),
        {"sqlite_autoincrement": True},
    )


class MultiOutcomeAnalysis(Base):
    __tablename__ = "multi_outcome_analyses"
    analysis_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    parent_event_slug = Column(Text, nullable=False)
    timestamp_analyzed = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    full_distribution = Column(Text, nullable=False)
    market_prices = Column(Text, nullable=False)
    edges = Column(Text, nullable=False)
    best_outcome_slug = Column(Text)
    reasoning = Column(Text)
    outcomes_count = Column(Integer)

    __table_args__ = (
        Index("idx_multi_analyses_parent", "parent_event_slug"),
        Index("idx_multi_analyses_timestamp", "timestamp_analyzed"),
    )


class RejectedMarket(Base):
    __tablename__ = "rejected_markets"
    rejection_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
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
    timestamp_analyzed = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    end_date = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("market_price BETWEEN 0 AND 1"),
        CheckConstraint("ai_probability BETWEEN 0 AND 1"),
        CheckConstraint("confidence_score BETWEEN 0 AND 1"),
    )


class ApiUsage(Base):
    __tablename__ = "api_usage"
    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    timestamp = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    api_name = Column(Text, nullable=False)
    endpoint = Column(Text)
    calls = Column(Integer, default=1)
    tokens_prompt = Column(Integer, default=0)
    tokens_response = Column(Integer, default=0)
    tokens_total = Column(Integer, default=0)
    response_time_ms = Column(Integer, default=0)


class PortfolioState(Base):
    __tablename__ = "portfolio_state"
    id = Column(Integer, primary_key=True)
    total_capital = Column(Numeric(15, 2), nullable=False)
    last_updated = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_dashboard_update = Column(DateTime(timezone=True))
    last_run_timestamp = Column(DateTime(timezone=True))
    version = Column(Integer, nullable=False, default=1)

    __table_args__ = (CheckConstraint("id = 1"),)


class GitSyncState(Base):
    __tablename__ = "git_sync_state"
    id = Column(Integer, primary_key=True)
    last_git_push = Column(DateTime(timezone=True))
    pending_changes_count = Column(Integer, default=0)
    has_new_bets = Column(Boolean, default=False)
    has_new_rejections = Column(Boolean, default=False)
    has_bet_resolutions = Column(Boolean, default=False)

    __table_args__ = (CheckConstraint("id = 1"),)


class BetAnalysis(Base):
    __tablename__ = "bet_analysis"
    analysis_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    archive_id = Column(
        BigInteger, ForeignKey("archived_bets.archive_id"), nullable=False
    )

    ai_model = Column(Text, nullable=False)
    predicted_outcome = Column(Text, nullable=False)
    confidence = Column(Numeric(5, 4), nullable=False)
    reasoning = Column(Text)
    timestamp_analyzed = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    raw_response = Column(JSON)

    __table_args__ = (
        CheckConstraint("predicted_outcome IN ('YES', 'NO')"),
        CheckConstraint("confidence BETWEEN 0 AND 1"),
    )


class FinalPredictions(Base):
    __tablename__ = "final_predictions"
    prediction_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    archive_id = Column(
        BigInteger, ForeignKey("archived_bets.archive_id"), nullable=False, unique=True
    )
    aggregated_outcome = Column(Text, nullable=False)
    weighted_confidence = Column(Numeric(5, 4), nullable=False)
    models_used = Column(
        ARRAY(Text) if DATABASE_URL and DATABASE_URL.startswith("postgresql") else JSON,
        nullable=True,
    )
    weights_applied = Column(JSON)
    timestamp_created = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    version = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("aggregated_outcome IN ('YES', 'NO')"),
        CheckConstraint("weighted_confidence BETWEEN 0 AND 1"),
    )


class BetStatusHistory(Base):
    __tablename__ = "bet_status_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bet_id = Column(Integer, nullable=False, index=True)
    is_archived = Column(
        Boolean, default=False
    )  # True if bet_id refers to archived_bets.archive_id
    old_status = Column(Text, nullable=False)
    new_status = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
    profit_loss_at_time = Column(Numeric(10, 2), nullable=True)
    timestamp = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("idx_bet_timestamp", "bet_id", "timestamp"),)
