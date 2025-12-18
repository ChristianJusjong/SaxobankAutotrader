import time
import logging
import os
import sys

# Add src to path if needed, though usually running from root works
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from auth_manager import SaxoAuthManager
from account_info import AccountManager
from market_data import MarketDataManager
from strategy import TrendFollower
from executor import OrderExecutor

# Setup Directories
script_dir = os.path.dirname(os.path.abspath(__file__))
log_dir = os.path.join(script_dir, '..', 'logs')
os.makedirs(log_dir, exist_ok=True)

# Configure General Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, 'bot.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("SaxoTrader")

# Configure Trades Logger
trade_logger = logging.getLogger("Trades")
trade_logger.setLevel(logging.INFO)
# Standard File Handler
trade_handler = logging.FileHandler(os.path.join(log_dir, 'trades.log'))
trade_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
trade_logger.addHandler(trade_handler)
# ADDED: Stream Handler for Docker/Railway Logs
trade_console_handler = logging.StreamHandler()
trade_console_handler.setFormatter(logging.Formatter('[TRADE] %(asctime)s - %(message)s'))
trade_logger.addHandler(trade_console_handler)

trade_logger.propagate = False # Don't duplicate to root logger

from reporting import DailyReporter

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

    # 2. Initialize Modules
    account = AccountManager(auth)
    market_data = MarketDataManager(auth)
    executor = OrderExecutor(account, dry_run=SIMULATION_MODE)
    strategy = TrendFollower(account)
    reporter = DailyReporter(log_dir, account)
    
    # 3. Start Market Data Stream
    market_data.start_stream(UICS_TO_TRADE)
    
    # Track last processed update to avoid duplicates
    last_processed_time = {} # uic -> timestamp
    last_health_check = time.time()

    logger.info("Bot is running. Press Ctrl+C to stop (and trigger Kill Switch).")
    
    try:
        while True:
            # A. Maintenance
            if not auth.ensure_valid_token():
                logger.warning("Token expired, attempting refresh...")
            
            # Health Check (Every 60s)
            if time.time() - last_health_check > 60:
                reporter.log_health(strategy)
                last_health_check = time.time()

            # B. Strategy Loop
            for uic in UICS_TO_TRADE:
                # Get latest state
                state = market_data.live_market_state.get(uic)
                
                if state:
                    current_price = state.get('LastPrice')
                    update_time = state.get('Updated')
                    
                    # Only process if we haven't seen this specific update yet
                    if update_time != last_processed_time.get(uic):
                        logger.debug(f"Processing update for {uic}: {current_price}")
                        
                        # Update Strategy
                        signal = strategy.update(uic, current_price, quantity=TRADE_QUANTITY)
                        
                        # Handle Signals
                        if signal:
                            action = 'Buy' if signal == 'BUY' else 'Sell'
                            trade_logger.info(f"SIGNAL DETECTED: {action} {uic} @ {current_price}")
                            
                            if SIMULATION_MODE:
                                reporter.log_simulation_trade(action, uic, current_price, "Strategy Signal (Dry Run)")
                                # In Sim mode, strategy should arguably NOT clear the position if we aren't "really" trading, 
                                # BUT to test the *Strategy Flow* (Buy -> Peak -> Sell), we MUST pretend we filled it.
                                # Strategy class already updated its internal state (added/removed position) before returning signal?
                                # Wait, strategy.update() calls _check_entry_signal which adds to self.positions...
                                # So logic is already stateful. Good.
                            else:
                                success = executor.place_order(
                                    uic=uic,
                                    amount=TRADE_QUANTITY,
                                    action=action,
                                    order_type='Market',
                                    asset_type='Stock'
                                )
                                
                                if success:
                                    # Log rich details for PnL calculation
                                    trade_logger.info(f"EXECUTION SUCCESS: {action} {uic} @ {current_price} | EstCost: TBD")
                                else:
                                    trade_logger.error(f"EXECUTION FAILED: {action} {uic}")
                        
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
