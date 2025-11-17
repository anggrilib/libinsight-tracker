import os
import requests
import base64
from typing import Optional, Dict

class SpringshareAuth:
    def __init__(self):
        """Initialize Springshare authentication with environment variables"""
        self.key = os.environ.get('LI_KEY')
        self.secret = os.environ.get('LI_SECRET')
        
        if not self.key or not self.secret:
            raise ValueError("LibInsight credentials not found in environment variables")
            
        self.token_url = 'https://acaweb.libinsight.com/v1.0/oauth/token'
        self.scope = ['GET']
        
    def get_authorization_header(self) -> str:
        """Create Base64 encoded authorization header"""
        credentials = f"{self.key}:{self.secret}"
        encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
        return f"Basic {encoded_credentials}"
        
    def get_token(self) -> Optional[Dict]:
        """Get an OAuth2 token using client credentials flow with Basic Auth"""
        try:
            headers = {
                'Authorization': self.get_authorization_header(),
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'grant_type': 'client_credentials',
                'scope': ' '.join(self.scope)
            }
            
            response = requests.post(self.token_url, headers=headers, data=data)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            print(f"Error getting token: {str(e)}")
            if hasattr(e.response, 'text'):
                print(f"Response text: {e.response.text}")
            return None
