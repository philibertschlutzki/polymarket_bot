"""
Advanced Analytics Module für Polymarket Bot
Berechnet erweiterte Metriken für Dashboard-Optimierung
"""

import logging
from datetime import timedelta
from typing import Any, Dict, List, Tuple, cast

from src.dashboard import to_cet

logger = logging.getLogger(__name__)

# ============================================================================
# 1. CONFIDENCE CALIBRATION ANALYSIS
# ============================================================================


def calculate_confidence_calibration(results: List) -> Dict[str, Any]:
    """
    Analysiert Kalibrierung der AI Confidence Scores.

    Returns:
        {
            'buckets': [
                {
                    'range': '90-100%',
                    'predicted_win_rate': 0.95,
                    'actual_win_rate': 0.92,
                    'num_bets': 12,
                    'calibration_error': -0.03,
                    'status': 'well_calibrated'
                },
                ...
            ],
            'overall_calibration': 0.92  # 0-1 score
        }
    """

    # Define 5 confidence buckets
    buckets = [
        (0.90, 1.00, "90-100%"),
        (0.80, 0.90, "80-90%"),
        (0.70, 0.80, "70-80%"),
        (0.60, 0.70, "60-70%"),
        (0.00, 0.60, "<60%"),
    ]

    bucket_data = []

    for min_conf, max_conf, label in buckets:
        # Filter results in this bucket
        bucket_results = []
        for r in results:
            # Handle sqlite3.Row or dict
            conf = r["confidence_score"] if "confidence_score" in r.keys() else None

            if conf is not None and min_conf <= conf < max_conf:
                bucket_results.append(r)

        if not bucket_results:
            bucket_data.append(
                {
                    "range": label,
                    "predicted_win_rate": (min_conf + max_conf) / 2,
                    "actual_win_rate": None,
                    "num_bets": 0,
                    "calibration_error": None,
                    "status": "insufficient_data",
                }
            )
            continue

        # Calculate metrics
        num_bets = len(bucket_results)
        avg_predicted = sum(r["confidence_score"] for r in bucket_results) / num_bets

        # Actual win rate (bet matched outcome)
        wins = sum(1 for r in bucket_results if r["action"] == r["actual_outcome"])
        actual_win_rate = wins / num_bets

        calibration_error = actual_win_rate - avg_predicted

        # Status determination
        if abs(calibration_error) <= 0.05:
            status = "well_calibrated"
        elif abs(calibration_error) <= 0.10:
            status = "acceptable"
        else:
            status = "overconfident" if calibration_error < 0 else "underconfident"

        bucket_data.append(
            {
                "range": label,
                "predicted_win_rate": avg_predicted,
                "actual_win_rate": actual_win_rate,
                "num_bets": num_bets,
                "calibration_error": calibration_error,
                "status": status,
            }
        )

    # Overall calibration score (weighted by number of bets)
    total_bets = sum(cast(int, b["num_bets"]) for b in bucket_data)
    if total_bets > 0:
        weighted_error = (
            sum(
                abs(cast(float, b["calibration_error"])) * cast(int, b["num_bets"])
                for b in bucket_data
                if b["calibration_error"] is not None
            )
            / total_bets
        )
        overall_calibration = 1.0 - weighted_error  # 1.0 = perfect
    else:
        overall_calibration = 0.0

    return {"buckets": bucket_data, "overall_calibration": overall_calibration}


# ============================================================================
# 2. EDGE VALIDATION ANALYSIS
# ============================================================================


