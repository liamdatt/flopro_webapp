import os
import requests
from requests import HTTPError
from typing import Dict, List, Optional, Any


class N8nClient:
    """Client for interacting with n8n API"""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base = (base_url or os.environ.get("N8N_API_BASE_URL", "")).rstrip("/")
        # Use public API prefix per docs; allow override (e.g., to 'rest')
        api_prefix = os.environ.get("N8N_API_PREFIX", "/api/v1").strip()
        if not api_prefix.startswith("/"):
            api_prefix = f"/{api_prefix}"
        self.api_prefix = api_prefix.rstrip("/")
        key = (api_key or os.environ.get("N8N_API_KEY", "")).strip()

        if not self.base:
            raise RuntimeError("N8N_API_BASE_URL is not set")
        if not key:
            raise RuntimeError("N8N_API_KEY is not set")

        # Send both n8n header and Authorization bearer to satisfy some proxies
        self.headers = {
            "X-N8N-API-KEY": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make an HTTP request to n8n API"""
        # endpoint should start with '/'
        url = f"{self.base}{self.api_prefix}{endpoint}"
        response = requests.request(method, url, headers=self.headers, **kwargs)
        try:
            response.raise_for_status()
        except HTTPError as exc:
            # Include response body for easier diagnosis (but not headers)
            msg = f"{exc} | url={url} | status={response.status_code} | body={response.text[:500]}"
            raise HTTPError(msg, response=response) from exc
        # Some endpoints may return no JSON
        if not response.content:
            return {}
        return response.json()

    def get_workflow(self, workflow_id: int) -> Dict[str, Any]:
        """Get workflow details from n8n"""
        return self._make_request("GET", f"/workflows/{workflow_id}")

    def create_workflow(self, workflow_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new workflow in n8n"""
        return self._make_request("POST", "/workflows", json=workflow_data)

    def update_workflow(self, workflow_id: int, workflow_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing workflow in n8n"""
        return self._make_request("PATCH", f"/workflows/{workflow_id}", json=workflow_data)

    def delete_workflow(self, workflow_id: int) -> None:
        """Delete a workflow from n8n"""
        self._make_request("DELETE", f"/workflows/{workflow_id}")

    def activate_workflow(self, workflow_id: int) -> Dict[str, Any]:
        """Activate a workflow in n8n"""
        return self._make_request("POST", f"/workflows/{workflow_id}/activate")

    def deactivate_workflow(self, workflow_id: int) -> Dict[str, Any]:
        """Deactivate a workflow in n8n"""
        return self._make_request("POST", f"/workflows/{workflow_id}/deactivate")

    def create_credential(self, name: str, cred_type: str, data: Dict[str, Any], node_types: List[str]) -> Dict[str, Any]:
        """Create a new credential in n8n"""
        payload = {
            "name": name,
            "type": cred_type,
            "data": data,
            "nodesAccess": [{"nodeType": node_type} for node_type in node_types],
        }
        return self._make_request("POST", "/credentials", json=payload)

    def update_credential(self, credential_id: int, name: str, cred_type: str, data: Dict[str, Any], node_types: List[str]) -> Dict[str, Any]:
        """Update an existing credential in n8n"""
        payload = {
            "name": name,
            "type": cred_type,
            "data": data,
            "nodesAccess": [{"nodeType": node_type} for node_type in node_types],
        }
        return self._make_request("PATCH", f"/credentials/{credential_id}", json=payload)

    def delete_credential(self, credential_id: int) -> None:
        """Delete a credential from n8n"""
        self._make_request("DELETE", f"/credentials/{credential_id}")

    def get_credential(self, credential_id: int) -> Dict[str, Any]:
        """Get credential details from n8n"""
        return self._make_request("GET", f"/credentials/{credential_id}")

    def execute_workflow(self, workflow_id: int, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a workflow in n8n"""
        payload = {"data": data} if data else {}
        return self._make_request("POST", f"/workflows/{workflow_id}/execute", json=payload)

    def build_oauth_authorize_url(self, credential_id: int, return_url: str) -> str:
        """Get provider OAuth URL for a credential via n8n.

        This endpoint is normally hit by the n8n editor which includes the
        session cookie.  When calling it programmatically we need to supply the
        API key and capture the `Location` header of the redirect to the OAuth
        provider.  The returned URL can then be used to redirect the end user.

        Args:
            credential_id: ID of the credential in n8n
            return_url: Absolute URL n8n should redirect to after auth
        """
        # Construct endpoint respecting any configured API prefix
        url = f"{self.base}{self.api_prefix}/oauth2-credential/auth"
        params = {
            "id": credential_id,
            "redirectAfterAuth": return_url,
        }
        # Request without following redirects so we can extract provider URL
        response = requests.get(
            url, headers=self.headers, params=params, allow_redirects=False
        )
        if response.status_code not in (200, 302) or "location" not in response.headers:
            msg = f"Failed to initiate OAuth: status={response.status_code} body={response.text[:200]}"
            raise HTTPError(msg, response=response)
        # n8n responds with a 302 redirect to the provider
        return response.headers["location"]
