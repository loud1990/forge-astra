from contextlib import nullcontext

from forge_astra.config import Settings


class Telemetry:
    def __init__(self, settings: Settings):
        self.client = None
        self.public_key = settings.langfuse_public_key
        secret = settings.langfuse_secret_key.get_secret_value()
        if not settings.langfuse_enabled:
            return
        if bool(self.public_key) != bool(secret):
            raise ValueError("Set both LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY")
        if self.public_key:
            from langfuse import Langfuse

            self.client = Langfuse(
                public_key=self.public_key, secret_key=secret, base_url=settings.langfuse_base_url
            )

    def callbacks(self) -> list:
        if not self.client:
            return []
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler(public_key=self.public_key)]

    def span(self, name: str, **kwargs):
        if not self.client:
            return nullcontext(None)
        return self.client.start_as_current_observation(name=name, **kwargs)

    def flush(self):
        if self.client:
            self.client.flush()
