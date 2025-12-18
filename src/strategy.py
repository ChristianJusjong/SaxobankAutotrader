import logging
import collections

logger = logging.getLogger(__name__)

class TrendFollower:
    def __init__(self, account_manager, stop_loss_pct=0.01):
        self.account = account_manager
        self.stop_loss_pct = stop_loss_pct
        
        # Positions: {uic: {'entry_price': float, 'quantity': int, 'max_price': float}}
        self.positions = {}
        
        # Price History for EMA: {uic: deque([p1, p2, ...], maxlen=20)}
        self.price_history = collections.defaultdict(lambda: collections.deque(maxlen=30))
        
        # EMA Settings
        self.short_period = 5
        self.long_period = 20

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
        
        # Basic check: if Short EMA is newly above Long EMA
        # In a real bot, we'd check previous step to confirm the 'Cross' happened JUST NOW.
        # For simplicity, we just check if Short > Long and we have no position.
        
        if short_ema > long_ema:
            logger.info(f"Entry Signal for UIC {uic}: ShortEMA({short_ema:.2f}) > LongEMA({long_ema:.2f})")
            
            # Record Position (Simulated Entry)
            self.positions[uic] = {
                'entry_price': current_price,
                'quantity': quantity,
                'max_price': current_price
            }
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
                return 'SELL'
            else:
                # Log the logic
                # We can re-call calculate_net_profit just for the log or rely on account_info logs
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
        def calculate_net_profit(self, entry, current, qty, uic):
            # Simulate a small cost
            return (current - entry) * qty - 2.0 

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

