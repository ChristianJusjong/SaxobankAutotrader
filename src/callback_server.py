from flask import Flask, request
from auth_manager import SaxoAuthManager
import threading
import time

import os

app = Flask(__name__)
auth_manager = SaxoAuthManager()

@app.route('/callback')
def callback():
    code = request.args.get('code')
    state = request.args.get('state')
    
    if code:
        if auth_manager.exchange_code(code):
            def shutdown():
                time.sleep(3)
                print("Authentication successful. Shutting down server...")
                os._exit(0)
            
            threading.Thread(target=shutdown).start()
            return "Authentication successful! You can close this window. The script will exit shortly."
        else:
            return "Authentication failed.", 400
    return "No code received.", 400

def run_server():
    app.run(port=5000)

if __name__ == "__main__":
    print(f"Please visit this URL to login: {auth_manager.get_login_url()}")
    run_server()
