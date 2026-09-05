import json

import httpx

from forge_astra.config import Settings
from forge_astra.http import JsonHTTP
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
