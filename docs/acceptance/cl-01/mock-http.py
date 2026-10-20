"""Isolated container fixture: all outbound HTTP is mocked, never a paid call."""

import os
import sys

import httpx


def respond(request):
    if request.url.path.endswith("/key"):
        if os.environ.get("CL01_FAIL_BUDGET") == "1":
            return httpx.Response(503, json={"error": "isolated budget observation failure"})
        return httpx.Response(
            200,
            json={
                "data": {
                    "usage": 0,
                    "usage_monthly": 0,
                    "limit": 15,
                    "limit_reset": "monthly",
                }
            },
        )
    if request.url.host == "cl01.example" and request.url.path == "/feed":
        return httpx.Response(
            200,
            text=(
                '<?xml version="1.0"?><rss version="2.0"><channel>'
                "<title>CL-01 isolated feed</title><item><title>CL-01 mock item</title>"
                "<link>https://cl01.example/item-1</link><guid>cl01-item-1</guid>"
                "<description>Isolated metadata fixture</description></item></channel></rss>"
            ),
        )
    raise AssertionError("Unexpected outbound HTTP in CL-01 isolation")


OriginalClient = httpx.Client


class MockClient(OriginalClient):
    def __init__(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(respond)
        super().__init__(*args, **kwargs)


httpx.Client = MockClient
if os.environ.get("CL01_FAIL_CHECK") == "1" and "--check" in sys.argv:
    os.environ["UNSPUN_OPENROUTER_API_KEY"] = ""
