import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, text, update
from sqlalchemy.orm import Session

from src.db_models import (
    ActiveBet,
    ApiUsage,
    ArchivedBet,
    Base,
    GitSyncState,
    PortfolioState,
    RejectedMarket,
    engine,
    session_scope,
)

# Configuration
INITIAL_CAPITAL = 1000.0

# Logging
logger = logging.getLogger(__name__)


def init_database():
    """Initializes the database with required tables and default values.

    Creates all tables defined in SQLAlchemy models if they don't exist.
    Also initializes the 'portfolio_state' with default capital if empty.

    Raises:
        SQLAlchemyError: If table creation fails.
    """
    try:
        # Create tables
        Base.metadata.create_all(engine)

        # Migrate api_usage table if needed
        migrate_api_usage_table()

        with session_scope() as session:
            # Initialize Portfolio State
            if session.query(PortfolioState).count() == 0:
                init_portfolio = PortfolioState(
                    id=1,
                    total_capital=INITIAL_CAPITAL,
                    last_updated=datetime.now(timezone.utc),
                )
                session.add(init_portfolio)
                logger.info(f"Initialized portfolio with ${INITIAL_CAPITAL} USDC")

            # Initialize Git Sync State
            if session.query(GitSyncState).count() == 0:
                init_git = GitSyncState(
                    id=1,
                    last_git_push=datetime.now(timezone.utc),
                    pending_changes_count=0,
                )
                session.add(init_git)

        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise


def migrate_api_usage_table():
    """Migrates api_usage table to ensure proper AUTOINCREMENT."""
    from src.db_models import ApiUsage

    try:
        with engine.connect() as conn:
            # Check if table exists
            result = conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='api_usage'"
                )
            )
            if result.fetchone():
                # Check current schema
                # SQLite doesn't expose AUTOINCREMENT in PRAGMA, need to check sql definition
                table_sql = conn.execute(
                    text(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name='api_usage'"
                    )
                ).fetchone()

                # If table doesn't have AUTOINCREMENT, migrate it
                if table_sql and "AUTOINCREMENT" not in table_sql[0]:
                    # Drop backup if exists
                    conn.execute(text("DROP TABLE IF EXISTS api_usage_backup"))
                    conn.commit()

                    # Rename existing table to backup
                    conn.execute(
                        text("ALTER TABLE api_usage RENAME TO api_usage_backup")
                    )
                    conn.commit()

                    # Recreate with proper schema
                    ApiUsage.__table__.create(engine, checkfirst=False)

                    # Restore data
                    conn.execute(text("""
                        INSERT INTO api_usage (timestamp, api_name, endpoint, calls,
                                              tokens_prompt, tokens_response, tokens_total, response_time_ms)
                        SELECT timestamp, api_name, endpoint, calls,
                               tokens_prompt, tokens_response, tokens_total, response_time_ms
                        FROM api_usage_backup
                    """))
                    conn.execute(text("DROP TABLE api_usage_backup"))
                    conn.commit()

                    logger.info("api_usage table migration completed successfully.")
                else:
                    logger.info("api_usage table already has correct schema.")

    except Exception as e:
        logger.error(f"Error migrating api_usage table: {e}")
        raise


def to_dict(obj) -> Dict[str, Any]:
    """Helper to convert SQLAlchemy object to dict."""
    if not obj:
        return {}
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def get_db_connection():
    """Legacy wrapper for compatibility, though distinct from session_scope."""
    return session_scope()


def get_current_capital() -> float:
    """Reads current capital from portfolio_state."""
    with session_scope() as session:
        state = session.query(PortfolioState).filter_by(id=1).first()
        if state:
            return float(state.total_capital)
        return INITIAL_CAPITAL


def update_capital(new_capital: float):
    """Updates total capital in portfolio_state (Atomic/Optimistic)."""
    with session_scope() as session:
        session.execute(
            update(PortfolioState)
            .where(PortfolioState.id == 1)
            .values(
                total_capital=new_capital,
                last_updated=datetime.now(timezone.utc),
                version=PortfolioState.version + 1,
            )
        )
        logger.info(f"Capital updated to ${new_capital:.2f}")


