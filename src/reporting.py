from collections import defaultdict
from logger_config import logger

class DailyReporter:
    def __init__(self, log_dir, account_manager):
        self.log_dir = log_dir
        self.account = account_manager
        self.daily_report_path = os.path.join(log_dir, 'daily_report.log')
        
    def log_health(self, strategy):
        """
        Logs bot health metrics: CPU, RAM, Active Positions, Peak Tracking.
        """
        try:
            # System Metrics
            process = psutil.Process()
            mem_info = process.memory_info()
            cpu_pct = process.cpu_percent(interval=None)
            ram_mb = mem_info.rss / 1024 / 1024
            
            # Application Metrics
            active_count = len(strategy.positions)
            tracking_info = []
            for uic, data in strategy.positions.items():
                tracking_info.append(f"UIC:{uic} Ent:{data['entry_price']} Max:{data['max_price']}")
            
            msg = (
                f"HEALTH CHECK | CPU: {cpu_pct:.1f}% | RAM: {ram_mb:.1f}MB | "
                f"Active Positions: {active_count} | {', '.join(tracking_info)}"
            )
            
            # Log to main log and reporting log
            logger.info(msg)
            with open(self.daily_report_path, 'a') as f:
                f.write(f"{datetime.datetime.now()} - {msg}\n")
                
        except Exception as e:
            logger.error(f"Error logging health: {e}")

    def calculate_daily_pnl(self, trades_log_path):
        """
        Parses `trades.log` for the current day to calculate Theoretical PnL.
        This relies on trades.log having a specific format or we can use internal tracking.
        For robust reporting, we'll scan the log for "EXECUTION SUCCESS" entries.
        """
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        total_pnl = 0.0
        trades_count = 0
        
        # NOTE: Parsing text logs is fragile. In a production system, use a DB.
        # But for this 20-day test, we scan for our specific log format:
        # "EXECUTION SUCCESS: {action} {uic}" 
        # Wait, the log doesn't have PRICE info in the success message in main.py yet!
        # We need to ensure main.py logs the PRICE and COST in the success message.
        
        # Placeholder for now until we update main.py logging format.
        logger.info(f"Daily Report for {today_str}: Calculation pending log format update.")

    def log_simulation_trade(self, action, uic, price, reason):
        """
        Explicitly logs a 'Dry Run' trade decision.
        """
        msg = f"[DRY RUN] WOULD HAVE {action} {uic} @ {price}. Reason: {reason}"
        logger.info(msg)
        with open(self.daily_report_path, 'a') as f:
            f.write(f"{datetime.datetime.now()} - {msg}\n")
