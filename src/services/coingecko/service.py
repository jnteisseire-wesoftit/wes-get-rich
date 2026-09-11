"""
CoinGecko public API service for fetching crypto price data.

Provides functions for:
- Current price fetching (live)
- Historical data retrieval (daily, hourly, minute-level sampling)
- Backfilling the database with historical prices
"""
import requests
from datetime import datetime, timedelta, timezone
from typing import List
import psycopg
import time

from src.db import insert_price_sample


# CoinGecko API base URL
COINGECKO_API = "https://api.coingecko.com/api/v3"

# Mapping of asset symbols to CoinGecko coin IDs
ASSET_TO_COIN_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
}


def _get_coin_id(asset_symbol: str) -> str:
    """Convert asset symbol (BTC) to CoinGecko coin ID (bitcoin)."""
    coin_id = ASSET_TO_COIN_ID.get(asset_symbol)
    if not coin_id:
        raise ValueError(f"Unknown asset symbol: {asset_symbol}")
    return coin_id


def fetch_current_price(asset_symbol: str = "BTC", vs_currency: str = "usd") -> float:
    """
    Fetch current price from CoinGecko.
    
    Args:
        asset_symbol: BTC, ETH, SOL, etc.
        vs_currency: usd, chf, eur, etc.
    
    Returns:
        Current price in the specified currency.
    """
    coin_id = _get_coin_id(asset_symbol)
    url = f"{COINGECKO_API}/simple/price"
    params = {
        "ids": coin_id,
        "vs_currencies": vs_currency,
    }
    
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    price = float(data[coin_id][vs_currency])
    
    return price


def fetch_historical_daily_prices(
    asset_symbol: str = "BTC",
    days: int = 365,
    vs_currency: str = "usd",
) -> List[tuple[datetime, float]]:
    """
    Fetch historical daily prices for the past N days.
    
    Args:
        asset_symbol: BTC, ETH, SOL, etc.
        days: Number of days to fetch (max ~365)
        vs_currency: usd, chf, eur, etc.
    
    Returns:
        List of (timestamp, price) tuples, oldest to newest.
    """
    coin_id = _get_coin_id(asset_symbol)
    url = f"{COINGECKO_API}/coins/{coin_id}/market_chart"
    params = {
        "vs_currency": vs_currency,
        "days": str(days),
        "interval": "daily",
    }
    
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    
    prices = []
    for timestamp_ms, price in data.get("prices", []):
        # Convert milliseconds to seconds and create datetime in UTC
        timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        prices.append((timestamp, float(price)))
    
    return prices


def fetch_price_range_with_sampling(
    asset_symbol: str = "BTC",
    start_date: datetime = None,
    end_date: datetime = None,
    sample_interval_minutes: int = 1440,
    vs_currency: str = "usd",
) -> List[tuple[datetime, float]]:
    """
    Fetch historical prices for a date range with custom sampling interval.
    
    Uses daily prices from CoinGecko and samples them at the specified interval.
    For example, with sample_interval_minutes=1440 (daily), returns one price per day.
    With sample_interval_minutes=5, returns prices every 5 minutes (simulated from daily data).
    
    Note: CoinGecko only provides daily granularity for historical data, so minute-level
    sampling interpolates from daily averages.
    
    Args:
        asset_symbol: BTC, ETH, SOL, etc.
        start_date: Start of date range (default: 365 days ago)
        end_date: End of date range (default: now)
        sample_interval_minutes: Minutes between samples (default 1440 = 1 day)
        vs_currency: usd, chf, eur, etc.
    
    Returns:
        List of (timestamp, price) tuples sampled at the requested interval.
    """
    if end_date is None:
        end_date = datetime.now(timezone.utc)
    if start_date is None:
        start_date = end_date - timedelta(days=365)
    
    # Calculate how many days to fetch
    days_range = (end_date - start_date).days
    if days_range < 1:
        days_range = 1
    
    print(f"📊 Fetching {asset_symbol} prices from {start_date.date()} to {end_date.date()} ({days_range} days)...")
    
    # Fetch daily prices for the range
    daily_prices = fetch_historical_daily_prices(
        asset_symbol=asset_symbol,
        days=min(days_range + 1, 365),
        vs_currency=vs_currency,
    )
    
    if not daily_prices:
        print(f"   ⚠ No price data available for {asset_symbol}")
        return []
    
    # Filter to requested date range
    filtered_prices = [
        (ts, price) for ts, price in daily_prices
        if start_date <= ts <= end_date
    ]
    
    print(f"   Retrieved {len(filtered_prices)} daily prices")
    
    # Sample at requested interval
    sample_interval = timedelta(minutes=sample_interval_minutes)
    sampled_prices = []
    
    current_sample_time = start_date
    while current_sample_time <= end_date:
        # Find closest price to current sample time
        closest_price = None
        closest_diff = None
        
        for ts, price in filtered_prices:
            diff = abs((ts - current_sample_time).total_seconds())
            if closest_diff is None or diff < closest_diff:
                closest_price = price
                closest_diff = diff
        
        if closest_price is not None:
            sampled_prices.append((current_sample_time, closest_price))
        
        current_sample_time += sample_interval
    
    print(f"   Sampled to {len(sampled_prices)} prices at {sample_interval_minutes}-minute intervals")
    return sampled_prices


