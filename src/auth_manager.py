import os
import requests
import datetime
import logging
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
        self.refresh_token = os.getenv('REFRESH_TOKEN')
        self.token_expiry = None

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
            response.raise_for_status()
            token_data = response.json()

            self.access_token = token_data.get('access_token')
            self.refresh_token = token_data.get('refresh_token')
            expires_in = token_data.get('expires_in') # Seconds
            
            # Calculate expiry time (subtract a buffer, e.g., 60 seconds)
            if expires_in:
                self.token_expiry = datetime.datetime.now() + datetime.timedelta(seconds=int(expires_in) - 60)

            # Update .env with new refresh token to persist it
            if self.refresh_token:
                 # Note: This updates the file on disk, which is useful for restarts
                set_key(self.env_path, "REFRESH_TOKEN", self.refresh_token)

            logger.info("Token retrieved successfully.")
            return True

        except requests.exceptions.HTTPError as e:
            logger.error(f"Failed to retrieve token: {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
            return False

    def ensure_valid_token(self):
        """Checks if token is valid, refreshes if necessary. Returns access_token."""
        if not self.access_token or (self.token_expiry and datetime.datetime.now() >= self.token_expiry):
            logger.info("Access token expired or missing. Attempting refresh...")
            if not self.refresh_access_token():
                logger.error("Failed to refresh token. Manual login required.")
                return None
        return self.access_token

if __name__ == "__main__":
    # Simple test execution
    auth = SaxoAuthManager()
    print(f"Login URL: {auth.get_login_url()}")
    # In a real scenario, you'd capture the code from the redirect and call auth.exchange_code(code)
