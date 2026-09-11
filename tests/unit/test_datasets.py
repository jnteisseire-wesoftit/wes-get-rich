"""Test datasets for strategy tests."""
from datetime import datetime, timedelta
from src.db import PriceSample, HourlyMetric


class CrashGuardDatasets:
    """Datasets for crash guard testing."""
    
    @staticmethod
    def get_stable_price_data(
        base_time: datetime,
        days: int = 90,
        price: float = 100.0,
        interval_minutes: int = 5,
    ) -> list[PriceSample]:
        """
        Generate stable price data (no volatility).
        
        Args:
            base_time: Starting time for data generation
            days: Number of days to generate
            price: Base price (stays constant)
            interval_minutes: Minutes between samples
        """
        samples = []
        for day in range(days, 0, -1):
            for hour in range(24):
                for minute_block in range(0, 60, interval_minutes):
                    samples.append(PriceSample(
                        sampled_at=base_time - timedelta(
                            days=day,
                            hours=hour,
                            minutes=minute_block,
                        ),
                        price_usd=price,
                        source="test_stable",
                    ))
        return sorted(samples, key=lambda s: s.sampled_at)
    
    @staticmethod
    def get_declining_price_data(
        base_time: datetime,
        window_minutes: int,
        decline_pct: float,
        interval_minutes: int = 5,
    ) -> list[PriceSample]:
        """
        Generate declining price data over a window.
        
        Args:
            base_time: Starting time for current window
            window_minutes: Duration of decline window
            decline_pct: Percentage decline over the window
            interval_minutes: Minutes between samples
        """
        samples = []
        initial_price = 100.0
        
        for minute in range(0, window_minutes, interval_minutes):
            progress = minute / window_minutes
            price = initial_price - (initial_price * decline_pct / 100 * progress)
            samples.append(PriceSample(
                sampled_at=base_time + timedelta(minutes=minute),
                price_usd=price,
                source="test_declining",
            ))
        
        return samples
    
    @staticmethod
    def get_rising_price_data(
        base_time: datetime,
        window_minutes: int,
        rise_pct: float,
        interval_minutes: int = 5,
    ) -> list[PriceSample]:
        """
        Generate rising price data over a window.
        
        Args:
            base_time: Starting time for current window
            window_minutes: Duration of rise window
            rise_pct: Percentage rise over the window
            interval_minutes: Minutes between samples
        """
        samples = []
        initial_price = 100.0
        
        for minute in range(0, window_minutes, interval_minutes):
            progress = minute / window_minutes
            price = initial_price + (initial_price * rise_pct / 100 * progress)
            samples.append(PriceSample(
                sampled_at=base_time + timedelta(minutes=minute),
                price_usd=price,
                source="test_rising",
            ))
        
        return samples
    
    @staticmethod
    def create_full_dataset_with_crash(
        base_time: datetime,
        lookback_days: int = 90,
        window_minutes: int = 5760,  # 4 days
        current_decline_pct: float = 5.0,
        historical_decline_pct: float = 1.0,
        interval_minutes: int = 5,
    ) -> list[PriceSample]:
        """
        Create a complete dataset with historical data and a crash scenario.
        
        Args:
            base_time: Latest timestamp
            lookback_days: Days of history to include
            window_minutes: Crash window duration
            current_decline_pct: Current decline percentage
            historical_decline_pct: Historical decline percentage for comparison
            interval_minutes: Minutes between samples
        """
        samples = []
        
        # Add stable historical baseline
        stable_data = CrashGuardDatasets.get_stable_price_data(
            base_time=base_time - timedelta(days=lookback_days),
            days=lookback_days,
            price=100.0,
            interval_minutes=interval_minutes,
        )
        samples.extend(stable_data)
        
        # Add a few historical decline examples (smaller than current)
        for offset_days in [30, 20]:
            crash_start = base_time - timedelta(days=offset_days, minutes=window_minutes)
            historical_crash = CrashGuardDatasets.get_declining_price_data(
                base_time=crash_start,
                window_minutes=window_minutes,
                decline_pct=historical_decline_pct,
                interval_minutes=interval_minutes,
            )
            samples.extend(historical_crash)
        
        # Add current crash (larger decline)
        current_crash = CrashGuardDatasets.get_declining_price_data(
            base_time=base_time,
            window_minutes=window_minutes,
            decline_pct=current_decline_pct,
            interval_minutes=interval_minutes,
        )
        samples.extend(current_crash)
        
        return sorted(samples, key=lambda s: s.sampled_at)
    
    @staticmethod
    def create_full_dataset_no_crash(
        base_time: datetime,
        lookback_days: int = 90,
        window_minutes: int = 5760,
        small_decline_pct: float = 0.5,
        interval_minutes: int = 5,
    ) -> list[PriceSample]:
        """
        Create a complete dataset with only small, normal movements (no crash).
        """
        samples = []
        
        # Add stable historical data
        stable_data = CrashGuardDatasets.get_stable_price_data(
            base_time=base_time - timedelta(days=lookback_days),
            days=lookback_days,
            price=100.0,
            interval_minutes=interval_minutes,
        )
        samples.extend(stable_data)
        
        # Add small current decline (normal market movement)
        current_small_decline = CrashGuardDatasets.get_declining_price_data(
            base_time=base_time,
            window_minutes=window_minutes,
            decline_pct=small_decline_pct,
            interval_minutes=interval_minutes,
        )
        samples.extend(current_small_decline)
        
        return sorted(samples, key=lambda s: s.sampled_at)


