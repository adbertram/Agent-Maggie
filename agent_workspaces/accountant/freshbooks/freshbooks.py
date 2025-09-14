"""
FreshBooks API Integration Module with Integrated Token Management

This module provides functions to interact with the FreshBooks API for managing
invoices and clients, with built-in automatic token refresh handling.
"""

import os
import json
import tempfile
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv, set_key

# Load environment variables (override=True to reload changes)
load_dotenv(override=True)


class FreshBooksClient:
    """Client for interacting with FreshBooks API with automatic token management"""
    
    def __init__(self, account_id: str = None, access_token: str = None):
        """
        Initialize FreshBooks client
        
        Args:
            account_id: Your FreshBooks account ID (defaults to FRESHBOOKS_ACCOUNT_ID env var)
            access_token: OAuth2 access token for authentication (defaults to FRESHBOOKS_ACCESS_TOKEN env var)
        """
        # Load environment variables
        load_dotenv(override=True)
        
        self.account_id = account_id or os.getenv('FRESHBOOKS_ACCOUNT_ID', 'ogqZ2g')
        self.access_token = access_token or os.getenv('FRESHBOOKS_ACCESS_TOKEN')
        self.refresh_token = os.getenv('FRESHBOOKS_REFRESH_TOKEN')
        self.token_expires_at = os.getenv('FRESHBOOKS_TOKEN_EXPIRES_AT')
        
        # OAuth configuration
        self.client_id = os.getenv('FRESHBOOKS_CLIENT_ID')
        self.client_secret = os.getenv('FRESHBOOKS_CLIENT_SECRET')
        self.redirect_uri = os.getenv('FRESHBOOKS_REDIRECT_URI')
        self.token_url = 'https://api.freshbooks.com/auth/oauth/token'
        self.env_path = '.env'
        
        if not self.access_token:
            raise ValueError(
                "No access token available. Please authenticate first:\n"
                "1. Visit the FreshBooks OAuth URL\n"
                "2. Get authorization code\n"
                "3. Run: python freshbooks.py AUTH_CODE"
            )
        
        self.base_url = "https://api.freshbooks.com"
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    def atomic_save_tokens(self, access_token: str, refresh_token: str, expires_in: int = 43200):
        """
        Atomically save both tokens to prevent loss of single-use refresh token
        
        CRITICAL: FreshBooks refresh tokens are single-use! If we don't save the new
        refresh token after using it, we'll need to manually re-authenticate.
        
        Args:
            access_token: New access token
            refresh_token: New refresh token (single-use, must not be lost!)
            expires_in: Token lifetime in seconds (default 12 hours)
        """
        # Calculate expiration timestamp
        expires_at = datetime.now().timestamp() + expires_in
        
        # Create backup of current .env
        backup_path = f"{self.env_path}.backup"
        if os.path.exists(self.env_path):
            with open(self.env_path, 'r') as f:
                backup_content = f.read()
            with open(backup_path, 'w') as f:
                f.write(backup_content)
        
        try:
            # Update all token-related values atomically
            set_key(self.env_path, 'FRESHBOOKS_ACCESS_TOKEN', access_token)
            set_key(self.env_path, 'FRESHBOOKS_REFRESH_TOKEN', refresh_token)
            set_key(self.env_path, 'FRESHBOOKS_TOKEN_EXPIRES_AT', str(expires_at))
            
            # Update instance variables
            self.access_token = access_token
            self.refresh_token = refresh_token
            self.token_expires_at = str(expires_at)
            self.headers['Authorization'] = f"Bearer {access_token}"
            
            # Remove backup on success
            if os.path.exists(backup_path):
                os.remove(backup_path)
                
            print(f"✓ Tokens saved atomically at {datetime.now().isoformat()}")
            
        except Exception as e:
            # Restore from backup on failure
            print(f"ERROR saving tokens: {e}")
            if os.path.exists(backup_path):
                with open(backup_path, 'r') as f:
                    backup_content = f.read()
                with open(self.env_path, 'w') as f:
                    f.write(backup_content)
                print("Restored from backup")
            raise
    
    def is_token_expired(self) -> bool:
        """Check if access token is expired or about to expire (within 5 minutes)"""
        if not self.token_expires_at:
            return True
        
        try:
            expires_at = float(self.token_expires_at)
            # Consider expired if less than 5 minutes remaining
            return datetime.now().timestamp() > (expires_at - 300)
        except (ValueError, TypeError):
            return True
    
    def refresh_access_token(self) -> Dict:
        """
        Refresh the access token using the single-use refresh token
        
        CRITICAL: This consumes the refresh token! The new refresh token
        MUST be saved or you'll need to re-authenticate manually.
        
        Returns:
            Token data including new access and refresh tokens
        """
        if not self.refresh_token:
            raise ValueError(
                "No refresh token available - manual re-authentication required.\n"
                "Run: python freshbooks.py AUTH_CODE"
            )
        
        print(f"Refreshing token at {datetime.now().isoformat()}")
        
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }
        
        response = requests.post(self.token_url, data=data)
        
        if response.status_code != 200:
            error_data = response.json()
            if error_data.get('error') == 'invalid_grant':
                raise ValueError(
                    f"Refresh token is invalid (already used or revoked).\n"
                    f"Manual re-authentication required.\n"
                    f"This usually happens when:\n"
                    f"1. The refresh token was used but new token wasn't saved\n"
                    f"2. Multiple processes tried to refresh simultaneously\n"
                    f"3. The token was manually revoked\n\n"
                    f"To fix: Get a new auth code and run: python freshbooks.py AUTH_CODE"
                )
            response.raise_for_status()
        
        token_data = response.json()
        
        # CRITICAL: Save tokens immediately and atomically
        # FreshBooks refresh tokens are single-use!
        new_access = token_data.get('access_token')
        new_refresh = token_data.get('refresh_token')
        expires_in = token_data.get('expires_in', 43200)
        
        if not new_access or not new_refresh:
            raise ValueError("Invalid token response - missing access or refresh token")
        
        # Atomic save to prevent token loss
        self.atomic_save_tokens(new_access, new_refresh, expires_in)
        
        return token_data
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict:
        """
        Make an HTTP request to the FreshBooks API
        
        Args:
            method: HTTP method (GET, POST, PUT, etc.)
            endpoint: API endpoint path
            data: Request body data
            params: Query parameters
            
        Returns:
            Response JSON data
            
        Raises:
            requests.exceptions.RequestException: If request fails
        """
        url = f"{self.base_url}{endpoint}"
        
        # Check if token needs refresh before making request
        if self.is_token_expired():
            print("Access token expired or expiring soon, refreshing...")
            try:
                self.refresh_access_token()
            except Exception as e:
                print(f"Token refresh failed: {e}")
                # Continue with existing token, might still work
        
        # Make the request
        response = requests.request(
            method=method,
            url=url,
            headers=self.headers,
            json=data,
            params=params
        )
        
        # If we get a 401, try refreshing the token
        if response.status_code == 401:
            try:
                print("Got 401 Unauthorized, attempting token refresh...")
                self.refresh_access_token()
                
                # Retry the request with new token
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    json=data,
                    params=params
                )
                
            except ValueError as e:
                print(f"Token refresh failed: {e}")
                raise
            except Exception as e:
                print(f"Unexpected error during token refresh: {e}")
                raise
        
        response.raise_for_status()
        return response.json()
    
    def get_invoices(self, status: Optional[List[str]] = None) -> Dict:
        """
        Get list of invoices with optional status filter
        
        Args:
            status: List of invoice statuses to filter by (e.g., ['draft', 'sent', 'paid'])
                   If None, returns all invoices
        
        Returns:
            Dictionary containing invoice data
        """
        endpoint = f"/search/account/{self.account_id}/invoices_current"
        
        params = {}
        if status:
            # Add status parameters as array
            for s in status:
                params[f"status[]"] = s
        
        return self._make_request("GET", endpoint, params=params)
    
    def get_invoice(self, invoice_id: str) -> Dict:
        """
        Get detailed information about a specific invoice
        
        Args:
            invoice_id: The ID of the invoice to retrieve
            
        Returns:
            Dictionary containing detailed invoice data including line items
        """
        endpoint = f"/accounting/account/{self.account_id}/invoices/invoices/{invoice_id}"
        params = {"include[]": "lines"}
        
        return self._make_request("GET", endpoint, params=params)
    
    def create_invoice(self, client_email: str, items: List[Dict]) -> Dict:
        """
        Create a new invoice for a client
        
        Args:
            client_email: Email address of the client
            items: List of invoice line items, each containing:
                   - name: Item description
                   - qty: Quantity (as string)
                   - unit_cost: Dict with 'amount' (string) and 'code' (e.g., 'USD')
                   
        Returns:
            Dictionary containing the created invoice data
            
        Example:
            items = [
                {
                    "name": "Consulting Services",
                    "qty": "1",
                    "unit_cost": {
                        "amount": "500.00",
                        "code": "USD"
                    }
                }
            ]
        """
        # First, get the client ID from email
        client_data = self.get_client_by_email(client_email)
        
        if not client_data.get("response", {}).get("result", {}).get("clients"):
            raise ValueError(f"No client found with email: {client_email}")
        
        clients = client_data["response"]["result"]["clients"]
        if len(clients) > 1:
            raise ValueError(f"Multiple clients found with email: {client_email}")
        
        client_id = clients[0]["id"]
        
        # Create the invoice
        endpoint = f"/accounting/account/{self.account_id}/invoices/invoices"
        
        invoice_data = {
            "invoice": {
                "customerid": client_id,
                "create_date": datetime.now().strftime("%Y-%m-%d"),
                "due_offset_days": 30,
                "currency_code": "USD",
                "language": "en",
                "lines": items,
                "send_now": False
            }
        }
        
        return self._make_request("POST", endpoint, data=invoice_data)
    
    def send_invoice(self, invoice_id: str, humanApproved: bool = False) -> Dict:
        """
        Send an invoice to the client via email
        
        WARNING: This sends the invoice immediately. Requires explicit 
        human approval via humanApproved=True parameter.
        
        Args:
            invoice_id: The ID of the invoice to send
            humanApproved: Must be explicitly set to True after getting human approval
            
        Returns:
            Dictionary containing the response data
            
        Raises:
            ValueError: If humanApproved is not True
        """
        if not humanApproved:
            raise ValueError(
                "SAFETY CHECK: Invoice cannot be sent without explicit human approval. "
                "Set humanApproved=True only after receiving explicit permission from the user. "
                "Example: client.send_invoice(invoice_id, humanApproved=True)"
            )
            
        endpoint = f"/accounting/account/{self.account_id}/invoices/invoices/{invoice_id}"
        
        data = {
            "invoice": {
                "action_email": True
            }
        }
        
        return self._make_request("PUT", endpoint, data=data)
    
    def delete_invoice(self, invoice_id: str) -> Dict:
        """
        Delete/void an invoice by setting its visibility state to deleted
        
        Args:
            invoice_id: The ID of the invoice to delete
            
        Returns:
            Dictionary containing the response data
        """
        endpoint = f"/accounting/account/{self.account_id}/invoices/invoices/{invoice_id}"
        
        data = {
            "invoice": {
                "vis_state": 1  # 1 = deleted
            }
        }
        
        return self._make_request("PUT", endpoint, data=data)
    
    def get_clients(self, per_page: int = 100) -> Dict:
        """
        Get list of all clients
        
        Args:
            per_page: Number of clients to return per page (default 100)
            
        Returns:
            Dictionary containing client data
        """
        endpoint = f"/accounting/account/{self.account_id}/users/clients"
        params = {"per_page": per_page}
        
        return self._make_request("GET", endpoint, params=params)
    
    def get_client_by_email(self, email: str) -> Dict:
        """
        Get client information by email address
        
        Args:
            email: Client's email address
            
        Returns:
            Dictionary containing client data
        """
        endpoint = f"/accounting/account/{self.account_id}/users/clients"
        params = {"search[email]": email}
        
        return self._make_request("GET", endpoint, params=params)
    
    def get_client(self, organization: Optional[str] = None, email: Optional[str] = None) -> Dict:
        """
        Get client information by organization name or email
        
        Args:
            organization: Organization name to filter by
            email: Email address to filter by
            
        Returns:
            Dictionary containing filtered client data
            
        Raises:
            ValueError: If neither organization nor email is provided
        """
        if not organization and not email:
            raise ValueError("Either organization or email must be provided")
        
        if email:
            return self.get_client_by_email(email)
        
        # Get all clients and filter by organization
        all_clients = self.get_clients()
        clients = all_clients.get("response", {}).get("result", {}).get("clients", [])
        
        filtered_clients = [
            client for client in clients
            if client.get("organization") == organization
        ]
        
        return {
            "response": {
                "result": {
                    "clients": filtered_clients
                }
            }
        }
    
    def create_client(self, email: str, first_name: str, last_name: str, organization: str) -> Dict:
        """
        Create a new client
        
        Args:
            email: Client's email address
            first_name: Client's first name
            last_name: Client's last name
            organization: Client's organization/company name
            
        Returns:
            Dictionary containing the created client data
        """
        endpoint = f"/accounting/account/{self.account_id}/users/clients"
        
        client_data = {
            "client": {
                "email": email,
                "fname": first_name,
                "lname": last_name,
                "organization": organization
            }
        }
        
        return self._make_request("POST", endpoint, data=client_data)
    
    def update_client(self, client_id: str, **kwargs) -> Dict:
        """
        Update an existing client's information
        
        Args:
            client_id: The ID of the client to update
            **kwargs: Client fields to update (organization, fname, lname, email, street, street2, city, province, country, postal_code)
            
        Returns:
            Dictionary containing the updated client data
        """
        endpoint = f"/accounting/account/{self.account_id}/users/clients/{client_id}"
        
        client_data = {
            "client": kwargs
        }
        
        return self._make_request("PUT", endpoint, data=client_data)
    
    @staticmethod
    def exchange_code_for_tokens(auth_code: str):
        """
        Exchange authorization code for new tokens (static method for initial auth)
        
        Args:
            auth_code: Authorization code from OAuth callback
        """
        load_dotenv(override=True)
        
        client_id = os.getenv('FRESHBOOKS_CLIENT_ID')
        client_secret = os.getenv('FRESHBOOKS_CLIENT_SECRET')
        redirect_uri = os.getenv('FRESHBOOKS_REDIRECT_URI')
        token_url = 'https://api.freshbooks.com/auth/oauth/token'
        
        data = {
            'grant_type': 'authorization_code',
            'code': auth_code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri
        }
        
        response = requests.post(token_url, data=data)
        response.raise_for_status()
        
        token_data = response.json()
        
        # Save tokens atomically
        access_token = token_data.get('access_token')
        refresh_token = token_data.get('refresh_token')
        expires_in = token_data.get('expires_in', 43200)
        expires_at = datetime.now().timestamp() + expires_in
        
        set_key('.env', 'FRESHBOOKS_ACCESS_TOKEN', access_token)
        set_key('.env', 'FRESHBOOKS_REFRESH_TOKEN', refresh_token)
        set_key('.env', 'FRESHBOOKS_TOKEN_EXPIRES_AT', str(expires_at))
        
        print(f"✓ Tokens successfully saved!")
        print(f"  Access token: {access_token[:50]}...")
        print(f"  Refresh token: {refresh_token[:20]}...")
        print(f"  Expires in: {expires_in} seconds")
        
        return token_data


