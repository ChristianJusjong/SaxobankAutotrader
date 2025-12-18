import pytest
import sys
import os

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from account_info import AccountManager

class MockAccountManager(AccountManager):
    """
    Mocking the network calls to test pure math logic.
    """
    def __init__(self, account_currency='EUR'):
        # Skip super init which calls API
        self.auth = None
        self.base_url = "mock"
        self.account_key = "mock_key"
        self.base_currency = account_currency
        
        # Configuration for Audit
        self.fx_fee_pct = 0.005 # 0.5%
        self.slippage_bps = 5 # 5 basis points
        self.min_commission = 1.0 # $1 minimum

    def get_commissions(self, uic, quantity, price, asset_type="Stock"):
        """Simulate commissions."""
        # Standard: 0.1% or Min $1
        commission = max(self.min_commission, price * quantity * 0.001)
        return commission

    # We will override calculate_net_profit in the actual class, 
    # but for testing the OLD logic vs NEW logic, we might need to verify the change.
    # Here we assume we are testing the NEW method signature we are ABOUT to write.
    
    def get_fx_rate(self, from_curr, to_curr):
        if from_curr == to_curr: return 1.0
        if from_curr == 'USD' and to_curr == 'EUR': return 0.90
        return 1.0

# -------------------------------------------------------------------------
# SCENARIO 1: Winning trade that barely clears costs
# -------------------------------------------------------------------------
def test_winning_trade_clears_costs():
    """
    Entry: $1000 total ($100 * 10)
    Exit: $1005 total ($100.5 * 10)
    Gross Profit: $5
    """
    mgr = MockAccountManager(account_currency='USD')
    
    # Explicitly pass account_currency='USD' to avoid FX fees for this specific test
    net = mgr.calculate_net_profit(100, 100.5, 10, uic=123, 
                                 instrument_currency='USD', 
                                 account_currency='USD')
    
    assert net > 0
    print(f"Scenario 1 Net: {net}")

# -------------------------------------------------------------------------
# SCENARIO 2: Profitable on paper, loses on FX
# -------------------------------------------------------------------------
def test_paper_profit_fx_loss():
    """
    Account: EUR. Instrument: USD.
    FX Friction: 0.5% on Notional.
    Net: 45 (Profit) - 90 (Fees) = -45 EUR.
    """
    mgr = MockAccountManager(account_currency='EUR')
    
    # This defaults to EUR account in signature, so FX applies
    net = mgr.calculate_net_profit(100, 100.5, 100, uic=123, instrument_currency='USD')
    
    assert net < 0
    print(f"Scenario 2 Net: {net}")

# -------------------------------------------------------------------------
# SCENARIO 3: Profit Guard Floor with Slippage
# -------------------------------------------------------------------------
def test_profit_guard_floor():
    """
    We simulate the 'Profit Guard' check.
    """
    mgr = MockAccountManager(account_currency='USD')
    
    # Case A: Good profit (Needs to be substantial to cover 5bps slippage + comms)
    # Entry 100, Exit 102 (2% gain). Qty 100. Gross $200.
    # Slip: 10200 * 0.0005 = $5.1.
    # Comm: ~$10.
    # Net: ~$185.
    net_good = mgr.calculate_net_profit(100, 102, 100, uic=123, 
                                      instrument_currency='USD', 
                                      account_currency='USD', # No FX
                                      include_slippage=True)
    assert net_good > 0
    
    # Case B: Razor thin profit, killed by slippage buffer
    # Entry 100, Exit 100.04 (4 cent gain). Gross $4.
    # Comm: ~$1. (assuming min)
    # Slip: 10004 * 0.0005 = $5.
    # Net = 4 - 1 - 5 = -2.
    net_fail = mgr.calculate_net_profit(100, 100.04, 100, uic=123, 
                                      instrument_currency='USD', 
                                      account_currency='USD',
                                      include_slippage=True)
    
    assert net_fail < 0
    print(f"Scenario 3 Net Fail: {net_fail}")


