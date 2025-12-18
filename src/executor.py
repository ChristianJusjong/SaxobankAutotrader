import logging
import requests
import json

logger = logging.getLogger(__name__)

class OrderExecutor:
    def __init__(self, account_manager, dry_run=True):
        self.account = account_manager
        self.dry_run = dry_run
        self.base_url = account_manager.base_url # Re-use base URL from account manager
        
        if self.dry_run:
            logger.warning("EXECUTOR IS IN SIMULATION MODE (DRY RUN). NO REAL TRADES WILL BE PLACED.")

    def _get_headers(self):
        return self.account._get_headers() # Reuse auth headers logic

    def place_order(self, uic, amount, action='Buy', order_type='Market', price=None, asset_type='Stock'):
        """
        Places an order.
        action: 'Buy' or 'Sell'
        """
        account_key = self.account.get_account_key()
        if not account_key:
            logger.error("Cannot place order: No AccountKey found.")
            return False

        # Construct Order Payload
        payload = {
            "Uic": uic,
            "AssetType": asset_type,
            "Amount": amount,
            "BuySell": action,
            "OrderDuration": {"DurationType": "DayOrder"},
            "AccountKey": account_key,
            "OrderType": order_type
        }
        
        if order_type == 'Limit':
            if price is None:
                logger.error("Limit order requires a price.")
                return False
            payload['OrderPrice'] = price

        if self.dry_run:
            logger.info(f"[SIMULATION] would place order: {json.dumps(payload, indent=2)}")
            return True # Pretend success

        # Real Execution
        endpoint = f"{self.base_url}/trade/v1/orders"
        try:
            response = requests.post(endpoint, headers=self._get_headers(), json=payload)
            response.raise_for_status()
            data = response.json()
            logger.info(f"Order placed successfully. OrderId: {data.get('OrderId')}")
            return True
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return False

    def cancel_all_orders(self):
        """Cancels all open orders."""
        if self.dry_run:
            logger.info("[SIMULATION] would CANCEL ALL open orders.")
            return

        logger.warning("KILL SWITCH: Attempting to cancel all open orders...")
        
        # 1. Fetch Open Orders
        # Endpoint: /trade/v1/orders?FieldGroups=DisplayAndFormat&ClientKey=...
        # We'll just fetch for the account
        account_key = self.account.get_account_key()
        endpoint = f"{self.base_url}/trade/v1/orders"
        params = {
            'AccountKey': account_key,
            'FieldGroups': 'DisplayAndFormat'
        }
        
        try:
            resp = requests.get(endpoint, headers=self._get_headers(), params=params)
            resp.raise_for_status()
            orders = resp.json().get('Data', [])
            
            for order in orders:
                order_id = order.get('OrderId')
                if order_id:
                    self._cancel_single_order(order_id, account_key)
                    
        except Exception as e:
            logger.error(f"Error fetching orders for cancellation: {e}")

    def _cancel_single_order(self, order_id, account_key):
        delete_endpoint = f"{self.base_url}/trade/v1/orders/{order_id}?AccountKey={account_key}"
        try:
            resp = requests.delete(delete_endpoint, headers=self._get_headers())
            resp.raise_for_status()
            logger.info(f"Cancelled Order {order_id}")
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")

    def close_all_positions(self):
        """Closes all open positions at Market Price."""
        if self.dry_run:
            logger.info("[SIMULATION] would CLOSE ALL positions.")
            return

        logger.warning("KILL SWITCH: Attempting to close all positions...")
        
        account_key = self.account.get_account_key()
        # Fetch Positions
        endpoint = f"{self.base_url}/port/v1/positions"
        params = {
            'AccountKey': account_key,
            'FieldGroups': 'DisplayAndFormat,PositionBase' 
        }
        
        try:
            resp = requests.get(endpoint, headers=self._get_headers(), params=params)
            resp.raise_for_status()
            positions = resp.json().get('Data', [])
            
            for pos in positions:
                # To close, we place an opposing order
                position_base = pos.get('PositionBase', {})
                uic = position_base.get('Uic')
                amount = position_base.get('Amount') # Positive or negative
                asset_type = position_base.get('AssetType')
                
                if not uic or not amount: continue
                
                # If we are Long (Amount > 0), we Sell. If Short (Amount < 0), we Buy.
                action = 'Sell' if amount > 0 else 'Buy'
                abs_amount = abs(amount)
                
                logger.info(f"Closing position UIC {uic} ({amount}): {action} {abs_amount}")
                
                # Careful: Close-All implies market order usually
                self.place_order(uic, abs_amount, action=action, order_type='Market', asset_type=asset_type)
                
        except Exception as e:
            logger.error(f"Error fetching positions for closure: {e}")

    def kill_switch(self):
        """EMERGENCY: Cancels all orders and closes all positions."""
        logger.critical("!!! KILL SWITCH ACTIVATED !!!")
        self.cancel_all_orders()
        self.close_all_positions()

if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    from account_info import AccountManager
    
    acc = AccountManager()
    # FORCE SIMULATION MODE
    executor = OrderExecutor(acc, dry_run=True)
    
    # Test Buy
    executor.place_order(211, 10, 'Buy', 'Market')
    
    # Test Kill Switch (Simulation)
    executor.kill_switch()
