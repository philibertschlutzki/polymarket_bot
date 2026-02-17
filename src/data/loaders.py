import sqlite3
from typing import List

from nautilus_trader.model.data import QuoteTick, TradeTick
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity


class SQLiteDataLoader:
    """
    Loads market data from SQLite database into Nautilus Trader objects.
    """

    def __init__(self, db_path: str = "src/data/market_data.db"):
        self.db_path = db_path

    def load_quotes(self, instrument_id: str) -> List[QuoteTick]:
        """
        Load QuoteTicks for a specific instrument.
        """
        quotes = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Check if table exists
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='quotes'")
                if not cursor.fetchone():
                    return []

                cursor = conn.execute(
                    """
                    SELECT timestamp, bid_price, ask_price, bid_size, ask_size
                    FROM quotes
                    WHERE instrument_id = ?
                    ORDER BY timestamp ASC
                    """,
                    (instrument_id,),
                )
                instr_id_obj = InstrumentId.from_str(instrument_id)

                for row in cursor:
                    ts = int(row[0])
                    # Ensure floats
                    bid_px = Price.from_float(float(row[1]))
                    ask_px = Price.from_float(float(row[2]))
                    bid_sz = Quantity.from_float(float(row[3]))
                    ask_sz = Quantity.from_float(float(row[4]))

                    quotes.append(
                        QuoteTick(
                            instrument_id=instr_id_obj,
                            bid_price=bid_px,
                            ask_price=ask_px,
                            bid_size=bid_sz,
                            ask_size=ask_sz,
                            ts_event=ts,
                            ts_init=ts,
                        )
                    )
        except Exception as e:
            # Log or re-raise? Since this is a loader helper, maybe print or log.
            print(f"Error loading quotes: {e}")

        return quotes

    def load_trades(self, instrument_id: str) -> List[TradeTick]:
        """
        Load TradeTicks for a specific instrument.
        """
        trades = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
                if not cursor.fetchone():
                    return []

                cursor = conn.execute(
                    """
                    SELECT timestamp, price, size, side
                    FROM trades
                    WHERE instrument_id = ?
                    ORDER BY timestamp ASC
                    """,
                    (instrument_id,),
                )
                instr_id_obj = InstrumentId.from_str(instrument_id)

                for row in cursor:
                    ts = int(row[0])
                    price = Price.from_float(float(row[1]))
                    size = Quantity.from_float(float(row[2]))
                    side_str = row[3]
                    try:
                        side = OrderSide[side_str]
                    except KeyError:
                        # Fallback or skip
                        continue

                    trades.append(
                        TradeTick(
                            instrument_id=instr_id_obj,
                            price=price,
                            size=size,
                            side=side,
                            ts_event=ts,
                            ts_init=ts,
                        )
                    )
        except Exception as e:
            print(f"Error loading trades: {e}")

        return trades
