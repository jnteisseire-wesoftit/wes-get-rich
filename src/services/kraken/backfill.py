"""
Kraken OHLC backfill service for historical price data collection.

Uses Kraken public API OHLC endpoint to fetch historical prices without auth.
"""
from datetime import datetime, timezone, timedelta
import psycopg

from src.db import insert_price_sample
from .service import KrakenService, KrakenServiceError


def backfill_kraken_ohlc(
    conn: psycopg.Connection,
    asset_symbol: str = "BTC",
    start_at: datetime = None,
    end_at: datetime = None,
    interval_minutes: int = 5,
) -> int:
    """
    Backfill price data using Kraken public OHLC endpoint.
    
    Args:
        conn: Database connection
        asset_symbol: BTC, ETH, etc. (only BTC supported by Kraken for now)
        start_at: Start date (default: 365 days ago)
        end_at: End date (default: now)
        interval_minutes: OHLC interval - 1, 5, 15, 30, 60, 240, 1440, 10080, 21600
    
    Returns:
        Number of new price samples inserted
    """
    if end_at is None:
        end_at = datetime.now(timezone.utc)
    if start_at is None:
        start_at = end_at - timedelta(days=365)
    
    # Map asset symbols to Kraken pairs
    kraken_pair = {
        "BTC": "XBTUSD",
        "ETH": "ETHUSD",
    }.get(asset_symbol)
    
    if not kraken_pair:
        raise ValueError(f"Unsupported asset for Kraken: {asset_symbol}")
    
    print(f"📊 Backfilling {asset_symbol} from Kraken (OHLC {interval_minutes}min intervals)")
    print(f"   Date range: {start_at.date()} to {end_at.date()}")
    
    kraken = KrakenService()
    inserted_count = 0
    current_cursor = None
    
    # Convert start_at to epoch seconds for Kraken API
    since_epoch = int(start_at.timestamp())
    
    while True:
        try:
            print(f"   Fetching OHLC batch (cursor={current_cursor or 'start'})...")
            
            batch = kraken.fetch_ohlc_close_prices_batch(
                pair=kraken_pair,
                interval_minutes=interval_minutes,
                since_epoch=since_epoch if current_cursor is None else None,
            )
            
            if not batch.samples:
                print(f"   ✓ No more data available")
                break
            
            # Filter samples within date range and avoid duplicates
            for sample in batch.samples:
                if sample.sampled_at > end_at:
                    print(f"   ✓ Reached end date, stopping")
                    break
                
                if sample.sampled_at < start_at:
                    continue
                
                # Check if already exists
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT 1 FROM price_samples
                        WHERE asset_symbol = %s
                          AND sampled_at = %s
                        LIMIT 1
                        """,
                        (asset_symbol, sample.sampled_at),
                    )
                    if cur.fetchone():
                        continue  # Skip if already exists
                
                # Insert new sample
                insert_price_sample(
                    conn=conn,
                    asset_symbol=asset_symbol,
                    sampled_at=sample.sampled_at,
                    price_usd=sample.price_usd,
                    source=f"kraken_{interval_minutes}m",
                )
                inserted_count += 1
            
            # Check if we've reached end date
            if batch.samples and batch.samples[-1].sampled_at >= end_at:
                print(f"   ✓ Reached end date")
                break
            
            # Commit batch
            if inserted_count % 100 == 0 and inserted_count > 0:
                conn.commit()
                print(f"   ✓ Inserted {inserted_count} samples so far...")
            
            # Move to next batch
            current_cursor = batch.last
            if current_cursor is None or current_cursor <= since_epoch:
                print(f"   ✓ No more batches available")
                break
            
            # Update since_epoch for next iteration
            since_epoch = current_cursor
            
        except KrakenServiceError as e:
            print(f"   ⚠ Kraken error: {e}")
            break
        except Exception as e:
            print(f"   ⚠ Error during backfill: {e}")
            continue
    
    conn.commit()
    print(f"✓ Backfill complete: inserted {inserted_count} new price samples for {asset_symbol}")
    return inserted_count