# Convenience functions for backward compatibility
def create_freshbooks_client(account_id: str = None, access_token: str = None) -> FreshBooksClient:
    """
    Create a FreshBooks client instance
    
    Args:
        account_id: FreshBooks account ID (defaults to env var FRESHBOOKS_ACCOUNT_ID)
        access_token: OAuth2 access token (defaults to env var FRESHBOOKS_ACCESS_TOKEN)
        
    Returns:
        Configured FreshBooksClient instance
    """
    return FreshBooksClient(account_id, access_token)


# Standalone functions that create a client internally
def get_invoice(invoice_id: str, account_id: str = None, access_token: str = None) -> Dict:
    """Get invoice details"""
    client = create_freshbooks_client(account_id, access_token)
    return client.get_invoice(invoice_id)


def get_client(organization: str = None, email: str = None, account_id: str = None, access_token: str = None) -> Dict:
    """Get client information"""
    client = create_freshbooks_client(account_id, access_token)
    return client.get_client(organization, email)


def create_invoice(client_email: str, items: List[Dict], account_id: str = None, access_token: str = None) -> Dict:
    """Create a new invoice"""
    client = create_freshbooks_client(account_id, access_token)
    return client.create_invoice(client_email, items)


def create_client(email: str, first_name: str, last_name: str, organization: str, 
                  account_id: str = None, access_token: str = None) -> Dict:
    """Create a new client"""
    client = create_freshbooks_client(account_id, access_token)
    return client.create_client(email, first_name, last_name, organization)


