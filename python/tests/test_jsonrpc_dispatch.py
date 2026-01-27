"""Tests for JSON-RPC 2.0 dispatch method."""

import json
import pytest
from crystalmath.api import CrystalController, JSONRPC_METHOD_NOT_FOUND, JSONRPC_PARSE_ERROR


@pytest.fixture
def controller():
    """Create a controller in demo mode for testing."""
    return CrystalController(use_aiida=False, db_path=None)


class TestJsonRpcDispatch:
    """Test the JSON-RPC 2.0 dispatch method."""

    def test_dispatch_fetch_jobs(self, controller):
        """Test dispatch routes fetch_jobs correctly."""
        request = json.dumps({
            "jsonrpc": "2.0",
            "method": "fetch_jobs",
            "params": {"limit": 10},
            "id": 1,
        })

        response_str = controller.dispatch(request)
        response = json.loads(response_str)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "result" in response
        assert "error" not in response
        # Result should be the parsed JSON from get_jobs_json
        assert isinstance(response["result"], list)

    def test_dispatch_method_not_found(self, controller):
        """Test dispatch returns error for unknown method."""
        request = json.dumps({
            "jsonrpc": "2.0",
            "method": "unknown_method",
            "params": {},
            "id": 2,
        })

        response_str = controller.dispatch(request)
        response = json.loads(response_str)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 2
        assert "error" in response
        assert response["error"]["code"] == JSONRPC_METHOD_NOT_FOUND
        assert "unknown_method" in response["error"]["message"]

    def test_dispatch_parse_error(self, controller):
        """Test dispatch handles malformed JSON."""
        response_str = controller.dispatch("not valid json {")
        response = json.loads(response_str)

        assert response["jsonrpc"] == "2.0"
        assert "error" in response
        assert response["error"]["code"] == JSONRPC_PARSE_ERROR

    def test_dispatch_missing_jsonrpc_version(self, controller):
        """Test dispatch validates jsonrpc version field."""
        request = json.dumps({
            "method": "fetch_jobs",
            "params": {},
            "id": 3,
        })

        response_str = controller.dispatch(request)
        response = json.loads(response_str)

        assert "error" in response
        assert "jsonrpc" in response["error"]["message"].lower()

    def test_dispatch_with_positional_params(self, controller):
        """Test dispatch handles positional parameters."""
        request = json.dumps({
            "jsonrpc": "2.0",
            "method": "fetch_jobs",
            "params": [5],  # limit=5 as positional
            "id": 4,
        })

        response_str = controller.dispatch(request)
        response = json.loads(response_str)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 4
        assert "result" in response

    def test_dispatch_check_workflows_available(self, controller):
        """Test dispatch routes check_workflows_available."""
        request = json.dumps({
            "jsonrpc": "2.0",
            "method": "check_workflows_available",
            "params": {},
            "id": 5,
        })

        response_str = controller.dispatch(request)
        response = json.loads(response_str)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 5
        assert "result" in response
        # Result should have workflow availability info
        result = response["result"]
        assert "available" in result or "ok" in result

    def test_dispatch_list_templates(self, controller):
        """Test dispatch routes list_templates."""
        request = json.dumps({
            "jsonrpc": "2.0",
            "method": "list_templates",
            "params": {},
            "id": 6,
        })

        response_str = controller.dispatch(request)
        response = json.loads(response_str)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 6
        assert "result" in response

    def test_registry_security(self, controller):
        """Test that only registered methods can be called."""
        # Private method should not be callable
        request = json.dumps({
            "jsonrpc": "2.0",
            "method": "_init_aiida",  # Private method
            "params": {"profile_name": "test"},
            "id": 7,
        })

        response_str = controller.dispatch(request)
        response = json.loads(response_str)

        assert "error" in response
        assert response["error"]["code"] == JSONRPC_METHOD_NOT_FOUND

    def test_dispatch_null_id_notification(self, controller):
        """Test dispatch handles null id (notification style)."""
        request = json.dumps({
            "jsonrpc": "2.0",
            "method": "fetch_jobs",
            "params": {},
            "id": None,
        })

        response_str = controller.dispatch(request)
        response = json.loads(response_str)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] is None
        assert "result" in response
