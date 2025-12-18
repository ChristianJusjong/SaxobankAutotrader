import time
import logging
import requests
import json
import threading
import websocket
import struct
from urllib.parse import urlencode
from auth_manager import SaxoAuthManager
from logger_config import logger

def decode_saxo_message(message):
    """
    Decodes the Saxo binary WebSocket message format.
    Format:
    [0-7]   MessageId (8 bytes, Little Endian)
    [8-9]   Reserved (2 bytes)
    [10]    RefId Length (1 byte)
    [11..]  RefId
    [..]    Payload Format (1 byte) - 0=JSON
    [..]    Payload Size (4 bytes, Little Endian)
    [..]    Payload Data
    """
    offset = 0
    msg_id = struct.unpack_from('<Q', message, offset)[0]
    offset += 8
    
    # Reserved
    offset += 2
    
    # RefId Length
    ref_id_len = struct.unpack_from('B', message, offset)[0]
    offset += 1
    
    # RefId
    ref_id = message[offset:offset+ref_id_len].decode('ascii')
    offset += ref_id_len
    
    # Payload Format
    payload_format = struct.unpack_from('B', message, offset)[0]
    offset += 1
    
    # Payload Size
    payload_size = struct.unpack_from('<I', message, offset)[0]
    offset += 4
    
    # Payload
    payload_data = message[offset:offset+payload_size]
    
    decoded_payload = None
    if payload_format == 0: # JSON
        try:
             decoded_payload = json.loads(payload_data.decode('utf-8'))
        except:
             decoded_payload = payload_data # Fallback
    else:
        # Protobuf or other - not handled, return raw
        decoded_payload = payload_data

    return {
        'msgId': msg_id,
        'refId': ref_id,
        'payload': decoded_payload
    }

