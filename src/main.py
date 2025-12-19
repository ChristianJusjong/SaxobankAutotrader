import asyncio
import time
import os
import sys
import signal
import json
import redis
import functools
from concurrent.futures import ThreadPoolExecutor

# Add src to path if needed
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from logger_config import logger

from auth_manager import SaxoAuthManager
from account_info import AccountManager
from market_data import MarketDataManager
from strategy import TrendFollower
from executor import OrderExecutor, RateLimiter
from reporting import DailyReporter
from scanner import MarketScanner

# Configuration
UICS_TO_TRADE = [211] # Apple default
TRADE_QUANTITY = 10
SIMULATION_MODE = True
REDIS_URL = os.getenv('REDIS_URL')

class BotOrchestrator:
    def __init__(self):
        self.running = True
        self.executor = ThreadPoolExecutor(max_workers=5)
        
        # 1. Initialize Modules
        self.auth = SaxoAuthManager()
        self.token = self.auth.ensure_valid_token()
        if not self.token:
            logger.critical("Authentication failed. Exiting.")
            sys.exit(1)
            
        self.rate_limiter = RateLimiter(limit=115, window=60)
        self.account = AccountManager(self.auth)
        self.market_data = MarketDataManager(self.auth)
        self.executor_module = OrderExecutor(self.account, dry_run=SIMULATION_MODE, rate_limiter=self.rate_limiter)
        self.strategy = TrendFollower(self.account)
        self.reporter = DailyReporter(os.path.join(os.path.dirname(__file__), '..', 'logs'), self.account)
        self.scanner = MarketScanner(self.auth, self.market_data, rate_limiter=self.rate_limiter)
        
        # Redis Control
        self.redis = None
        if REDIS_URL:
            try:
                self.redis = redis.from_url(REDIS_URL)
                self.redis.ping()
                logger.info("Connected to Redis for ActiveUniverse.")
            except Exception as e:
                logger.error(f"Redis connection failed: {e}")

        # State Tracking
        self.last_processed_time = {} # uic -> timestamp

    def sync_active_universe(self):
        """Syncs Watched and Owned lists to Redis."""
        if not self.redis: return
        
        try:
            watched = list(self.market_data.active_uics)
            owned = list(self.strategy.active_positions.keys())
            
            payload = {
                "watched": watched,
                "owned": owned,
                "timestamp": time.time()
            }
            self.redis.set("saxotrader:active_universe", json.dumps(payload))
            # logger.debug("Synced ActiveUniverse to Redis.")
        except Exception as e:
            logger.error(f"Failed to sync ActiveUniverse: {e}")

    async def task_scanner(self):
        """Task 1: The Scanner (Every 10 min)."""
        logger.info("Task [Scanner]: Started.")
        loop = asyncio.get_running_loop()
        
        while self.running:
            try:
                # Run sync scanner in thread pool
                logger.info("Scanner: Starting Broad Market Scan...")
                
                # We don't need to manually call add_to_stream, the scanner logic does it.
                # But to satisfy specific requirements, we ensure scanner uses market_data.add_to_stream
                # (which it does in our refactored scanner.py via self.md.add_subscription)
                
                await loop.run_in_executor(self.executor, self.scanner.perform_market_scan)
                
                # Sync state after potential additions
                self.sync_active_universe()
                
            except Exception as e:
                logger.error(f"Scanner Task Error: {e}")
                
            # Wait 10 minutes
            await asyncio.sleep(600)

    async def task_janitor(self):
        """Task 3: The Janitor (Every 60 min)."""
        logger.info("Task [Janitor]: Started.")
        loop = asyncio.get_running_loop()
        
        while self.running:
            try:
                logger.info("Janitor: Checking for stale subscriptions...")
                
                # Run sync prune in thread pool
                # Strategy positions are SAFE from pruning
                safe_list = self.strategy.active_positions
                prune_func = functools.partial(self.market_data.prune_stream, safe_uics=safe_list)
                
                await loop.run_in_executor(self.executor, prune_func)
                
                # Sync state after potential removals
                self.sync_active_universe()
                
            except Exception as e:
                logger.error(f"Janitor Task Error: {e}")
                
            # Wait 60 minutes
            await asyncio.sleep(3600)

    async def task_stream_processor(self):
        """Task 2: The Streamer (Real-time Tick Processing)."""
        logger.info("Task [stream_processor]: Started.")
        # This replaces the old main loop
        
        while self.running:
            try:
                # Maintenance: Token Refresh
                if not self.auth.ensure_valid_token():
                     logger.warning("Token expired, refreshing...")
                
                # Process Ticks
                # We copy active_uics to avoid thread contention issues during iteration
                active_uics = list(self.market_data.active_uics)
                
                for uic in active_uics:
                    state = self.market_data.live_market_state.get(uic)
                    if not state: continue
                    
                    current_price = state.get('LastPrice')
                    update_time = state.get('Updated')
                    
                    if not current_price: continue
                    
                    # Deduplicate ticks
                    if update_time != self.last_processed_time.get(uic):
                        prev_peak = self.strategy.active_positions.get(uic, {}).get('peak_price', 0)
                        
                        # EXECUTE STRATEGY
                        signal = self.strategy.update(uic, current_price, quantity=TRADE_QUANTITY)
                        
                        # Logging & Notification
                        new_peak = self.strategy.active_positions.get(uic, {}).get('peak_price', 0)
                        if new_peak > prev_peak and prev_peak > 0:
                             logger.warning(f"PEAK DETECTED: UIC {uic} New High: {new_peak:.2f}")

                        if signal:
                            action = 'Buy' if signal == 'BUY' else 'Sell'
                            logger.critical(f"TRADE SIGNAL: {action} {uic} @ {current_price}")
                            
                            success = False
                            if not SIMULATION_MODE:
                                success = self.executor_module.place_order(
                                    uic=uic, amount=TRADE_QUANTITY, action=action, 
                                    order_type='Market', asset_type='Stock'
                                )
                            else:
                                self.reporter.log_simulation_trade(action, uic, current_price, "Signal")
                                success = True
                                
                            if success:
                                # Sync state on trade execution (Ownership change)
                                self.sync_active_universe()

                        self.last_processed_time[uic] = update_time
                
                # Small sleep to yield to event loop (don't burn CPU)
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Stream Processor Error: {e}")
                await asyncio.sleep(1)

    async def task_reporting(self):
        """Periodic Health Reporting."""
        logger.info("Task [Reporting]: Started.")
        while self.running:
            self.reporter.log_health(self.strategy)
            await asyncio.sleep(60)

    async def shutdown(self):
        """Graceful Shutdown."""
        logger.warning("Shutdown Signal Received. Saving state...")
        self.running = False
        
        # Save all peak prices
        # Strategy saves incrementally, but we can verify here if needed.
        # Ideally strategy would have a bulk save, but incremental is safer.
        logger.info("Verifying all positions persisted...")
        for uic in self.strategy.active_positions:
            self.strategy._save_state(uic)
        
        # Close Redis
        if self.redis:
            self.redis.close()
            
        logger.info("Stopping WebSocket...")
        if self.market_data.ws:
            self.market_data.ws.close()
            
        logger.info("Shutdown Complete.")
        
    async def run(self):
        """Main Entry Point."""
        logger.info("Starting Asyncio Orchestrator...")
        
        # Start WebSocket Thread (It's self-managed)
        self.market_data.start_stream(UICS_TO_TRADE)
        
        # Register Signals
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
        
        # Create Tasks
        t1 = asyncio.create_task(self.task_scanner())
        t2 = asyncio.create_task(self.task_stream_processor())
        t3 = asyncio.create_task(self.task_janitor())
        t4 = asyncio.create_task(self.task_reporting())
        
        # Keep alive until running is False
        while self.running:
            await asyncio.sleep(1)
            
        # Should cancel tasks here if we want strict cleanup
        t1.cancel()
        t2.cancel()
        t3.cancel()
        t4.cancel()

if __name__ == "__main__":
    bot = BotOrchestrator()
    # Windows doesn't support add_signal_handler for SIGINT effectively in loop
    # But Railway is Linux (usually). For Windows dev, we stick to KeyboardInterrupt logic if needed.
    # Actually, asyncio.run handles this reasonably well.
    try:
        if sys.platform == 'win32':
             # Windows Polyfill Loop Policy if needed or just run
             asyncio.run(bot.run())
        else:
             asyncio.run(bot.run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass

