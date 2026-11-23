# ollama_client.py
# Big Data: Tools and Techniques - MCP Group Lab
# Part: Ollama + MCP client integration (Guli)
#
# This script connects a local Ollama model to our MCP server.
# The model reads the list of MCP tools, decides which tool to call
# for the user's question, and then answers using the tool result.
#
# How to run (start mongo_api.py, redis_flask.py and mcp_server.py first):
#   python ollama_client.py "Show me 5 sales from Germany."
#   python ollama_client.py "How many questions have been asked so far?" qwen3:14b
# The second argument is optional and chooses the model.
# Ollama only (no MCP tools, for comparison):
#   python ollama_client.py "Show me 5 sales from Germany." qwen3:14b --no-tools

import asyncio
import sys
import time

import httpx
from mcp import Client
from ollama import AsyncClient

SERVER_URL = "http://127.0.0.1:8000/mcp"     # Sharmin's MCP server
REDIS_API = "http://127.0.0.1:5002"          # Tara's monitoring API
MODEL = "qwen3:4b"
MAX_TOOL_ROUNDS = 5   # limit on tool calls per question, to avoid endless loops (DoS)


# MCP and Ollama describe tools in different formats,
# so I convert each MCP tool into the format Ollama expects.
def mcp_tools_to_ollama(mcp_tools):
    ollama_tools = []
    for tool in mcp_tools:
        ollama_tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.input_schema,
            },
        })
    return ollama_tools


# Get the text out of an MCP tool result so the model can read it.
def result_to_text(result):
    return "\n".join(getattr(block, "text", str(block)) for block in result.content)


# Tell Tara's Redis monitoring API that a new user question arrived.
# Sent once per question (not once per tool call), as Tara asked.
# If monitoring is down, the question still gets answered.
async def send_query_submitted():
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.post(
                REDIS_API + "/monitor/event", json={"event": "query_submitted"}
            )
            response.raise_for_status()
    except httpx.HTTPError as e:
        print(f"  (Monitoring warning: could not record query_submitted: {e})")


async def ask(question, model, verbose=True):
    """Answer one question with one model.

    Returns a dictionary with what happened, so compare_models.py can score it:
      tool_calls: list of (tool name, arguments) the model asked for, in order
      answer:     the model's final answer text
      seconds:    time from sending the question to getting the final answer
    """
    ollama = AsyncClient()

    await send_query_submitted()

    async with Client(SERVER_URL) as mcp:
        # 1. Tool discovery: ask the MCP server which tools it has
        tool_list = await mcp.list_tools()
        tools = mcp_tools_to_ollama(tool_list.tools)

        if verbose:
            print("Model:", model)
            print("Tools available:", [t.name for t in tool_list.tools])
            print("Question:", question)
            print()

        messages = [{"role": "user", "content": question}]
        answer = None
        tool_calls = []
        start = time.time()

        for _ in range(MAX_TOOL_ROUNDS):
            # 2. Send the question and the tool list to the model
            response = await ollama.chat(
                model=model,
                messages=messages,
                tools=tools,
                think=False,   # turn off qwen3 "thinking" to keep runs shorter
            )
            message = response.message
            messages.append(message)

            # 3. If the model did not ask for a tool, this is the final answer
            if not message.tool_calls:
                answer = message.content or ""
                # the small qwen3 model sometimes still prints its thinking,
                # so I keep only the text after </think>
                if "</think>" in answer:
                    answer = answer.split("</think>")[-1].strip()
                break

            # 4. Tool invocation: run each tool the model asked for
            for call in message.tool_calls:
                name = call.function.name
                args = dict(call.function.arguments or {})
                tool_calls.append((name, args))
                if verbose:
                    print(f"  Model chose: {name}({args})")

                try:
                    result = await mcp.call_tool(name, args)
                    text = result_to_text(result)
                    if result.is_error:
                        text = "Tool error: " + text
                except Exception as e:
                    text = f"Error calling {name}: {e}"

                if verbose:
                    print("  Tool returned:", text)
                    print()

                # 5. Give the tool result back to the model
                messages.append({"role": "tool", "content": text, "tool_name": name})

        seconds = time.time() - start

        if answer is None:
            answer = f"(No final answer after {MAX_TOOL_ROUNDS} rounds of tool calls.)"

        if verbose:
            print("Answer:", answer)
            print()
            print(f"Time: {seconds:.1f} seconds")

        return {"tool_calls": tool_calls, "answer": answer, "seconds": seconds}


async def ask_without_tools(question, model, verbose=True):
    """Ollama only: the same question sent to the model with NO MCP tools.

    This is the baseline the professor asked for, to show how the model answers
    without our NoSQL MCP. It does not contact the MCP server or the Redis API,
    so these runs are not counted in the monitoring statistics.
    Returns the same dictionary shape as ask(), with an empty tool_calls list.
    """
    ollama = AsyncClient()

    if verbose:
        print("Model:", model)
        print("Tools available: none (Ollama only)")
        print("Question:", question)
        print()

    start = time.time()
    response = await ollama.chat(
        model=model,
        messages=[{"role": "user", "content": question}],
        think=False,
    )
    seconds = time.time() - start

    answer = response.message.content or ""
    if "</think>" in answer:
        answer = answer.split("</think>")[-1].strip()

    if verbose:
        print("Answer:", answer)
        print()
        print(f"Time: {seconds:.1f} seconds")

    return {"tool_calls": [], "answer": answer, "seconds": seconds}


if __name__ == "__main__":
    # add --no-tools anywhere to ask Ollama only, without the MCP tools
    no_tools = "--no-tools" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--no-tools"]
    if not args:
        print('Usage: python ollama_client.py "your question" [model] [--no-tools]')
        sys.exit(1)

    question = args[0]
    model = args[1] if len(args) > 1 else MODEL
    if no_tools:
        asyncio.run(ask_without_tools(question, model))
    else:
        asyncio.run(ask(question, model))
