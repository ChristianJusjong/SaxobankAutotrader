import requests
import time
import threading
from logger_config import logger

class MarketScanner:
    def __init__(self, auth_manager, market_data_manager, rate_limiter=None):
        self.auth = auth_manager
        self.md = market_data_manager
        self.rate_limiter = rate_limiter
        self.running = False
        # Example: US Big Tech & High Volatility Tickers (UICs)
        self.watchlist_uics = [211, 212, 111] 
        self.scan_interval = 300 # 5 minutes

    def start(self):
        self.running = True
        t = threading.Thread(target=self._scan_loop)
        t.daemon = True
        t.start()
        logger.info("Market Scanner started (Interval: 5m)")

    def _scan_loop(self):
        while self.running:
            try:
                self._run_scan()
            except Exception as e:
                logger.error(f"Scanner Loop Error: {e}")
            
            time.sleep(self.scan_interval)

    def _run_scan(self):
        # Rate Limiter Check (Low Priority)
        # We check BEFORE auth or request to save calls
        if self.rate_limiter:
            if not self.rate_limiter.can_proceed(priority='low'):
                logger.warning("Market Scanner PAUSED due to API Rate Limit (Saving bandwidth for Sells).")
                return # Skip this interval

        token = self.auth.ensure_valid_token()
        if not token: return
        
        # 1. Fetch Snapshot for entire watchlist
        # Endpoint: GET /trade/v1/infoprices/list?Uics=...&AssetType=Stock
        uic_str = ",".join(map(str, self.watchlist_uics))
        url = f"https://gateway.saxobank.com/sim/openapi/trade/v1/infoprices/list?Uics={uic_str}&AssetType=Stock"
        
        headers = {"Authorization": f"Bearer {token}"}
        
        resp = requests.get(url, headers=headers)
        
        # Count the call
        if self.rate_limiter: self.rate_limiter.add_call()
        
        if resp.status_code == 200:
            data = resp.json().get('Data', [])
            for item in data:
                self._analyze_instrument(item)
        elif resp.status_code == 429:
             retry_after = int(resp.headers.get("Retry-After", 60))
             if self.rate_limiter: self.rate_limiter.trigger_cooldown(retry_after)
             logger.warning(f"Scanner hit 429. Backing off for {retry_after}s.")
        else:
            logger.warning(f"Failed to fetch scanner snapshot: {resp.status_code}")

    def _analyze_instrument(self, item):
        uic = item.get('Uic')
        quote = item.get('Quote', {})
        
        percent_change = quote.get('PercentChange', 0.0)
        current_price = quote.get('LastTraded')
        
        # Criteria: > 3% Trend Start
        if percent_change > 3.0:
            symbol = item.get('DisplayAndFormat', {}).get('Symbol', f"UIC:{uic}")
            
        if percent_change > 3.0:
            symbol = item.get('DisplayAndFormat', {}).get('Symbol', f"UIC:{uic}")
            
            # Info level is configured as Cyan in logger_config.py
            logger.info(f"Quick Win Detected! {symbol} is up {percent_change:.2f}% (Price: {current_price}). Adding to Stream.")
            
            # Dynamic Subscription
            self.md.add_subscription(uic)