class HourlyMetricDatasets:
    """Datasets for hourly metric tests."""
    
    @staticmethod
    def get_bullish_metrics(
        base_time: datetime,
        hours: int = 30,
    ) -> list[HourlyMetric]:
        """Generate hourly metrics showing bullish trend (short MA > long MA)."""
        metrics = []
        
        for i in range(hours):
            hour_start = base_time - timedelta(hours=i)
            # For BULLISH: most recent (i=0) should have highest price
            # Decrease price as we go back in time
            avg_price = 100 + (hours - i) * 0.5
            
            metrics.append(HourlyMetric(
                hour_start=hour_start,
                sample_count=12,
                min_price_usd=avg_price - 1,
                max_price_usd=avg_price + 1,
                avg_price_usd=avg_price,
                last_price_usd=avg_price + 0.5,
            ))
        
        # Return with most recent first
        return sorted(metrics, key=lambda m: m.hour_start, reverse=True)
    
    @staticmethod
    def get_bearish_metrics(
        base_time: datetime,
        hours: int = 30,
    ) -> list[HourlyMetric]:
        """Generate hourly metrics showing bearish trend (short MA < long MA)."""
        metrics = []
        
        for i in range(hours):
            hour_start = base_time - timedelta(hours=i)
            # For BEARISH: most recent (i=0) should have lowest price
            # Increase price as we go back in time
            avg_price = 100 + i * 0.5
            
            metrics.append(HourlyMetric(
                hour_start=hour_start,
                sample_count=12,
                min_price_usd=avg_price - 1,
                max_price_usd=avg_price + 1,
                avg_price_usd=avg_price,
                last_price_usd=avg_price - 0.5,
            ))
        
        # Return with most recent first
        return sorted(metrics, key=lambda m: m.hour_start, reverse=True)
    
    @staticmethod
    def get_stable_metrics(
        base_time: datetime,
        hours: int = 30,
        price: float = 100.0,
    ) -> list[HourlyMetric]:
        """Generate stable hourly metrics (no trend)."""
        metrics = []
        
        for i in range(hours):
            hour_start = base_time - timedelta(hours=i)
            
            metrics.append(HourlyMetric(
                hour_start=hour_start,
                sample_count=12,
                min_price_usd=price - 0.5,
                max_price_usd=price + 0.5,
                avg_price_usd=price,
                last_price_usd=price,
            ))
        
        # Return with most recent first
        return sorted(metrics, key=lambda m: m.hour_start, reverse=True)
    
    @staticmethod
    def get_high_volatility_metrics(
        base_time: datetime,
        hours: int = 24,
    ) -> list[HourlyMetric]:
        """Generate hourly metrics with high volatility."""
        metrics = []
        
        for i in range(hours):
            hour_start = base_time - timedelta(hours=i)
            avg_price = 100
            
            metrics.append(HourlyMetric(
                hour_start=hour_start,
                sample_count=12,
                min_price_usd=avg_price - 5,  # Large range
                max_price_usd=avg_price + 5,  # Large range
                avg_price_usd=avg_price,
                last_price_usd=avg_price,
            ))
        
        # Return with most recent first
        return sorted(metrics, key=lambda m: m.hour_start, reverse=True)
    
    @staticmethod
    def get_low_volatility_metrics(
        base_time: datetime,
        hours: int = 24,
    ) -> list[HourlyMetric]:
        """Generate hourly metrics with low volatility."""
        metrics = []
        
        for i in range(hours):
            hour_start = base_time - timedelta(hours=i)
            avg_price = 100
            
            metrics.append(HourlyMetric(
                hour_start=hour_start,
                sample_count=12,
                min_price_usd=avg_price - 0.1,  # Very small range
                max_price_usd=avg_price + 0.1,  # Very small range
                avg_price_usd=avg_price,
                last_price_usd=avg_price,
            ))
        
        # Return with most recent first
        return sorted(metrics, key=lambda m: m.hour_start, reverse=True)
