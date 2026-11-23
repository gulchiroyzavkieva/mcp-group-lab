"""Discover and call the real MCP tools without Ollama."""

import asyncio
import json
import os
import sys

from mcp import Client

SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")


async def main() -> bool:
    passed = True
    async with Client(SERVER_URL) as client:
        discovered = await client.list_tools()
        names = {tool.name for tool in discovered.tools}
        print("Available MCP tools:")
        for tool in discovered.tools:
            print("\nName:", tool.name)
            print("Description:", tool.description)
            schema = getattr(tool, "input_schema", None)
            if schema is None:
                schema = getattr(tool, "inputSchema", None)
            print("Arguments:", json.dumps(schema, indent=2))

        required = {"search_sales", "get_statistics"}
        if not required.issubset(names):
            print("Missing tools:", sorted(required - names))
            return False

        for name, arguments in [
            ("search_sales", {"country": "United Kingdom", "limit": 5}),
            ("get_statistics", {}),
        ]:
            print(f"\nCalling {name}: {arguments}")
            try:
                result = await client.call_tool(name, arguments)
                error = getattr(result, "is_error", None)
                if error is None:
                    error = getattr(result, "isError", False)
                print("Tool error:", bool(error))
                passed = passed and not error
                for block in result.content:
                    print(getattr(block, "text", str(block)))
            except Exception as exc:
                passed = False
                print("Call failed:", exc)
    return passed


if __name__ == "__main__":
    success = asyncio.run(main())
    print("\nBoth tool calls passed." if success else "\nA check failed; review the output.")
    sys.exit(0 if success else 1)
