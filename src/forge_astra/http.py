import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx


class RemoteError(RuntimeError):
    pass


class JsonHTTP:
    """Bounded retries without putting auth headers or response bodies into logs."""

    def __init__(
        self,
        base_url: str,
        headers: dict | None = None,
        interval: float = 0,
        timeout: float = 45,
        transport: httpx.BaseTransport | None = None,
    ):
        self.client = httpx.Client(
            base_url=base_url, headers=headers or {}, timeout=timeout, transport=transport
        )
        self.interval = interval
        self.last_request = 0.0

    def close(self):
        self.client.close()

    def request(self, method: str, path: str, *, empty_404: bool = False, **kwargs):
        for attempt in range(4):
            time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                response = self.client.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                # A timed-out POST may still be generating server-side. Do not
                # multiply an ambiguous request by retrying it automatically.
                if attempt == 3 or method.upper() != "GET":
                    raise RemoteError(f"Network request failed ({type(exc).__name__})") from None
                time.sleep(2**attempt)
                continue
            if response.status_code == 404 and empty_404:
                return None
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                wait = 2**attempt
                retry = response.headers.get("Retry-After", "")
                try:
                    wait = float(retry)
                except ValueError:
                    try:
                        wait = (parsedate_to_datetime(retry) - datetime.now(UTC)).total_seconds()
                    except (ValueError, TypeError):
                        pass
                if wait > 60:
                    raise RemoteError(
                        "Remote service requested a long retry delay; retry next poll"
                    )
                time.sleep(max(0, wait))
                continue
            if response.is_error:
                raise RemoteError(f"Remote service returned HTTP {response.status_code}")
            try:
                return response.json()
            except ValueError:
                raise RemoteError("Remote service returned invalid JSON") from None
        raise RemoteError("Retry limit exceeded")