def backfill_price_data(
    conn: psycopg.Connection,
    asset_symbol: str = "BTC",
    start_date: datetime = None,
    end_date: datetime = None,
    sample_interval_minutes: int = 1440,
) -> int:
    """
    Fetch and store historical price data in the database.
    
    Fetches prices for the date range with the specified sampling interval
    and inserts them into the price_samples table.
    
    Args:
        conn: Database connection
        asset_symbol: BTC, ETH, SOL, etc.
        start_date: Start of date range (default: 365 days ago)
        end_date: End of date range (default: now)
        sample_interval_minutes: Minutes between samples (default 1440 = 1 day)
    
    Returns:
        Number of new price samples inserted.
    """
    prices = fetch_price_range_with_sampling(
        asset_symbol=asset_symbol,
        start_date=start_date,
        end_date=end_date,
        sample_interval_minutes=sample_interval_minutes,
    )
    
    inserted_count = 0
    for sampled_at, price_usd in prices:
        try:
            # Check if this sample already exists (same asset, same timestamp)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM price_samples
                    WHERE asset_symbol = %s
                      AND sampled_at = %s
                    LIMIT 1
                    """,
                    (asset_symbol, sampled_at),
                )
                if cur.fetchone():
                    continue  # Skip if already exists
            
            # Insert new price sample
            insert_price_sample(
                conn=conn,
                asset_symbol=asset_symbol,
                sampled_at=sampled_at,
                price_usd=price_usd,
                source="coingecko",
            )
            inserted_count += 1
            
            # Commit every 100 inserts to avoid transaction timeout
            if inserted_count % 100 == 0:
                conn.commit()
                print(f"   ✓ Inserted {inserted_count} samples...")
        except Exception as e:
            print(f"   ⚠ Error inserting price for {sampled_at}: {e}")
            continue
    
    conn.commit()
    print(f"✓ Total inserted: {inserted_count} new price samples for {asset_symbol}")
    return inserted_count


def record_current_price(
    conn: psycopg.Connection,
    asset_symbol: str = "BTC",
) -> bool:
    """
    Fetch and record the current price for an asset.
    
    Args:
        conn: Database connection
        asset_symbol: BTC, ETH, SOL, etc.
    
    Returns:
        True if a new sample was recorded, False if not needed.
    """
    try:
        price_usd = fetch_current_price(asset_symbol=asset_symbol)
        now = datetime.now(timezone.utc)
        
        # Check if we already have a sample from the last minute
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM price_samples
                WHERE asset_symbol = %s
                  AND sampled_at > %s
                LIMIT 1
                """,
                (asset_symbol, now - timedelta(minutes=1)),
            )
            if cur.fetchone():
                return False  # Already have recent sample
        
        # Record the new price sample
        insert_price_sample(
            conn=conn,
            asset_symbol=asset_symbol,
            sampled_at=now,
            price_usd=price_usd,
            source="coingecko_live",
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"❌ Error recording current price for {asset_symbol}: {e}")
        return False