def calculate_edge_validation(results: List, min_bets: int = 10) -> Dict[str, Any]:
    """
    Vergleicht predicted edge vs realized edge.

    Args:
        results: List of closed bets
        min_bets: Minimum bets in bucket to show data

    Returns:
        {
            'buckets': [
                {
                    'range': '+30% or more',
                    'avg_predicted_edge': 0.352,
                    'avg_realized_edge': 0.281,
                    'delta': -0.071,
                    'accuracy': 0.80,
                    'num_bets': 15,
                    'status': 'sufficient_data'
                },
                ...
            ],
            'overall_accuracy': 0.89
        }
    """

    # Define edge buckets
    buckets = [
        (0.30, float("inf"), "+30% or more"),
        (0.20, 0.30, "+20% to +30%"),
        (0.10, 0.20, "+10% to +20%"),
        (0.00, 0.10, "+0% to +10%"),
        (-0.10, 0.00, "-0% to -10%"),
        (-float("inf"), -0.10, "-10% or less"),
    ]

    bucket_data = []

    for min_edge, max_edge, label in buckets:
        # Filter results with edge data
        bucket_results = []
        for r in results:
            edge = r["edge"] if "edge" in r.keys() else None

            if edge is not None and min_edge <= edge < max_edge:
                bucket_results.append(r)

        num_bets = len(bucket_results)

        if num_bets < min_bets:
            bucket_data.append(
                {
                    "range": label,
                    "avg_predicted_edge": None,
                    "avg_realized_edge": None,
                    "delta": None,
                    "accuracy": None,
                    "num_bets": num_bets,
                    "status": "insufficient_data",
                }
            )
            continue

        # Calculate predicted edge (stored in DB)
        avg_predicted_edge = sum(r["edge"] for r in bucket_results) / num_bets

        # Calculate realized edge
        # Realized edge = actual probability of correct prediction
        wins = sum(1 for r in bucket_results if r["action"] == r["actual_outcome"])
        realized_win_rate = wins / num_bets

        # For YES bets: realized_edge = win_rate - entry_price
        # Simplified: Use win_rate as proxy for realized probability
        avg_market_price = sum(r["entry_price"] for r in bucket_results) / num_bets
        avg_realized_edge = realized_win_rate - avg_market_price

        delta = avg_realized_edge - avg_predicted_edge

        # Accuracy: How close is realized to predicted (0-1 scale)
        accuracy = 1.0 - min(abs(delta) / max(abs(avg_predicted_edge), 0.01), 1.0)

        bucket_data.append(
            {
                "range": label,
                "avg_predicted_edge": avg_predicted_edge,
                "avg_realized_edge": avg_realized_edge,
                "delta": delta,
                "accuracy": accuracy,
                "num_bets": num_bets,
                "status": "sufficient_data",
            }
        )

    # Overall accuracy
    valid_buckets = [b for b in bucket_data if b["accuracy"] is not None]
    if valid_buckets:
        total_bets = sum(cast(int, b["num_bets"]) for b in valid_buckets)
        overall_accuracy = (
            sum(
                cast(float, b["accuracy"]) * cast(int, b["num_bets"])
                for b in valid_buckets
            )
            / total_bets
        )
    else:
        overall_accuracy = 0.0

    return {"buckets": bucket_data, "overall_accuracy": overall_accuracy}


# ============================================================================
# 3. AI MODEL PERFORMANCE TRENDS
# ============================================================================


def calculate_model_trends(
    results: List, window_days: int = 30, num_periods: int = 8
) -> Dict[str, Any]:
    """
    Berechnet Rolling Performance Metrics über Zeit.

    Args:
        results: List of closed bets (sorted by timestamp)
        window_days: Rolling window size (default 30 days)
        num_periods: Number of periods to display

    Returns:
        {
            'periods': [
                {
                    'period_label': 'Week 1',
                    'start_date': '2026-01-01',
                    'end_date': '2026-01-08',
                    'win_rate': 0.583,
                    'avg_confidence': 0.72,
                    'calibration_score': 0.81,
                    'num_bets': 12
                },
                ...
            ],
            'trend_direction': 'improving'  # improving, declining, stable
        }
    """

    if not results:
        return {"periods": [], "trend_direction": "insufficient_data"}

    # Sort by close time
    sorted_results = sorted(results, key=lambda x: x["timestamp_closed"])

    # Get date range
    first_date = to_cet(sorted_results[0]["timestamp_closed"])
    last_date = to_cet(sorted_results[-1]["timestamp_closed"])

    if not first_date or not last_date:
        return {"periods": [], "trend_direction": "error"}

    # Calculate periods (weekly for 8 weeks)
    periods = []
    period_duration = timedelta(days=7)

    for i in range(num_periods):
        period_end = last_date - (i * period_duration)
        period_start = period_end - timedelta(days=window_days)

        # Filter results in rolling window
        period_results = [
            r
            for r in sorted_results
            if to_cet(r["timestamp_closed"]) is not None
            and period_start <= to_cet(r["timestamp_closed"]) <= period_end
        ]

        if not period_results:
            continue

        # Calculate metrics
        num_bets = len(period_results)
        wins = sum(1 for r in period_results if r["action"] == r["actual_outcome"])
        win_rate = wins / num_bets

        avg_confidence = (
            sum(
                (
                    r["confidence_score"]
                    if "confidence_score" in r.keys()
                    and r["confidence_score"] is not None
                    else 0
                )
                for r in period_results
            )
            / num_bets
        )

        # Simple calibration: 1 - |win_rate - avg_confidence|
        calibration_score = 1.0 - abs(win_rate - avg_confidence)

        periods.append(
            {
                "period_label": f"Week {num_periods - i}",
                "start_date": period_start.strftime("%Y-%m-%d"),
                "end_date": period_end.strftime("%Y-%m-%d"),
                "win_rate": win_rate,
                "avg_confidence": avg_confidence,
                "calibration_score": calibration_score,
                "num_bets": num_bets,
            }
        )

    # Reverse to chronological order
    periods.reverse()

    # Determine trend
    if len(periods) >= 3:
        recent_wr = sum(p["win_rate"] for p in periods[-3:]) / 3
        older_wr = sum(p["win_rate"] for p in periods[:3]) / 3

        if recent_wr > older_wr + 0.05:
            trend_direction = "improving"
        elif recent_wr < older_wr - 0.05:
            trend_direction = "declining"
        else:
            trend_direction = "stable"
    else:
        trend_direction = "insufficient_data"

    return {"periods": periods, "trend_direction": trend_direction}


