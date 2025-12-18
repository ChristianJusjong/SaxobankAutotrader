import time
import os
import sys

# Add src to path if needed
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from logger_config import logger # Professional Logger

from auth_manager import SaxoAuthManager
from account_info import AccountManager
from market_data import MarketDataManager
from strategy import TrendFollower
from executor import OrderExecutor, RateLimiter

# Setup Directories
script_dir = os.path.dirname(os.path.abspath(__file__))
log_dir = os.path.join(script_dir, '..', 'logs')
os.makedirs(log_dir, exist_ok=True)

from reporting import DailyReporter
from scanner import MarketScanner

# Configuration
UICS_TO_TRADE = [211] # Apple
TRADE_QUANTITY = 10
SIMULATION_MODE = True

def main():
    logger.info("Starting SaxoTrader Bot...")
    logger.info(f"Mode: {'SIMULATION' if SIMULATION_MODE else 'REAL MONEY'}")
    
    # 1. Initialize Authentication
    auth = SaxoAuthManager()
    token = auth.ensure_valid_token()
    if not token:
        logger.error("Authentication failed. Run 'src/callback_server.py' first.")
        return

    # 2. Rate Limiter (Global)
    # 120 calls per 60 seconds (API Limit)
    rate_limiter = RateLimiter(limit=115, window=60)

    # 3. Initialize Modules
    account = AccountManager(auth)
    market_data = MarketDataManager(auth)
    executor = OrderExecutor(account, dry_run=SIMULATION_MODE, rate_limiter=rate_limiter)
    strategy = TrendFollower(account)
    reporter = DailyReporter(log_dir, account)
    scanner = MarketScanner(auth, market_data, rate_limiter=rate_limiter)
    
    # 4. Start Market Data Stream & Scanner
    market_data.start_stream(UICS_TO_TRADE)
    scanner.start() # Start Polling in background
    
    # Track last processed update to avoid duplicates
    last_processed_time = {} # uic -> timestamp
    last_health_check = time.time()
    last_heartbeat = time.time()

    logger.info("Bot is running. Press Ctrl+C to stop (and trigger Kill Switch).")
    
    try:
        while True:
            current_time = time.time()

            # A. Maintenance
            if not auth.ensure_valid_token():
                logger.warning("Token expired, attempting refresh...")
            
            # Heartbeat (Every 5 mins)
            if current_time - last_heartbeat > 300:
                logger.info("[HEARTBEAT] System Healthy. Connection Stable.")
                last_heartbeat = current_time

            # Health Check (Every 60s)
            if current_time - last_health_check > 60:
                reporter.log_health(strategy)
                last_health_check = current_time

            # B. Strategy Loop
            # Copy active_uics because Scanner might modify the list in another thread
            active_uics = list(market_data.active_uics) 

            for uic in active_uics:
                # Get latest state
                state = market_data.live_market_state.get(uic)
                
                if state:
                    current_price = state.get('LastPrice')
                    update_time = state.get('Updated')
                    
                    # Only process if we haven't seen this specific update yet
                    if update_time != last_processed_time.get(uic):
                        # logger.debug(f"Tick: {uic} @ {current_price}")
                        
                        prev_max = strategy.positions.get(uic, {}).get('max_price', 0)

                        # Update Strategy
                        signal = strategy.update(uic, current_price, quantity=TRADE_QUANTITY)
                        
                        # Check for Peak Update
                        new_max = strategy.positions.get(uic, {}).get('max_price', 0)
                        if new_max > prev_max and prev_max > 0:
                            # User requested WARNING (Yellow) for Peaks
                            logger.warning(f"PEAK DETECTED: UIC {uic} New High: {new_max:.2f}")

                        # Handle Signals
                        if signal:
                            action = 'Buy' if signal == 'BUY' else 'Sell'
                            
                            # User requested CRITICAL (Bold Red) for Executing Trades
                            logger.critical(f"TRADE SIGNAL: {action} {uic} @ {current_price}")
                            
                            if SIMULATION_MODE:
                                reporter.log_simulation_trade(action, uic, current_price, "Strategy Signal (Dry Run)")
                            else:
                                success = executor.place_order(
                                    uic=uic,
                                    amount=TRADE_QUANTITY,
                                    action=action,
                                    order_type='Market',
                                    asset_type='Stock'
                                )
                                
                                if success:
                                    logger.critical(f"EXECUTION SUCCESS: {action} {uic}")
                                else:
                                    logger.error(f"EXECUTION FAILED: {action} {uic}")
                        
                        # Update tracker
                        last_processed_time[uic] = update_time
            
            # Efficient Sleep
            time.sleep(0.5)

    except KeyboardInterrupt:
        logger.warning("\nUser interrupted. Shutting down...")
        print("!!! STOPPING BOT !!!")
        
        # Final Health Report
        reporter.log_health(strategy)

        choice = input("Do you want to CLOSE ALL POSITIONS before exiting? (y/N): ")
        if choice.lower() == 'y':
            executor.kill_switch()
        
        if market_data.ws:
            market_data.ws.close()
            
    except Exception as e:
        logger.critical(f"Unexpected crash: {e}", exc_info=True)

if __name__ == "__main__":
    main()