class MarketDataManager:
    def __init__(self, auth_manager=None, context_id='BotContext'):
        self.auth = auth_manager if auth_manager else SaxoAuthManager()
        # WebSocket Streaming URL for Simulation
        # Verified correct URL: wss://sim-streaming.saxobank.com/sim/oapi/streaming/ws/connect
        self.streaming_url = "wss://sim-streaming.saxobank.com/sim/oapi/streaming/ws/connect" # Note 'oapi' not 'openapi'
        self.context_id = context_id
        self.ref_id = "PriceSub_1"
        self.live_market_state = {} # uic -> {LastPrice, QuoteUpdated}
        self.ws = None
        self.active_uics = []
        self.uic_ref_map = {} # uic -> ref_id
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def start_stream(self, uics):
        """Starts the WebSocket stream and subscribes to the given UICs."""
        self.active_uics = list(uics) # Copy
        token = self.auth.ensure_valid_token()
        if not token:
            logger.error("No valid token for streaming.")
            return

        # Build WS URL with auth params
        url = f"{self.streaming_url}?contextId={self.context_id}"
        headers = {
            "Authorization": f"Bearer {token}"
        }

        logger.info(f"Connecting to WebSocket stream at {url}...")
        
        self.ws = websocket.WebSocketApp(
            url,
            header=headers,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )

        # Run in separate thread
        wst = threading.Thread(target=self.ws.run_forever)
        wst.daemon = True
        wst.start()
        
        # Give it a moment (async connect)
        time.sleep(2)

    def _on_open(self, ws):
        logger.info("WebSocket Connected! Setting up subscriptions...")
        self._subscribe_uics(self.active_uics)

    def _on_error(self, ws, error):
        logger.error(f"WebSocket Error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        logger.info(f"WebSocket Closed: {close_status_code} - {close_msg}")

    def _subscribe_uics(self, uics, ref_id_suffix=""):
        """Subscribes to InfoPrices via REST API. suffix allows multiple subs."""
        token = self.auth.ensure_valid_token()
        url = "https://gateway.saxobank.com/sim/openapi/trade/v1/infoprices/subscriptions"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # Unique RefID for this batch
        final_ref_id = self.ref_id + ref_id_suffix
        
        data = {
            "Arguments": {
                "Uics": ",".join(map(str, uics)),
                "AssetType": "Stock"
            },
            "ContextId": self.context_id,
            "ReferenceId": final_ref_id,
            "RefreshRate": 1000 # ms
        }
        
        try:
            resp = requests.post(url, headers=headers, json=data)
            if resp.status_code == 201:
                logger.info(f"Subscription confirmed for UICs: {uics} (RefId: {final_ref_id})")
                
                # Map UICs to this RefID for future unsubscription
                with self._lock:
                    for uic in uics:
                        self.uic_ref_map[uic] = final_ref_id

                # Process initial snapshot if present
                snapshot = resp.json().get('Snapshot', {})
                if snapshot:
                    self._process_data_list(snapshot.get('Data', []))
            else:
                logger.error(f"Failed to subscribe: {resp.text}")
        except Exception as e:
            logger.error(f"Subscription error: {e}")

    def subscribe_to_ticker(self, uic):
        """Adds a single UIC to the monitoring stream dynamically."""
        with self._lock:
            if uic in self.active_uics:
                logger.debug(f"UIC {uic} is already tracked.")
                return
            
            self.active_uics.append(uic)
        
        # Subscribe using a unique RefId suffix relative to time + uic to avoid collisions
        suffix = f"_{uic}_{int(time.time())}"
        self._subscribe_uics([uic], ref_id_suffix=suffix)
        
    def add_subscription(self, uic):
        """Alias for subscribe_to_ticker."""
        self.subscribe_to_ticker(uic)

    def unsubscribe_from_ticker(self, uic):
        """Removes a UIC from monitoring and deletes its subscription."""
        ref_id = None
        
        with self._lock:
             if uic not in self.active_uics:
                 logger.warning(f"UIC {uic} not found in active list.")
                 return
             
             ref_id = self.uic_ref_map.get(uic)
             if not ref_id:
                 logger.warning(f"No Reference ID found for UIC {uic}. Cannot unsubscribe via API.")
                 # Still remove from local tracking
                 self.active_uics.remove(uic)
                 if uic in self.live_market_state: del self.live_market_state[uic]
                 return
        
        # Call API to DELETE subscription
        token = self.auth.ensure_valid_token()
        # DELETE /trade/v1/infoprices/subscriptions/{ContextId}/{ReferenceId}
        url = f"https://gateway.saxobank.com/sim/openapi/trade/v1/infoprices/subscriptions/{self.context_id}/{ref_id}"
        headers = {"Authorization": f"Bearer {token}"}
        
        try:
            resp = requests.delete(url, headers=headers)
            if resp.status_code in [202, 204, 200]:
                logger.info(f"Unsubscribed from UIC {uic} (RefId: {ref_id})")
                
                # Cleanup Local State
                with self._lock:
                    if uic in self.active_uics: self.active_uics.remove(uic)
                    if uic in self.uic_ref_map: del self.uic_ref_map[uic]
                    if uic in self.live_market_state: del self.live_market_state[uic]
                    
            else:
                logger.error(f"Failed to unsubscribe UIC {uic}: {resp.status_code} {resp.text}")
                
        except Exception as e:
            logger.error(f"Unsubscription error: {e}")

    def _on_message(self, ws, message):
        """Callback when binary message is received."""
        try:
            # Decode the binary message using custom helper
            # Message is bytes
            if isinstance(message, str):
                 # Sometimes error messages are text
                 logger.info(f"Text message received: {message}")
                 return

            decoded = decode_saxo_message(message)
            
            # Decoded message structure:
            # {
            #   'msgId': ...,
            #   'refId': ...,
            #   'payload': [...] or {...}
            # }
            
            if decoded.get('refId') == self.ref_id:
                payload = decoded.get('payload')
                self._process_data_list(payload)
                
        except Exception as e:
            logger.error(f"Error decoding/processing message: {e}")

    def _process_data_list(self, data):
        """Updates internal state with new price data."""
        if not isinstance(data, list):
             data = [data]

        with self._lock:
            for item in data:
                uic = item.get("Uic")
                quote = item.get("Quote", {})
                last_price = quote.get("LastTraded") or quote.get("Ask") or quote.get("Bid")
                
                if uic and last_price:
                    self.live_market_state[uic] = {
                        "LastPrice": last_price,
                        "Updated": time.time(),
                        "Raw": item
                    }
                    logger.info(f"Price Update: UIC {uic} = {last_price}")

    def get_latest_price(self, uic):
        with self._lock:
            return self.live_market_state.get(uic, {}).get("LastPrice")

if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    md = MarketDataManager()
    # UIC 211 is Apple
    md.start_stream([211])
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping...")
        if md.ws:
            md.ws.close()