def send_invoice(invoice_id: str, humanApproved: bool = False, account_id: str = None, access_token: str = None) -> Dict:
    """
    Send an invoice via email
    
    Args:
        invoice_id: The ID of the invoice to send
        humanApproved: Must be explicitly set to True after getting human approval
        account_id: Optional account ID override
        access_token: Optional access token override
        
    Returns:
        Dictionary containing the response data
        
    Raises:
        ValueError: If humanApproved is not True
    """
    client = create_freshbooks_client(account_id, access_token)
    return client.send_invoice(invoice_id, humanApproved=humanApproved)


def delete_invoice(invoice_id: str, account_id: str = None, access_token: str = None) -> Dict:
    """Delete/void an invoice"""
    client = create_freshbooks_client(account_id, access_token)
    return client.delete_invoice(invoice_id)


if __name__ == "__main__":
    # Handle command-line auth code exchange
    import sys
    
    if len(sys.argv) > 1:
        auth_code = sys.argv[1]
        try:
            FreshBooksClient.exchange_code_for_tokens(auth_code)
        except Exception as e:
            print(f"ERROR: {e}")
            sys.exit(1)
    else:
        print("FreshBooks API Module")
        print("=====================")
        print()
        print("To exchange an authorization code for tokens:")
        print("  python freshbooks.py AUTH_CODE")
        print()
        print("To get an authorization code:")
        print("1. Visit the FreshBooks OAuth URL")
        print("2. Authorize the application")  
        print("3. Copy the code from the redirect URL")
        print()
        print("Usage example:")
        print()
        print("from freshbooks import create_freshbooks_client")
        print()
        print("client = create_freshbooks_client()")
        print()
        print("# Create an invoice")
        print("items = [")
        print("    {")
        print("        'name': 'Consulting Services',")
        print("        'qty': '1',")
        print("        'unit_cost': {'amount': '500.00', 'code': 'USD'}")
        print("    }")
        print("]")
        print("invoice = client.create_invoice('client@example.com', items)")
        print()
        print("# Send the invoice")
        print("client.send_invoice(invoice['response']['result']['invoice']['id'])")