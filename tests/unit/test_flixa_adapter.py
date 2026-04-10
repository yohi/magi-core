import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from magi.core.providers import ProviderContext
from magi.llm.providers import FlixaAdapter
from magi.llm.client import LLMRequest, LLMResponse

@pytest.mark.asyncio
async def test_flixa_adapter_url_construction():
    """Verify FlixaAdapter correctly constructs the full chat URL as '.../v1/agent/responses' using default parameters."""
    context = ProviderContext(
        provider_id="flixa",
        api_key="test-key",
        model="gpt-4o"
    )
    
    mock_client = AsyncMock()
    # Mock post to return a valid response
    mock_response = MagicMock()
    mock_response.json.return_value = {"output_text": "hello"}
    mock_response.status_code = 200
    mock_client.post.return_value = mock_response
    
    adapter = FlixaAdapter(context, http_client=mock_client)
    
    request = LLMRequest(system_prompt="sys", user_prompt="user")
    await adapter.send(request)
    
    # Verify the URL used in post
    args, kwargs = mock_client.post.call_args
    assert args[0] == "https://api.flixa.engineer/v1/agent/responses"

@pytest.mark.asyncio
async def test_flixa_adapter_header_cleanup():
    """Verify FlixaAdapter.send removes all non-Bearer auth headers even if present in the provider context."""
    # ProviderContext can have options that might leak into headers if not careful
    context = ProviderContext(
        provider_id="flixa",
        api_key="test-key",
        model="gpt-4o",
        options={"headers": {
            "x-api-key": "leaked-key",
            "X-API-KEY": "capitalized-key",
            "api-key": "another-key",
            "Authorization": "Basic wrong-format"
        }}
    )
    
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.json.return_value = {"output_text": "hello"}
    mock_response.status_code = 200
    mock_client.post.return_value = mock_response
    
    adapter = FlixaAdapter(context, http_client=mock_client)
    
    request = LLMRequest(system_prompt="sys", user_prompt="user")
    await adapter.send(request)
    
    args, kwargs = mock_client.post.call_args
    headers = kwargs.get("headers", {})
    
    # Check that problematic headers are removed
    assert "x-api-key" not in headers
    assert "X-API-KEY" not in headers
    assert "api-key" not in headers
    
    # Check that Authorization is corrected
    assert headers.get("Authorization") == "Bearer test-key"

@pytest.mark.asyncio
async def test_flixa_adapter_health_url():
    """Verify FlixaAdapter.health correctly reaches the models endpoint regardless of trailing slashes in the base endpoint."""
    test_cases = [
        ("https://api.flixa.engineer/v1/agent", "https://api.flixa.engineer/v1/models"),
        ("https://api.flixa.engineer/v1/agent/", "https://api.flixa.engineer/v1/models"),
        ("https://custom.flixa.app/v1/agent", "https://custom.flixa.app/v1/models"),
    ]
    
    for endpoint, expected_health_url in test_cases:
        context = ProviderContext(
            provider_id="flixa",
            api_key="test-key",
            model="gpt-4o",
            endpoint=endpoint
        )
        
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_response.status_code = 200
        mock_client.get.return_value = mock_response
        
        adapter = FlixaAdapter(context, http_client=mock_client)
        await adapter.health()
        
        args, kwargs = mock_client.get.call_args
        assert args[0] == expected_health_url
        
        headers = kwargs.get("headers", {})
        assert "x-api-key" not in headers
        assert headers.get("Authorization") == "Bearer test-key"

@patch("httpx.get")
def test_model_fetcher_flixa_bearer_token(mock_get):
    """Verify the model fetcher correctly attaches the Bearer token for Flixa requests."""
    from magi.cli.model_fetcher import fetch_available_models
    
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": [{"id": "model-1"}]}
    mock_response.status_code = 200
    mock_get.return_value = mock_response
    
    # This will now pass as flixa is handled in model_fetcher
    models = fetch_available_models("flixa", "test-key")
    
    assert models == ["model-1"]
    args, kwargs = mock_get.call_args
    headers = kwargs.get("headers", {})
    assert headers.get("Authorization") == "Bearer test-key"
    assert args[0] == "https://api.flixa.engineer/v1/models"

@pytest.mark.asyncio
async def test_flixa_health_exception_filtering():
    """Verify FlixaAdapter.health only catches RequestError and ValueError."""
    context = ProviderContext(
        provider_id="flixa",
        api_key="test-key",
        model="gpt-4o"
    )
    
    mock_client = AsyncMock()
    adapter = FlixaAdapter(context, http_client=mock_client)
    
    # 1. Catchable exception (httpx.RequestError)
    import httpx
    mock_client.get.side_effect = httpx.RequestError("Network error")
    health = await adapter.health()
    assert health.ok is False
    assert "Network error" in health.details["error"]
    
    # 2. Catchable exception (ValueError, e.g. JSON decode error)
    mock_client.get.side_effect = None
    mock_response = MagicMock()
    mock_response.json.side_effect = ValueError("Invalid JSON")
    mock_response.status_code = 200
    mock_client.get.return_value = mock_response
    health = await adapter.health()
    assert health.ok is False
    assert "Invalid JSON" in health.details["error"]
    
    # 3. Non-catchable exception (RuntimeError) should be raised
    mock_client.get.side_effect = RuntimeError("Something very bad")
    with pytest.raises(RuntimeError):
        await adapter.health()