# ============================================================================
# 4. DRAWDOWN ANALYSIS
# ============================================================================


def calculate_drawdown_metrics(  # noqa: C901
    capital_history: List[Tuple[Any, float]],
) -> Dict[str, Any]:
    """
    Berechnet Drawdown-Metriken.

    Args:
        capital_history: List of (timestamp, capital) tuples

    Returns:
        {
            'current_drawdown_pct': -0.023,
            'current_drawdown_days': 3,
            'peak_capital': 1023.50,
            'current_capital': 1000.00,
            'max_historical_dd': -0.085,
            'max_dd_recovery_days': 12,
            'status': 'warning',  # normal, warning, alert, critical
            'recommendation': 'Consider reducing position sizes by 25%',
            'drawdown_periods': [
                {
                    'start_date': '2026-01-15',
                    'end_date': '2026-01-27',
                    'duration_days': 12,
                    'max_dd': -0.085,
                    'recovery_days': 12
                },
                ...
            ]
        }
    """

    if len(capital_history) < 2:
        return {
            "current_drawdown_pct": 0.0,
            "current_drawdown_days": 0,
            "status": "insufficient_data",
        }

    # Calculate running peak and drawdowns
    peak = capital_history[0][1]
    current_dd_start = None
    max_dd = 0.0
    max_dd_period = None
    drawdown_periods = []

    current_capital = capital_history[-1][1]
    current_dd = 0.0
    current_dd_days = 0

    for i, (timestamp, capital) in enumerate(capital_history):
        if capital > peak:
            # New peak - end any ongoing DD period
            if current_dd_start is not None:
                dd_pct = (capital_history[i - 1][1] - peak) / peak
                duration = (timestamp - current_dd_start).days

                drawdown_periods.append(
                    {
                        "start_date": current_dd_start.strftime("%Y-%m-%d"),
                        "end_date": timestamp.strftime("%Y-%m-%d"),
                        "duration_days": duration,
                        "max_dd": dd_pct,
                        "recovery_days": duration,
                    }
                )

                if abs(dd_pct) > abs(max_dd):
                    max_dd = dd_pct
                    max_dd_period = drawdown_periods[-1]

                current_dd_start = None

            peak = capital
        else:
            # In drawdown
            dd = (capital - peak) / peak

            # Update max_dd even if not recovered yet
            if abs(dd) > abs(max_dd):
                max_dd = dd

            if current_dd_start is None:
                current_dd_start = timestamp

            # If this is the last point, calculate current DD
            if i == len(capital_history) - 1:
                current_dd = dd
                current_dd_days = (timestamp - current_dd_start).days

    # Determine status based on thresholds
    dd_pct = abs(current_dd)

    if dd_pct < 0.05:
        status = "normal"
        recommendation = "Continue normal operations"
    elif dd_pct < 0.10:
        status = "warning"
        recommendation = "Consider reducing position sizes by 25%"
    elif dd_pct < 0.20:
        status = "alert"
        recommendation = "Reduce position sizes by 50% until recovery"
    else:
        status = "critical"
        recommendation = "⚠️ Pause new bets until capital recovers above 85% of peak"

    return {
        "current_drawdown_pct": current_dd,
        "current_drawdown_days": current_dd_days,
        "peak_capital": peak,
        "current_capital": current_capital,
        "max_historical_dd": max_dd,
        "max_dd_recovery_days": (
            max_dd_period["recovery_days"] if max_dd_period else 0
        ),
        "status": status,
        "recommendation": recommendation,
        "drawdown_periods": sorted(
            drawdown_periods,
            key=lambda x: abs(x["max_dd"]),
            reverse=True,
        )[
            :5
        ],  # Top 5 worst
    }
