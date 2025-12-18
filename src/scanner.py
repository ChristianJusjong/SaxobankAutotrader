import logging
import requests
import time
import threading

# ANSI Color Codes for "Sophisticated Logging"
CYAN = "\033[96m"
RESET = "\033[0m"

logger = logging.getLogger("Scanner")

class MarketScanner:
    def __init__(self, auth_manager, market_data_manager):
        self.auth = auth_manager
        self.md = market_data_manager
        self.running = False
        # Example: US Big Tech & High Volatility Tickers (UICs)
        # In a real dynamic search, we'd query /ref/v1/instruments
        # For this demo, we pre-seed a "Market Watchlist" of UICs to scan
        # 211: Apple, 137: Google (Demo UICs might differ, using placeholders/common ones from Sim)
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
        token = self.auth.ensure_valid_token()
        if not token: return
        
        # 1. Fetch Snapshot for entire watchlist
        # Endpoint: GET /trade/v1/infoprices/list?Uics=...&AssetType=Stock
        uic_str = ",".join(map(str, self.watchlist_uics))
        url = f"https://gateway.saxobank.com/sim/openapi/trade/v1/infoprices/list?Uics={uic_str}&AssetType=Stock"
        
        headers = {"Authorization": f"Bearer {token}"}
        
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json().get('Data', [])
            for item in data:
                self._analyze_instrument(item)
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
            
            # Log with CYAN color
            msg = f"{CYAN}[SCANNER] Quick Win Detected! {symbol} is up {percent_change:.2f}% (Price: {current_price}). Adding to High-Speed Stream.{RESET}"
            print(msg) # Ensure it goes to console with color
            logger.info(f"Quick Win Detected: {symbol} (+{percent_change}%)")
            
            # Dynamic Subscription
            self.md.add_subscription(uic)
