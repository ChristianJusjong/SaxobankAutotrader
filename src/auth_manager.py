import os
import requests
import datetime
import logging
import redis
from urllib.parse import urlencode
from dotenv import load_dotenv, set_key

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SaxoAuthManager:
    def __init__(self, env_path='.env'):
        self.env_path = env_path
        self.app_key = os.getenv('APP_KEY')
        self.app_secret = os.getenv('APP_SECRET')
        self.auth_endpoint = os.getenv('AUTH_ENDPOINT')
        self.token_endpoint = os.getenv('TOKEN_ENDPOINT')
        self.redirect_url = os.getenv('REDIRECT_URL')
        
        self.access_token = None
        self.token_expiry = None
        
        # --- Redis Integration for Token Persistence ---
        self.redis_client = None
        redis_url = os.getenv('REDIS_URL')
        if redis_url:
            try:
                self.redis_client = redis.from_url(redis_url)
                self.redis_client.ping()
                logger.info("Connected to Redis for Token Persistence.")
            except Exception as e:
                logger.error(f"Failed to connect to Redis (Auth): {e}")
                self.redis_client = None

        # Load Refresh Token (Priority: Redis > Env)
        self.refresh_token = self._load_refresh_token()
        
    def _load_refresh_token(self):
        """Loads refresh token from Redis or falls back to Environment."""
        token = None
        
        # 1. Try Redis
        if self.redis_client:
            try:
                msg = self.redis_client.get("saxotrader:refresh_token")
                if msg:
                    token = msg.decode('utf-8')
                    logger.info("Loaded Refresh Token from Redis.")
            except Exception as e:
                logger.error(f"Error loading token from Redis: {e}")
        
        # 2. Key Env var (if Redis failed or empty)
        if not token:
            token = os.getenv('REFRESH_TOKEN')
            if token:
                logger.info("Loaded Refresh Token from Environment.")
                
        return token

    def _save_refresh_token(self, token):
        """Saves refresh token to Redis and .env."""
        self.refresh_token = token
        
        # 1. Save to Redis
        if self.redis_client:
            try:
                self.redis_client.set("saxotrader:refresh_token", token)
                logger.info("Saved new Refresh Token to Redis.")
            except Exception as e:
                logger.error(f"Error saving token to Redis: {e}")
        
        # 2. Save to .env (Local Backup)
        try:
            os.environ['REFRESH_TOKEN'] = token 
            if os.path.exists(self.env_path):
                set_key(self.env_path, "REFRESH_TOKEN", token)
        except Exception as e:
            logger.warning(f"Could not update .env file: {e}")

    def get_login_url(self, state='init'):
        """Generates the URL for the user to authorize the app."""
        params = {
            'response_type': 'code',
            'client_id': self.app_key,
            'redirect_uri': self.redirect_url,
            'state': state
        }
        return f"{self.auth_endpoint}?{urlencode(params)}"

    def exchange_code(self, code):
        """Exchanges the authorization code for an access token."""
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': self.app_key,
            'client_secret': self.app_secret,
            'redirect_uri': self.redirect_url
        }
        return self._request_token(data)

    def refresh_access_token(self):
        """Refreshes the access token using the stored refresh token."""
        if not self.refresh_token:
            logger.error("No refresh token available. Please login first.")
            return False

        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.app_key,
            'client_secret': self.app_secret
        }
        return self._request_token(data)

    def _request_token(self, data):
        """Helper to make the token request and update state."""
        try:
            response = requests.post(self.token_endpoint, data=data)
            
            # Better Error Logging for HTML responses
            if not response.ok:
                logger.error(f"Token Request Failed: {response.status_code}")
                try:
                    # Attempt to parse and redact
                    err_data = response.json()
                    # Redact potential sensitive keys
                    for key in ['access_token', 'refresh_token', 'client_secret']:
                        if key in err_data:
                            err_data[key] = "***REDACTED***"
                    logger.error(f"Response: {err_data}")
                except:
                    # Text fallback - risky to log full body if it contains echoed secrets
                    # Log only first 100 chars and ensure no obvious token patterns (basic safety)
                    safe_text = response.text[:200]
                    logger.error(f"Response Body (First 200 chars): {safe_text}...")
                return False

            token_data = response.json()

            self.access_token = token_data.get('access_token')
            expires_in = token_data.get('expires_in') # Seconds
            
            # Update Refresh Token if returned (It rotates!)
            new_refresh = token_data.get('refresh_token')
            if new_refresh:
                self._save_refresh_token(new_refresh)
            
            # Calculate expiry time (subtract a buffer, e.g., 60 seconds)
            if expires_in:
                self.token_expiry = datetime.datetime.now() + datetime.timedelta(seconds=int(expires_in) - 60)

            logger.info("Token retrieved successfully.")
            return True

        except Exception as e:
            logger.error(f"An unexpected error occurred during token request: {e}", exc_info=True)
            return False

    def ensure_valid_token(self):
        """Checks if token is valid, refreshes if necessary. Returns access_token."""
        if not self.access_token or (self.token_expiry and datetime.datetime.now() >= self.token_expiry):
            logger.info("Access token expired or missing. Attempting refresh...")
            
            # Reload from Redis just in case another worker refreshed it
            current_stored = self._load_refresh_token()
            if current_stored and current_stored != self.refresh_token:
                logger.info("Newer refresh token found in storage. Updating...")
                self.refresh_token = current_stored

            if not self.refresh_access_token():
                logger.error("Failed to refresh token. Manual login required.")
                return None
        return self.access_token

if __name__ == "__main__":
    # Simple test execution
    auth = SaxoAuthManager()
    print(f"Login URL: {auth.get_login_url()}")
    # In a real scenario, you'd capture the code from the redirect and call auth.exchange_code(code)
