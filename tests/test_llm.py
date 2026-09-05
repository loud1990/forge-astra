import json

import httpx
import pytest

from forge_astra.config import Settings
from forge_astra.http import JsonHTTP, RemoteError
from forge_astra.llm import ChatClient
from forge_astra.models import Plan
from forge_astra.observability import Telemetry


def test_generic_endpoint_no_native_json_or_tools_required():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        text = "not json" if len(requests) == 1 else '{"clauses":[],"mechanics":[]}'
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": text}}]}
        )

    settings = Settings(
        _env_file=None,
        llm_model="local-model",
        llm_base_url="http://example.test/custom/v1",
        langfuse_enabled=False,
    )
    http = JsonHTTP(settings.llm_base_url, transport=httpx.MockTransport(handler))
    client = ChatClient(settings, Telemetry(settings), http)
    assert client.ask("plan", {}, Plan).clauses == []
    assert len(requests) == 2
    assert "response_format" not in requests[0]
    assert "tools" not in requests[0]
    assert requests[0]["model"] == "local-model"
    assert client.url == "http://example.test/custom/v1/chat/completions"
    http.close()


def test_ambiguous_post_timeout_is_not_automatically_duplicated():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("still generating")

    http = JsonHTTP("http://example.test", transport=httpx.MockTransport(handler))
    with pytest.raises(RemoteError, match="ReadTimeout"):
        http.request("POST", "/chat/completions", json={})
    assert len(calls) == 1
    http.close()


def test_full_endpoint_preserves_gateway_query_parameters():
    settings = Settings(
        _env_file=None,
        llm_model="deployment",
        llm_base_url="https://example.test/deployments/name/chat/completions?api-version=test",
        langfuse_enabled=False,
    )
    client = ChatClient(settings, Telemetry(settings))
    assert client.url == settings.llm_base_url
    client.http.close()