def insert_active_bet(bet_data: Dict[str, Any]):
    """Records a new active bet in the database.

    Args:
        bet_data: A dictionary containing bet details (market_slug, question,
            stake_usdc, etc.).
    """
    with session_scope() as session:
        bet = ActiveBet(
            market_slug=bet_data["market_slug"],
            url_slug=bet_data.get(
                "url_slug", bet_data["market_slug"]
            ),  # Fallback if missing
            question=bet_data["question"],
            action=bet_data["action"],
            stake_usdc=bet_data["stake_usdc"],
            entry_price=bet_data["entry_price"],
            ai_probability=bet_data["ai_probability"],
            confidence_score=bet_data["confidence_score"],
            expected_value=bet_data["expected_value"],
            edge=bet_data.get("edge", 0.0),
            ai_reasoning=bet_data.get("ai_reasoning", ""),
            end_date=bet_data.get(
                "end_date"
            ),  # Expecting datetime object or ISO string
            timestamp_created=datetime.now(timezone.utc),
            status="OPEN",
        )
        # Handle string date if passed
        if isinstance(bet.end_date, str):
            from dateutil import parser

            bet.end_date = parser.parse(bet.end_date)
            if bet.end_date.tzinfo is None:
                bet.end_date = bet.end_date.replace(tzinfo=timezone.utc)

        session.add(bet)
        # session.commit() handled by context manager

        # Mark for git sync (needs new session or nested transaction if calling another function using session_scope,
        # but mark_git_change uses session_scope which handles new session. Commit here is implicit by context manager exit)

    mark_git_change("bet")
    edge_pct = bet_data.get("edge", 0) * 100
    logger.info(
        f"New bet recorded: {bet_data['question'][:30]}... (${bet_data['stake_usdc']}, Edge: {edge_pct:+.1f}%)"
    )


def get_active_bets() -> List[Dict[str, Any]]:
    """Retrieves all currently active (open) bets.

    Returns:
        A list of dictionaries representing active bets.
    """
    with session_scope() as session:
        bets = session.query(ActiveBet).filter(ActiveBet.status == "OPEN").all()
        return [to_dict(b) for b in bets]


def close_bet(
    bet_id: int, outcome: str, profit_loss: float, conn: Optional[Session] = None
):
    """Closes an active bet and records the result.

    Moves the bet from 'active_bets' to 'archived_bets', records the outcome
    and P/L, and updates the global capital atomically.

    Args:
        bet_id: The ID of the bet to close.
        outcome: The resolved outcome ('YES' or 'NO').
        profit_loss: The realized profit or loss in USDC.
        conn: Optional existing SQLAlchemy session to use (for transactions).
    """

    # Inner function to perform logic with a given session
    def _perform_close(session: Session):
        bet = (
            session.query(ActiveBet).filter_by(bet_id=bet_id).with_for_update().first()
        )
        if not bet:
            logger.error(f"Bet {bet_id} not found!")
            return

        # Calculate ROI
        roi = (profit_loss / float(bet.stake_usdc)) if bet.stake_usdc > 0 else 0.0

        # Archive
        archived = ArchivedBet(
            original_bet_id=bet.bet_id,
            market_slug=bet.market_slug,
            url_slug=bet.url_slug,
            question=bet.question,
            action=bet.action,
            stake_usdc=bet.stake_usdc,
            entry_price=bet.entry_price,
            ai_probability=bet.ai_probability,
            confidence_score=bet.confidence_score,
            edge=bet.edge,
            ai_reasoning=bet.ai_reasoning,
            timestamp_created=bet.timestamp_created,
            end_date=bet.end_date,
            actual_outcome=outcome,
            profit_loss=profit_loss,
            roi=roi,
            timestamp_resolved=datetime.now(timezone.utc),
        )
        session.add(archived)

        # Delete from active
        # Schema suggests moving to archived implies active removal.
        # Original code kept 'results' table and 'active_bets' with status 'CLOSED'.
        # New prompt schema: 'active_bets' and 'archived_bets'.
        # Prompt says: "Moves a bet from active_bets to results".
        # Prompt for `archive_bet_without_resolution` says "session.delete(bet) # Remove from active".
        # So I will DELETE from active_bets.
        session.delete(bet)

        # Atomic Capital Update
        session.execute(
            text(
                "UPDATE portfolio_state SET total_capital = total_capital + :pl, version = version + 1 WHERE id = 1"
            ),
            {"pl": profit_loss},
        )

        # Fetch new capital for logging
        new_capital = session.query(PortfolioState.total_capital).scalar()

        logger.info(
            f"Bet {bet_id} closed. AI predicted {bet.action} ({float(bet.ai_probability)*100:.0f}%), "
            f"Actual: {outcome}. P/L: ${profit_loss:.2f}. New Capital: ${new_capital:.2f}"
        )

    if conn:
        _perform_close(conn)
        # Caller manages commit if conn is passed
    else:
        with session_scope() as session:
            _perform_close(session)
            # session.commit()

    mark_git_change("resolution")


