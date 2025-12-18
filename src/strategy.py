import logging
import collections
import os
import json
import redis
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class TrendFollower:
    def __init__(self, account_manager, stop_loss_pct=0.01):
        self.account = account_manager
        self.stop_loss_pct = stop_loss_pct
        
        # Redis Setup
        self.redis_client = None
        redis_url = os.getenv('REDIS_URL')
        if redis_url:
            try:
                # Railway provides redis://...
                self.redis_client = redis.from_url(redis_url)
                self.redis_client.ping()
                logger.info("Connected to Redis for state persistence.")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                self.redis_client = None
        else:
            logger.warning("REDIS_URL not found. Bot running in stateless mode (memory only).")

        # Positions: {uic: {'entry_price': float, 'quantity': int, 'max_price': float}}
        self.positions = {}
        
        # Load State if available
        self._load_state()
        
        # Price History for EMA: {uic: deque([p1, p2, ...], maxlen=20)}
        self.price_history = collections.defaultdict(lambda: collections.deque(maxlen=30))
        
        # EMA Settings
        self.short_period = 5
        self.long_period = 20

    def _load_state(self):
        """Loads active positions from Redis on startup."""
        if not self.redis_client: return
        
        try:
            # We assume keys are stored as "saxotrader:position:{uic}"
            match_pattern = "saxotrader:position:*"
            keys = self.redis_client.keys(match_pattern)
            
            for key in keys:
                data = self.redis_client.get(key)
                if data:
                    pos_data = json.loads(data)
                    uic = pos_data.get('uic')
                    if uic:
                        self.positions[int(uic)] = pos_data
                        logger.info(f"Restored orphaned position from Redis: UIC {uic} | Entry: {pos_data['entry_price']} | Max: {pos_data['max_price']}")
        except Exception as e:
            logger.error(f"Error loading state from Redis: {e}")

    def _save_state(self, uic):
        """Saves current position state to Redis."""
        if not self.redis_client: return
        
        if uic in self.positions:
            data = self.positions[uic]
            data['uic'] = uic # ensure UIC is in the payload
            key = f"saxotrader:position:{uic}"
            try:
                self.redis_client.set(key, json.dumps(data))
                # logger.debug(f"Saved state for UIC {uic} to Redis.")
            except Exception as e:
                logger.error(f"Error saving state to Redis: {e}")

    def _delete_state(self, uic):
        """Removes position state from Redis."""
        if not self.redis_client: return
        
        key = f"saxotrader:position:{uic}"
        try:
            self.redis_client.delete(key)
            logger.info(f"Deleted state for UIC {uic} from Redis.")
        except Exception as e:
            logger.error(f"Error deleting state from Redis: {e}")

    def update(self, uic, current_price, quantity=10):
        """
        Called whenever a new price is received.
        Returns 'BUY', 'SELL', or None.
        """
        # 1. Update History
        self.price_history[uic].append(current_price)
        
        # 2. Check Signals
        if uic in self.positions:
            return self._check_exit_signal(uic, current_price)
        else:
            return self._check_entry_signal(uic, current_price, quantity)

    def _check_entry_signal(self, uic, current_price, quantity):
        """
        Checks for EMA Crossover (Short > Long).
        """
        history = list(self.price_history[uic])
        if len(history) < self.long_period:
            return None # Not enough data

        short_ema = self._calculate_ema(history, self.short_period)
        long_ema = self._calculate_ema(history, self.long_period)
        
        if short_ema > long_ema:
            logger.info(f"Entry Signal for UIC {uic}: ShortEMA({short_ema:.2f}) > LongEMA({long_ema:.2f})")
            
            # Record Position (Simulated Entry)
            self.positions[uic] = {
                'entry_price': current_price,
                'quantity': quantity,
                'max_price': current_price
            }
            # PERSIST
            self._save_state(uic)
            
            return 'BUY'
        
        return None

    def _check_exit_signal(self, uic, current_price):
        """
        Checks Trailing Stop with Profit Guard.
        """
        position = self.positions[uic]
        
        # Update Peak
        if current_price > position['max_price']:
            position['max_price'] = current_price
            # PERSIST (Update Max Price)
            self._save_state(uic)
            # logger.info(f"New Max Price for UIC {uic}: {current_price}")
        
        # Calculate Stop Price
        stop_price = position['max_price'] * (1.0 - self.stop_loss_pct)
        
        if current_price <= stop_price:
            logger.warning(f"Trailing Stop HIT for UIC {uic} at {current_price} (Stop: {stop_price:.2f})")
            
            # --- PROFIT GUARD ---
            entry_price = position['entry_price']
            qty = position['quantity']
            
            # Strict Audit Check: Includes FX Friction and Slippage Buffer
            # Defaulting to USD instrument for now as per audit context
            is_profitable_safe = self.account.evaluate_trade(entry_price, current_price, qty, uic, instrument_currency="USD")
            
            if is_profitable_safe:
                logger.info(f"Profit Guard PASSED. Trade evaluated as SAFE (Net > 0 after FX/Slippage). Executing SELL.")
                del self.positions[uic] # Close internal position tracker
                # PERSIST (Remove)
                self._delete_state(uic)
                return 'SELL'
            else:
                # Log the logic
                logger.warning(f"Profit Guard BLOCK. Trade is technically visible stop, but FAILS audit (Fees/FX/Slippage > Profit). HOLDING.")
                return None
        
        return None

    def _calculate_ema(self, prices, period):
        """Simple EMA calculation."""
        if not prices: return 0
        
        # Initial SMA
        ema = sum(prices[:period]) / period
        
        # Multiplier: 2 / (N + 1)
        k = 2 / (period + 1)
        
        for price in prices[period:]:
            ema = (price * k) + (ema * (1 - k))
            
        return ema

if __name__ == "__main__":
    # Test Strategy Logic
    logging.basicConfig(level=logging.INFO)
    
    # Mock Account Manager
    class MockAccount:
        def evaluate_trade(self, entry, current, qty, uic, instrument_currency="USD"):
            # Mock pass
            return True

    strategy = TrendFollower(MockAccount())
    
    # Simulate Price Data (Rising then Falling)
    prices = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 
              109, 108, 107, 106, 105, 104] # Should trigger stop eventually
              
    print("Testing Strategy with simulated prices...")
    for i, p in enumerate(prices):
        signal = strategy.update(211, p)
        print(f"Price: {p} -> Signal: {signal}")
        
    # Check if position was recorded
    if 211 in strategy.positions:
        print(f"Position still open: {strategy.positions[211]}")
    else:
        print("Position closed.")


