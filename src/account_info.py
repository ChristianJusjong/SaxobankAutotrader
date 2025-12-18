import requests
import logging
import os
from auth_manager import SaxoAuthManager

logger = logging.getLogger(__name__)

class AccountManager:
    def __init__(self, auth_manager=None):
        self.auth = auth_manager if auth_manager else SaxoAuthManager()
        # Use generic gateway URL for simulation.
        # Live would be: https://gateway.saxobank.com/openapi
        self.base_url = os.getenv("SAXO_BASE_URL", "https://gateway.saxobank.com/sim/openapi")
        self.account_key = None

    def _get_headers(self):
        token = self.auth.ensure_valid_token()
        if not token:
            raise Exception("Failed to get valid access token")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    def get_account_key(self):
        """Fetches the primary AccountKey for the user."""
        if self.account_key:
            return self.account_key

        endpoint = f"{self.base_url}/port/v1/accounts/me"
        try:
            response = requests.get(endpoint, headers=self._get_headers())
            response.raise_for_status()
            data = response.json()
            
            # Assuming the first account is the primary one for now
            if data.get('Data'):
                # Many Saxo endpoints wrap lists in 'Data'
                accounts = data['Data']
                if accounts:
                    self.account_key = accounts[0]['AccountKey']
                    logger.info(f"Retrieved AccountKey: {self.account_key}")
                    return self.account_key
            else:
                # Some versions might return list directly or dict
                logger.warning(f"Unexpected response format from accounts endpoint: {data}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching AccountKey: {e}")
            return None

    def get_commissions(self, uic, quantity, price, asset_type="Stock"):
        """
        Calculates the estimated commission for a trade.
        Returns the Cost in AGREED ACCOUNT CURRENCY (usually implied by the API response).
        """
        account_key = self.get_account_key()
        if not account_key:
            return 0.0

        from urllib.parse import quote
        safe_key = quote(account_key)
        endpoint = f"{self.base_url}/cs/v1/tradingconditions/cost/{safe_key}/{uic}/{asset_type}"
        
        params = {
            'Amount': quantity,
            'Price': price,
            'FieldGroups': 'DisplayAndFormat' 
        }

        try:
            response = requests.get(endpoint, headers=self._get_headers(), params=params)
            response.raise_for_status()
            data = response.json()
            
            costs = data.get('Cost', {})
            cost_details = costs.get('Long') or costs.get('Short')
            
            if cost_details:
                total_cost = cost_details.get('TotalCost', 0.0)
                return float(total_cost)
            
            return 0.0

        except Exception as e:
            logger.error(f"Error calculating commission for UIC {uic}: {e}")
            return 0.0

    def get_fx_rate(self, from_curr, to_curr):
        """
        Fetches or simulates FX rate.
        For Simulation/Audit, we default to static known rates if not provided.
        Real implementation would query Saxo FX prices.
        """
        if from_curr == to_curr: return 1.0
        # Mock Rates for Logic Check
        if from_curr == 'USD' and to_curr == 'EUR': return 0.90
        if from_curr == 'EUR' and to_curr == 'USD': return 1.11
        return 1.0 # Default

    def calculate_net_profit(self, entry_price, exit_price, quantity, uic, asset_type="Stock", 
                           instrument_currency="USD", account_currency="EUR", 
                           include_slippage=False):
        """
        Calculates Audit-Grade Net Profit.
        Includes:
        - Gross Profit (converted to Acct Currency)
        - Commission (from API)
        - FX Friction (0.5% on Notional Value if Currencies differ)
        - Slippage Buffer (Optional 5 bps safety margin)
        """
        fx_rate = self.get_fx_rate(instrument_currency, account_currency)
        
        # 1. Gross Profit in Instrument Currency
        gross_pnl_instr = (exit_price - entry_price) * quantity
        
        # 2. Convert to Account Currency
        gross_pnl_acct = gross_pnl_instr * fx_rate
        
        # 3. Commissions (API returns in Account Currency)
        # We use average price for cost estimation
        avg_price = (entry_price + exit_price) / 2
        commissions_acct = self.get_commissions(uic, quantity, avg_price, asset_type)
        
        # 4. FX Friction (Hidden Fee on Notional Volume)
        fx_cost_acct = 0.0
        if instrument_currency != account_currency:
            notional_entry = entry_price * quantity
            notional_exit = exit_price * quantity
            total_volume_instr = notional_entry + notional_exit
            
            # Conversion Fee 0.5% (0.005)
            fx_fee_pct = 0.005 
            fx_cost_acct = (total_volume_instr * fx_rate) * fx_fee_pct

        # 5. Slippage Buffer (Virtual Cost for Decision Making)
        slippage_cost_acct = 0.0
        if include_slippage:
            # 5 basis points (0.0005) on the Exit Value
            slippage_bps = 0.0005
            exit_value_acct = (exit_price * quantity) * fx_rate
            slippage_cost_acct = exit_value_acct * slippage_bps
        
        # Total Deductions
        total_costs = commissions_acct + fx_cost_acct + slippage_cost_acct
        
        net_profit = gross_pnl_acct - total_costs
        
        logger.info(f"Profit Audit UIC {uic}: Gross({gross_pnl_acct:.2f}) - Comm({commissions_acct:.2f}) - FX({fx_cost_acct:.2f}) - Slip({slippage_cost_acct:.2f}) = Net({net_profit:.2f}) {account_currency}")
        
        return net_profit

    def calculate_breakeven_move(self, entry_price, quantity, uic, asset_type="Stock", 
                               instrument_currency="USD", account_currency="EUR"):
        """
        Calculates how much price must move per share (in Instrument Currency) 
        to cover ALL round-trip costs (Comm + FX).
        """
        fx_rate = self.get_fx_rate(instrument_currency, account_currency)
        
        # Estimate Fixed Costs (Commissions)
        commissions_acct = self.get_commissions(uic, quantity, entry_price, asset_type)
        
        # Estimate FX Costs (Round Trip)
        fx_cost_acct = 0.0
        if instrument_currency != account_currency:
            notional_round_trip = (entry_price * quantity) * 2
            fx_cost_acct = (notional_round_trip * fx_rate) * 0.005
            
        total_cost_acct = commissions_acct + fx_cost_acct
        
        # Convert Total Cost back to Instrument Currency to get Per-Share Move
        if fx_rate == 0: fx_rate = 1.0
        total_cost_instr = total_cost_acct / fx_rate
        
        breakeven_move_per_share = total_cost_instr / quantity
        
        return breakeven_move_per_share

    def evaluate_trade(self, entry_price, current_price, quantity, uic, instrument_currency="USD"):
        """
        Higher level 'Profit Guard' check.
        Returns True if SAFE TO SELL.
        """
        # Hardcoded Acct Currency for now
        acct_curr = "EUR" 
        
        net = self.calculate_net_profit(
            entry_price, current_price, quantity, uic, 
            instrument_currency=instrument_currency, 
            account_currency=acct_curr,
            include_slippage=True # STRICT MODE
        )
        
        return net > 0

if __name__ == "__main__":
    # Test script
    acct = AccountManager()
    
    # Test getting account key
    key = acct.get_account_key()
    if key:
        print(f"Primary Account Key: {key}")
        
        # Test profit calc for a dummy trade (e.g. Apple UIC 211, assume price 150 -> 155)
        # Note: API calls will fail if UIC is invalid or Market is closed/Sim unsupported for that specific one without data
        # We'll just try it.
        profit = acct.calculate_net_profit(150, 155, 10, 211) 
        print(f"Calculated Net Profit: {profit}")
    else:
        print("Could not retrieve account key.")
