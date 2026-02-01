#!/usr/bin/env python3
"""
One-time migration from SQLite to PostgreSQL.
1. Reads existing SQLite data
2. Fetches missing url_slug from API
3. Writes to PostgreSQL
"""

import sqlite3
import requests
import logging
from datetime import datetime, timezone
from dateutil import parser
from db_models import (
    session_scope, engine, Base,
    ActiveBet, ArchivedBet, RejectedMarket,
    ApiUsage, PortfolioState, GitSyncState
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fetch_url_slug(market_slug: str) -> str:
    """Fetches url_slug from Polymarket API."""
    try:
        url = f"https://gamma-api.polymarket.com/markets/{market_slug}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get('slug', market_slug)
    except:
        pass
    return market_slug  # Fallback

def ensure_utc(dt_val):
    if dt_val is None:
        return None
    if isinstance(dt_val, str):
        try:
            dt = parser.parse(dt_val)
        except:
            return None
    elif isinstance(dt_val, datetime):
        dt = dt_val
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def migrate():
    # Create PostgreSQL tables
    Base.metadata.create_all(engine)

    db_path = 'polymarket.db'
    if not os.path.exists(db_path):
        logger.error(f"SQLite database {db_path} not found.")
        return

    # Read SQLite data
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    with session_scope() as session:
        # 1. Migrate active_bets
        logger.info("Migrating active_bets...")
        try:
            cursor.execute("SELECT * FROM active_bets WHERE status='OPEN'")
            rows = cursor.fetchall()
            for row in rows:
                url_slug = fetch_url_slug(row['market_slug'])
                bet = ActiveBet(
                    market_slug=row['market_slug'],
                    url_slug=url_slug,
                    question=row['question'],
                    action=row['action'],
                    stake_usdc=row['stake_usdc'],
                    entry_price=row['entry_price'],
                    ai_probability=row['ai_probability'],
                    confidence_score=row['confidence_score'],
                    expected_value=row['expected_value'],
                    edge=row.get('edge', 0.0) if 'edge' in row.keys() else 0.0,
                    ai_reasoning=row.get('ai_reasoning', '') if 'ai_reasoning' in row.keys() else '',
                    end_date=ensure_utc(row['end_date']),
                    timestamp_created=ensure_utc(row['timestamp_created']),
                    status='OPEN'
                )
                session.add(bet)
            session.commit() # Commit batch
        except Exception as e:
            logger.error(f"Error migrating active_bets: {e}")

        # 2. Migrate results (closed bets) -> archived_bets
        logger.info("Migrating results to archived_bets...")
        try:
            cursor.execute("SELECT * FROM results")
            rows = cursor.fetchall()
            for row in rows:
                # Need to fetch url slug too? Yes.
                url_slug = fetch_url_slug(row['market_slug'])

                # Try to find original bet ID but might be hard to map exactly if sequence changed.
                # Use result_id as reference or row['bet_id'].
                # Since Postgres uses BIGSERIAL, we can let it auto-inc archive_id.
                # But original_bet_id refers to active_bet.id which is GONE from active_bets.
                # We should just store the old ID or generate a new one.
                # The model says `original_bet_id` is NOT NULL and UNIQUE.
                # If multiple archives refer to same original ID (re-bet?), unique constraint might fail.
                # But typically 1 active -> 1 result.

                # Check keys for new columns
                edge = row['edge'] if 'edge' in row.keys() else 0.0
                ai_reasoning = row['ai_reasoning'] if 'ai_reasoning' in row.keys() else ''
                ai_probability = row['ai_probability'] if 'ai_probability' in row.keys() else 0.0
                confidence_score = row['confidence_score'] if 'confidence_score' in row.keys() else 0.0

                # End date? Results table doesn't have end_date usually?
                # SQLite schema: results has timestamp_created, timestamp_closed. No end_date.
                # ArchivedBet model has end_date. We can leave it NULL or try to fetch.
                # Leaving NULL for now.

                bet = ArchivedBet(
                    original_bet_id=row['bet_id'],
                    market_slug=row['market_slug'],
                    url_slug=url_slug,
                    question=row['question'],
                    action=row['action'],
                    stake_usdc=row['stake_usdc'],
                    entry_price=row['entry_price'],
                    ai_probability=ai_probability,
                    confidence_score=confidence_score,
                    edge=edge,
                    ai_reasoning=ai_reasoning,
                    timestamp_created=ensure_utc(row['timestamp_created']),
                    timestamp_archived=ensure_utc(row['timestamp_closed']), # Using closed time as archived time
                    end_date=None,
                    actual_outcome=row['actual_outcome'],
                    profit_loss=row['profit_loss'],
                    roi=row['roi'],
                    timestamp_resolved=ensure_utc(row['timestamp_closed'])
                )
                session.add(bet)
            session.commit()
        except Exception as e:
            logger.error(f"Error migrating results: {e}")

        # 3. Migrate rejected_markets
        logger.info("Migrating rejected_markets...")
        try:
            cursor.execute("SELECT * FROM rejected_markets")
            rows = cursor.fetchall()
            objs = []
            for row in rows:
                # Fetching URL slug for ALL rejections might be too much API spam.
                # Use market_slug as fallback.
                url_slug = row['market_slug']

                objs.append(RejectedMarket(
                    market_slug=row['market_slug'],
                    url_slug=url_slug,
                    question=row['question'],
                    market_price=row['market_price'],
                    volume=row['volume'],
                    ai_probability=row['ai_probability'],
                    confidence_score=row['confidence_score'],
                    edge=row['edge'],
                    rejection_reason=row['rejection_reason'],
                    ai_reasoning=row.get('ai_reasoning', '') if 'ai_reasoning' in row.keys() else '',
                    timestamp_analyzed=ensure_utc(row['timestamp_analyzed']),
                    end_date=ensure_utc(row.get('end_date')) if 'end_date' in row.keys() else None
                ))
                if len(objs) >= 100:
                    session.bulk_save_objects(objs)
                    objs = []
            if objs:
                session.bulk_save_objects(objs)
            session.commit()
        except Exception as e:
            logger.error(f"Error migrating rejected_markets: {e}")

        # 4. Migrate portfolio_state
        logger.info("Migrating portfolio_state...")
        try:
            cursor.execute("SELECT * FROM portfolio_state WHERE id=1")
            row = cursor.fetchone()
            if row:
                # Check keys
                last_dash = ensure_utc(row['last_dashboard_update']) if 'last_dashboard_update' in row.keys() else None
                last_run = ensure_utc(row['last_run_timestamp']) if 'last_run_timestamp' in row.keys() else None

                # Check if exists in PG (init_database might have created it)
                existing = session.query(PortfolioState).filter_by(id=1).first()
                if existing:
                    existing.total_capital = row['total_capital']
                    existing.last_updated = ensure_utc(row['last_updated'])
                    existing.last_dashboard_update = last_dash
                    existing.last_run_timestamp = last_run
                else:
                    pf = PortfolioState(
                        id=1,
                        total_capital=row['total_capital'],
                        last_updated=ensure_utc(row['last_updated']),
                        last_dashboard_update=last_dash,
                        last_run_timestamp=last_run
                    )
                    session.add(pf)
                session.commit()
        except Exception as e:
            logger.error(f"Error migrating portfolio_state: {e}")

        # 5. Migrate api_usage
        logger.info("Migrating api_usage...")
        try:
            cursor.execute("SELECT * FROM api_usage")
            rows = cursor.fetchall()
            objs = []
            for row in rows:
                objs.append(ApiUsage(
                    timestamp=ensure_utc(row['timestamp']),
                    api_name=row['api_name'],
                    endpoint=row.get('endpoint'),
                    calls=row.get('calls', 1),
                    tokens_prompt=row.get('tokens_prompt', 0),
                    tokens_response=row.get('tokens_response', 0),
                    tokens_total=row.get('tokens_total', 0),
                    response_time_ms=row.get('response_time_ms', 0)
                ))
                if len(objs) >= 500:
                    session.bulk_save_objects(objs)
                    objs = []
            if objs:
                session.bulk_save_objects(objs)
            session.commit()
        except Exception as e:
            logger.error(f"Error migrating api_usage: {e}")

        # 6. Migrate git_sync_state
        logger.info("Migrating git_sync_state...")
        try:
            cursor.execute("SELECT * FROM git_sync_state WHERE id=1")
            row = cursor.fetchone()
            if row:
                existing = session.query(GitSyncState).filter_by(id=1).first()
                if existing:
                    existing.last_git_push = ensure_utc(row['last_git_push'])
                    existing.pending_changes_count = row['pending_changes_count']
                    existing.has_new_bets = row['has_new_bets'] if 'has_new_bets' in row.keys() else False
                    existing.has_new_rejections = row['has_new_rejections'] if 'has_new_rejections' in row.keys() else False
                    existing.has_bet_resolutions = row['has_bet_resolutions'] if 'has_bet_resolutions' in row.keys() else False
                else:
                    gs = GitSyncState(
                        id=1,
                        last_git_push=ensure_utc(row['last_git_push']),
                        pending_changes_count=row['pending_changes_count'],
                        has_new_bets=row.get('has_new_bets', False),
                        has_new_rejections=row.get('has_new_rejections', False),
                        has_bet_resolutions=row.get('has_bet_resolutions', False)
                    )
                    session.add(gs)
                session.commit()
        except Exception as e:
            logger.error(f"Error migrating git_sync_state: {e}")

    conn.close()
    print("✅ Migration complete")

import os
if __name__ == "__main__":
    migrate()
