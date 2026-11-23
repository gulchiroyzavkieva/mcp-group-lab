"""MCP bridge for sales API and monitoring API."""

import logging
import os

import httpx
from mcp.server import MCPServer

MONGO_API = os.getenv("MONGO_API", "http://127.0.0.1:5001").rstrip("/")
REDIS_API = os.getenv("REDIS_API", "http://127.0.0.1:5002").rstrip("/")

logger = logging.getLogger(__name__)
mcp = MCPServer("Online Retail MCP Server")


def record_event(event: str) -> None:
    """Best-effort monitoring; monitoring failure must not hide retail data."""
    try:
        with httpx.Client(timeout=3.0) as client:
            response = client.post(
                REDIS_API + "/monitor/event", json={"event": event}
            )
            response.raise_for_status()
    except httpx.HTTPError:
        logger.warning("Could not record monitoring event: %s", event)


def call_flask(base_url: str, endpoint: str, params: dict) -> dict:
    """Call a fixed Flask endpoint and require a JSON object response."""
    with httpx.Client(timeout=10.0) as client:
        response = client.get(base_url + endpoint, params=params)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("The service did not return a JSON object")
        return data


def monitored_call(event: str, base_url: str, endpoint: str, params: dict) -> dict:
    record_event(event)
    try:
        return call_flask(base_url, endpoint, params)
    except httpx.TimeoutException as exc:
        record_event("request_failed")
        raise RuntimeError("The Flask service timed out. Check its terminal.") from exc
    except httpx.HTTPStatusError as exc:
        record_event("request_failed")
        raise RuntimeError(
            f"The Flask service returned HTTP {exc.response.status_code}. "
            "Check its terminal."
        ) from exc
    except httpx.RequestError as exc:
        record_event("request_failed")
        raise RuntimeError(
            "Cannot reach the Flask service. Check its URL and whether it is running."
        ) from exc
    except ValueError as exc:
        record_event("request_failed")
        raise RuntimeError("The Flask service returned an invalid JSON response.") from exc


@mcp.tool()
def search_sales(country: str = "", limit: int = 10) -> dict:

    """Retrieve a limited sample of historical UCI Online Retail transaction rows."""

    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    return monitored_call(
        "mongodb_request", MONGO_API, "/sales",
        {"country": country.strip(), "limit": limit},
    )


@mcp.tool()
def get_statistics() -> dict:

    """Retrieve application monitoring statistics from Redis. """
    
    return monitored_call("redis_request", REDIS_API, "/statistics", {})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8000)