def archive_bet_without_resolution(bet_id: int):
    """Archives expired bet without resolution."""
    with session_scope() as session:
        bet = (
            session.query(ActiveBet).filter_by(bet_id=bet_id).with_for_update().first()
        )
        if not bet:
            return

        archived = ArchivedBet(
            original_bet_id=bet.bet_id,
            market_slug=bet.market_slug,
            url_slug=bet.url_slug,
            question=bet.question,
            action=bet.action,
            stake_usdc=bet.stake_usdc,
            entry_price=bet.entry_price,
            ai_probability=bet.ai_probability,
            confidence_score=bet.confidence_score,
            edge=bet.edge,
            ai_reasoning=bet.ai_reasoning,
            timestamp_created=bet.timestamp_created,
            end_date=bet.end_date,
            actual_outcome=None,  # UNRESOLVED implicit or explicit? Schema says check IN ('YES', 'NO', 'UNRESOLVED') or null?
            # Schema: actual_outcome TEXT CHECK ...
            # Let's set it to 'UNRESOLVED' or None. Prompt code example set actual_outcome=None.
            # But the CHECK constraint allows 'UNRESOLVED'.
            # If I set None, it might fail check if NOT NULL is there?
            # Schema: "actual_outcome TEXT CHECK (actual_outcome IN ('YES', 'NO', 'UNRESOLVED'))"
            # It does NOT say NOT NULL.
            # However, prompt `archive_bet_without_resolution` sample code set `actual_outcome=None`.
            # I will follow prompt code.
            profit_loss=None,
            roi=None,
            timestamp_resolved=None,
        )
        session.add(archived)
        session.delete(bet)
        logger.info(f"Archived expired bet {bet_id} without resolution.")


def get_all_results() -> List[Dict[str, Any]]:
    """Retrieves all closed bets (archived)."""
    with session_scope() as session:
        results = (
            session.query(ArchivedBet)
            .order_by(ArchivedBet.timestamp_resolved.desc().nulls_last())
            .all()
        )
        # Filter for those that have been resolved if needed, or return all archived?
        # Function name is get_all_results, used for metrics. Metrics need P/L.
        # So we should probably filter out those with profit_loss IS NULL.
        filtered = [to_dict(r) for r in results if r.profit_loss is not None]
        # For compatibility with legacy code which expects 'timestamp_closed', mapping timestamp_resolved
        for r in filtered:
            r["timestamp_closed"] = r.get("timestamp_resolved")
        return filtered


def get_results_with_metrics() -> List[Dict[str, Any]]:
    """
    Holt alle Results mit berechneten Metriken.
    """
    with session_scope() as session:
        # We can calculate days_held in python or SQL.
        results = (
            session.query(ArchivedBet)
            .filter(ArchivedBet.profit_loss.is_not(None))
            .order_by(ArchivedBet.timestamp_resolved.desc())
            .all()
        )
        data = []
        for r in results:
            d = to_dict(r)
            d["timestamp_closed"] = d.get("timestamp_resolved")
            if d["timestamp_closed"] and d["timestamp_created"]:
                # Ensure timezones are compatible
                created = d["timestamp_created"]
                closed = d["timestamp_closed"]
                d["computed_days_held"] = (closed - created).days
            else:
                d["computed_days_held"] = 0
            data.append(d)
        return data


