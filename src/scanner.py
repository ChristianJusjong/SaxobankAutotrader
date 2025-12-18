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
        self.scan_interval = 300 # 5 minutes
        self.universe_uics = []

    def start(self):
        """Starts the background scanning loop."""
        self.running = True
        # Initial Universe Fetch
        try:
            self.universe_uics = self.get_tradable_universe()
            logger.info(f"Market Scanner initialized with {len(self.universe_uics)} instruments.")
        except Exception as e:
            logger.error(f"Failed to fetch universe: {e}")
            # Fallback
            self.universe_uics = [211, 212, 111, 137] 

        t = threading.Thread(target=self._scan_loop)
        t.daemon = True
        t.start()
        logger.info(f"Market Scanner loop started (Interval: {self.scan_interval}s)")

    def get_tradable_universe(self):
        """
        Fetches tradable universe from Saxo.
        Simulated 'US Large Cap' by searching for major keywords/exchanges.
        """
        token = self.auth.ensure_valid_token()
        if not token: return []
        
        # Searching for 'All US Stocks' via API is complex without a scanner subscription.
        # We will approximate "US Large Cap" by searching for common keywords or a curated list.
        # For this requirement, we'll try to get reasonable results using AssetType=Stock.
        
        # In a real scenario, you might iterate exchanges. 
        # Here we perform a search for "Apple", "Microsoft", "Tesla", "Amazon", "NVDA", "GOOG"
        # to build a valid list for the SIMULATION.
        
        keywords = ["Apple", "Microsoft", "Tesla", "Amazon", "Nvidia", "Google", "Meta", "AMD", "Intel", "Netflix"]
        uics = set()
        
        url = "https://gateway.saxobank.com/sim/openapi/ref/v1/instruments"
        headers = {"Authorization": f"Bearer {token}"}
        
        for kw in keywords:
            params = {
                'Keywords': kw,
                'AssetTypes': 'Stock',
                'IncludeNonTradable': False
            }
            try:
                resp = requests.get(url, headers=headers, params=params)
                if resp.status_code == 200:
                    data = resp.json().get('Data', [])
                    for item in data:
                        # Simple filter: check if strictly stock and decent match
                        if item.get('AssetType') == 'Stock':
                            uics.add(item.get('Identifier')) # Identifier is typically UIC
            except Exception as e:
                logger.error(f"Universe search error for {kw}: {e}")
                
        return list(uics)

    def _scan_loop(self):
        while self.running:
            try:
                hot_list = self.perform_market_scan()
                if hot_list:
                    logger.info(f"Scanner found {len(hot_list)} Hot Candidates: {[u for u,p in hot_list]}")
                    
                    for uic, price in hot_list:
                         # Dynamic Subscription
                         self.md.add_subscription(uic)
            except Exception as e:
                logger.error(f"Scanner Loop Error: {e}")
            
            time.sleep(self.scan_interval)

    def perform_market_scan(self):
        """
        Scans the universe in batches of 50.
        Returns list of (uic, price) tuples for 'Hot Candidates'.
        """
        if not self.universe_uics:
            logger.warning("Empty universe, skipping scan.")
            return []

        token = self.auth.ensure_valid_token()
        if not token: return []

        hot_candidates = []
        batch_size = 50
        
        # Generator for batches
        batches = [self.universe_uics[i:i + batch_size] for i in range(0, len(self.universe_uics), batch_size)]
        
        for batch in batches:
            # Rate Limiter Check per batch
            if self.rate_limiter and not self.rate_limiter.can_proceed(priority='low'):
                logger.warning("Scanner paused for batch due to Rate Limit.")
                time.sleep(10) # Quick pause
                continue

            uic_str = ",".join(map(str, batch))
            url = f"https://gateway.saxobank.com/sim/openapi/trade/v1/infoprices/list?Uics={uic_str}&AssetType=Stock"
            headers = {"Authorization": f"Bearer {token}"}
            
            try:
                resp = requests.get(url, headers=headers)
                if self.rate_limiter: self.rate_limiter.add_call()
                
                if resp.status_code == 200:
                    data = resp.json().get('Data', [])
                    for item in data:
                        res = self._analyze_hot_candidate(item)
                        if res:
                            hot_candidates.append(res)
                elif resp.status_code == 429:
                    # Backoff handled by main scanner loop if needed, or trigger global limiter
                    retry = int(resp.headers.get("Retry-After", 60))
                    if self.rate_limiter: self.rate_limiter.trigger_cooldown(retry)
                    break 
            except Exception as e:
                logger.error(f"Batch scan error: {e}")
        
        return hot_candidates

    def _analyze_hot_candidate(self, item):
        """Checks if item meets criteria (>2% change)."""
        uic = item.get('Uic')
        quote = item.get('Quote', {})
        
        percent_change = quote.get('PercentChange', 0.0)
        current_price = quote.get('LastTraded')
        
        # Criteria: > 2.0%
        if percent_change > 2.0:
            symbol = item.get('DisplayAndFormat', {}).get('Symbol', f"UIC:{uic}")
            
            # Cyan Info Log
            logger.info(f"Quick Win Detected! {symbol} is up {percent_change:.2f}% (Price: {current_price})")
            return (uic, current_price)
            
        return None
