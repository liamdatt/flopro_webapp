import os
import requests
from typing import Dict, List, Optional, Any


class N8nClient:
    """Client for interacting with n8n API"""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base = (base_url or os.environ.get("N8N_API_BASE_URL", "")).rstrip("/")
        self.headers = {
            "X-N8N-API-KEY": api_key or os.environ.get("N8N_API_KEY", ""),
            "Content-Type": "application/json",
        }

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make an HTTP request to n8n API"""
        url = f"{self.base}/rest{endpoint}"
        response = requests.request(method, url, headers=self.headers, **kwargs)
        response.raise_for_status()
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