def get_capital_history() -> List[Tuple[datetime, float]]:
    """
    Gibt Zeitreihe von (timestamp, capital) zurück.
    """
    with session_scope() as session:
        results = (
            session.query(ArchivedBet.timestamp_resolved, ArchivedBet.profit_loss)
            .filter(ArchivedBet.profit_loss.is_not(None))
            .order_by(ArchivedBet.timestamp_resolved.asc())
            .all()
        )

        history = [(datetime.now(timezone.utc) - timedelta(days=365), INITIAL_CAPITAL)]
        running_capital = INITIAL_CAPITAL
        for ts, pl in results:
            running_capital += float(pl)
            history.append((ts, running_capital))

        return history


def insert_rejected_market(market_data: Dict[str, Any]):
    """Loggt abgelehnte Märkte."""
    with session_scope() as session:
        rej = RejectedMarket(
            market_slug=market_data["market_slug"],
            url_slug=market_data.get("url_slug", market_data["market_slug"]),
            question=market_data["question"],
            market_price=market_data["market_price"],
            volume=market_data["volume"],
            ai_probability=market_data["ai_probability"],
            confidence_score=market_data["confidence_score"],
            edge=market_data["edge"],
            rejection_reason=market_data["rejection_reason"],
            ai_reasoning=market_data.get("ai_reasoning", ""),
            timestamp_analyzed=datetime.now(timezone.utc),
            end_date=market_data.get("end_date"),
        )
        if isinstance(rej.end_date, str):
            from dateutil import parser

            try:
                rej.end_date = parser.parse(rej.end_date)
                if rej.end_date.tzinfo is None:
                    rej.end_date = rej.end_date.replace(tzinfo=timezone.utc)
            except Exception:
                rej.end_date = None

        session.add(rej)

    mark_git_change("rejection")
    logger.info(
        f"Rejected market logged: {market_data['question'][:40]}... (Reason: {market_data['rejection_reason']})"
    )


def insert_rejected_markets_batch(markets: List[Dict[str, Any]]):
    """Batch insert rejected markets."""
    if not markets:
        return

    with session_scope() as session:
        for m in markets:
            end_date = m.get("end_date")
            if isinstance(end_date, str):
                from dateutil import parser

                try:
                    end_date = parser.parse(end_date)
                    if end_date.tzinfo is None:
                        end_date = end_date.replace(tzinfo=timezone.utc)
                except Exception:
                    end_date = None

            rej = RejectedMarket(
                market_slug=m["market_slug"],
                url_slug=m.get("url_slug", m["market_slug"]),
                question=m["question"],
                market_price=m["market_price"],
                volume=m["volume"],
                ai_probability=m["ai_probability"],
                confidence_score=m["confidence_score"],
                edge=m["edge"],
                rejection_reason=m["rejection_reason"],
                ai_reasoning=m.get("ai_reasoning", ""),
                timestamp_analyzed=datetime.now(timezone.utc),
                end_date=end_date,
            )
            session.add(rej)  # Triggers AUTOINCREMENT

    mark_git_change("rejection")
    logger.info(f"Batch inserted {len(markets)} rejected markets.")


def get_rejected_markets(limit: int = 50) -> List[Dict[str, Any]]:
    """Holt letzte abgelehnte Märkte."""
    with session_scope() as session:
        markets = (
            session.query(RejectedMarket)
            .order_by(RejectedMarket.timestamp_analyzed.desc())
            .limit(limit)
            .all()
        )
        return [to_dict(m) for m in markets]


