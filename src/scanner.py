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
            self.universe_uics = self.get_us_universe()
            logger.info(f"Market Scanner initialized with {len(self.universe_uics)} instruments.")
        except Exception as e:
            logger.error(f"Failed to fetch universe: {e}")
            # Fallback
            self.universe_uics = [211, 212, 111, 137] 

        t = threading.Thread(target=self._scan_loop)
        t.daemon = True
        t.start()
        logger.info(f"Market Scanner loop started (Interval: {self.scan_interval}s)")

    def get_us_universe(self):
        """
        Fetches 'broad market' universe from Saxo via ExchangeId=NYSE/NASDAQ.
        """
        token = self.auth.ensure_valid_token()
        if not token: return []
        
        uics = set()
        url = "https://gateway.saxobank.com/sim/openapi/ref/v1/instruments"
        headers = {"Authorization": f"Bearer {token}"}
        
        # User requested Exchanges
        exchanges = ["NYSE", "NASDAQ"]
        
        for ex in exchanges:
            params = {
                'ExchangeId': ex,
                'AssetTypes': 'Stock',
                'IncludeNonTradable': False
            }
            try:
                resp = requests.get(url, headers=headers, params=params)
                if resp.status_code == 200:
                    data = resp.json().get('Data', [])
                    count = 0
                    for item in data:
                        # Ensure strictly Stock
                        if item.get('AssetType') == 'Stock':
                            uics.add(item.get('Identifier'))
                            count += 1
                    logger.info(f"Loaded {count} instruments from {ex}")
                else:
                    logger.warning(f"Failed to fetch {ex} universe: {resp.status_code} {resp.text}")
                    
            except Exception as e:
                logger.error(f"Universe search error for {ex}: {e}")
                
        # Fallback if empty (Sim might not index cleanly by ExchangeId without specific subscription)
        if not uics:
            logger.warning("Exchange fetch returned 0 results. Falling back to Keyword search for 'US Tech'...")
            # Fallback Logic (Quick Copy)
            keywords = ["Apple", "Microsoft", "Tesla", "Amazon", "Nvidia"]
            for kw in keywords:
                try:
                    p = {'Keywords': kw, 'AssetTypes': 'Stock'}
                    r = requests.get(url, headers=headers, params=p)
                    if r.status_code == 200:
                        for i in r.json().get('Data', []):
                           uics.add(i.get('Identifier'))
                except: pass
                
        return list(uics)

    def _scan_loop(self):
        while self.running:
            try:
                hot_list = self.perform_market_scan()
                if hot_list:
                    # hot_list is now (uic, price, asset_type)
                    # For logging purposes, extract uics
                    uic_display = [h[0] for h in hot_list]
                    logger.info(f"Scanner found {len(hot_list)} Hot Candidates: {uic_display}")
                    
                    for uic, price, asset_type in hot_list:
                         # Dynamic Subscription
                         self.md.add_subscription(uic)
            except Exception as e:
                logger.error(f"Scanner Loop Error: {e}")
            
            time.sleep(self.scan_interval)

    def perform_market_scan(self):
        """
        Scans the universe in batches of 50.
        Returns list of (uic, price, asset_type) tuples for 'Hot Candidates'.
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
                    max_change = 0.0
                    for item in data:
                        quote = item.get('Quote', {})
                        pct = abs(quote.get('PercentChange', 0.0))
                        if pct > max_change: max_change = pct
                        
                        res = self._analyze_hot_candidate(item)
                        if res:
                            hot_candidates.append(res)
                            
                    logger.info(f"Scanner Batch ({len(data)} items) processed. Top Mover: {max_change:.2f}%")
                    
                elif resp.status_code == 429:
                    # Backoff handled by main scanner loop if needed, or trigger global limiter
                    retry = int(resp.headers.get("Retry-After", 60))
                    if self.rate_limiter: self.rate_limiter.trigger_cooldown(retry)
                    break 
            except Exception as e:
                logger.error(f"Batch scan error: {e}")
            
            # rate limit buffer
            time.sleep(0.5)
        
        return hot_candidates

    def _analyze_hot_candidate(self, item):
        """Checks if item meets criteria (>1.5% change) AND Price limits ($1-$20)."""
        uic = item.get('Uic')
        asset_type = item.get('AssetType', 'Stock')
        quote = item.get('Quote', {})
        
        percent_change = quote.get('PercentChange', 0.0)
        current_price = quote.get('LastTraded', 0.0)
        
        # 1. Price Filter (Micro-Capital: $1 - $20)
        # corresponds roughly to 7kr - 140kr
        if not (1.0 <= current_price <= 20.0):
            return None
        
        # 2. Hot Criteria: > 1.5%
        if percent_change > 1.5:
            symbol = item.get('DisplayAndFormat', {}).get('Symbol', f"UIC:{uic}")
            
            # Cyan Info Log
            logger.info(f"Quick Win Detected! {symbol} is up {percent_change:.2f}% (Price: {current_price})")
            return (uic, current_price, asset_type)
            
        return None
