import json
from uuid import uuid4

import httpx
import langfuse
from langgraph.graph import END, START, StateGraph
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from forge_astra.config import Settings
from forge_astra.http import JsonHTTP
from forge_astra.llm import ChatClient
from forge_astra.models import Plan
from forge_astra.observability import Telemetry


def test_real_langfuse_and_langgraph_emit_connected_model_spans(monkeypatch):
    # Exercise the installed SDK and callback. Only the network exporter is replaced.
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    monkeypatch.setattr("langfuse._client.span_processor.OTLPSpanExporter", lambda **_: exporter)
    monkeypatch.setenv("LANGFUSE_MEDIA_UPLOAD_ENABLED", "false")
    original = langfuse.Langfuse
    monkeypatch.setattr(
        langfuse, "Langfuse", lambda **kwargs: original(**kwargs, tracer_provider=provider)
    )
    settings = Settings(
        _env_file=None,
        llm_model="trace-test-model",
        llm_api_key="do-not-trace-this-key",
        langfuse_public_key="test-" + uuid4().hex,
        langfuse_secret_key="do-not-trace-this-secret",
        langfuse_base_url="https://tracing.example.test",
    )
    telemetry = Telemetry(settings)
    http = JsonHTTP(
        "https://model.example.test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": '{"clauses":[],"mechanics":[]}'},
                        }
                    ],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
                },
            )
        ),
    )
    client = ChatClient(settings, telemetry, http)
    graph = StateGraph(dict)
    graph.add_node("planning", lambda state: client.ask("Plan this card", state, Plan).model_dump())
    graph.add_edge(START, "planning")
    graph.add_edge("planning", END)
    try:
        with telemetry.span("forge-astra.card", input={"card": "Trace Trial"}):
            result = graph.compile().invoke(
                {"name": "Trace Trial"},
                config={
                    "callbacks": telemetry.callbacks(),
                    "metadata": {
                        "langfuse_session_id": "trace-test-run",
                        "langfuse_tags": ["forge-astra", "tst"],
                    },
                },
            )
        telemetry.flush()
        assert result == {"clauses": [], "mechanics": []}
        spans = exporter.get_finished_spans()
        assert {"forge-astra.card", "LangGraph", "planning", "Plan"} <= {
            span.name for span in spans
        }
        assert len({span.context.trace_id for span in spans}) == 1
        root = next(span for span in spans if span.name == "forge-astra.card")
        assert root.parent is None
        ids = {span.context.span_id for span in spans}
        assert all(span.parent.span_id in ids for span in spans if span is not root)
        generation = next(span for span in spans if span.name == "Plan")
        attributes = dict(generation.attributes)
        assert attributes["langfuse.observation.type"] == "generation"
        assert attributes["langfuse.observation.model.name"] == "trace-test-model"
        assert json.loads(attributes["langfuse.observation.usage_details"])["total"] == 20
        serialized = json.dumps([dict(span.attributes) for span in spans])
        assert "trace-test-run" in serialized and "tst" in serialized
        assert settings.llm_api_key.get_secret_value() not in serialized
        assert settings.langfuse_secret_key.get_secret_value() not in serialized
    finally:
        http.close()
        telemetry.client.shutdown()
        provider.shutdown()