def calculate_metrics() -> Dict[str, Any]:
    """Calculates performance metrics."""
    results = get_all_results()

    if not results:
        return {
            "total_bets": 0,
            "win_rate": 0.0,
            "avg_roi": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "total_return_usd": 0.0,
            "total_return_percent": 0.0,
            "best_bet_usd": 0.0,
            "worst_bet_usd": 0.0,
        }

    wins = 0
    total_roi = 0.0
    returns = []
    capital_curve = [INITIAL_CAPITAL]
    current_cap = INITIAL_CAPITAL

    best_bet = -float("inf")
    worst_bet = float("inf")
    total_pl = 0.0

    # Sort results by closed time
    sorted_results = sorted(
        results,
        key=lambda x: x["timestamp_closed"]
        or datetime.min.replace(tzinfo=timezone.utc),
    )

    for res in sorted_results:
        pl = float(res["profit_loss"])
        total_pl += pl
        if pl > 0:
            wins += 1

        roi = float(res["roi"])
        total_roi += roi
        returns.append(roi)

        current_cap += pl
        capital_curve.append(current_cap)

        if pl > best_bet:
            best_bet = pl
        if pl < worst_bet:
            worst_bet = pl

    total_bets = len(results)
    win_rate = wins / total_bets
    avg_roi = total_roi / total_bets

    # Sharpe Ratio
    if total_bets > 1:
        mean_return = sum(returns) / total_bets
        variance = sum((x - mean_return) ** 2 for x in returns) / (total_bets - 1)
        std_dev = math.sqrt(variance)
        sharpe = (mean_return / std_dev) if std_dev > 0 else 0.0
    else:
        sharpe = 0.0

    # Max Drawdown
    peak = capital_curve[0]
    max_dd = 0.0

    for val in capital_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak
        if dd > max_dd:
            max_dd = dd

    total_return_usd = current_cap - INITIAL_CAPITAL
    total_return_percent = total_return_usd / INITIAL_CAPITAL

    return {
        "total_bets": total_bets,
        "win_rate": win_rate,
        "avg_roi": avg_roi,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "total_return_usd": total_return_usd,
        "total_return_percent": total_return_percent,
        "best_bet_usd": best_bet if total_bets > 0 else 0.0,
        "worst_bet_usd": worst_bet if total_bets > 0 else 0.0,
    }


def update_last_dashboard_update():
    with session_scope() as session:
        session.execute(
            update(PortfolioState)
            .where(PortfolioState.id == 1)
            .values(last_dashboard_update=datetime.now(timezone.utc))
        )


def get_last_dashboard_update() -> Optional[datetime]:
    with session_scope() as session:
        state = session.query(PortfolioState).filter_by(id=1).first()
        if state:
            return state.last_dashboard_update
        return None


def log_api_usage(
    api_name: str,
    endpoint: str,
    tokens_prompt: int,
    tokens_response: int,
    response_time_ms: int,
):
    """Log API usage to the database."""
    with session_scope() as session:
        usage = ApiUsage(
            api_name=api_name,
            endpoint=endpoint,
            calls=1,
            tokens_prompt=tokens_prompt,
            tokens_response=tokens_response,
            tokens_total=tokens_prompt + tokens_response,
            response_time_ms=response_time_ms,
        )
        session.add(usage)


def get_api_usage_rpm(api_name: str = "gemini") -> int:
    """Returns number of API calls in the last minute."""
    with session_scope() as session:
        one_min_ago = datetime.now(timezone.utc) - timedelta(minutes=1)
        count = (
            session.query(func.sum(ApiUsage.calls))
            .filter(ApiUsage.api_name == api_name, ApiUsage.timestamp >= one_min_ago)
            .scalar()
        )
        return count or 0


def get_api_usage_rpd(api_name: str = "gemini") -> int:
    """Returns number of API calls today (UTC based)."""
    with session_scope() as session:
        now_utc = datetime.now(timezone.utc)
        start_of_day = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        count = (
            session.query(func.sum(ApiUsage.calls))
            .filter(ApiUsage.api_name == api_name, ApiUsage.timestamp >= start_of_day)
            .scalar()
        )
        return count or 0


def get_api_usage_tpm(api_name: str = "gemini") -> int:
    """Returns sum of tokens in the last minute."""
    with session_scope() as session:
        one_min_ago = datetime.now(timezone.utc) - timedelta(minutes=1)
        tokens = (
            session.query(func.sum(ApiUsage.tokens_total))
            .filter(ApiUsage.api_name == api_name, ApiUsage.timestamp >= one_min_ago)
            .scalar()
        )
        return tokens or 0


def get_last_run_timestamp() -> Optional[datetime]:
    """Reads last run timestamp from DB."""
    with session_scope() as session:
        state = session.query(PortfolioState).filter_by(id=1).first()
        if state:
            return state.last_run_timestamp
        return None


