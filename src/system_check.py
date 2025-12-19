import time
import sys
import logging
from logger_config import logger

# Modules
from auth_manager import SaxoAuthManager
from account_info import AccountManager
from market_data import MarketDataManager
from scanner import MarketScanner
from strategy import TrendFollower

def run_system_check():
    logger.info("=== STARTING COMPREHENSIVE SYSTEM CHECK ===")
    
    # 1. AUTH
    logger.info("[1/5] Testing Authentication...")
    auth = SaxoAuthManager()
    token = auth.ensure_valid_token()
    if token:
        logger.info("Auth Success: Token acquired.")
    else:
        logger.critical("Auth Failed.")
        return

    # 2. ACCOUNT
    logger.info("[2/5] Testing Account Data...")
    try:
        account = AccountManager(auth)
        # Client Key logic might be internal, let's try a balance check if exposed, 
        # or just rely on initialization which fetches client_key
        if account.client_key:
             logger.info(f"Account Success: Client Key {account.client_key}")
        else:
             logger.error("Account Failed: No Client Key.")
    except Exception as e:
        logger.error(f"Account Error: {e}")

    # 3. SCANNER
    logger.info("[3/5] Testing Market Scanner (Live)...")
    try:
        # We mock rate_limiter with None for test
        md = MarketDataManager(auth)
        scanner = MarketScanner(auth, md, rate_limiter=None)
    
        # Patch universe fetching to be fast? No, let's test real fetch.
        logger.info("Fetching Universe (NYSE/NASDAQ)...")
        uics = scanner.get_us_universe()
        if len(uics) > 100:
             logger.info(f"Universe Fetch Success: {len(uics)} instruments.")
        else:
             logger.warning(f"Universe Fetch Low? {len(uics)} items.")
             
        # Run 1 Batch
        scanner.universe_uics = uics[:50] # Limit to 1 batch
        logger.info("Running Batch Scan (50 items)...")
        hot = scanner.perform_market_scan()
        logger.info(f"Scanner Batch Success. Found {len(hot)} candidates.")
        
    except Exception as e:
        logger.error(f"Scanner Error: {e}")

    # 4. STREAMING
    logger.info("[4/5] Testing WebSocket Stream (Live)...")
    try:
        test_uic = 211 # Apple
        md.start_stream([test_uic])
        
        logger.info("Waiting 10s for Price Tick...")
        start = time.time()
        success = False
        while time.time() - start < 15:
            price = md.get_latest_price(test_uic)
            if price:
                logger.info(f"Stream Success: Received Price for 211: {price}")
                success = True
                break
            time.sleep(1)
            
        if not success:
            logger.error("Stream Timeout: No price received in 15s. (Market Closed?)")
    except Exception as e:
        logger.error(f"Stream Error: {e}")

    # 5. STRATEGY logic
    logger.info("[5/5] Testing Strategy Logic (Simulation)...")
    try:
        strategy = TrendFollower(account)
        # Inject fake position
        strategy.active_positions[99999] = {'entry_price': 100, 'peak_price': 100, 'qty': 10}
        
        # 1. Tick Up
        strategy.update(99999, 105, 10)
        peak = strategy.active_positions[99999]['peak_price']
        if peak == 105:
            logger.info("Strategy Peak Detection Success (100 -> 105)")
        else:
            logger.error(f"Strategy Fail: Peak is {peak}, expected 105")
    except Exception as e:
        logger.error(f"Strategy Error: {e}")

    # Cleanup
    if md.ws: md.ws.close()
    
    logger.info("=== SYSTEM CHECK COMPLETE ===")

if __name__ == "__main__":
    run_system_check()