def set_last_run_timestamp(timestamp: datetime):
    """Saves last run timestamp."""
    with session_scope() as session:
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        session.execute(
            update(PortfolioState)
            .where(PortfolioState.id == 1)
            .values(last_run_timestamp=timestamp)
        )


# ============================================================================
# GIT SYNC HELPERS
# ============================================================================


def mark_git_change(change_type: str):
    """
    Markiert eine Änderung für Git-Push.
    change_type: 'bet', 'rejection', 'resolution'
    """
    with session_scope() as session:
        field_map = {
            "bet": "has_new_bets",
            "rejection": "has_new_rejections",
            "resolution": "has_bet_resolutions",
        }
        field = field_map.get(change_type)
        if field:
            # Need to build update dict dynamically or use raw sql
            # Using raw sql for simplicity with field name variable
            sql = text(f"""
                UPDATE git_sync_state
                SET {field} = true, pending_changes_count = pending_changes_count + 1
                WHERE id = 1
            """)
            session.execute(sql)


def should_push_to_git() -> bool:
    """
    Prüft ob Git-Push nötig ist (mind. 1h seit letztem Push UND Änderungen vorhanden).
    """
    with session_scope() as session:
        state = session.query(GitSyncState).filter_by(id=1).first()
        if not state:
            return False

        if state.pending_changes_count == 0:
            return False

        last_push = state.last_git_push
        if not last_push:
            return True

        # Ensure UTC
        if last_push.tzinfo is None:
            last_push = last_push.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) - last_push >= timedelta(hours=1):
            return True

        return False


def has_ai_decisions_changes() -> bool:
    """Prüft ob AI_DECISIONS.md relevante Änderungen hat."""
    with session_scope() as session:
        state = session.query(GitSyncState).filter_by(id=1).first()
        if not state:
            return False
        return any(
            [state.has_new_bets, state.has_new_rejections, state.has_bet_resolutions]
        )


def reset_git_sync_flags():
    """Setzt Flags nach erfolgreichem Push zurück."""
    with session_scope() as session:
        session.execute(
            update(GitSyncState)
            .where(GitSyncState.id == 1)
            .values(
                last_git_push=datetime.now(timezone.utc),
                pending_changes_count=0,
                has_new_bets=False,
                has_new_rejections=False,
                has_bet_resolutions=False,
            )
        )


def get_unresolved_archived_bets() -> List[Dict[str, Any]]:
    """Retrieves archived bets that are unresolved and older than 24h."""
    with session_scope() as session:
        cutoff = datetime.now(timezone.utc) - timedelta(days=1)
        bets = (
            session.query(ArchivedBet)
            .filter(ArchivedBet.actual_outcome.is_(None), ArchivedBet.end_date < cutoff)
            .all()
        )
        return [to_dict(b) for b in bets]


def get_all_unresolved_bets() -> List[Dict[str, Any]]:
    """Retrieves all archived bets that are unresolved (for dashboard)."""
    with session_scope() as session:
        bets = (
            session.query(ArchivedBet)
            .filter(ArchivedBet.actual_outcome.is_(None))
            .all()
        )
        return [to_dict(b) for b in bets]


def update_archived_bet_outcome(archive_id: int, outcome: str, profit_loss: float):
    """Updates an archived bet with the final outcome."""
    with session_scope() as session:
        bet = (
            session.query(ArchivedBet)
            .filter_by(archive_id=archive_id)
            .with_for_update()
            .first()
        )
        if not bet:
            return

        roi = (profit_loss / float(bet.stake_usdc)) if bet.stake_usdc > 0 else 0.0

        bet.actual_outcome = outcome
        bet.profit_loss = profit_loss
        bet.roi = roi
        bet.timestamp_resolved = datetime.now(timezone.utc)

        # Update capital (since it wasn't updated when archived without resolution)
        session.execute(
            text(
                "UPDATE portfolio_state SET total_capital = total_capital + :pl, version = version + 1 WHERE id = 1"
            ),
            {"pl": profit_loss},
        )

    mark_git_change("resolution")
    logger.info(
        f"Archived Bet {archive_id} resolved: {outcome} (P/L: ${profit_loss:.2f})"
    )
